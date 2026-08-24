from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from uthcode.application import ApplicationContextService, CommandDispatcher, ContextUsage, EffectiveConfig, OpenSessionPicker, OutcomeStatus, SessionChanged, SessionOperationError, create_application, create_builtin_registry
from uthcode.application.history import _transcript_entries_for_message
from uthcode.application.instructions import InstructionLoader
from uthcode.application.runtime_context import ApplicationRuntimeContext
from uthcode.core.history import ActiveCheckpoint, SemanticEntry, Transcript, TranscriptEntry, TranscriptKind
from uthcode.core.provider import FinishReason, GenerationCompleted, Message, ModelLimits, ProviderResponse, TextPart, ToolCallPart, ToolResultPart, Usage
from uthcode.integrations.instruction_files import InstructionFileReader
from uthcode.integrations.providers.fake import FakeProvider
from uthcode.integrations.session_files import SessionBusyError, SessionFileError, SessionFileStore
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


@pytest.mark.asyncio
async def test_w04_commands_are_registered_and_compact_rejects_extra_arguments() -> None:
    registry = create_builtin_registry()
    dispatcher = CommandDispatcher(registry)
    assert callable(registry.resolve("compact").handler)  # type: ignore[union-attr]
    assert isinstance((await dispatcher.dispatch_text_async("/resume")).ui_action, OpenSessionPicker)  # type: ignore[union-attr]
    rejected = await dispatcher.dispatch_text_async("/compact -- focus")
    assert rejected is not None and rejected.status is OutcomeStatus.USAGE_ERROR


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
