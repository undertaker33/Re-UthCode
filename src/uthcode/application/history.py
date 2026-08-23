"""Private application conversion from provider messages to durable Transcript."""

from __future__ import annotations

from uthcode.core.history import TranscriptEntry, transcript_entries_from_message
from uthcode.core.provider import Message


def _transcript_entries_for_message(
    session_id: str,
    turn_id: str,
    sequence: int,
    message: Message,
) -> tuple[TranscriptEntry, ...]:
    """Persist one complete Message as an identity-local semantic unit."""

    entries = transcript_entries_from_message(session_id, turn_id, sequence, message)
    message_id = f"{turn_id}:{sequence}"
    converted: list[TranscriptEntry] = []
    for entry in entries:
        payload = dict(entry.payload)
        payload["message"] = message.to_dict()
        payload["message_id"] = message_id
        converted.append(
            TranscriptEntry(
                session_id=entry.session_id,
                sequence=entry.sequence,
                turn_id=entry.turn_id,
                kind=entry.kind,
                payload=payload,
                created_at=entry.created_at,
                commit_boundary=entry.commit_boundary,
                semantic_unit_id=entry.semantic_unit_id,
            )
        )
    return tuple(converted)
