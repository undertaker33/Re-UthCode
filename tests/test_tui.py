from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from uthcode.application import (
    ArgumentSpec,
    CommandDefinition,
    CommandKind,
    CompletionCandidate,
    EffectiveConfig,
    GenerationCompleted,
    LaunchOptions,
    Message,
    ModelProfile,
    ProviderKind,
    ProviderIdentity,
    ProviderResponse,
    ProviderProfile,
    ReasoningDelta,
    TextDelta,
    TextPart,
    UthCodeApplication,
    Usage,
    create_application,
    load_effective_config,
)
from uthcode.core.provider import FinishReason, GenerationCancelled, NetworkError
from uthcode.integrations.providers.fake import FakeProvider
from uthcode.interfaces.tui.app import UthCodeTUI
from uthcode.interfaces.tui.completion import (
    CommandCompletionMenu,
    CompletionMenuItem,
    CompletionMenuState,
)
from uthcode.interfaces.tui.picker import ModelPicker, ModelPickerState
from uthcode.interfaces.tui.rendering import StreamRenderer
from uthcode.interfaces.tui.state import (
    EscArmState,
    ScrollFollowState,
    TranscriptEntryKind,
    TranscriptState,
)
from uthcode.interfaces.tui.widgets import (
    ComposerTextArea,
    SelectableMarkdown,
    TranscriptWidget,
)


def _completed(text: str = "done") -> GenerationCompleted:
    return GenerationCompleted(
        ProviderResponse(
            message=Message("assistant", (TextPart(text),)),
            usage=Usage(),
            finish_reason=FinishReason.STOP,
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


class _ImmediatePauseProvider:
    """Emit one event immediately, then pause without closing the stream."""

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
        self.requests: list[object] = []

    async def stream(self, request, *, cancellation):  # type: ignore[no-untyped-def]
        self.requests.append(request)
        yield self.first_event
        if self.wait_for_cancel:
            while not cancellation.cancelled:
                await asyncio.sleep(0.01)
            raise GenerationCancelled()
        await asyncio.sleep(self.pause)
        if self.error is not None:
            raise self.error
        yield _completed("finished")


def _application_from_provider(provider: _ImmediatePauseProvider) -> UthCodeApplication:
    return UthCodeApplication(provider)  # type: ignore[arg-type]


def test_state_models_cover_only_visible_entry_kinds_and_reset_scroll() -> None:
    state = TranscriptState()
    state.add(TranscriptEntryKind.USER, "hello")
    state.add(TranscriptEntryKind.ASSISTANT, "answer")
    state.add(TranscriptEntryKind.REASONING, "thinking")
    state.add(TranscriptEntryKind.COMMAND, "/help")
    state.add(TranscriptEntryKind.SYSTEM, "ready")
    state.add(TranscriptEntryKind.ERROR, "failed")

    assert [entry.kind for entry in state.entries] == list(TranscriptEntryKind)
    state.scroll.follow = False
    state.clear()
    assert state.entries == []
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


def test_stream_renderer_batches_deltas_and_flushes_terminal_response() -> None:
    now = [0.0]
    renderer = StreamRenderer(clock=lambda: now[0])

    assert renderer.push(TextDelta("a")) is None
    now[0] = 0.21
    batch = renderer.push(TextDelta("b"))
    assert batch is not None
    assert batch.text == "ab"
    assert batch.completed is False

    terminal = renderer.push(_completed("ignored"))
    assert terminal is not None
    assert terminal.completed is True
    assert terminal.text == ""


def test_completion_and_picker_have_separate_state_and_widget_types() -> None:
    assert CompletionMenuState is not ModelPickerState
    assert CommandCompletionMenu is not ModelPicker
    assert CompletionMenuItem is not CompletionCandidate


def _configured_model_application() -> tuple[UthCodeApplication, list[str]]:
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

    return (
        create_application(
            config,
            provider_builder=builder,
            model_writer=writes.append,
        ),
        writes,
    )


@pytest.mark.asyncio
async def test_tui_argument_completion_uses_catalog_and_formal_model_dispatch() -> None:
    application, writes = _configured_model_application()
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
        menu = tui.query_one(CommandCompletionMenu)
        composer.focus()

        composer.text = "/model "
        await pilot.pause()
        assert [candidate.value for candidate in menu.state.candidates] == [
            "/model one/ref",
            "/model two/ref",
        ]
        menu_text = menu._body.render().plain
        assert "Usage: /model [model-ref]" in menu_text
        assert "model-ref: Model Ref" in menu_text

        composer.text = "/model two"
        await pilot.pause()
        assert [candidate.value for candidate in menu.state.candidates] == [
            "/model two/ref"
        ]
        await pilot.press("tab")
        assert composer.text == "/model two/ref"

        composer.text = "/model two"
        await pilot.pause()
        assert menu.state.open is True
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
        menu_text = menu._body.render().plain
        assert "Usage: /format <style> --preview" in menu_text
        assert "style: format style" in menu_text


@pytest.mark.asyncio
async def test_tui_layout_composer_and_streamed_assistant_block() -> None:
    application = _application(events=(TextDelta("hello"), _completed("ignored")))
    tui = UthCodeTUI(application, cwd=Path("C:/workspace"))

    async with tui.run_test() as pilot:
        assert "UthCode" in tui.query_one("#topbar").render().plain
        composer = tui.query_one(ComposerTextArea)
        composer.focus()
        composer.text = "hello"
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()

        transcript = tui.query_one(TranscriptWidget)
        assert [entry.kind for entry in transcript.state.entries] == [
            TranscriptEntryKind.USER,
            TranscriptEntryKind.ASSISTANT,
        ]
        assert transcript.state.entries[-1].text == "hello"
        assert len(tui.query(".assistant-entry")) == 1


@pytest.mark.asyncio
async def test_composer_shift_enter_inserts_newline_and_blank_submit_is_ignored() -> None:
    tui = UthCodeTUI(_application())

    async with tui.run_test() as pilot:
        composer = tui.query_one(ComposerTextArea)
        composer.focus()
        composer.text = "one"
        composer.move_cursor((0, len(composer.text)))
        await pilot.press("shift+enter")
        composer.insert("two")
        assert composer.text == "one\ntwo"

        composer.text = "   "
        await pilot.press("enter")
        await pilot.pause()
        assert tui.query_one(TranscriptWidget).state.entries == []


@pytest.mark.asyncio
async def test_transcript_keyboard_scroll_pauses_and_restores_following() -> None:
    tui = UthCodeTUI(_application())

    async with tui.run_test(size=(80, 14)) as pilot:
        transcript = tui.query_one(TranscriptWidget)
        for index in range(30):
            transcript.add_entry(TranscriptEntryKind.SYSTEM, f"line {index}")
        await pilot.pause()
        transcript.scroll_end(animate=False)
        await pilot.pause()
        assert transcript.state.scroll.follow is True
        assert transcript.scroll_y == transcript.max_scroll_y

        transcript.focus()
        await pilot.pause()
        assert transcript.has_focus is True
        await pilot.press("home")
        await pilot.pause(0.5)
        assert transcript.scroll_y < transcript.max_scroll_y
        assert transcript.state.scroll.follow is False
        held_position = transcript.scroll_y

        transcript.add_entry(TranscriptEntryKind.SYSTEM, "new output")
        await pilot.pause()
        assert transcript.scroll_y <= held_position
        assert transcript.scroll_y < transcript.max_scroll_y
        assert transcript.state.scroll.follow is False

        await pilot.press("end")
        await pilot.pause(0.5)
        assert transcript.scroll_y == transcript.max_scroll_y
        assert transcript.state.scroll.follow is True


@pytest.mark.asyncio
async def test_completion_escape_and_picker_model_selection() -> None:
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
            identity=ProviderIdentity(provider.provider_profile_id, "fake", model.remote_model_id),
            events=(_completed(model.remote_model_id),),
        )

    application = create_application(config, provider_builder=builder, model_writer=writes.append)
    tui = UthCodeTUI(application)

    async with tui.run_test() as pilot:
        composer = tui.query_one(ComposerTextArea)
        composer.focus()
        composer.text = "/"
        await pilot.pause()
        menu = tui.query_one(CommandCompletionMenu)
        assert menu.state.open is True
        assert len(menu.state.candidates) == 15
        await pilot.press("down")
        assert menu.state.selected_index == 1
        await pilot.press("tab")
        assert composer.text == "/model"
        await pilot.press("escape")
        assert menu.state.open is False

        composer.text = "/"
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert menu.state.open is False

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


@pytest.mark.asyncio
async def test_double_escape_cancels_only_active_handle_and_rejects_second_prompt() -> None:
    tui = UthCodeTUI(
        _application(events=(TextDelta("late"), _completed()), delay=0.5)
    )

    async with tui.run_test() as pilot:
        composer = tui.query_one(ComposerTextArea)
        composer.focus()
        composer.text = "first"
        await pilot.press("enter")
        await pilot.pause(0.05)

        composer.text = "second"
        await pilot.press("enter")
        await pilot.pause()
        assert any(
            entry.kind is TranscriptEntryKind.ERROR
            for entry in tui.query_one(TranscriptWidget).state.entries
        )

        await pilot.press("escape")
        assert "again" in tui.query_one("#activity").render().plain
        await pilot.press("escape")
        await pilot.pause(0.1)
        await pilot.pause(0.1)
        assert tui.query_one("#activity").render().plain == "cancelled"


@pytest.mark.asyncio
async def test_stream_timer_flushes_delta_before_provider_terminal_and_cleans_up() -> None:
    provider = _ImmediatePauseProvider(TextDelta("first"), pause=0.6)
    tui = UthCodeTUI(_application_from_provider(provider))

    async with tui.run_test() as pilot:
        composer = tui.query_one(ComposerTextArea)
        composer.focus()
        composer.text = "hello"
        await pilot.press("enter")
        await pilot.pause(0.25)

        transcript = tui.query_one(TranscriptWidget)
        assert transcript.state.entries[-1].kind is TranscriptEntryKind.ASSISTANT
        assert transcript.state.entries[-1].text == "first"
        assert len(tui.query(".assistant-entry")) == 1
        assert tui._stream_timer is not None

        await pilot.pause(0.5)
        assert tui.query_one("#activity").render().plain == "ready"
        assert tui._stream_timer is None
        assert tui._generation_task is None
        assert tui.query_one(SelectableMarkdown).ALLOW_SELECT is True


@pytest.mark.asyncio
async def test_stream_timer_flushes_reasoning_before_provider_terminal() -> None:
    provider = _ImmediatePauseProvider(ReasoningDelta("think"), pause=0.6)
    tui = UthCodeTUI(_application_from_provider(provider))

    async with tui.run_test() as pilot:
        composer = tui.query_one(ComposerTextArea)
        composer.focus()
        composer.text = "hello"
        await pilot.press("enter")
        await pilot.pause(0.25)

        transcript = tui.query_one(TranscriptWidget)
        assert any(
            entry.kind is TranscriptEntryKind.REASONING and entry.text == "think"
            for entry in transcript.state.entries
        )
        assert len(tui.query(".reasoning-entry")) == 1

        await pilot.pause(0.5)
        assert tui._stream_timer is None
        assert tui._generation_task is None


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["cancel", "error"])
async def test_stream_terminal_paths_flush_buffer_and_stop_timer(mode: str) -> None:
    if mode == "cancel":
        provider = _ImmediatePauseProvider(
            TextDelta("pending"),
            wait_for_cancel=True,
        )
    else:
        provider = _ImmediatePauseProvider(
            TextDelta("pending"),
            pause=0.05,
            error=NetworkError("offline failure"),
        )
    tui = UthCodeTUI(_application_from_provider(provider))

    async with tui.run_test() as pilot:
        composer = tui.query_one(ComposerTextArea)
        composer.focus()
        composer.text = "hello"
        await pilot.press("enter")
        if mode == "cancel":
            await pilot.pause(0.03)
            await pilot.press("escape")
            await pilot.press("escape")
        await pilot.pause(0.25)
        if mode == "error":
            await pilot.pause(0.15)

        transcript = tui.query_one(TranscriptWidget)
        assert any(
            entry.kind is TranscriptEntryKind.ASSISTANT and entry.text == "pending"
            for entry in transcript.state.entries
        )
        assert tui._stream_timer is None
        assert tui._generation_task is None
        assert tui.query_one(SelectableMarkdown).ALLOW_SELECT is True
        if mode == "cancel":
            assert tui.query_one("#activity").render().plain == "cancelled"
        else:
            errors = [
                entry.text
                for entry in transcript.state.entries
                if entry.kind is TranscriptEntryKind.ERROR
            ]
            assert errors == ["生成失败"]
            assert tui.query_one("#activity").render().plain == "error"


@pytest.mark.asyncio
async def test_tui_exit_cancels_generation_and_removes_stream_resources() -> None:
    provider = _ImmediatePauseProvider(
        TextDelta("pending"),
        wait_for_cancel=True,
    )
    tui = UthCodeTUI(_application_from_provider(provider))

    async with tui.run_test() as pilot:
        composer = tui.query_one(ComposerTextArea)
        composer.focus()
        composer.text = "hello"
        await pilot.press("enter")
        await pilot.pause(0.03)
        assert tui._generation_task is not None
        assert tui._stream_timer is not None
        tui.exit()
        await pilot.pause()

    assert tui._active_handle is None
    assert tui._generation_task is None
    assert tui._stream_timer is None


@pytest.mark.asyncio
async def test_formal_fake_tui_flow_covers_commands_isolation_and_cancel(
    tmp_path: Path,
) -> None:
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
    configuration = load_effective_config(
        LaunchOptions(cwd=project, home=home)
    )
    providers: list[FakeProvider] = []

    def builder(provider, model):  # type: ignore[no-untyped-def]
        instance = FakeProvider(
            identity=ProviderIdentity(
                provider.provider_profile_id,
                "fake",
                model.remote_model_id,
            ),
            events=(TextDelta(f"{model.remote_model_id} response"), _completed()),
            delay=0.5,
        )
        providers.append(instance)
        return instance

    application = create_application(configuration, provider_builder=builder)
    tui = UthCodeTUI(application, cwd=project)

    async with tui.run_test() as pilot:
        composer = tui.query_one(ComposerTextArea)
        menu = tui.query_one(CommandCompletionMenu)
        transcript = tui.query_one(TranscriptWidget)
        composer.focus()

        composer.text = "/"
        await pilot.pause()
        assert len(menu.state.candidates) == 15

        composer.text = "/c"
        await pilot.pause()
        c_values = [candidate.value for candidate in menu.state.candidates]
        assert "/clear" in c_values
        assert "/compact" in c_values
        assert c_values[-1] == "/help"

        composer.text = "/help"
        await pilot.press("enter")
        await pilot.pause()
        assert any("/clear" in entry.text for entry in transcript.state.entries)

        composer.text = "first request"
        await pilot.press("enter")
        await pilot.pause(1.1)
        assert providers[0].recorded_requests[0].messages == (
            Message("user", (TextPart("first request"),)),
        )

        composer.text = "/clear"
        await pilot.press("enter")
        await pilot.pause()
        assert transcript.state.entries == []

        composer.text = "/new"
        await pilot.press("enter")
        await pilot.pause()
        assert any("功能未实现：/new" in entry.text for entry in transcript.state.entries)

        composer.text = "/model"
        await pilot.press("enter")
        await pilot.pause()
        picker = tui.query_one(ModelPicker)
        assert picker.state.open is True
        await pilot.press("down")
        await pilot.press("enter")
        await pilot.pause()
        assert application.current_model_ref == "two/ref"
        assert 'model = "two/ref"' in user_config.read_text(encoding="utf-8")

        composer.text = "second request"
        await pilot.press("enter")
        await pilot.pause(1.1)
        assert providers[1].recorded_requests[0].messages == (
            Message("user", (TextPart("second request"),)),
        )

        composer.text = "cancel me"
        await pilot.press("enter")
        await pilot.pause(0.03)
        composer.text = "/status"
        await pilot.press("enter")
        await pilot.pause()
        assert any(
            entry.kind is TranscriptEntryKind.COMMAND and entry.text == "/status"
            for entry in transcript.state.entries
        )

        composer.text = "/model one/ref"
        await pilot.press("enter")
        await pilot.pause()
        assert application.current_model_ref == "two/ref"
        assert any("生成进行中不能切换模型" in entry.text for entry in transcript.state.entries)

        await pilot.press("escape")
        await pilot.press("escape")
        await pilot.pause(0.2)
        assert tui.query_one("#activity").render().plain == "cancelled"


@pytest.mark.asyncio
async def test_expired_second_escape_rearms_without_cancelling() -> None:
    provider = _ImmediatePauseProvider(
        TextDelta("pending"),
        wait_for_cancel=True,
    )
    tui = UthCodeTUI(_application_from_provider(provider))

    async with tui.run_test() as pilot:
        composer = tui.query_one(ComposerTextArea)
        composer.focus()
        composer.text = "hello"
        await pilot.press("enter")
        await pilot.pause(0.03)

        await pilot.press("escape")
        await pilot.pause(1.05)
        await pilot.press("escape")
        assert tui._active_handle is not None
        assert tui._active_handle.cancelled is False
        assert "again" in tui.query_one("#activity").render().plain

        await pilot.press("escape")
        await pilot.pause(0.2)
        assert tui.query_one("#activity").render().plain == "cancelled"
