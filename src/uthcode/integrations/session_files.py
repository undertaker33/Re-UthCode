"""Durable Session v3 files with single-writer and crash-safe append rules."""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from uthcode.core.history import (
    ActiveCheckpoint,
    EpochMacroSummary,
    SemanticEntry,
    SemanticUnit,
    Timeline,
    TimelineRecord,
    Transcript,
    TranscriptEntry,
    TranscriptKind,
    timeline_record_from_dict,
)


SESSION_SCHEMA_VERSION = 3
SESSION_RECORD_SCHEMA_VERSION = 2


class SessionFileError(RuntimeError):
    """Base error for durable Session file operations."""


class SessionBusyError(SessionFileError):
    """Another process currently owns the Session writer lock."""


class SessionNotFoundError(SessionFileError):
    """The requested Session does not exist."""


class SessionIncompatibleError(SessionFileError):
    """The Session belongs to an unsupported layout and is not migrated."""


class SessionCorruptError(SessionFileError):
    """A metadata or semantic record cannot be recovered safely."""


class SessionWriterRequiredError(SessionFileError):
    """A durable mutation was attempted without the held writer lock."""


class SessionDurabilityUnknownError(SessionFileError):
    """The held Session writer is quarantined after an unknown append outcome."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _validate_session_id(value: str) -> str:
    value = _require_text(value, "session_id")
    if value in {".", ".."} or "/" in value or "\\" in value or "\x00" in value:
        raise ValueError("session_id must be a single safe path component")
    return value


def _json_safe(value: object) -> object:
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_safe(item) for item in value]
    raise TypeError("instruction_state contains a non-JSON value")


def _safe_instruction_state(value: Mapping[str, object] | None) -> dict[str, object]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise TypeError("instruction_state must be a mapping")
    allowed = {
        "activated_directory_scopes",
        "instruction_epoch",
        "stable_prefix_fingerprint",
        "source_fingerprints",
        "change_reason",
    }
    unknown = set(value).difference(allowed)
    if unknown:
        raise ValueError("instruction_state contains unsupported fields: " + ", ".join(sorted(map(str, unknown))))
    result = {key: _json_safe(value[key]) for key in allowed if key in value}
    encoded = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if any(marker in encoded.casefold() for marker in ("agents正文", "effective_instruction_set", "prompt_text")):
        raise ValueError("instruction_state must not contain instruction text")
    return result


@dataclass(frozen=True, slots=True)
class SessionMetadata:
    session_id: str
    project_key: str
    created_at: str
    last_used_at: str
    instruction_state: Mapping[str, object] = field(default_factory=dict)
    schema_version: int = SESSION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _validate_session_id(self.session_id)
        _require_text(self.project_key, "project_key")
        _require_text(self.created_at, "created_at")
        _require_text(self.last_used_at, "last_used_at")
        if self.schema_version != SESSION_SCHEMA_VERSION:
            raise ValueError(f"unsupported Session metadata schema_version: {self.schema_version!r}")
        object.__setattr__(self, "instruction_state", _safe_instruction_state(self.instruction_state))

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "session_id": self.session_id,
            "project_key": self.project_key,
            "created_at": self.created_at,
            "last_used_at": self.last_used_at,
            "instruction_state": dict(self.instruction_state),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "SessionMetadata":
        if not isinstance(value, Mapping):
            raise TypeError("Session metadata must be a mapping")
        version = value.get("schema_version")
        if version in {1, 2}:
            raise SessionIncompatibleError("Session v1/v2 is incompatible with Session v3; migration is not supported")
        required = {"schema_version", "session_id", "project_key", "created_at", "last_used_at", "instruction_state"}
        missing = required.difference(value)
        if missing:
            raise SessionCorruptError(f"Session metadata missing fields: {sorted(missing)}")
        unknown = set(value).difference(required)
        if unknown:
            raise SessionCorruptError(f"Session metadata has unknown fields: {sorted(unknown)}")
        try:
            return cls(
                schema_version=int(value["schema_version"]),
                session_id=str(value["session_id"]),
                project_key=str(value["project_key"]),
                created_at=str(value["created_at"]),
                last_used_at=str(value["last_used_at"]),
                instruction_state=value["instruction_state"],  # type: ignore[arg-type]
            )
        except (TypeError, ValueError) as exc:
            raise SessionCorruptError(f"invalid Session metadata: {exc}") from exc


@dataclass(frozen=True, slots=True)
class SessionSnapshot:
    metadata: SessionMetadata
    transcript: Transcript
    timeline: Timeline
    last_transcript_sequence: int
    last_timeline_sequence: int
    recovery_diagnostics: tuple[str, ...] = ()

    @property
    def session_id(self) -> str:
        return self.metadata.session_id

    @property
    def project_key(self) -> str:
        return self.metadata.project_key

    @property
    def last_record_sequence(self) -> int:
        return self.last_transcript_sequence

    @property
    def next_record_sequence(self) -> int:
        return self.last_record_sequence + 1

    def to_dict(self) -> dict[str, object]:
        return {
            "metadata": self.metadata.to_dict(),
            "transcript": [entry.to_dict() for entry in self.transcript.entries],
            "timeline": [record.to_dict() for record in self.timeline.records],
            "last_transcript_sequence": self.last_transcript_sequence,
            "last_timeline_sequence": self.last_timeline_sequence,
            "recovery_diagnostics": list(self.recovery_diagnostics),
        }


@dataclass(frozen=True, slots=True)
class TranscriptAppendOutcome:
    snapshot: SessionSnapshot
    transcript_appended: bool
    reload_succeeded: bool
    metadata_synced: bool
    failure_stage: str | None
    durability: str

    def __post_init__(self) -> None:
        if self.durability not in {"not_attempted", "durable", "not_durable", "unknown"}:
            raise ValueError(f"unknown Transcript append durability: {self.durability!r}")
        if self.transcript_appended != (self.durability == "durable"):
            raise ValueError("transcript_appended must match the durable outcome")


@dataclass(frozen=True, slots=True)
class TimelineAppendOutcome:
    snapshot: SessionSnapshot
    timeline_appended: bool
    reload_succeeded: bool
    metadata_synced: bool
    failure_stage: str | None
    durability: str

    def __post_init__(self) -> None:
        if self.durability not in {"not_attempted", "durable", "not_durable", "unknown"}:
            raise ValueError(f"unknown Timeline append durability: {self.durability!r}")
        if self.timeline_appended != (self.durability == "durable"):
            raise ValueError("timeline_appended must match the durable outcome")


@dataclass(frozen=True, slots=True)
class _ParsedLine:
    value: Mapping[str, object]
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class _LoadedSnapshot:
    snapshot: SessionSnapshot
    transcript_valid_end: int
    timeline_valid_end: int
    transcript_record_sequence: int
    timeline_record_sequence: int


class _ExclusiveFileLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._handle: Any | None = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        try:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
                os.fsync(handle.fileno())
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, IOError) as exc:
            handle.close()
            raise SessionBusyError(f"session busy: {self.path.parent.name}") from exc
        self._handle = handle

    def release(self) -> None:
        handle = self._handle
        self._handle = None
        if handle is None:
            return
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()

    def __enter__(self) -> "_ExclusiveFileLock":
        self.acquire()
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        del exc_type, exc, tb
        self.release()


class SessionFileStore:
    """Versioned Session v3 layout and durable append primitives."""

    def __init__(self, root: str | os.PathLike[str] | Path) -> None:
        self.root = Path(root).expanduser().resolve(strict=False)

    def session_path(self, session_id: str) -> Path:
        return self.root / _validate_session_id(session_id)

    def create_session(
        self,
        session_id: str | None = None,
        *,
        project_key: str,
        instruction_state: Mapping[str, object] | None = None,
    ) -> SessionMetadata:
        identifier = _validate_session_id(session_id or uuid.uuid4().hex)
        path = self.session_path(identifier)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.mkdir()
        except FileExistsError as exc:
            raise SessionFileError(f"Session already exists: {identifier}") from exc
        (path / "tool-results").mkdir()
        (path / "writer.lock").touch()
        for filename in ("transcript.jsonl", "timeline.jsonl"):
            (path / filename).touch()
        now = _now()
        metadata = SessionMetadata(identifier, _require_text(project_key, "project_key"), now, now, instruction_state or {})
        _atomic_write_json(path / "metadata.json", metadata.to_dict())
        return metadata

    def open_writer(self, session_id: str, *, expected_project_key: str | None = None) -> "SessionWriter":
        return SessionWriter(self, _validate_session_id(session_id), expected_project_key)

    def read_session(self, session_id: str, *, expected_project_key: str | None = None) -> SessionSnapshot:
        path = self.session_path(session_id)
        if not path.is_dir():
            raise SessionNotFoundError(f"unknown Session: {session_id}")
        return self._load_snapshot(path, expected_project_key=expected_project_key).snapshot

    def persist_tool_result(self, session_id: str, content: str, *, policy: object | None = None) -> object:
        from .tools.tool_result_read import ToolResultFileStore

        return ToolResultFileStore(self).persist(session_id, content, policy=policy)  # type: ignore[arg-type]

    def read_tool_result(self, session_id: str, ref: str, *, offset: int = 0, limit: int | None = None, policy: object | None = None) -> object:
        from .tools.tool_result_read import ToolResultFileStore

        return ToolResultFileStore(self).read_page(session_id, ref, offset=offset, limit=limit, policy=policy)  # type: ignore[arg-type]

    def list_metadata(self, *, project_key: str | None = None) -> tuple[SessionMetadata, ...]:
        if not self.root.is_dir():
            return ()
        values: list[SessionMetadata] = []
        for path in self.root.iterdir():
            if not path.is_dir() or path.name == "tool-results":
                continue
            try:
                metadata = _read_metadata(path / "metadata.json")
            except SessionFileError:
                continue
            if project_key is None or metadata.project_key == project_key:
                values.append(metadata)
        values.sort(key=lambda item: (item.last_used_at, item.session_id), reverse=True)
        return tuple(values)

    def _load_snapshot(self, path: Path, *, expected_project_key: str | None = None, recover_incomplete_tail: bool = True) -> _LoadedSnapshot:
        metadata = _read_metadata(path / "metadata.json")
        if metadata.session_id != path.name:
            raise SessionCorruptError("Session metadata id does not match its directory")
        if expected_project_key is not None and metadata.project_key != expected_project_key:
            raise SessionNotFoundError("Session belongs to another project")
        if (path / "history.jsonl").exists():
            raise SessionIncompatibleError("old Session v1 history layout is incompatible with Session v3")
        required = (path / "transcript.jsonl", path / "timeline.jsonl")
        if not all(item.is_file() for item in required):
            raise SessionCorruptError("Session v3 files are incomplete")
        transcript, transcript_end, transcript_sequence, transcript_diagnostics = _read_transcript(
            path / "transcript.jsonl", metadata.session_id, recover_incomplete_tail=recover_incomplete_tail
        )
        timeline, timeline_end, timeline_sequence, timeline_diagnostics = _read_timeline(
            path / "timeline.jsonl", metadata.session_id, transcript
        )
        return _LoadedSnapshot(
            snapshot=SessionSnapshot(
                metadata=metadata,
                transcript=transcript,
                timeline=timeline,
                last_transcript_sequence=transcript_sequence,
                last_timeline_sequence=timeline_sequence,
                recovery_diagnostics=tuple(transcript_diagnostics + timeline_diagnostics),
            ),
            transcript_valid_end=transcript_end,
            timeline_valid_end=timeline_end,
            transcript_record_sequence=transcript_sequence,
            timeline_record_sequence=timeline_sequence,
        )


class SessionWriter:
    def __init__(self, store: SessionFileStore, session_id: str, expected_project_key: str | None) -> None:
        self.store = store
        self.session_id = session_id
        self.expected_project_key = expected_project_key
        self._lock = _ExclusiveFileLock(store.session_path(session_id) / "writer.lock")
        self._loaded: _LoadedSnapshot | None = None
        self._closed = False
        self._durability_unknown = False

    def __enter__(self) -> "SessionWriter":
        if self._closed:
            raise SessionFileError("SessionWriter is closed")
        path = self.store.session_path(self.session_id)
        if not path.is_dir():
            raise SessionNotFoundError(f"unknown Session: {self.session_id}")
        self._lock.acquire()
        try:
            self._loaded = self.store._load_snapshot(path, expected_project_key=self.expected_project_key)
            self._repair_tails()
        except Exception:
            self._lock.release()
            raise
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        del exc_type, exc, tb
        self.close()

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._lock.release()

    @property
    def durability_unknown(self) -> bool:
        return self._durability_unknown

    def quarantine_unknown_durability(self) -> None:
        self._require_open()
        self._durability_unknown = True

    def _require_open(self) -> None:
        if self._closed or self._loaded is None:
            raise SessionWriterRequiredError("Session writer lock is not held")

    def _require_writable(self) -> None:
        self._require_open()
        if self._durability_unknown:
            raise SessionDurabilityUnknownError("Session durability is unknown; close and reopen before writing")

    @property
    def snapshot(self) -> SessionSnapshot:
        self._require_open()
        assert self._loaded is not None
        return self._loaded.snapshot

    @property
    def metadata(self) -> SessionMetadata:
        return self.snapshot.metadata

    def touch(self) -> SessionMetadata:
        self._require_writable()
        metadata = replace(self.metadata, last_used_at=_now())
        self._write_metadata(metadata)
        return metadata

    def update_instruction_state(self, instruction_state: Mapping[str, object]) -> SessionMetadata:
        self._require_writable()
        metadata = replace(self.metadata, instruction_state=_safe_instruction_state(instruction_state), last_used_at=_now())
        self._write_metadata(metadata)
        return metadata

    def append_transcript(self, entries: TranscriptEntry | Sequence[TranscriptEntry]) -> TranscriptAppendOutcome:
        self._require_writable()
        values = (entries,) if isinstance(entries, TranscriptEntry) else tuple(entries)
        if not values:
            return TranscriptAppendOutcome(self.snapshot, False, True, True, None, "not_attempted")
        if not all(isinstance(entry, TranscriptEntry) for entry in values):
            raise TypeError("entries must contain TranscriptEntry values")
        _validate_transcript_append(self.snapshot.transcript, values)
        before = self.snapshot
        expected = self._loaded.transcript_record_sequence + 1  # type: ignore[union-attr]
        envelopes = []
        for entry in values:
            if entry.session_id != self.session_id:
                raise SessionFileError("Transcript entry belongs to another Session")
            envelopes.append({"schema_version": SESSION_RECORD_SCHEMA_VERSION, "kind": "transcript", "sequence": expected, "entry": entry.to_dict()})
            expected += 1
        path = self.store.session_path(self.session_id) / "transcript.jsonl"
        try:
            _append_jsonl(path, envelopes)
        except Exception:
            reconciliation, loaded = self._reconcile_transcript_append(before, values)
            if reconciliation == "durable":
                return self._finish_transcript(True, "transcript_append_reconciled")
            if reconciliation == "not_durable":
                return TranscriptAppendOutcome(loaded or self.snapshot, False, False, False, "transcript_append", "not_durable")
            self.quarantine_unknown_durability()
            return TranscriptAppendOutcome(self.snapshot, False, False, False, "transcript_durability_unknown", "unknown")
        try:
            self._reload(touch=False)
        except Exception:
            reconciliation, loaded = self._reconcile_transcript_append(before, values)
            if reconciliation == "durable":
                return self._finish_transcript(False, "transcript_reload")
            if reconciliation == "not_durable":
                return TranscriptAppendOutcome(loaded or self.snapshot, False, False, False, "transcript_reload", "not_durable")
            self.quarantine_unknown_durability()
            return TranscriptAppendOutcome(self.snapshot, False, False, False, "transcript_durability_unknown", "unknown")
        return self._finish_transcript(True, None)

    def _finish_transcript(self, reload_succeeded: bool, failure_stage: str | None) -> TranscriptAppendOutcome:
        metadata_synced = True
        stage = failure_stage
        try:
            self.touch()
        except Exception:
            metadata_synced = False
            stage = stage or "transcript_metadata_sync"
        return TranscriptAppendOutcome(self.snapshot, True, reload_succeeded, metadata_synced, stage, "durable")

    def _reconcile_transcript_append(self, before: SessionSnapshot, values: Sequence[TranscriptEntry]) -> tuple[str, SessionSnapshot | None]:
        try:
            loaded = self.store._load_snapshot(self.store.session_path(self.session_id), expected_project_key=self.expected_project_key, recover_incomplete_tail=False)
        except Exception:
            return "unknown", None
        expected = before.transcript.entries + tuple(values)
        actual = loaded.snapshot.transcript.entries
        if actual == expected:
            self._loaded = loaded
            self._repair_tails()
            return "durable", loaded.snapshot
        if actual == before.transcript.entries:
            self._loaded = loaded
            self._repair_tails()
            return "not_durable", loaded.snapshot
        return "unknown", loaded.snapshot

    def append_timeline_transaction(self, derived: Sequence[SemanticEntry | EpochMacroSummary], checkpoint: ActiveCheckpoint) -> TimelineAppendOutcome:
        self._require_writable()
        values = tuple(derived)
        if not values:
            return TimelineAppendOutcome(self.snapshot, False, True, True, None, "not_attempted")
        before = self.snapshot
        current_timeline = before.timeline
        try:
            candidate_timeline = current_timeline.append_transaction(values, checkpoint)
        except (TypeError, ValueError) as exc:
            raise SessionFileError("Timeline transaction identity is invalid") from exc
        added = tuple(candidate_timeline.records[len(current_timeline.records) :])
        normalized_values = added[:-1]
        normalized_checkpoint = added[-1]
        assert isinstance(normalized_checkpoint, ActiveCheckpoint)
        _validate_timeline_transaction(
            before.transcript,
            current_timeline,
            normalized_values,
            normalized_checkpoint,
            self.session_id,
        )
        expected = self._loaded.timeline_record_sequence + 1  # type: ignore[union-attr]
        envelopes: list[dict[str, object]] = []
        for record in added:
            envelopes.append({"schema_version": SESSION_RECORD_SCHEMA_VERSION, "kind": "timeline", "sequence": expected, "record": record.to_dict()})
            expected += 1
        path = self.store.session_path(self.session_id) / "timeline.jsonl"
        try:
            _append_jsonl(path, envelopes)
        except Exception:
            reconciliation, loaded = self._reconcile_timeline_append(before, added)
            if reconciliation == "durable":
                return self._finish_timeline(True, "timeline_append_reconciled")
            if reconciliation == "not_durable":
                return TimelineAppendOutcome(loaded or self.snapshot, False, False, False, "timeline_append", "not_durable")
            self.quarantine_unknown_durability()
            return TimelineAppendOutcome(self.snapshot, False, False, False, "timeline_durability_unknown", "unknown")
        try:
            self._reload(touch=False)
        except Exception:
            reconciliation, loaded = self._reconcile_timeline_append(before, added)
            if reconciliation == "durable":
                return self._finish_timeline(False, "timeline_reload")
            if reconciliation == "not_durable":
                return TimelineAppendOutcome(loaded or self.snapshot, False, False, False, "timeline_reload", "not_durable")
            self.quarantine_unknown_durability()
            return TimelineAppendOutcome(self.snapshot, False, False, False, "timeline_durability_unknown", "unknown")
        return self._finish_timeline(True, None)

    def append_timeline(self, timeline: Timeline) -> TimelineAppendOutcome:
        self._require_writable()
        if not isinstance(timeline, Timeline) or timeline.session_id != self.session_id:
            raise SessionFileError("timeline belongs to another Session")
        current = self.snapshot.timeline
        if not _timeline_records_equal(timeline.records[: len(current.records)], current.records):
            raise SessionFileError("Timeline candidate does not extend the current Timeline")
        added = timeline.records[len(current.records) :]
        if not added or not isinstance(added[-1], ActiveCheckpoint):
            raise SessionFileError("Timeline candidate must end with an ActiveCheckpoint")
        return self.append_timeline_transaction(added[:-1], added[-1])

    def _finish_timeline(self, reload_succeeded: bool, failure_stage: str | None) -> TimelineAppendOutcome:
        metadata_synced = True
        stage = failure_stage
        try:
            self.touch()
        except Exception:
            metadata_synced = False
            stage = stage or "timeline_metadata_sync"
        return TimelineAppendOutcome(self.snapshot, True, reload_succeeded, metadata_synced, stage, "durable")

    def _reconcile_timeline_append(self, before: SessionSnapshot, values: Sequence[TimelineRecord]) -> tuple[str, SessionSnapshot | None]:
        try:
            loaded = self.store._load_snapshot(self.store.session_path(self.session_id), expected_project_key=self.expected_project_key, recover_incomplete_tail=False)
        except Exception:
            return "unknown", None
        expected = before.timeline.records + tuple(values)
        actual = loaded.snapshot.timeline.records
        if _timeline_records_equal(actual, expected):
            self._loaded = loaded
            self._repair_tails()
            return "durable", loaded.snapshot
        if _timeline_records_equal(actual, before.timeline.records):
            self._loaded = loaded
            self._repair_tails()
            return "not_durable", loaded.snapshot
        return "unknown", loaded.snapshot

    def persist_tool_result(self, content: str, *, policy: object | None = None) -> object:
        self._require_writable()
        return self.store.persist_tool_result(self.session_id, content, policy=policy)

    def read_tool_result(self, ref: str, *, offset: int = 0, limit: int | None = None, policy: object | None = None) -> object:
        self._require_open()
        return self.store.read_tool_result(self.session_id, ref, offset=offset, limit=limit, policy=policy)

    def _require_open_writer_for_metadata(self) -> None:
        self._require_open()

    def _write_metadata(self, metadata: SessionMetadata) -> None:
        _atomic_write_json(self.store.session_path(self.session_id) / "metadata.json", metadata.to_dict())
        assert self._loaded is not None
        self._loaded = replace(self._loaded, snapshot=replace(self._loaded.snapshot, metadata=metadata))

    def _repair_tails(self) -> None:
        assert self._loaded is not None
        path = self.store.session_path(self.session_id)
        for filename, valid_end in (
            ("transcript.jsonl", self._loaded.transcript_valid_end),
            ("timeline.jsonl", self._loaded.timeline_valid_end),
        ):
            target = path / filename
            size = target.stat().st_size if target.exists() else 0
            if valid_end < size:
                with target.open("r+b") as handle:
                    handle.truncate(valid_end)
                    handle.flush()
                    os.fsync(handle.fileno())

    def _reload(self, *, touch: bool) -> None:
        self._loaded = self.store._load_snapshot(self.store.session_path(self.session_id), expected_project_key=self.expected_project_key, recover_incomplete_tail=False)
        self._repair_tails()
        if touch:
            self.touch()


def _read_metadata(path: Path) -> SessionMetadata:
    if not path.is_file():
        raise SessionCorruptError(f"missing Session metadata: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SessionCorruptError(f"invalid Session metadata: {path}") from exc
    try:
        return SessionMetadata.from_dict(value)
    except SessionIncompatibleError:
        raise
    except (TypeError, ValueError) as exc:
        raise SessionCorruptError(f"invalid Session metadata: {exc}") from exc


def _atomic_write_json(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _append_jsonl(path: Path, values: Sequence[Mapping[str, object]]) -> None:
    payload = "".join(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n" for value in values).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def _read_jsonl_lines(path: Path) -> tuple[tuple[_ParsedLine, ...], int, tuple[str, ...]]:
    try:
        data = path.read_bytes() if path.exists() else b""
    except OSError as exc:
        raise SessionCorruptError(f"could not read Session log: {path}") from exc
    parsed: list[_ParsedLine] = []
    diagnostics: list[str] = []
    offset = 0
    valid_end = len(data)
    chunks = data.splitlines(keepends=True)
    for index, chunk in enumerate(chunks):
        start = offset
        offset += len(chunk)
        complete_line = chunk.endswith(b"\n")
        raw = chunk[:-1] if complete_line else chunk
        if raw.endswith(b"\r"):
            raw = raw[:-1]
        if not raw.strip():
            if not complete_line and index == len(chunks) - 1:
                valid_end = start
                diagnostics.append("ignored_incomplete_tail")
                break
            continue
        if not complete_line:
            valid_end = start
            diagnostics.append("ignored_incomplete_tail")
            break
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise SessionCorruptError(f"corrupt middle record in {path} at byte {start}") from exc
        if not isinstance(value, Mapping):
            raise SessionCorruptError(f"Session record must be a JSON object: {path}")
        parsed.append(_ParsedLine(value, start, offset))
    return tuple(parsed), valid_end, tuple(diagnostics)


def _validate_envelope(value: Mapping[str, object], *, path: Path) -> tuple[str, int]:
    required = {"schema_version", "kind", "sequence"}
    if not required.issubset(value):
        raise SessionCorruptError(f"Session record missing fields in {path}")
    if value["schema_version"] != SESSION_RECORD_SCHEMA_VERSION:
        raise SessionCorruptError(f"unsupported Session record schema in {path}")
    kind = value["kind"]
    if not isinstance(kind, str) or kind not in {"transcript", "timeline"}:
        raise SessionCorruptError(f"unknown Session record kind in {path}")
    allowed = required | ({"entry"} if kind == "transcript" else {"record"})
    if set(value).difference(allowed):
        raise SessionCorruptError(f"Session record has unknown fields in {path}")
    sequence = value["sequence"]
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
        raise SessionCorruptError(f"invalid Session record sequence in {path}")
    return kind, sequence


def _incomplete_units(transcript: Transcript) -> tuple[SemanticUnit, ...]:
    return tuple(unit for unit in transcript.semantic_units(complete_only=False) if not unit.complete)


def _tool_id(entry: TranscriptEntry) -> str | None:
    part = entry.payload.get("part")
    payload = part if isinstance(part, Mapping) else entry.payload
    value = payload.get("tool_call_id")
    return value if isinstance(value, str) and value else None


def _recoverable_incomplete_unit(unit: SemanticUnit) -> bool:
    if any(
        entry.kind not in (TranscriptKind.TOOL_CALL, TranscriptKind.TOOL_RESULT) and not entry.commit_boundary
        for entry in unit.entries
    ):
        return False
    calls = [_tool_id(entry) for entry in unit.entries if entry.kind is TranscriptKind.TOOL_CALL]
    results = [_tool_id(entry) for entry in unit.entries if entry.kind is TranscriptKind.TOOL_RESULT]
    if not calls or any(item is None for item in (*calls, *results)):
        return False
    return len(calls) == len(set(calls)) and len(results) == len(set(results)) and all(item in calls for item in results)


def _validate_transcript_append(transcript: Transcript, values: Sequence[TranscriptEntry]) -> None:
    current_incomplete = _incomplete_units(transcript)
    if current_incomplete:
        pending = current_incomplete[0]
        units = transcript.semantic_units(complete_only=False)
        if len(current_incomplete) != 1 or units[-1].unit_id != pending.unit_id or not _recoverable_incomplete_unit(pending):
            raise SessionFileError("Transcript contains an invalid incomplete semantic unit")
        call_ids = {_tool_id(entry) for entry in pending.entries if entry.kind is TranscriptKind.TOOL_CALL}
        result_ids = {_tool_id(entry) for entry in pending.entries if entry.kind is TranscriptKind.TOOL_RESULT}
        for entry in values:
            if entry.kind is not TranscriptKind.TOOL_RESULT or entry.semantic_unit_id != pending.unit_id or _tool_id(entry) not in call_ids - result_ids:
                raise SessionFileError("only a matching ToolResult may follow an incomplete ToolCall group")
            result_ids.add(_tool_id(entry))
    candidate = transcript
    try:
        for entry in values:
            candidate = candidate.append(entry)
    except (TypeError, ValueError) as exc:
        raise SessionFileError("Transcript append violates strict sequence") from exc
    incomplete = _incomplete_units(candidate)
    if incomplete:
        units = candidate.semantic_units(complete_only=False)
        if len(incomplete) != 1 or units[-1].unit_id != incomplete[0].unit_id or not _recoverable_incomplete_unit(incomplete[0]):
            raise SessionFileError("Transcript append would leave an invalid incomplete unit")


def _validate_timeline_transaction(transcript: Transcript, timeline: Timeline, derived: Sequence[SemanticEntry | EpochMacroSummary], checkpoint: ActiveCheckpoint, session_id: str) -> None:
    if checkpoint.session_id not in (None, session_id):
        raise SessionFileError("ActiveCheckpoint belongs to another Session")
    transaction_ids = {record.transaction_id for record in (*derived, checkpoint) if record.transaction_id is not None}
    if len(transaction_ids) > 1 or (transaction_ids and checkpoint.transaction_id not in transaction_ids):
        raise SessionFileError("Timeline transaction records do not share one transaction identity")
    if _incomplete_units(transcript):
        raise SessionFileError("Timeline cannot commit while Transcript has an incomplete unit")
    for record in derived:
        if not isinstance(record, (SemanticEntry, EpochMacroSummary)):
            raise SessionFileError("Timeline transaction contains an invalid derived record")
        if record.session_id not in (None, session_id):
            raise SessionFileError("Timeline record belongs to another Session")
        for ref in record.refs:
            if ref.session_id != session_id:
                raise SessionFileError("Timeline ref belongs to another Session")
            try:
                transcript.select(ref.sequence_start, ref.sequence_end, complete_only=True)
            except ValueError as exc:
                raise SessionFileError("Timeline ref is not a complete Transcript boundary") from exc
    if not derived:
        raise SessionFileError("Timeline transaction must contain a derived record")


def _timeline_records_equal(left: Sequence[TimelineRecord], right: Sequence[TimelineRecord]) -> bool:
    return tuple(record.to_dict() for record in left) == tuple(record.to_dict() for record in right)


def _read_transcript(path: Path, session_id: str, *, recover_incomplete_tail: bool) -> tuple[Transcript, int, int, list[str]]:
    lines, valid_end, diagnostics = _read_jsonl_lines(path)
    expected = 1
    transcript = Transcript(session_id)
    parsed: list[tuple[TranscriptEntry, _ParsedLine]] = []
    for line in lines:
        kind, sequence = _validate_envelope(line.value, path=path)
        if kind != "transcript":
            raise SessionCorruptError(f"non-Transcript record found in transcript log: {path}")
        if sequence != expected:
            raise SessionCorruptError(f"Transcript record sequence is not strict in {path}")
        expected += 1
        value = line.value.get("entry")
        if not isinstance(value, Mapping):
            raise SessionCorruptError(f"Transcript record entry must be a mapping: {path}")
        try:
            entry = TranscriptEntry.from_dict(value)
            if entry.session_id != session_id:
                raise ValueError("entry belongs to another Session")
            transcript = transcript.append(entry)
            parsed.append((entry, line))
        except (TypeError, ValueError, KeyError) as exc:
            raise SessionCorruptError(f"invalid Transcript record in {path}: {exc}") from exc
    incomplete = _incomplete_units(transcript)
    if incomplete:
        units = transcript.semantic_units(complete_only=False)
        pending = incomplete[0]
        if len(incomplete) != 1 or units[-1].unit_id != pending.unit_id or not _recoverable_incomplete_unit(pending):
            raise SessionCorruptError(f"incomplete semantic unit cannot be recovered: {path}")
        start = next((line.start for entry, line in parsed if entry.sequence >= pending.sequence_start), None)
        if start is None:
            raise SessionCorruptError(f"incomplete semantic unit has no persisted boundary: {path}")
        if recover_incomplete_tail and any(entry.kind is TranscriptKind.TOOL_CALL for entry in pending.entries):
            diagnostics = [*diagnostics, "preserved_incomplete_tool_semantic_tail"]
        elif recover_incomplete_tail:
            transcript = Transcript(session_id, tuple(entry for entry, line in parsed if line.start < start))
            valid_end = start
            diagnostics = [*diagnostics, "ignored_incomplete_semantic_tail"]
    record_sequence = sum(1 for line in lines if line.end <= valid_end)
    return transcript, valid_end, record_sequence, list(diagnostics)


def _read_timeline(path: Path, session_id: str, transcript: Transcript) -> tuple[Timeline, int, int, list[str]]:
    lines, valid_end, diagnostics = _read_jsonl_lines(path)
    expected = 1
    records: list[TimelineRecord] = []
    for line in lines:
        kind, sequence = _validate_envelope(line.value, path=path)
        if kind != "timeline":
            raise SessionCorruptError(f"non-Timeline record found in timeline log: {path}")
        if sequence != expected:
            raise SessionCorruptError(f"Timeline record sequence is not strict in {path}")
        expected += 1
        value = line.value.get("record")
        if not isinstance(value, Mapping):
            raise SessionCorruptError(f"Timeline record must be a mapping: {path}")
        try:
            record = timeline_record_from_dict(value)
            if record.session_id not in (None, session_id):
                raise ValueError("record belongs to another Session")
            if not isinstance(record, ActiveCheckpoint):
                for ref in record.refs:
                    transcript.select(ref.sequence_start, ref.sequence_end, complete_only=True)
            records.append(record)
        except (TypeError, ValueError, KeyError) as exc:
            raise SessionCorruptError(f"invalid Timeline record in {path}: {exc}") from exc
    try:
        timeline = Timeline(session_id, tuple(records))
    except (TypeError, ValueError) as exc:
        raise SessionCorruptError(f"invalid Timeline transaction structure in {path}: {exc}") from exc
    uncommitted_groups = False
    for group in timeline.transaction_groups():
        if group and isinstance(group[-1], ActiveCheckpoint):
            _validate_timeline_transaction(transcript, timeline, group[:-1], group[-1], session_id)
        else:
            uncommitted_groups = uncommitted_groups or bool(group)
    if uncommitted_groups:
        diagnostics = [*diagnostics, "ignored_uncommitted_timeline_tail"]
    record_sequence = sum(1 for line in lines if line.end <= valid_end)
    return timeline, valid_end, record_sequence, list(diagnostics)


__all__ = [
    "SESSION_RECORD_SCHEMA_VERSION",
    "SESSION_SCHEMA_VERSION",
    "SessionBusyError",
    "SessionCorruptError",
    "SessionDurabilityUnknownError",
    "SessionFileError",
    "SessionFileStore",
    "SessionIncompatibleError",
    "SessionMetadata",
    "SessionNotFoundError",
    "SessionSnapshot",
    "SessionWriter",
    "SessionWriterRequiredError",
    "TimelineAppendOutcome",
    "TranscriptAppendOutcome",
]
