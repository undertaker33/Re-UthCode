from __future__ import annotations

import json

import pytest

from uthcode.core.history import transcript_entries_from_message
from uthcode.core.history import (
    Transcript,
    TranscriptBoundaryError,
    TranscriptEntry,
    TranscriptKind,
    TranscriptRef,
    TranscriptSequenceError,
)
from uthcode.core.provider import Message, NativeItem, ReasoningPart, TextPart, ToolCallPart, ToolResultPart


def _entry(sequence: int, *, turn_id: str = "turn-1", kind: TranscriptKind = TranscriptKind.USER_MESSAGE, unit: str | None = None, payload: dict | None = None, commit_boundary: bool = True) -> TranscriptEntry:
    return TranscriptEntry(
        session_id="session-1",
        sequence=sequence,
        turn_id=turn_id,
        kind=kind,
        payload=payload or {"text": f"message-{sequence}"},
        commit_boundary=commit_boundary,
        semantic_unit_id=unit or turn_id,
    )


def test_transcript_is_strict_and_round_trips_jsonl() -> None:
    transcript = Transcript("session-1").append(_entry(1))
    transcript = transcript.append(_entry(2, turn_id="turn-2"))
    restored = Transcript.from_jsonl("session-1", transcript.to_jsonl())
    assert restored == transcript
    with pytest.raises(TranscriptSequenceError):
        transcript.append(_entry(4, turn_id="turn-3"))


def test_tool_call_and_result_are_one_complete_semantic_unit() -> None:
    call = _entry(1, kind=TranscriptKind.TOOL_CALL, payload={"tool_call_id": "call-1", "type": "tool_call"})
    result = _entry(2, kind=TranscriptKind.TOOL_RESULT, payload={"tool_call_id": "call-1", "type": "tool_result"})
    transcript = Transcript("session-1", (call, result))
    unit = transcript.semantic_units()[0]
    assert unit.complete is True
    assert transcript.reference(1, 2).session_id == "session-1"
    with pytest.raises(TranscriptBoundaryError):
        transcript.reference(1, 1)


def test_matching_tool_pair_does_not_close_a_non_tool_open_entry() -> None:
    open_message = _entry(1, unit="turn-1", commit_boundary=False)
    call = _entry(2, kind=TranscriptKind.TOOL_CALL, unit="turn-1", payload={"tool_call_id": "call-1", "type": "tool_call"})
    result = _entry(3, kind=TranscriptKind.TOOL_RESULT, unit="turn-1", payload={"tool_call_id": "call-1", "type": "tool_result"})
    transcript = Transcript("session-1", (open_message, call, result))
    assert transcript.semantic_units()[0].complete is False
    with pytest.raises(TranscriptBoundaryError):
        transcript.reference(1, 3)


def test_transcript_ref_is_opaque_and_ownership_is_encoded() -> None:
    reference = TranscriptRef("session-1", 1, 2)
    token = reference.to_token()
    assert "session-1" not in token
    assert TranscriptRef.from_token(token) == reference
    with pytest.raises(ValueError):
        TranscriptRef.from_token("not-a-ref")


def test_application_message_conversion_preserves_complete_message_identity() -> None:
    message = Message(
        "assistant",
        (
            ToolCallPart("call-1", "lookup", {"q": "x"}),
            ToolResultPart("call-1", "done"),
        ),
    )
    entries = transcript_entries_from_message("session-1", "turn-1", 1, message)
    assert len(entries) == 2
    assert {entry.semantic_unit_id for entry in entries} == {"turn-1"}
    assert [entry.payload["message_id"] for entry in entries] == ["turn-1:1", "turn-1:1"]
    assert [entry.payload["message_part_index"] for entry in entries] == [0, 1]
    assert [entry.payload["role"] for entry in entries] == ["assistant", "assistant"]
    assert [entry.payload["part"] for entry in entries] == [
        message.parts[0].to_dict(),
        message.parts[1].to_dict(),
    ]
    assert all("message" not in entry.payload for entry in entries)


def test_application_message_conversion_keeps_each_reasoning_carrier_local() -> None:
    reasoning_native = NativeItem(
        "anthropic",
        "messages",
        "claude-test",
        sequence_index=0,
        kind="thinking",
        payload={"type": "thinking", "thinking": "plan", "signature": "sig"},
    )
    text_native = NativeItem(
        "anthropic",
        "messages",
        "claude-test",
        sequence_index=1,
        kind="text",
        payload={"type": "text", "text": "answer"},
    )
    message = Message(
        "assistant",
        (ReasoningPart("plan"), TextPart("answer")),
        native_items=(reasoning_native, text_native),
    )

    entries = transcript_entries_from_message("session-1", "turn-2", 4, message)

    assert [entry.payload["part"] for entry in entries] == [
        {"type": "reasoning", "text": "plan"},
        {"type": "text", "text": "answer"},
    ]
    assert entries[0].payload["native_items"] == [reasoning_native.to_dict()]
    assert entries[1].payload["native_items"] == [text_native.to_dict()]
    encoded = "".join(json.dumps(entry.to_dict(), ensure_ascii=False) for entry in entries)
    assert encoded.count('"message"') == 0
    assert encoded.count('"part"') == 2
