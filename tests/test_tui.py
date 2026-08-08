from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncIterator, Iterable
from pathlib import Path

import pytest
from prompt_toolkit.input.defaults import create_pipe_input
from prompt_toolkit.document import Document
from prompt_toolkit.layout import VSplit
from prompt_toolkit.output import DummyOutput

from uthcode.application import (
    AgentRun,
    ApplicationRuntimeContext,
    GenerationCompleted,
    GenerationRequest,
    Message,
    ModelProfile,
    PauseKind,
    PauseReason,
    PauseRequest,
    PermissionApprovalChoice,
    PermissionApprovalRequest,
    ProviderResponse,
    PermissionMode,
    QuestionOption,
    QuestionKind,
    RetryProviderResponse,
    RunStatus,
    TextDelta,
    TextPart,
    TurnHandle,
    ToolCallPart,
    ToolResultPart,
    Usage,
    UthCodeApplication,
    UserInputRequest,
    UserQuestion,
)
from uthcode.core.provider import (
    CancellationToken,
    FinishReason,
    NetworkError,
    ProviderEvent,
    RateLimitError,
)
from uthcode.core.permission import Effect, ResourceScope
from uthcode.integrations.providers.fake import FakeProvider
from uthcode.interfaces.tui.app import (
    UthCodeTUI,
    _StreamProjection,
    _tail_for_preview,
    _window_start,
)
from uthcode.interfaces.tui.interaction import InteractionMode, TuiInteractionState
from uthcode.interfaces.tui.rendering import (
    AgentEventRenderer,
    MarkdownStream,
    RenderBatch,
    TextUpdate,
    ToolUpdate,
)
from uthcode.interfaces.tui.state import EscArmState, previous_grapheme_length
from uthcode.interfaces.tui.terminal import (
    CLEAR_VIEWPORT,
    KITTY_KEYBOARD_OFF,
    KITTY_KEYBOARD_ON,
    RichTerminalRenderer,
    SYNCHRONIZED_OUTPUT_OFF,
    SYNCHRONIZED_OUTPUT_ON,
    _protect_nested_markdown_fences,
)
from uthcode.interfaces.tui.windows_input import create_windows_unicode_input


class RecordingOutput(DummyOutput):
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    def write(self, data: str) -> None:
        self.events.append(("write", data))

    def write_raw(self, data: str) -> None:
        self.events.append(("raw", data))

    def erase_down(self) -> None:
        self.events.append(("erase_down", ""))

    def cursor_goto(self, row: int = 0, column: int = 0) -> None:
        self.events.append(("cursor_goto", f"{row},{column}"))

    def getvalue(self) -> str:
        return "".join(
            value
            for operation, value in self.events
            if operation in {"write", "raw"}
        )


class _ScriptedProvider(FakeProvider):
    def __init__(
        self,
        scripts: Iterable[Iterable[ProviderEvent]],
        *,
        delay: float = 0.0,
        delays: tuple[float, ...] | None = None,
    ) -> None:
        super().__init__(delay=delay)
        self._scripts = tuple(tuple(script) for script in scripts)
        self._delays = delays

    async def stream(
        self,
        request: GenerationRequest,
        *,
        cancellation: CancellationToken,
    ) -> AsyncIterator[ProviderEvent]:
        self.requests.append(request)
        cancellation.raise_if_cancelled()
        index = min(len(self.requests) - 1, len(self._scripts) - 1)
        for event in self._scripts[index]:
            delay = self._delays[index] if self._delays is not None else self._delay
            if delay:
                try:
                    await asyncio.wait_for(cancellation.wait(), timeout=delay)
                except asyncio.TimeoutError:
                    pass
                else:
                    cancellation.raise_if_cancelled()
            cancellation.raise_if_cancelled()
            yield event


class _ProviderFailureThenSuccess(_ScriptedProvider):
    def __init__(
        self,
        error: NetworkError | RateLimitError,
        success: Iterable[ProviderEvent],
    ) -> None:
        super().__init__((tuple(success),))
        self._error = error

    async def stream(
        self,
        request: GenerationRequest,
        *,
        cancellation: CancellationToken,
    ) -> AsyncIterator[ProviderEvent]:
        if not self.requests:
            self.requests.append(request)
            cancellation.raise_if_cancelled()
            raise self._error
        async for event in super().stream(request, cancellation=cancellation):
            yield event


def _completed(
    text: str = "done",
    *parts: object,
    finish_reason: FinishReason = FinishReason.STOP,
) -> GenerationCompleted:
    return GenerationCompleted(
        ProviderResponse(
            message=Message("assistant", (TextPart(text), *parts)),
            usage=Usage(),
            finish_reason=finish_reason,
        )
    )


def _application(*events: object, delay: float = 0.0) -> UthCodeApplication:
    provider_events = events or (_completed("fake response"),)
    return UthCodeApplication(
        FakeProvider(events=provider_events, delay=delay),  # type: ignore[arg-type]
        runtime_context=ApplicationRuntimeContext.from_system(
            workdir=Path("C:/workspace"),
            platform_name="TestOS",
            platform_release="1.0",
            current_date="2026-08-06",
        ),
    )


async def _wait_until(predicate, attempts: int = 80) -> None:  # type: ignore[no-untyped-def]
    for _ in range(attempts):
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition did not become true")


async def _start_tui(
    application: UthCodeApplication | None = None,
) -> tuple[UthCodeTUI, object, asyncio.Task[int], RecordingOutput]:
    pipe_context = create_pipe_input()
    pipe = pipe_context.__enter__()
    output = RecordingOutput()
    tui = UthCodeTUI(
        application or _application(),
        input_device=pipe,
        terminal_output=output,
    )
    task = asyncio.create_task(tui.run_async())
    await _wait_until(lambda: tui.ui.is_running)
    return tui, (pipe_context, pipe), task, output


async def _stop_tui(
    tui: UthCodeTUI,
    pipe_state: object,
    task: asyncio.Task[int],
) -> None:
    pipe_context, pipe = pipe_state  # type: ignore[misc]
    if tui.ui.is_running:
        pipe.send_text("\x03")
    await asyncio.wait_for(task, timeout=2)
    pipe_context.__exit__(None, None, None)


async def _assert_tui_shutdown_cleanup(
    tui: UthCodeTUI,
    run: AgentRun,
    handle: TurnHandle,
) -> None:
    driver = handle._driver
    assert driver._result_future is not None
    assert driver._result_future.done()
    result = await handle.result()
    assert result.status is RunStatus.CANCELLED
    assert run._active_turn is None
    assert handle.pending_pause is None
    assert tui._generation_task is None
    assert tui._active_handle is None
    assert not tui._background_tasks
    assert driver._task is None
    assert driver._response_waiter is None
    assert driver._segment_signal is None


async def _assert_consumer_failure_cleanup(
    tui: UthCodeTUI,
    run: AgentRun,
    handle: TurnHandle,
    task: asyncio.Task[None],
) -> None:
    assert task.done()
    assert not task.cancelled()
    assert task.exception() is None
    driver = handle._driver
    assert driver._result_future is not None
    assert driver._result_future.done()
    result = await handle.result()
    assert result.status is RunStatus.CANCELLED
    assert run._active_turn is None
    assert handle.pending_pause is None
    assert driver._task is None
    assert driver._response_waiter is None
    assert driver._segment_signal is None
    assert tui._active_handle is None
    assert tui._generation_task is None
    assert not tui._background_tasks


def test_grapheme_backspace_lengths_cover_chinese_combining_and_emoji() -> None:
    assert previous_grapheme_length("你好") == 1
    assert previous_grapheme_length("e\u0301") == 2
    assert previous_grapheme_length("👨‍👩‍👧‍👦") == len("👨‍👩‍👧‍👦")
    assert previous_grapheme_length("") == 0


def test_double_escape_state_is_time_bound() -> None:
    esc = EscArmState()
    esc.arm(10.0)
    assert esc.consume(10.5) is True
    esc.arm(10.0)
    assert esc.consume(11.1) is False


def test_tui_interaction_state_handles_select_multi_other_and_review() -> None:
    request = UserInputRequest(
        (
            UserQuestion(
                "single",
                "Mode",
                "Choose a mode",
                QuestionKind.SINGLE_SELECT,
                (
                    QuestionOption("fast", "Fast mode"),
                    QuestionOption("safe", "Safe mode"),
                ),
            ),
            UserQuestion(
                "multi",
                "Targets",
                "Choose targets",
                QuestionKind.MULTI_SELECT,
                (
                    QuestionOption("api", "API"),
                    QuestionOption("ui", "UI"),
                ),
            ),
            UserQuestion(
                "other",
                "Owner",
                "Who owns it?",
                QuestionKind.SINGLE_SELECT,
                (
                    QuestionOption("team", "The team"),
                    QuestionOption("me", "The user"),
                ),
                allow_other=True,
            ),
        )
    )
    pause = PauseRequest(
        "pause",
        "run",
        "turn",
        PauseKind.USER_INPUT_REQUIRED,
        PauseReason.USER_INPUT_REQUIRED,
        1,
        "now",
        "call",
        request,
    )
    state = TuiInteractionState()
    state.open_pause(pause)
    assert state.mode is InteractionMode.QUESTIONS

    assert state.submit_current() is True
    assert state.answers["single"] == ["fast"]
    state.move(1)
    assert state.toggle_option() is True
    state.move(1)
    assert state.toggle_option() is True
    assert state.submit_current() is True
    assert state.answers["multi"] == ["api", "ui"]
    state.choose_other()
    state.set_draft("a partner")
    assert state.submit_current() is True
    assert state.mode is InteractionMode.REVIEW
    response = state.user_input_response()
    assert response is not None
    assert response.answers["other"] == ["a partner"]


def test_tui_interaction_state_renders_permission_choices_without_secret_payload() -> None:
    request = PermissionApprovalRequest(
        permission_id="permission-1",
        run_id="run",
        turn_id="turn",
        tool_call_id="call",
        tool="WriteFile",
        action="write",
        effect=Effect.WRITE,
        resource="safe.txt",
        scope=ResourceScope.INSIDE,
        reason="mode_fallback",
        mode=PermissionMode.DEFAULT,
        choices=(
            PermissionApprovalChoice.ONCE,
            PermissionApprovalChoice.SESSION,
            PermissionApprovalChoice.REJECT,
        ),
        guard=False,
    )
    pause = PauseRequest(
        pause_id="pause",
        run_id="run",
        turn_id="turn",
        kind=PauseKind.PERMISSION_REQUIRED,
        reason=PauseReason.PERMISSION_REQUIRED,
        iteration=1,
        created_at="now",
        tool_call_id="call",
        permission_request=request,
    )
    state = TuiInteractionState()
    state.open_pause(pause)
    assert state.mode is InteractionMode.PERMISSION
    assert state.permission_choices == request.choices
    assert "Allow for session" in "".join(text for _style, text in state.render_lines())
    assert "secret" not in "".join(text for _style, text in state.render_lines())
    state.move(1)
    response = state.permission_response()
    assert response is not None
    assert response.choice is PermissionApprovalChoice.SESSION


def test_tui_interaction_exit_other_restores_legal_single_select_focus() -> None:
    question = UserQuestion(
        "mode",
        "Mode",
        "Choose a mode",
        QuestionKind.SINGLE_SELECT,
        (
            QuestionOption("fast", "Fast mode"),
            QuestionOption("safe", "Safe mode"),
        ),
        allow_other=True,
    )
    pause = PauseRequest(
        "pause",
        "run",
        "turn",
        PauseKind.USER_INPUT_REQUIRED,
        PauseReason.USER_INPUT_REQUIRED,
        1,
        "now",
        "call",
        UserInputRequest((question,)),
    )
    state = TuiInteractionState()
    state.open_pause(pause)

    state.move(1)
    assert state.toggle_option() is True
    state.move(1)
    assert state.option_index == len(question.options)
    assert state.choose_other() is True
    state.set_draft("custom")

    assert state.exit_other() is True
    assert state.other_mode is False
    assert state.draft == ""
    assert state.option_index == 1
    assert state.selected_options == {1}
    assert 0 <= state.option_index < len(question.options)

    state.open_pause(pause)
    state.move(len(question.options))
    assert state.choose_other() is True
    state.set_draft("custom")
    assert state.exit_other() is True
    assert state.other_mode is False
    assert state.draft == ""
    assert state.option_index == 0
    assert state.selected_options == set()
    assert 0 <= state.option_index < len(question.options)


def test_markdown_stream_waits_for_real_fence_closure() -> None:
    stream = MarkdownStream()
    assert stream.append("```text\ninside\n```not-a-close\n") == ()
    assert stream.committed == ""
    assert stream.append("```\n") == (
        "```text\ninside\n```not-a-close\n```\n",
    )


def test_markdown_stream_commits_paragraphs_and_force_flushes_tail() -> None:
    stream = MarkdownStream()
    assert stream.append("第一段\n\n") == ("第一段\n\n",)
    assert stream.append("- one\n- two") == ()
    assert stream.force() == "- one\n- two"


def test_renderer_restores_roles_surfaces_markdown_and_code_colours() -> None:
    renderer = RichTerminalRenderer(width=80)
    user = renderer.user_message("你好")
    agent = renderer.agent_message(
        "# 标题\n\n- 一\n- 二\n\n`inline`\n\n"
        "```python\nprovider = self._provider\nprint(provider)\n```"
    )
    assert "you" in user
    assert "UthCode:" in agent
    assert "┃" in user and "┃" in agent
    assert "48;2;36;47;56m" in user
    assert "48;2;30;30;30m" not in agent
    assert "48;2;18;18;18m" in agent
    assert "38;2;224;224;224m" in agent
    assert "38;2;254;166;43" in agent
    assert "38;2;0;0;0" not in agent


def test_tool_rows_keep_status_text_and_semantic_colour() -> None:
    renderer = RichTerminalRenderer(width=80)
    success = renderer.tool(status="finished", name="Bash", command="dir")
    failure = renderer.tool(status="denied", name="Bash", command="del")
    assert "finished" in success and "38;2;78;191;113m" in success
    assert "denied" in failure and "38;2;185;60;91m" in failure
    assert "\x1b[38;2;154;154;154m┃" in success
    assert "\x1b[38;2;154;154;154m┃" in failure
    assert success.endswith("\n\n") and failure.endswith("\n\n")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows console event")
def test_windows_native_shift_enter_maps_to_newline() -> None:
    from prompt_toolkit.keys import Keys
    from prompt_toolkit.win32_types import KEY_EVENT_RECORD

    input_device = create_windows_unicode_input()
    reader = input_device.console_input_reader  # type: ignore[attr-defined]
    event = KEY_EVENT_RECORD()
    event.KeyDown = 1
    event.RepeatCount = 1
    event.VirtualKeyCode = 13
    event.VirtualScanCode = 28
    event.uChar.UnicodeChar = "\r"
    event.ControlKeyState = reader.SHIFT_PRESSED
    keys = reader._event_to_key_presses(event)
    assert [key.key for key in keys] == [Keys.ControlJ]


def test_composer_prompt_is_separate_from_ime_buffer_cursor() -> None:
    tui = UthCodeTUI(_application(), terminal_output=RecordingOutput())
    composer = tui._composer
    assert isinstance(composer, VSplit)
    assert len(composer.children) == 2
    assert composer.children[1].content is tui._buffer_control


@pytest.mark.asyncio
async def test_tui_permission_picker_uses_run_session_and_warns_on_full_access() -> None:
    output = RecordingOutput()
    tui = UthCodeTUI(_application(), terminal_output=output)
    outcome = tui.dispatcher.dispatch_text("/permission")
    assert outcome is not None
    await tui._apply_command_outcome("/permission", outcome)
    assert tui.permission_picker.open is True
    assert tui._run.permission_mode is PermissionMode.DEFAULT

    tui.permission_picker.move(1)
    tui._select_permission_mode()
    assert tui._run.permission_mode is PermissionMode.AUTO
    assert tui.application.create_run().permission_mode is PermissionMode.DEFAULT

    outcome = tui.dispatcher.dispatch_text("/permission")
    assert outcome is not None
    await tui._apply_command_outcome("/permission", outcome)
    tui.permission_picker.move(1)
    assert tui.permission_picker.selected is PermissionMode.FULL_ACCESS
    tui._select_permission_mode()
    await asyncio.sleep(0)
    assert tui._run.permission_mode is PermissionMode.FULL_ACCESS
    assert "高风险提示" in output.getvalue()


@pytest.mark.asyncio
async def test_hardware_cursor_tracks_persistent_buffer_window_at_bottom() -> None:
    tui, pipe_state, task, _output = await _start_tui()
    _context, pipe = pipe_state  # type: ignore[misc]
    try:
        pipe.send_text("hi")
        await _wait_until(lambda: tui.buffer.text == "hi")
        await asyncio.sleep(0.05)
        screen = tui.ui.renderer.last_rendered_screen
        point = screen.get_cursor_position(tui.ui.layout.current_window)
        assert point.x == 6  # two letters after the four-column prompt
        assert point.y == tui.ui.output.get_size().rows - 4
        assert tui.ui.layout.current_window in screen.cursor_positions
    finally:
        await _stop_tui(tui, pipe_state, task)


def test_composer_is_three_lines_then_expands_with_content() -> None:
    tui = UthCodeTUI(_application(), terminal_output=RecordingOutput())
    tui._terminal_size = lambda: (40, 20)  # type: ignore[method-assign]
    assert tui._composer_height() == 3
    tui.buffer.set_document(Document("一\n二\n三\n四", 7), bypass_readonly=True)
    assert tui._composer_height() == 4


def test_stream_preview_tracks_latest_rows_instead_of_freezing_at_top() -> None:
    assert _tail_for_preview(
        "第一行\n第二行\n第三行\n第四行",
        width=20,
        height=2,
    ) == "第三行\n第四行"
    assert _tail_for_preview(
        "123456789",
        width=3,
        height=2,
    ) == "456\n789"


def test_nested_markdown_code_fence_uses_a_longer_outer_fence() -> None:
    source = (
        "```markdown\n"
        "# 文档\n\n"
        "```python\n"
        "print('嵌套代码块')\n"
        "```\n"
        "```\n"
    )
    protected = _protect_nested_markdown_fences(source)
    assert protected.startswith("````markdown\n")
    assert protected.endswith("````\n")
    assert "```python\nprint('嵌套代码块')\n```\n" in protected


def test_welcome_contains_logo_model_cwd_and_no_global_background() -> None:
    value = RichTerminalRenderer(width=100).welcome(
        "deepseek/chat", "C:\\workspace"
    )
    assert "UthCode" in value
    assert "deepseek/chat" in value
    assert "C:\\workspace" in value
    assert "Shift+Enter" in value


@pytest.mark.asyncio
async def test_startup_clears_viewport_without_clearing_scrollback_or_alt_screen() -> None:
    tui, pipe_state, task, output = await _start_tui()
    try:
        rendered = output.getvalue()
        raw_writes = [
            value
            for operation, value in output.events
            if operation == "raw"
        ]
        assert raw_writes[0] == SYNCHRONIZED_OUTPUT_ON
        assert raw_writes[1].startswith(CLEAR_VIEWPORT)
        assert raw_writes[2] == SYNCHRONIZED_OUTPUT_OFF
        assert SYNCHRONIZED_OUTPUT_OFF in rendered
        assert KITTY_KEYBOARD_ON in rendered
        assert "\x1b[3J" not in rendered
        assert "\x1b[?1049" not in rendered
        assert "\x1b[?1000" not in rendered
        assert tui.ui.full_screen is False
    finally:
        await _stop_tui(tui, pipe_state, task)
    assert KITTY_KEYBOARD_OFF in output.getvalue()


@pytest.mark.asyncio
async def test_permanent_commit_wraps_erase_content_and_redraw_on_one_output() -> None:
    tui, pipe_state, task, output = await _start_tui()
    try:
        output.events.clear()
        await tui._emit("PERMANENT")
        on = output.events.index(("raw", SYNCHRONIZED_OUTPUT_ON))
        content = output.events.index(("raw", "PERMANENT"))
        off = output.events.index(("raw", SYNCHRONIZED_OUTPUT_OFF))
        assert on < content < off
        assert any(
            operation == "erase_down"
            for operation, _value in output.events[on + 1 : content]
        )
        assert any(
            operation in {"write", "cursor_goto"}
            for operation, _value in output.events[content + 1 : off]
        )
    finally:
        await _stop_tui(tui, pipe_state, task)


@pytest.mark.asyncio
async def test_one_event_batch_uses_one_permanent_terminal_commit() -> None:
    tui = UthCodeTUI(_application(), terminal_output=RecordingOutput())
    writes: list[str] = []

    async def capture(value: str) -> None:
        writes.append(value)

    tui._emit = capture  # type: ignore[method-assign]
    await tui._apply_batch(
        RenderBatch(
            users=(("user", "问题"),),
            text=(
                TextUpdate(
                    "assistant",
                    "assistant",
                    "第一段。\n\n第二段。",
                ),
            ),
            tools=(ToolUpdate("tool", "Bash", "dir", "finished"),),
        )
    )
    assert len(writes) == 1
    assert "问题" in writes[0]
    assert "第一段" in writes[0] and "第二段" in writes[0]
    assert "finished" in writes[0]


@pytest.mark.asyncio
async def test_permanent_render_uses_current_terminal_width() -> None:
    tui = UthCodeTUI(_application(), terminal_output=RecordingOutput())
    tui._terminal_size = lambda: (52, 20)  # type: ignore[method-assign]
    await tui._apply_batch(RenderBatch(users=(("user", "问题"),)))
    assert tui._renderer.width == 52


@pytest.mark.asyncio
async def test_unicode_input_and_grapheme_backspace_do_not_exit() -> None:
    tui, pipe_state, task, _output = await _start_tui()
    pipe_context, pipe = pipe_state  # type: ignore[misc]
    del pipe_context
    try:
        pipe.send_text("你好")
        await _wait_until(lambda: tui.buffer.text == "你好")
        pipe.send_text("\x7f")
        await _wait_until(lambda: tui.buffer.text == "你")
        pipe.send_text("\x7f\x7f")
        await _wait_until(lambda: tui.buffer.text == "")
        assert tui.ui.is_running
        pipe.send_text("e\u0301")
        await _wait_until(lambda: tui.buffer.text == "e\u0301")
        pipe.send_text("\x7f")
        await _wait_until(lambda: tui.buffer.text == "")
        assert tui.ui.is_running
    finally:
        await _stop_tui(tui, pipe_state, task)


@pytest.mark.asyncio
async def test_slash_menu_keeps_accepting_text_and_backspace() -> None:
    tui, pipe_state, task, _output = await _start_tui()
    _context, pipe = pipe_state  # type: ignore[misc]
    try:
        pipe.send_text("/")
        await _wait_until(lambda: tui.completion.open)
        pipe.send_text("status")
        await _wait_until(lambda: tui.buffer.text == "/status")
        assert tui.completion.open
        pipe.send_text("\x7f")
        await _wait_until(lambda: tui.buffer.text == "/statu")
        assert tui.ui.is_running
    finally:
        await _stop_tui(tui, pipe_state, task)


@pytest.mark.asyncio
async def test_shift_enter_ctrl_j_and_multiline_paste_preserve_newlines() -> None:
    tui, pipe_state, task, _output = await _start_tui()
    _context, pipe = pipe_state  # type: ignore[misc]
    try:
        pipe.send_text("甲\x1b[13;2u乙")
        await _wait_until(lambda: tui.buffer.text == "甲\n乙")
        pipe.send_text("\n丙")
        await _wait_until(lambda: tui.buffer.text == "甲\n乙\n丙")
        pipe.send_text("丁\n戊")
        await _wait_until(lambda: tui.buffer.text.endswith("丁\n戊"))
        assert tui._generation_task is None
    finally:
        await _stop_tui(tui, pipe_state, task)


@pytest.mark.asyncio
async def test_enter_submits_exact_chinese_to_provider_and_finishes() -> None:
    application = _application(_completed("回答"))
    provider = application.provider
    tui, pipe_state, task, output = await _start_tui(application)
    _context, pipe = pipe_state  # type: ignore[misc]
    try:
        pipe.send_text("你好\r")
        await _wait_until(lambda: tui._generation_task is None and bool(provider.requests))
        request = provider.requests[0]
        assert any(
            getattr(part, "text", None) == "你好"
            for message in request.messages
            for part in message.parts
        )
        rendered = output.getvalue()
        assert "you" in rendered and "你好" in rendered
        assert "UthCode:" in rendered and "回答" in rendered
    finally:
        await _stop_tui(tui, pipe_state, task)


@pytest.mark.asyncio
async def test_model_picker_escape_restores_draft_and_never_exits() -> None:
    tui, pipe_state, task, _output = await _start_tui()
    _context, pipe = pipe_state  # type: ignore[misc]
    try:
        tui._picker_draft = Document("/model", len("/model"))
        tui.picker.replace(
            (ModelProfile("fake/model", "fake", "model", "Fake"),),
            "fake/model",
        )
        assert tui.picker.open
        pipe.send_text("\x1b")
        await _wait_until(lambda: not tui.picker.open)
        assert tui.buffer.text == "/model"
        assert tui.ui.is_running
    finally:
        await _stop_tui(tui, pipe_state, task)


def test_candidate_window_tracks_selected_visible_item() -> None:
    assert _window_start(0, 15, 8) == 0
    assert _window_start(8, 15, 8) <= 8 < _window_start(8, 15, 8) + 8
    assert _window_start(14, 15, 8) == 7


@pytest.mark.asyncio
async def test_tui_double_escape_pauses_and_resume_keeps_the_turn_alive() -> None:
    provider = _ScriptedProvider(
        ((_completed("回答"),), (_completed("回答"),)),
        delays=(5.0, 0.0),
    )
    application = UthCodeApplication(
        provider,
        runtime_context=ApplicationRuntimeContext.from_system(
            workdir=Path("C:/workspace"),
            platform_name="TestOS",
            platform_release="1.0",
            current_date="2026-08-06",
        ),
    )
    tui, pipe_state, task, _output = await _start_tui(application)
    _context, pipe = pipe_state  # type: ignore[misc]
    try:
        pipe.send_text("hello\r")
        await _wait_until(lambda: tui._active_handle is not None and bool(provider.requests))
        pipe.send_text("\x1b\x1b")
        await _wait_until(
            lambda: tui._active_handle is not None
            and tui._active_handle.pending_pause is not None,
            attempts=500,
        )
        await _wait_until(lambda: tui.activity == "paused")
        assert tui._active_handle is not None
        assert not tui._active_handle.cancelled()
        pipe.send_text("\r")
        await _wait_until(lambda: tui._generation_task is None, attempts=500)
        assert tui._active_handle is None
        assert provider.requests
    finally:
        await _stop_tui(tui, pipe_state, task)


@pytest.mark.asyncio
async def test_tui_pause_resume_and_ask_user_pilot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call = ToolCallPart(
        "ask-1",
        "AskUserQuestion",
        {
            "questions": [
                {
                    "question_id": "q1",
                    "header": "Value",
                    "question": "What value should be used?",
                    "kind": "text",
                }
            ]
        },
    )
    provider = _ScriptedProvider(
        (
            (_completed("discarded before pause"),),
            (_completed("need input", call, finish_reason=FinishReason.TOOL_CALLS),),
            (_completed("已完成"),),
        ),
        delays=(5.0, 0.0, 0.0),
    )
    application = UthCodeApplication(
        provider,
        runtime_context=ApplicationRuntimeContext.from_system(
            workdir=Path("C:/workspace"),
            platform_name="TestOS",
            platform_release="1.0",
            current_date="2026-08-06",
        ),
    )
    started_handles: list[TurnHandle] = []
    original_start_turn = AgentRun.start_turn

    def record_start(run: AgentRun, prompt: str) -> TurnHandle:
        handle = original_start_turn(run, prompt)
        started_handles.append(handle)
        return handle

    monkeypatch.setattr(AgentRun, "start_turn", record_start)
    tui, pipe_state, task, output = await _start_tui(application)
    _context, pipe = pipe_state  # type: ignore[misc]
    try:
        pipe.send_text("hello\r")
        await _wait_until(lambda: tui._active_handle is not None and len(provider.requests) == 1)
        pipe.send_text("\x1b\x1b")
        await _wait_until(
            lambda: tui._active_handle is not None
            and tui._active_handle.pending_pause is not None
            and tui.activity == "paused",
            attempts=500,
        )
        handle = tui._active_handle
        assert handle is not None
        assert len(started_handles) == 1
        assert not handle.cancelled()

        # Resume the same Turn through the public TUI action menu.  The retry
        # reaches a second pause for AskUserQuestion without starting a new Turn.
        pipe.send_text("\r")
        await _wait_until(
            lambda: tui._active_handle is handle
            and tui.interaction.mode is InteractionMode.QUESTIONS
            and handle.pending_pause is not None
            and len(provider.requests) == 2,
            attempts=500,
        )
        pipe.send_text("答案\r")
        await _wait_until(lambda: tui.interaction.mode is InteractionMode.REVIEW)
        pipe.send_text("\r")
        await _wait_until(
            lambda: tui._generation_task is None
            and tui._active_handle is None
            and tui.interaction.mode is InteractionMode.CLOSED,
            attempts=500,
        )

        assert len(started_handles) == 1
        assert len(provider.requests) == 3
        assert "已完成" in output.getvalue()
        assert provider.requests[2].messages[-1].parts == (
            ToolResultPart("ask-1", '{"answers": {"q1": ["答案"]}}'),
        )
        assert not tui._background_tasks
    finally:
        await _stop_tui(tui, pipe_state, task)


@pytest.mark.asyncio
async def test_tui_pause_cancel_cleans_turn_without_saved_state() -> None:
    provider = _ScriptedProvider(
        ((_completed("不会完成"),), (_completed("不会完成"),)),
        delays=(5.0, 0.0),
    )
    application = UthCodeApplication(
        provider,
        runtime_context=ApplicationRuntimeContext.from_system(
            workdir=Path("C:/workspace"),
            platform_name="TestOS",
            platform_release="1.0",
            current_date="2026-08-06",
        ),
    )
    tui, pipe_state, task, output = await _start_tui(application)
    _context, pipe = pipe_state  # type: ignore[misc]
    try:
        pipe.send_text("hello\r")
        await _wait_until(lambda: tui._active_handle is not None and bool(provider.requests))
        pipe.send_text("\x1b\x1b")
        await _wait_until(
            lambda: tui._active_handle is not None
            and tui._active_handle.pending_pause is not None,
            attempts=500,
        )
        await _wait_until(lambda: tui.activity == "paused")
        tui.interaction.move(1)
        pipe.send_text("\r")
        await _wait_until(lambda: tui._generation_task is None, attempts=500)
        assert tui._active_handle is None
        assert len(provider.requests) == 1
        assert "保存" not in output.getvalue()
        assert not tui._background_tasks
    finally:
        await _stop_tui(tui, pipe_state, task)


@pytest.mark.asyncio
async def test_tui_shutdown_waits_for_active_turn_terminal_and_releases_run() -> None:
    provider = _ScriptedProvider(
        (
            (_completed("cancelled response"),),
            (_completed("after shutdown"),),
        ),
        delays=(5.0, 0.0),
    )
    application = UthCodeApplication(
        provider,
        runtime_context=ApplicationRuntimeContext.from_system(
            workdir=Path("C:/workspace"),
            platform_name="TestOS",
            platform_release="1.0",
            current_date="2026-08-06",
        ),
    )
    tui, pipe_state, task, _output = await _start_tui(application)
    _context, pipe = pipe_state  # type: ignore[misc]
    try:
        pipe.send_text("hello\r")
        await _wait_until(
            lambda: tui._active_handle is not None and bool(provider.requests),
            attempts=500,
        )
        handle = tui._active_handle
        assert handle is not None
        run = tui._run

        await tui.shutdown()

        await _assert_tui_shutdown_cleanup(tui, run, handle)
        next_handle = run.start_turn("after shutdown")
        assert (await next_handle.result()).status is RunStatus.COMPLETED
        await tui.shutdown()
    finally:
        await _stop_tui(tui, pipe_state, task)


@pytest.mark.asyncio
@pytest.mark.parametrize("pause_case", ("user_requested", "ask_user"))
async def test_tui_shutdown_cleans_paused_or_ask_user_turn_and_is_idempotent(
    pause_case: str,
) -> None:
    ask_call = ToolCallPart(
        "ask-shutdown",
        "AskUserQuestion",
        {
            "questions": [
                {
                    "question_id": "q1",
                    "header": "Value",
                    "question": "What value should be used?",
                    "kind": "text",
                }
            ]
        },
    )
    if pause_case == "user_requested":
        provider = _ScriptedProvider(
            ((_completed("paused response"),),),
            delays=(5.0,),
        )
    else:
        provider = _ScriptedProvider(
            ((_completed("need input", ask_call, finish_reason=FinishReason.TOOL_CALLS),),)
        )
    application = UthCodeApplication(
        provider,
        runtime_context=ApplicationRuntimeContext.from_system(
            workdir=Path("C:/workspace"),
            platform_name="TestOS",
            platform_release="1.0",
            current_date="2026-08-06",
        ),
    )
    tui, pipe_state, task, _output = await _start_tui(application)
    _context, pipe = pipe_state  # type: ignore[misc]
    try:
        pipe.send_text("hello\r")
        if pause_case == "user_requested":
            await _wait_until(
                lambda: tui._active_handle is not None and bool(provider.requests),
                attempts=500,
            )
            pipe.send_text("\x1b\x1b")
            await _wait_until(
                lambda: tui._active_handle is not None
                and tui._active_handle.pending_pause is not None
                and tui.activity == "paused",
                attempts=500,
            )
        else:
            await _wait_until(
                lambda: tui.interaction.mode is InteractionMode.QUESTIONS,
                attempts=500,
            )
        handle = tui._active_handle
        assert handle is not None
        assert handle.pending_pause is not None
        run = tui._run

        await tui.shutdown()

        await _assert_tui_shutdown_cleanup(tui, run, handle)
        await tui.shutdown()
    finally:
        await _stop_tui(tui, pipe_state, task)


@pytest.mark.asyncio
async def test_tui_renderer_failure_closes_application_turn_before_dropping_handle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _ScriptedProvider(
        (
            (_completed("cancelled response"),),
            (_completed("next turn"),),
        ),
        delays=(5.0, 0.0),
    )
    application = UthCodeApplication(
        provider,
        runtime_context=ApplicationRuntimeContext.from_system(
            workdir=Path("C:/workspace"),
            platform_name="TestOS",
            platform_release="1.0",
            current_date="2026-08-06",
        ),
    )

    def fail_projection(
        self: AgentEventRenderer,
        event: object,
    ) -> RenderBatch | None:
        del self, event
        raise RuntimeError("projection failed")

    monkeypatch.setattr(AgentEventRenderer, "push", fail_projection)
    tui = UthCodeTUI(application, terminal_output=RecordingOutput())
    tui._start_generation("hello")
    handle = tui._active_handle
    task = tui._generation_task
    assert handle is not None
    assert task is not None
    run = tui._run

    await task

    await _assert_consumer_failure_cleanup(tui, run, handle, task)
    next_handle = run.start_turn("after failure")
    assert (await next_handle.result()).status is RunStatus.COMPLETED
    await tui.shutdown()


@pytest.mark.asyncio
async def test_tui_periodic_flush_failure_closes_stalled_application_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _ScriptedProvider(
        ((_completed("cancelled response"),),),
        delays=(5.0,),
    )
    application = UthCodeApplication(
        provider,
        runtime_context=ApplicationRuntimeContext.from_system(
            workdir=Path("C:/workspace"),
            platform_name="TestOS",
            platform_release="1.0",
            current_date="2026-08-06",
        ),
    )

    def fail_flush(self: AgentEventRenderer) -> RenderBatch:
        del self
        raise RuntimeError("periodic flush failed")

    monkeypatch.setattr(AgentEventRenderer, "flush", fail_flush)
    tui = UthCodeTUI(application, terminal_output=RecordingOutput())
    tui._start_generation("hello")
    handle = tui._active_handle
    task = tui._generation_task
    assert handle is not None
    assert task is not None
    run = tui._run

    await task

    await _assert_consumer_failure_cleanup(tui, run, handle, task)
    await tui.shutdown()


@pytest.mark.asyncio
async def test_tui_secondary_error_display_failure_still_closes_application_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _ScriptedProvider(
        ((_completed("cancelled response"),),),
        delays=(5.0,),
    )
    application = UthCodeApplication(
        provider,
        runtime_context=ApplicationRuntimeContext.from_system(
            workdir=Path("C:/workspace"),
            platform_name="TestOS",
            platform_release="1.0",
            current_date="2026-08-06",
        ),
    )

    def fail_projection(
        self: AgentEventRenderer,
        event: object,
    ) -> RenderBatch | None:
        del self, event
        raise RuntimeError("projection failed")

    async def fail_error_display(text: str) -> None:
        del text
        raise RuntimeError("error display failed")

    monkeypatch.setattr(AgentEventRenderer, "push", fail_projection)
    tui = UthCodeTUI(application, terminal_output=RecordingOutput())
    monkeypatch.setattr(tui, "_show_error", fail_error_display)
    tui._start_generation("hello")
    handle = tui._active_handle
    task = tui._generation_task
    assert handle is not None
    assert task is not None
    run = tui._run

    await task

    await _assert_consumer_failure_cleanup(tui, run, handle, task)
    await tui.shutdown()
    await tui.shutdown()


@pytest.mark.asyncio
async def test_tui_ask_user_projection_failure_clears_pending_waiter_and_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ask_call = ToolCallPart(
        "ask-consumer-failure",
        "AskUserQuestion",
        {
            "questions": [
                {
                    "question_id": "q1",
                    "header": "Value",
                    "question": "What value should be used?",
                    "kind": "text",
                }
            ]
        },
    )
    provider = _ScriptedProvider(
        ((_completed("need input", ask_call, finish_reason=FinishReason.TOOL_CALLS),),)
    )
    application = UthCodeApplication(
        provider,
        runtime_context=ApplicationRuntimeContext.from_system(
            workdir=Path("C:/workspace"),
            platform_name="TestOS",
            platform_release="1.0",
            current_date="2026-08-06",
        ),
    )

    def fail_open_pause(
        self: TuiInteractionState,
        pause: PauseRequest,
    ) -> None:
        del self, pause
        raise RuntimeError("interaction projection failed")

    monkeypatch.setattr(TuiInteractionState, "open_pause", fail_open_pause)
    tui = UthCodeTUI(application, terminal_output=RecordingOutput())
    tui._start_generation("hello")
    handle = tui._active_handle
    task = tui._generation_task
    assert handle is not None
    assert task is not None
    run = tui._run

    await task

    await _assert_consumer_failure_cleanup(tui, run, handle, task)
    await tui.shutdown()


@pytest.mark.asyncio
async def test_tui_pause_question_panel_submits_through_application_turn() -> None:
    call = ToolCallPart(
        "ask-1",
        "AskUserQuestion",
        {
            "questions": [
                {
                    "question_id": "q1",
                    "header": "Value",
                    "question": "What value should be used?",
                    "kind": "text",
                }
            ]
        },
    )
    provider = _ScriptedProvider(
        (
            (_completed("need input", call, finish_reason=FinishReason.TOOL_CALLS),),
            (_completed("已完成"),),
        )
    )
    application = UthCodeApplication(
        provider,
        runtime_context=ApplicationRuntimeContext.from_system(
            workdir=Path("C:/workspace"),
            platform_name="TestOS",
            platform_release="1.0",
            current_date="2026-08-06",
        ),
    )
    tui, pipe_state, task, output = await _start_tui(application)
    _context, pipe = pipe_state  # type: ignore[misc]
    try:
        pipe.send_text("hello\r")
        await _wait_until(
            lambda: tui._active_handle is not None
            and tui._active_handle.pending_pause is not None
        )
        await _wait_until(lambda: tui.activity == "paused")
        pipe.send_text("答案\r")
        await _wait_until(lambda: tui.interaction.is_review)
        pipe.send_text("\r")
        await _wait_until(lambda: tui._generation_task is None)
        assert "已完成" in output.getvalue()
        assert len(provider.requests) == 2
        assert any(
            "答案" in getattr(part, "content", "")
            for part in provider.requests[1].messages[-1].parts
        )
    finally:
        await _stop_tui(tui, pipe_state, task)


@pytest.mark.asyncio
async def test_real_tui_single_other_escape_enter_returns_to_ordinary_option(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call = ToolCallPart(
        "ask-other",
        "AskUserQuestion",
        {
            "questions": [
                {
                    "question_id": "mode",
                    "header": "Mode",
                    "question": "Choose a mode.",
                    "kind": "single_select",
                    "options": [
                        {"label": "fast", "description": "Fast"},
                        {"label": "safe", "description": "Safe"},
                    ],
                    "allow_other": True,
                }
            ]
        },
    )
    provider = _ScriptedProvider(
        (
            (_completed("need mode", call, finish_reason=FinishReason.TOOL_CALLS),),
            (_completed("done"),),
        )
    )
    application = UthCodeApplication(
        provider,
        runtime_context=ApplicationRuntimeContext.from_system(
            workdir=Path("C:/workspace"),
            platform_name="TestOS",
            platform_release="1.0",
            current_date="2026-08-06",
        ),
    )
    started_handles: list[TurnHandle] = []
    resume_calls: list[object] = []
    original_start_turn = AgentRun.start_turn
    original_resume = TurnHandle.resume

    def record_start(run: AgentRun, prompt: str) -> TurnHandle:
        handle = original_start_turn(run, prompt)
        started_handles.append(handle)
        return handle

    def record_resume(handle: TurnHandle, response: object) -> bool:
        resume_calls.append(response)
        return original_resume(handle, response)  # type: ignore[arg-type]

    monkeypatch.setattr(AgentRun, "start_turn", record_start)
    monkeypatch.setattr(TurnHandle, "resume", record_resume)
    tui, pipe_state, task, _output = await _start_tui(application)
    _context, pipe = pipe_state  # type: ignore[misc]
    try:
        pipe.send_text("hello\r")
        await _wait_until(
            lambda: tui.interaction.mode is InteractionMode.QUESTIONS,
            attempts=500,
        )
        question = tui.interaction.current_question
        assert question is not None
        tui.interaction.move(len(question.options))
        assert tui.interaction.option_index == len(question.options)
        assert tui.interaction.toggle_option() is True
        assert tui.interaction.other_mode is True
        pipe.send_text("custom-owner")
        await _wait_until(lambda: tui.buffer.text == "custom-owner")

        pipe.send_text("\x1b[27u")
        await _wait_until(
            lambda: not tui.interaction.other_mode
            and tui.buffer.text == ""
            and 0 <= tui.interaction.option_index < len(question.options),
            attempts=500,
        )
        assert tui.interaction.draft == ""
        assert tui.interaction.selected_options == set()
        assert resume_calls == []

        pipe.send_text("\r")
        await _wait_until(lambda: tui.interaction.mode is InteractionMode.REVIEW)
        assert tui.interaction.answers["mode"] == ["fast"]
        assert resume_calls == []

        pipe.send_text("\r")
        await _wait_until(
            lambda: tui._generation_task is None
            and tui._active_handle is None
            and tui.interaction.mode is InteractionMode.CLOSED
            and not tui._background_tasks,
            attempts=500,
        )
        assert len(started_handles) == 1
        assert len(provider.requests) == 2
        assert len(resume_calls) == 1
        response = resume_calls[0]
        assert type(response).__name__ == "UserInputResponse"
        assert response.answers["mode"] == ["fast"]  # type: ignore[union-attr]
        assert provider.requests[1].messages[-1].parts == (
            ToolResultPart("ask-other", '{"answers": {"mode": ["fast"]}}'),
        )
        assert "custom-owner" not in provider.requests[1].messages[-1].parts[0].content
    finally:
        await _stop_tui(tui, pipe_state, task)


@pytest.mark.asyncio
async def test_real_tui_question_back_restores_buffer_and_draft_without_resuming(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call = ToolCallPart(
        "ask-text",
        "AskUserQuestion",
        {
            "questions": [
                {
                    "question_id": "q1",
                    "header": "First",
                    "question": "First answer?",
                    "kind": "text",
                },
                {
                    "question_id": "q2",
                    "header": "Second",
                    "question": "Second answer?",
                    "kind": "text",
                },
            ]
        },
    )
    provider = _ScriptedProvider(
        (
            (_completed("need answers", call, finish_reason=FinishReason.TOOL_CALLS),),
            (_completed("answers accepted"),),
        )
    )
    application = UthCodeApplication(
        provider,
        runtime_context=ApplicationRuntimeContext.from_system(
            workdir=Path("C:/workspace"),
            platform_name="TestOS",
            platform_release="1.0",
            current_date="2026-08-06",
        ),
    )
    resume_calls: list[object] = []
    original_resume = TurnHandle.resume

    def record_resume(handle: TurnHandle, response: object) -> bool:
        resume_calls.append(response)
        return original_resume(handle, response)  # type: ignore[arg-type]

    monkeypatch.setattr(TurnHandle, "resume", record_resume)
    tui, pipe_state, task, _output = await _start_tui(application)
    _context, pipe = pipe_state  # type: ignore[misc]
    try:
        pipe.send_text("hello\r")
        await _wait_until(lambda: tui.interaction.mode is InteractionMode.QUESTIONS)
        pipe.send_text("answer-one\r")
        await _wait_until(lambda: tui.interaction.question_index == 1)
        pipe.send_text("answer-two\r")
        await _wait_until(lambda: tui.interaction.is_review)
        assert provider.requests and len(provider.requests) == 1

        await asyncio.sleep(0.05)
        pipe.send_text("\x1b[27u")
        await _wait_until(
            lambda: tui.interaction.mode is InteractionMode.QUESTIONS
            and tui.interaction.current_question is not None
            and tui.interaction.current_question.question_id == "q2"
            and tui.buffer.text == "answer-two"
        )
        assert tui.buffer.cursor_position == len("answer-two")
        assert tui.interaction.draft == "answer-two"
        assert tui.interaction.answers["q2"] == ["answer-two"]
        assert resume_calls == []

        pipe.send_text("\r")
        await _wait_until(lambda: tui.interaction.is_review)
        assert tui.interaction.answers["q2"] == ["answer-two"]
        assert len(provider.requests) == 1
        assert resume_calls == []

        await asyncio.sleep(0.05)
        pipe.send_text("\x1b[27u")
        await _wait_until(lambda: tui.buffer.text == "answer-two")
        tui.buffer.set_document(
            Document("answer-new", len("answer-new")),
            bypass_readonly=True,
        )
        pipe.send_text("\r")
        await _wait_until(lambda: tui.interaction.is_review)
        assert tui.interaction.answers["q2"] == ["answer-new"]
        assert len(provider.requests) == 1
        assert resume_calls == []

        pipe.send_text("\r")
        await _wait_until(
            lambda: tui._generation_task is None
            and tui._active_handle is None
            and not tui._background_tasks
        )
        assert len(provider.requests) == 2
        assert len(resume_calls) == 1
        assert type(resume_calls[0]).__name__ == "UserInputResponse"
    finally:
        await _stop_tui(tui, pipe_state, task)


@pytest.mark.asyncio
async def test_real_tui_question_back_restores_other_and_selection_state() -> None:
    call = ToolCallPart(
        "ask-options",
        "AskUserQuestion",
        {
            "questions": [
                {
                    "question_id": "text",
                    "header": "Text",
                    "question": "Describe it.",
                    "kind": "text",
                },
                {
                    "question_id": "single",
                    "header": "Mode",
                    "question": "Choose one.",
                    "kind": "single_select",
                    "options": [
                        {"label": "fast", "description": "Fast"},
                        {"label": "safe", "description": "Safe"},
                    ],
                },
                {
                    "question_id": "multi",
                    "header": "Targets",
                    "question": "Choose many.",
                    "kind": "multi_select",
                    "options": [
                        {"label": "api", "description": "API"},
                        {"label": "ui", "description": "UI"},
                    ],
                },
                {
                    "question_id": "other",
                    "header": "Owner",
                    "question": "Who owns it?",
                    "kind": "single_select",
                    "options": [
                        {"label": "team", "description": "The team"},
                        {"label": "me", "description": "The user"},
                    ],
                    "allow_other": True,
                },
            ]
        },
    )
    provider = _ScriptedProvider(
        ((_completed("need options", call, finish_reason=FinishReason.TOOL_CALLS),),)
    )
    application = UthCodeApplication(
        provider,
        runtime_context=ApplicationRuntimeContext.from_system(
            workdir=Path("C:/workspace"),
            platform_name="TestOS",
            platform_release="1.0",
            current_date="2026-08-06",
        ),
    )
    tui, pipe_state, task, _output = await _start_tui(application)
    _context, pipe = pipe_state  # type: ignore[misc]
    try:
        pipe.send_text("hello\r")
        await _wait_until(lambda: tui.interaction.mode is InteractionMode.QUESTIONS)
        pipe.send_text("description\r")
        await _wait_until(
            lambda: tui.interaction.current_question is not None
            and tui.interaction.current_question.question_id == "single"
        )

        tui.interaction.move(1)
        tui.interaction.toggle_option()
        pipe.send_text("\r")
        await _wait_until(
            lambda: tui.interaction.current_question is not None
            and tui.interaction.current_question.question_id == "multi"
        )
        tui.interaction.toggle_option()
        tui.interaction.move(1)
        tui.interaction.toggle_option()
        pipe.send_text("\r")
        await _wait_until(
            lambda: tui.interaction.current_question is not None
            and tui.interaction.current_question.question_id == "other"
        )

        tui.interaction.move(2)
        tui.interaction.toggle_option()
        pipe.send_text("custom-owner\r")
        await _wait_until(lambda: tui.interaction.is_review)

        await asyncio.sleep(0.05)
        pipe.send_text("\x1b[27u")
        await _wait_until(
            lambda: tui.interaction.current_question is not None
            and tui.interaction.current_question.question_id == "other"
            and tui.interaction.other_mode
            and tui.buffer.text == "custom-owner"
        )
        assert tui.buffer.cursor_position == len("custom-owner")

        pipe.send_text("\x1b[D")
        await _wait_until(
            lambda: tui.interaction.current_question is not None
            and tui.interaction.current_question.question_id == "multi"
        )
        assert tui.interaction.selected_options == {0, 1}
        assert tui.buffer.text == ""

        pipe.send_text("\x1b[D")
        await _wait_until(
            lambda: tui.interaction.current_question is not None
            and tui.interaction.current_question.question_id == "single"
        )
        assert tui.interaction.selected_options == {1}
        assert tui.buffer.text == ""
        assert len(provider.requests) == 1
    finally:
        await _stop_tui(tui, pipe_state, task)


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [NetworkError("network"), RateLimitError("rate")])
async def test_tui_provider_retry_pilot_uses_one_turn_and_cleans_up(
    error: NetworkError | RateLimitError,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _ProviderFailureThenSuccess(error, (_completed("retry succeeded"),))
    application = UthCodeApplication(
        provider,
        runtime_context=ApplicationRuntimeContext.from_system(
            workdir=Path("C:/workspace"),
            platform_name="TestOS",
            platform_release="1.0",
            current_date="2026-08-06",
        ),
    )
    started_prompts: list[str] = []
    original_start_turn = AgentRun.start_turn
    resume_calls: list[object] = []

    def record_start(run: AgentRun, prompt: str):  # type: ignore[no-untyped-def]
        started_prompts.append(prompt)
        return original_start_turn(run, prompt)

    original_resume = TurnHandle.resume

    def record_resume(handle: TurnHandle, response: object) -> bool:
        resume_calls.append(response)
        return original_resume(handle, response)  # type: ignore[arg-type]

    monkeypatch.setattr(AgentRun, "start_turn", record_start)
    monkeypatch.setattr(TurnHandle, "resume", record_resume)
    tui, pipe_state, task, output = await _start_tui(application)
    _context, pipe = pipe_state  # type: ignore[misc]
    try:
        pipe.send_text("hello\r")
        await _wait_until(
            lambda: tui.interaction.mode is InteractionMode.PAUSE_ACTION
            and len(provider.requests) == 1
        )
        pipe.send_text("\r")
        await _wait_until(
            lambda: tui._generation_task is None
            and tui._active_handle is None
            and tui.interaction.mode is InteractionMode.CLOSED
            and not tui._background_tasks
        )
        assert len(started_prompts) == 1
        assert len(provider.requests) == 2
        assert len(resume_calls) == 1
        assert isinstance(resume_calls[0], RetryProviderResponse)
        assert "retry succeeded" in output.getvalue()
    finally:
        await _stop_tui(tui, pipe_state, task)


@pytest.mark.asyncio
async def test_tui_provider_cancel_pilot_stops_retry_and_cleans_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _ProviderFailureThenSuccess(
        NetworkError("network"),
        (_completed("must not run"),),
    )
    application = UthCodeApplication(
        provider,
        runtime_context=ApplicationRuntimeContext.from_system(
            workdir=Path("C:/workspace"),
            platform_name="TestOS",
            platform_release="1.0",
            current_date="2026-08-06",
        ),
    )
    started_prompts: list[str] = []
    original_start_turn = AgentRun.start_turn
    resume_calls: list[object] = []
    cancel_calls = 0

    def record_start(run: AgentRun, prompt: str):  # type: ignore[no-untyped-def]
        started_prompts.append(prompt)
        return original_start_turn(run, prompt)

    original_resume = TurnHandle.resume
    original_cancel = TurnHandle.cancel

    def record_resume(handle: TurnHandle, response: object) -> bool:
        resume_calls.append(response)
        return original_resume(handle, response)  # type: ignore[arg-type]

    def record_cancel(handle: TurnHandle) -> bool:
        nonlocal cancel_calls
        cancel_calls += 1
        return original_cancel(handle)

    monkeypatch.setattr(AgentRun, "start_turn", record_start)
    monkeypatch.setattr(TurnHandle, "resume", record_resume)
    monkeypatch.setattr(TurnHandle, "cancel", record_cancel)
    tui, pipe_state, task, output = await _start_tui(application)
    _context, pipe = pipe_state  # type: ignore[misc]
    try:
        pipe.send_text("hello\r")
        await _wait_until(
            lambda: tui.interaction.mode is InteractionMode.PAUSE_ACTION
            and len(provider.requests) == 1
        )
        tui.interaction.move(1)
        pipe.send_text("\r")
        await _wait_until(
            lambda: tui._generation_task is None
            and tui._active_handle is None
            and tui.interaction.mode is InteractionMode.CLOSED
            and not tui._background_tasks
        )
        assert len(started_prompts) == 1
        assert len(provider.requests) == 1
        assert resume_calls == []
        assert cancel_calls == 1
        assert "保存" not in output.getvalue()
        assert "retry succeeded" not in output.getvalue()
    finally:
        await _stop_tui(tui, pipe_state, task)


def test_transient_height_budget_fits_small_terminal() -> None:
    tui = UthCodeTUI(_application(), terminal_output=RecordingOutput())
    tui._terminal_size = lambda: (40, 5)  # type: ignore[method-assign]
    tui.picker.replace(
        (ModelProfile("fake/model", "fake", "model", "Fake"),),
        "fake/model",
    )
    assert (
        tui._candidate_height()
        + tui._composer_height()
        + tui._preview_height()
        + 1
        <= 5
    )
    tui._streams["pending"] = _StreamProjection(
        MarkdownStream(pending="still generating"),
        "assistant",
    )
    tui._terminal_size = lambda: (40, 3)  # type: ignore[method-assign]
    assert tui._preview_height() == 0
    assert not tui._has_preview()


@pytest.mark.asyncio
async def test_stalled_stream_delta_reaches_temporary_preview(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _ScriptedProvider(
        ((_completed("done"),),),
        delays=(0.2,),
    )
    application = UthCodeApplication(
        provider,
        runtime_context=ApplicationRuntimeContext.from_system(
            workdir=Path("C:/workspace"),
            platform_name="TestOS",
            platform_release="1.0",
            current_date="2026-08-06",
        ),
    )
    original_flush = AgentEventRenderer.flush
    sent = False

    def flush_with_partial(renderer: AgentEventRenderer) -> RenderBatch:
        nonlocal sent
        if not sent:
            sent = True
            return RenderBatch(
                text=(TextUpdate("assistant", "assistant", "partial"),)
            )
        return original_flush(renderer)

    monkeypatch.setattr(AgentEventRenderer, "flush", flush_with_partial)
    tui = UthCodeTUI(application, terminal_output=RecordingOutput())
    tui._start_generation("hello")
    task = tui._generation_task
    assert task is not None

    await _wait_until(lambda: tui._pending_text() == "partial")
    await tui.shutdown()
    await task


@pytest.mark.asyncio
async def test_interaction_error_is_visible_and_input_can_continue() -> None:
    output = RecordingOutput()
    tui = UthCodeTUI(_application(), terminal_output=output)

    async def fail() -> None:
        raise ValueError("bad input")

    tui._spawn(fail())
    await _wait_until(lambda: not tui._background_tasks)
    assert "界面操作失败：ValueError；可以继续输入" in output.getvalue()
    assert not tui._closing


@pytest.mark.asyncio
async def test_clear_keeps_scrollback_and_run_but_resets_projection() -> None:
    output = RecordingOutput()
    tui = UthCodeTUI(_application(), terminal_output=output)
    run = tui._run
    tui._streams["x"] = _StreamProjection(
        MarkdownStream(pending="preview"),
        "assistant",
    )
    await tui._clear_viewport()
    assert tui._run is run
    assert not tui._streams
    assert CLEAR_VIEWPORT in output.getvalue()
    assert "\x1b[3J" not in output.getvalue()
    assert "上方终端历史仍保留" in output.getvalue()


@pytest.mark.asyncio
async def test_each_turn_discards_previous_transient_stream_projection() -> None:
    tui = UthCodeTUI(_application(), terminal_output=RecordingOutput())
    tui._streams["old-turn"] = _StreamProjection(
        MarkdownStream(pending="stale preview"),
        "assistant",
        started=True,
        open=True,
    )

    tui._start_generation("new turn")
    assert "old-turn" not in tui._streams
    assert tui._generation_task is not None
    await tui._generation_task


@pytest.mark.asyncio
async def test_authoritative_correction_appends_without_rewriting() -> None:
    output = RecordingOutput()
    tui = UthCodeTUI(_application(), terminal_output=output)
    await tui._apply_batch(
        RenderBatch(
            text=(TextUpdate("m:assistant", "assistant", "partial\n\n"),),
        )
    )
    await tui._flush_streams()
    await tui._apply_batch(
        RenderBatch(
            text=(
                TextUpdate(
                    "m:assistant",
                    "assistant",
                    "authoritative",
                    mode="replace",
                ),
            ),
        )
    )
    rendered = output.getvalue()
    assert "partial" in rendered
    assert "响应已修正" in rendered
    assert "authoritative" in rendered


@pytest.mark.asyncio
async def test_final_answer_renders_once_instead_of_one_role_block_per_paragraph() -> None:
    output = RecordingOutput()
    tui = UthCodeTUI(_application(), terminal_output=output)
    await tui._apply_batch(
        RenderBatch(
            text=(
                TextUpdate(
                    "m:assistant",
                    "assistant",
                    "第一段。\n\n第二段。\n\n- 项目一\n- 项目二\n",
                ),
            )
        )
    )
    partial = output.getvalue()
    assert partial.count("UthCode:") == 1
    assert "第一段" in partial and "第二段" in partial
    assert "项目二" not in partial
    await tui._apply_batch(
        RenderBatch(
            terminal="completed",
            final_text="第一段。\n\n第二段。\n\n- 项目一\n- 项目二\n",
        )
    )
    rendered = output.getvalue()
    assert rendered.count("UthCode:") == 1
    assert "第一段" in rendered and "第二段" in rendered and "项目二" in rendered


@pytest.mark.asyncio
async def test_running_tool_is_transient_and_terminal_tool_commits_once() -> None:
    output = RecordingOutput()
    tui = UthCodeTUI(_application(), terminal_output=output)
    running = RenderBatch(
        tools=(ToolUpdate("t", "Bash", "dir", "running"),),
    )
    await tui._apply_batch(running)
    assert tui.activity == "running Bash: dir"
    assert "running Bash" not in output.getvalue()
    finished = RenderBatch(
        tools=(ToolUpdate("t", "Bash", "dir", "finished"),),
    )
    await tui._apply_batch(finished)
    assert output.getvalue().count("finished") == 1


def test_source_and_dependencies_have_no_textual_blessed_or_removed_assets() -> None:
    root = Path(__file__).parents[1]
    tui_root = root / "src/uthcode/interfaces/tui"
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in tui_root.glob("*.py")
    )
    assert "textual" not in source.casefold()
    assert "blessed" not in source.casefold()
    assert not (tui_root / "tui.tcss").exists()
    assert not (tui_root / "widgets.py").exists()
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    assert "textual" not in pyproject.casefold()
    assert "blessed" not in pyproject.casefold()
    assert "prompt_toolkit>=3.0.52,<4" in pyproject
