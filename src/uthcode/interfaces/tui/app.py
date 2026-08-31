"""Inline prompt_toolkit adapter for the UthCode Application API."""

from __future__ import annotations

import asyncio
import shlex
import sys
import time
from collections.abc import Awaitable
from dataclasses import dataclass

from prompt_toolkit.application import Application, in_terminal
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.document import Document
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import StyleAndTextTuples
from prompt_toolkit.input.base import Input
from prompt_toolkit.input.ansi_escape_sequences import ANSI_SEQUENCES
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout import (
    BufferControl,
    ConditionalContainer,
    Dimension,
    HSplit,
    Layout,
    VSplit,
    Window,
)
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.output import Output
from prompt_toolkit.styles import Style
from prompt_toolkit.utils import get_cwidth

from uthcode.application import (
    AgentEvent,
    AgentRun,
    BehaviorMode,
    BehaviorModeSelected,
    ClearTranscript,
    CommandDefinition,
    CommandDispatcher,
    CommandInvocation,
    CommandOutcome,
    CommandParser,
    CompletionEngine,
    ModelSelected,
    OpenPermissionPicker,
    OpenModelPicker,
    OpenSessionPicker,
    PermissionMode,
    PermissionModeSelected,
    QuitInterface,
    SessionChanged,
    TurnHandle,
    UthCodeApplication,
    create_builtin_registry,
    failure_message as project_failure_message,
)

from .completion import CompletionMenuItem, CompletionMenuState
from .interaction import InteractionMode, PlanReviewAction, TuiInteractionState
from .picker import ModelPickerState, PermissionPickerState, SessionPickerState
from .rendering import (
    AgentEventRenderer,
    MarkdownStream,
    RenderBatch,
    context_usage_ring,
)
from .state import EscArmState, previous_grapheme_length
from .terminal import (
    CLEAR_VIEWPORT,
    KITTY_KEYBOARD_OFF,
    KITTY_KEYBOARD_ON,
    PALETTE,
    RichTerminalRenderer,
    SYNCHRONIZED_OUTPUT_OFF,
    SYNCHRONIZED_OUTPUT_ON,
)
from .windows_input import create_windows_unicode_input


@dataclass(slots=True)
class _StreamProjection:
    stream: MarkdownStream
    kind: str
    block_id: str = ""
    started: bool = False
    open: bool = False
    authoritative: bool = False


def _install_modified_enter_sequences() -> None:
    """Teach prompt_toolkit the Kitty sequences needed by chat editors."""

    ANSI_SEQUENCES.setdefault("\x1b[13u", Keys.ControlM)
    ANSI_SEQUENCES.setdefault("\x1b[13;2u", Keys.ControlJ)
    ANSI_SEQUENCES.setdefault("\x1b[27u", Keys.Escape)
    ANSI_SEQUENCES.setdefault("\x1b[127u", Keys.Backspace)


class UthCodeTUI:
    """A main-buffer chat TUI with prompt_toolkit-owned input and layout."""

    def __init__(
        self,
        application: UthCodeApplication,
        *,
        input_device: Input | None = None,
        terminal_output: Output | None = None,
    ) -> None:
        if input_device is None and sys.platform == "win32":
            input_device = create_windows_unicode_input()
            self._uses_kitty_keyboard = False
        else:
            self._uses_kitty_keyboard = True
            _install_modified_enter_sequences()
        self.application = application
        self._run: AgentRun = application.create_run()
        self.registry = create_builtin_registry()
        self.parser = CommandParser(self.registry)
        self.dispatcher = CommandDispatcher(self.registry, application)
        self.completion = CompletionMenuState()
        self.picker = ModelPickerState()
        self.permission_picker = PermissionPickerState()
        self.session_picker = SessionPickerState()
        self.interaction = TuiInteractionState()
        self.buffer = Buffer(
            multiline=True,
            on_text_changed=lambda _buffer: self._on_buffer_changed(),
        )
        self.activity = "ready"
        self._active_handle: TurnHandle | None = None
        self._generation_task: asyncio.Task[None] | None = None
        self._closing = False
        self._exit_code = 0
        self._esc = EscArmState()
        self._picker_draft: Document | None = None
        # Keep one append-only list in provider/event order.  A mapping keyed
        # by message kind would regroup interleaved reasoning and assistant
        # blocks and make the permanent scrollback chronology unknowable.
        self._streams: list[_StreamProjection] = []
        self._background_tasks: set[asyncio.Task[object]] = set()
        self._emit_lock = asyncio.Lock()
        self._renderer = RichTerminalRenderer()
        self._bindings = self._build_bindings()
        self._buffer_control = BufferControl(
            buffer=self.buffer,
            focusable=True,
        )
        self._preview_window = Window(
            FormattedTextControl(self._preview_fragments),
            height=lambda: Dimension(max=self._preview_height()),
            wrap_lines=True,
            style="class:preview",
        )
        self._candidate_window = Window(
            FormattedTextControl(self._candidate_fragments),
            height=lambda: Dimension(max=self._candidate_height()),
            wrap_lines=False,
            style="class:candidates",
        )
        composer_height = lambda: Dimension.exact(self._composer_height())
        self._composer = VSplit(
            [
                Window(
                    FormattedTextControl([("class:prompt", "  › ")]),
                    width=4,
                    height=composer_height,
                    dont_extend_width=True,
                    style="class:composer",
                ),
                Window(
                    self._buffer_control,
                    height=composer_height,
                    wrap_lines=True,
                    style="class:composer",
                ),
            ]
        )
        self.ui = Application[None](
            layout=Layout(self._build_layout(), focused_element=self._buffer_control),
            key_bindings=self._bindings,
            style=self._style(),
            full_screen=False,
            mouse_support=False,
            erase_when_done=False,
            paste_mode=False,
            min_redraw_interval=0.016,
            terminal_size_polling_interval=0.25,
            input=input_device,
            output=terminal_output,
        )
        # Escape is also the prefix of modified terminal sequences.  Keep the
        # ambiguity window short enough for a standalone picker/menu Escape to
        # feel immediate while still allowing an Escape/Escape pause gesture.
        self.ui.timeoutlen = 0.15

    def run(self) -> int:
        return asyncio.run(self.run_async())

    async def run_async(self) -> int:
        try:
            await self.ui.run_async(
                pre_run=lambda: self._spawn(self._show_startup())
            )
        except (EOFError, KeyboardInterrupt):
            self._closing = True
        except Exception:
            await self._emit(self._renderer.system(
                "界面输入错误；终端状态已恢复",
                error=True,
            ))
            self._closing = True
            self._exit_code = 1
        finally:
            await self.shutdown()
            if self._uses_kitty_keyboard:
                self._write(KITTY_KEYBOARD_OFF)
        return self._exit_code

    async def _show_startup(self) -> None:
        self._sync_renderer_width()
        await self._emit(
            CLEAR_VIEWPORT
            + (KITTY_KEYBOARD_ON if self._uses_kitty_keyboard else "")
            + self._renderer.welcome(
                self.application.current_model_ref,
                str(self.application.runtime_context.workdir),
            )
        )

    async def shutdown(self) -> None:
        handle = self._active_handle
        self._closing = True
        if handle is not None:
            handle.cancel()
        task = self._generation_task
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        if handle is not None:
            await handle.result()
        pending = tuple(task for task in self._background_tasks if not task.done())
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        self.application.close()

    def _application_completion(self, text: str) -> tuple[CompletionMenuItem, ...]:
        engine = CompletionEngine(self.registry, self.application)
        stripped = text.lstrip()
        if not stripped.startswith("/"):
            return ()
        body = stripped[1:]
        name_end = 0
        while name_end < len(body) and not body[name_end].isspace():
            name_end += 1
        if name_end == len(body):
            return tuple(
                CompletionMenuItem.from_command(candidate)
                for candidate in engine.complete(text)
            )
        invocation = self.parser.parse(text)
        definition = invocation.definition
        if definition is None or not definition.arguments:
            return ()
        argument_text = body[name_end:]
        partial, argument_index, replacement_start = self._argument_context(
            argument_text, invocation
        )
        values = engine.argument_candidates(invocation, argument_index=argument_index)
        return tuple(
            CompletionMenuItem(
                value=f"/{definition.canonical}{argument_text[:replacement_start]}{value}",
                display=self._argument_display(definition, argument_index, value),
            )
            for value in values
            if str(value).casefold().startswith(partial.casefold())
        )

    @staticmethod
    def _argument_display(
        definition: CommandDefinition,
        index: int,
        value: str,
    ) -> str:
        arguments = definition.arguments
        if index >= len(arguments):
            return str(value)
        description = arguments[index].description
        return f"{value} — {description}" if description else str(value)

    @staticmethod
    def _argument_context(
        argument_text: str,
        invocation: CommandInvocation,
    ) -> tuple[str, int, int]:
        trimmed = argument_text.rstrip()
        if len(trimmed) != len(argument_text):
            return "", len(invocation.args), len(argument_text)
        token_start = max(
            (index + 1 for index, char in enumerate(trimmed) if char.isspace()),
            default=0,
        )
        try:
            completed = len(shlex.split(trimmed[:token_start], posix=True))
        except ValueError:
            completed = max(len(invocation.args) - 1, 0)
        return trimmed[token_start:], completed, token_start

    def _build_layout(self) -> HSplit:
        preview = ConditionalContainer(
            self._preview_window,
            filter=Condition(self._has_preview),
        )
        candidates = ConditionalContainer(
            self._candidate_window,
            filter=Condition(self._has_candidates),
        )
        filler = Window()
        separator = Window(
            FormattedTextControl(self._separator_fragments),
            height=1,
            dont_extend_height=True,
        )
        status = Window(
            FormattedTextControl(self._status_fragments),
            height=1,
            dont_extend_height=True,
            style="class:status",
        )
        return HSplit(
            [filler, preview, candidates, separator, self._composer, status]
        )

    def _separator_fragments(self) -> StyleAndTextTuples:
        columns, _rows = self._terminal_size()
        style = (
            "class:separator.plan"
            if self._run.behavior_mode is BehaviorMode.PLAN
            else "class:separator"
        )
        return [(style, "─" * columns)]

    def _status_fragments(self) -> StyleAndTextTuples:
        permission_style = (
            "class:status.warning"
            if self._run.permission_mode is PermissionMode.FULL_ACCESS
            else "class:status"
        )
        usage = self.application.context_usage()
        ring_style, ring_text = context_usage_ring(usage)
        columns, _rows = self._terminal_size()
        if columns < 48:
            # Preserve a useful dynamic-limit signal in narrow terminals
            # while leaving the main input buffer and its prompt untouched.
            return [
                (ring_style, f" {ring_text} | "),
                (permission_style, f"permission: {self._run.permission_mode.value}"),
            ]
        return [
            ("class:status", f" {self.activity} | {self.application.current_model_ref} | "),
            ("class:status", f"mode: {self._run.behavior_mode.value} | "),
            (permission_style, f"permission: {self._run.permission_mode.value}"),
            ("class:status", f" | {ring_text} | {self.application.runtime_context.workdir} "),
        ]

    def _preview_fragments(self) -> StyleAndTextTuples:
        columns, _rows = self._terminal_size()
        pending = _tail_for_preview(
            self._pending_text(),
            width=max(1, columns - 2),
            height=self._preview_height(),
        )
        return [
            (
                "class:preview.reasoning.role"
                if self._latest_preview_kind() == "reasoning"
                else "class:preview.role",
                (
                    "┃ UthCode · reasoning:\n"
                    if self._latest_preview_kind() == "reasoning"
                    else "┃ UthCode:\n"
                ),
            ),
            (
                "class:preview.reasoning"
                if self._latest_preview_kind() == "reasoning"
                else "class:preview",
                pending,
            ),
        ]

    def _candidate_fragments(self) -> StyleAndTextTuples:
        if self.interaction.open:
            return list(self.interaction.render_lines())
        if self.completion.open:
            items = self.completion.candidates
            selected = self.completion.selected_index
            height = self._candidate_height()
            start = _window_start(selected, len(items), height)
            rows: StyleAndTextTuples = []
            for index in range(start, min(len(items), start + height)):
                marker = "›" if index == selected else " "
                style = "class:candidate.selected" if index == selected else "class:candidate"
                rows.append((style, f"{marker} {items[index].display}\n"))
            return rows
        if self.permission_picker.open:
            rows = []
            for index, mode in enumerate(self.permission_picker.modes):
                marker = "›" if index == self.permission_picker.selected_index else " "
                current = " · current" if mode is self.permission_picker.current_mode else ""
                style = "class:candidate.selected" if index == self.permission_picker.selected_index else "class:candidate"
                rows.append((style, f"{marker} {mode.value}{current}\n"))
            warning = self.permission_picker.warning
            if warning is not None:
                rows.append(("class:interaction.hint", f"{warning}\n"))
            return rows
        if self.session_picker.open:
            items = self.session_picker.page_items
            columns, _rows = self._terminal_size()
            height = self._candidate_height()
            rows: StyleAndTextTuples = [
                (
                    "class:interaction.hint",
                    f"Session {self.session_picker.page + 1}/{self.session_picker.page_count} · "
                    "↑/↓ select · ←/→ page · Enter resume · Esc back\n",
                )
            ]
            visible = max(0, height - 1)
            for index, entry in enumerate(items[:visible]):
                session_id = str(getattr(entry, "session_id", "unknown"))
                last_used = str(getattr(entry, "last_used_at", "unknown"))
                title = str(getattr(entry, "title", "") or "").strip()
                display_width = max(12, columns - len(session_id) - 24)
                preview = _bounded_display_text(
                    str(getattr(entry, "preview", "")),
                    width=display_width,
                )
                label = (
                    _bounded_display_text(title, width=display_width)
                    if title
                    else preview
                )
                marker = "›" if index == self.session_picker.selected_index else " "
                style = (
                    "class:candidate.selected"
                    if index == self.session_picker.selected_index
                    else "class:candidate"
                )
                rows.append(
                    (
                        style,
                        f"{marker} {session_id} · {last_used} · {label}\n",
                    )
                )
            return rows
        items = self.picker.models
        selected = self.picker.selected_index
        height = self._candidate_height()
        start = _window_start(selected, len(items), height)
        rows = []
        for index in range(start, min(len(items), start + height)):
            model = items[index]
            ref = model.model_ref
            label = model.display_name or ref
            current = " · current" if ref == self.picker.current_model_ref else ""
            marker = "›" if index == selected else " "
            style = "class:candidate.selected" if index == selected else "class:candidate"
            rows.append((style, f"{marker} {ref} — {label}{current}\n"))
        return rows

    def _build_bindings(self) -> KeyBindings:
        bindings = KeyBindings()
        completion_open = Condition(lambda: self.completion.open)
        picker_open = Condition(lambda: self.picker.open)
        permission_picker_open = Condition(lambda: self.permission_picker.open)
        session_picker_open = Condition(lambda: self.session_picker.open)
        menu_open = (
            completion_open
            | picker_open
            | permission_picker_open
            | session_picker_open
        )

        @bindings.add(Keys.ControlM, eager=True)
        def _submit(event: object) -> None:
            del event
            if self.interaction.open:
                self._submit_interaction()
            elif self.completion.open:
                self._execute_selected_command()
            elif self.picker.open:
                self._select_picker_model()
            elif self.permission_picker.open:
                self._select_permission_mode()
            elif self.session_picker.open:
                self._select_session()
            else:
                text = self.buffer.text
                if text.strip():
                    self.buffer.set_document(Document("", 0), bypass_readonly=True)
                    self._spawn(self._handle_submission(text))

        @bindings.add(Keys.ControlJ, eager=True)
        @bindings.add(Keys.Escape, Keys.ControlJ, eager=True)
        def _newline(event: object) -> None:
            del event
            if self.interaction.open:
                if not self.interaction.is_select:
                    self.buffer.insert_text("\n")
            elif not menu_open():
                self.buffer.insert_text("\n")

        interaction_open = Condition(lambda: self.interaction.open)

        @bindings.add(Keys.Up, filter=interaction_open, eager=True)
        def _interaction_up(event: object) -> None:
            del event
            self.interaction.move(-1)
            self._invalidate()

        @bindings.add(Keys.Down, filter=interaction_open, eager=True)
        def _interaction_down(event: object) -> None:
            del event
            self.interaction.move(1)
            self._invalidate()

        @bindings.add(Keys.Left, filter=interaction_open, eager=True)
        def _interaction_left(event: object) -> None:
            del event
            if self.interaction.previous_question():
                self._sync_interaction_buffer()
            self._invalidate()

        @bindings.add(Keys.Right, filter=interaction_open, eager=True)
        def _interaction_right(event: object) -> None:
            del event
            if self.interaction.mode is InteractionMode.QUESTIONS:
                self._submit_interaction()

        @bindings.add(
            " ",
            filter=Condition(lambda: self.interaction.open and self.interaction.is_select),
            eager=True,
        )
        def _interaction_space(event: object) -> None:
            del event
            self.interaction.toggle_option()
            self._invalidate()

        @bindings.add(
            Keys.Escape,
            Keys.Escape,
            filter=Condition(
                lambda: self._active_handle is not None
                and not self._active_handle.paused
                and not self.completion.open
                and not self.picker.open
                and not self.permission_picker.open
                and not self.session_picker.open
                and not self.interaction.open
            ),
            eager=True,
        )
        def _double_escape(event: object) -> None:
            del event
            self._esc.arm(time.monotonic())
            self._handle_generation_escape()

        @bindings.add(Keys.Backspace, eager=True)
        @bindings.add(Keys.ControlH, eager=True)
        def _backspace(event: object) -> None:
            del event
            if self.picker.open or self.permission_picker.open or self.session_picker.open:
                return
            before = self.buffer.text[: self.buffer.cursor_position]
            count = previous_grapheme_length(before)
            if count:
                self.buffer.delete_before_cursor(count=count)

        @bindings.add(Keys.Up, filter=menu_open, eager=True)
        def _menu_up(event: object) -> None:
            del event
            if self.completion.open:
                self.completion.move(-1)
            elif self.permission_picker.open:
                self.permission_picker.move(-1)
            elif self.session_picker.open:
                self.session_picker.move(-1)
            else:
                self.picker.move(-1)

        @bindings.add(Keys.Down, filter=menu_open, eager=True)
        def _menu_down(event: object) -> None:
            del event
            if self.completion.open:
                self.completion.move(1)
            elif self.permission_picker.open:
                self.permission_picker.move(1)
            elif self.session_picker.open:
                self.session_picker.move(1)
            else:
                self.picker.move(1)

        @bindings.add(Keys.Left, filter=session_picker_open, eager=True)
        def _session_previous_page(event: object) -> None:
            del event
            self.session_picker.previous_page()
            self._invalidate()

        @bindings.add(Keys.Right, filter=session_picker_open, eager=True)
        def _session_next_page(event: object) -> None:
            del event
            self.session_picker.next_page()
            self._invalidate()

        @bindings.add(Keys.Tab, eager=True)
        def _tab(event: object) -> None:
            del event
            if self.completion.open:
                self._complete_command()

        # Keep the single Escape binding non-eager so the root-level
        # Escape/Escape sequence can be recognized as one cooperative pause
        # gesture without stealing the first key from the sequence matcher.
        @bindings.add(Keys.Escape)
        def _escape(event: object) -> None:
            del event
            if self.completion.open:
                self.completion.close()
                self._reset_interaction_context()
            elif self.picker.open:
                self.picker.close()
                if self._picker_draft is not None:
                    self.buffer.set_document(self._picker_draft, bypass_readonly=True)
                self._picker_draft = None
                self._reset_interaction_context()
            elif self.permission_picker.open:
                self.permission_picker.close()
                self._reset_interaction_context()
            elif self.session_picker.open:
                self.session_picker.close()
                self._reset_interaction_context()
            elif self.interaction.open:
                self._handle_interaction_escape()
            elif self._active_handle is not None and self._active_handle.paused:
                self._open_pending_interaction()
            elif self._active_handle is not None:
                self._handle_generation_escape()

        @bindings.add(Keys.ControlC, eager=True)
        def _quit(event: object) -> None:
            del event
            self._closing = True
            self.ui.exit()

        return bindings

    def _on_buffer_changed(self) -> None:
        text = self.buffer.text
        if self.interaction.open:
            self.completion.close()
        elif (
            not self.picker.open
            and not self.permission_picker.open
            and not self.session_picker.open
            and text.lstrip().startswith("/")
        ):
            self.completion.replace(self._application_completion(text))
        else:
            self.completion.close()
        self._invalidate()

    async def _handle_submission(self, text: str) -> None:
        self.completion.close()
        if self.interaction.open:
            self._submit_interaction()
            return
        if (
            self._active_handle is not None
            and self._active_handle.pending_pause is not None
        ):
            self._open_pending_interaction()
            return
        if text.lstrip().startswith("/"):
            invocation = self.parser.parse(text)
            if invocation.is_bare_slash:
                self.buffer.set_document(Document("/", 1), bypass_readonly=True)
                return
            if self._active_handle is not None and invocation.canonical == "model":
                await self._show_error("生成进行中不能切换模型")
                return
            if self._active_handle is not None and invocation.canonical in {
                "compact",
                "new",
                "resume",
            }:
                await self._show_error(
                    f"生成进行中不能执行 /{invocation.canonical}"
                )
                return
            outcome = await self.dispatcher.dispatch_async(invocation)
            if outcome is not None:
                await self._apply_command_outcome(text, outcome)
            return
        if self._active_handle is not None:
            accepted = self._active_handle.steer(text)  # type: ignore[attr-defined]
            if not accepted:
                await self._show_error("当前请求暂不能接收任务更新")
                return
            self._sync_renderer_width()
            await self._emit(self._renderer.user_message(text))
            self.activity = "steering…"
            self._invalidate()
            return
        self._start_turn(text)

    async def _apply_command_outcome(
        self,
        text: str,
        outcome: CommandOutcome,
    ) -> None:
        self._sync_renderer_width()
        await self._emit(self._renderer.system(text))
        message = outcome.message
        if message:
            await self._emit(
                self._renderer.system(
                    str(message),
                    error=outcome.error is not None,
                )
            )
        action = outcome.ui_action
        if isinstance(action, ClearTranscript):
            await self._clear_viewport()
        elif isinstance(action, OpenModelPicker):
            self._picker_draft = Document(text, len(text))
            self.picker.replace(
                tuple(self.application.model_catalog()),
                self.application.current_model_ref,
            )
        elif isinstance(action, OpenPermissionPicker):
            self.permission_picker.replace(self._run.permission_mode)
        elif isinstance(action, OpenSessionPicker):
            catalog = getattr(self.application, "session_catalog", None)
            sessions = tuple(catalog()) if callable(catalog) else ()
            if not sessions:
                await self._show_error("没有可恢复的 Session")
            else:
                self.session_picker.replace(sessions)
        elif isinstance(action, QuitInterface):
            self._closing = True
            self.ui.exit()
        elif isinstance(action, ModelSelected):
            self.activity = f"model: {action.model_ref}"
        elif isinstance(action, PermissionModeSelected):
            self._run.set_permission_mode(action.mode)
            self.activity = f"permission: {action.mode.value}"
            if action.warning is not None:
                await self._emit(self._renderer.system(action.warning))
        elif isinstance(action, BehaviorModeSelected):
            if self._active_handle is not None:
                await self._show_error("生成进行中不能切换行为模式")
            else:
                self._run.set_behavior_mode(action.mode)  # type: ignore[attr-defined]
                self.activity = f"mode: {action.mode.value}"
        elif isinstance(action, SessionChanged):
            self._run = self.application.create_run()
            self._reset_stream_projection()
            self.interaction.close()
            self.completion.close()
            self.picker.close()
            self.permission_picker.close()
            self.session_picker.close()
            self._picker_draft = None
            self.activity = (
                f"resumed: {action.session_id}"
                if action.restored
                else f"new session: {action.session_id}"
            )
            if action.restored:
                await self._hydrate_replay(action.replay)
        self._invalidate()

    def _start_turn(self, prompt: str) -> bool:
        ensure_session = getattr(self.application, "ensure_session", None)
        if callable(ensure_session):
            try:
                ensure_session()
            except Exception:
                self.activity = "error"
                self._spawn(self._show_error("无法创建 Session；可以继续输入"))
                return False
        self._reset_stream_projection()
        self.interaction.close()
        try:
            handle = self._run.start_turn(prompt)
        except Exception:
            self.activity = "error"
            self._spawn(self._show_error("无法开始请求；可以继续输入"))
            return False
        self._active_handle = handle
        self._esc.clear()
        self.activity = "generating"
        self._generation_task = asyncio.create_task(self._consume_turn(handle))
        self._invalidate()
        return True

    async def _consume_turn(self, handle: TurnHandle) -> None:
        renderer = AgentEventRenderer()
        terminal: str | None = None
        failure_message: str | None = None
        cancelled = False
        event_task: asyncio.Task[AgentEvent] | None = None
        try:
            events = handle.events().__aiter__()
            while True:
                event_task = asyncio.create_task(anext(events))
                while not event_task.done():
                    done, _pending = await asyncio.wait(
                        (event_task,),
                        timeout=renderer.interval_seconds,
                    )
                    if done:
                        break
                    batch = renderer.flush()
                    if batch.has_updates:
                        await self._apply_batch(batch)
                try:
                    event = event_task.result()
                except StopAsyncIteration:
                    event_task = None
                    break
                event_task = None
                if not isinstance(event, AgentEvent):
                    raise RuntimeError("Application returned an invalid AgentEvent")
                if event.event_type == "turn_pausing":
                    self.activity = "pausing…"
                    self._invalidate()
                    continue
                if event.event_type == "turn_paused":
                    pause = getattr(event, "pause", None)
                    if pause is not None:
                        self.interaction.open_pause(pause)
                        self._esc.clear()
                        self.activity = "paused"
                        self.buffer.set_document(Document("", 0), bypass_readonly=True)
                        self._invalidate()
                    continue
                if event.event_type == "turn_resumed":
                    self.interaction.close()
                    self._esc.clear()
                    self.activity = "generating"
                    self._invalidate()
                    continue
                batch = renderer.push(event)
                if batch is not None:
                    await self._apply_batch(batch)
                    terminal = batch.terminal or terminal

            if terminal is None and not self._closing:
                await self._flush_streams()
                self.activity = "ready"
        except asyncio.CancelledError:
            cancelled = True
        except Exception:
            failure_message = project_failure_message(None)
        finally:
            if event_task is not None:
                event_task.cancel()
                await asyncio.gather(event_task, return_exceptions=True)
            try:
                if not self._closing:
                    if cancelled:
                        await self._finish_consumer_output(
                            renderer,
                            discard_assistant=True,
                        )
                        self.activity = "cancelled"
                    elif failure_message is not None:
                        await self._finish_consumer_output(
                            renderer,
                            error_message=failure_message,
                            discard_assistant=True,
                        )
            finally:
                if failure_message is not None or (cancelled and not self._closing):
                    handle.cancel()
                await handle.result()
                if self._active_handle is handle:
                    self._active_handle = None
                self.interaction.close()
                self._generation_task = None
                self._esc.clear()
                self._invalidate()

    async def _finish_consumer_output(
        self,
        renderer: AgentEventRenderer,
        *,
        error_message: str | None = None,
        discard_assistant: bool = False,
    ) -> None:
        """Best-effort UI closure that never owns Application Turn cleanup."""

        try:
            await self._apply_batch(renderer.flush())
        except Exception:
            pass
        try:
            await self._flush_streams(discard_assistant=discard_assistant)
        except Exception:
            pass
        if error_message is not None:
            try:
                await self._show_error(error_message)
            except Exception:
                pass

    async def _apply_batch(self, batch: RenderBatch) -> None:
        self._sync_renderer_width()
        if batch.activity is not None:
            self.activity = batch.activity
        writes: list[str] = []
        if batch.operations:
            for operation in batch.operations:
                if operation.kind == "user":
                    _message_id, text = operation.value  # type: ignore[misc]
                    writes.append(self._renderer.user_message(text))
                elif operation.kind == "plan":
                    update = operation.value
                    writes.append(
                        self._renderer.plan_message(
                            update.text, revision=update.revision  # type: ignore[union-attr]
                        )
                    )
                elif operation.kind == "task_state":
                    update = operation.value
                    writes.append(self._renderer.task_state(update.items))  # type: ignore[union-attr]
                elif operation.kind == "text":
                    self._apply_text_update(operation.value, writes)  # type: ignore[arg-type]
                elif operation.kind == "tool":
                    update = operation.value
                    self._apply_tool_update(update, writes)  # type: ignore[arg-type]
                elif operation.kind == "terminal":
                    self._apply_terminal_update(batch, writes)
        else:
            # Keep direct RenderBatch construction useful for local callers
            # while all AgentEventRenderer output uses the ordered path above.
            for _message_id, text in batch.users:
                writes.append(self._renderer.user_message(text))
            for update in batch.plans:
                writes.append(
                    self._renderer.plan_message(update.text, revision=update.revision)
                )
            for update in batch.task_states:
                writes.append(self._renderer.task_state(update.items))
            for update in batch.text:
                self._apply_text_update(update, writes)
            if batch.tools:
                for update in batch.tools:
                    self._apply_tool_update(update, writes)
            if batch.terminal is not None:
                self._apply_terminal_update(batch, writes)
        output = "".join(writes)
        if output:
            await self._emit(output)
        self._invalidate()

    def _stream_projection(
        self,
        block_id: str,
        kind: str,
    ) -> _StreamProjection:
        for projection in self._streams:
            if projection.block_id == block_id:
                return projection
        projection = _StreamProjection(
            MarkdownStream(),
            kind,
            block_id=block_id,
        )
        self._streams.append(projection)
        return projection

    def _apply_text_update(self, update: object, writes: list[str]) -> None:
        block_id = str(getattr(update, "block_id"))
        kind = str(getattr(update, "kind"))
        text = str(getattr(update, "text"))
        mode = str(getattr(update, "mode", "append"))
        authoritative = bool(getattr(update, "authoritative", False))
        projection = self._stream_projection(block_id, kind)
        stream = projection.stream

        if kind == "assistant" and not authoritative:
            if mode == "replace":
                if projection.started and stream.committed:
                    writes.append(self._renderer.correction(text))
                    stream.committed = text
                    stream.pending = ""
                else:
                    stream.pending = text
            else:
                stream.pending += text
            return

        if authoritative:
            if kind == "assistant":
                forced = self._force_reasoning_before(projection)
                if forced:
                    writes.append(forced)
            if projection.authoritative:
                if stream.committed != text:
                    writes.append(self._renderer.correction(text))
                    stream.committed = text
                stream.pending = ""
                return
            if stream.committed and stream.committed != text:
                writes.append(self._renderer.correction(text))
            elif not stream.committed and text:
                writes.append(self._render_stream_block(block_id, text))
            stream.committed = text
            stream.pending = ""
            projection.authoritative = True
            return

        if mode == "replace":
            commits, corrected = stream.replace(text)
            if corrected:
                if not projection.started:
                    stream.committed = ""
                    stream.pending = text
                    commits = ()
                else:
                    writes.append(self._renderer.correction(text))
                    stream.committed = text
                    stream.pending = ""
        else:
            commits = stream.append(text)
        for block in commits:
            writes.append(self._render_stream_block(block_id, block))

    def _force_reasoning_before(self, projection: _StreamProjection) -> str:
        """Close earlier reasoning previews before an assistant authority."""

        writes: list[str] = []
        for candidate in self._streams:
            if candidate is projection:
                break
            if candidate.kind != "reasoning":
                continue
            tail = candidate.stream.force()
            if tail:
                writes.append(self._render_stream_block(candidate.block_id, tail))
        return "".join(writes)

    def _render_forced_reasoning(self) -> str:
        """Commit only reasoning tails at a Tool or failed-turn boundary."""

        writes: list[str] = []
        for projection in self._streams:
            if projection.kind != "reasoning":
                continue
            tail = projection.stream.force()
            if tail:
                writes.append(self._render_stream_block(projection.block_id, tail))
        if any(
            projection.kind == "reasoning" and projection.open
            for projection in self._streams
        ):
            writes.append("\n")
            for projection in self._streams:
                if projection.kind == "reasoning":
                    projection.open = False
        return "".join(writes)

    def _discard_assistant_previews(self) -> None:
        """Drop non-authoritative assistant tails without writing scrollback."""

        for projection in self._streams:
            if projection.kind == "assistant":
                projection.stream.pending = ""
                projection.open = False

    def _apply_tool_update(self, update: object, writes: list[str]) -> None:
        status = str(getattr(update, "status"))
        tool_name = str(getattr(update, "tool_name"))
        command = str(getattr(update, "command"))
        forced = self._render_forced_reasoning()
        if status == "running":
            if forced:
                writes.append(forced)
            self.activity = f"running {tool_name}: {command}"
            return
        writes.append(
            forced
            + self._renderer.tool(
                status=status,
                name=tool_name,
                command=command,
            )
        )

    def _apply_terminal_update(self, batch: RenderBatch, writes: list[str]) -> None:
        terminal = batch.terminal
        if terminal == "completed":
            writes.append(
                self._render_forced_streams(
                    final_text=batch.final_text,
                )
            )
            self.activity = "ready"
        else:
            writes.append(self._render_forced_reasoning())
            self._discard_assistant_previews()
            if terminal == "cancelled":
                self.activity = "cancelled"
                return
            writes.append(
                self._renderer.system(
                    batch.terminal_message or project_failure_message(None),
                    error=True,
                )
            )
            self.activity = "error"

    def _render_stream_block(self, block_id: str, text: str) -> str:
        projection = self._stream_projection(block_id, "assistant")
        if projection.kind == "reasoning":
            rendered = self._renderer.reasoning_message(
                text,
                show_role=not projection.started,
                trailing_blank=False,
            )
        else:
            rendered = self._renderer.agent_message(
                text,
                show_role=not projection.started,
                trailing_blank=False,
            )
        projection.started = True
        projection.open = True
        return rendered

    def _render_forced_streams(self, *, final_text: str | None = None) -> str:
        writes: list[str] = []
        latest_assistant = next(
            (
                projection
                for projection in reversed(self._streams)
                if projection.kind == "assistant"
            ),
            None,
        )
        for projection in self._streams:
            if projection is latest_assistant and final_text is not None:
                continue
            tail = projection.stream.force()
            if tail:
                writes.append(self._render_stream_block(projection.block_id, tail))
        if final_text is not None:
            if latest_assistant is None:
                latest_assistant = self._stream_projection(
                    "assistant:terminal",
                    "assistant",
                )
            if latest_assistant.authoritative:
                if latest_assistant.stream.committed != final_text:
                    writes.append(self._renderer.correction(final_text))
            else:
                current = latest_assistant.stream.committed
                latest_assistant.stream.pending = ""
                if current and current != final_text:
                    writes.append(self._renderer.correction(final_text))
                elif not current and final_text:
                    writes.append(
                        self._render_stream_block(
                            latest_assistant.block_id,
                            final_text,
                        )
                    )
                latest_assistant.stream.committed = final_text
                latest_assistant.authoritative = True
        if any(projection.open for projection in self._streams):
            writes.append("\n")
            for projection in self._streams:
                projection.open = False
        return "".join(writes)

    async def _flush_streams(
        self,
        *,
        final_text: str | None = None,
        discard_assistant: bool = False,
    ) -> None:
        if discard_assistant:
            output = self._render_forced_reasoning()
            self._discard_assistant_previews()
        else:
            output = self._render_forced_streams(final_text=final_text)
        if output:
            await self._emit(output)

    def _handle_generation_escape(self) -> None:
        now = time.monotonic()
        if self._esc.consume(now):
            assert self._active_handle is not None
            if self._active_handle.pause():
                self.activity = "pausing…"
            else:
                self.activity = "generating"
        else:
            self._esc.arm(now)
            self.activity = "再次按 Esc 暂停当前生成"
        self._invalidate()

    def _open_pending_interaction(self) -> None:
        handle = self._active_handle
        pause = handle.pending_pause if handle is not None else None
        if pause is None:
            return
        self.interaction.open_pause(pause)
        self._esc.clear()
        self._invalidate()

    def _reset_interaction_context(self) -> None:
        self._esc.clear()
        self._invalidate()

    def _sync_interaction_buffer(self) -> None:
        question = self.interaction.current_question
        value = ""
        if self.interaction.mode is InteractionMode.PLAN_REVISION:
            value = self.interaction.draft
        elif question is not None and (
            question.kind.value == "text" or self.interaction.free_text_mode
        ):
            value = self.interaction.draft
        self.buffer.set_document(
            Document(value, len(value)),
            bypass_readonly=True,
        )

    def _handle_interaction_escape(self) -> None:
        if self.interaction.mode is InteractionMode.PLAN_REVISION:
            self.interaction.mode = InteractionMode.PLAN_REVIEW
            self.interaction.set_draft("")
            self.buffer.set_document(Document("", 0), bypass_readonly=True)
        elif (
            self.interaction.mode is InteractionMode.QUESTIONS
            and self.interaction.free_text_mode
        ):
            self.interaction.exit_free_text()
            self._sync_interaction_buffer()
        elif self.interaction.previous_question():
            self._sync_interaction_buffer()
        else:
            # Esc only closes the temporary layer.  It never submits an empty
            # answer and never cancels a pending Turn.
            self.interaction.close()
            self.activity = "paused"
            self.buffer.set_document(Document("", 0), bypass_readonly=True)
        self._reset_interaction_context()

    def _submit_interaction(self) -> None:
        handle = self._active_handle
        if handle is None or not self.interaction.open:
            return
        if self.interaction.mode is InteractionMode.PLAN_REVIEW:
            action = self.interaction.selected_plan_review_action
            if action is PlanReviewAction.CANCEL:
                handle.cancel()
                self.interaction.close()
                self.activity = "cancelling"
            elif action is PlanReviewAction.REVISE:
                if self.interaction.begin_plan_revision():
                    self.buffer.set_document(Document("", 0), bypass_readonly=True)
                    self.activity = "revising plan"
            else:
                response = self.interaction.plan_review_response()
                if response is not None and handle.resume(response):
                    self.interaction.close()
                    self.activity = "resuming"
            self._reset_interaction_context()
            return

        if self.interaction.mode is InteractionMode.PLAN_REVISION:
            self.interaction.set_draft(self.buffer.text)
            response = self.interaction.plan_review_response()
            if response is not None and handle.resume(response):
                self.interaction.close()
                self.buffer.set_document(Document("", 0), bypass_readonly=True)
                self.activity = "resuming"
                self._reset_interaction_context()
            return
        if self.interaction.mode is InteractionMode.PAUSE_ACTION:
            action = self.interaction.confirm_action()
            if action is None:
                return
            if action.value == "cancel":
                handle.cancel()
                self.interaction.close()
                self.activity = "cancelling"
            else:
                response = self.interaction.response_for_action()
                if response is not None and handle.resume(response):
                    self.interaction.close()
                    self.activity = "resuming"
            self._reset_interaction_context()
            return

        if self.interaction.mode is InteractionMode.PERMISSION:
            response = self.interaction.permission_response()
            if response is not None and handle.resume(response):
                self.interaction.close()
                self.activity = "resuming"
                self._reset_interaction_context()
            return

        if self.interaction.mode is InteractionMode.REVIEW:
            response = self.interaction.user_input_response()
            if response is not None and handle.resume(response):
                self.interaction.close()
                self.buffer.set_document(Document("", 0), bypass_readonly=True)
                self.activity = "resuming"
                self._reset_interaction_context()
            return

        question = self.interaction.current_question
        if question is None:
            return
        typed = self.buffer.text.strip()
        if question.kind.value != "text" and typed:
            if typed in self.interaction.current_options:
                self.interaction.selected_options = {
                    self.interaction.current_options.index(typed)
                }
                self.interaction.free_text_mode = False
                self.interaction.set_draft("")
            else:
                self.interaction.choose_free_text()
                self.interaction.set_draft(typed)
        else:
            self.interaction.set_draft(self.buffer.text)
        if self.interaction.submit_current():
            self.buffer.set_document(Document("", 0), bypass_readonly=True)
            self._invalidate()

    def _complete_command(self) -> None:
        selected = self.completion.selected
        if selected is not None:
            self.buffer.set_document(
                Document(selected.value, len(selected.value)),
                bypass_readonly=True,
            )
        self.completion.close()

    def _execute_selected_command(self) -> None:
        selected = self.completion.selected
        self.completion.close()
        if selected is not None:
            self.buffer.set_document(Document("", 0), bypass_readonly=True)
            self._spawn(self._handle_submission(selected.value))

    def _select_picker_model(self) -> None:
        model = self.picker.selected
        self.picker.close()
        self._picker_draft = None
        if model is not None:
            self._spawn(
                self._handle_submission(f"/model {model.model_ref}")
            )

    def _select_permission_mode(self) -> None:
        mode = self.permission_picker.selected
        self.permission_picker.close()
        self._spawn(self._handle_submission(f"/permission {mode.value}"))
        self._reset_interaction_context()

    def _select_session(self) -> None:
        entry = self.session_picker.selected
        self.session_picker.close()
        if entry is not None:
            session_id = str(getattr(entry, "session_id", ""))
            if session_id:
                self._spawn(self._handle_submission(f"/resume {session_id}"))
        self._reset_interaction_context()

    async def _clear_viewport(self) -> None:
        self._reset_stream_projection()
        self._sync_renderer_width()
        await self._emit(
            CLEAR_VIEWPORT + self._renderer.system(
                "──────── 新视图；上方终端历史仍保留 ────────"
            )
        )
        self.activity = "ready"

    def _reset_stream_projection(self) -> None:
        self._streams.clear()

    async def _show_error(self, text: str) -> None:
        self._sync_renderer_width()
        await self._emit(self._renderer.system(text, error=True))
        self.activity = "error"
        self._invalidate()

    async def _emit(self, value: str) -> None:
        async with self._emit_lock:
            if self.ui.is_running:
                self._write(SYNCHRONIZED_OUTPUT_ON)
                try:
                    async with in_terminal(render_cli_done=False):
                        self._write(value)
                finally:
                    self._write(SYNCHRONIZED_OUTPUT_OFF)
            else:
                self._write(value)

    def _spawn(self, awaitable: Awaitable[object]) -> None:
        task = asyncio.create_task(self._run_background(awaitable))
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def _run_background(self, awaitable: Awaitable[object]) -> None:
        try:
            await awaitable
        except asyncio.CancelledError:
            raise
        except Exception:
            await self._show_error("界面操作失败；可以继续输入")

    def _has_preview(self) -> bool:
        return bool(self._pending_text()) and self._preview_height() > 0

    def _has_candidates(self) -> bool:
        return (
            self.completion.open
            or self.picker.open
            or self.permission_picker.open
            or self.session_picker.open
            or self.interaction.open
        ) and self._candidate_height() > 0

    def _pending_text(self) -> str:
        for projection in reversed(self._streams):
            if projection.stream.pending:
                return projection.stream.pending
        return ""

    def _latest_preview_kind(self) -> str | None:
        for projection in reversed(self._streams):
            if projection.stream.pending:
                return projection.kind
        return None

    async def _hydrate_replay(self, records: object) -> None:
        """Append safe Application replay records in bounded UI batches."""

        values = tuple(records)  # type: ignore[arg-type]
        allowed = {"user", "steering", "reasoning", "assistant", "tool"}
        if any(getattr(record, "kind", None) not in allowed for record in values):
            raise ValueError("Application returned an invalid Session replay record")
        batch_size = 32
        for start in range(0, len(values), batch_size):
            self._sync_renderer_width()
            writes: list[str] = []
            for record in values[start : start + batch_size]:
                kind = str(getattr(record, "kind"))
                text = str(getattr(record, "text", ""))
                if kind == "user":
                    writes.append(self._renderer.user_message(text))
                elif kind == "steering":
                    writes.append(self._renderer.user_message(text, role="you · steering"))
                elif kind == "reasoning":
                    writes.append(self._renderer.reasoning_message(text))
                elif kind == "assistant":
                    writes.append(self._renderer.agent_message(text))
                else:
                    writes.append(
                        self._renderer.tool(
                            status=str(getattr(record, "status", None) or "finished"),
                            name=str(getattr(record, "tool_name", None) or "unknown tool"),
                            command=text or "<tool summary unavailable>",
                        )
                    )
            if writes:
                await self._emit("".join(writes))
            if start + batch_size < len(values):
                await self._yield_replay()

    async def _yield_replay(self) -> None:
        await asyncio.sleep(0)

    def _terminal_size(self) -> tuple[int, int]:
        try:
            size = self.ui.output.get_size()
            return max(20, size.columns), max(3, size.rows)
        except Exception:
            return 80, 24

    def _sync_renderer_width(self) -> None:
        columns, _rows = self._terminal_size()
        self._renderer.resize(columns)

    def _candidate_height(self) -> int:
        _columns, rows = self._terminal_size()
        available = rows - self._composer_height() - 2
        return max(0, min(8, available // 2))

    def _composer_height(self) -> int:
        columns, rows = self._terminal_size()
        content_width = max(1, columns - 4)
        visual_lines = sum(
            max(1, (get_cwidth(line) + content_width - 1) // content_width)
            for line in self.buffer.text.split("\n")
        )
        return max(1, min(10, max(3, visual_lines), rows - 2))

    def _preview_height(self) -> int:
        _columns, rows = self._terminal_size()
        candidate_height = (
            self._candidate_height()
            if (
                self.completion.open
                or self.picker.open
                or self.permission_picker.open
                or self.session_picker.open
                or self.interaction.open
            )
            else 0
        )
        occupied = self._composer_height() + candidate_height + 2
        return max(0, min(12, rows - occupied))

    def _style(self) -> Style:
        return Style.from_dict(
            {
                "prompt": f"bold {PALETTE.accent}",
                "composer": f"{PALETTE.text} bg:{PALETTE.input_background}",
                "status": PALETTE.muted,
                "status.warning": PALETTE.error,
                "preview": f"{PALETTE.text} bg:{PALETTE.input_background}",
                "preview.role": f"bold {PALETTE.success} bg:{PALETTE.input_background}",
                "preview.reasoning": (
                    f"{PALETTE.text} bg:{PALETTE.input_background}"
                ),
                "preview.reasoning.role": (
                    f"bold {PALETTE.reasoning_accent} bg:{PALETTE.input_background}"
                ),
                "candidates": f"{PALETTE.text} bg:{PALETTE.user_background}",
                "candidate": f"{PALETTE.text} bg:{PALETTE.user_background}",
                "candidate.selected": (
                    f"bold {PALETTE.input_background} bg:{PALETTE.accent}"
                ),
                "interaction.title": f"bold {PALETTE.accent} bg:{PALETTE.user_background}",
                "interaction.question": f"{PALETTE.text} bg:{PALETTE.user_background}",
                "interaction.hint": f"{PALETTE.muted} bg:{PALETTE.user_background}",
                "interaction.option": f"{PALETTE.text} bg:{PALETTE.user_background}",
                "separator": PALETTE.muted,
                "separator.plan": f"bold {PALETTE.plan_accent}",
                "interaction.plan.title": (
                    f"bold {PALETTE.plan_accent} bg:{PALETTE.plan_background}"
                ),
            }
        )

    def _invalidate(self) -> None:
        if hasattr(self, "ui") and self.ui.is_running:
            self.ui.invalidate()

    def _write(self, value: str) -> None:
        self.ui.output.write_raw(value)
        self.ui.output.flush()


def _bounded_display_text(text: str, *, width: int) -> str:
    """Keep Picker previews single-line and terminal-width bounded."""

    normalized = " ".join(text.split())
    if get_cwidth(normalized) <= width:
        return normalized
    if width <= 1:
        return "…"
    result = ""
    current_width = 0
    for character in normalized:
        character_width = max(0, get_cwidth(character))
        if current_width + character_width + get_cwidth("…") > width:
            break
        result += character
        current_width += character_width
    return result.rstrip() + "…"


def _window_start(selected: int, total: int, height: int) -> int:
    if total <= height:
        return 0
    return max(0, min(selected - height // 2, total - height))


def _tail_for_preview(text: str, *, width: int, height: int) -> str:
    if not text or height <= 0:
        return ""
    rows: list[str] = [""]
    cell_width = 0
    for character in text:
        if character == "\n":
            rows.append("")
            cell_width = 0
            continue
        character_width = max(0, get_cwidth(character))
        if cell_width and cell_width + character_width > width:
            rows.append("")
            cell_width = 0
        rows[-1] += character
        cell_width += character_width
    return "\n".join(rows[-height:])


def run_tui(application: UthCodeApplication) -> int:
    return UthCodeTUI(application).run()


__all__ = ["UthCodeTUI", "run_tui"]
