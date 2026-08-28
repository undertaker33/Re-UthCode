from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from uthcode.application import ApplicationContextService, CommandDispatcher, ContextUsage, EffectiveConfig, OpenSessionPicker, OutcomeStatus, SessionChanged, SessionOperationError, SessionReplayRecord, create_application, create_builtin_registry
from uthcode.application.history import _transcript_entries_for_message
from uthcode.application.instructions import InstructionLoader
from uthcode.application.runtime_context import ApplicationRuntimeContext
from uthcode.core.history import ActiveCheckpoint, SemanticEntry, Transcript, TranscriptEntry, TranscriptKind
from uthcode.core.provider import FinishReason, GenerationCompleted, Message, ModelLimits, NativeItem, ProviderResponse, ReasoningPart, TextPart, ToolCallPart, ToolResultPart, Usage
from uthcode.integrations.instruction_files import InstructionFileReader
from uthcode.integrations import session_files
from uthcode.integrations.providers.fake import FakeProvider
from uthcode.integrations.session_files import SessionBusyError, SessionFileError, SessionFileStore
from uthcode.interfaces.cli import _stream_exec
from uthcode.interfaces.tui.picker import SessionPickerState
from uthcode.interfaces.tui.rendering import context_usage_bar, context_usage_ring, context_usage_style


TEST_LIMITS = ModelLimits(max_input_tokens=1_000_000, source="test.fake")


def _application(tmp_path: Path, store: SessionFileStore, *, provider: FakeProvider | None = None):
    user_root = tmp_path / "home" / ".uthcode"
    project_root = tmp_path / "project"
    user_root.mkdir(parents=True, exist_ok=True)
    project_root.mkdir(parents=True, exist_ok=True)
    (project_root / "AGENTS.md").write_text("project rule", encoding="utf-8")
    loader = InstructionLoader(user_root=user_root, project_root=project_root, reader=InstructionFileReader())
    return create_application(EffectiveConfig.single_model("fake/model", context_window=1_000_000), provider_builder=None if provider is None else lambda _profile, _model: provider, runtime_context=ApplicationRuntimeContext.from_system(workdir=project_root), instruction_loader=loader, session_store=store)


def _completed(text: str = "done") -> GenerationCompleted:
    return GenerationCompleted(ProviderResponse(Message("assistant", (TextPart(text),)), finish_reason=FinishReason.STOP, usage=Usage()))


def _message_transcript(session_id: str, messages: tuple[Message, ...]) -> Transcript:
    transcript = Transcript(session_id)
    sequence = 1
    for index, message in enumerate(messages, start=1):
        entries = _transcript_entries_for_message(session_id, f"turn-{index}", sequence, message)
        for entry in entries:
            transcript = transcript.append(entry)
        sequence += len(entries)
    return transcript


def _seed(application, session_id: str = "session-1") -> Transcript:
    session = application.create_session(session_id)
    transcript = _message_transcript(session_id, (Message("user", (TextPart("first prompt"),)),))
    session.append_transcript(transcript.entries)
    session.close()
    return transcript


def _request_text(request) -> str:
    return "\n".join(part.text for message in request.messages for part in message.parts if isinstance(part, TextPart))


def _replay_transcript(session_id: str) -> Transcript:
    """Build one complete mixed-part Turn for the Application replay contract."""

    entries: list[TranscriptEntry] = []
    sequence = 1

    def append(
        message: Message,
        *,
        kind: TranscriptKind | None = None,
        turn_id: str = "turn-replay",
    ) -> None:
        nonlocal sequence
        if kind is None:
            values = _transcript_entries_for_message(
                session_id, turn_id, sequence, message
            )
        else:
            values = (
                TranscriptEntry(
                    session_id=session_id,
                    sequence=sequence,
                    turn_id=turn_id,
                    kind=kind,
                    payload={
                        "role": message.role,
                        "part": message.parts[0].to_dict(),
                    },
                    semantic_unit_id=turn_id,
                ),
            )
        entries.extend(values)
        sequence += len(values)

    append(Message("user", (TextPart("durable user"),)))
    append(Message("user", (TextPart("steering secret"),)), kind=TranscriptKind.USER_STEERING)
    append(
        Message(
            "assistant",
            (
                ReasoningPart("private reasoning"),
                TextPart("formal answer"),
            ),
            native_items=(
                NativeItem(
                    provider="fake",
                    protocol="test",
                    model="fake-model",
                    payload={"native_secret": "should not replay"},
                ),
            ),
        )
    )
    append(
        Message(
            "assistant",
            (
                ToolCallPart(
                    "call-1",
                    "Bash",
                    {"command": "echo API-KEY-SECRET"},
                ),
            ),
        )
    )
    append(
        Message(
            "tool",
            (
                ToolResultPart(
                    "call-1",
                    "RAW-TOOL-RESULT-SECRET",
                    metadata={
                        "execution_status": "succeeded",
                        "api_key": "sk-raw-secret",
                    },
                ),
            ),
        )
    )
    append(Message("assistant", (TextPart("after tool"),)))
    append(
        Message(
            "assistant",
            (ToolCallPart("pending-call", "Bash", {"command": "pending"}),),
        ),
        turn_id="turn-pending",
    )
    return Transcript(session_id, tuple(entries))


@pytest.mark.asyncio
async def test_w04_commands_are_registered_and_compact_rejects_extra_arguments() -> None:
    registry = create_builtin_registry()
    dispatcher = CommandDispatcher(registry)
    assert callable(registry.resolve("compact").handler)  # type: ignore[union-attr]
    assert isinstance((await dispatcher.dispatch_text_async("/resume")).ui_action, OpenSessionPicker)  # type: ignore[union-attr]
    rejected = await dispatcher.dispatch_text_async("/compact -- focus")
    assert rejected is not None and rejected.status is OutcomeStatus.USAGE_ERROR


def test_application_command_facts_are_safe_without_an_active_session(tmp_path: Path) -> None:
    store = SessionFileStore(tmp_path / "sessions")
    application = _application(tmp_path, store)
    try:
        assert application.session_service is not None
        assert application.session_service.active_session is None
        assert application.session_catalog() == ()
        assert application.status().timeline_checkpoint_id is None
        assert application.create_run() is not None
        application.close()
        assert store.list_metadata(project_key=str((tmp_path / "project").resolve())) == ()
    finally:
        application.close()


def test_lazy_ensure_failure_leaves_idle_session_and_no_provider_work(
    tmp_path: Path,
) -> None:
    provider = FakeProvider(events=(_completed(),), model_limits=TEST_LIMITS)
    store = SessionFileStore(tmp_path / "sessions")
    application = _application(tmp_path, store, provider=provider)
    try:
        assert application.session_service is not None

        def fail_create(*_args, **_kwargs):
            raise SessionOperationError("storage")

        application.session_service.create_session_for_command = fail_create  # type: ignore[method-assign]
        created_runs = []
        original_create_run = application.create_run

        def record_create_run(*_args, **_kwargs):
            run = original_create_run(*_args, **_kwargs)
            created_runs.append(run)
            return run

        application.create_run = record_create_run  # type: ignore[method-assign]
        stdout = io.StringIO()
        stderr = io.StringIO()
        code = asyncio.run(
            _stream_exec(
                application,
                "ordinary prompt",
                stdout=stdout,
                stderr=stderr,
            )
        )
        assert code == 1
        assert application.session_service.active_session is None
        assert store.list_metadata(project_key=str((tmp_path / "project").resolve())) == ()
        assert provider.recorded_requests == ()
        assert created_runs == []
        application.close()
    finally:
        application.close()


@pytest.mark.asyncio
async def test_first_exec_prompt_lazily_creates_one_session_and_persists_user(
    tmp_path: Path,
) -> None:
    provider = FakeProvider(events=(_completed("exec answer"),), model_limits=TEST_LIMITS)
    store = SessionFileStore(tmp_path / "sessions")
    application = _application(tmp_path, store, provider=provider)
    try:
        code = await _stream_exec(
            application,
            "first ordinary prompt",
            stdout=io.StringIO(),
            stderr=io.StringIO(),
        )
        sessions = application.list_sessions()
        assert code == 0
        assert len(sessions) == 1
        snapshot = store.read_session(sessions[0].session_id)
        assert any(
            entry.payload.get("part", {}).get("text") == "first ordinary prompt"
            for entry in snapshot.transcript.entries
            if entry.kind is TranscriptKind.USER_MESSAGE
        )
    finally:
        application.close()


@pytest.mark.asyncio
async def test_first_resume_and_new_have_no_throwaway_session(
    tmp_path: Path,
) -> None:
    store = SessionFileStore(tmp_path / "resume-sessions")
    application = _application(tmp_path, store)
    try:
        _seed(application, "resume-target")
        outcome = await CommandDispatcher(
            create_builtin_registry(), application
        ).dispatch_text_async("/resume resume-target")
        assert outcome is not None and isinstance(outcome.ui_action, SessionChanged)
        assert outcome.ui_action.restored is True
        assert [item.session_id for item in application.list_sessions()] == [
            "resume-target"
        ]
    finally:
        application.close()

    new_root = tmp_path / "new"
    new_store = SessionFileStore(new_root / "sessions")
    new_application = _application(new_root, new_store)
    try:
        outcome = await CommandDispatcher(
            create_builtin_registry(), new_application
        ).dispatch_text_async("/new")
        assert outcome is not None and isinstance(outcome.ui_action, SessionChanged)
        assert outcome.ui_action.restored is False
        assert len(new_application.list_sessions()) == 1
    finally:
        new_application.close()


@pytest.mark.asyncio
async def test_new_resume_restore_transcript_timeline_instruction_state_and_status(tmp_path: Path) -> None:
    store = SessionFileStore(tmp_path / "sessions")
    application = _application(tmp_path, store)
    try:
        transcript = _seed(application)
        active = application.resume_session("session-1")
        assert active.transcript.entries == transcript.entries
        assert active.timeline.active_checkpoint is None
        status = await CommandDispatcher(create_builtin_registry(), application).dispatch_text_async("/status")
        assert status is not None and status.output is not None
        assert "Timeline checkpoint:" in status.output
        assert "dynamic input operating limit" in status.output
        assert "258K" not in status.output
        outcome = await CommandDispatcher(
            create_builtin_registry(), application
        ).dispatch_text_async("/resume session-1")
        assert outcome is not None and isinstance(outcome.ui_action, SessionChanged)
        assert outcome.ui_action.replay == active.replay
    finally:
        application.close()


@pytest.mark.asyncio
async def test_resume_exposes_sorted_safe_replay_records_without_side_effects(
    tmp_path: Path,
) -> None:
    store = SessionFileStore(tmp_path / "sessions")
    application = _application(tmp_path, store)
    try:
        session = application.create_session("replay")
        transcript = _replay_transcript("replay")
        session.append_transcript(transcript.entries)
        session.close()

        before_count = len(store.read_session("replay").transcript.entries)
        before_provider_calls = len(application.provider.recorded_requests)
        resumed = application.resume_session_for_command("replay")
        records = resumed.replay

        assert all(isinstance(record, SessionReplayRecord) for record in records)
        assert [record.sequence for record in records] == sorted(
            record.sequence for record in records
        )
        assert [record.kind for record in records] == [
            "user",
            "steering",
            "reasoning",
            "assistant",
            "tool",
            "assistant",
        ]
        assert records[0].text == "durable user"
        assert records[1].text == "steering secret"
        assert records[2].text == "private reasoning"
        assert records[3].text == "formal answer"
        assert records[4].tool_name == "Bash"
        assert records[4].status == "succeeded"
        assert records[4].text
        assert records[-1].text == "after tool"
        assert all(record.turn_id != "turn-pending" for record in records)
        encoded = json.dumps([record.to_dict() for record in records], ensure_ascii=False)
        assert "RAW-TOOL-RESULT-SECRET" not in encoded
        assert "API-KEY-SECRET" not in encoded
        assert "sk-raw-secret" not in encoded
        assert "native_secret" not in encoded
        assert "should not replay" not in encoded
        assert len(store.read_session("replay").transcript.entries) == before_count
        assert len(application.provider.recorded_requests) == before_provider_calls
    finally:
        application.close()


def test_resume_replay_projection_is_atomic_when_projection_fails(tmp_path: Path) -> None:
    store = SessionFileStore(tmp_path / "sessions")
    application = _application(tmp_path, store)
    try:
        _seed(application, "current")
        _seed(application, "target")
        # The staged target must be rejected before it replaces the active
        # Session.  Application's projection hook is intentionally failed to
        # exercise the transaction boundary without touching Provider/Turn.
        current = application.resume_session("current")
        original_replay = current.replay
        original_builder = application._build_session_replay
        application._build_session_replay = lambda _snapshot: (_ for _ in ()).throw(
            ValueError("replay projection failed")
        )
        with pytest.raises(SessionOperationError) as error:
            application.resume_session_for_command("target")
        assert error.value.kind == "corrupt"
        assert application.session_service is not None
        assert application.session_service.active_session is current
        assert current.replay == original_replay
        application._build_session_replay = original_builder
    finally:
        application.close()


def test_resume_busy_unknown_and_storage_failures_keep_active_session_atomic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = SessionFileStore(tmp_path / "sessions")
    application = _application(tmp_path, store)
    owner = _application(tmp_path, store)
    try:
        _seed(application, "current")
        _seed(application, "target")
        current = application.resume_session("current")
        original_replay = current.replay

        with pytest.raises(SessionOperationError) as unknown:
            application.resume_session_for_command("missing")
        assert unknown.value.kind == "unknown"
        # The command dispatcher owns user-facing conversion; the service
        # still keeps lifecycle ownership unchanged on an unknown target.
        assert application.session_service is not None
        assert application.session_service.active_session is current
        assert current.replay == original_replay

        held = owner.resume_session("target")
        try:
            with pytest.raises(SessionOperationError) as busy:
                application.resume_session_for_command("target")
            assert busy.value.kind == "busy"
            assert application.session_service.active_session is current
            assert current.replay == original_replay
        finally:
            held.close()

        def fail_open(*_args, **_kwargs):
            raise SessionFileError("storage failure")

        monkeypatch.setattr(store, "open_writer", fail_open)
        with pytest.raises(SessionOperationError) as storage:
            application.resume_session_for_command("target")
        assert storage.value.kind == "storage"
        assert application.session_service.active_session is current
        assert current.replay == original_replay
    finally:
        application.close()
        owner.close()


def test_resume_projects_legacy_full_message_once_without_rewriting_transcript(
    tmp_path: Path,
) -> None:
    store = SessionFileStore(tmp_path / "sessions")
    application = _application(tmp_path, store)
    try:
        application.create_session("legacy-replay").close()
        message = Message(
            "assistant",
            (ReasoningPart("legacy reasoning"), TextPart("legacy answer")),
        )
        legacy_payload = {
            "message_id": "turn-legacy:1",
            "message": message.to_dict(),
        }
        legacy_reasoning_entry = TranscriptEntry(
            "legacy-replay",
            1,
            "turn-legacy",
            TranscriptKind.ASSISTANT_MESSAGE,
            {**legacy_payload, "type": "reasoning", "text": "legacy reasoning"},
            semantic_unit_id="turn-legacy",
        )
        legacy_text_entry = TranscriptEntry(
            "legacy-replay",
            2,
            "turn-legacy",
            TranscriptKind.ASSISTANT_MESSAGE,
            {**legacy_payload, "type": "text", "text": "legacy answer"},
            semantic_unit_id="turn-legacy",
        )
        transcript_path = store.session_path("legacy-replay") / "transcript.jsonl"
        session_files._append_jsonl(
            transcript_path,
            (
                {
                    "schema_version": 2,
                    "kind": "transcript",
                    "sequence": 1,
                    "entry": legacy_reasoning_entry.to_dict(),
                },
                {
                    "schema_version": 2,
                    "kind": "transcript",
                    "sequence": 2,
                    "entry": legacy_text_entry.to_dict(),
                },
            ),
        )
        before_bytes = transcript_path.read_bytes()
        before_mtime = transcript_path.stat().st_mtime_ns

        resumed = application.resume_session_for_command("legacy-replay")

        assert [(record.kind, record.text) for record in resumed.replay] == [
            ("reasoning", "legacy reasoning"),
            ("assistant", "legacy answer"),
        ]
        assert transcript_path.read_bytes() == before_bytes
        assert transcript_path.stat().st_mtime_ns == before_mtime
    finally:
        application.close()


@pytest.mark.asyncio
async def test_resumed_transcript_enters_headless_provider_request(tmp_path: Path) -> None:
    provider = FakeProvider(events=(_completed(),), model_limits=TEST_LIMITS)
    store = SessionFileStore(tmp_path / "sessions")
    application = _application(tmp_path, store, provider=provider)
    try:
        _seed(application, "resume-transcript")
        application.resume_session_for_command("resume-transcript")
        result = await application.create_run().start_turn("NEW_TURN_MARKER").result()
        assert result.final_text == "done"
        text = _request_text(provider.recorded_requests[0])
        assert "first prompt" in text and "NEW_TURN_MARKER" in text
    finally:
        application.close()


def test_same_text_process_turn_is_not_deduplicated_against_durable_transcript() -> None:
    durable = _message_transcript("same-text", (Message("user", (TextPart("repeat"),)),))
    request, _snapshot = ApplicationContextService().compose_generation_request((Message("user", (TextPart("repeat"),)), Message("assistant", (TextPart("answer"),)), Message("user", (TextPart("repeat"),))), run_id="run", session_id="same-text", transcript=durable)
    repeats = [message for message in request.messages if message.role == "user" and any(isinstance(part, TextPart) and part.text == "repeat" for part in message.parts)]
    assert len(repeats) == 3


@pytest.mark.asyncio
async def test_new_command_releases_old_writer_and_opens_fresh_session(tmp_path: Path) -> None:
    store = SessionFileStore(tmp_path / "sessions")
    application = _application(tmp_path, store)
    try:
        _seed(application)
        outcome = await CommandDispatcher(create_builtin_registry(), application).dispatch_text_async("/new")
        assert outcome is not None and outcome.status is OutcomeStatus.SUCCESS
        assert isinstance(outcome.ui_action, SessionChanged)
        assert outcome.ui_action.restored is False
    finally:
        application.close()


@pytest.mark.asyncio
async def test_resume_busy_and_unknown_are_user_visible(tmp_path: Path) -> None:
    store = SessionFileStore(tmp_path / "sessions")
    owner = _application(tmp_path, store)
    contender = _application(tmp_path, store)
    try:
        _seed(owner, "busy")
        held = owner.resume_session("busy")
        busy = await CommandDispatcher(create_builtin_registry(), contender).dispatch_text_async("/resume busy")
        assert busy is not None and busy.status is OutcomeStatus.EXECUTION_ERROR and "Session busy" in (busy.error or "")
        held.close()
        unknown = await CommandDispatcher(create_builtin_registry(), contender).dispatch_text_async("/resume missing")
        assert unknown is not None and unknown.error == "unknown Session: missing"
    finally:
        owner.close()
        contender.close()


@pytest.mark.asyncio
async def test_compact_command_surfaces_success_and_noop(tmp_path: Path) -> None:
    store = SessionFileStore(tmp_path / "sessions")
    provider = FakeProvider(
        events=(
            _completed(
                json.dumps(
                    {
                        "entries": [{"turn_id": "turn-1", "summary": "bounded summary"}],
                        "coverage": ["turn-1"],
                    }
                )
            ),
        ),
        model_limits=TEST_LIMITS,
    )
    application = _application(tmp_path, store, provider=provider)
    try:
        _seed(application, "compact")
        application.resume_session("compact")
        dispatcher = CommandDispatcher(create_builtin_registry(), application)
        first = await dispatcher.dispatch_text_async("/compact")
        second = await dispatcher.dispatch_text_async("/compact")
        assert first is not None and first.status is OutcomeStatus.SUCCESS
        assert first.output is not None and "Timeline checkpoint" in first.output
        assert second is not None and second.status is OutcomeStatus.SUCCESS
        assert second.output is not None and "无需压缩" in second.output
        status = await dispatcher.dispatch_text_async("/status")
        assert status is not None and status.output is not None
        assert "context limits:" in status.output
        assert "default=256000" in status.output
        assert "effective=1000000" in status.output
        assert "source=configured" in status.output
        assert "observed=['configured', 'provider']" in status.output
        assert "tightened=[]" in status.output
        assert "context gate:" in status.output and "hard_safe=True" in status.output
        assert "context outcome:" in status.output
        assert application.session_service.active_session.timeline.active_checkpoint is not None  # type: ignore[union-attr]
    finally:
        application.close()


@pytest.mark.asyncio
async def test_compact_command_reports_non_reducing_candidate_as_successful_noop(
    tmp_path: Path,
) -> None:
    store = SessionFileStore(tmp_path / "sessions")
    non_reducing_summary = "x" * 3_000
    provider = FakeProvider(
        events=(
            _completed(
                json.dumps(
                    {
                        "entries": [
                            {"turn_id": "turn-1", "summary": non_reducing_summary}
                        ],
                        "coverage": ["turn-1"],
                    }
                )
            ),
        ),
        model_limits=TEST_LIMITS,
    )
    application = _application(tmp_path, store, provider=provider)
    try:
        _seed(application, "compact-non-reducing")
        active = application.resume_session("compact-non-reducing")
        before_records = active.timeline.records
        dispatcher = CommandDispatcher(create_builtin_registry(), application)

        outcome = await dispatcher.dispatch_text_async("/compact")

        assert outcome is not None and outcome.status is OutcomeStatus.SUCCESS
        assert outcome.output is not None and "无需压缩" in outcome.output
        assert active.timeline.records == before_records
        assert active.timeline.fine_entries == ()
        assert active.timeline.macro_summaries == ()
        assert active.timeline.active_checkpoint is None
        assert len(provider.recorded_requests) == 1
    finally:
        application.close()


def test_session_picker_has_fixed_ten_page_and_keyboard_state() -> None:
    entries = tuple(SimpleNamespace(session_id=f"session-{index:02d}", last_used_at=f"2026-08-17T00:{index:02d}:00+00:00", preview=f"prompt {index}") for index in range(21))
    picker = SessionPickerState()
    picker.replace(entries)
    assert picker.page_size == 10 and picker.page_count == 3
    picker.move(1)
    assert picker.selected.session_id == "session-01"
    picker.next_page()
    assert picker.selected.session_id == "session-11"


def test_status_bar_and_input_ring_share_dynamic_usage_projection() -> None:
    low = ContextUsage(10, budget_tokens=25_000)
    high = ContextUsage(250_000, budget_tokens=250_000)
    unavailable = ContextUsage(0, budget_tokens=None, available=False)
    assert context_usage_style(low) == "class:status"
    assert context_usage_style(high) == "class:status.warning"
    assert context_usage_style(unavailable) == "class:status"
    assert context_usage_bar(low)[1].endswith("10/25K")
    assert context_usage_ring(high)[1].endswith("250000/250K")
    assert "unavailable/?" in context_usage_ring(unavailable)[1]
