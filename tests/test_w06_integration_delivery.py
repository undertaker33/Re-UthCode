from __future__ import annotations

import asyncio
import json
from contextlib import contextmanager
from collections.abc import AsyncIterator, Mapping
from pathlib import Path

import pytest
from prompt_toolkit.input.defaults import create_pipe_input
from prompt_toolkit.output import DummyOutput

from uthcode.application import (
    CommandDispatcher,
    EffectiveConfig,
    GenerationCompleted,
    Message,
    ModelProfile,
    OutcomeStatus,
    ProviderEvent,
    ProviderIdentity,
    ProviderResponse,
    ProviderKind,
    ProviderProfile,
    TextPart,
    Usage,
    create_builtin_registry,
    create_application,
)
from uthcode.core.history import transcript_entries_from_message
from uthcode.application.instructions import InstructionLoader, InstructionSourceNotFoundError
from uthcode.application.runtime_context import ApplicationRuntimeContext
from uthcode.core.history import Transcript, TranscriptKind
from uthcode.core.provider import (
    CancellationToken,
    FinishReason,
    GenerationRequest,
    ModelLimits,
    NativeItem,
    ReasoningDelta as ProviderReasoningDelta,
    ReasoningPart,
    TextDelta,
    ToolCallPart,
    ToolResultPart,
)
from uthcode.integrations.instruction_files import InstructionFileReader
from uthcode.integrations.session_files import SessionFileStore
from uthcode.interfaces.tui.app import UthCodeTUI
from uthcode.interfaces.tui.rendering import RenderBatch, RenderOperation, TextUpdate
from conftest import _assert_isolated_test_path


def _completed(text: str = "answer") -> GenerationCompleted:
    return GenerationCompleted(ProviderResponse(Message("assistant", (TextPart(text),)), finish_reason=FinishReason.STOP, usage=Usage(input_tokens=11, output_tokens=7, total_tokens=18)))


class _Provider:
    def __init__(self, text: str = "answer") -> None:
        self.identity = ProviderIdentity("fake", "w06", "fake-model")
        self.text = text
        self.requests: list[GenerationRequest] = []

    def resolve_model_limits(self, _model: str) -> ModelLimits:
        return ModelLimits(max_input_tokens=1_000_000, source="test.runtime")

    async def stream(self, request: GenerationRequest, *, cancellation: CancellationToken) -> AsyncIterator[ProviderEvent]:
        self.requests.append(request)
        cancellation.raise_if_cancelled()
        yield _completed(self.text)


class _SessionE2EProvider:
    def __init__(self) -> None:
        self.identity = ProviderIdentity("fake", "t09-2-session", "fake-model")
        self.requests: list[GenerationRequest] = []
        self._ordinary_calls = 0

    def resolve_model_limits(self, _model: str) -> ModelLimits:
        return ModelLimits(max_input_tokens=1_000_000, source="test.runtime")

    async def stream(self, request: GenerationRequest, *, cancellation: CancellationToken) -> AsyncIterator[ProviderEvent]:
        self.requests.append(request)
        cancellation.raise_if_cancelled()
        if request.metadata.get("context_compaction_request") is True:
            turn_ids = [
                value
                for value in request.metadata.get("context_compaction_epoch_turns", ())
                if isinstance(value, str)
            ]
            yield _completed(
                json.dumps(
                    {
                        "entries": [
                            {"turn_id": turn_id, "summary": f"summary for {turn_id}"}
                            for turn_id in turn_ids
                        ],
                        "coverage": turn_ids,
                    }
                )
            )
            return
        self._ordinary_calls += 1
        if self._ordinary_calls == 1:
            response = ProviderResponse(
                Message(
                    "assistant",
                    (ToolCallPart("read-large", "ReadFile", {"path": "large.txt"}),),
                ),
                finish_reason=FinishReason.TOOL_CALLS,
                usage=Usage(),
            )
            yield GenerationCompleted(response)
            return
        yield _completed("resumed final" if self._ordinary_calls > 2 else "first final")


class _TwoToolProvider:
    """Drive one formal TUI entry through reasoning, a FIFO tool batch, and final text."""

    def __init__(self, *, continuation: bool = False) -> None:
        self.identity = ProviderIdentity("fake", "t09-2-formal", "fake-model")
        self.requests: list[GenerationRequest] = []
        self._ordinary_calls = 0
        self._continuation = continuation

    def resolve_model_limits(self, _model: str) -> ModelLimits:
        return ModelLimits(max_input_tokens=1_000_000, source="test.runtime")

    async def stream(
        self,
        request: GenerationRequest,
        *,
        cancellation: CancellationToken,
    ) -> AsyncIterator[ProviderEvent]:
        self.requests.append(request)
        cancellation.raise_if_cancelled()
        self._ordinary_calls += 1
        if self._continuation:
            yield _completed("continued answer")
            return
        if self._ordinary_calls == 1:
            yield ProviderReasoningDelta("reasoning before tools")
            yield GenerationCompleted(
                ProviderResponse(
                    Message(
                        "assistant",
                        (
                            ReasoningPart("reasoning before tools"),
                            ToolCallPart(
                                "read-formal",
                                "ReadFile",
                                {"path": "evidence.txt"},
                            ),
                            ToolCallPart(
                                "glob-formal",
                                "Glob",
                                {"pattern": "*.txt", "path": "."},
                            ),
                        ),
                    ),
                    finish_reason=FinishReason.TOOL_CALLS,
                    usage=Usage(),
                )
            )
            return
        yield GenerationCompleted(
            ProviderResponse(
                Message(
                    "assistant",
                    (ReasoningPart("final reasoning"), TextPart("final answer")),
                ),
                finish_reason=FinishReason.STOP,
                usage=Usage(),
            )
        )


class _StreamingPreviewProvider:
    """Hold a real TUI Turn open while reasoning and assistant previews change."""

    def __init__(self) -> None:
        self.identity = ProviderIdentity("fake", "w06-preview", "fake-model")
        self.requests: list[GenerationRequest] = []
        self.ready_for_terminal = asyncio.Event()
        self.allow_terminal = asyncio.Event()

    def resolve_model_limits(self, _model: str) -> ModelLimits:
        return ModelLimits(max_input_tokens=1_000_000, source="test.runtime")

    async def stream(
        self,
        request: GenerationRequest,
        *,
        cancellation: CancellationToken,
    ) -> AsyncIterator[ProviderEvent]:
        self.requests.append(request)
        cancellation.raise_if_cancelled()
        yield ProviderReasoningDelta("safe reasoning block\n\nreasoning-tail-1")
        await asyncio.sleep(0.25)
        cancellation.raise_if_cancelled()
        yield ProviderReasoningDelta(" reasoning-tail-2")
        await asyncio.sleep(0.25)
        cancellation.raise_if_cancelled()
        yield TextDelta("formal-draft-1")
        await asyncio.sleep(0.25)
        cancellation.raise_if_cancelled()
        yield TextDelta(" formal-draft-2")
        self.ready_for_terminal.set()
        await self.allow_terminal.wait()
        cancellation.raise_if_cancelled()
        yield _completed("formal answer")


def _build_application(project: Path, sessions: SessionFileStore, provider: _Provider):
    user_root = project.parent / "home" / ".uthcode"
    _assert_isolated_test_path("W06 project", project)
    _assert_isolated_test_path("W06 session store", sessions.root)
    _assert_isolated_test_path("W06 user root", user_root)
    _assert_isolated_test_path("W06 config", user_root / "config.toml")
    user_root.mkdir(parents=True, exist_ok=True)
    loader = InstructionLoader(user_root=user_root, project_root=project, reader=InstructionFileReader())
    return create_application(EffectiveConfig.single_model("fake/ref", provider_profile_id="fake", remote_id="fake-model", context_window=1_000_000), provider_builder=lambda _profile, _model: provider, runtime_context=ApplicationRuntimeContext.from_system(workdir=project), instruction_loader=loader, session_store=sessions)


def test_w06_test_state_guard_rejects_real_user_profile_and_config() -> None:
    with pytest.raises(AssertionError, match="real user profile/config"):
        _assert_isolated_test_path("test HOME", Path(r"C:\Users\93445"))
    with pytest.raises(AssertionError, match="real user profile/config"):
        _assert_isolated_test_path("test config", Path(r"C:\Users\93445\.uthcode\config.toml"))


def test_w06_create_fails_closed_on_missing_instruction_include(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "AGENTS.md").write_text('parent\n@include("missing.md")\n', encoding="utf-8")
    sessions = SessionFileStore(tmp_path / "sessions")
    application = _build_application(project, sessions, _Provider())
    try:
        with pytest.raises(InstructionSourceNotFoundError):
            application.create_session("include-fails")
        assert application.session_service.active_session is None  # type: ignore[union-attr]
        assert not sessions.session_path("include-fails").exists()
    finally:
        application.close()


@pytest.mark.asyncio
async def test_formal_run_persists_closed_transcript_facts(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    provider = _Provider("final")
    sessions = SessionFileStore(tmp_path / "sessions")
    application = _build_application(project, sessions, provider)
    try:
        session = application.create_session("persist")
        result = await application.create_run().start_turn("hello").result()
        assert result.final_text == "final"
        assert session.transcript.entries
        assert all(entry.commit_boundary for entry in session.transcript.entries)
        assert not (sessions.session_path("persist") / "history.jsonl").exists()
    finally:
        application.close()


@pytest.mark.asyncio
async def test_resume_uses_transcript_and_starts_a_fresh_run(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    provider = _Provider("resumed")
    sessions = SessionFileStore(tmp_path / "sessions")
    application = _build_application(project, sessions, provider)
    try:
        session = application.create_session("resume")
        entries = transcript_entries_from_message("resume", "seed", 1, Message("user", (TextPart("DURABLE_MARKER"),)))
        session.append_transcript(entries)
        session.close()
        resumed = application.resume_session_for_command("resume")
        assert resumed.transcript.entries == entries
        assert application.create_run().snapshot().iteration_count == 0
        before_entries = len(resumed.transcript.entries)
        result = await application.create_run().start_turn("new marker").result()
        assert result.final_text == "resumed"
        assert len(resumed.transcript.entries) == before_entries + 2
        text = "\n".join(part.text for message in provider.requests[0].messages for part in message.parts if isinstance(part, TextPart))
        assert "DURABLE_MARKER" in text and "new marker" in text
    finally:
        application.close()


@pytest.mark.asyncio
async def test_process_boundary_resume_replays_mixed_turn_once_and_new_is_empty(
    tmp_path: Path,
) -> None:
    """A fresh Application reconstructs one mixed durable Turn without duplication."""

    project = tmp_path / "project"
    project.mkdir()
    sessions = SessionFileStore(tmp_path / "sessions")
    first_application = _build_application(project, sessions, _Provider())
    session_id = "process-boundary"
    try:
        session = first_application.create_session(session_id)
        messages = (
            Message("user", (TextPart("seed user"),)),
            Message("assistant", (ReasoningPart("seed reasoning"),)),
            Message(
                "assistant",
                (
                    ToolCallPart(
                        "call-one",
                        "ReadFile",
                        {"path": "evidence.txt", "secret": "API-KEY-SECRET"},
                    ),
                    ToolCallPart(
                        "call-two",
                        "Glob",
                        {"pattern": "*.txt", "path": "."},
                    ),
                ),
            ),
            Message(
                "tool",
                (
                    ToolResultPart(
                        "call-one",
                        "RAW-TOOL-RESULT-SECRET",
                        metadata={"execution_status": "succeeded", "api_key": "sk-secret"},
                    ),
                    ToolResultPart(
                        "call-two",
                        "RAW-TOOL-RESULT-SECOND",
                        metadata={"execution_status": "failed"},
                        is_error=True,
                    ),
                ),
            ),
            Message(
                "assistant",
                (TextPart("seed final"),),
                native_items=(
                    NativeItem(
                        "fake",
                        "protocol",
                        "fake-model",
                        payload={"native_secret": "do-not-replay"},
                    ),
                ),
            ),
        )
        entries: list[object] = []
        sequence = 1
        for message in messages:
            values = transcript_entries_from_message(
                session_id,
                "formal-turn",
                sequence,
                message,
            )
            entries.extend(values)
            sequence += len(values)
        transcript = Transcript(session_id, tuple(entries))  # type: ignore[arg-type]
        session.append_transcript(transcript.entries)
        session.close()
    finally:
        first_application.close()

    second_provider = _Provider("continued")
    second_application = _build_application(project, sessions, second_provider)
    tui = UthCodeTUI(second_application, terminal_output=DummyOutput())
    emitted: list[str] = []

    async def capture(value: str) -> None:
        emitted.append(value)

    tui._emit = capture  # type: ignore[method-assign]
    try:
        resumed = second_application.resume_session_for_command(session_id)
        assert resumed.session_id == session_id
        replay = resumed.replay
        assert [(record.kind, record.sequence) for record in replay] == [
            ("user", 1),
            ("reasoning", 2),
            ("tool", 5),
            ("tool", 6),
            ("assistant", 7),
        ]
        assert [record.tool_call_id for record in replay if record.kind == "tool"] == [
            "call-one",
            "call-two",
        ]

        run = second_application.create_run()
        before_provider_count = len(second_provider.requests)
        before_turn_count = run.snapshot().iteration_count
        before_transcript_count = len(resumed.transcript.entries)
        await tui._hydrate_replay(replay)
        assert len(second_provider.requests) == before_provider_count == 0
        assert run.snapshot().iteration_count == before_turn_count == 0
        assert len(resumed.transcript.entries) == before_transcript_count == 7
        replay_text = "".join(emitted)
        assert replay_text.index("seed user") < replay_text.index("seed reasoning")
        assert replay_text.index("seed reasoning") < replay_text.index("evidence.txt")
        assert replay_text.index("evidence.txt") < replay_text.index("pattern=*.txt path=.")
        assert replay_text.index("pattern=*.txt path=.") < replay_text.index("seed final")
        for marker in ("seed user", "seed reasoning", "evidence.txt", "pattern=*.txt path=.", "seed final"):
            assert replay_text.count(marker) == 1
        assert "RAW-TOOL-RESULT" not in replay_text
        assert "native_secret" not in replay_text

        durable_before_new = sessions.read_session(session_id).transcript.entries
        outcome = await CommandDispatcher(
            create_builtin_registry(), second_application
        ).dispatch_text_async("/new")
        assert outcome is not None and outcome.status is OutcomeStatus.SUCCESS
        assert getattr(outcome.ui_action, "restored", True) is False
        active = second_application.session_service.active_session
        assert active is not None and active.session_id != session_id
        assert active.replay == ()
        assert sessions.read_session(session_id).transcript.entries == durable_before_new
    finally:
        second_application.close()


@pytest.mark.asyncio
async def test_t09_2_v3_session_formal_turn_compact_close_reopen_resume_preserves_facts(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "large.txt").write_text("x" * 9_000, encoding="utf-8")
    provider = _SessionE2EProvider()
    sessions = SessionFileStore(tmp_path / "sessions")
    application = _build_application(project, sessions, provider)  # type: ignore[arg-type]
    try:
        session = application.create_session("t09-2-v3")
        result = await application.create_run().start_turn("read the large evidence").result()
        assert result.final_text == "first final"
        tool_results = [
            entry
            for entry in session.transcript.entries
            if entry.kind is TranscriptKind.TOOL_RESULT
        ]
        assert len(tool_results) == 1
        metadata = tool_results[0].payload["part"]["metadata"]
        assert isinstance(metadata, Mapping)
        reference = metadata["ref"]
        assert isinstance(reference, str) and reference
        assert (sessions.session_path("t09-2-v3") / "tool-results" / reference).is_dir()

        compacted = await application.compact_session()
        assert compacted.changed is True
        assert session.timeline.active_checkpoint is not None
        transcript_before_close = session.transcript.entries
        timeline_before_close = session.timeline.records
        instruction_state_before_close = dict(session.metadata.instruction_state)

        application.close()
        reopened = application.resume_session_for_command("t09-2-v3")
        assert reopened.metadata.schema_version == 3
        assert reopened.transcript.entries == transcript_before_close
        assert reopened.timeline.records == timeline_before_close
        assert reopened.metadata.instruction_state == instruction_state_before_close
        page = reopened.read_tool_result(reference, limit=64)
        assert page.content.startswith("1\t")
        assert page.content[2:] == "x" * 62

        resumed = await application.create_run().start_turn("continue from durable facts").result()
        assert resumed.final_text == "resumed final"
    finally:
        application.close()


def test_transcript_message_groups_keep_tool_call_and_result_together(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    sessions = SessionFileStore(tmp_path / "sessions")
    application = _build_application(project, sessions, _Provider())
    try:
        session = application.create_session("tool-group")
        entries = transcript_entries_from_message("tool-group", "turn", 1, Message("assistant", (TextPart("before"),)))
        session.append_transcript(entries)
        assert [entry.kind for entry in session.transcript.entries] == [TranscriptKind.ASSISTANT_MESSAGE]
    finally:
        application.close()


@pytest.mark.asyncio
async def test_unique_application_chain_preserves_history_across_model_switch(
    tmp_path: Path,
) -> None:
    """A model command changes the next Turn, not the Application history path."""

    project = tmp_path / "project"
    project.mkdir()
    user_root = tmp_path / "home" / ".uthcode"
    _assert_isolated_test_path("W06 model-switch project", project)
    _assert_isolated_test_path("W06 model-switch user root", user_root)
    _assert_isolated_test_path("W06 model-switch config", user_root / "config.toml")
    user_root.mkdir(parents=True)
    loader = InstructionLoader(
        user_root=user_root,
        project_root=project,
        reader=InstructionFileReader(),
    )
    first = _Provider("first model answer")
    first.identity = ProviderIdentity("fake", "switch-1", "remote-one")
    second = _Provider("second model answer")
    second.identity = ProviderIdentity("fake", "switch-2", "remote-two")
    providers = {"remote-one": first, "remote-two": second}
    config = EffectiveConfig(
        default_model="fake/one",
        providers={
            "fake-one": ProviderProfile("fake-one", ProviderKind.FAKE),
            "fake-two": ProviderProfile("fake-two", ProviderKind.FAKE),
        },
        models={
            "fake/one": ModelProfile("fake/one", "fake-one", "remote-one"),
            "fake/two": ModelProfile("fake/two", "fake-two", "remote-two"),
        },
    )
    application = create_application(
        config,
        provider_builder=lambda _profile, model: providers[model.remote_id],
        runtime_context=ApplicationRuntimeContext.from_system(workdir=project),
        instruction_loader=loader,
        session_store=SessionFileStore(tmp_path / "sessions"),
    )
    try:
        application.create_session("model-switch")
        run = application.create_run()
        first_result = await run.start_turn("first turn").result()
        assert first_result.final_text == "first model answer"

        selected = application.select_model("fake/two")
        assert selected.remote_id == "remote-two"

        second_result = await run.start_turn("second turn").result()
        assert second_result.final_text == "second model answer"
        assert first.requests[0].model == "remote-one"
        assert second.requests[0].model == "remote-two"
        user_text = [
            part.text
            for message in second.requests[0].messages
            if message.role == "user"
            for part in message.parts
            if isinstance(part, TextPart)
        ]
        assert "first turn" in user_text
        assert user_text[-1] == "second turn"
    finally:
        application.close()


@pytest.mark.asyncio
async def test_formal_tui_four_prompt_sequence_preserves_current_user_tail(
    tmp_path: Path,
) -> None:
    """The real TUI submission path keeps each prompt as the final user message."""

    project = tmp_path / "project"
    project.mkdir()
    provider = _Provider("formal answer")
    application = _build_application(
        project,
        SessionFileStore(tmp_path / "sessions"),
        provider,
    )
    pipe_context = create_pipe_input()
    pipe = pipe_context.__enter__()
    tui = UthCodeTUI(
        application,
        input_device=pipe,
        terminal_output=DummyOutput(),
    )
    task = asyncio.create_task(tui.run_async())
    prompts = ("你好", "你是什么模型", "当前工作环境是？", "？")

    async def wait_until(predicate) -> None:  # type: ignore[no-untyped-def]
        for _ in range(200):
            if predicate():
                return
            await asyncio.sleep(0.01)
        raise AssertionError("condition did not become true")

    try:
        await wait_until(lambda: tui.ui.is_running)
        for index, prompt in enumerate(prompts, start=1):
            pipe.send_text(prompt + "\r")
            await wait_until(
                lambda expected=index: (
                    tui._generation_task is None
                    and len(provider.requests) == expected
                )
            )

        assert len(application.list_sessions()) == 1
        for request, prompt in zip(provider.requests, prompts, strict=True):
            assert request.messages[-1] == Message(
                "user",
                (TextPart(prompt),),
            )
    finally:
        if tui.ui.is_running:
            pipe.send_text("\x03")
        await asyncio.wait_for(task, timeout=2)
        pipe_context.__exit__(None, None, None)
        application.close()


@pytest.mark.asyncio
async def test_tui_session_picker_open_close_does_not_create_session(
    tmp_path: Path,
) -> None:
    """Opening and dismissing the picker only reads Application catalog data."""

    project = tmp_path / "project"
    project.mkdir()
    sessions = SessionFileStore(tmp_path / "sessions")
    application = _build_application(project, sessions, _Provider())
    existing = application.create_session("existing")
    existing.close()
    initial_ids = tuple(item.session_id for item in application.list_sessions())

    pipe_context = create_pipe_input()
    pipe = pipe_context.__enter__()
    input_attached = asyncio.Event()
    original_attach = pipe.attach

    @contextmanager
    def attach_with_lifecycle_signal(callback):  # type: ignore[no-untyped-def]
        with original_attach(callback):
            input_attached.set()
            yield

    pipe.attach = attach_with_lifecycle_signal  # type: ignore[method-assign]
    tui = UthCodeTUI(
        application,
        input_device=pipe,
        terminal_output=DummyOutput(),
    )
    task = asyncio.create_task(tui.run_async())

    async def wait_until(predicate) -> None:  # type: ignore[no-untyped-def]
        for _ in range(200):
            if predicate():
                return
            await asyncio.sleep(0.01)
        raise AssertionError("condition did not become true")

    try:
        # is_running is set before prompt_toolkit attaches the pipe reader;
        # synchronize on the actual attachment before injecting keys.
        await wait_until(lambda: tui.ui.is_running and input_attached.is_set())
        await tui._handle_submission("/resume")
        assert tui.session_picker.open
        assert tuple(item.session_id for item in application.list_sessions()) == initial_ids
        # Send the terminal's explicit Kitty Escape sequence so the fixture
        # does not depend on prompt_toolkit's bare-Escape timeout matcher.
        pipe.send_text("\x1b[27u")
        await wait_until(lambda: not tui.session_picker.open)
        assert tuple(item.session_id for item in application.list_sessions()) == initial_ids
    finally:
        if tui.ui.is_running:
            pipe.send_text("\x03")
        await asyncio.wait_for(task, timeout=2)
        pipe_context.__exit__(None, None, None)
        application.close()


@pytest.mark.asyncio
async def test_tui_streaming_previews_commit_safe_reasoning_before_final(
    tmp_path: Path,
) -> None:
    """The real TUI consumer samples changing previews before terminal authority."""

    project = tmp_path / "project"
    project.mkdir()
    provider = _StreamingPreviewProvider()
    application = _build_application(
        project,
        SessionFileStore(tmp_path / "sessions"),
        provider,  # type: ignore[arg-type]
    )
    tui = UthCodeTUI(application, terminal_output=DummyOutput())
    emitted: list[str] = []

    async def capture(value: str) -> None:
        emitted.append(value)

    tui._emit = capture  # type: ignore[method-assign]
    generation: asyncio.Task[None] | None = None
    try:
        assert tui._start_turn("preview request") is True
        generation = tui._generation_task
        assert generation is not None

        async def wait_until(predicate) -> None:  # type: ignore[no-untyped-def]
            for _ in range(300):
                if predicate():
                    return
                await asyncio.sleep(0.01)
            raise AssertionError("condition did not become true")

        await wait_until(
            lambda: bool(tui._streams)
            and "reasoning-tail-1" in tui._streams[0].stream.full_text
        )
        preview_one = tui._preview_fragments()
        await wait_until(
            lambda: bool(tui._streams)
            and "reasoning-tail-2" in tui._streams[0].stream.full_text
        )
        preview_two = tui._preview_fragments()

        assert preview_one != preview_two
        await wait_until(lambda: "safe reasoning block" in "".join(emitted))
        assert not generation.done()
        assert "safe reasoning block" in "".join(emitted)

        await wait_until(
            lambda: bool(tui._streams)
            and any(
                projection.kind == "assistant"
                and "formal-draft-1" in projection.stream.full_text
                for projection in tui._streams
            )
        )
        assistant_preview_one = tui._preview_fragments()
        await wait_until(
            lambda: bool(tui._streams)
            and any(
                projection.kind == "assistant"
                and "formal-draft-2" in projection.stream.full_text
                for projection in tui._streams
            )
        )
        await wait_until(lambda: provider.ready_for_terminal.is_set())
        assistant_preview_two = tui._preview_fragments()
        assert assistant_preview_one != assistant_preview_two

        provider.allow_terminal.set()
        await asyncio.wait_for(generation, timeout=3)
        output = "".join(emitted)
        assert output.count("formal answer") == 1
        assert "formal-draft-1" not in output
        assert "formal-draft-2" not in output
    finally:
        provider.allow_terminal.set()
        if generation is not None and not generation.done():
            await asyncio.wait_for(generation, timeout=3)
        application.close()


@pytest.mark.asyncio
async def test_tui_failed_resume_keeps_screen_session_and_run_atomic(
    tmp_path: Path,
) -> None:
    """Busy, corrupt, and unknown /resume failures do not clear current TUI state."""

    project = tmp_path / "project"
    project.mkdir()
    sessions = SessionFileStore(tmp_path / "sessions")

    seed = _build_application(project, sessions, _Provider())
    try:
        for session_id in ("current", "busy", "corrupt"):
            created = seed.create_session(session_id)
            created.close()
    finally:
        seed.close()

    async def exercise(
        application: object,
        command: str,
        expected_error: str,
    ) -> None:
        tui = UthCodeTUI(application, terminal_output=DummyOutput())  # type: ignore[arg-type]
        emitted: list[str] = []

        async def capture(value: str) -> None:
            emitted.append(value)

        tui._emit = capture  # type: ignore[method-assign]
        await tui._apply_batch(
            RenderBatch(
                operations=(
                    RenderOperation(
                        "text",
                        TextUpdate("current-preview", "reasoning", "keep this preview"),
                    ),
                )
            )
        )
        before_run = tui._run
        before_session = application.session_service.active_session  # type: ignore[attr-defined]
        before_ids = tuple(item.session_id for item in application.list_sessions())  # type: ignore[attr-defined]
        before_streams = tuple(
            (
                projection.block_id,
                projection.kind,
                projection.stream.committed,
                projection.stream.pending,
                projection.started,
                projection.open,
                projection.authoritative,
            )
            for projection in tui._streams
        )

        try:
            await tui._handle_submission(command)
            after_streams = tuple(
                (
                    projection.block_id,
                    projection.kind,
                    projection.stream.committed,
                    projection.stream.pending,
                    projection.started,
                    projection.open,
                    projection.authoritative,
                )
                for projection in tui._streams
            )
            assert application.session_service.active_session is before_session  # type: ignore[attr-defined]
            assert tui._run is before_run
            assert after_streams == before_streams
            assert tuple(item.session_id for item in application.list_sessions()) == before_ids  # type: ignore[attr-defined]
            assert expected_error in "".join(emitted)
            assert tui.session_picker.open is False
        finally:
            application.close()  # type: ignore[attr-defined]

    unknown_application = _build_application(project, sessions, _Provider())
    unknown_application.resume_session_for_command("current")
    await exercise(unknown_application, "/resume missing", "unknown Session: missing")

    busy_owner = _build_application(project, sessions, _Provider())
    busy_application = _build_application(project, sessions, _Provider())
    busy_owner.resume_session_for_command("busy")
    busy_application.resume_session_for_command("current")
    try:
        await exercise(
            busy_application,
            "/resume busy",
            "Session busy; close the other writer and retry",
        )
    finally:
        busy_owner.close()

    (sessions.session_path("corrupt") / "transcript.jsonl").write_text(
        "{invalid json\n",
        encoding="utf-8",
    )
    corrupt_application = _build_application(project, sessions, _Provider())
    corrupt_application.resume_session_for_command("current")
    await exercise(
        corrupt_application,
        "/resume corrupt",
        "Session corrupt; resume stopped for safety",
    )


@pytest.mark.asyncio
async def test_formal_tui_entry_tools_restart_resume_and_continue_in_order(
    tmp_path: Path,
) -> None:
    """Exercise reasoning -> two tools -> final, then fresh-app resume and continuation."""

    project = tmp_path / "project"
    project.mkdir()
    (project / "evidence.txt").write_text("durable evidence\n", encoding="utf-8")
    sessions = SessionFileStore(tmp_path / "sessions")
    first_provider = _TwoToolProvider()
    first_application = _build_application(  # type: ignore[arg-type]
        project,
        sessions,
        first_provider,
    )
    first_tui = UthCodeTUI(first_application, terminal_output=DummyOutput())
    first_emitted: list[str] = []

    async def capture_first(value: str) -> None:
        first_emitted.append(value)

    first_tui._emit = capture_first  # type: ignore[method-assign]
    session_id: str | None = None
    try:
        assert first_tui._start_turn("formal request") is True
        generation = first_tui._generation_task
        assert generation is not None
        await asyncio.wait_for(generation, timeout=5)
        active = first_application.session_service.active_session
        assert active is not None
        session_id = active.session_id
        entries = active.transcript.entries
        assert len(first_provider.requests) == 2
        assert sum(entry.kind is TranscriptKind.TOOL_CALL for entry in entries) == 2
        assert sum(entry.kind is TranscriptKind.TOOL_RESULT for entry in entries) == 2
        first_text = "".join(first_emitted)
        assert first_text.index("reasoning before tools") < first_text.index("ReadFile")
        assert first_text.index("ReadFile") < first_text.index("Glob")
        assert first_text.index("Glob") < first_text.index("final answer")
        assert first_text.count("final answer") == 1
    finally:
        first_application.close()

    assert session_id is not None
    second_provider = _TwoToolProvider(continuation=True)
    second_application = _build_application(  # type: ignore[arg-type]
        project,
        sessions,
        second_provider,
    )
    second_tui = UthCodeTUI(second_application, terminal_output=DummyOutput())
    second_emitted: list[str] = []

    async def capture_second(value: str) -> None:
        second_emitted.append(value)

    second_tui._emit = capture_second  # type: ignore[method-assign]
    try:
        await second_tui._handle_submission(f"/resume {session_id}")
        resumed = second_application.session_service.active_session
        assert resumed is not None and resumed.session_id == session_id
        replay_text = "".join(second_emitted)
        assert replay_text.index("formal request") < replay_text.index("reasoning before tools")
        assert replay_text.index("reasoning before tools") < replay_text.index("ReadFile")
        assert replay_text.index("ReadFile") < replay_text.index("Glob")
        assert replay_text.index("Glob") < replay_text.index("final answer")
        for marker in (
            "formal request",
            "reasoning before tools",
            "ReadFile",
            "Glob",
            "final answer",
        ):
            assert replay_text.count(marker) == 1

        before_continue_entries = len(resumed.transcript.entries)
        assert second_tui._start_turn("continue") is True
        continuation = second_tui._generation_task
        assert continuation is not None
        await asyncio.wait_for(continuation, timeout=5)
        assert len(second_provider.requests) == 1
        request = second_provider.requests[0]
        assert request.messages[-1] == Message(
            "user",
            (TextPart("continue"),),
        )
        formal_users = [
            (index, message)
            for index, message in enumerate(request.messages)
            if message == Message("user", (TextPart("formal request"),))
        ]
        assert len(formal_users) == 1
        tool_call_messages = [
            (index, message)
            for index, message in enumerate(request.messages)
            if any(isinstance(part, ToolCallPart) for part in message.parts)
        ]
        tool_result_messages = [
            (index, message)
            for index, message in enumerate(request.messages)
            if any(isinstance(part, ToolResultPart) for part in message.parts)
        ]
        final_messages = [
            (index, message)
            for index, message in enumerate(request.messages)
            if message == Message(
                "assistant",
                (ReasoningPart("final reasoning"), TextPart("final answer")),
            )
        ]
        assert len(tool_call_messages) == 1
        assert len(tool_result_messages) == 1
        assert len(final_messages) == 1
        assert formal_users[0][0] < tool_call_messages[0][0]
        assert tool_call_messages[0][0] < tool_result_messages[0][0]
        assert tool_result_messages[0][0] < final_messages[0][0]
        assert tool_call_messages[0][1].parts == (
            ReasoningPart("reasoning before tools"),
            ToolCallPart("read-formal", "ReadFile", {"path": "evidence.txt"}),
            ToolCallPart("glob-formal", "Glob", {"pattern": "*.txt", "path": "."}),
        )
        assert all(
            isinstance(part, ToolResultPart)
            for part in tool_result_messages[0][1].parts
        )
        assert [
            part.tool_call_id
            for part in tool_result_messages[0][1].parts
            if isinstance(part, ToolResultPart)
        ] == ["read-formal", "glob-formal"]
        assert len(resumed.transcript.entries) == before_continue_entries + 2
        assert "continued answer" in "".join(second_emitted)
    finally:
        second_application.close()
