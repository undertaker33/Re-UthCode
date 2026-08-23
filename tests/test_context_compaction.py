from __future__ import annotations

import pytest

from uthcode.application.context import ApplicationContextService
from uthcode.core.context import CompactionPolicy, ContextCompactor
from uthcode.core.history import ActiveCheckpoint, EpochMacroSummary, SemanticEntry, Timeline, Transcript, TranscriptEntry, TranscriptKind, TranscriptRef


def _transcript() -> Transcript:
    entries = tuple(
        TranscriptEntry("compact-session", index, f"turn-{index}", TranscriptKind.USER_MESSAGE, {"text": f"fact-{index}"}, semantic_unit_id=f"turn-{index}")
        for index in range(1, 5)
    )
    return Transcript("compact-session", entries)


def test_compactor_returns_timeline_candidate_with_refs_and_checkpoint() -> None:
    transcript = _transcript()
    result = ContextCompactor(policy=CompactionPolicy(input_budget=500, output_reserve=50, summary_hard_cap=100), token_estimator=lambda text: max(1, len(text) // 20)).compact(transcript, summarize=lambda text: "bounded summary")
    assert result.changed is True
    assert result.timeline is not None
    assert isinstance(result.timeline.active_checkpoint, ActiveCheckpoint)
    assert result.timeline.fine_entries
    assert all(entry.refs[0].session_id == transcript.session_id for entry in result.timeline.fine_entries)


def test_compactor_no_summary_is_controlled_and_does_not_mutate_transcript() -> None:
    transcript = _transcript()
    before = transcript
    result = ContextCompactor().compact(transcript)
    assert result.changed is False
    assert result.failure == "summary_function_required"
    assert result.timeline is None
    assert transcript == before


def test_compactor_respects_existing_committed_timeline() -> None:
    transcript = _transcript()
    first = SemanticEntry("turn-1", "old", (transcript.reference(1, 1),), session_id=transcript.session_id)
    previous = Timeline(transcript.session_id).append_transaction((first,), ActiveCheckpoint("turn-1", ("turn-1",), session_id=transcript.session_id))
    result = ContextCompactor(token_estimator=lambda _text: 1).compact(transcript, timeline=previous, summarize=lambda _text: "new")
    assert result.changed is True
    assert result.timeline is not None
    assert result.timeline.active_checkpoint is not None
    assert result.timeline.sequence_end == transcript.last_sequence


@pytest.mark.asyncio
async def test_application_context_compact_records_bounded_diagnostics() -> None:
    transcript = _transcript()
    service = ApplicationContextService()

    async def summarize(epoch):
        return {"summary": "summary", "coverage": list(epoch.turn_ids)}

    result = await service.compact_async(transcript, summarize=summarize)
    assert result.timeline is not None
    diagnostics = service.public_diagnostics()
    assert diagnostics["compaction"]["count"] == 1
    assert diagnostics["compaction"]["last"]["coverage_count"] >= 1


def test_context_compactor_single_flight_rejects_reentrant_lock() -> None:
    compactor = ContextCompactor()
    transcript = _transcript()
    lock = compactor._acquire_single_flight(transcript.session_id)
    try:
        with pytest.raises(Exception, match="already running"):
            compactor.compact(transcript, summarize=lambda _text: "summary")
    finally:
        lock.release()


@pytest.mark.asyncio
async def test_timeline_aging_uses_raw_transcript_and_logically_supersedes_fine() -> None:
    transcript = _transcript()
    fine = tuple(
        SemanticEntry(
            f"turn-{index}",
            f"Fine summary {index}",
            (transcript.reference(index, index),),
            session_id=transcript.session_id,
        )
        for index in range(1, 5)
    )
    timeline = Timeline(transcript.session_id).append_transaction(
        fine,
        ActiveCheckpoint("turn-4", tuple(entry.turn_id for entry in fine), session_id=transcript.session_id),
    )
    compactor = ContextCompactor(
        policy=CompactionPolicy(input_budget=500, output_reserve=50, summary_hard_cap=100),
        token_estimator=lambda text: max(1, len(text) // 20),
    )
    service = ApplicationContextService(compactor=compactor)
    captured: list[str] = []

    async def summarize(epoch):
        captured.append(epoch.input_text)
        return {"summary": "one macro", "coverage": list(epoch.turn_ids)}

    result = await service.age_timeline_async(
        transcript,
        timeline=timeline,
        summarize=summarize,
        fine_budget=1,
        input_budget=500,
        output_reserve=50,
        summary_hard_cap=100,
    )

    assert result.changed is True
    assert result.timeline is not None
    assert len(captured) == 1
    assert "Fine summary" not in captured[0]
    assert "fact-1" in captured[0]
    assert result.timeline.physical_fine_entries == fine
    assert result.timeline.fine_entries == ()
    assert len(result.timeline.macro_summaries) == 1
    assert isinstance(result.timeline.logical_records[-2], EpochMacroSummary)
    assert result.timeline.records[-1].record_type == "active_checkpoint"
    assert service.public_diagnostics()["compaction"]["last"]["level"] == "L5"


@pytest.mark.asyncio
async def test_timeline_aging_rejects_an_unsafe_oldest_fine_epoch_without_model_call() -> None:
    transcript = _transcript()
    malformed = SemanticEntry(
        "turn-1",
        "Fine summary",
        (TranscriptRef(transcript.session_id, 1, 2),),
        session_id=transcript.session_id,
    )
    timeline = Timeline(transcript.session_id).append_transaction(
        (malformed,),
        ActiveCheckpoint("turn-1", ("turn-1",), session_id=transcript.session_id),
    )
    service = ApplicationContextService(
        compactor=ContextCompactor(token_estimator=lambda text: max(1, len(text) // 20))
    )
    called = False

    async def summarize(_epoch):
        nonlocal called
        called = True
        return {"summary": "must not run"}

    result = await service.age_timeline_async(
        transcript,
        timeline=timeline,
        summarize=summarize,
        fine_budget=1,
    )
    assert result.changed is False
    assert result.failure == "no_safe_epoch"
    assert called is False
