"""Durable, single-writer files for one UthCode Session.

This Integration owns bytes, fsync, atomic metadata replacement, and the
cross-platform advisory lock.  It does not decide when a Session is resumed
or how Instruction State changes; those policies remain in Application.
"""

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
    CanonicalHistory,
    HistoryEntry,
    HistoryKind,
    Projection,
    RuntimeLog,
    RuntimeLogEntry,
    SemanticUnit,
)


SESSION_SCHEMA_VERSION = 1
SESSION_RECORD_SCHEMA_VERSION = 1


class SessionFileError(RuntimeError):
    """Base error for durable Session file operations."""


class SessionBusyError(SessionFileError):
    """Another process currently owns the Session writer lock."""


class SessionNotFoundError(SessionFileError):
    """The requested Session does not exist."""


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


def _safe_instruction_state(value: Mapping[str, object] | None) -> dict[str, object]:
    """Keep only the W01 metadata contract; never persist AGENTS正文."""

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
        raise ValueError(
            "instruction_state contains unsupported or unsafe fields: "
            + ", ".join(sorted(str(item) for item in unknown))
        )
    result: dict[str, object] = {}
    for key in allowed:
        if key in value:
            result[key] = _json_safe(value[key])
    # A content-bearing field is intentionally not accepted even nested in a
    # future shape.  Source fingerprints are the only persisted source facts.
    encoded = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if any(marker in encoded.casefold() for marker in ("agents正文", "effective_instruction_set", "prompt_text")):
        raise ValueError("instruction_state must not contain instruction text")
    return result


def _json_safe(value: object) -> object:
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_safe(item) for item in value]
    raise TypeError("instruction_state contains a non-JSON value")


@dataclass(frozen=True, slots=True)
class SessionMetadata:
    """Versioned metadata that is safe to persist outside semantic History."""

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
        required = {
            "schema_version",
            "session_id",
            "project_key",
            "created_at",
            "last_used_at",
            "instruction_state",
        }
        missing = required.difference(value)
        if missing:
            raise SessionCorruptError(f"Session metadata missing fields: {sorted(missing)}")
        unknown = set(value).difference(required)
        if unknown:
            raise SessionCorruptError(f"Session metadata has unknown fields: {sorted(unknown)}")
        try:
            return cls(
                schema_version=value["schema_version"],  # type: ignore[arg-type]
                session_id=value["session_id"],  # type: ignore[arg-type]
                project_key=value["project_key"],  # type: ignore[arg-type]
                created_at=value["created_at"],  # type: ignore[arg-type]
                last_used_at=value["last_used_at"],  # type: ignore[arg-type]
                instruction_state=value["instruction_state"],  # type: ignore[arg-type]
            )
        except (TypeError, ValueError) as exc:
            raise SessionCorruptError(f"invalid Session metadata: {exc}") from exc


@dataclass(frozen=True, slots=True)
class SessionSnapshot:
    """Recovered semantic and non-semantic values at one durable boundary."""

    metadata: SessionMetadata
    history: CanonicalHistory
    projection: Projection | None
    runtime_log: RuntimeLog
    last_record_sequence: int
    recovery_diagnostics: tuple[str, ...] = ()

    @property
    def session_id(self) -> str:
        return self.metadata.session_id

    @property
    def project_key(self) -> str:
        return self.metadata.project_key

    @property
    def next_record_sequence(self) -> int:
        return self.last_record_sequence + 1

    def to_dict(self) -> dict[str, object]:
        return {
            "metadata": self.metadata.to_dict(),
            "history": [entry.to_dict() for entry in self.history.entries],
            "projection": self.projection.to_dict() if self.projection is not None else None,
            "runtime_log": [entry.to_dict() for entry in self.runtime_log.entries],
            "last_record_sequence": self.last_record_sequence,
            "recovery_diagnostics": list(self.recovery_diagnostics),
        }


@dataclass(frozen=True, slots=True)
class HistoryAppendOutcome:
    """Separate durable History append from reload and metadata touch steps."""

    snapshot: SessionSnapshot
    history_appended: bool
    reload_succeeded: bool
    metadata_synced: bool
    failure_stage: str | None
    durability: str

    def __post_init__(self) -> None:
        if self.durability not in {
            "not_attempted",
            "durable",
            "not_durable",
            "unknown",
        }:
            raise ValueError(f"unknown History append durability: {self.durability!r}")
        if self.history_appended != (self.durability == "durable"):
            raise ValueError("history_appended must match the durable outcome")
        if not isinstance(self.reload_succeeded, bool):
            raise TypeError("reload_succeeded must be a boolean")
        if not isinstance(self.metadata_synced, bool):
            raise TypeError("metadata_synced must be a boolean")


@dataclass(frozen=True, slots=True)
class _ParsedLine:
    value: Mapping[str, object]
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class _LoadedSnapshot:
    snapshot: SessionSnapshot
    history_valid_end: int
    runtime_valid_end: int
    runtime_record_sequence: int


class _ExclusiveFileLock:
    """A process-held advisory/exclusive lock for Windows and POSIX."""

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
    """Versioned Session layout and durable append primitives."""

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
        project = _require_text(project_key, "project_key")
        path = self.session_path(identifier)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.mkdir()
        except FileExistsError as exc:
            raise SessionFileError(f"Session already exists: {identifier}") from exc
        (path / "tool-results").mkdir()
        (path / "writer.lock").touch()
        (path / "history.jsonl").touch()
        (path / "runtime.jsonl").touch()
        now = _now()
        metadata = SessionMetadata(
            session_id=identifier,
            project_key=project,
            created_at=now,
            last_used_at=now,
            instruction_state={} if instruction_state is None else instruction_state,
        )
        try:
            _atomic_write_json(path / "metadata.json", metadata.to_dict())
        except Exception:
            # Creation failed before the Session became usable.  The caller can
            # safely remove this empty directory manually; no semantic record
            # has been written.
            raise
        return metadata

    def open_writer(
        self,
        session_id: str,
        *,
        expected_project_key: str | None = None,
    ) -> "SessionWriter":
        return SessionWriter(self, _validate_session_id(session_id), expected_project_key)

    def read_session(
        self,
        session_id: str,
        *,
        expected_project_key: str | None = None,
    ) -> SessionSnapshot:
        path = self.session_path(session_id)
        if not path.is_dir():
            raise SessionNotFoundError(f"unknown Session: {session_id}")
        loaded = self._load_snapshot(path, expected_project_key=expected_project_key)
        return loaded.snapshot

    def persist_tool_result(
        self,
        session_id: str,
        content: str,
        *,
        policy: object | None = None,
    ) -> object:
        """Persist one complete Tool Result under the validated Session root."""

        from .tools.tool_result_read import ToolResultFileStore

        return ToolResultFileStore(self).persist(session_id, content, policy=policy)  # type: ignore[arg-type]

    def read_tool_result(
        self,
        session_id: str,
        ref: str,
        *,
        offset: int = 0,
        limit: int | None = None,
        policy: object | None = None,
    ) -> object:
        """Read one bounded page through an opaque, Session-owned ref."""

        from .tools.tool_result_read import ToolResultFileStore

        return ToolResultFileStore(self).read_page(  # type: ignore[arg-type]
            session_id,
            ref,
            offset=offset,
            limit=limit,
            policy=policy,
        )

    def list_metadata(self, *, project_key: str | None = None) -> tuple[SessionMetadata, ...]:
        if not self.root.is_dir():
            return ()
        values: list[SessionMetadata] = []
        for path in self.root.iterdir():
            if not path.is_dir() or path.name == "tool-results":
                continue
            metadata_path = path / "metadata.json"
            if not metadata_path.is_file():
                continue
            try:
                metadata = _read_metadata(metadata_path)
            except SessionFileError:
                continue
            if project_key is None or metadata.project_key == project_key:
                values.append(metadata)
        values.sort(key=lambda item: (item.last_used_at, item.session_id), reverse=True)
        return tuple(values)

    def _load_snapshot(
        self,
        path: Path,
        *,
        expected_project_key: str | None = None,
        recover_incomplete_tail: bool = True,
    ) -> _LoadedSnapshot:
        metadata = _read_metadata(path / "metadata.json")
        if metadata.session_id != path.name:
            raise SessionCorruptError("Session metadata id does not match its directory")
        if expected_project_key is not None and metadata.project_key != expected_project_key:
            raise SessionNotFoundError("Session belongs to another project")
        history, history_end, history_sequence, history_diagnostics = _read_history(
            path / "history.jsonl",
            metadata.session_id,
            recover_incomplete_tail=recover_incomplete_tail,
        )
        projection = _read_projection_from_history(path / "history.jsonl", history, metadata.session_id)
        runtime, runtime_end, runtime_sequence, runtime_diagnostics = _read_runtime(
            path / "runtime.jsonl",
        )
        return _LoadedSnapshot(
            snapshot=SessionSnapshot(
                metadata=metadata,
                history=history,
                projection=projection,
                runtime_log=runtime,
                last_record_sequence=history_sequence,
                recovery_diagnostics=tuple(history_diagnostics + runtime_diagnostics),
            ),
            history_valid_end=history_end,
            runtime_valid_end=runtime_end,
            runtime_record_sequence=runtime_sequence,
        )


class SessionWriter:
    """A lock-held Session handle with durable append operations."""

    def __init__(
        self,
        store: SessionFileStore,
        session_id: str,
        expected_project_key: str | None,
    ) -> None:
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
            self._loaded = self.store._load_snapshot(
                path,
                expected_project_key=self.expected_project_key,
            )
            self._repair_tails()
        except Exception:
            self._lock.release()
            raise
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        del exc_type, exc, tb
        self.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._lock.release()

    @property
    def durability_unknown(self) -> bool:
        """Whether this held writer must be closed and reopened to reconcile."""

        return self._durability_unknown

    def quarantine_unknown_durability(self) -> None:
        """Quarantine this writer until a fresh writer validates the Session."""

        self._require_open()
        self._durability_unknown = True

    def _require_writable(self) -> None:
        self._require_open()
        if self._durability_unknown:
            raise SessionDurabilityUnknownError(
                "Session History durability is unknown; close and reopen the "
                "Session to reconcile before writing"
            )

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
        metadata = replace(
            self.metadata,
            instruction_state=_safe_instruction_state(instruction_state),
            last_used_at=_now(),
        )
        self._write_metadata(metadata)
        return metadata

    def append_history(
        self,
        entries: HistoryEntry | Sequence[HistoryEntry],
    ) -> HistoryAppendOutcome:
        self._require_writable()
        values = (entries,) if isinstance(entries, HistoryEntry) else tuple(entries)
        if not values:
            return HistoryAppendOutcome(
                snapshot=self.snapshot,
                history_appended=False,
                reload_succeeded=True,
                metadata_synced=True,
                failure_stage=None,
                durability="not_attempted",
            )
        if not all(isinstance(entry, HistoryEntry) for entry in values):
            raise TypeError("entries must contain HistoryEntry values")
        before = self.snapshot
        expected_semantic = self.snapshot.history.last_sequence + 1
        expected_record = self.snapshot.next_record_sequence
        envelopes: list[dict[str, object]] = []
        for entry in values:
            if entry.session_id != self.session_id:
                raise SessionFileError("history entry belongs to another Session")
            if entry.sequence != expected_semantic:
                raise SessionFileError(
                    f"history append expected sequence {expected_semantic}, got {entry.sequence}"
                )
            envelopes.append(
                {
                    "schema_version": SESSION_RECORD_SCHEMA_VERSION,
                    "kind": "interaction",
                    "sequence": expected_record,
                    "entry": entry.to_dict(),
                }
            )
            expected_semantic += 1
            expected_record += 1
        _validate_history_append(self.snapshot.history, values)
        path = self.store.session_path(self.session_id) / "history.jsonl"
        try:
            _append_jsonl(path, envelopes)
        except Exception:
            reconciliation, snapshot = self._reconcile_history_append(before, values)
            if reconciliation == "durable":
                return self._finish_history_append(
                    reload_succeeded=False,
                    failure_stage="history_append_reconciled",
                )
            if reconciliation == "not_durable":
                return HistoryAppendOutcome(
                    snapshot=self.snapshot if snapshot is None else snapshot,
                    history_appended=False,
                    reload_succeeded=False,
                    metadata_synced=False,
                    failure_stage="history_append",
                    durability="not_durable",
                )
            self.quarantine_unknown_durability()
            return HistoryAppendOutcome(
                snapshot=self.snapshot,
                history_appended=False,
                reload_succeeded=False,
                metadata_synced=False,
                failure_stage="history_durability_unknown",
                durability="unknown",
            )

        try:
            self._reload(touch=False)
        except Exception:
            reconciliation, _snapshot = self._reconcile_history_append(before, values)
            if reconciliation != "durable":
                self.quarantine_unknown_durability()
                return HistoryAppendOutcome(
                    snapshot=self.snapshot,
                    history_appended=False,
                    reload_succeeded=False,
                    metadata_synced=False,
                    failure_stage="history_durability_unknown",
                    durability="unknown",
                )
            return self._finish_history_append(
                reload_succeeded=False,
                failure_stage="history_reload",
            )
        return self._finish_history_append(
            reload_succeeded=True,
            failure_stage=None,
        )

    def _finish_history_append(
        self,
        *,
        reload_succeeded: bool,
        failure_stage: str | None,
    ) -> HistoryAppendOutcome:
        metadata_synced = True
        final_failure_stage = failure_stage
        try:
            self.touch()
        except Exception:
            metadata_synced = False
            if final_failure_stage is None:
                final_failure_stage = "history_metadata_sync"
        return HistoryAppendOutcome(
            snapshot=self.snapshot,
            history_appended=True,
            reload_succeeded=reload_succeeded,
            metadata_synced=metadata_synced,
            failure_stage=final_failure_stage,
            durability="durable",
        )

    def _reconcile_history_append(
        self,
        before: SessionSnapshot,
        values: Sequence[HistoryEntry],
    ) -> tuple[str, SessionSnapshot | None]:
        """Reconcile a post-write exception using structured History identity."""

        try:
            loaded = self.store._load_snapshot(
                self.store.session_path(self.session_id),
                expected_project_key=self.expected_project_key,
                recover_incomplete_tail=False,
            )
        except Exception:
            return "unknown", None

        actual = loaded.snapshot.history.entries
        expected = before.history.entries + tuple(values)
        if actual == expected:
            self._loaded = loaded
            self._repair_tails()
            return "durable", loaded.snapshot
        if actual == before.history.entries:
            self._loaded = loaded
            self._repair_tails()
            return "not_durable", loaded.snapshot
        return "unknown", loaded.snapshot

    def persist_tool_result(
        self,
        content: str,
        *,
        policy: object | None = None,
    ) -> object:
        """Persist a result while this writer owns the Session lock."""

        self._require_writable()
        return self.store.persist_tool_result(self.session_id, content, policy=policy)

    def read_tool_result(
        self,
        ref: str,
        *,
        offset: int = 0,
        limit: int | None = None,
        policy: object | None = None,
    ) -> object:
        """Read a bounded result page through the held Session boundary."""

        self._require_open()
        return self.store.read_tool_result(
            self.session_id,
            ref,
            offset=offset,
            limit=limit,
            policy=policy,
        )

    def append_projection(self, projection: Projection) -> SessionSnapshot:
        self._require_writable()
        if not isinstance(projection, Projection):
            raise TypeError("projection must be a Projection")
        if projection.session_id != self.session_id:
            raise SessionFileError("projection belongs to another Session")
        current = self.snapshot.projection
        if current is not None and projection.revision <= current.revision:
            raise SessionFileError("projection revision must be strictly increasing")
        if _incomplete_units(self.snapshot.history):
            raise SessionFileError("projection cannot follow an incomplete semantic unit")
        if projection.sequence_end > self.snapshot.history.last_sequence:
            raise SessionFileError("projection cannot reference unwritten history")
        for unit in projection.units:
            for entry in unit.entries:
                if (
                    entry.sequence > self.snapshot.history.last_sequence
                    or self.snapshot.history.entries[entry.sequence - 1] != entry
                ):
                    raise SessionFileError("projection does not match canonical History")
        envelope = {
            "schema_version": SESSION_RECORD_SCHEMA_VERSION,
            "kind": "projection",
            "sequence": self.snapshot.next_record_sequence,
            "projection": projection.to_dict(),
        }
        _append_jsonl(self.store.session_path(self.session_id) / "history.jsonl", (envelope,))
        self._reload(touch=True)
        return self.snapshot

    def append_runtime(self, entry: RuntimeLogEntry) -> SessionSnapshot:
        self._require_writable()
        if not isinstance(entry, RuntimeLogEntry):
            raise TypeError("entry must be RuntimeLogEntry")
        envelope = {
            "schema_version": SESSION_RECORD_SCHEMA_VERSION,
            "kind": "runtime",
            "sequence": self._loaded.runtime_record_sequence + 1 if self._loaded else 1,
            "entry": entry.to_dict(),
        }
        _append_jsonl(self.store.session_path(self.session_id) / "runtime.jsonl", (envelope,))
        self._reload(touch=True)
        return self.snapshot

    def _require_open(self) -> None:
        if self._closed or self._loaded is None:
            raise SessionWriterRequiredError("Session writer lock is not held")

    def _write_metadata(self, metadata: SessionMetadata) -> None:
        _atomic_write_json(
            self.store.session_path(self.session_id) / "metadata.json",
            metadata.to_dict(),
        )
        assert self._loaded is not None
        self._loaded = replace(
            self._loaded,
            snapshot=replace(self._loaded.snapshot, metadata=metadata),
        )

    def _repair_tails(self) -> None:
        assert self._loaded is not None
        session_path = self.store.session_path(self.session_id)
        for filename, valid_end in (
            ("history.jsonl", self._loaded.history_valid_end),
            ("runtime.jsonl", self._loaded.runtime_valid_end),
        ):
            path = session_path / filename
            size = path.stat().st_size if path.exists() else 0
            if valid_end < size:
                with path.open("r+b") as handle:
                    handle.truncate(valid_end)
                    handle.flush()
                    os.fsync(handle.fileno())

    def _reload(self, *, touch: bool) -> None:
        loaded = self.store._load_snapshot(
            self.store.session_path(self.session_id),
            expected_project_key=self.expected_project_key,
            recover_incomplete_tail=False,
        )
        self._loaded = loaded
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
    return SessionMetadata.from_dict(value)


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
    payload = "".join(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        for value in values
    ).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def _read_jsonl_lines(path: Path) -> tuple[tuple[_ParsedLine, ...], int, tuple[str, ...]]:
    if not path.exists():
        return (), 0, ()
    try:
        data = path.read_bytes()
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
    if set(value).intersection({"record_kind"}):
        raise SessionCorruptError(f"unknown Session record field in {path}")
    if not required.issubset(value):
        raise SessionCorruptError(f"Session record missing fields in {path}")
    if value["schema_version"] != SESSION_RECORD_SCHEMA_VERSION:
        raise SessionCorruptError(f"unsupported Session record schema in {path}")
    kind = value["kind"]
    if not isinstance(kind, str) or kind not in {"interaction", "projection", "runtime"}:
        raise SessionCorruptError(f"unknown Session record kind in {path}")
    allowed = required | ({"projection"} if kind == "projection" else {"entry"})
    unknown = set(value).difference(allowed)
    if unknown:
        raise SessionCorruptError(f"Session record has unknown fields in {path}")
    sequence = value["sequence"]
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
        raise SessionCorruptError(f"invalid Session record sequence in {path}")
    return kind, sequence


def _incomplete_units(history: CanonicalHistory) -> tuple[SemanticUnit, ...]:
    return tuple(unit for unit in history.semantic_units(include_incomplete=True) if not unit.complete)


def _recoverable_incomplete_unit(unit: SemanticUnit) -> bool:
    """Return whether an incomplete unit can be a safely droppable tail."""

    calls = [entry.tool_call_id for entry in unit.entries if entry.kind is HistoryKind.TOOL_CALL]
    results = [entry.tool_call_id for entry in unit.entries if entry.kind is HistoryKind.TOOL_RESULT]
    if len(calls) != len(set(calls)) or len(results) != len(set(results)):
        return False
    if any(result_id not in calls for result_id in results):
        return False
    if results and not calls:
        return False
    return True


def _validate_history_append(history: CanonicalHistory, values: Sequence[HistoryEntry]) -> None:
    """Validate semantic boundaries before writing any history bytes."""

    current_units = history.semantic_units(include_incomplete=True)
    current_incomplete = _incomplete_units(history)
    if current_incomplete:
        pending = current_incomplete[0]
        if len(current_incomplete) != 1 or current_units[-1].unit_id != pending.unit_id:
            raise SessionFileError("history contains middle incomplete semantic corruption")
        if not _recoverable_incomplete_unit(pending):
            raise SessionFileError("history contains an invalid incomplete semantic unit")
        call_ids = {
            entry.tool_call_id
            for entry in pending.entries
            if entry.kind is HistoryKind.TOOL_CALL
        }
        result_ids = {
            entry.tool_call_id
            for entry in pending.entries
            if entry.kind is HistoryKind.TOOL_RESULT
        }
        for entry in values:
            if entry.kind is not HistoryKind.TOOL_RESULT:
                raise SessionFileError(
                    "only a matching ToolResult may follow an incomplete ToolCall group"
                )
            tool_call_id = entry.tool_call_id
            if tool_call_id not in call_ids or tool_call_id in result_ids:
                raise SessionFileError("ToolResult does not match the pending ToolCall group")
            result_ids.add(tool_call_id)

    candidate = history
    try:
        for entry in values:
            candidate = candidate.append(entry)
    except (TypeError, ValueError) as exc:
        raise SessionFileError("history append violates the canonical semantic boundary") from exc

    candidate_units = candidate.semantic_units(include_incomplete=True)
    candidate_incomplete = _incomplete_units(candidate)
    if not candidate_incomplete:
        return
    if (
        len(candidate_incomplete) != 1
        or candidate_units[-1].unit_id != candidate_incomplete[0].unit_id
    ):
        raise SessionFileError("history append would leave an incomplete unit in the middle")
    if not _recoverable_incomplete_unit(candidate_incomplete[0]):
        raise SessionFileError("history append would create an invalid incomplete semantic unit")


def _read_history(
    path: Path,
    session_id: str,
    *,
    recover_incomplete_tail: bool = True,
) -> tuple[CanonicalHistory, int, int, list[str]]:
    lines, valid_end, diagnostics = _read_jsonl_lines(path)
    expected_record = 1
    interactions: list[tuple[HistoryEntry, _ParsedLine]] = []
    projections: list[tuple[Projection, _ParsedLine]] = []
    for line in lines:
        kind, sequence = _validate_envelope(line.value, path=path)
        if kind == "runtime":
            raise SessionCorruptError(f"runtime record found in history log: {path}")
        if sequence != expected_record:
            raise SessionCorruptError(
                f"Session record sequence is not strict in {path}: expected {expected_record}, got {sequence}"
            )
        expected_record += 1
        try:
            if kind == "interaction":
                entry_value = line.value.get("entry")
                if not isinstance(entry_value, Mapping):
                    raise TypeError("interaction record entry must be a mapping")
                entry = HistoryEntry.from_dict(entry_value)
                if entry.session_id != session_id:
                    raise ValueError("interaction record belongs to another Session")
                interactions.append((entry, line))
            else:
                projection_value = line.value.get("projection")
                if not isinstance(projection_value, Mapping):
                    raise TypeError("projection record projection must be a mapping")
                projection = Projection.from_dict(projection_value)
                if projection.session_id != session_id:
                    raise ValueError("projection record belongs to another Session")
                projections.append((projection, line))
        except (TypeError, ValueError, KeyError) as exc:
            raise SessionCorruptError(f"invalid history record in {path}: {exc}") from exc

    history = CanonicalHistory(session_id)
    for entry, _line in interactions:
        try:
            history = history.append(entry)
        except (TypeError, ValueError) as exc:
            raise SessionCorruptError(f"invalid canonical History sequence in {path}") from exc

    dropped_start: int | None = None
    incomplete_start: int | None = None
    units = history.semantic_units(include_incomplete=True)
    incomplete_units = _incomplete_units(history)
    if incomplete_units:
        incomplete = incomplete_units[0]
        if len(incomplete_units) != 1 or units[-1].unit_id != incomplete.unit_id:
            raise SessionCorruptError(
                f"incomplete semantic unit in the middle of history: {path}"
            )
        if not _recoverable_incomplete_unit(incomplete):
            raise SessionCorruptError(
                f"incomplete semantic unit cannot be safely recovered: {path}"
            )
        try:
            incomplete_start = next(
                line.start
                for entry, line in interactions
                if entry.sequence >= incomplete.sequence_start
            )
        except StopIteration as exc:
            raise SessionCorruptError(
                f"incomplete semantic unit has no persisted boundary: {path}"
            ) from exc
        if any(line.start >= incomplete_start for _projection, line in projections):
            raise SessionCorruptError(
                f"Projection follows an incomplete semantic unit: {path}"
            )
        if recover_incomplete_tail:
            dropped_start = incomplete_start
            history = CanonicalHistory(
                session_id,
                tuple(entry for entry, line in interactions if line.start < dropped_start),
            )
            diagnostics = (*diagnostics, "ignored_incomplete_semantic_tail")

    if dropped_start is not None:
        valid_end = dropped_start
        projections = [(projection, line) for projection, line in projections if line.start < dropped_start]
    elif incomplete_units:
        diagnostics = (*diagnostics, "incomplete_semantic_tail_pending")

    active_projection: Projection | None = None
    for projection, line in projections:
        if line.end > valid_end:
            continue
        if projection.sequence_end > history.last_sequence:
            raise SessionCorruptError(f"projection references unwritten History in {path}")
        if active_projection is not None and projection.revision <= active_projection.revision:
            raise SessionCorruptError(f"Projection revision is not increasing in {path}")
        for unit in projection.units:
            for entry in unit.entries:
                if entry.sequence > history.last_sequence or history.entries[entry.sequence - 1] != entry:
                    raise SessionCorruptError(f"projection does not match canonical History in {path}")
        active_projection = projection

    last_record_sequence = 0
    for line in lines:
        if line.end <= valid_end:
            last_record_sequence = _validate_envelope(line.value, path=path)[1]
    return history, valid_end, last_record_sequence, list(diagnostics)


def _read_projection_from_history(path: Path, history: CanonicalHistory, session_id: str) -> Projection | None:
    # Projection recovery is performed in _read_history.  Re-reading only the
    # final valid projection keeps the public _read_history return compact and
    # makes deletion of runtime.jsonl irrelevant to semantic recovery.
    lines, valid_end, _diagnostics = _read_jsonl_lines(path)
    active: Projection | None = None
    expected = 1
    for line in lines:
        kind, sequence = _validate_envelope(line.value, path=path)
        if line.end > valid_end:
            break
        if sequence != expected:
            break
        expected += 1
        if kind != "projection":
            continue
        value = line.value.get("projection")
        if not isinstance(value, Mapping):
            raise SessionCorruptError(f"projection record projection must be a mapping: {path}")
        try:
            candidate = Projection.from_dict(value)
        except (TypeError, ValueError, KeyError) as exc:
            raise SessionCorruptError(f"invalid projection record in {path}") from exc
        if candidate.session_id != session_id or candidate.sequence_end > history.last_sequence:
            raise SessionCorruptError(f"projection references unwritten History in {path}")
        for unit in candidate.units:
            for entry in unit.entries:
                if entry.sequence > history.last_sequence or history.entries[entry.sequence - 1] != entry:
                    raise SessionCorruptError(f"projection does not match canonical History in {path}")
        active = candidate
    return active


def _read_runtime(path: Path) -> tuple[RuntimeLog, int, int, list[str]]:
    lines, valid_end, diagnostics = _read_jsonl_lines(path)
    expected = 1
    values: list[RuntimeLogEntry] = []
    for line in lines:
        kind, sequence = _validate_envelope(line.value, path=path)
        if kind != "runtime":
            raise SessionCorruptError(f"non-runtime record found in runtime log: {path}")
        if sequence != expected:
            raise SessionCorruptError(
                f"runtime record sequence is not strict in {path}: expected {expected}, got {sequence}"
            )
        expected += 1
        value = line.value.get("entry")
        if not isinstance(value, Mapping):
            raise SessionCorruptError(f"runtime record entry must be a mapping: {path}")
        try:
            values.append(
                RuntimeLogEntry(
                    kind=value["kind"],
                    payload=value.get("payload", {}),
                    created_at=value["created_at"],
                )
            )
        except (TypeError, ValueError, KeyError) as exc:
            raise SessionCorruptError(f"invalid runtime record in {path}") from exc
    return RuntimeLog(tuple(values)), valid_end, expected - 1, list(diagnostics)


__all__ = [
    "HistoryAppendOutcome",
    "SESSION_RECORD_SCHEMA_VERSION",
    "SESSION_SCHEMA_VERSION",
    "SessionBusyError",
    "SessionCorruptError",
    "SessionDurabilityUnknownError",
    "SessionFileError",
    "SessionFileStore",
    "SessionMetadata",
    "SessionNotFoundError",
    "SessionSnapshot",
    "SessionWriter",
    "SessionWriterRequiredError",
]
