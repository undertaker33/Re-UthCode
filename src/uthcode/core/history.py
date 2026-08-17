"""Provider-independent append-only semantic history contracts.

Task 3 defines the in-memory value boundary only.  Files, locks, fsync, and
session metadata belong to later Integration/Application work and are not
implemented here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping, Sequence

from .prompt import ContextAuthority
from .provider import JsonPayload, Message, ToolCallPart, ToolResultPart


HISTORY_SCHEMA_VERSION = 1


class HistoryKind(str, Enum):
    """Kinds allowed in canonical semantic history."""

    USER_MESSAGE = "user_message"
    ASSISTANT_MESSAGE = "assistant_message"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    USER_STEERING = "user_steering"


class HistoryBoundaryError(ValueError):
    """A selection or projection would split a semantic unit."""


class HistorySequenceError(ValueError):
    """A history append would violate strict sequence ownership."""


class HistoryEnvelopeError(ValueError):
    """A persisted HistoryEntry does not match the current envelope."""


def _require_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _json_object(value: Mapping[str, Any] | JsonPayload) -> JsonPayload:
    if not isinstance(value, Mapping):
        raise TypeError("payload must be a JSON object")
    return JsonPayload(value)


def _plain(value: Any) -> Any:
    if isinstance(value, JsonPayload):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_plain(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class HistoryEntry:
    """One committed semantic record owned by one Session."""

    session_id: str
    sequence: int
    turn_id: str
    kind: HistoryKind | str
    payload: JsonPayload | Mapping[str, Any]
    created_at: str
    commit_boundary: bool
    semantic_unit_id: str | None
    schema_version: int

    def __post_init__(self) -> None:
        _require_text(self.session_id, "session_id")
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int) or self.sequence < 1:
            raise ValueError("sequence must be a positive integer")
        _require_text(self.turn_id, "turn_id")
        if isinstance(self.kind, HistoryKind):
            kind = self.kind
        elif isinstance(self.kind, str):
            try:
                kind = HistoryKind(self.kind)
            except ValueError as exc:
                raise ValueError(f"unknown history kind: {self.kind!r}") from exc
        else:
            raise TypeError("kind must be a canonical HistoryKind value")
        if (
            isinstance(self.schema_version, bool)
            or not isinstance(self.schema_version, int)
            or self.schema_version != HISTORY_SCHEMA_VERSION
        ):
            raise ValueError(
                f"unsupported history schema_version: {self.schema_version!r}"
            )
        if not isinstance(self.commit_boundary, bool):
            raise TypeError("commit_boundary must be a boolean")
        if not isinstance(self.payload, Mapping):
            raise TypeError("payload must be a JSON object")
        payload = _json_object(self.payload)
        if kind in {HistoryKind.TOOL_CALL, HistoryKind.TOOL_RESULT}:
            tool_call_id = payload.get("tool_call_id")
            if not isinstance(tool_call_id, str) or not tool_call_id.strip():
                raise ValueError(
                    f"{kind.value} requires a non-empty tool_call_id"
                )
        if self.semantic_unit_id is not None and not isinstance(
            self.semantic_unit_id, str
        ):
            raise TypeError("semantic_unit_id must be a string or None")
        if self.semantic_unit_id is not None and not self.semantic_unit_id.strip():
            raise ValueError("semantic_unit_id must be a non-empty string or None")
        if not isinstance(self.created_at, str) or not self.created_at.strip():
            raise ValueError("created_at must be a non-empty string")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "payload", payload)

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "HistoryEntry":
        if not isinstance(value, Mapping):
            raise TypeError("HistoryEntry payload must be a mapping")
        if any(not isinstance(key, str) for key in value):
            raise HistoryEnvelopeError("HistoryEntry keys must be strings")
        required = {
            "schema_version",
            "session_id",
            "sequence",
            "turn_id",
            "kind",
            "payload",
            "created_at",
            "commit_boundary",
            "semantic_unit_id",
        }
        missing = required.difference(value)
        if missing:
            raise HistoryEnvelopeError(
                f"HistoryEntry missing required fields: {sorted(missing)}"
            )
        unknown = set(value).difference(required)
        if unknown:
            raise HistoryEnvelopeError(
                f"HistoryEntry has unknown fields: {sorted(unknown)}"
            )
        if not isinstance(value["kind"], str):
            raise TypeError("persisted history kind must be a string")
        return cls(
            schema_version=value["schema_version"],  # type: ignore[arg-type]
            session_id=value["session_id"],  # type: ignore[arg-type]
            sequence=value["sequence"],  # type: ignore[arg-type]
            turn_id=value["turn_id"],  # type: ignore[arg-type]
            kind=value["kind"],  # type: ignore[arg-type]
            payload=value["payload"],  # type: ignore[arg-type]
            created_at=value["created_at"],  # type: ignore[arg-type]
            commit_boundary=value["commit_boundary"],  # type: ignore[arg-type]
            semantic_unit_id=value["semantic_unit_id"],  # type: ignore[arg-type]
        )

    @classmethod
    def from_json(cls, value: str) -> "HistoryEntry":
        parsed = json.loads(value)
        if not isinstance(parsed, Mapping):
            raise TypeError("HistoryEntry JSON must contain an object")
        return cls.from_dict(parsed)

    @property
    def is_tool_call(self) -> bool:
        return self.kind is HistoryKind.TOOL_CALL

    @property
    def is_tool_result(self) -> bool:
        return self.kind is HistoryKind.TOOL_RESULT

    @property
    def tool_call_id(self) -> str | None:
        value = self.payload.get("tool_call_id")
        return value if isinstance(value, str) else None

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "session_id": self.session_id,
            "sequence": self.sequence,
            "turn_id": self.turn_id,
            "kind": self.kind.value,
            "payload": _plain(self.payload),
            "created_at": self.created_at,
            "commit_boundary": self.commit_boundary,
            "semantic_unit_id": self.semantic_unit_id,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)



@dataclass(frozen=True, slots=True)
class SemanticUnit:
    """The smallest complete selection, compaction, and recovery atom."""

    unit_id: str
    session_id: str
    entries: tuple[HistoryEntry, ...]
    complete: bool = True

    def __post_init__(self) -> None:
        _require_text(self.unit_id, "unit_id")
        _require_text(self.session_id, "session_id")
        entries = tuple(self.entries)
        if not entries:
            raise ValueError("SemanticUnit requires at least one entry")
        if not all(isinstance(item, HistoryEntry) for item in entries):
            raise TypeError("entries must contain HistoryEntry values")
        if any(item.session_id != self.session_id for item in entries):
            raise ValueError("SemanticUnit entries must share session_id")
        if any(right.sequence != left.sequence + 1 for left, right in zip(entries, entries[1:])):
            raise HistorySequenceError("SemanticUnit entries must be contiguous")
        if not isinstance(self.complete, bool):
            raise TypeError("complete must be a boolean")
        object.__setattr__(self, "entries", entries)

    @property
    def sequence_start(self) -> int:
        return self.entries[0].sequence

    @property
    def sequence_end(self) -> int:
        return self.entries[-1].sequence

    @property
    def contains_tool_pair(self) -> bool:
        return any(item.is_tool_call for item in self.entries) and any(
            item.is_tool_result for item in self.entries
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "unit_id": self.unit_id,
            "session_id": self.session_id,
            "entries": [entry.to_dict() for entry in self.entries],
            "complete": self.complete,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "SemanticUnit":
        if not isinstance(value, Mapping):
            raise TypeError("SemanticUnit payload must be a mapping")
        raw_entries = value.get("entries", ())
        if not isinstance(raw_entries, Sequence) or isinstance(raw_entries, (str, bytes, bytearray)):
            raise TypeError("SemanticUnit entries must be a sequence")
        return cls(
            unit_id=value["unit_id"],  # type: ignore[arg-type]
            session_id=value["session_id"],  # type: ignore[arg-type]
            entries=tuple(HistoryEntry.from_dict(item) for item in raw_entries),  # type: ignore[arg-type]
            complete=value.get("complete", True),  # type: ignore[arg-type]
        )


@dataclass(frozen=True, slots=True)
class Projection:
    """An immutable history view; it never rewrites canonical records."""

    session_id: str
    revision: int
    sequence_start: int
    sequence_end: int
    units: tuple[SemanticUnit, ...]
    previous_revision: int | None = None
    summary: str | None = None
    authority: str = ContextAuthority.HISTORY_PROJECTION.value

    def __post_init__(self) -> None:
        _require_text(self.session_id, "session_id")
        if isinstance(self.revision, bool) or not isinstance(self.revision, int) or self.revision < 1:
            raise ValueError("revision must be a positive integer")
        if isinstance(self.sequence_start, bool) or not isinstance(self.sequence_start, int) or self.sequence_start < 1:
            raise ValueError("sequence_start must be a positive integer")
        if isinstance(self.sequence_end, bool) or not isinstance(self.sequence_end, int) or self.sequence_end < self.sequence_start:
            raise ValueError("sequence_end must be >= sequence_start")
        if self.previous_revision is not None and (
            isinstance(self.previous_revision, bool)
            or not isinstance(self.previous_revision, int)
            or self.previous_revision < 1
            or self.previous_revision >= self.revision
        ):
            raise ValueError("previous_revision must be a prior positive revision")
        if self.summary is not None and not isinstance(self.summary, str):
            raise TypeError("summary must be a string or None")
        if self.authority != ContextAuthority.HISTORY_PROJECTION.value:
            raise ValueError("Projection authority cannot be escalated")
        units = tuple(self.units)
        if not all(isinstance(item, SemanticUnit) for item in units):
            raise TypeError("units must contain SemanticUnit values")
        if any(item.session_id != self.session_id for item in units):
            raise ValueError("Projection units must share session_id")
        if any(not item.complete for item in units):
            raise HistoryBoundaryError("Projection cannot contain an incomplete SemanticUnit")
        if units:
            if units[0].sequence_start != self.sequence_start or units[-1].sequence_end != self.sequence_end:
                raise HistoryBoundaryError("Projection range must cover complete SemanticUnit boundaries")
            if any(right.sequence_start != left.sequence_end + 1 for left, right in zip(units, units[1:])):
                raise HistorySequenceError("Projection units must be contiguous")
        object.__setattr__(self, "units", units)

    @property
    def previous_link(self) -> int | None:
        return self.previous_revision

    @property
    def projection_revision(self) -> int:
        return self.revision

    def to_dict(self) -> dict[str, object]:
        return {
            "session_id": self.session_id,
            "revision": self.revision,
            "sequence_start": self.sequence_start,
            "sequence_end": self.sequence_end,
            "units": [unit.to_dict() for unit in self.units],
            "previous_revision": self.previous_revision,
            "summary": self.summary,
            "authority": self.authority,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "Projection":
        if not isinstance(value, Mapping):
            raise TypeError("Projection payload must be a mapping")
        raw_units = value.get("units", ())
        if not isinstance(raw_units, Sequence) or isinstance(raw_units, (str, bytes, bytearray)):
            raise TypeError("Projection units must be a sequence")
        return cls(
            session_id=value["session_id"],  # type: ignore[arg-type]
            revision=value["revision"],  # type: ignore[arg-type]
            sequence_start=value["sequence_start"],  # type: ignore[arg-type]
            sequence_end=value["sequence_end"],  # type: ignore[arg-type]
            units=tuple(SemanticUnit.from_dict(item) for item in raw_units),  # type: ignore[arg-type]
            previous_revision=value.get("previous_revision"),  # type: ignore[arg-type]
            summary=value.get("summary"),  # type: ignore[arg-type]
            authority=value.get("authority", ContextAuthority.HISTORY_PROJECTION.value),  # type: ignore[arg-type]
        )


@dataclass(frozen=True, slots=True)
class CanonicalHistory:
    """An immutable append-only sequence with strict session ownership."""

    session_id: str
    entries: tuple[HistoryEntry, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.session_id, "session_id")
        entries = tuple(self.entries)
        if not all(isinstance(item, HistoryEntry) for item in entries):
            raise TypeError("entries must contain HistoryEntry values")
        expected = 1
        for entry in entries:
            if entry.session_id != self.session_id:
                raise HistorySequenceError("history entry belongs to another session")
            if entry.sequence != expected:
                raise HistorySequenceError(
                    f"history sequence must be strict and contiguous; expected {expected}, got {entry.sequence}"
                )
            expected += 1
        object.__setattr__(self, "entries", entries)

    @property
    def last_sequence(self) -> int:
        return self.entries[-1].sequence if self.entries else 0

    @property
    def sequence(self) -> int:
        return self.last_sequence

    def append(
        self,
        entry: HistoryEntry | None = None,
        *,
        turn_id: str | None = None,
        kind: HistoryKind | str | None = None,
        payload: Mapping[str, Any] | JsonPayload | None = None,
        created_at: str | None = None,
        commit_boundary: bool = True,
        semantic_unit_id: str | None = None,
    ) -> "CanonicalHistory":
        if entry is None:
            if turn_id is None or kind is None:
                raise TypeError("append requires entry or turn_id and kind")
            entry = HistoryEntry(
                session_id=self.session_id,
                sequence=self.last_sequence + 1,
                turn_id=turn_id,
                kind=kind,
                payload={} if payload is None else payload,
                created_at=(
                    datetime.now(timezone.utc).isoformat()
                    if created_at is None
                    else created_at
                ),
                commit_boundary=commit_boundary,
                semantic_unit_id=semantic_unit_id,
                schema_version=HISTORY_SCHEMA_VERSION,
            )
        if not isinstance(entry, HistoryEntry):
            raise TypeError("entry must be a HistoryEntry")
        if entry.session_id != self.session_id:
            raise HistorySequenceError("history entry belongs to another session")
        if entry.sequence != self.last_sequence + 1:
            raise HistorySequenceError(
                f"history append expected sequence {self.last_sequence + 1}, got {entry.sequence}"
            )
        return CanonicalHistory(self.session_id, self.entries + (entry,))

    def to_jsonl(self) -> str:
        return "".join(f"{entry.to_json()}\n" for entry in self.entries)

    @classmethod
    def from_jsonl(cls, session_id: str, value: str) -> "CanonicalHistory":
        if not isinstance(value, str):
            raise TypeError("history JSONL must be a string")
        history = cls(session_id)
        for line in value.splitlines():
            if not line.strip():
                continue
            history = history.append(HistoryEntry.from_json(line))
        return history

    def semantic_units(self, *, include_incomplete: bool = True) -> tuple[SemanticUnit, ...]:
        units: list[SemanticUnit] = []
        index = 0
        while index < len(self.entries):
            entry = self.entries[index]
            explicit_id = entry.semantic_unit_id
            if explicit_id is not None:
                group = [entry]
                index += 1
                while index < len(self.entries) and self.entries[index].semantic_unit_id == explicit_id:
                    group.append(self.entries[index])
                    index += 1
                complete = _tool_group_complete(group)
                unit = SemanticUnit(explicit_id, self.session_id, tuple(group), complete)
            elif entry.kind is HistoryKind.TOOL_CALL:
                group: list[HistoryEntry] = []
                while index < len(self.entries) and self.entries[index].kind is HistoryKind.TOOL_CALL:
                    group.append(self.entries[index])
                    index += 1
                while index < len(self.entries) and self.entries[index].kind is HistoryKind.TOOL_RESULT:
                    group.append(self.entries[index])
                    index += 1
                unit = SemanticUnit(
                    f"unit-{entry.sequence}",
                    self.session_id,
                    tuple(group),
                    _tool_group_complete(group),
                )
            elif entry.kind is HistoryKind.TOOL_RESULT:
                index += 1
                unit = SemanticUnit(f"unit-{entry.sequence}", self.session_id, (entry,), False)
            else:
                index += 1
                unit = SemanticUnit(f"unit-{entry.sequence}", self.session_id, (entry,), entry.commit_boundary)
            if include_incomplete or unit.complete:
                units.append(unit)
        return tuple(units)

    def complete_semantic_units(self) -> tuple[SemanticUnit, ...]:
        return self.semantic_units(include_incomplete=False)

    def select_units(
        self,
        *,
        sequence_start: int | None = None,
        sequence_end: int | None = None,
        include_incomplete: bool = False,
    ) -> tuple[SemanticUnit, ...]:
        units = self.semantic_units(include_incomplete=include_incomplete)
        if not units:
            return ()
        start = units[0].sequence_start if sequence_start is None else sequence_start
        end = units[-1].sequence_end if sequence_end is None else sequence_end
        selected = tuple(unit for unit in units if unit.sequence_start >= start and unit.sequence_end <= end)
        if not selected or selected[0].sequence_start != start or selected[-1].sequence_end != end:
            raise HistoryBoundaryError("selection must begin and end on complete SemanticUnit boundaries")
        if any(right.sequence_start != left.sequence_end + 1 for left, right in zip(selected, selected[1:])):
            raise HistoryBoundaryError("selection cannot skip a SemanticUnit")
        return selected

    def select(self, *, sequence_start: int, sequence_end: int) -> tuple[HistoryEntry, ...]:
        return tuple(entry for unit in self.select_units(sequence_start=sequence_start, sequence_end=sequence_end) for entry in unit.entries)

    def project(
        self,
        *,
        revision: int,
        sequence_start: int | None = None,
        sequence_end: int | None = None,
        previous_revision: int | None = None,
        summary: str | None = None,
    ) -> Projection:
        units = self.select_units(sequence_start=sequence_start, sequence_end=sequence_end)
        if not units:
            raise HistoryBoundaryError("Projection requires at least one complete SemanticUnit")
        return Projection(
            session_id=self.session_id,
            revision=revision,
            sequence_start=units[0].sequence_start,
            sequence_end=units[-1].sequence_end,
            units=units,
            previous_revision=previous_revision,
            summary=summary,
        )

    def compact(self, *, sequence_start: int, sequence_end: int) -> Projection:
        """Create a projection candidate without changing existing records."""

        return self.project(revision=1, sequence_start=sequence_start, sequence_end=sequence_end)


@dataclass(frozen=True, slots=True)
class RuntimeLogEntry:
    """Non-authoritative lifecycle/diagnostic fact kept outside History."""

    kind: str
    payload: JsonPayload | Mapping[str, Any] = field(default_factory=JsonPayload)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def __post_init__(self) -> None:
        _require_text(self.kind, "kind")
        object.__setattr__(self, "payload", _json_object(self.payload))
        _require_text(self.created_at, "created_at")

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "payload": _plain(self.payload),
            "created_at": self.created_at,
        }


@dataclass(frozen=True, slots=True)
class RuntimeLog:
    entries: tuple[RuntimeLogEntry, ...] = ()

    def append(self, entry: RuntimeLogEntry) -> "RuntimeLog":
        if not isinstance(entry, RuntimeLogEntry):
            raise TypeError("entry must be a RuntimeLogEntry")
        return RuntimeLog(self.entries + (entry,))


def _tool_group_complete(entries: Sequence[HistoryEntry]) -> bool:
    if not entries:
        return False
    if not all(entry.commit_boundary for entry in entries):
        return False
    calls = [entry.tool_call_id for entry in entries if entry.is_tool_call]
    results = [entry.tool_call_id for entry in entries if entry.is_tool_result]
    if not calls and not results:
        return True
    if any(call_id is None for call_id in (*calls, *results)):
        return False
    if len(calls) != len(set(calls)) or len(results) != len(set(results)):
        return False
    return len(calls) == len(results) and set(calls) == set(results)


def history_entries_from_message(
    session_id: str,
    turn_id: str,
    sequence: int,
    message: Message,
) -> tuple[HistoryEntry, ...]:
    """Convert one Core Message into atomic semantic records for adapters."""

    if not isinstance(message, Message):
        raise TypeError("message must be a Message")
    entries: list[HistoryEntry] = []
    for part in message.parts:
        if isinstance(part, ToolCallPart):
            kind = HistoryKind.TOOL_CALL
            payload = part.to_dict()
        elif isinstance(part, ToolResultPart):
            kind = HistoryKind.TOOL_RESULT
            payload = part.to_dict()
        else:
            kind = (
                HistoryKind.USER_MESSAGE
                if message.role == "user"
                else HistoryKind.ASSISTANT_MESSAGE
            )
            payload = {"role": message.role, "part": part.to_dict()}
        entries.append(
            HistoryEntry(
                session_id=session_id,
                sequence=sequence + len(entries),
                turn_id=turn_id,
                kind=kind,
                payload=payload,
                created_at=datetime.now(timezone.utc).isoformat(),
                commit_boundary=True,
                semantic_unit_id=None,
                schema_version=HISTORY_SCHEMA_VERSION,
            )
        )
    if not entries:
        entries.append(
            HistoryEntry(
                session_id=session_id,
                sequence=sequence,
                turn_id=turn_id,
                kind=(HistoryKind.USER_MESSAGE if message.role == "user" else HistoryKind.ASSISTANT_MESSAGE),
                payload={"role": message.role, "parts": []},
                created_at=datetime.now(timezone.utc).isoformat(),
                commit_boundary=True,
                semantic_unit_id=None,
                schema_version=HISTORY_SCHEMA_VERSION,
            )
        )
    return tuple(entries)


__all__ = [
    "CanonicalHistory",
    "HistoryBoundaryError",
    "HistoryEnvelopeError",
    "HistoryEntry",
    "HistoryKind",
    "HistorySequenceError",
    "HISTORY_SCHEMA_VERSION",
    "Projection",
    "RuntimeLog",
    "RuntimeLogEntry",
    "SemanticUnit",
    "history_entries_from_message",
]
