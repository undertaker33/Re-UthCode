"""Application-owned conversion from provider messages to durable Transcript."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from uthcode.core.history import (
    ActiveCheckpoint,
    RuntimeLog,
    RuntimeLogEntry,
    SemanticEntry,
    Timeline,
    Transcript,
    TranscriptEntry,
    TranscriptKind,
    transcript_entries_from_message,
)
from uthcode.core.provider import JsonPayload, Message


@dataclass(frozen=True, slots=True)
class ApplicationHistory:
    """Coordinate a Session's raw Transcript and derived Timeline in memory."""

    session_id: str
    transcript: Transcript | None = None
    timeline: Timeline | None = None
    runtime_log: RuntimeLog | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.session_id, str) or not self.session_id.strip():
            raise ValueError("session_id must be a non-empty string")
        transcript = self.transcript or Transcript(self.session_id)
        timeline = self.timeline
        runtime_log = self.runtime_log or RuntimeLog(self.session_id)
        if transcript.session_id != self.session_id:
            raise ValueError("transcript belongs to another session")
        if timeline is not None and timeline.session_id != self.session_id:
            raise ValueError("timeline belongs to another session")
        if runtime_log.session_id != self.session_id:
            raise ValueError("runtime log belongs to another session")
        object.__setattr__(self, "transcript", transcript)
        object.__setattr__(self, "runtime_log", runtime_log)

    @property
    def history(self) -> Transcript:
        """Current raw facts; retained as a descriptive property, not a legacy type."""

        assert self.transcript is not None
        return self.transcript

    @property
    def active_timeline(self) -> Timeline | None:
        return self.timeline

    def append(self, entry: TranscriptEntry) -> "ApplicationHistory":
        return ApplicationHistory(
            self.session_id,
            transcript=self.history.append(entry),
            timeline=self.timeline,
            runtime_log=self.runtime_log,
        )

    def append_record(
        self,
        *,
        turn_id: str,
        kind: TranscriptKind | str,
        payload: Mapping[str, Any] | JsonPayload | None = None,
        semantic_unit_id: str | None = None,
    ) -> "ApplicationHistory":
        entry = TranscriptEntry(
            session_id=self.session_id,
            sequence=self.history.last_sequence + 1,
            turn_id=turn_id,
            kind=TranscriptKind(kind),
            payload=payload or {},
            semantic_unit_id=semantic_unit_id,
        )
        return self.append(entry)

    def append_message(self, *, turn_id: str, message: Message) -> "ApplicationHistory":
        result = self
        for entry in transcript_entries_for_message(
            self.session_id, turn_id, self.history.last_sequence + 1, message
        ):
            result = result.append(entry)
        return result

    def replace_timeline(self, timeline: Timeline) -> "ApplicationHistory":
        if not isinstance(timeline, Timeline) or timeline.session_id != self.session_id:
            raise ValueError("timeline belongs to another session")
        return ApplicationHistory(
            self.session_id,
            transcript=self.history,
            timeline=timeline,
            runtime_log=self.runtime_log,
        )

    def append_runtime(self, entry: RuntimeLogEntry) -> "ApplicationHistory":
        return ApplicationHistory(
            self.session_id,
            transcript=self.history,
            timeline=self.timeline,
            runtime_log=self.runtime_log.append(entry),
        )


def transcript_entries_for_message(
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


__all__ = ["ApplicationHistory", "transcript_entries_for_message"]
