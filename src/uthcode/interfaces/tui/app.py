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
    ClearTranscript,
    CommandDefinition,
    CommandDispatcher,
    CommandInvocation,
    CommandOutcome,
    CommandParser,
    CompletionEngine,
    ModelSelected,
    OpenModelPicker,
    ProviderError,
    QuitInterface,
    TurnHandle,
    UthCodeApplication,
    create_builtin_registry,
)

from .completion import CompletionMenuItem, CompletionMenuState
from .picker import ModelPickerState
from .rendering import AgentEventRenderer, MarkdownStream, RenderBatch
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
    started: bool = False
    open: bool = False


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
        self._streams: dict[str, _StreamProjection] = {}
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

    def run(self) -> int:
        return asyncio.run(self.run_async())

    async def run_async(self) -> int:
        try:
            await self.ui.run_async(
                pre_run=lambda: self._spawn(self._show_startup())
            )
        except (EOFError, KeyboardInterrupt):
            self._closing = True
        except Exception as exc:
            await self._emit(self._renderer.system(
                f"界面输入错误：{type(exc).__name__}；终端状态已恢复",
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
        self._closing = True
        if self._active_handle is not None:
            self._active_handle.cancel()
        task = self._generation_task
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        pending = tuple(task for task in self._background_tasks if not task.done())
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

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
        return [("class:separator", "─" * columns)]

    def _status_fragments(self) -> StyleAndTextTuples:
        return [
            (
                "class:status",
                f" {self.activity} | {self.application.current_model_ref} | "
                f"{self.application.runtime_context.workdir} ",
            )
        ]

    def _preview_fragments(self) -> StyleAndTextTuples:
        columns, _rows = self._terminal_size()
        pending = _tail_for_preview(
            self._pending_text(),
            width=max(1, columns - 2),
            height=self._preview_height(),
        )
        return [
            ("class:preview.role", "┃ UthCode:\n"),
            ("class:preview", pending),
        ]

    def _candidate_fragments(self) -> StyleAndTextTuples:
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
        items = self.picker.models
        selected = self.picker.selected_index
        height = self._candidate_height()
        start = _window_start(selected, len(items), height)
        rows = []
        for index in range(start, min(len(items), start + height)):
            model = items[index]
            ref = model.model_ref
            label = model.label or ref
            current = " · current" if ref == self.picker.current_model_ref else ""
            marker = "›" if index == selected else " "
            style = "class:candidate.selected" if index == selected else "class:candidate"
            rows.append((style, f"{marker} {ref} — {label}{current}\n"))
        return rows

    def _build_bindings(self) -> KeyBindings:
        bindings = KeyBindings()
        completion_open = Condition(lambda: self.completion.open)
        picker_open = Condition(lambda: self.picker.open)
        menu_open = completion_open | picker_open

        @bindings.add(Keys.ControlM, eager=True)
        def _submit(event: object) -> None:
            del event
            if self.completion.open:
                self._execute_selected_command()
            elif self.picker.open:
                self._select_picker_model()
            else:
                text = self.buffer.text
                if text.strip():
                    self.buffer.set_document(Document("", 0), bypass_readonly=True)
                    self._spawn(self._handle_submission(text))

        @bindings.add(Keys.ControlJ, eager=True)
        @bindings.add(Keys.Escape, Keys.ControlJ, eager=True)
        def _newline(event: object) -> None:
            del event
            if not menu_open():
                self.buffer.insert_text("\n")

        @bindings.add(Keys.Backspace, eager=True)
        @bindings.add(Keys.ControlH, eager=True)
        def _backspace(event: object) -> None:
            del event
            if self.picker.open:
                return
            before = self.buffer.text[: self.buffer.cursor_position]
            count = previous_grapheme_length(before)
            if count:
                self.buffer.delete_before_cursor(count=count)

        @bindings.add(Keys.Up, filter=menu_open, eager=True)
        def _menu_up(event: object) -> None:
            del event
            (self.completion if self.completion.open else self.picker).move(-1)

        @bindings.add(Keys.Down, filter=menu_open, eager=True)
        def _menu_down(event: object) -> None:
            del event
            (self.completion if self.completion.open else self.picker).move(1)

        @bindings.add(Keys.Tab, eager=True)
        def _tab(event: object) -> None:
            del event
            if self.completion.open:
                self._complete_command()

        @bindings.add(Keys.Escape, eager=True)
        def _escape(event: object) -> None:
            del event
            if self.completion.open:
                self.completion.close()
            elif self.picker.open:
                self.picker.close()
                if self._picker_draft is not None:
                    self.buffer.set_document(self._picker_draft, bypass_readonly=True)
                self._picker_draft = None
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
        if not self.picker.open and text.lstrip().startswith("/"):
            self.completion.replace(self._application_completion(text))
        else:
            self.completion.close()
        self._invalidate()

    async def _handle_submission(self, text: str) -> None:
        self.completion.close()
        if text.lstrip().startswith("/"):
            invocation = self.parser.parse(text)
            if invocation.is_bare_slash:
                self.buffer.set_document(Document("/", 1), bypass_readonly=True)
                return
            if self._active_handle is not None and invocation.canonical == "model":
                await self._show_error("生成进行中不能切换模型")
                return
            outcome = self.dispatcher.dispatch(invocation)
            if outcome is not None:
                await self._apply_command_outcome(text, outcome)
            return
        if self._active_handle is not None:
            await self._show_error("生成进行中，请等待当前请求结束")
            return
        self._start_generation(text)

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
        elif isinstance(action, QuitInterface):
            self._closing = True
            self.ui.exit()
        elif isinstance(action, ModelSelected):
            self.activity = f"model: {action.model_ref}"
        prompt = outcome.prompt
        if prompt:
            if self._active_handle is None:
                self._start_generation(prompt)
            else:
                await self._show_error("生成进行中，请等待当前请求结束")
        self._invalidate()

    def _start_generation(self, prompt: str) -> None:
        self._reset_stream_projection()
        handle = self._run.start_turn(prompt)
        self._active_handle = handle
        self._esc.clear()
        self.activity = "generating"
        self._generation_task = asyncio.create_task(self._consume_turn(handle))
        self._invalidate()

    async def _consume_turn(self, handle: TurnHandle) -> None:
        renderer = AgentEventRenderer()
        terminal: str | None = None
        try:
            ticker = asyncio.create_task(self._flush_renderer_periodically(renderer))
            try:
                async for event in handle.events():
                    if not isinstance(event, AgentEvent):
                        raise RuntimeError("Application returned an invalid AgentEvent")
                    batch = renderer.push(event)
                    if batch is not None:
                        await self._apply_batch(batch)
                        terminal = batch.terminal or terminal
            finally:
                ticker.cancel()
                try:
                    await ticker
                except asyncio.CancelledError:
                    pass
        except asyncio.CancelledError:
            if not self._closing:
                await self._apply_batch(renderer.flush())
                await self._flush_streams()
                self.activity = "cancelled"
        except ProviderError:
            if not self._closing:
                await self._apply_batch(renderer.flush())
                await self._flush_streams()
                await self._show_error("生成失败")
        except Exception as exc:
            if not self._closing:
                await self._apply_batch(renderer.flush())
                await self._flush_streams()
                await self._show_error(f"生成失败：{type(exc).__name__}")
        else:
            if terminal is None and not self._closing:
                await self._flush_streams()
                self.activity = "ready"
        finally:
            if self._active_handle is handle:
                self._active_handle = None
            self._generation_task = None
            self._esc.clear()
            self._invalidate()

    async def _flush_renderer_periodically(
        self,
        renderer: AgentEventRenderer,
    ) -> None:
        while True:
            await asyncio.sleep(renderer.interval_seconds)
            batch = renderer.flush()
            if batch.has_updates:
                await self._apply_batch(batch)

    async def _apply_batch(self, batch: RenderBatch) -> None:
        self._sync_renderer_width()
        writes: list[str] = []
        for _message_id, text in batch.users:
            writes.append(self._renderer.user_message(text))
        for update in batch.text:
            projection = self._streams.setdefault(
                update.block_id,
                _StreamProjection(MarkdownStream(), update.kind),
            )
            projection.kind = update.kind
            stream = projection.stream
            if update.mode == "replace":
                commits, corrected = stream.replace(update.text)
                if corrected:
                    if not projection.started:
                        stream.committed = ""
                        stream.pending = update.text
                        corrected = False
                        commits = ()
                    else:
                        writes.append(self._renderer.correction(update.text))
                        stream.committed = update.text
                        stream.pending = ""
            else:
                commits = stream.append(update.text)
            for block in commits:
                writes.append(self._render_stream_block(update.block_id, block))
        if batch.tools:
            writes.append(self._render_forced_streams())
            for update in batch.tools:
                if update.status == "running":
                    self.activity = f"running {update.tool_name}: {update.command}"
                else:
                    writes.append(
                        self._renderer.tool(
                            status=update.status,
                            name=update.tool_name,
                            command=update.command,
                        )
                    )
        if batch.terminal is not None:
            writes.append(self._render_forced_streams(
                final_text=batch.final_text if batch.terminal == "completed" else None
            ))
            if batch.terminal == "completed":
                self.activity = "ready"
            elif batch.terminal == "cancelled":
                self.activity = "cancelled"
            else:
                writes.append(self._renderer.system("生成失败", error=True))
                self.activity = "error"
        output = "".join(writes)
        if output:
            await self._emit(output)
        self._invalidate()

    def _render_stream_block(self, block_id: str, text: str) -> str:
        projection = self._streams[block_id]
        role = "UthCode · reasoning" if projection.kind == "reasoning" else "UthCode:"
        rendered = self._renderer.agent_message(
            text,
            role=role,
            show_role=not projection.started,
            trailing_blank=False,
        )
        projection.started = True
        projection.open = True
        return rendered

    def _render_forced_streams(self, *, final_text: str | None = None) -> str:
        writes: list[str] = []
        for block_id, projection in self._streams.items():
            tail = projection.stream.force()
            if tail:
                writes.append(self._render_stream_block(block_id, tail))
        if any(projection.open for projection in self._streams.values()):
            writes.append("\n")
            for projection in self._streams.values():
                projection.open = False
        if final_text is not None:
            latest = next(
                (
                    projection.stream.committed
                    for projection in reversed(tuple(self._streams.values()))
                    if projection.kind == "assistant"
                ),
                "",
            )
            if latest != final_text:
                writes.append(self._renderer.correction(final_text))
        return "".join(writes)

    async def _flush_streams(self, *, final_text: str | None = None) -> None:
        output = self._render_forced_streams(final_text=final_text)
        if output:
            await self._emit(output)

    def _handle_generation_escape(self) -> None:
        now = time.monotonic()
        if self._esc.consume(now):
            assert self._active_handle is not None
            self._active_handle.cancel()
            self.activity = "cancelling"
        else:
            self._esc.arm(now)
            self.activity = "再次按 Esc 取消当前生成"
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
        except Exception as exc:
            await self._show_error(
                f"界面操作失败：{type(exc).__name__}；可以继续输入"
            )

    def _has_preview(self) -> bool:
        return bool(self._pending_text()) and self._preview_height() > 0

    def _has_candidates(self) -> bool:
        return (
            self.completion.open or self.picker.open
        ) and self._candidate_height() > 0

    def _pending_text(self) -> str:
        return "".join(
            projection.stream.pending
            for projection in self._streams.values()
        )

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
            if self.completion.open or self.picker.open
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
                "preview": f"{PALETTE.text} bg:{PALETTE.input_background}",
                "preview.role": f"bold {PALETTE.success} bg:{PALETTE.input_background}",
                "candidates": f"{PALETTE.text} bg:{PALETTE.user_background}",
                "candidate": f"{PALETTE.text} bg:{PALETTE.user_background}",
                "candidate.selected": (
                    f"bold {PALETTE.input_background} bg:{PALETTE.accent}"
                ),
                "separator": PALETTE.muted,
            }
        )

    def _invalidate(self) -> None:
        if hasattr(self, "ui") and self.ui.is_running:
            self.ui.invalidate()

    def _write(self, value: str) -> None:
        self.ui.output.write_raw(value)
        self.ui.output.flush()


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
