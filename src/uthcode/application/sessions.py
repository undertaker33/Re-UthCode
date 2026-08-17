"""Application-owned Session lifecycle and Instruction State composition."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from uthcode.core.history import HistoryEntry, HistoryKind, Projection, RuntimeLogEntry
from uthcode.integrations.session_files import (
    SessionFileStore,
    SessionFileError,
    SessionMetadata,
    SessionSnapshot,
    SessionWriter,
)

from .instructions import InstructionError, InstructionLoader, InstructionStateMetadata


class SessionActiveError(RuntimeError):
    """A second Application Session was opened before the active one closed."""


class SessionOperationError(RuntimeError):
    """Stable Application error for command-level Session failures."""

    def __init__(self, kind: str, *, session_id: str | None = None) -> None:
        if kind not in {"busy", "corrupt", "unknown", "storage"}:
            raise ValueError("unknown Session operation error kind")
        self.kind = kind
        self.session_id = session_id
        super().__init__(kind)


@dataclass(frozen=True, slots=True)
class SessionCatalogEntry:
    """Application-owned, display-safe data for the independent TUI Picker."""

    session_id: str
    project_key: str
    last_used_at: str
    preview: str = ""
    projection_revision: int | None = None
    history_entries: int = 0
    corrupt: bool = False


@dataclass(slots=True)
class _StagedSession:
    """A lock-held target that has not become the Application active Session."""

    session: "ApplicationSession"
    instruction_loader: InstructionLoader | None


class ApplicationSession:
    """One lock-held Application Session at a durable semantic boundary."""

    __slots__ = ("_service", "_writer", "_closed")

    def __init__(self, service: "ApplicationSessionService", writer: SessionWriter) -> None:
        self._service = service
        self._writer = writer
        self._closed = False

    def __enter__(self) -> "ApplicationSession":
        self._require_open()
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        del exc_type, exc, tb
        self.close()

    @property
    def session_id(self) -> str:
        return self.snapshot.session_id

    @property
    def project_key(self) -> str:
        return self.snapshot.project_key

    @property
    def snapshot(self) -> SessionSnapshot:
        self._require_open()
        return self._writer.snapshot

    @property
    def metadata(self) -> SessionMetadata:
        return self.snapshot.metadata

    @property
    def history(self):
        return self.snapshot.history

    @property
    def projection(self):
        return self.snapshot.projection

    @property
    def runtime_log(self):
        return self.snapshot.runtime_log

    @property
    def instruction_state(self) -> InstructionStateMetadata:
        return InstructionStateMetadata.from_dict(self.metadata.instruction_state)

    @property
    def recovery_diagnostics(self) -> tuple[str, ...]:
        return self.snapshot.recovery_diagnostics

    def append_history(self, entries: HistoryEntry | Sequence[HistoryEntry]) -> SessionSnapshot:
        self._require_open()
        return self._writer.append_history(entries)

    def append_projection(self, projection: Projection) -> SessionSnapshot:
        self._require_open()
        return self._writer.append_projection(projection)

    def append_runtime(self, entry: RuntimeLogEntry) -> SessionSnapshot:
        self._require_open()
        return self._writer.append_runtime(entry)

    def persist_tool_result(self, content: str, *, policy: object | None = None) -> object:
        self._require_open()
        return self._writer.persist_tool_result(content, policy=policy)

    def read_tool_result(
        self,
        ref: str,
        *,
        offset: int = 0,
        limit: int | None = None,
        policy: object | None = None,
    ) -> object:
        self._require_open()
        return self._writer.read_tool_result(
            ref,
            offset=offset,
            limit=limit,
            policy=policy,
        )

    def persist_instruction_state(self) -> SessionMetadata:
        self._require_open()
        return self._service._sync_instruction_state(self._writer)

    def close(self) -> None:
        if self._closed:
            return
        # Sync is deliberately outside the release/finalize step.  If it
        # fails, this Session remains open and _active still points at it so a
        # transactional Session switch can abort without losing the writer.
        self._prepare_close()
        self._release_after_sync()

    def _prepare_close(self) -> None:
        """Persist close-time state without changing lifecycle ownership."""

        self._require_open()
        # Persist the latest activated directory scopes before releasing the
        # process-held writer.  A caller may still use the explicit persist
        # method for an earlier durable boundary.
        self._service._sync_instruction_state(self._writer)

    def _release_after_sync(self) -> None:
        """Finalize a Session after its close-time sync has succeeded."""

        if self._closed:
            return
        self._writer.close()
        self._closed = True
        self._service._forget(self)

    def _close_staged(self) -> None:
        """Release a failed staged writer without syncing current state."""

        if self._closed:
            return
        self._closed = True
        try:
            self._writer.close()
        finally:
            self._service._forget(self)

    def _require_open(self) -> None:
        if self._closed:
            raise RuntimeError("ApplicationSession is closed")


class ApplicationSessionService:
    """Create/resume/catalog Sessions for one Application project key."""

    def __init__(
        self,
        *,
        storage_root: str | Path,
        project_key: str,
        instruction_loader: InstructionLoader | None,
        store: SessionFileStore | None = None,
    ) -> None:
        self.store = store or SessionFileStore(storage_root)
        if not isinstance(self.store, SessionFileStore):
            raise TypeError("store must be a SessionFileStore or None")
        if not isinstance(project_key, str) or not project_key.strip():
            raise ValueError("project_key must be a non-empty string")
        if instruction_loader is not None and not isinstance(instruction_loader, InstructionLoader):
            raise TypeError("instruction_loader must be InstructionLoader or None")
        self.project_key = project_key
        self.instruction_loader = instruction_loader
        self._active: ApplicationSession | None = None
        self._last_operation: dict[str, object] | None = None

    @property
    def active_session(self) -> ApplicationSession | None:
        """Return the one lock-held Session, if the Application opened one."""

        return self._active

    def public_diagnostics(self) -> dict[str, object]:
        """Return Session recovery facts without storage paths or payloads."""

        active = self._active
        recovery = list(active.recovery_diagnostics) if active is not None else []
        last = None if self._last_operation is None else dict(self._last_operation)
        return {
            "schema_version": 1,
            "status": "active" if active is not None else "idle",
            "active": active is not None,
            "active_session_id": active.session_id if active is not None else None,
            "recovery_diagnostics": recovery,
            "last_operation": last,
            "busy": bool(isinstance(last, Mapping) and last.get("kind") == "busy"),
        }

    def create_session(self, session_id: str | None = None) -> ApplicationSession:
        self._require_no_active_session()
        if self.instruction_loader is not None:
            self.instruction_loader.reset_for_new_session()
            result = self.instruction_loader.load_session(strict=False)
            state = result.instruction_state.to_dict()
        else:
            state = InstructionStateMetadata().to_dict()
        metadata = self.store.create_session(
            session_id,
            project_key=self.project_key,
            instruction_state=state,
        )
        writer = self.store.open_writer(
            metadata.session_id,
            expected_project_key=self.project_key,
        )
        try:
            writer.__enter__()
        except Exception:
            writer.close()
            raise
        session = ApplicationSession(self, writer)
        self._active = session
        self._record_operation(
            "create",
            "success",
            session.session_id,
            recovery=session.recovery_diagnostics,
        )
        return session

    def create_session_for_command(
        self,
        session_id: str | None = None,
    ) -> ApplicationSession:
        """Map Integration file failures to the Application command boundary."""

        try:
            session = self._commit_staged(self._stage_create_session(session_id))
            self._record_operation(
                "create",
                "success",
                session.session_id,
                recovery=session.recovery_diagnostics,
            )
            return session
        except SessionFileError as exc:
            error = _session_operation_error(exc, session_id=session_id)
            self._record_operation("create", "failed", session_id, kind=error.kind)
            raise error from exc
        except (InstructionError, TypeError, ValueError) as exc:
            self._record_operation("create", "failed", session_id, kind="storage")
            raise SessionOperationError("storage", session_id=session_id) from exc

    def resume_session(self, session_id: str) -> ApplicationSession:
        self._require_no_active_session()
        writer = self.store.open_writer(
            session_id,
            expected_project_key=self.project_key,
        )
        try:
            writer.__enter__()
            if self.instruction_loader is not None:
                state = InstructionStateMetadata.from_dict(writer.snapshot.metadata.instruction_state)
                self.instruction_loader.rebuild_from_metadata(state, strict=False)
                self._sync_instruction_state(writer)
            else:
                writer.touch()
        except Exception:
            writer.close()
            raise
        session = ApplicationSession(self, writer)
        self._active = session
        self._record_operation(
            "resume",
            "success",
            session.session_id,
            recovery=session.recovery_diagnostics,
        )
        return session

    def resume_session_for_command(self, session_id: str) -> ApplicationSession:
        """Resume with a stable error category safe for Slash command output."""

        try:
            active = self._active
            if active is not None and active.session_id == session_id:
                # The current writer already owns this target.  Re-opening it
                # would require releasing the very lock that proves it is
                # active, so rebuild a candidate loader under that existing
                # lock and commit only after the filesystem read succeeds.
                session = self._refresh_active_session_for_resume(active)
            else:
                session = self._commit_staged(self._stage_resume_session(session_id))
            self._record_operation(
                "resume",
                "success",
                session.session_id,
                recovery=session.recovery_diagnostics,
            )
            return session
        except SessionFileError as exc:
            error = _session_operation_error(exc, session_id=session_id)
            self._record_operation("resume", "failed", session_id, kind=error.kind)
            raise error from exc
        except (InstructionError, TypeError, ValueError) as exc:
            self._record_operation("resume", "failed", session_id, kind="corrupt")
            raise SessionOperationError("corrupt", session_id=session_id) from exc

    def list_sessions(self, *, project_key: str | None = None) -> tuple[SessionMetadata, ...]:
        key = self.project_key if project_key is None else project_key
        return self.store.list_metadata(project_key=key)

    def list_catalog(self) -> tuple[SessionCatalogEntry, ...]:
        """Return same-project Sessions with durable ordering and bounded previews."""

        entries: list[SessionCatalogEntry] = []
        for metadata in self.list_sessions():
            try:
                snapshot = self.read_session(metadata.session_id)
            except SessionFileError:
                # Keep the selectable row visible so an explicit resume can
                # report the stable corrupt/unknown error instead of silently
                # hiding a durable Session from the user.
                entries.append(
                    SessionCatalogEntry(
                        session_id=metadata.session_id,
                        project_key=metadata.project_key,
                        last_used_at=metadata.last_used_at,
                        preview="[Session recovery unavailable]",
                        corrupt=True,
                    )
                )
                continue
            entries.append(
                SessionCatalogEntry(
                    session_id=metadata.session_id,
                    project_key=metadata.project_key,
                    last_used_at=metadata.last_used_at,
                    preview=_first_user_preview(snapshot),
                    projection_revision=(
                        snapshot.projection.revision
                        if snapshot.projection is not None
                        else None
                    ),
                    history_entries=len(snapshot.history.entries),
                )
            )
        return tuple(entries)

    def read_session(self, session_id: str) -> SessionSnapshot:
        return self.store.read_session(session_id, expected_project_key=self.project_key)

    def close(self) -> None:
        session = self._active
        if session is not None:
            session.close()

    def _require_no_active_session(self) -> None:
        if self._active is not None:
            raise SessionActiveError(
                f"Application Session {self._active.session_id!r} is active; close it before opening another"
            )

    def _stage_create_session(self, session_id: str | None) -> _StagedSession:
        """Prepare a new Session while leaving the current one untouched."""

        candidate_loader: InstructionLoader | None = None
        if self.instruction_loader is not None:
            candidate_loader = self.instruction_loader.fork_for_session()
            candidate_loader.reset_for_new_session()
            result = candidate_loader.load_session(strict=False)
            state = result.instruction_state.to_dict()
        else:
            state = InstructionStateMetadata().to_dict()
        metadata = self.store.create_session(
            session_id,
            project_key=self.project_key,
            instruction_state=state,
        )
        writer = self.store.open_writer(
            metadata.session_id,
            expected_project_key=self.project_key,
        )
        try:
            writer.__enter__()
        except Exception:
            writer.close()
            raise
        return _StagedSession(ApplicationSession(self, writer), candidate_loader)

    def _stage_resume_session(self, session_id: str) -> _StagedSession:
        """Lock and validate a target before touching the active Session."""

        writer = self.store.open_writer(
            session_id,
            expected_project_key=self.project_key,
        )
        candidate_loader: InstructionLoader | None = None
        try:
            writer.__enter__()
            if self.instruction_loader is not None:
                candidate_loader = self.instruction_loader.fork_for_session()
                state = InstructionStateMetadata.from_dict(
                    writer.snapshot.metadata.instruction_state
                )
                candidate_loader.rebuild_from_metadata(state, strict=False)
                # Persist only the target's freshly rebuilt metadata.  The
                # current loader is not changed until _commit_staged().
                writer.update_instruction_state(
                    candidate_loader.instruction_state.to_dict()
                )
            else:
                writer.touch()
        except Exception:
            writer.close()
            raise
        return _StagedSession(ApplicationSession(self, writer), candidate_loader)

    def _refresh_active_session_for_resume(
        self,
        active: ApplicationSession,
    ) -> ApplicationSession:
        """Refresh an already-held target without releasing its writer lock."""

        if self.instruction_loader is None:
            active._writer.touch()
            return active
        candidate_loader = self.instruction_loader.fork_for_session()
        state = InstructionStateMetadata.from_dict(
            active._writer.snapshot.metadata.instruction_state
        )
        candidate_loader.rebuild_from_metadata(state, strict=False)
        active._writer.update_instruction_state(
            candidate_loader.instruction_state.to_dict()
        )
        self.instruction_loader.adopt_session_state(candidate_loader)
        return active

    def _commit_staged(self, staged: _StagedSession) -> ApplicationSession:
        """Commit a fully locked/recovered target and release the old writer."""

        old = self._active
        try:
            if old is not None:
                # All target I/O and Instruction State rebuilding happened
                # before this point.  Prepare the old close while it is still
                # active; a sync failure leaves its writer and lifecycle
                # ownership untouched.
                old._prepare_close()
            if self.instruction_loader is not None and staged.instruction_loader is not None:
                self.instruction_loader.adopt_session_state(staged.instruction_loader)
            self._active = staged.session
            if old is not None:
                # The old writer was already synchronized before the loader
                # changed.  Release it without a second sync under the target
                # Instruction State.
                old._release_after_sync()
            return staged.session
        except Exception:
            if old is not None and self._active is staged.session:
                self._active = old
            staged.session._close_staged()
            raise

    def _sync_instruction_state(self, writer: SessionWriter) -> SessionMetadata:
        if self.instruction_loader is None:
            return writer.touch()
        return writer.update_instruction_state(self.instruction_loader.instruction_state.to_dict())

    def _forget(self, session: ApplicationSession) -> None:
        if self._active is session:
            self._active = None

    def _record_operation(
        self,
        operation: str,
        status: str,
        session_id: str | None,
        *,
        kind: str | None = None,
        recovery: Sequence[str] = (),
    ) -> None:
        value: dict[str, object] = {
            "operation": operation,
            "status": status,
            "session_id": session_id,
            "recovery_diagnostics": [str(item) for item in recovery],
        }
        if kind is not None:
            value["kind"] = kind
        self._last_operation = value


__all__ = [
    "ApplicationSession",
    "ApplicationSessionService",
    "SessionCatalogEntry",
    "SessionActiveError",
    "SessionOperationError",
]


def _first_user_preview(snapshot: SessionSnapshot, *, limit: int = 160) -> str:
    """Extract only the first User Message and keep it to one display line."""

    for entry in snapshot.history.entries:
        if entry.kind is not HistoryKind.USER_MESSAGE:
            continue
        value = _preview_value(entry.payload)
        if value:
            normalized = " ".join(value.split())
            if len(normalized) > limit:
                return normalized[: max(1, limit - 1)].rstrip() + "…"
            return normalized
        break
    return "(no user message)"


def _preview_value(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        for key in ("text", "content", "message", "part", "parts", "input"):
            if key in value:
                result = _preview_value(value[key])
                if result:
                    return result
        return ""
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return " ".join(
            result
            for item in value
            if (result := _preview_value(item))
        )
    return ""


def _session_operation_error(
    exc: SessionFileError,
    *,
    session_id: str | None,
) -> SessionOperationError:
    from uthcode.integrations.session_files import (
        SessionBusyError,
        SessionCorruptError,
        SessionNotFoundError,
    )

    if isinstance(exc, SessionBusyError):
        return SessionOperationError("busy", session_id=session_id)
    if isinstance(exc, SessionCorruptError):
        return SessionOperationError("corrupt", session_id=session_id)
    if isinstance(exc, SessionNotFoundError):
        return SessionOperationError("unknown", session_id=session_id)
    return SessionOperationError("storage", session_id=session_id)
