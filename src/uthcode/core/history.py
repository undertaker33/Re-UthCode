"""Provider-independent Transcript and Timeline value contracts.

Transcript is the durable raw-fact authority.  Timeline is an append-only
derived view whose last checkpoint is its only commit marker.  Persistence,
locking, and recovery are implemented by the session integration layer.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Mapping as MappingABC, Sequence as SequenceABC
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping, Sequence

from .provider import JsonPayload, Message, ToolCallPart, ToolResultPart


TRANSCRIPT_SCHEMA_VERSION = 2
TIMELINE_SCHEMA_VERSION = 2


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_plain(value: Any) -> Any:
    if isinstance(value, MappingABC):
        return {str(key): _json_plain(item) for key, item in value.items()}
    if isinstance(value, SequenceABC) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_plain(item) for item in value]
    return value


class TranscriptKind(str, Enum):
    USER_MESSAGE = "user_message"
    ASSISTANT_MESSAGE = "assistant_message"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    USER_STEERING = "user_steering"


class TranscriptBoundaryError(ValueError):
    """A read or reference would split a semantic unit."""


class TranscriptSequenceError(ValueError):
    """Transcript sequences are strictly increasing by one."""


class TimelineError(ValueError):
    """A Timeline record or transaction is invalid."""


class TimelineSequenceError(TimelineError):
    """Timeline records cannot be appended out of order."""


@dataclass(frozen=True)
class TranscriptEntry:
    session_id: str
    sequence: int
    turn_id: str
    kind: TranscriptKind
    payload: JsonPayload
    created_at: str = field(default_factory=_now)
    commit_boundary: bool = True
    semantic_unit_id: str | None = None
    schema_version: int = TRANSCRIPT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.session_id or self.sequence < 1 or not self.turn_id:
            raise ValueError("TranscriptEntry identity is invalid")
        if self.schema_version != TRANSCRIPT_SCHEMA_VERSION:
            raise ValueError("unsupported TranscriptEntry schema version")
        object.__setattr__(self, "kind", TranscriptKind(self.kind))
        if not isinstance(self.payload, Mapping):
            raise TypeError("TranscriptEntry payload must be a mapping")
        object.__setattr__(self, "payload", JsonPayload(self.payload))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "session_id": self.session_id,
            "sequence": self.sequence,
            "turn_id": self.turn_id,
            "kind": self.kind.value,
            "payload": _json_plain(self.payload),
            "created_at": self.created_at,
            "semantic_unit_id": self.semantic_unit_id,
            "commit_boundary": self.commit_boundary,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TranscriptEntry":
        return cls(
            session_id=str(data["session_id"]),
            sequence=int(data["sequence"]),
            turn_id=str(data["turn_id"]),
            kind=TranscriptKind(data["kind"]),
            payload=dict(data.get("payload", {})),
            created_at=str(data.get("created_at") or _now()),
            commit_boundary=bool(data.get("commit_boundary", True)),
            semantic_unit_id=data.get("semantic_unit_id"),
            schema_version=int(data.get("schema_version", TRANSCRIPT_SCHEMA_VERSION)),
        )

    @property
    def is_tool_call(self) -> bool:
        return self.kind is TranscriptKind.TOOL_CALL

    @property
    def is_tool_result(self) -> bool:
        return self.kind is TranscriptKind.TOOL_RESULT


@dataclass(frozen=True)
class SemanticUnit:
    unit_id: str
    turn_id: str
    entries: tuple[TranscriptEntry, ...]

    @property
    def sequence_start(self) -> int:
        return self.entries[0].sequence

    @property
    def sequence_end(self) -> int:
        return self.entries[-1].sequence

    @property
    def complete(self) -> bool:
        calls = tuple(
            entry.payload.get("tool_call_id")
            for entry in self.entries
            if entry.kind is TranscriptKind.TOOL_CALL
        )
        results = tuple(
            entry.payload.get("tool_call_id")
            for entry in self.entries
            if entry.kind is TranscriptKind.TOOL_RESULT
        )
        if any(
            not isinstance(entry.payload.get("tool_call_id"), str) or not entry.payload.get("tool_call_id")
            for entry in self.entries
            if entry.kind in (TranscriptKind.TOOL_CALL, TranscriptKind.TOOL_RESULT)
        ):
            return False
        if any(
            entry.kind not in (TranscriptKind.TOOL_CALL, TranscriptKind.TOOL_RESULT) and not entry.commit_boundary
            for entry in self.entries
        ):
            return False
        if calls or results:
            return (
                bool(calls)
                and len(calls) == len(set(calls))
                and len(results) == len(set(results))
                and set(calls) == set(results)
            )
        return all(entry.commit_boundary for entry in self.entries)

    def to_dict(self) -> dict[str, Any]:
        return {
            "unit_id": self.unit_id,
            "turn_id": self.turn_id,
            "entries": [entry.to_dict() for entry in self.entries],
            "complete": self.complete,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SemanticUnit":
        entries = tuple(TranscriptEntry.from_dict(item) for item in data.get("entries", ()))
        if not entries:
            raise ValueError("SemanticUnit must contain entries")
        return cls(str(data["unit_id"]), str(data["turn_id"]), entries)


@dataclass(frozen=True)
class TranscriptRef:
    session_id: str
    sequence_start: int
    sequence_end: int
    schema_version: int = TRANSCRIPT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.session_id or self.sequence_start < 1 or self.sequence_end < self.sequence_start:
            raise ValueError("TranscriptRef range is invalid")
        if self.schema_version != TRANSCRIPT_SCHEMA_VERSION:
            raise ValueError("unsupported TranscriptRef schema version")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "session_id": self.session_id,
            "sequence_start": self.sequence_start,
            "sequence_end": self.sequence_end,
        }

    def to_token(self) -> str:
        raw = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TranscriptRef":
        return cls(
            session_id=str(data["session_id"]),
            sequence_start=int(data["sequence_start"]),
            sequence_end=int(data["sequence_end"]),
            schema_version=int(data.get("schema_version", TRANSCRIPT_SCHEMA_VERSION)),
        )

    @classmethod
    def from_token(cls, token: str) -> "TranscriptRef":
        if not isinstance(token, str) or not token:
            raise ValueError("TranscriptRef token is invalid")
        try:
            padded = token + "=" * (-len(token) % 4)
            data = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
            if not isinstance(data, Mapping):
                raise ValueError
            return cls.from_dict(data)
        except (ValueError, TypeError, KeyError, json.JSONDecodeError, UnicodeError) as exc:
            raise ValueError("TranscriptRef token is invalid") from exc


@dataclass(frozen=True)
class Transcript:
    session_id: str
    entries: tuple[TranscriptEntry, ...] = ()
    schema_version: int = TRANSCRIPT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.session_id or self.schema_version != TRANSCRIPT_SCHEMA_VERSION:
            raise ValueError("Transcript schema or identity is invalid")
        object.__setattr__(self, "entries", tuple(self.entries))
        previous = 0
        for entry in self.entries:
            if entry.session_id != self.session_id or entry.sequence != previous + 1:
                raise TranscriptSequenceError("Transcript sequence or session ownership is invalid")
            previous = entry.sequence

    @property
    def last_sequence(self) -> int:
        return self.entries[-1].sequence if self.entries else 0

    def append(self, entry: TranscriptEntry) -> "Transcript":
        if entry.session_id != self.session_id or entry.sequence != self.last_sequence + 1:
            raise TranscriptSequenceError("Transcript append must use the next sequence")
        return Transcript(self.session_id, self.entries + (entry,), self.schema_version)

    def semantic_units(self, *, complete_only: bool = False) -> tuple[SemanticUnit, ...]:
        grouped: list[SemanticUnit] = []
        current: list[TranscriptEntry] = []
        current_id: str | None = None
        for entry in self.entries:
            unit_id = entry.semantic_unit_id or entry.turn_id
            if current and unit_id != current_id:
                unit = SemanticUnit(current_id or current[0].turn_id, current[0].turn_id, tuple(current))
                if not complete_only or unit.complete:
                    grouped.append(unit)
                current = []
            current_id = unit_id
            current.append(entry)
        if current:
            unit = SemanticUnit(current_id or current[0].turn_id, current[0].turn_id, tuple(current))
            if not complete_only or unit.complete:
                grouped.append(unit)
        return tuple(grouped)

    def select(self, sequence_start: int, sequence_end: int, *, complete_only: bool = True) -> tuple[TranscriptEntry, ...]:
        if sequence_start < 1 or sequence_end < sequence_start or sequence_end > self.last_sequence:
            raise TranscriptBoundaryError("Transcript range is invalid")
        selected = tuple(entry for entry in self.entries if sequence_start <= entry.sequence <= sequence_end)
        if not selected or selected[0].sequence != sequence_start or selected[-1].sequence != sequence_end:
            raise TranscriptBoundaryError("Transcript range is invalid")
        for unit in self.semantic_units():
            overlaps = any(sequence_start <= entry.sequence <= sequence_end for entry in unit.entries)
            contained = sequence_start <= unit.sequence_start and unit.sequence_end <= sequence_end
            if overlaps and not contained:
                raise TranscriptBoundaryError("Transcript range splits a semantic unit")
            if contained and complete_only and not unit.complete:
                raise TranscriptBoundaryError("Transcript range contains an incomplete semantic unit")
        return selected

    def reference(self, sequence_start: int, sequence_end: int) -> TranscriptRef:
        self.select(sequence_start, sequence_end, complete_only=True)
        return TranscriptRef(self.session_id, sequence_start, sequence_end)

    def complete(self) -> "Transcript":
        entries = tuple(entry for unit in self.semantic_units(complete_only=True) for entry in unit.entries)
        return Transcript(self.session_id, entries)

    def to_jsonl(self) -> str:
        return "".join(json.dumps(entry.to_dict(), sort_keys=True, ensure_ascii=False) + "\n" for entry in self.entries)

    @classmethod
    def from_jsonl(cls, session_id: str, text: str) -> "Transcript":
        transcript = cls(session_id)
        for line in text.splitlines():
            if line.strip():
                transcript = transcript.append(TranscriptEntry.from_dict(json.loads(line)))
        return transcript


def _refs(value: Sequence[TranscriptRef | Mapping[str, Any]]) -> tuple[TranscriptRef, ...]:
    return tuple(item if isinstance(item, TranscriptRef) else TranscriptRef.from_dict(item) for item in value)


@dataclass(frozen=True)
class SemanticEntry:
    turn_id: str
    summary: str
    refs: tuple[TranscriptRef, ...]
    session_id: str | None = None
    schema_version: int = TIMELINE_SCHEMA_VERSION
    transaction_id: str | None = field(default=None, compare=False)
    record_type: str = field(init=False, default="semantic_entry")

    def __post_init__(self) -> None:
        if not self.turn_id or not self.summary or self.schema_version != TIMELINE_SCHEMA_VERSION:
            raise TimelineError("SemanticEntry is invalid")
        if self.transaction_id is not None and not self.transaction_id.strip():
            raise TimelineError("SemanticEntry transaction_id is invalid")
        object.__setattr__(self, "refs", _refs(self.refs))

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": self.schema_version, "record_type": self.record_type, "turn_id": self.turn_id, "summary": self.summary, "refs": [ref.to_dict() for ref in self.refs], **({"session_id": self.session_id} if self.session_id else {}), **({"transaction_id": self.transaction_id} if self.transaction_id else {})}


@dataclass(frozen=True)
class EpochMacroSummary:
    turn_id: str
    summary: str
    refs: tuple[TranscriptRef, ...]
    coverage: tuple[str, ...]
    session_id: str | None = None
    schema_version: int = TIMELINE_SCHEMA_VERSION
    transaction_id: str | None = field(default=None, compare=False)
    record_type: str = field(init=False, default="epoch_macro_summary")

    def __post_init__(self) -> None:
        if not self.turn_id or not self.summary or self.schema_version != TIMELINE_SCHEMA_VERSION:
            raise TimelineError("EpochMacroSummary is invalid")
        if self.transaction_id is not None and not self.transaction_id.strip():
            raise TimelineError("EpochMacroSummary transaction_id is invalid")
        object.__setattr__(self, "refs", _refs(self.refs))
        coverage = tuple(self.coverage)
        if not coverage or any(not isinstance(turn_id, str) or not turn_id for turn_id in coverage):
            raise TimelineError("EpochMacroSummary coverage is invalid")
        if len(set(coverage)) != len(coverage):
            raise TimelineError("EpochMacroSummary coverage contains duplicate Turns")
        object.__setattr__(self, "coverage", coverage)

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": self.schema_version, "record_type": self.record_type, "turn_id": self.turn_id, "summary": self.summary, "refs": [ref.to_dict() for ref in self.refs], "coverage": list(self.coverage), **({"session_id": self.session_id} if self.session_id else {}), **({"transaction_id": self.transaction_id} if self.transaction_id else {})}


@dataclass(frozen=True)
class ActiveCheckpoint:
    turn_id: str
    active_turns: tuple[str, ...]
    session_id: str | None = None
    schema_version: int = TIMELINE_SCHEMA_VERSION
    transaction_id: str | None = field(default=None, compare=False)
    record_type: str = field(init=False, default="active_checkpoint")

    def __post_init__(self) -> None:
        if not self.turn_id or self.schema_version != TIMELINE_SCHEMA_VERSION:
            raise TimelineError("ActiveCheckpoint is invalid")
        if self.transaction_id is not None and not self.transaction_id.strip():
            raise TimelineError("ActiveCheckpoint transaction_id is invalid")
        object.__setattr__(self, "active_turns", tuple(self.active_turns))

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": self.schema_version, "record_type": self.record_type, "turn_id": self.turn_id, "active_turns": list(self.active_turns), **({"session_id": self.session_id} if self.session_id else {}), **({"transaction_id": self.transaction_id} if self.transaction_id else {})}


TimelineRecord = SemanticEntry | EpochMacroSummary | ActiveCheckpoint


def timeline_record_from_dict(data: Mapping[str, Any]) -> TimelineRecord:
    version = int(data.get("schema_version", TIMELINE_SCHEMA_VERSION))
    if version != TIMELINE_SCHEMA_VERSION:
        raise TimelineError("unsupported Timeline schema version")
    record_type = data.get("record_type")
    common = {"turn_id": str(data["turn_id"]), "session_id": data.get("session_id"), "transaction_id": data.get("transaction_id"), "schema_version": version}
    if record_type == "semantic_entry":
        return SemanticEntry(summary=str(data["summary"]), refs=_refs(data.get("refs", ())), **common)
    if record_type == "epoch_macro_summary":
        return EpochMacroSummary(summary=str(data["summary"]), refs=_refs(data.get("refs", ())), coverage=tuple(data.get("coverage", ())), **common)
    if record_type == "active_checkpoint":
        return ActiveCheckpoint(active_turns=tuple(data.get("active_turns", ())), **common)
    raise TimelineError("unknown Timeline record type")


@dataclass(frozen=True)
class Timeline:
    session_id: str
    records: tuple[TimelineRecord, ...] = ()
    schema_version: int = TIMELINE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.session_id or self.schema_version != TIMELINE_SCHEMA_VERSION:
            raise TimelineError("Timeline schema or identity is invalid")
        object.__setattr__(self, "records", tuple(self.records))
        for record in self.records:
            if record.session_id not in (None, self.session_id):
                raise TimelineError("Timeline record belongs to another Session")
        for group in self.transaction_groups():
            if group and isinstance(group[-1], ActiveCheckpoint) and len(group) == 1:
                raise TimelineError("Timeline checkpoint must commit a non-empty transaction")

    def transaction_groups(self) -> tuple[tuple[TimelineRecord, ...], ...]:
        """Return physical transactions, preserving uncommitted groups.

        New transactions carry an identity on each of their existing product
        records.  Records from the original v2 shape have no identity; those
        are grouped by contiguous physical runs ending at a checkpoint.  A
        newly identified transaction therefore cannot absorb an older
        identity-less trailing run after a crash.
        """

        groups: list[tuple[TimelineRecord, ...]] = []
        current: list[TimelineRecord] = []
        current_id: str | None = None

        def flush() -> None:
            nonlocal current, current_id
            if current:
                groups.append(tuple(current))
            current = []
            current_id = None

        for record in self.records:
            record_id = getattr(record, "transaction_id", None)
            same_transaction = bool(current) and (
                record_id is not None and record_id == current_id
                or record_id is None and current_id is None
            )
            if not same_transaction:
                flush()
            current.append(record)
            current_id = record_id
            if isinstance(record, ActiveCheckpoint):
                flush()
        flush()
        return tuple(groups)

    @property
    def latest_checkpoint_index(self) -> int | None:
        offset = 0
        latest: int | None = None
        for group in self.transaction_groups():
            if group and isinstance(group[-1], ActiveCheckpoint):
                latest = offset + len(group) - 1
            offset += len(group)
        return latest

    @property
    def active_checkpoint(self) -> ActiveCheckpoint | None:
        for group in reversed(self.transaction_groups()):
            if group and isinstance(group[-1], ActiveCheckpoint):
                return group[-1]
        return None

    @property
    def committed_records(self) -> tuple[TimelineRecord, ...]:
        return tuple(record for group in self.transaction_groups() if group and isinstance(group[-1], ActiveCheckpoint) for record in group)

    @property
    def trailing_records(self) -> tuple[TimelineRecord, ...]:
        return tuple(record for group in self.transaction_groups() if not group or not isinstance(group[-1], ActiveCheckpoint) for record in group)

    @property
    def physical_fine_entries(self) -> tuple[SemanticEntry, ...]:
        """Return every committed Fine record, including superseded history."""

        return tuple(record for record in self.committed_records if isinstance(record, SemanticEntry))

    @property
    def logical_records(self) -> tuple[TimelineRecord, ...]:
        """Return the append-only Timeline's current logical projection.

        Fine records remain physically present for audit/recovery.  A committed
        Macro supersedes only the Fine records whose Turn IDs it explicitly
        covers; unrelated and newer Fine records stay visible.
        """

        committed = self.committed_records
        superseded_turns = {
            turn_id
            for record in committed
            if isinstance(record, EpochMacroSummary)
            for turn_id in record.coverage
        }
        return tuple(
            record
            for record in committed
            if not isinstance(record, SemanticEntry) or record.turn_id not in superseded_turns
        )

    @property
    def fine_entries(self) -> tuple[SemanticEntry, ...]:
        """Return logical Fine records after committed Macro supersession."""

        return tuple(record for record in self.logical_records if isinstance(record, SemanticEntry))

    @property
    def macro_summaries(self) -> tuple[EpochMacroSummary, ...]:
        return tuple(record for record in self.committed_records if isinstance(record, EpochMacroSummary))

    @property
    def summary(self) -> str:
        derived = tuple(record for record in self.logical_records if isinstance(record, (SemanticEntry, EpochMacroSummary)))
        return derived[-1].summary if derived else ""

    @property
    def sequence_end(self) -> int:
        return max((ref.sequence_end for record in self.committed_records if isinstance(record, (SemanticEntry, EpochMacroSummary)) for ref in record.refs), default=0)

    def append(self, record: TimelineRecord) -> "Timeline":
        if record.session_id not in (None, self.session_id):
            raise TimelineError("Timeline record belongs to another Session")
        if isinstance(record, ActiveCheckpoint):
            checkpoint_index = self.latest_checkpoint_index
            pending = self.records[checkpoint_index + 1 :] if checkpoint_index is not None else self.records
            if not pending:
                raise TimelineError("Timeline checkpoint must commit a non-empty transaction")
        return Timeline(self.session_id, self.records + (record,), self.schema_version)

    def append_transaction(self, derived: Sequence[SemanticEntry | EpochMacroSummary], checkpoint: ActiveCheckpoint) -> "Timeline":
        if not derived:
            raise TimelineError("Timeline transaction must contain a derived record")
        records = (*derived, checkpoint)
        transaction_ids = {record.transaction_id for record in records if record.transaction_id is not None}
        if len(transaction_ids) > 1:
            raise TimelineError("Timeline transaction has multiple transaction identities")
        transaction_id = next(iter(transaction_ids), f"timeline-tx-{len(self.records) + 1}")
        normalized = tuple(
            replace(record, transaction_id=transaction_id)
            for record in records
        )
        result = self
        for record in normalized[:-1]:
            if isinstance(record, ActiveCheckpoint):
                raise TimelineError("checkpoint is not a derived record")
            result = result.append(record)
        return result.append(normalized[-1])

    def to_jsonl(self) -> str:
        return "".join(json.dumps(record.to_dict(), sort_keys=True, ensure_ascii=False) + "\n" for record in self.records)

    @classmethod
    def from_jsonl(cls, session_id: str, text: str) -> "Timeline":
        result = cls(session_id)
        for line in text.splitlines():
            if line.strip():
                result = result.append(timeline_record_from_dict(json.loads(line)))
        return result


@dataclass(frozen=True)
class RuntimeLogEntry:
    session_id: str
    sequence: int
    event: str
    payload: JsonPayload
    created_at: str = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return {"session_id": self.session_id, "sequence": self.sequence, "event": self.event, "payload": _json_plain(self.payload), "created_at": self.created_at}


@dataclass(frozen=True)
class RuntimeLog:
    session_id: str
    entries: tuple[RuntimeLogEntry, ...] = ()

    @property
    def last_sequence(self) -> int:
        return self.entries[-1].sequence if self.entries else 0

    def append(self, entry: RuntimeLogEntry) -> "RuntimeLog":
        if entry.session_id != self.session_id or entry.sequence != self.last_sequence + 1:
            raise ValueError("RuntimeLog sequence is invalid")
        return RuntimeLog(self.session_id, self.entries + (entry,))


def transcript_entries_from_message(session_id: str, turn_id: str, sequence_start: int, message: Message) -> tuple[TranscriptEntry, ...]:
    entries: list[TranscriptEntry] = []
    sequence = sequence_start
    unit_id = turn_id
    for part in message.parts:
        if isinstance(part, ToolCallPart):
            kind = TranscriptKind.TOOL_CALL
        elif isinstance(part, ToolResultPart):
            kind = TranscriptKind.TOOL_RESULT
        else:
            kind = TranscriptKind.USER_MESSAGE if message.role == "user" else TranscriptKind.ASSISTANT_MESSAGE
        payload = part.to_dict() if hasattr(part, "to_dict") else {"text": str(part)}
        entries.append(TranscriptEntry(session_id, sequence, turn_id, kind, payload, semantic_unit_id=unit_id))
        sequence += 1
    if not entries:
        entries.append(TranscriptEntry(session_id, sequence, turn_id, TranscriptKind.USER_MESSAGE if message.role == "user" else TranscriptKind.ASSISTANT_MESSAGE, {"text": ""}, semantic_unit_id=unit_id))
    return tuple(entries)
