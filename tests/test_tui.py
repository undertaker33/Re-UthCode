from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
from prompt_toolkit.input.defaults import create_pipe_input
from prompt_toolkit.document import Document
from prompt_toolkit.layout import VSplit
from prompt_toolkit.output import DummyOutput

from uthcode.application import (
    ApplicationRuntimeContext,
    GenerationCompleted,
    Message,
    ModelProfile,
    ProviderResponse,
    TextDelta,
    TextPart,
    Usage,
    UthCodeApplication,
)
from uthcode.core.provider import FinishReason
from uthcode.integrations.providers.fake import FakeProvider
from uthcode.interfaces.tui.app import (
    UthCodeTUI,
    _StreamProjection,
    _tail_for_preview,
    _window_start,
)
from uthcode.interfaces.tui.rendering import (
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


def _completed(text: str = "done") -> GenerationCompleted:
    return GenerationCompleted(
        ProviderResponse(
            message=Message("assistant", (TextPart(text),)),
            usage=Usage(),
            finish_reason=FinishReason.STOP,
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
async def test_stalled_stream_delta_reaches_temporary_preview() -> None:
    class FlushProbe:
        interval_seconds = 0.01

        def __init__(self) -> None:
            self.sent = False

        def flush(self) -> RenderBatch:
            if self.sent:
                return RenderBatch()
            self.sent = True
            return RenderBatch(
                text=(TextUpdate("assistant", "assistant", "partial"),)
            )

    tui = UthCodeTUI(_application(), terminal_output=RecordingOutput())
    probe = FlushProbe()
    task = asyncio.create_task(tui._flush_renderer_periodically(probe))  # type: ignore[arg-type]
    try:
        await _wait_until(lambda: tui._pending_text() == "partial")
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
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
