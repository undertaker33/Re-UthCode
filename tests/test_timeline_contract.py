from __future__ import annotations

import pytest

from uthcode.core.history import (
    ActiveCheckpoint,
    EpochMacroSummary,
    SemanticEntry,
    Timeline,
    TimelineError,
    Transcript,
    TranscriptEntry,
    TranscriptKind,
)


def _transcript() -> Transcript:
    values = tuple(
        TranscriptEntry("session-1", sequence, f"turn-{sequence}", TranscriptKind.USER_MESSAGE, {"text": str(sequence)}, semantic_unit_id=f"turn-{sequence}")
        for sequence in range(1, 4)
    )
    return Transcript("session-1", values)


def test_timeline_has_only_fine_macro_and_checkpoint_records() -> None:
    transcript = _transcript()
    fine = SemanticEntry("turn-1", "fine summary", (transcript.reference(1, 1),), session_id="session-1")
    macro = EpochMacroSummary("turn-1", "macro summary", (transcript.reference(1, 1),), ("turn-1",), session_id="session-1")
    checkpoint = ActiveCheckpoint("turn-1", ("turn-1",), session_id="session-1")
    timeline = Timeline("session-1").append_transaction((fine,), checkpoint)
    assert timeline.fine_entries == (fine,)
    assert timeline.active_checkpoint == checkpoint
    assert timeline.committed_records == (fine, checkpoint)
    assert timeline.append_transaction((macro,), ActiveCheckpoint("turn-1", ("turn-1",), session_id="session-1")).macro_summaries == (macro,)


def test_checkpoint_last_controls_logical_view_and_trailing_records_are_ignored() -> None:
    transcript = _transcript()
    fine = SemanticEntry("turn-1", "fine summary", (transcript.reference(1, 1),), session_id="session-1")
    checkpoint = ActiveCheckpoint("turn-1", ("turn-1",), session_id="session-1")
    trailing = SemanticEntry("turn-2", "uncommitted", (transcript.reference(2, 2),), session_id="session-1")
    timeline = Timeline("session-1", (fine, checkpoint, trailing))
    assert timeline.committed_records == (fine, checkpoint)
    assert timeline.trailing_records == (trailing,)
    restored = Timeline.from_jsonl("session-1", timeline.to_jsonl())
    assert restored.committed_records == timeline.committed_records
    assert restored.trailing_records == timeline.trailing_records


def test_reopened_trailing_transaction_cannot_be_revived_by_a_later_checkpoint() -> None:
    transcript = _transcript()
    first = SemanticEntry("turn-1", "first", (transcript.reference(1, 1),), session_id="session-1")
    first_checkpoint = ActiveCheckpoint("turn-1", ("turn-1",), session_id="session-1")
    committed = Timeline("session-1").append_transaction((first,), first_checkpoint)

    crashed = SemanticEntry("turn-2", "crashed", (transcript.reference(2, 2),), session_id="session-1")
    reopened = Timeline("session-1", committed.records + (crashed,))
    assert [record.summary for record in reopened.committed_records if isinstance(record, SemanticEntry)] == ["first"]
    assert reopened.trailing_records == (crashed,)

    fresh = SemanticEntry("turn-3", "fresh", (transcript.reference(3, 3),), session_id="session-1")
    fresh_checkpoint = ActiveCheckpoint("turn-3", ("turn-3",), session_id="session-1")
    after = reopened.append_transaction((fresh,), fresh_checkpoint)

    assert [record.summary for record in after.committed_records if isinstance(record, SemanticEntry)] == ["first", "fresh"]
    assert after.trailing_records == (crashed,)
    assert Timeline("session-1", after.records).committed_records == after.committed_records


def test_checkpoint_cannot_be_a_fourth_or_empty_record() -> None:
    checkpoint = ActiveCheckpoint("turn-1", (), session_id="session-1")
    with pytest.raises(TimelineError):
        Timeline("session-1").append(checkpoint)
