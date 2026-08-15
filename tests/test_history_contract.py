from __future__ import annotations

import pytest

from uthcode.core.history import (
    CanonicalHistory,
    HistoryBoundaryError,
    HistoryEnvelopeError,
    HistoryEntry,
    HistoryKind,
    HistorySequenceError,
    HISTORY_SCHEMA_VERSION,
    Projection,
    RuntimeLog,
    RuntimeLogEntry,
)
from uthcode.application.history import ApplicationHistory


def _entry_dict(
    *,
    kind: str = HistoryKind.USER_MESSAGE.value,
    payload: dict[str, object] | None = None,
    **overrides: object,
) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": HISTORY_SCHEMA_VERSION,
        "session_id": "session-1",
        "sequence": 1,
        "turn_id": "turn-1",
        "kind": kind,
        "payload": {"text": "inspect"} if payload is None else payload,
        "created_at": "2026-08-15T00:00:00+00:00",
        "commit_boundary": True,
        "semantic_unit_id": None,
    }
    value.update(overrides)
    return value


def _history() -> CanonicalHistory:
    history = CanonicalHistory("session-1")
    history = history.append(
        turn_id="turn-1",
        kind=HistoryKind.USER_MESSAGE,
        payload={"text": "inspect"},
    )
    history = history.append(
        turn_id="turn-1",
        kind=HistoryKind.TOOL_CALL,
        payload={"tool_call_id": "call-1", "name": "ReadFile"},
    )
    return history.append(
        turn_id="turn-1",
        kind=HistoryKind.TOOL_RESULT,
        payload={"tool_call_id": "call-1", "content": "ok"},
    )


def test_history_schema_kind_sequence_and_json_round_trip() -> None:
    history = _history()
    serialized = history.to_jsonl()
    restored = CanonicalHistory.from_jsonl("session-1", serialized)
    assert restored == history
    assert restored.to_jsonl() == serialized
    assert restored.last_sequence == 3
    assert any(unit.contains_tool_pair for unit in restored.complete_semantic_units())

    with pytest.raises(ValueError, match="unknown history kind"):
        HistoryEntry.from_dict(_entry_dict(kind="future_kind"))
    with pytest.raises(HistorySequenceError):
        CanonicalHistory(
            "session-1",
            (HistoryEntry.from_dict(_entry_dict(sequence=2)),),
        )


def test_history_entry_persisted_envelope_is_strict() -> None:
    for kind in ("user", "assistant", "tool", "future_kind"):
        with pytest.raises(ValueError):
            HistoryEntry.from_dict(_entry_dict(kind=kind))

    for field in ("schema_version", "created_at", "commit_boundary"):
        invalid = _entry_dict()
        del invalid[field]
        with pytest.raises(HistoryEnvelopeError, match="missing required fields"):
            HistoryEntry.from_dict(invalid)

    with pytest.raises(ValueError, match="unsupported history schema_version"):
        HistoryEntry.from_dict(_entry_dict(schema_version=999))
    with pytest.raises(HistoryEnvelopeError, match="unknown fields"):
        HistoryEntry.from_dict(_entry_dict(extra_field="reject"))
    with pytest.raises(TypeError, match="JSON object"):
        HistoryEntry.from_dict(_entry_dict(payload=[]))
    with pytest.raises(TypeError, match="object"):
        HistoryEntry.from_json("[]")


@pytest.mark.parametrize("kind", [HistoryKind.TOOL_CALL.value, HistoryKind.TOOL_RESULT.value])
def test_tool_entries_require_non_empty_call_id(kind: str) -> None:
    with pytest.raises(ValueError, match="tool_call_id"):
        HistoryEntry.from_dict(_entry_dict(kind=kind, payload={}))
    with pytest.raises(ValueError, match="tool_call_id"):
        HistoryEntry.from_dict(_entry_dict(kind=kind, payload={"tool_call_id": "  "}))


def test_incomplete_tool_groups_never_become_complete_units() -> None:
    duplicate = CanonicalHistory("session-1")
    for kind, payload in (
        (HistoryKind.TOOL_CALL, {"tool_call_id": "call-1"}),
        (HistoryKind.TOOL_CALL, {"tool_call_id": "call-1"}),
        (HistoryKind.TOOL_RESULT, {"tool_call_id": "call-1"}),
        (HistoryKind.TOOL_RESULT, {"tool_call_id": "call-1"}),
    ):
        duplicate = duplicate.append(turn_id="turn-1", kind=kind, payload=payload)
    assert duplicate.complete_semantic_units() == ()

    mismatch = CanonicalHistory("session-1")
    mismatch = mismatch.append(
        turn_id="turn-1",
        kind=HistoryKind.TOOL_CALL,
        payload={"tool_call_id": "call-1"},
    )
    mismatch = mismatch.append(
        turn_id="turn-1",
        kind=HistoryKind.TOOL_RESULT,
        payload={"tool_call_id": "call-2"},
    )
    assert mismatch.complete_semantic_units() == ()

    missing_result = CanonicalHistory("session-1").append(
        turn_id="turn-1",
        kind=HistoryKind.TOOL_CALL,
        payload={"tool_call_id": "call-1"},
    )
    assert missing_result.complete_semantic_units() == ()

    extra_result = CanonicalHistory("session-1")
    extra_result = extra_result.append(
        turn_id="turn-1",
        kind=HistoryKind.TOOL_CALL,
        payload={"tool_call_id": "call-1"},
    )
    extra_result = extra_result.append(
        turn_id="turn-1",
        kind=HistoryKind.TOOL_RESULT,
        payload={"tool_call_id": "call-1"},
    )
    extra_result = extra_result.append(
        turn_id="turn-1",
        kind=HistoryKind.TOOL_RESULT,
        payload={"tool_call_id": "call-2"},
    )
    assert extra_result.complete_semantic_units() == ()


def test_tool_call_and_result_are_one_atomic_selection_unit() -> None:
    history = _history()
    original = history.to_jsonl()
    with pytest.raises(HistoryBoundaryError):
        history.select(sequence_start=2, sequence_end=2)
    projection = history.project(revision=1, sequence_start=2, sequence_end=3)
    assert projection.sequence_start == 2
    assert projection.sequence_end == 3
    assert history.to_jsonl() == original

    with pytest.raises(ValueError, match="authority"):
        Projection(
            session_id="session-1",
            revision=2,
            sequence_start=2,
            sequence_end=3,
            units=projection.units,
            previous_revision=1,
            authority="project_instruction",
        )

    batch = CanonicalHistory("batch")
    batch = batch.append(
        turn_id="turn-1",
        kind=HistoryKind.TOOL_CALL,
        payload={"tool_call_id": "a"},
    )
    batch = batch.append(
        turn_id="turn-1",
        kind=HistoryKind.TOOL_CALL,
        payload={"tool_call_id": "b"},
    )
    batch = batch.append(
        turn_id="turn-1",
        kind=HistoryKind.TOOL_RESULT,
        payload={"tool_call_id": "a"},
    )
    batch = batch.append(
        turn_id="turn-1",
        kind=HistoryKind.TOOL_RESULT,
        payload={"tool_call_id": "b"},
    )
    units = batch.complete_semantic_units()
    assert len(units) == 1
    assert units[0].sequence_start == 1 and units[0].sequence_end == 4


def test_runtime_log_is_separate_and_projection_revision_does_not_rewrite_history() -> None:
    history = _history()
    before = history.to_jsonl()
    runtime = RuntimeLog().append(RuntimeLogEntry("stream_delta", {"text": "partial"}))
    projection = history.project(revision=2, sequence_start=1, sequence_end=3, previous_revision=1)
    assert runtime.entries[0].kind == "stream_delta"
    assert projection.authority == "history_projection"
    assert history.to_jsonl() == before


def test_application_history_coordinates_values_without_persisting_or_rewriting() -> None:
    state = ApplicationHistory("session-1").append_record(
        turn_id="turn-1",
        kind=HistoryKind.USER_MESSAGE,
        payload={"text": "hello"},
    )
    projected = state.project(revision=1)
    assert projected.history == state.history
    assert projected.projection is not None
    assert projected.history.to_jsonl() == state.history.to_jsonl()
