from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterable
from pathlib import Path

import pytest

from uthcode.application import (
    ApplicationRuntimeContext,
    ArgumentSpec,
    CommandDefinition,
    CommandKind,
    CompletionCandidate,
    EffectiveConfig,
    GenerationCompleted,
    LaunchOptions,
    Message,
    ModelProfile,
    ProviderIdentity,
    ProviderKind,
    ProviderProfile,
    ProviderResponse,
    ReasoningDelta,
    TextDelta,
    TextPart,
    UthCodeApplication,
    Usage,
    create_application,
    load_effective_config,
)
from uthcode.core.provider import (
    CancellationToken,
    FinishReason,
    GenerationCancelled,
    GenerationRequest,
    NetworkError,
    ProviderEvent,
    ReasoningPart,
    ToolCallPart,
    ToolDefinition,
)
from uthcode.core.tool import ToolExecutionResult
from uthcode.integrations.providers.fake import FakeProvider
from uthcode.interfaces.tui.app import UthCodeTUI
from uthcode.interfaces.tui.completion import (
    CommandCompletionMenu,
    CompletionMenuItem,
    CompletionMenuState,
)
from uthcode.interfaces.tui.picker import ModelPicker, ModelPickerState
from uthcode.interfaces.tui.rendering import AgentEventRenderer
from uthcode.interfaces.tui.state import (
    EscArmState,
    ScrollFollowState,
    TranscriptEntryKind,
    TranscriptState,
)
from uthcode.interfaces.tui.widgets import (
    AgentTextBlock,
    ComposerTextArea,
    SelectableMarkdown,
    ToolActivityRow,
    TranscriptWidget,
    UserMessageBlock,
)


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


def _application(
    *,
    events: tuple[object, ...] = (_completed("fake response"),),
    delay: float = 0.0,
) -> UthCodeApplication:
    return UthCodeApplication(
        FakeProvider(events=events, delay=delay),  # type: ignore[arg-type]
    )


class _ScriptedProvider(FakeProvider):
    def __init__(self, scripts: Iterable[Iterable[ProviderEvent]], *, delay: float = 0.0) -> None:
        super().__init__(delay=delay)
        self._script_delay = delay
        self._scripts = tuple(tuple(script) for script in scripts)

    async def stream(
        self,
        request: GenerationRequest,
        *,
        cancellation: CancellationToken,
    ) -> AsyncIterator[ProviderEvent]:
        self.requests.append(request)
        cancellation.raise_if_cancelled()
        if self._script_delay:
            await asyncio.sleep(self._script_delay)
        index = min(len(self.requests) - 1, len(self._scripts) - 1)
        for event in self._scripts[index]:
            cancellation.raise_if_cancelled()
            yield event


class _TurnGateProvider(FakeProvider):
    """Hold a turn at a provider boundary until the test explicitly releases it."""

    def __init__(
        self,
        events: Iterable[ProviderEvent],
        *,
        released: bool = False,
    ) -> None:
        super().__init__()
        self._events = tuple(events)
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.terminal_emitted = asyncio.Event()
        if released:
            self.release.set()

    async def stream(
        self,
        request: GenerationRequest,
        *,
        cancellation: CancellationToken,
    ) -> AsyncIterator[ProviderEvent]:
        self.requests.append(request)
        cancellation.raise_if_cancelled()
        self.entered.set()
        await self.release.wait()
        cancellation.raise_if_cancelled()
        for event in self._events:
            cancellation.raise_if_cancelled()
            yield event
        self.terminal_emitted.set()


class _AuthoritativeCorrectionProvider(FakeProvider):
    """Emit visible partial text, then wait before the authoritative terminal text."""

    def __init__(self) -> None:
        super().__init__()
        self.partial_emitted = asyncio.Event()
        self.release = asyncio.Event()
        self.terminal_emitted = asyncio.Event()

    async def stream(
        self,
        request: GenerationRequest,
        *,
        cancellation: CancellationToken,
    ) -> AsyncIterator[ProviderEvent]:
        self.requests.append(request)
        cancellation.raise_if_cancelled()
        yield TextDelta("partial-text")
        self.partial_emitted.set()
        await self.release.wait()
        cancellation.raise_if_cancelled()
        yield _completed("authoritative-final")
        self.terminal_emitted.set()


class _ImmediatePauseProvider:
    """Emit one Provider event immediately, then pause before terminal output."""

    def __init__(
        self,
        first_event: object,
        *,
        pause: float = 0.5,
        error: NetworkError | None = None,
        wait_for_cancel: bool = False,
    ) -> None:
        self.identity = ProviderIdentity("fake", "script", "paused-model")
        self.first_event = first_event
        self.pause = pause
        self.error = error
        self.wait_for_cancel = wait_for_cancel
        self.requests: list[GenerationRequest] = []

    async def stream(
        self,
        request: GenerationRequest,
        *,
        cancellation: CancellationToken,
    ) -> AsyncIterator[ProviderEvent]:
        self.requests.append(request)
        yield self.first_event  # type: ignore[misc]
        if self.wait_for_cancel:
            while not cancellation.cancelled:
                await asyncio.sleep(0.01)
            raise GenerationCancelled()
        await asyncio.sleep(self.pause)
        if self.error is not None:
            raise self.error
        yield _completed("finished")


class _DisplayBashTool:
    definition = ToolDefinition(
        "Bash",
        "Run a display-only test command.",
        {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
            "additionalProperties": False,
        },
    )

    async def execute(
        self,
        arguments: dict[str, object],
        *,
        cancellation: CancellationToken,
    ) -> ToolExecutionResult:
        del arguments, cancellation
        return ToolExecutionResult("TUI-TOOL-RESULT-SENTINEL")


def _application_from_provider(provider: object) -> UthCodeApplication:
    return UthCodeApplication(provider)  # type: ignore[arg-type]


async def _wait_until(pilot, predicate, *, attempts: int = 30) -> None:  # type: ignore[no-untyped-def]
    for _ in range(attempts):
        await pilot.pause(0.05)
        if predicate():
            return
    raise AssertionError("condition did not become true")


def test_state_models_cover_display_entries_and_reset_scroll() -> None:
    state = TranscriptState()
    for kind in TranscriptEntryKind:
        state.add(kind, kind.value)

    assert [entry.kind for entry in state.entries] == list(TranscriptEntryKind)
    state.widgets["message"] = object()
    state.tool_rows["tool"] = object()
    state.active_turn_id = "turn"
    state.cancel_prompt = "again"
    state.scroll.follow = False
    state.clear()

    assert state.entries == []
    assert state.widgets == {}
    assert state.tool_rows == {}
    assert state.active_turn_id is None
    assert state.cancel_prompt is None
    assert state.scroll.follow is True


def test_scroll_and_double_escape_state_are_time_bound() -> None:
    scroll = ScrollFollowState()
    scroll.observe(0, 20)
    assert scroll.follow is False
    scroll.observe(20, 20)
    assert scroll.follow is True

    esc = EscArmState()
    esc.arm(10.0)
    assert esc.consume(10.5) is True
    esc.arm(10.0)
    assert esc.consume(11.1) is False


@pytest.mark.asyncio
async def test_agent_event_renderer_batches_text_and_flushes_terminal() -> None:
    provider = FakeProvider(
        events=(TextDelta("a"), TextDelta("b"), _completed("ab")),
    )
    handle = UthCodeApplication(provider).create_run().start_turn("hello")
    events = [event async for event in handle.events()]
    text_events = [
        event
        for event in events
        if event.event_type == "assistant_message_delta"
    ]
    completed = next(event for event in events if event.event_type == "turn_completed")

    now = [0.0]
    renderer = AgentEventRenderer(clock=lambda: now[0])
    assert renderer.push(text_events[0]) is None
    now[0] = 0.21
    batch = renderer.push(text_events[1])
    assert batch is not None
    assert batch.text[0].text == "ab"

    terminal = renderer.push(completed)
    assert terminal is not None
    assert terminal.terminal == "completed"
    assert terminal.text == ()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("terminal_text", "expected_mode", "expected_text"),
    (
        ("partial-text", None, ""),
        ("partial-text-final", "append", "-final"),
        ("authoritative-final", "replace", "authoritative-final"),
    ),
)
async def test_agent_event_renderer_classifies_authoritative_text_updates(
    terminal_text: str,
    expected_mode: str | None,
    expected_text: str,
) -> None:
    provider = FakeProvider(events=(TextDelta("partial-text"), _completed(terminal_text)))
    handle = UthCodeApplication(provider).create_run().start_turn("hello")
    events = [event async for event in handle.events()]
    delta = next(event for event in events if event.event_type == "assistant_message_delta")
    completed = next(
        event for event in events if event.event_type == "assistant_message_completed"
    )

    now = [0.0]
    renderer = AgentEventRenderer(clock=lambda: now[0])
    assert renderer.push(delta) is None
    now[0] = 0.21
    streamed = renderer.flush()
    assert [(update.mode, update.text) for update in streamed.text] == [
        ("append", "partial-text")
    ]

    terminal = renderer.push(completed)
    assert terminal is not None
    if expected_mode is None:
        assert terminal.text == ()
    else:
        assert [(update.mode, update.text) for update in terminal.text] == [
            (expected_mode, expected_text)
        ]


def test_completion_and_picker_have_separate_state_and_widget_types() -> None:
    assert CompletionMenuState is not ModelPickerState
    assert CommandCompletionMenu is not ModelPicker
    assert CompletionMenuItem is not CompletionCandidate


@pytest.mark.asyncio
async def test_tui_projects_user_reasoning_and_final_with_visual_hierarchy() -> None:
    context = ApplicationRuntimeContext.from_system(
        workdir=Path("C:/workspace"),
        platform_name="TestOS",
        platform_release="1.0",
        current_date="2026-08-05",
    )
    application = UthCodeApplication(
        FakeProvider(
            events=(
                ReasoningDelta("thinking"),
                TextDelta("hello"),
                _completed("hello", ReasoningPart("thinking")),
            )
        ),
        runtime_context=context,
    )
    tui = UthCodeTUI(application)

    async with tui.run_test() as pilot:
        composer = tui.query_one(ComposerTextArea)
        composer.focus()
        composer.text = "hello"
        await pilot.press("enter")
        await _wait_until(
            pilot,
            lambda: tui.query_one("#activity").render().plain == "ready",
        )

        transcript = tui.query_one(TranscriptWidget)
        assert [entry.kind for entry in transcript.state.entries] == [
            TranscriptEntryKind.USER,
            TranscriptEntryKind.REASONING,
            TranscriptEntryKind.ASSISTANT,
        ]
        assert transcript.state.entries[-1].text == "hello"
        user = tui.query_one(UserMessageBlock)
        assert "user-message-block" in user.classes
        assert len(tui.query(AgentTextBlock)) == 2
        assert len(tui.query(SelectableMarkdown)) == 2
        assert all(not widget.styles.text_style.italic for widget in tui.query(AgentTextBlock))
        assert all(not widget.styles.text_style.dim for widget in tui.query(AgentTextBlock))
        assert "reasoning-entry" not in tui.query_one(AgentTextBlock).classes
        assert "UthCode" in tui.query_one("#topbar").render().plain

    css = Path(__file__).parents[1] / "src/uthcode/interfaces/tui/tui.tcss"
    css_text = css.read_text(encoding="utf-8")
    assert "$text" in css_text
    assert "$text-muted" in css_text
    assert "background: $panel" in css_text
    assert "text-style: italic" not in css_text


@pytest.mark.asyncio
async def test_tui_replaces_flushed_partial_with_authoritative_terminal_text() -> None:
    provider = _AuthoritativeCorrectionProvider()
    tui = UthCodeTUI(_application_from_provider(provider))

    async with tui.run_test() as pilot:
        composer = tui.query_one(ComposerTextArea)
        composer.focus()
        composer.text = "hello"
        await pilot.press("enter")

        await provider.partial_emitted.wait()
        await pilot.pause(0.25)
        transcript = tui.query_one(TranscriptWidget)
        assistant_entries = [
            entry
            for entry in transcript.state.entries
            if entry.kind is TranscriptEntryKind.ASSISTANT
        ]
        assert [entry.text for entry in assistant_entries] == ["partial-text"]

        provider.release.set()
        await provider.terminal_emitted.wait()
        while tui._active_handle is not None or tui._generation_task is not None:
            await pilot.pause()

        assistant_widgets = [
            widget for widget in tui.query(AgentTextBlock) if widget.kind == "assistant"
        ]
        assert len(assistant_widgets) == 1
        assistant = assistant_widgets[0]

        def assistant_dom_text() -> str:
            return "".join(str(child.render()) for child in assistant.query("*"))

        while not assistant_dom_text():
            await pilot.pause()
        dom_text = assistant_dom_text()
        assistant_entries = [
            entry
            for entry in transcript.state.entries
            if entry.kind is TranscriptEntryKind.ASSISTANT
        ]
        assert [entry.text for entry in assistant_entries] == ["authoritative-final"]
        assert dom_text == "authoritative-final"
        assert assistant_entries[0].text == dom_text
        assert "partial-textauthoritative-final" not in dom_text
        assert all("partial-text" not in entry.text for entry in transcript.state.entries)
        transcript_dom_text = "".join(
            str(child.render()) for child in transcript.query("*")
        )
        assert "partial-text" not in transcript_dom_text
        assert transcript_dom_text.count("authoritative-final") == 1
        assert tui.query_one("#activity").render().plain == "ready"
        assert tui._stream_timer is None
        assert tui._active_handle is None
        assert tui._generation_task is None


@pytest.mark.asyncio
async def test_tui_uses_one_run_for_multiple_turns_and_preserves_conversation() -> None:
    provider = _ScriptedProvider(
        (
            (_completed("first answer"),),
            (_completed("second answer"),),
        )
    )
    tui = UthCodeTUI(_application_from_provider(provider))

    async with tui.run_test() as pilot:
        composer = tui.query_one(ComposerTextArea)
        composer.focus()
        composer.text = "first"
        await pilot.press("enter")
        await _wait_until(
            pilot,
            lambda: tui.query_one("#activity").render().plain == "ready",
        )

        composer.text = "second"
        await pilot.press("enter")
        await _wait_until(
            pilot,
            lambda: tui.query_one("#activity").render().plain == "ready"
            and len(provider.requests) == 2,
        )

    assert len(provider.requests) == 2
    assert [
        part.text
        for message in provider.requests[1].messages
        for part in message.parts
        if isinstance(getattr(part, "text", None), str)
    ] == ["first", "first answer", "second"]


@pytest.mark.asyncio
async def test_clear_only_clears_display_and_next_turn_keeps_conversation() -> None:
    provider = _ScriptedProvider(
        (
            (_completed("first answer"),),
            (_completed("second answer"),),
        )
    )
    tui = UthCodeTUI(_application_from_provider(provider))

    async with tui.run_test() as pilot:
        composer = tui.query_one(ComposerTextArea)
        composer.focus()
        composer.text = "first"
        await pilot.press("enter")
        await _wait_until(
            pilot,
            lambda: tui.query_one("#activity").render().plain == "ready",
        )

        composer.text = "/clear"
        await pilot.press("enter")
        await pilot.pause()
        assert tui.query_one(TranscriptWidget).state.entries == []

        composer.text = "second"
        await pilot.press("enter")
        await _wait_until(
            pilot,
            lambda: tui.query_one("#activity").render().plain == "ready"
            and len(provider.requests) == 2,
        )

    assert len(provider.requests[1].messages) == 3
    assert provider.requests[1].messages[-1].parts[0].text == "second"


@pytest.mark.asyncio
async def test_tui_tool_rows_use_application_summary_and_hide_tool_result(tmp_path: Path) -> None:
    sentinel = "TUI-TOOL-RESULT-SENTINEL"
    note = tmp_path / "note.txt"
    note.write_text(sentinel + "\n", encoding="utf-8")
    call = ToolCallPart("read-1", "ReadFile", {"path": "note.txt"})
    provider = _ScriptedProvider(
        (
            (_completed("reading", call, finish_reason=FinishReason.TOOL_CALLS),),
            (_completed("final answer"),),
        )
    )
    config = EffectiveConfig.single_model(
        "local/ref",
        provider_profile_id="local",
        provider_kind=ProviderKind.FAKE,
        remote_model_id="fake-model",
    )
    application = create_application(
        config,
        provider_builder=lambda _provider, _model: provider,
        runtime_context=ApplicationRuntimeContext.from_system(workdir=tmp_path),
    )
    tui = UthCodeTUI(application)

    async with tui.run_test() as pilot:
        composer = tui.query_one(ComposerTextArea)
        composer.focus()
        composer.text = "read note"
        await pilot.press("enter")
        await _wait_until(
            pilot,
            lambda: tui.query_one("#activity").render().plain == "ready",
        )

        row = tui.query_one(ToolActivityRow)
        assert row.status == "finished"
        assert row.tool_name == "ReadFile"
        assert row.command == "ReadFile note.txt"
        assert sentinel not in row.render().plain
        assert all(sentinel not in entry.text for entry in tui.query_one(TranscriptWidget).state.entries)
        assert sentinel not in tui._run.snapshot().to_json()
        assert not tui.query("Button")


@pytest.mark.asyncio
async def test_tui_long_tool_command_is_already_truncated_before_rendering() -> None:
    long_command = "echo " + ("x" * 500)
    call = ToolCallPart("bash-1", "Bash", {"command": long_command})
    provider = _ScriptedProvider(
        (
            (_completed("running", call, finish_reason=FinishReason.TOOL_CALLS),),
            (_completed("done"),),
        )
    )
    config = EffectiveConfig.single_model(
        "local/ref",
        provider_profile_id="local",
        provider_kind=ProviderKind.FAKE,
        remote_model_id="fake-model",
    )
    application = create_application(
        config,
        provider_builder=lambda _provider, _model: provider,
        runtime_context=ApplicationRuntimeContext.from_system(workdir=Path.cwd()),
        tools=(_DisplayBashTool(),),
    )
    tui = UthCodeTUI(application)

    async with tui.run_test() as pilot:
        composer = tui.query_one(ComposerTextArea)
        composer.focus()
        composer.text = "run"
        await pilot.press("enter")
        await _wait_until(
            pilot,
            lambda: tui.query_one("#activity").render().plain == "ready",
        )

        row = tui.query_one(ToolActivityRow)
        assert len(row.command) <= 240
        assert long_command not in row.render().plain
        assert "echo" in row.command


@pytest.mark.asyncio
@pytest.mark.parametrize("_iteration", range(5))
async def test_tui_active_turn_rejects_prompt_and_model_switch_then_switches_next_turn(
    _iteration: int,
) -> None:
    config = EffectiveConfig(
        model="one/ref",
        providers={"local": ProviderProfile("local", ProviderKind.FAKE)},
        models={
            "one/ref": ModelProfile("one/ref", "local", "one"),
            "two/ref": ModelProfile("two/ref", "local", "two"),
        },
    )
    providers: dict[str, _TurnGateProvider] = {
        "one/ref": _TurnGateProvider((_completed("one answer"),)),
        "two/ref": _TurnGateProvider((_completed("two answer"),), released=True),
    }

    def builder(_provider, model):  # type: ignore[no-untyped-def]
        return providers[model.model_ref]

    application = create_application(
        config,
        provider_builder=builder,
        model_writer=lambda _model_ref: None,
    )
    tui = UthCodeTUI(application)

    async with tui.run_test() as pilot:
        composer = tui.query_one(ComposerTextArea)
        composer.focus()
        composer.text = "first"
        await pilot.press("enter")
        await providers["one/ref"].entered.wait()
        assert tui._active_handle is not None

        composer.text = "second"
        await pilot.press("enter")
        await pilot.pause()
        composer.text = "/model two/ref"
        await pilot.press("enter")
        await pilot.pause()
        assert application.current_model_ref == "one/ref"
        errors = [
            entry.text
            for entry in tui.query_one(TranscriptWidget).state.entries
            if entry.kind is TranscriptEntryKind.ERROR
        ]
        assert "生成进行中，请等待当前请求结束" in errors
        assert "生成进行中不能切换模型" in errors

        providers["one/ref"].release.set()
        await providers["one/ref"].terminal_emitted.wait()
        while tui._active_handle is not None or tui._generation_task is not None:
            await pilot.pause()
        assert tui.query_one("#activity").render().plain == "ready"

        composer.text = "/model two/ref"
        await pilot.press("enter")
        await pilot.pause()
        assert application.current_model_ref == "two/ref"

        composer.text = "next"
        await pilot.press("enter")
        await providers["two/ref"].entered.wait()
        await providers["two/ref"].terminal_emitted.wait()
        while tui._active_handle is not None or tui._generation_task is not None:
            await pilot.pause()
        assert tui.query_one("#activity").render().plain == "ready"
        assert len(providers["two/ref"].requests) == 1

    assert "模型选择：two/ref" in (providers["two/ref"].requests[0].system_prompt or "")


@pytest.mark.asyncio
async def test_composer_completion_picker_and_slash_command_regressions() -> None:
    config = EffectiveConfig(
        model="one/ref",
        providers={"local": ProviderProfile("local", ProviderKind.FAKE)},
        models={
            "one/ref": ModelProfile("one/ref", "local", "one"),
            "two/ref": ModelProfile("two/ref", "local", "two"),
        },
    )
    writes: list[str] = []

    def builder(provider, model):  # type: ignore[no-untyped-def]
        return FakeProvider(
            identity=ProviderIdentity(
                provider.provider_profile_id,
                "fake",
                model.remote_model_id,
            ),
            events=(_completed(model.remote_model_id),),
        )

    application = create_application(config, provider_builder=builder, model_writer=writes.append)
    tui = UthCodeTUI(application)
    tui.registry.register(
        CommandDefinition(
            canonical="format",
            description="format output",
            kind=CommandKind.LOCAL,
            usage="/format <style> --preview",
            arguments=(
                ArgumentSpec(
                    "style",
                    required=True,
                    description="format style",
                    choices=("plain", "markdown"),
                ),
            ),
        )
    )

    async with tui.run_test() as pilot:
        composer = tui.query_one(ComposerTextArea)
        composer.focus()
        menu = tui.query_one(CommandCompletionMenu)

        composer.text = "/model "
        await pilot.pause()
        assert [candidate.value for candidate in menu.state.candidates] == [
            "/model one/ref",
            "/model two/ref",
        ]
        await pilot.press("escape")
        assert menu.state.open is False

        composer.text = "/"
        await pilot.pause()
        assert len(menu.state.candidates) == 16
        await pilot.press("down")
        await pilot.press("tab")
        assert composer.text == "/model"
        await pilot.press("escape")

        composer.text = "/model"
        await pilot.press("enter")
        await pilot.pause()
        picker = tui.query_one(ModelPicker)
        assert picker.state.open is True
        await pilot.press("down")
        await pilot.press("enter")
        await pilot.pause()
        assert application.current_model_ref == "two/ref"
        assert writes == ["two/ref"]

        composer.text = "/format "
        await pilot.pause()
        assert [candidate.value for candidate in menu.state.candidates] == [
            "/format plain",
            "/format markdown",
        ]
        await pilot.press("escape")

        composer.text = "   "
        await pilot.press("enter")
        await pilot.pause()
        assert [entry.text for entry in tui.query_one(TranscriptWidget).state.entries] == [
            "/model",
            "/model two/ref",
        ]


@pytest.mark.asyncio
async def test_composer_shift_enter_and_scroll_protection() -> None:
    tui = UthCodeTUI(_application())

    async with tui.run_test(size=(80, 14)) as pilot:
        composer = tui.query_one(ComposerTextArea)
        composer.focus()
        composer.text = "one"
        composer.move_cursor((0, len(composer.text)))
        await pilot.press("shift+enter")
        composer.insert("two")
        assert composer.text == "one\ntwo"

        transcript = tui.query_one(TranscriptWidget)
        for index in range(30):
            transcript.add_entry(TranscriptEntryKind.SYSTEM, f"line {index}")
        await pilot.pause()
        transcript.scroll_end(animate=False)
        await pilot.pause()
        assert transcript.state.scroll.follow is True
        transcript.focus()
        await pilot.press("home")
        await pilot.pause(0.2)
        assert transcript.state.scroll.follow is False
        held_position = transcript.scroll_y
        transcript.add_entry(TranscriptEntryKind.SYSTEM, "new output")
        await pilot.pause()
        assert transcript.scroll_y <= held_position
        await pilot.press("end")
        await pilot.pause(0.2)
        assert transcript.state.scroll.follow is True


@pytest.mark.asyncio
async def test_double_escape_cancels_only_active_turn() -> None:
    provider = _ImmediatePauseProvider(TextDelta("pending"), wait_for_cancel=True)
    tui = _application_from_provider(provider)

    async with UthCodeTUI(tui).run_test() as pilot:
        app = pilot.app
        composer = app.query_one(ComposerTextArea)
        composer.focus()
        composer.text = "hello"
        await pilot.press("enter")
        await pilot.pause(0.03)
        await pilot.press("escape")
        assert "again" in app.query_one("#activity").render().plain
        await pilot.press("escape")
        await _wait_until(
            pilot,
            lambda: app.query_one("#activity").render().plain == "cancelled",
        )


@pytest.mark.asyncio
async def test_stream_timer_batches_assistant_and_reasoning_before_terminal() -> None:
    for first_event, kind in ((TextDelta("first"), TranscriptEntryKind.ASSISTANT), (ReasoningDelta("think"), TranscriptEntryKind.REASONING)):
        provider = _ImmediatePauseProvider(first_event, pause=0.6)
        app = UthCodeTUI(_application_from_provider(provider))

        async with app.run_test() as pilot:
            composer = app.query_one(ComposerTextArea)
            composer.focus()
            composer.text = "hello"
            await pilot.press("enter")
            await pilot.pause(0.25)
            transcript = app.query_one(TranscriptWidget)
            assert any(entry.kind is kind and entry.text == first_event.text for entry in transcript.state.entries)
            assert app._stream_timer is not None

            await _wait_until(
                pilot,
                lambda: app.query_one("#activity").render().plain == "ready",
                attempts=25,
            )
            assert app._stream_timer is None
            assert app._generation_task is None
            assert app.query_one(SelectableMarkdown).ALLOW_SELECT is True


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["cancel", "error"])
async def test_stream_terminal_paths_hide_results_and_clean_up(mode: str) -> None:
    if mode == "cancel":
        provider = _ImmediatePauseProvider(TextDelta("pending"), wait_for_cancel=True)
    else:
        provider = _ImmediatePauseProvider(
            TextDelta("pending"),
            pause=0.05,
            error=NetworkError("offline failure"),
        )
    app = UthCodeTUI(_application_from_provider(provider))

    async with app.run_test() as pilot:
        composer = app.query_one(ComposerTextArea)
        composer.focus()
        composer.text = "hello"
        await pilot.press("enter")
        if mode == "cancel":
            await pilot.pause(0.03)
            await pilot.press("escape")
            await pilot.press("escape")
        await _wait_until(
            pilot,
            lambda: app._generation_task is None,
            attempts=30,
        )
        transcript = app.query_one(TranscriptWidget)
        assert any(
            entry.kind is TranscriptEntryKind.ASSISTANT and entry.text == "pending"
            for entry in transcript.state.entries
        )
        assert app._stream_timer is None
        assert app.query_one(SelectableMarkdown).ALLOW_SELECT is True
        if mode == "cancel":
            assert app.query_one("#activity").render().plain == "cancelled"
        else:
            assert [
                entry.text
                for entry in transcript.state.entries
                if entry.kind is TranscriptEntryKind.ERROR
            ] == ["生成失败"]
            assert app.query_one("#activity").render().plain == "error"


@pytest.mark.asyncio
async def test_tui_exit_cancels_generation_and_removes_stream_resources() -> None:
    provider = _ImmediatePauseProvider(TextDelta("pending"), wait_for_cancel=True)
    app = UthCodeTUI(_application_from_provider(provider))

    async with app.run_test() as pilot:
        composer = app.query_one(ComposerTextArea)
        composer.focus()
        composer.text = "hello"
        await pilot.press("enter")
        await pilot.pause(0.03)
        assert app._generation_task is not None
        assert app._stream_timer is not None
        app.exit()
        await pilot.pause()

    assert app._active_handle is None
    assert app._generation_task is None
    assert app._stream_timer is None


@pytest.mark.asyncio
async def test_formal_fake_tui_flow_keeps_commands_and_model_state(tmp_path: Path) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    project.mkdir()
    user_config = home / ".uthcode" / "config.toml"
    user_config.parent.mkdir(parents=True)
    user_config.write_text(
        '''model = "one/ref"

[providers.local]
kind = "fake"

[models."one/ref"]
provider = "local"
model = "one"
label = "One"

[models."two/ref"]
provider = "local"
model = "two"
label = "Two"
''',
        encoding="utf-8",
    )
    configuration = load_effective_config(LaunchOptions(cwd=project, home=home))
    providers: list[FakeProvider] = []

    def builder(provider, model):  # type: ignore[no-untyped-def]
        instance = FakeProvider(
            identity=ProviderIdentity(
                provider.provider_profile_id,
                "fake",
                model.remote_model_id,
            ),
            events=(TextDelta(f"{model.remote_model_id} response"), _completed(f"{model.remote_model_id} response")),
            delay=0.05,
        )
        providers.append(instance)
        return instance

    application = create_application(
        configuration,
        provider_builder=builder,
        runtime_context=ApplicationRuntimeContext.from_system(workdir=project),
    )
    app = UthCodeTUI(application)

    async with app.run_test() as pilot:
        composer = app.query_one(ComposerTextArea)
        composer.focus()

        composer.text = "/help"
        await pilot.press("enter")
        await pilot.pause()
        assert any("/clear" in entry.text for entry in app.query_one(TranscriptWidget).state.entries)

        composer.text = "first request"
        await pilot.press("enter")
        await _wait_until(
            pilot,
            lambda: app.query_one("#activity").render().plain == "ready",
        )

        composer.text = "/clear"
        await pilot.press("enter")
        await pilot.pause()
        assert app.query_one(TranscriptWidget).state.entries == []

        composer.text = "/new"
        await pilot.press("enter")
        await pilot.pause()
        assert any("功能未实现：/new" in entry.text for entry in app.query_one(TranscriptWidget).state.entries)

        composer.text = "/model"
        await pilot.press("enter")
        await pilot.pause()
        picker = app.query_one(ModelPicker)
        assert picker.state.open is True
        await pilot.press("down")
        await pilot.press("enter")
        await pilot.pause()
        assert application.current_model_ref == "two/ref"

        composer.text = "second request"
        await pilot.press("enter")
        await _wait_until(
            pilot,
            lambda: app.query_one("#activity").render().plain == "ready",
        )
        assert len(providers) == 2
        assert "模型选择：two/ref" in (providers[1].recorded_requests[0].system_prompt or "")
