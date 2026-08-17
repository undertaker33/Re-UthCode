"""Application-owned history conversion and in-memory orchestration."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping

from uthcode.core.history import (
    CanonicalHistory,
    HistoryEntry,
    HistoryKind,
    Projection,
    RuntimeLog,
    RuntimeLogEntry,
    history_entries_from_message,
)
from uthcode.core.provider import JsonPayload, Message


@dataclass(frozen=True, slots=True)
class ApplicationHistory:
    """Coordinate one append-only semantic history and its active projection."""

    session_id: str
    canonical: CanonicalHistory | None = None
    projection: Projection | None = None
    runtime_log: RuntimeLog = RuntimeLog()

    def __post_init__(self) -> None:
        if not isinstance(self.session_id, str) or not self.session_id.strip():
            raise ValueError("session_id must be a non-empty string")
        canonical = self.canonical or CanonicalHistory(self.session_id)
        if not isinstance(canonical, CanonicalHistory):
            raise TypeError("canonical must be CanonicalHistory or None")
        if canonical.session_id != self.session_id:
            raise ValueError("canonical history belongs to another session")
        if self.projection is not None:
            if not isinstance(self.projection, Projection):
                raise TypeError("projection must be Projection or None")
            if self.projection.session_id != self.session_id:
                raise ValueError("projection belongs to another session")
        if not isinstance(self.runtime_log, RuntimeLog):
            raise TypeError("runtime_log must be RuntimeLog")
        object.__setattr__(self, "canonical", canonical)

    @property
    def history(self) -> CanonicalHistory:
        assert self.canonical is not None
        return self.canonical

    @property
    def active_projection(self) -> Projection | None:
        return self.projection

    def append(self, entry: HistoryEntry) -> "ApplicationHistory":
        return ApplicationHistory(
            session_id=self.session_id,
            canonical=self.history.append(entry),
            projection=self.projection,
            runtime_log=self.runtime_log,
        )

    def append_record(
        self,
        *,
        turn_id: str,
        kind: HistoryKind | str,
        payload: Mapping[str, Any] | JsonPayload | None = None,
        semantic_unit_id: str | None = None,
    ) -> "ApplicationHistory":
        return ApplicationHistory(
            session_id=self.session_id,
            canonical=self.history.append(
                turn_id=turn_id,
                kind=kind,
                payload=payload,
                semantic_unit_id=semantic_unit_id,
            ),
            projection=self.projection,
            runtime_log=self.runtime_log,
        )

    def append_message(
        self,
        *,
        turn_id: str,
        message: Message,
    ) -> "ApplicationHistory":
        """Append a Message's provider-independent semantic parts in order."""

        result = self
        for entry in history_entries_for_message(
            self.session_id,
            turn_id,
            self.history.last_sequence + 1,
            message,
        ):
            result = result.append(entry)
        return result

    def replace_projection(self, projection: Projection) -> "ApplicationHistory":
        """Set a new immutable view without changing canonical records."""

        if not isinstance(projection, Projection):
            raise TypeError("projection must be a Projection")
        if projection.session_id != self.session_id:
            raise ValueError("projection belongs to another session")
        return ApplicationHistory(
            session_id=self.session_id,
            canonical=self.history,
            projection=projection,
            runtime_log=self.runtime_log,
        )

    def append_runtime(self, entry: RuntimeLogEntry) -> "ApplicationHistory":
        return ApplicationHistory(
            session_id=self.session_id,
            canonical=self.history,
            projection=self.projection,
            runtime_log=self.runtime_log.append(entry),
        )

    def project(
        self,
        *,
        revision: int,
        sequence_start: int | None = None,
        sequence_end: int | None = None,
        previous_revision: int | None = None,
        summary: str | None = None,
    ) -> "ApplicationHistory":
        projection = self.history.project(
            revision=revision,
            sequence_start=sequence_start,
            sequence_end=sequence_end,
            previous_revision=previous_revision,
            summary=summary,
        )
        return self.replace_projection(projection)


def history_entries_for_message(
    session_id: str,
    turn_id: str,
    sequence: int,
    message: Message,
) -> tuple[HistoryEntry, ...]:
    """Convert one Message while retaining its identity-local reconstruction."""

    entries = history_entries_from_message(session_id, turn_id, sequence, message)
    converted: list[HistoryEntry] = []
    for entry in entries:
        payload = dict(entry.payload)
        payload["message"] = message.to_dict()
        converted.append(replace(entry, payload=payload))
    return tuple(converted)


__all__ = ["ApplicationHistory", "history_entries_for_message"]
