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
    """Persist one Message as part-local entries in one semantic unit."""

    return transcript_entries_from_message(session_id, turn_id, sequence, message)
