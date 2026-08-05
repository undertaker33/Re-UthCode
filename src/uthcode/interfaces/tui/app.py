"""Default Textual application adapter for the UthCode Application API."""

from __future__ import annotations

import asyncio
import shlex
import time

from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.events import Key
from textual.timer import Timer
from textual.widgets import Static

from uthcode.application import (
    ClearTranscript,
    CommandDispatcher,
    CommandParser,
    CompletionEngine,
    GenerationCancelled,
    GenerationHandle,
    GenerationRequest,
    GenerationCompleted,
    Message,
    ModelSelected,
    OpenModelPicker,
    ProviderError,
    QuitInterface,
    TextPart,
    UthCodeApplication,
    create_builtin_registry,
)

from .completion import CommandCompletionMenu, CompletionMenuItem
from .picker import ModelPicker
from .rendering import (
    STREAM_RENDER_INTERVAL_SECONDS,
    RenderBatch,
    StreamRenderer,
)
from .state import EscArmState, TranscriptEntryKind
from .widgets import ComposerTextArea, Topbar, TranscriptWidget


class UthCodeTUI(App[None]):
    """A single-screen, single-message Textual interface."""

    CSS_PATH = "tui.tcss"
    ALLOW_SELECT = True
    BINDINGS = [("ctrl+c", "quit_interface", "Quit")]

    def __init__(
        self,
        application: UthCodeApplication,
    ) -> None:
        super().__init__()
        self.application = application
        self.registry = create_builtin_registry()
        self.parser = CommandParser(self.registry)
        self.dispatcher = CommandDispatcher(self.registry, application)
        self._active_handle: GenerationHandle | None = None
        self._generation_task: asyncio.Task[None] | None = None
        self._stream_renderer: StreamRenderer | None = None
        self._stream_timer: Timer | None = None
        self._closing = False
        self._esc = EscArmState()

    def compose(self) -> ComposeResult:
        yield Topbar(
            self.application.current_model_ref,
            self.application.runtime_context.workdir,
        )
        with Vertical(id="main-column"):
            yield TranscriptWidget()
            yield Static("ready", id="activity")
            yield CommandCompletionMenu()
            yield ModelPicker()
            yield ComposerTextArea(
                placeholder="Message UthCode, or type / for commands",
                id="composer",
            )

    def on_mount(self) -> None:
        self._completion_menu().close()
        self._model_picker().close()
        self.query_one(ComposerTextArea).focus()

    def on_key(self, event: Key) -> None:
        key = event.key.lower()
        completion = self._completion_menu()
        picker = self._model_picker()

        if completion.state.open:
            if key == "up":
                event.stop()
                completion.move(-1)
            elif key == "down":
                event.stop()
                completion.move(1)
            elif key in {"escape", "esc"}:
                event.stop()
                completion.close()
            elif key == "tab":
                event.stop()
                self._complete_command()
            elif key == "enter":
                event.stop()
                self._execute_selected_command()
            return

        if picker.state.open:
            if key == "up":
                event.stop()
                picker.move(-1)
            elif key == "down":
                event.stop()
                picker.move(1)
            elif key in {"escape", "esc"}:
                event.stop()
                picker.close()
                self._focus_composer()
            elif key == "enter":
                event.stop()
                self._select_picker_model()
            return

        if key in {"escape", "esc"}:
            event.stop()
            self._handle_escape()

    def on_text_area_changed(self, event: ComposerTextArea.Changed) -> None:
        text = event.text_area.text
        try:
            completion = self._completion_menu()
        except Exception:
            return
        if text.lstrip().startswith("/"):
            candidates = self.application_completion(text)
            if candidates:
                completion.open(candidates)
                return
        completion.close()

    def on_composer_text_area_submitted(
        self,
        event: ComposerTextArea.Submitted,
    ) -> None:
        event.stop()
        if self._completion_menu().state.open:
            self._execute_selected_command()
        else:
            self._submit_text(event.text)

    def on_command_completion_menu_action(
        self,
        event: CommandCompletionMenu.Action,
    ) -> None:
        if event.action == "close":
            self._completion_menu().close()
            self._focus_composer()
        elif event.action == "complete":
            self._complete_command()
        elif event.action == "execute":
            self._execute_selected_command()

    def on_model_picker_action(self, event: ModelPicker.Action) -> None:
        if event.action == "close":
            self._model_picker().close()
            self._focus_composer()
        elif event.action == "select":
            self._select_picker_model()

    def action_quit_interface(self) -> None:
        self.exit()

    async def on_unmount(self) -> None:
        """Stop stream-owned resources before Textual tears down the view."""

        self._closing = True
        self._stop_stream_timer()
        handle = self._active_handle
        if handle is not None:
            handle.cancel()
        task = self._generation_task
        if task is not None and not task.done():
            task.cancel()
            await task

    def application_completion(self, text: str):
        engine = CompletionEngine(self.registry, self.application)
        stripped = text.lstrip()
        if not stripped.startswith("/"):
            return ()

        body = stripped[1:]
        name_end = 0
        while name_end < len(body) and not body[name_end].isspace():
            name_end += 1
        if name_end == len(body) or not body[name_end:].startswith((" ", "\t", "\n", "\r")):
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
            argument_text,
            invocation,
        )
        values = engine.argument_candidates(
            invocation,
            argument_index=argument_index,
        )
        normalized_partial = partial.casefold()
        usage = engine.usage_for(invocation) or definition.usage_text
        argument_prompt = engine.argument_prompt_for(invocation) or definition.argument_prompt
        return tuple(
            CompletionMenuItem(
                value=(
                    f"/{definition.canonical}"
                    + argument_text[:replacement_start]
                    + value
                ),
                display=self._argument_display(definition, argument_index, value),
                usage=usage,
                argument_prompt=argument_prompt,
            )
            for value in values
            if str(value).casefold().startswith(normalized_partial)
        )

    @staticmethod
    def _argument_display(definition, argument_index: int, value: str) -> str:
        if argument_index >= len(definition.arguments):
            return str(value)
        argument = definition.arguments[argument_index]
        if argument.description:
            return f"{value} — {argument.description}"
        return str(value)

    @staticmethod
    def _argument_context(
        argument_text: str,
        invocation,
    ) -> tuple[str, int, int]:
        """Return partial text, argument index, and raw replacement offset."""

        trimmed = argument_text.rstrip()
        trailing_space = len(trimmed) != len(argument_text)
        if trailing_space:
            partial = ""
            replacement_start = len(argument_text)
            argument_index = len(invocation.args)
            return partial, argument_index, replacement_start

        token_start = 0
        for index in range(len(trimmed) - 1, -1, -1):
            if trimmed[index].isspace():
                token_start = index + 1
                break
        partial = trimmed[token_start:]
        preceding = trimmed[:token_start]
        try:
            completed_args = len(shlex.split(preceding, posix=True))
        except ValueError:
            completed_args = max(len(invocation.args) - 1, 0)
        return partial, completed_args, token_start

    def _submit_text(self, text: str) -> None:
        self._completion_menu().close()
        composer = self.query_one(ComposerTextArea)
        composer.text = ""
        if not text.strip():
            return

        if text.lstrip().startswith("/"):
            invocation = self.parser.parse(text)
            if invocation.is_bare_slash:
                self._completion_menu().open(self.application_completion("/"))
                return
            if (
                self._active_handle is not None
                and invocation.canonical == "model"
            ):
                self._show_error("生成进行中不能切换模型")
                return
            outcome = self.dispatcher.dispatch(invocation)
            if outcome is None:
                return
            self._apply_command_outcome(text, outcome)
            return

        if self._active_handle is not None:
            self._show_error("生成进行中，请等待当前请求结束")
            return
        self._start_generation(text)

    def _apply_command_outcome(self, text: str, outcome: object) -> None:
        status = getattr(outcome, "status", None)
        if status is not None:
            self._transcript().add_entry(TranscriptEntryKind.COMMAND, text)
        message = getattr(outcome, "message", None)
        if message:
            kind = (
                TranscriptEntryKind.ERROR
                if getattr(outcome, "error", None) is not None
                else TranscriptEntryKind.SYSTEM
            )
            self._transcript().add_entry(kind, str(message))

        action = getattr(outcome, "ui_action", None)
        if isinstance(action, ClearTranscript):
            self._transcript().clear_transcript()
            self._set_activity("ready")
        elif isinstance(action, OpenModelPicker):
            self._open_model_picker()
        elif isinstance(action, QuitInterface):
            self.exit()
        elif isinstance(action, ModelSelected):
            self._topbar().update_model(action.model_ref)
            self._set_activity(f"model: {action.model_ref}")

        prompt = getattr(outcome, "prompt", None)
        if prompt:
            if self._active_handle is None:
                self._start_generation(prompt)
            else:
                self._show_error("生成进行中，请等待当前请求结束")

    def _start_generation(self, prompt: str) -> None:
        self._transcript().add_entry(TranscriptEntryKind.USER, prompt)
        self._transcript().begin_stream()
        request = GenerationRequest(
            messages=(Message("user", (TextPart(prompt),)),)
        )
        handle = self.application.start_generation(request)
        self._active_handle = handle
        self._esc.clear()
        self._set_activity("generating")
        self._generation_task = asyncio.create_task(self._consume_generation(handle))

    async def _consume_generation(self, handle: GenerationHandle) -> None:
        renderer = StreamRenderer()
        self._stream_renderer = renderer
        self._stream_timer = self.set_interval(
            STREAM_RENDER_INTERVAL_SECONDS,
            self._flush_stream_timer,
            name="stream-render",
        )
        try:
            async for event in handle.events():
                batch = renderer.push(event)
                if batch is not None:
                    self._apply_batch(batch)
                await asyncio.sleep(0)
        except GenerationCancelled:
            if not self._closing:
                self._apply_batch(renderer.finish_cancelled())
                self._set_activity("cancelled")
        except asyncio.CancelledError:
            if not self._closing:
                self._apply_batch(renderer.finish_cancelled())
                self._set_activity("cancelled")
        except ProviderError:
            if not self._closing:
                self._apply_batch(renderer.flush())
                self._show_error("生成失败")
                self._set_activity("error")
        except Exception:
            if not self._closing:
                self._apply_batch(renderer.flush())
                self._show_error("生成失败")
                self._set_activity("error")
        else:
            if not self._closing:
                self._transcript().finish_stream()
                self._set_activity("ready")
        finally:
            self._stop_stream_timer()
            self._stream_renderer = None
            if not self._closing:
                self._transcript().finish_stream()
            if self._active_handle is handle:
                self._active_handle = None
            self._generation_task = None
            self._esc.clear()
            if not self._closing:
                self._focus_composer()

    def _flush_stream_timer(self) -> None:
        renderer = self._stream_renderer
        if renderer is None or self._active_handle is None:
            return
        batch = renderer.flush()
        if batch.text or batch.reasoning:
            self._apply_batch(batch)

    def _stop_stream_timer(self) -> None:
        timer = self._stream_timer
        self._stream_timer = None
        if timer is not None:
            timer.stop()

    def _apply_batch(self, batch: RenderBatch) -> None:
        transcript = self._transcript()
        if batch.reasoning:
            transcript.append_reasoning(batch.reasoning)
        if batch.text:
            transcript.append_assistant(batch.text)
        if batch.completed:
            transcript.finish_stream()

    def _handle_escape(self) -> None:
        if self._active_handle is None:
            return
        now = time.monotonic()
        if self._esc.consume(now):
            self._active_handle.cancel()
            self._set_activity("cancelling")
        else:
            self._esc.arm(now)
            self._set_activity("press Esc again within 1 second to cancel")

    def _open_model_picker(self) -> None:
        if self._active_handle is not None:
            self._show_error("生成进行中不能切换模型")
            return
        self._completion_menu().close()
        picker = self._model_picker()
        picker.open(tuple(self.application.model_catalog()), self.application.current_model_ref)
        picker.focus()

    def _select_picker_model(self) -> None:
        picker = self._model_picker()
        model = picker.selected
        if model is None:
            picker.close()
            self._focus_composer()
            return
        ref = str(getattr(model, "model_ref", ""))
        self._submit_text(f"/model {ref}")
        picker.close()
        self._focus_composer()

    def _complete_command(self) -> None:
        candidate = self._completion_menu().selected
        if candidate is None:
            return
        composer = self.query_one(ComposerTextArea)
        composer.text = candidate.value
        composer.focus()
        self._completion_menu().close()

    def _execute_selected_command(self) -> None:
        candidate = self._completion_menu().selected
        if candidate is None:
            return
        self._completion_menu().close()
        self._submit_text(candidate.value)

    def _show_error(self, text: str) -> None:
        self._transcript().add_entry(TranscriptEntryKind.ERROR, text)
        self._set_activity("error")

    def _set_activity(self, text: str) -> None:
        self.query_one("#activity", Static).update(text)

    def _focus_composer(self) -> None:
        self.query_one(ComposerTextArea).focus()

    def _transcript(self) -> TranscriptWidget:
        return self.query_one(TranscriptWidget)

    def _topbar(self) -> Topbar:
        return self.query_one(Topbar)

    def _completion_menu(self) -> CommandCompletionMenu:
        return self.query_one(CommandCompletionMenu)

    def _model_picker(self) -> ModelPicker:
        return self.query_one(ModelPicker)


def run_tui(
    application: UthCodeApplication,
) -> object:
    """Start the default TUI for one already-composed Application."""

    return UthCodeTUI(application).run()


__all__ = ["UthCodeTUI", "run_tui"]
