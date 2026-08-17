"""Application-owned Session lifecycle and Instruction State composition."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from uthcode.core.history import HistoryEntry, Projection, RuntimeLogEntry
from uthcode.integrations.session_files import (
    SessionFileStore,
    SessionMetadata,
    SessionSnapshot,
    SessionWriter,
)

from .instructions import InstructionLoader, InstructionStateMetadata


class SessionActiveError(RuntimeError):
    """A second Application Session was opened before the active one closed."""


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
        self._closed = True
        try:
            # Persist the latest activated directory scopes before releasing
            # the process-held writer.  A caller may still use the explicit
            # persist method for an earlier durable boundary.
            self._service._sync_instruction_state(self._writer)
        finally:
            self._writer.close()
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

    @property
    def active_session(self) -> ApplicationSession | None:
        """Return the one lock-held Session, if the Application opened one."""

        return self._active

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
        return session

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
        return session

    def list_sessions(self, *, project_key: str | None = None) -> tuple[SessionMetadata, ...]:
        key = self.project_key if project_key is None else project_key
        return self.store.list_metadata(project_key=key)

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

    def _sync_instruction_state(self, writer: SessionWriter) -> SessionMetadata:
        if self.instruction_loader is None:
            return writer.touch()
        return writer.update_instruction_state(self.instruction_loader.instruction_state.to_dict())

    def _forget(self, session: ApplicationSession) -> None:
        if self._active is session:
            self._active = None


__all__ = [
    "ApplicationSession",
    "ApplicationSessionService",
    "SessionActiveError",
]
