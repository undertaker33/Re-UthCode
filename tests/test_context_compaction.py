from __future__ import annotations

import pytest

from uthcode.application.context import ApplicationContextService
from uthcode.core.context import CompactionPolicy, ContextCompactor
from uthcode.core.history import ActiveCheckpoint, SemanticEntry, Timeline, Transcript, TranscriptEntry, TranscriptKind


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
    assert result.failure == "summarizer_unavailable"
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


def test_application_context_compact_records_bounded_diagnostics() -> None:
    transcript = _transcript()
    service = ApplicationContextService()
    result = service.compact(transcript, summarize=lambda _text: "summary")
    assert result.timeline is not None
    diagnostics = service.public_diagnostics()
    assert diagnostics["compaction"]["count"] == 1
    assert diagnostics["compaction"]["last"]["batch_count"] >= 1


def test_context_compactor_single_flight_rejects_reentrant_lock() -> None:
    compactor = ContextCompactor()
    transcript = _transcript()
    lock = compactor._acquire_single_flight(transcript.session_id)
    try:
        with pytest.raises(Exception, match="already running"):
            compactor.compact(transcript, summarize=lambda _text: "summary")
    finally:
        lock.release()
