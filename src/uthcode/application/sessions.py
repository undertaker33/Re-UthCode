"""Application-owned Session lifecycle and Instruction State composition."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from threading import Lock

from uthcode.core.agent_events import FailureReason, TerminationReason
from uthcode.core.history import (
    ActiveCheckpoint,
    EpochMacroSummary,
    SemanticEntry,
    TranscriptBoundaryError,
    TranscriptEntry,
    TranscriptKind,
    TranscriptRef,
)
from uthcode.core.provider import (
    Message,
    ReasoningPart,
    TextPart,
    ToolCallPart,
    ToolResultPart,
)
from uthcode.core.planning import parse_propose_plan_arguments
from uthcode.integrations.session_files import (
    TimelineAppendOutcome,
    TranscriptAppendOutcome,
    SessionFileStore,
    SessionFileError,
    SessionMetadata,
    SessionSnapshot,
    SessionWriter,
    normalize_session_title,
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


_REPLAY_KINDS = frozenset(
    {"user", "steering", "reasoning", "assistant", "tool", "plan", "failure"}
)
_REPLAY_TOOL_STATUSES = frozenset(
    {
        "succeeded",
        "success",
        "failed",
        "error",
        "cancelled",
        "unknown",
        "denied",
        "skipped",
        "finished",
    }
)


@dataclass(frozen=True, slots=True)
class SessionReplayRecord:
    """One durable, interface-neutral record safe for Session hydrate."""

    session_id: str
    sequence: int
    turn_id: str
    kind: str
    text: str = ""
    tool_name: str | None = None
    tool_call_id: str | None = None
    status: str | None = None
    is_error: bool = False
    created_at: str | None = None
    title: str | None = None
    termination_reason: str | None = None
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.session_id, str) or not self.session_id.strip():
            raise ValueError("replay session_id must be a non-empty string")
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int):
            raise TypeError("replay sequence must be an integer")
        if self.sequence < 1:
            raise ValueError("replay sequence must be positive")
        if not isinstance(self.turn_id, str) or not self.turn_id.strip():
            raise ValueError("replay turn_id must be a non-empty string")
        if not isinstance(self.kind, str) or self.kind not in _REPLAY_KINDS:
            raise ValueError("unsupported replay record kind")
        if not isinstance(self.text, str):
            raise TypeError("replay text must be a string")
        for value, field_name in (
            (self.tool_name, "tool_name"),
            (self.tool_call_id, "tool_call_id"),
            (self.status, "status"),
            (self.created_at, "created_at"),
            (self.termination_reason, "termination_reason"),
            (self.failure_reason, "failure_reason"),
        ):
            if value is not None and not isinstance(value, str):
                raise TypeError(f"replay {field_name} must be a string or None")
        if self.tool_name is not None and not self.tool_name.strip():
            raise ValueError("replay tool_name must be non-empty when provided")
        if self.tool_call_id is not None and not self.tool_call_id.strip():
            raise ValueError("replay tool_call_id must be non-empty when provided")
        if self.status is not None and self.status not in _REPLAY_TOOL_STATUSES:
            raise ValueError("unsupported replay tool status")
        if self.termination_reason is not None:
            TerminationReason(self.termination_reason)
        if self.failure_reason is not None:
            FailureReason(self.failure_reason)
        if self.kind == "failure" and self.termination_reason is None:
            raise ValueError("failure replay requires termination_reason")
        if not isinstance(self.is_error, bool):
            raise TypeError("replay is_error must be a boolean")
        if self.title is not None:
            object.__setattr__(self, "title", normalize_session_title(self.title))

    def to_dict(self) -> dict[str, object]:
        """Serialize only the bounded replay contract, never raw parts."""

        value: dict[str, object] = {
            "session_id": self.session_id,
            "sequence": self.sequence,
            "turn_id": self.turn_id,
            "kind": self.kind,
            "text": self.text,
            "is_error": self.is_error,
        }
        for field_name in (
            "tool_name",
            "tool_call_id",
            "status",
            "created_at",
            "title",
            "termination_reason",
            "failure_reason",
        ):
            field_value = getattr(self, field_name)
            if field_value is not None:
                value[field_name] = field_value
        return value


SessionReplayBuilder = Callable[
    [SessionSnapshot], Iterable[SessionReplayRecord]
]


@dataclass(frozen=True, slots=True)
class SessionCatalogEntry:
    """Application-owned, display-safe data for the independent TUI Picker."""

    session_id: str
    project_key: str
    last_used_at: str
    preview: str = ""
    timeline_checkpoint_id: str | None = None
    transcript_entries: int = 0
    corrupt: bool = False
    title: str | None = None
    model_ref: str | None = None


@dataclass(frozen=True, slots=True)
class SessionMutation:
    """Minimal Application projection returned by Session mutations."""

    session_id: str
    project_key: str
    title: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.session_id, str) or not self.session_id.strip():
            raise ValueError("session mutation session_id must be a non-empty string")
        if not isinstance(self.project_key, str) or not self.project_key.strip():
            raise ValueError("session mutation project_key must be a non-empty string")
        if self.title is not None:
            object.__setattr__(self, "title", normalize_session_title(self.title))

    def to_dict(self) -> dict[str, object]:
        return {
            "session_id": self.session_id,
            "project_key": self.project_key,
            "title": self.title,
        }


@dataclass(slots=True)
class _StagedSession:
    """A lock-held target that has not become the Application active Session."""

    session: "ApplicationSession"
    instruction_loader: InstructionLoader | None


class ApplicationSession:
    """One lock-held Application Session at a durable semantic boundary."""

    __slots__ = ("_service", "_writer", "_closed", "_replay")

    def __init__(
        self,
        service: "ApplicationSessionService",
        writer: SessionWriter,
        replay: Sequence[SessionReplayRecord] = (),
    ) -> None:
        self._service = service
        self._writer = writer
        self._closed = False
        self._replay = _normalize_replay(replay, writer.snapshot.session_id)

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
    def title(self) -> str | None:
        return self.snapshot.title

    @property
    def model_ref(self) -> str | None:
        """Return the durable model preference for this Session."""

        return self.metadata.model_ref

    def persist_model_ref(self, model_ref: str | None) -> SessionMetadata:
        """Persist a model selection while this Session writer is held."""

        self._require_writable()
        return self._writer.update_model_ref(model_ref)

    @property
    def snapshot(self) -> SessionSnapshot:
        self._require_open()
        return self._writer.snapshot

    @property
    def metadata(self) -> SessionMetadata:
        return self.snapshot.metadata

    @property
    def transcript(self):
        return self.snapshot.transcript

    @property
    def timeline(self):
        return self.snapshot.timeline

    @property
    def instruction_state(self) -> InstructionStateMetadata:
        return InstructionStateMetadata.from_dict(self.metadata.instruction_state)

    @property
    def replay(self) -> tuple[SessionReplayRecord, ...]:
        """Return the safe replay prepared at the last Session boundary."""

        self._require_open()
        return self._replay

    def _set_replay(self, replay: Sequence[SessionReplayRecord]) -> None:
        self._require_open()
        self._replay = _normalize_replay(replay, self.session_id)

    @property
    def recovery_diagnostics(self) -> tuple[str, ...]:
        return self.snapshot.recovery_diagnostics

    @property
    def durability_unknown(self) -> bool:
        """Whether this active Session writer is quarantined."""

        self._require_open()
        return self._writer.durability_unknown

    def _require_writable(self) -> None:
        self._require_open()
        self._writer._require_writable()

    def _quarantine_unknown_durability(self) -> None:
        self._require_open()
        self._writer.quarantine_unknown_durability()

    def append_transcript(
        self,
        entries: TranscriptEntry | Sequence[TranscriptEntry],
    ) -> TranscriptAppendOutcome:
        self._require_writable()
        return self._writer.append_transcript(entries)

    def append_timeline_transaction(
        self,
        derived: Sequence[SemanticEntry | EpochMacroSummary],
        checkpoint: ActiveCheckpoint,
    ) -> TimelineAppendOutcome:
        self._require_writable()
        return self._writer.append_timeline_transaction(derived, checkpoint)

    def append_timeline(self, timeline) -> TimelineAppendOutcome:
        self._require_writable()
        return self._writer.append_timeline(timeline)

    def persist_tool_result(self, content: str, *, policy: object | None = None) -> object:
        self._require_writable()
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

    def read_transcript(self, ref: TranscriptRef) -> tuple[TranscriptEntry, ...]:
        """Read one exact complete raw Transcript reference without mutation."""

        self._require_open()
        if not isinstance(ref, TranscriptRef) or ref.session_id != self.session_id:
            raise TranscriptBoundaryError("Transcript ref does not belong to this Session")
        return self.snapshot.transcript.select(
            ref.sequence_start,
            ref.sequence_end,
            complete_only=True,
        )

    def persist_instruction_state(self) -> SessionMetadata:
        self._require_writable()
        return self._service._sync_instruction_state(self._writer)

    def close(self) -> None:
        if self._closed:
            return
        if self._writer.durability_unknown:
            self._release_after_quarantine()
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

    def _release_after_quarantine(self) -> None:
        """Release an unknown writer without performing another mutation."""

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
        # Move receipts are deliberately process-local.  They allow only the
        # Application instance that completed a move to retry the same
        # converged request; restart recovery relies on the durable owner
        # instead of inventing a second journal or registry.
        self._move_lock = Lock()
        self._move_receipts: dict[tuple[str, str], SessionMutation] = {}

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
            "active_session_title": active.title if active is not None else None,
            "recovery_diagnostics": recovery,
            "last_operation": last,
            "busy": bool(isinstance(last, Mapping) and last.get("kind") == "busy"),
        }

    def create_session(
        self,
        session_id: str | None = None,
        *,
        model_ref: str | None = None,
    ) -> ApplicationSession:
        self._require_no_active_session()
        # Keep Loader state transactional just like the command path: strict
        # include failure must not clear or partially replace the current
        # loader before a Session and its metadata are committed.
        staged = self._stage_create_session(session_id, model_ref=model_ref)
        session = self._commit_staged(staged)
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
        *,
        model_ref: str | None = None,
    ) -> ApplicationSession:
        """Map Integration file failures to the Application command boundary."""

        try:
            session = self._commit_staged(
                self._stage_create_session(session_id, model_ref=model_ref)
            )
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

    def resume_session(
        self,
        session_id: str,
        *,
        replay_builder: SessionReplayBuilder | None = None,
    ) -> ApplicationSession:
        self._require_no_active_session()
        # Use the same staged loader boundary as the command path.  A strict
        # include failure must not leave a previously active instruction
        # prefix installed on the Application while this target is rejected.
        staged = self._stage_resume_session(
            session_id,
            replay_builder=replay_builder,
        )
        session = self._commit_staged(staged)
        self._record_operation(
            "resume",
            "success",
            session.session_id,
            recovery=session.recovery_diagnostics,
        )
        return session

    def resume_session_for_command(
        self,
        session_id: str,
        *,
        replay_builder: SessionReplayBuilder | None = None,
    ) -> ApplicationSession:
        """Resume with a stable error category safe for Slash command output."""

        try:
            active = self._active
            if active is not None and active.session_id == session_id:
                # The current writer already owns this target.  Re-opening it
                # would require releasing the very lock that proves it is
                # active, so rebuild a candidate loader under that existing
                # lock and commit only after the filesystem read succeeds.
                session = self._refresh_active_session_for_resume(
                    active,
                    replay_builder=replay_builder,
                )
            else:
                session = self._commit_staged(
                    self._stage_resume_session(
                        session_id,
                        replay_builder=replay_builder,
                    )
                )
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

    def rename_session(self, session_id: str, title: str) -> SessionMutation:
        """Persist a Session title without rewriting its durable history."""

        # Validate before opening a writer so invalid input cannot create a
        # transient lock or change last-used state.
        normalized_title = normalize_session_title(title)
        active = self._active
        try:
            if active is not None and active.session_id == session_id:
                metadata = active._writer.update_title(normalized_title)
                # A resumed Application Session keeps its safe replay in
                # memory. Refresh only that projection so a rename is
                # immediately visible without touching durable history.
                active._set_replay(
                    tuple(
                        replace(record, title=metadata.title)
                        for record in active.replay
                    )
                )
                return _session_mutation(metadata)
            with self.store.open_writer(
                session_id,
                expected_project_key=self.project_key,
            ) as writer:
                return _session_mutation(writer.update_title(normalized_title))
        except SessionFileError as exc:
            raise _session_operation_error(exc, session_id=session_id) from exc
        except OSError as exc:
            raise SessionOperationError("storage", session_id=session_id) from exc

    def move_session(self, session_id: str, target_project_key: str) -> SessionMutation:
        """Move a Session while preserving the writer ownership invariant.

        An open idle Session already has the only writer lock that can safely
        update its metadata.  Synchronize close-time state and perform the
        membership update under that lock, then release the source owner only
        after the update succeeds.  Active Turn rejection remains the Bridge
        boundary; this service deliberately has no second Turn state machine.
        """

        target = _canonical_project_key(target_project_key)
        receipt_key = (session_id, target)
        with self._move_lock:
            active = self._active
            if active is not None and active.session_id == session_id:
                # A target equal to the current owner is a safe no-op.  Still
                # synchronize close-time state so this boundary has the same
                # metadata durability as an ordinary move.
                try:
                    active._prepare_close()
                    if active.project_key == target:
                        result = _session_mutation(active._writer.metadata)
                        self._move_receipts[receipt_key] = result
                        self._record_operation("move", "success", session_id)
                        return result
                    if active.project_key != self.project_key:
                        raise SessionOperationError("unknown", session_id=session_id)
                    result = _session_mutation(active._writer.update_project_key(target))
                    # The metadata update is durable before ownership is
                    # released.  No optimistic source/target swap is exposed
                    # while the writer still belongs to this Application.
                    active._release_after_sync()
                except SessionOperationError as exc:
                    self._record_operation("move", "failed", session_id, kind=exc.kind)
                    raise
                except SessionFileError as exc:
                    error = _session_operation_error(exc, session_id=session_id)
                    self._record_operation("move", "failed", session_id, kind=error.kind)
                    raise error from exc
                except OSError as exc:
                    error = SessionOperationError("storage", session_id=session_id)
                    self._record_operation("move", "failed", session_id, kind=error.kind)
                    raise error from exc
                except Exception as exc:
                    error = SessionOperationError("storage", session_id=session_id)
                    self._record_operation("move", "failed", session_id, kind=error.kind)
                    raise error from exc
                self._move_receipts[receipt_key] = result
                self._record_operation("move", "success", session_id)
                return result
            receipt = self._move_receipts.get(receipt_key)
            if receipt is not None:
                # Re-open under the writer lock before honoring the receipt so
                # a concurrent move cannot make an old success look current.
                try:
                    with self.store.open_writer(
                        session_id,
                        expected_project_key=target,
                    ) as writer:
                        if writer.metadata.project_key != target:
                            raise SessionOperationError(
                                "unknown",
                                session_id=session_id,
                            )
                        refreshed = _session_mutation(writer.metadata)
                        self._move_receipts[receipt_key] = refreshed
                        return refreshed
                except SessionOperationError:
                    raise
                except SessionFileError as exc:
                    raise _session_operation_error(exc, session_id=session_id) from exc
                except OSError as exc:
                    raise SessionOperationError("storage", session_id=session_id) from exc
            try:
                with self.store.open_writer(
                    session_id,
                    expected_project_key=self.project_key,
                ) as writer:
                    # A Session already owned by this Application's project is
                    # a safe no-op and becomes a receipt for future retries.
                    result = _session_mutation(
                        writer.metadata
                        if writer.metadata.project_key == target
                        else writer.update_project_key(target)
                    )
            except SessionOperationError:
                raise
            except SessionFileError as exc:
                raise _session_operation_error(exc, session_id=session_id) from exc
            except OSError as exc:
                raise SessionOperationError("storage", session_id=session_id) from exc
            self._move_receipts[receipt_key] = result
            return result

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
                        title=metadata.title,
                        model_ref=metadata.model_ref,
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
                    title=metadata.title,
                    model_ref=metadata.model_ref,
                    preview=_first_user_preview(snapshot),
                    timeline_checkpoint_id=(
                        snapshot.timeline.active_checkpoint.turn_id
                        if snapshot.timeline.active_checkpoint is not None
                        else None
                    ),
                    transcript_entries=len(snapshot.transcript.entries),
                )
            )
        return tuple(entries)

    def read_session(self, session_id: str) -> SessionSnapshot:
        return self.store.read_session(session_id, expected_project_key=self.project_key)

    def read_session_for_command(self, session_id: str) -> SessionSnapshot:
        """Read a Session while translating storage failures at the Application boundary."""

        try:
            active = self._active
            if active is not None and active.session_id == session_id:
                return active.snapshot
            return self.read_session(session_id)
        except SessionFileError as exc:
            raise _session_operation_error(exc, session_id=session_id) from exc
        except OSError as exc:
            raise SessionOperationError("storage", session_id=session_id) from exc

    def project_replay(
        self,
        session_id: str,
        *,
        tool_summary: Callable[[ToolCallPart], str] | None = None,
    ) -> tuple[SessionReplayRecord, ...]:
        """Project one durable Session into safe records without opening it."""

        return _project_replay(
            self.read_session(session_id),
            tool_summary=tool_summary,
        )

    def project_replay_snapshot(
        self,
        snapshot: SessionSnapshot,
        *,
        tool_summary: Callable[[ToolCallPart], str] | None = None,
    ) -> tuple[SessionReplayRecord, ...]:
        """Project an already loaded snapshot without storage or lifecycle I/O."""

        if not isinstance(snapshot, SessionSnapshot):
            raise TypeError("snapshot must be a SessionSnapshot")
        if snapshot.project_key != self.project_key:
            raise ValueError("snapshot belongs to another project")
        return _project_replay(snapshot, tool_summary=tool_summary)

    def close(self) -> None:
        session = self._active
        if session is not None:
            session.close()

    def _require_no_active_session(self) -> None:
        if self._active is not None:
            raise SessionActiveError(
                f"Application Session {self._active.session_id!r} is active; close it before opening another"
            )

    def _stage_create_session(
        self,
        session_id: str | None,
        *,
        model_ref: str | None = None,
    ) -> _StagedSession:
        """Prepare a new Session while leaving the current one untouched."""

        candidate_loader: InstructionLoader | None = None
        if self.instruction_loader is not None:
            candidate_loader = self.instruction_loader.fork_for_session()
            candidate_loader.reset_for_new_session()
            result = candidate_loader.load_session(strict=True)
            state = result.instruction_state.to_dict()
        else:
            state = InstructionStateMetadata().to_dict()
        metadata = self.store.create_session(
            session_id,
            project_key=self.project_key,
            instruction_state=state,
            model_ref=model_ref,
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

    def _stage_resume_session(
        self,
        session_id: str,
        *,
        replay_builder: SessionReplayBuilder | None = None,
    ) -> _StagedSession:
        """Lock and validate a target before touching the active Session."""

        writer = self.store.open_writer(
            session_id,
            expected_project_key=self.project_key,
        )
        candidate_loader: InstructionLoader | None = None
        try:
            writer.__enter__()
            # Replay is a read-only projection of the loaded snapshot.  Build
            # it before any target metadata touch so a projection failure can
            # release the staged writer without mutating the active Session.
            replay = (
                _normalize_replay(
                    replay_builder(writer.snapshot),
                    writer.snapshot.session_id,
                )
                if replay_builder is not None
                else ()
            )
            if self.instruction_loader is not None:
                candidate_loader = self.instruction_loader.fork_for_session()
                state = InstructionStateMetadata.from_dict(
                    writer.snapshot.metadata.instruction_state
                )
                candidate_loader.rebuild_from_metadata(state, strict=True)
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
        return _StagedSession(
            ApplicationSession(self, writer, replay),
            candidate_loader,
        )

    def _refresh_active_session_for_resume(
        self,
        active: ApplicationSession,
        *,
        replay_builder: SessionReplayBuilder | None = None,
    ) -> ApplicationSession:
        """Refresh an already-held target without releasing its writer lock."""

        replay = (
            _normalize_replay(
                replay_builder(active._writer.snapshot),
                active.session_id,
            )
            if replay_builder is not None
            else active.replay
        )
        if self.instruction_loader is None:
            active._writer.touch()
            active._set_replay(replay)
            return active
        candidate_loader = self.instruction_loader.fork_for_session()
        state = InstructionStateMetadata.from_dict(
            active._writer.snapshot.metadata.instruction_state
        )
        candidate_loader.rebuild_from_metadata(state, strict=True)
        active._writer.update_instruction_state(
            candidate_loader.instruction_state.to_dict()
        )
        self.instruction_loader.adopt_session_state(candidate_loader)
        active._set_replay(replay)
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
    "TimelineAppendOutcome",
    "TranscriptAppendOutcome",
    "SessionCatalogEntry",
    "SessionMutation",
    "SessionReplayRecord",
    "SessionActiveError",
    "SessionOperationError",
]


def _normalize_replay(
    replay: Iterable[SessionReplayRecord],
    session_id: str,
) -> tuple[SessionReplayRecord, ...]:
    try:
        records = tuple(replay)
    except TypeError as exc:
        raise TypeError("replay must be an iterable of SessionReplayRecord") from exc
    previous_sequence = 0
    for record in records:
        if not isinstance(record, SessionReplayRecord):
            raise TypeError("replay must contain SessionReplayRecord values")
        if record.session_id != session_id:
            raise ValueError("replay record belongs to another Session")
        if record.sequence < previous_sequence:
            raise ValueError("replay records must be ordered by durable sequence")
        previous_sequence = record.sequence
    return records


def _session_mutation(metadata: SessionMetadata) -> SessionMutation:
    """Project integration metadata to the Application mutation contract."""

    return SessionMutation(
        session_id=metadata.session_id,
        project_key=metadata.project_key,
        title=metadata.title,
    )


def _canonical_project_key(value: object) -> str:
    """Resolve a target project key through the existing filesystem boundary."""

    if not isinstance(value, str) or not value.strip():
        raise ValueError("target_project_key must be a non-empty string")
    candidate = Path(value).expanduser().resolve(strict=False)
    if not candidate.is_dir():
        raise ValueError("target_project_key must identify an existing project directory")
    return str(candidate)


def _entry_parts(entry: TranscriptEntry) -> tuple[object, ...]:
    """Decode current part-local entries and the old full-message shape."""

    payload = entry.payload
    nested = payload.get("part")
    if isinstance(nested, Mapping):
        message = Message.from_dict(
            {
                "role": payload.get("role"),
                "parts": (nested,),
            }
        )
        return message.parts
    # Session v3 kept one full Message under ``message`` while the current
    # writer stores one typed part under ``part``.  The v3 reader deliberately
    # remains read-only; replay must understand that shape without rewriting
    # the durable transcript.
    legacy_message = payload.get("message")
    if isinstance(legacy_message, Mapping):
        return Message.from_dict(legacy_message).parts
    if isinstance(payload.get("parts"), Sequence):
        return Message.from_dict(payload).parts
    raise ValueError("Transcript entry has no typed Message part")


def _bounded_replay_text(value: str, *, limit: int = 240) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(1, limit - 1)].rstrip() + "…"


def _replay_tool_status(result: ToolResultPart) -> tuple[str, bool]:
    value = result.metadata.get("execution_status")
    status = value if isinstance(value, str) else None
    if status not in _REPLAY_TOOL_STATUSES:
        status = "failed" if result.is_error else "succeeded"
    return status, result.is_error


def _project_replay(
    snapshot: SessionSnapshot,
    *,
    tool_summary: Callable[[ToolCallPart], str] | None = None,
) -> tuple[SessionReplayRecord, ...]:
    """Build a chronological, safe projection from complete semantic units."""

    records: list[SessionReplayRecord] = []
    calls: dict[str, tuple[str, str]] = {}
    plan_call_ids: set[str] = set()
    plans: dict[str, tuple[int, str, str, str | None]] = {}
    user_seen: set[str] = set()
    legacy_message_ids: set[tuple[str, str, str]] = set()
    for unit in snapshot.transcript.semantic_units(complete_only=True):
        for entry in unit.entries:
            if entry.kind is TranscriptKind.TURN_FAILURE:
                termination_reason = entry.payload.get("termination_reason")
                failure_reason = entry.payload.get("failure_reason")
                records.append(
                    SessionReplayRecord(
                        session_id=snapshot.session_id,
                        sequence=entry.sequence,
                        turn_id=entry.turn_id,
                        kind="failure",
                        termination_reason=(
                            termination_reason
                            if isinstance(termination_reason, str)
                            else None
                        ),
                        failure_reason=(
                            failure_reason if isinstance(failure_reason, str) else None
                        ),
                        is_error=True,
                        created_at=entry.created_at,
                        title=snapshot.title,
                    )
                )
                continue
            # The pre-W02 writer emitted one full ``message`` envelope for
            # each part.  Those entries share the logical message identity;
            # project that envelope once while leaving current part-local
            # entries untouched (they have no ``message`` key).
            legacy_message = entry.payload.get("message")
            legacy_message_id = entry.payload.get("message_id")
            if isinstance(legacy_message, Mapping) and isinstance(
                legacy_message_id, str
            ) and legacy_message_id.strip():
                identity = (
                    entry.session_id,
                    entry.turn_id,
                    legacy_message_id,
                )
                if identity in legacy_message_ids:
                    continue
                legacy_message_ids.add(identity)
            for part in _entry_parts(entry):
                sequence = entry.sequence
                if isinstance(part, ToolCallPart):
                    if part.name == "ProposePlan":
                        # A Plan is replayable only after its complete
                        # semantic unit has a successful ToolResult.  Keep
                        # no raw arguments and suppress malformed/failed
                        # ProposePlan results below.
                        plan_call_ids.add(part.tool_call_id)
                        try:
                            plan_text = parse_propose_plan_arguments(part.arguments)
                        except (TypeError, ValueError, KeyError):
                            continue
                        plans[part.tool_call_id] = (
                            sequence,
                            entry.turn_id,
                            plan_text,
                            entry.created_at,
                        )
                        continue
                    summary = (
                        tool_summary(part)
                        if tool_summary is not None
                        else f"{part.name} completed"
                    )
                    if not isinstance(summary, str):
                        raise TypeError("tool replay summary must be a string")
                    calls[part.tool_call_id] = (
                        part.name,
                        _bounded_replay_text(summary),
                    )
                    continue
                if isinstance(part, ToolResultPart):
                    if part.tool_call_id in plan_call_ids:
                        plan = plans.pop(part.tool_call_id, None)
                        plan_status, plan_is_error = _replay_tool_status(part)
                        if (
                            plan is not None
                            and not plan_is_error
                            and plan_status in {"succeeded", "success", "finished"}
                        ):
                            plan_sequence, plan_turn_id, plan_text, plan_created_at = plan
                            records.append(
                                SessionReplayRecord(
                                    session_id=snapshot.session_id,
                                    sequence=plan_sequence,
                                    turn_id=plan_turn_id,
                                    kind="plan",
                                    text=plan_text,
                                    tool_name="ProposePlan",
                                    tool_call_id=part.tool_call_id,
                                    is_error=False,
                                    created_at=plan_created_at,
                                    title=snapshot.title,
                                )
                            )
                        continue
                    name, summary = calls.pop(
                        part.tool_call_id,
                        ("Tool", "Tool completed"),
                    )
                    status, is_error = _replay_tool_status(part)
                    records.append(
                        SessionReplayRecord(
                            session_id=snapshot.session_id,
                            sequence=sequence,
                            turn_id=entry.turn_id,
                            kind="tool",
                            text=summary,
                            tool_name=name,
                            tool_call_id=part.tool_call_id,
                            status=status,
                            is_error=is_error,
                            created_at=entry.created_at,
                            title=snapshot.title,
                        )
                    )
                    continue
                if not isinstance(part, (TextPart, ReasoningPart)):
                    continue
                if entry.kind in (
                    TranscriptKind.USER_MESSAGE,
                    TranscriptKind.USER_STEERING,
                ):
                    if not isinstance(part, TextPart):
                        continue
                    kind = (
                        "steering"
                        if entry.kind is TranscriptKind.USER_STEERING
                        or entry.turn_id in user_seen
                        else "user"
                    )
                    user_seen.add(entry.turn_id)
                elif isinstance(part, ReasoningPart):
                    kind = "reasoning"
                elif entry.kind in {
                    TranscriptKind.ASSISTANT_MESSAGE,
                    TranscriptKind.FAILED_ASSISTANT_MESSAGE,
                }:
                    kind = "assistant"
                else:
                    continue
                records.append(
                    SessionReplayRecord(
                        session_id=snapshot.session_id,
                        sequence=sequence,
                        turn_id=entry.turn_id,
                        kind=kind,
                        text=part.text,
                        created_at=entry.created_at,
                        title=snapshot.title,
                    )
                )
    return _normalize_replay(records, snapshot.session_id)


def _first_user_preview(snapshot: SessionSnapshot, *, limit: int = 160) -> str:
    """Extract only the first User Message and keep it to one display line."""

    for entry in snapshot.transcript.entries:
        if entry.kind is not TranscriptKind.USER_MESSAGE:
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
        SessionIncompatibleError,
        SessionNotFoundError,
    )

    if isinstance(exc, SessionBusyError):
        return SessionOperationError("busy", session_id=session_id)
    if isinstance(exc, (SessionCorruptError, SessionIncompatibleError)):
        return SessionOperationError("corrupt", session_id=session_id)
    if isinstance(exc, SessionNotFoundError):
        return SessionOperationError("unknown", session_id=session_id)
    return SessionOperationError("storage", session_id=session_id)
