"""Application-backed JSONL bridge for the Desktop child process.

The bridge is intentionally a small adapter, rather than a second runtime.
It owns the lifetime of one Application and one Run, forwards public
Application facts, and keeps transport/process failures separate from Agent
Turn failures.  All data crossing this module is projected through the
Application public exports or the strict protocol envelopes.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from enum import Enum
import inspect
import math
from pathlib import Path
import shlex
import sys
from typing import TextIO

from uthcode.application import (
    AgentEvent,
    agent_event_from_dict,
    ApplicationStatus,
    ApplicationRuntimeContext,
    PauseRequest,
    BehaviorMode,
    BehaviorModeSelected,
    ClearTranscript,
    CommandDispatcher,
    CommandOutcome,
    CommandParser,
    CompletionCandidate,
    ConfigurationError,
    ConfigurationInitializationRequired,
    CompletionEngine,
    EffectiveConfig,
    ModelSelected,
    OpenModelPicker,
    OpenPermissionPicker,
    OpenSessionPicker,
    OutcomeStatus,
    PermissionApprovalResponse,
    PermissionMode,
    PermissionModeSelected,
    PlanReviewResponse,
    QuitInterface,
    RetryProviderResponse,
    RunSnapshot,
    ResumeTurnResponse,
    SessionChanged,
    SessionCatalogEntry,
    SessionMutation,
    SessionOperationError,
    SessionReplayRecord,
    UserConfigurationWriteRequest,
    UserConfigurationView,
    UserInputResponse,
    create_application,
    create_builtin_registry,
    load_effective_config,
    read_user_api_key,
    read_user_configuration,
    write_user_configuration,
)

from .protocol import (
    AgentEventEnvelope,
    Envelope,
    ErrorPayload,
    ProtocolError,
    RequestEnvelope,
    ResponseEnvelope,
    RuntimeStateEnvelope,
    error_response,
    parse_request_line,
    write_envelope,
)


class BridgeError(RuntimeError):
    """A stable, safe error at the Desktop/Application adapter boundary."""

    def __init__(self, kind: str, message: str) -> None:
        self.kind = kind
        self.message = message
        super().__init__(message)


ApplicationFactory = Callable[[Path], object]
ConfigLoader = Callable[[Path], EffectiveConfig]


_METHODS = frozenset(
    {
        "runtime.initialize",
        "runtime.shutdown",
        "project.open",
        "project.sessions",
        "session.new",
        "session.resume",
        "session.rename",
        "session.move",
        "turn.start",
        "turn.steer",
        "turn.pause",
        "turn.resume",
        "turn.cancel",
        "command.complete",
        "command.execute",
        "status.get",
        "settings.get",
        "settings.reveal_api_key",
        "settings.save",
    }
)

# These commands mutate or replace the active Run/Application state.  The
# TUI rejects them while a Turn is active; keeping the same table here makes
# the Desktop adapter unable to bypass that gate via a Slash command.
_ACTIVE_COMMANDS = frozenset(
    {"model", "new", "resume", "compact", "plan", "do", "build"}
)
_SESSION_CHANGING_COMMANDS = frozenset({"new", "resume"})

_RESPONSE_TYPES: tuple[tuple[str, type[object]], ...] = (
    ("resume_turn", ResumeTurnResponse),
    ("user_input", UserInputResponse),
    ("retry_provider", RetryProviderResponse),
    ("permission_approval", PermissionApprovalResponse),
    ("plan_review", PlanReviewResponse),
)


def _path_value(value: object, field: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise BridgeError("invalid_request", f"{field} must be a non-empty string")
    path = Path(value).expanduser().resolve(strict=False)
    if not path.is_dir():
        raise BridgeError("project_not_found", "project path is not a directory")
    return path


def _require_params(
    params: Mapping[str, object],
    expected: set[str],
    *,
    method: str,
) -> None:
    actual = set(params)
    missing = expected - actual
    if missing:
        raise BridgeError(
            "invalid_request",
            f"{method} is missing fields: {sorted(missing)!r}",
        )
    extra = actual - expected
    if extra:
        raise BridgeError(
            "invalid_request",
            f"{method} has unknown fields: {sorted(extra)!r}",
        )


def _text_param(params: Mapping[str, object], field: str) -> str:
    value = params.get(field)
    if not isinstance(value, str) or not value.strip():
        raise BridgeError("invalid_request", f"{field} must be a non-empty string")
    return value




_INVALID = object()

# This is one Desktop wire contract, not a second AgentEvent schema.  The
# Core parser remains authoritative for event type, required fields, enums,
# and nested public DTOs.  New Core fields are intentionally ignored here
# until Desktop has a consumer for them.
_EVENT_OUTPUT_FIELDS = frozenset(
    {
        "type",
        "run_id",
        "turn_id",
        "message_id",
        "message",
        "iteration",
        "segment_index",
        "text",
        "kind",
        "usage",
        "previous_mode",
        "behavior_mode",
        "task_state",
        "revision",
        "plan_text",
        "tool_call_id",
        "unfinished_count",
        "steering_id",
        "pause_id",
        "reason",
        "request",
        "pause",
        "batch_id",
        "tool_call_ids",
        "tool_name",
        "command",
        "status",
        "is_error",
        "final_text",
        "termination_reason",
        "failure_reason",
    }
)
_SNAPSHOT_FIELDS = frozenset(
    {
        "run_id",
        "turn_id",
        "iteration_count",
        "tool_call_count",
        "consecutive_unknown_tools",
        "usage",
        "behavior_mode",
        "status",
        "termination_reason",
        "permission_mode",
    }
)
_USAGE_OUTPUT_FIELDS = (
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
)
_STATUS_OUTPUT_FIELDS = (
    "current_model",
    "provider_profile",
    "provider_identity",
    "state",
    "context_usage",
    "context_status",
    "compaction_status",
    "timeline_checkpoint_id",
    "active_session_title",
    "instruction_epoch",
    "compact_count",
    "stable_prefix_fingerprint",
    "prefix_changed",
    "prefix_change_reason",
    "tool_schema_fingerprint",
)
_CONFIGURATION_OUTPUT_FIELDS = (
    "default_model",
    "default_permission_mode",
    "providers",
    "models",
)
_PAUSE_OUTPUT_FIELDS = (
    "pause_id",
    "run_id",
    "turn_id",
    "kind",
    "reason",
    "iteration",
    "created_at",
    "tool_call_id",
    "user_input_request",
    "permission_request",
    "plan_review_request",
)
_REPLAY_OUTPUT_FIELDS = (
    "session_id",
    "sequence",
    "turn_id",
    "kind",
    "text",
    "tool_name",
    "tool_call_id",
    "status",
    "is_error",
    "created_at",
    "title",
)


def _text(value: object, *, optional: bool = False, non_empty: bool = False) -> object:
    if value is None and optional:
        return None
    return value if isinstance(value, str) and (not non_empty or bool(value.strip())) else _INVALID


def _boolean(value: object, *, optional: bool = False) -> object:
    if value is None and optional:
        return None
    return value if isinstance(value, bool) else _INVALID


def _enum_value(value: object, enum_type: type[Enum]) -> object:
    try:
        return enum_type(value).value
    except (TypeError, ValueError):
        return _INVALID


def _dto_payload(value: object, expected_type: type[object]) -> Mapping[str, object] | None:
    if type(value) is not expected_type:
        return None
    try:
        raw = value.to_dict()  # type: ignore[attr-defined]
    except Exception:
        return None
    if not isinstance(raw, Mapping) or not all(isinstance(key, str) for key in raw):
        return None
    return raw


def _json_safe(value: object) -> object:
    """Keep only JSON values after a typed DTO has chosen its fields."""

    if isinstance(value, Enum):
        return _json_safe(value.value)
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else _INVALID
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        try:
            items = value.items()
            for key, item in items:
                if not isinstance(key, str):
                    return _INVALID
                projected = _json_safe(item)
                if projected is _INVALID:
                    return _INVALID
                result[key] = projected
        except Exception:
            return _INVALID
        return result
    if isinstance(value, (list, tuple)):
        result = []
        for item in value:
            projected = _json_safe(item)
            if projected is _INVALID:
                return _INVALID
            result.append(projected)
        return result
    return _INVALID


def _project_fields(value: object, fields: tuple[str, ...] | frozenset[str]) -> dict[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    try:
        selected = {key: value[key] for key in fields if key in value}
    except Exception:
        return None
    projected = _json_safe(selected)
    return projected if isinstance(projected, dict) else None


def _dto_fields(
    value: object,
    expected_type: type[object],
    fields: tuple[str, ...] | frozenset[str],
) -> dict[str, object] | None:
    raw = _dto_payload(value, expected_type)
    return None if raw is None else _project_fields(raw, fields)


def _permission_mode_value(run: object) -> str | None:
    try:
        value = _enum_value(getattr(run, "permission_mode", None), PermissionMode)
    except Exception:
        return None
    return None if value is _INVALID else value  # type: ignore[return-value]


def _action_value(action: object | None) -> dict[str, object] | None:
    if action is None:
        return None
    if isinstance(action, ClearTranscript):
        return {"type": "clear_transcript"}
    if isinstance(action, OpenModelPicker):
        return {"type": "open_model_picker"}
    if isinstance(action, OpenPermissionPicker):
        return {"type": "open_permission_picker"}
    if isinstance(action, OpenSessionPicker):
        return {"type": "open_session_picker"}
    if isinstance(action, QuitInterface):
        return {"type": "quit_interface"}
    if isinstance(action, ModelSelected):
        model = _text(action.model_ref, non_empty=True)
        return {"type": "model_selected", "model_ref": model} if model is not _INVALID else {"type": "ui_action"}
    if isinstance(action, BehaviorModeSelected):
        mode = _enum_value(action.mode, BehaviorMode)
        return {"type": "behavior_mode_selected", "mode": mode} if mode is not _INVALID else {"type": "ui_action"}
    if isinstance(action, PermissionModeSelected):
        mode = _enum_value(action.mode, PermissionMode)
        # The warning is Application-owned prose (currently Chinese).  It is
        # intentionally represented as a boolean semantic flag so Renderer
        # locale resources, rather than command output, own the copy.
        warning = action.warning is not None
        return (
            {"type": "permission_mode_selected", "mode": mode, "warning": warning}
            if mode is not _INVALID
            else {"type": "ui_action"}
        )
    if isinstance(action, SessionChanged):
        session_id = _text(action.session_id, non_empty=True)
        restored = _boolean(action.restored)
        return (
            {"type": "session_changed", "session_id": session_id, "restored": restored}
            if session_id is not _INVALID and restored is not _INVALID
            else {"type": "ui_action"}
        )
    return {"type": "ui_action"}


def _catalog_entry(entry: object) -> dict[str, object] | None:
    if type(entry) is not SessionCatalogEntry:
        return None
    values = {
        "session_id": entry.session_id,
        "project_key": entry.project_key,
        "last_used_at": entry.last_used_at,
        "preview": entry.preview,
        "timeline_checkpoint_id": entry.timeline_checkpoint_id,
        "transcript_entries": entry.transcript_entries,
        "corrupt": entry.corrupt,
        "title": entry.title,
    }
    projected = _json_safe(values)
    return projected if isinstance(projected, dict) else None


def _catalog_entries(values: tuple[object, ...]) -> list[dict[str, object]]:
    result = [_catalog_entry(value) for value in values]
    if any(value is None for value in result):
        raise BridgeError("session_error", "Session catalog unavailable")
    return [value for value in result if value is not None]


def _session_mutation_value(value: object) -> dict[str, object]:
    projected = _dto_fields(value, SessionMutation, ("session_id", "project_key", "title"))
    if projected is None:
        raise BridgeError("session_error", "Session mutation returned no metadata")
    return projected


def _replay_values(values: object) -> list[object]:
    if isinstance(values, (str, bytes, bytearray)):
        return []
    try:
        records = tuple(values)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return []
    result: list[object] = []
    for record in records:
        if type(record) is not SessionReplayRecord:
            continue
        projected = _dto_fields(record, SessionReplayRecord, _REPLAY_OUTPUT_FIELDS)
        if projected is not None:
            result.append(projected)
    return result


def _application_status(value: object) -> dict[str, object] | None:
    """Top-level status allowlist; diagnostics and configuration paths are never returned."""

    return _dto_fields(value, ApplicationStatus, _STATUS_OUTPUT_FIELDS)


def _configuration(value: object) -> dict[str, object] | None:
    return _dto_fields(value, UserConfigurationView, _CONFIGURATION_OUTPUT_FIELDS)


def _strings(value: object, *, non_empty: bool = False) -> list[str] | None:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, (list, tuple)):
        return None
    result: list[str] = []
    for item in value:
        projected = _text(item, non_empty=non_empty)
        if projected is _INVALID:
            return None
        result.append(projected)  # type: ignore[arg-type]
    return result


def _completion_candidate(value: object) -> dict[str, object] | None:
    if type(value) is not CompletionCandidate:
        return None
    fields_value = {
        "canonical": _text(value.canonical, non_empty=True),
        "display": _text(value.display, non_empty=True),
        "description": _text(value.description),
        "aliases": _strings(value.aliases, non_empty=True),
        "usage": _text(value.usage, non_empty=True),
        "argument_prompt": _text(value.argument_prompt),
        "matched_alias": _text(value.matched_alias, optional=True),
    }
    if any(value is _INVALID for value in fields_value.values()) or fields_value["aliases"] is None:
        return None
    return {"value": f"/{fields_value['canonical']}", **fields_value}


def _event(value: object) -> dict[str, object] | None:
    if not isinstance(value, AgentEvent):
        return None
    try:
        # Rehydrate through Core's parser so this adapter never duplicates
        # AgentEvent's required fields, enum coercion, or nested DTO rules.
        parsed = agent_event_from_dict(value.to_dict())
        raw = parsed.to_dict()
    except Exception:
        return None
    return _project_fields(raw, _EVENT_OUTPUT_FIELDS)


def _snapshot(value: object) -> dict[str, object] | None:
    result = _dto_fields(value, RunSnapshot, _SNAPSHOT_FIELDS)
    if result is None:
        return None
    if "usage" in result:
        usage = _project_fields(result["usage"], _USAGE_OUTPUT_FIELDS)
        if usage is None:
            return None
        result["usage"] = usage
    return result

def _session_identity(value: object, fallback: str | None = None) -> str:
    if isinstance(value, str) and value.strip():
        return value
    if fallback is not None:
        return fallback
    raise BridgeError("session_error", "Session returned no identity")


def _completion_argument_index(prefix: str, invocation: object) -> int | None:
    """Find the argument currently being edited, matching TUI token rules."""

    args = getattr(invocation, "args", ())
    if not isinstance(args, tuple):
        return None
    body = prefix.lstrip()[1:]
    name_end = 0
    while name_end < len(body) and not body[name_end].isspace():
        name_end += 1
    argument_text = body[name_end:]
    trimmed = argument_text.rstrip()
    if len(trimmed) != len(argument_text):
        return len(args)
    token_start = max(
        (index + 1 for index, character in enumerate(trimmed) if character.isspace()),
        default=0,
    )
    try:
        completed = len(shlex.split(trimmed[:token_start], posix=True))
    except ValueError:
        completed = max(len(args) - 1, 0)
    return completed


class DesktopBridge:
    """One-process Desktop adapter around the public Application surface."""

    def __init__(
        self,
        application: object | None = None,
        *,
        application_factory: ApplicationFactory | None = None,
        config_loader: ConfigLoader | None = None,
        home: str | Path | None = None,
        workdir: str | Path | None = None,
        shutdown_timeout: float = 5.0,
    ) -> None:
        if application_factory is not None and not callable(application_factory):
            raise TypeError("application_factory must be callable or None")
        if config_loader is not None and not callable(config_loader):
            raise TypeError("config_loader must be callable or None")
        if shutdown_timeout <= 0:
            raise ValueError("shutdown_timeout must be positive")
        self._application = application
        self._run: object | None = None
        self._active_handle: object | None = None
        self._turn_task: asyncio.Task[None] | None = None
        self._outbox: list[Envelope] = []
        self._outbox_signal: asyncio.Event | None = None
        self._seen_request_ids: set[str] = set()
        self._application_factory = application_factory
        self._config_loader = config_loader
        self._home = None if home is None else Path(home).expanduser().resolve(strict=False)
        self._workdir = (
            Path(workdir).expanduser().resolve(strict=False)
            if workdir is not None
            else Path.cwd().resolve(strict=False)
        )
        self._shutdown_timeout = float(shutdown_timeout)
        # ``ready`` describes the child transport.  Application construction
        # is deliberately deferred until ``runtime.initialize`` so an
        # unconfigured user can still open Settings through the bridge.
        self._state = "ready"
        self._registry = create_builtin_registry()
        self._parser = CommandParser(self._registry)
        self._dispatcher = CommandDispatcher(self._registry, application)
        self._completion = CompletionEngine(self._registry, application)
        if application is not None:
            self._replace_run(application)

    @property
    def state(self) -> str:
        return self._state

    @property
    def application(self) -> object | None:
        return self._application

    @property
    def run(self) -> object | None:
        return self._run

    @property
    def active_handle(self) -> object | None:
        return self._active_handle

    def _replace_run(self, application: object) -> object:
        run = self._create_run(application)
        self._run = run
        return run

    @staticmethod
    def _create_run(application: object) -> object:
        create_run = getattr(application, "create_run", None)
        if not callable(create_run):
            raise BridgeError("application_error", "Application cannot create a Run")
        try:
            run = create_run()
        except BridgeError:
            raise
        except Exception:
            raise BridgeError("application_error", "Application cannot create a Run") from None
        if run is None:
            raise BridgeError("application_error", "Application returned no Run")
        return run

    def _publish(self, envelope: Envelope) -> None:
        self._outbox.append(envelope)
        signal = self._outbox_signal
        if signal is not None:
            signal.set()

    def drain_outbox(self) -> tuple[Envelope, ...]:
        values = tuple(self._outbox)
        self._outbox.clear()
        if not self._outbox and self._outbox_signal is not None:
            self._outbox_signal.clear()
        return values

    async def wait_for_idle(self) -> None:
        task = self._turn_task
        if task is None:
            return
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            raise
        finally:
            if task.done() and self._turn_task is task:
                self._turn_task = None

    @staticmethod
    def _snapshot_for(
        run: object | None,
        *,
        strict: bool = False,
    ) -> dict[str, object] | None:
        """Return the Run's explicit safe snapshot, optionally fail-closed."""

        if run is None:
            return None
        snapshot = getattr(run, "snapshot", None)
        if not callable(snapshot):
            return None
        try:
            value = snapshot()
        except Exception:
            if strict:
                raise BridgeError("projection_error", "Run projection unavailable") from None
            return None
        if value is None:
            return None
        projected = _snapshot(value)
        if strict and projected is None:
            raise BridgeError("projection_error", "Run projection unavailable")
        if projected is None:
            if strict:
                raise BridgeError("projection_error", "Run projection unavailable")
            return None
        # The current permission strategy belongs to the Application-owned
        # Run, so add only its allowlisted scalar to this existing projection.
        permission_mode = _permission_mode_value(run)
        if permission_mode is not None:
            projected["permission_mode"] = permission_mode
        return projected

    def _snapshot(self) -> dict[str, object] | None:
        return self._snapshot_for(self._run)

    def _pending_pause(self) -> object | None:
        handle = self._active_handle
        return None if handle is None else getattr(handle, "pending_pause", None)

    def _runtime_result(self) -> dict[str, object]:
        application = self._application
        state = self._state if isinstance(self._state, str) else "failed"
        return {
            "state": state,
            "application": application is not None,
            "run": self._snapshot(),
        }

    def _status_result(self) -> dict[str, object]:
        application = self._application
        status_method = getattr(application, "status", None)
        application_status: object | None = None
        if callable(status_method):
            try:
                application_status = status_method()
            except Exception:
                raise BridgeError("application_error", "Application status unavailable") from None
        result: dict[str, object] = {
            "runtime": self._runtime_result(),
            "active_turn": self._active_handle is not None,
            "pending_pause": _dto_fields(
                self._pending_pause(),
                PauseRequest,
                _PAUSE_OUTPUT_FIELDS,
            ),
        }
        if application_status is not None:
            projected = _application_status(application_status)
            if projected is not None:
                result["application"] = projected
        return result

    @staticmethod
    def _application_sessions_for(application: object | None) -> tuple[object, ...]:
        catalog = getattr(application, "session_catalog", None)
        if not callable(catalog):
            return ()
        try:
            values = catalog()
        except Exception:
            raise BridgeError("session_error", "Session catalog unavailable") from None
        if not isinstance(values, (tuple, list)):
            try:
                values = tuple(values)
            except Exception:
                raise BridgeError("session_error", "Session catalog unavailable") from None
        return tuple(values)

    def _application_sessions(self) -> tuple[object, ...]:
        return self._application_sessions_for(self._application)

    async def handle_request(self, request: RequestEnvelope) -> ResponseEnvelope:
        """Handle one already-parsed request without writing to stdout."""

        if not isinstance(request, RequestEnvelope):
            raise TypeError("request must be a RequestEnvelope")
        if request.id in self._seen_request_ids:
            return error_response(
                request.id,
                "duplicate_request_id",
                "request id has already been used",
            )
        self._seen_request_ids.add(request.id)
        try:
            if request.method not in _METHODS:
                raise BridgeError("unknown_method", "unknown Desktop method")
            result = await self._dispatch(request.method, request.params)
            return ResponseEnvelope(request.id, True, result)
        except ProtocolError:
            raise
        except BridgeError as exc:
            return error_response(request.id, exc.kind, exc.message)
        except (TypeError, ValueError):
            return error_response(
                request.id,
                "invalid_request",
                "request parameters are invalid",
            )
        except Exception:
            # Never serialize exception text: it can contain SDK payloads,
            # paths, credentials, or native exception objects.
            return error_response(
                request.id,
                "application_error",
                "Desktop Application operation failed",
            )

    async def _dispatch(
        self,
        method: str,
        params: Mapping[str, object],
    ) -> dict[str, object]:
        if method == "runtime.initialize":
            return await self._runtime_initialize(params)
        if method == "runtime.shutdown":
            _require_params(params, set(), method=method)
            await self.shutdown(publish_state=True)
            if self._state == "failed":
                raise BridgeError("application_close_failed", "Application close failed")
            return self._runtime_result()
        if method == "project.open":
            return await self._project_open(params)
        if method == "project.sessions":
            _require_params(params, set(), method=method)
            return {"sessions": _catalog_entries(self._application_sessions())}
        if method == "session.new":
            return await self._session_new(params)
        if method == "session.resume":
            return await self._session_resume(params)
        if method == "session.rename":
            return await self._session_rename(params)
        if method == "session.move":
            return await self._session_move(params)
        if method == "turn.start":
            return await self._turn_start(params)
        if method == "turn.steer":
            return await self._turn_steer(params)
        if method == "turn.pause":
            return await self._turn_pause(params)
        if method == "turn.resume":
            return await self._turn_resume(params)
        if method == "turn.cancel":
            return await self._turn_cancel(params)
        if method == "command.complete":
            return self._command_complete(params)
        if method == "command.execute":
            return await self._command_execute(params)
        if method == "status.get":
            _require_params(params, set(), method=method)
            return self._status_result()
        if method == "settings.get":
            _require_params(params, set(), method=method)
            try:
                view = read_user_configuration(home=self._home)
            except ConfigurationInitializationRequired:
                raise BridgeError("configuration_required", "user configuration is not initialized") from None
            except ConfigurationError:
                raise BridgeError("configuration_error", "user configuration is invalid") from None
            return {"configuration": _configuration(view)}
        if method == "settings.reveal_api_key":
            return await self._settings_reveal_api_key(params)
        if method == "settings.save":
            return await self._settings_save(params)
        raise BridgeError("unknown_method", "unknown Desktop method")

    async def _runtime_initialize(self, params: Mapping[str, object]) -> dict[str, object]:
        expected = {"workdir", "cwd"}
        if "workdir" in params and "cwd" in params:
            raise BridgeError("invalid_request", "runtime.initialize accepts only one workdir")
        if set(params) - expected:
            raise BridgeError(
                "invalid_request",
                f"runtime.initialize has unknown fields: {sorted(set(params) - expected)!r}",
            )
        selected_workdir = "workdir" if "workdir" in params else "cwd"
        if selected_workdir in params:
            path = _path_value(params[selected_workdir], selected_workdir)
            self._workdir = path
        if self._application is not None:
            self._state = "ready"
            if self._run is None:
                self._replace_run(self._application)
            return self._runtime_result()
        try:
            application = self._build_application(self._workdir)
        except ConfigurationInitializationRequired:
            self._state = "configuration_required"
            raise BridgeError("configuration_required", "user configuration is not initialized") from None
        except ConfigurationError:
            # Configuration is a recoverable bootstrap state: keep the child
            # alive so Settings can write a corrected user configuration and
            # retry ``runtime.initialize``.
            self._state = "configuration_required"
            raise BridgeError("configuration_error", "user configuration is invalid") from None
        except BridgeError as exc:
            if exc.kind == "configuration_required":
                self._state = "configuration_required"
                raise BridgeError(
                    "configuration_required",
                    "user configuration is not initialized",
                ) from None
            if exc.kind == "configuration_error":
                self._state = "configuration_required"
                raise BridgeError(
                    "configuration_error",
                    "user configuration is invalid",
                ) from None
            if exc.kind == "application_error":
                self._state = "failed"
                self._publish(
                    RuntimeStateEnvelope(
                        "failed",
                        ErrorPayload("application_error", "Application initialization failed"),
                    )
                )
                raise BridgeError(
                    "application_error",
                    "Application initialization failed",
                ) from None
            self._state = "failed"
            self._publish(
                RuntimeStateEnvelope(
                    "failed",
                    ErrorPayload("application_error", "Application initialization failed"),
                )
            )
            raise BridgeError("application_error", "Application initialization failed") from None
        except Exception:
            self._state = "failed"
            self._publish(
                RuntimeStateEnvelope(
                    "failed",
                    ErrorPayload("application_error", "Application initialization failed"),
                )
            )
            raise BridgeError("application_error", "Application initialization failed") from None
        try:
            run = self._create_run(application)
        except BridgeError:
            close = getattr(application, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass
            self._state = "failed"
            self._publish(
                RuntimeStateEnvelope(
                    "failed",
                    ErrorPayload("application_error", "Application initialization failed"),
                )
            )
            raise BridgeError("application_error", "Application cannot create a Run") from None
        self._application = application
        self._run = run
        self._dispatcher = CommandDispatcher(self._registry, application)
        self._completion = CompletionEngine(self._registry, application)
        self._state = "ready"
        return self._runtime_result()

    def _build_application(self, workdir: Path) -> object:
        if self._application_factory is not None:
            return self._application_factory(workdir)
        loader = self._config_loader
        if loader is None:
            config = load_effective_config(cwd=workdir, home=self._home)
        else:
            config = loader(workdir)
        if not isinstance(config, EffectiveConfig):
            raise BridgeError("configuration_error", "configuration loader returned invalid data")
        return create_application(
            config,
            runtime_context=ApplicationRuntimeContext.from_system(workdir=workdir),
        )

    async def _close_active_for_boundary(self) -> None:
        handle = self._active_handle
        if handle is None:
            return
        cancel = getattr(handle, "cancel", None)
        if callable(cancel):
            try:
                cancel()
            except Exception:
                raise BridgeError("turn_error", "active Turn could not be cancelled") from None
        task = self._turn_task
        if task is not None and not task.done():
            try:
                await asyncio.wait_for(asyncio.shield(task), self._shutdown_timeout)
            except asyncio.TimeoutError:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        self._active_handle = None
        self._turn_task = None

    async def _project_open(self, params: Mapping[str, object]) -> dict[str, object]:
        _require_params(params, {"path"}, method="project.open")
        path = _path_value(params["path"], "path")
        candidate: object | None = None
        candidate_run: object | None = None

        # Stage every candidate-side operation, including the projections that
        # will cross the wire, before touching the current Turn/Application.
        # A catalog/snapshot failure must therefore leave the old owner and
        # its active Session untouched.
        try:
            candidate = self._build_application(path)
            candidate_run = self._create_run(candidate)
            candidate_dispatcher = CommandDispatcher(self._registry, candidate)
            candidate_completion = CompletionEngine(self._registry, candidate)
            candidate_sessions = _catalog_entries(self._application_sessions_for(candidate))
            candidate_snapshot = self._snapshot_for(candidate_run, strict=True)
        except ConfigurationInitializationRequired:
            raise BridgeError("configuration_required", "project configuration is not initialized") from None
        except ConfigurationError:
            raise BridgeError("configuration_error", "project configuration is invalid") from None
        except BridgeError:
            if candidate is not None:
                close = getattr(candidate, "close", None)
                if callable(close):
                    try:
                        close()
                    except Exception:
                        pass
            raise BridgeError("project_open_failed", "project could not be opened") from None
        except Exception:
            if candidate is not None:
                close = getattr(candidate, "close", None)
                if callable(close):
                    try:
                        close()
                    except Exception:
                        pass
            raise BridgeError("project_open_failed", "project could not be opened") from None

        # Only now may the old Turn and Application be released.  If either
        # boundary fails, the candidate is discarded and the old references
        # remain installed.
        try:
            if self._active_handle is not None:
                await self._close_active_for_boundary()
        except Exception:
            close = getattr(candidate, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass
            raise
        old = self._application
        if old is not None:
            close = getattr(old, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    # Candidate construction succeeded, but the old
                    # Application could not release its writer.  Keep the
                    # old owner intact and release only the unused candidate
                    # so a failed switch remains transactional.
                    candidate_close = getattr(candidate, "close", None)
                    if callable(candidate_close):
                        try:
                            candidate_close()
                        except Exception:
                            pass
                    raise BridgeError("application_close_failed", "previous Application could not close") from None
        self._application = candidate
        self._workdir = path
        self._run = candidate_run
        self._dispatcher = candidate_dispatcher
        self._completion = candidate_completion
        self._state = "ready"
        return {
            "project": {"path": str(path)},
            "sessions": candidate_sessions,
            "run": candidate_snapshot,
        }

    async def _session_new(self, params: Mapping[str, object]) -> dict[str, object]:
        # The Application command use case allocates the durable identity;
        # Desktop does not invent or inject one.  Keeping the request empty
        # also prevents a caller from bypassing the Application Session
        # boundary with an arbitrary ID.
        _require_params(params, set(), method="session.new")
        if self._application is None:
            raise BridgeError("application_required", "Application is not initialized")
        application = self._application
        # Resolve the Application budget before cancelling any active Turn;
        # a cancelled resolver must leave the source Run and Session intact.
        context_budget: object | None = None
        preflight = getattr(application, "preflight_session_context_async", None)
        if callable(preflight):
            try:
                context_budget = preflight()
                if inspect.isawaitable(context_budget):
                    context_budget = await context_budget
            except Exception:
                raise BridgeError("session_error", "Session context could not be prepared") from None
        await self._close_active_for_boundary()
        # create_run loads the immutable permission rules for the next Run.
        # Stage it before the Application Session mutation so a loader/create
        # failure cannot leave a new Session paired with the old Run.
        candidate_run = self._fresh_session_run(application)
        create = getattr(application, "new_session_for_command_async", None)
        if not callable(create):
            create = getattr(application, "new_session_for_command", None)
        if not callable(create):
            raise BridgeError("session_error", "Application does not support Sessions")
        try:
            if context_budget is None:
                session = create()
            else:
                session = create(context_budget=context_budget)
            if inspect.isawaitable(session):
                session = await session
        except Exception as exc:
            kind = getattr(exc, "kind", None)
            raise BridgeError(
                {"busy": "session_busy", "corrupt": "session_corrupt", "unknown": "session_unknown"}.get(
                    kind,
                    "session_error",
                ),
                "Session could not be created",
            ) from None
        session_id = _session_identity(getattr(session, "session_id", None))
        self._run = candidate_run
        return {"session_id": session_id, "restored": False, "replay": [], "run": self._snapshot()}

    async def _session_resume(self, params: Mapping[str, object]) -> dict[str, object]:
        _require_params(params, {"session_id"}, method="session.resume")
        session_id = _text_param(params, "session_id")
        if self._application is None:
            raise BridgeError("application_required", "Application is not initialized")
        application = self._application
        # Resolve the Application budget before cancelling any active Turn;
        # a cancelled resolver must leave the source Run and Session intact.
        context_budget: object | None = None
        preflight = getattr(application, "preflight_session_context_async", None)
        if callable(preflight):
            try:
                context_budget = preflight()
                if inspect.isawaitable(context_budget):
                    context_budget = await context_budget
            except Exception:
                raise BridgeError("session_error", "Session context could not be prepared") from None
        await self._close_active_for_boundary()
        candidate_run = self._fresh_session_run(application)
        resume = getattr(application, "resume_session_for_command_async", None)
        if not callable(resume):
            resume = getattr(application, "resume_session_for_command", None)
        if not callable(resume):
            raise BridgeError("session_error", "Application does not support Sessions")
        try:
            if context_budget is None:
                session = resume(session_id)
            else:
                session = resume(session_id, context_budget=context_budget)
            if inspect.isawaitable(session):
                session = await session
        except Exception as exc:
            kind = getattr(exc, "kind", None)
            raise BridgeError(
                {"busy": "session_busy", "corrupt": "session_corrupt", "unknown": "session_unknown"}.get(
                    kind,
                    "session_error",
                ),
                "Session could not be resumed",
            ) from None
        restored_id = _session_identity(getattr(session, "session_id", None), session_id)
        replay = getattr(session, "replay", ())
        self._run = candidate_run
        return {
            "session_id": restored_id,
            "restored": True,
            "replay": _replay_values(replay),
            "run": self._snapshot(),
        }

    async def _session_rename(self, params: Mapping[str, object]) -> dict[str, object]:
        _require_params(params, {"session_id", "title"}, method="session.rename")
        session_id = _text_param(params, "session_id")
        title = _text_param(params, "title")
        self._ensure_no_active(method="session.rename")
        application = self._require_application()
        rename = getattr(application, "rename_session", None)
        if not callable(rename):
            raise BridgeError("session_error", "Application does not support Session rename")
        try:
            metadata = rename(session_id, title)
        except SessionOperationError as exc:
            kind = {
                "busy": "session_busy",
                "corrupt": "session_corrupt",
                "unknown": "session_unknown",
            }.get(exc.kind, "session_error")
            raise BridgeError(kind, "Session could not be renamed") from None
        except (TypeError, ValueError):
            raise BridgeError("invalid_request", "Session title is invalid") from None
        except Exception:
            raise BridgeError("session_error", "Session could not be renamed") from None
        projected = _session_mutation_value(metadata)
        return {
            "session_id": _session_identity(projected.get("session_id"), session_id),
            "title": projected.get("title"),
            "session": projected,
        }

    async def _session_move(self, params: Mapping[str, object]) -> dict[str, object]:
        _require_params(
            params,
            {"session_id", "target_project_key"},
            method="session.move",
        )
        session_id = _text_param(params, "session_id")
        target = _text_param(params, "target_project_key")
        self._ensure_no_active(method="session.move")
        # A target is a project identity, not an arbitrary storage path.  The
        # existing Desktop project boundary canonicalizes it and checks that
        # it is an actual directory before Application sees it.
        target_path = _path_value(target, "target_project_key")
        application = self._require_application()
        move = getattr(application, "move_session", None)
        if not callable(move):
            raise BridgeError("session_error", "Application does not support Session move")
        try:
            metadata = move(session_id, str(target_path))
        except SessionOperationError as exc:
            kind = {
                "busy": "session_busy",
                "corrupt": "session_corrupt",
                "unknown": "session_unknown",
            }.get(exc.kind, "session_error")
            raise BridgeError(kind, "Session could not be moved") from None
        except (TypeError, ValueError):
            raise BridgeError("project_not_found", "target project is not trusted") from None
        except Exception:
            raise BridgeError("session_error", "Session could not be moved") from None
        projected = _session_mutation_value(metadata)
        return {
            "session_id": _session_identity(projected.get("session_id"), session_id),
            "project_key": projected.get("project_key"),
            "title": projected.get("title"),
            "session": projected,
        }

    def _require_run(self) -> object:
        if self._application is None or self._run is None:
            raise BridgeError("application_required", "Application is not initialized")
        return self._run

    @staticmethod
    def _fresh_session_run(application: object) -> object:
        try:
            return DesktopBridge._create_run(application)
        except BridgeError:
            raise BridgeError("session_error", "Session Run could not be prepared") from None

    def _ensure_no_active(self, *, method: str) -> None:
        if self._active_handle is not None:
            raise BridgeError("turn_active", f"{method} is unavailable during an active Turn")

    async def _turn_start(self, params: Mapping[str, object]) -> dict[str, object]:
        _require_params(params, {"prompt"}, method="turn.start")
        prompt = _text_param(params, "prompt")
        if self._pending_pause() is not None:
            raise BridgeError("interaction_pending", "pending interaction captures this input")
        if self._active_handle is not None:
            raise BridgeError("turn_active", "a Turn is already active")
        application = self._application
        if application is None:
            raise BridgeError("application_required", "Application is not initialized")
        ensure = getattr(application, "ensure_session_async", None)
        if not callable(ensure):
            ensure = getattr(application, "ensure_session", None)
        if callable(ensure):
            try:
                result = ensure()
                if inspect.isawaitable(result):
                    await result
            except Exception:
                raise BridgeError("session_error", "Session could not be opened") from None
        run = self._require_run()
        start = getattr(run, "start_turn", None)
        if not callable(start):
            raise BridgeError("turn_error", "Run cannot start a Turn")
        try:
            handle = start(prompt)
        except Exception:
            raise BridgeError("turn_error", "Turn could not be started") from None
        if handle is None:
            raise BridgeError("turn_error", "Turn could not be started")
        self._active_handle = handle
        self._turn_task = asyncio.create_task(self._consume_turn(handle))
        snapshot = self._snapshot() or {}
        return {
            "run_id": snapshot.get("run_id"),
            "turn_id": snapshot.get("turn_id"),
            "status": "running",
        }

    async def _turn_steer(self, params: Mapping[str, object]) -> dict[str, object]:
        _require_params(params, {"text"}, method="turn.steer")
        text = _text_param(params, "text")
        handle = self._active_handle
        if handle is None:
            raise BridgeError("turn_idle", "no active Turn accepts steering")
        if self._pending_pause() is not None:
            raise BridgeError("interaction_pending", "pending interaction must be answered or cancelled")
        steer = getattr(handle, "steer", None)
        if not callable(steer):
            raise BridgeError("turn_error", "Turn does not support steering")
        try:
            accepted = steer(text)
        except Exception:
            raise BridgeError("turn_error", "Turn rejected steering") from None
        if not accepted:
            raise BridgeError("turn_not_accepting_input", "Turn cannot accept steering at this boundary")
        return {"accepted": True, "run": self._snapshot()}

    async def _turn_pause(self, params: Mapping[str, object]) -> dict[str, object]:
        _require_params(params, set(), method="turn.pause")
        handle = self._active_handle
        if handle is None:
            raise BridgeError("turn_idle", "no active Turn")
        if self._pending_pause() is not None:
            raise BridgeError("interaction_pending", "Turn already has a pending interaction")
        pause = getattr(handle, "pause", None)
        if not callable(pause):
            raise BridgeError("turn_error", "Turn does not support pause")
        try:
            accepted = pause()
        except Exception:
            raise BridgeError("turn_error", "Turn rejected pause") from None
        if not accepted:
            raise BridgeError("turn_not_paused", "Turn could not pause at this boundary")
        return {"accepted": True, "run": self._snapshot()}

    async def _turn_cancel(self, params: Mapping[str, object]) -> dict[str, object]:
        _require_params(params, set(), method="turn.cancel")
        handle = self._active_handle
        if handle is None:
            raise BridgeError("turn_idle", "no active Turn")
        cancel = getattr(handle, "cancel", None)
        if not callable(cancel):
            raise BridgeError("turn_error", "Turn does not support cancellation")
        try:
            accepted = cancel()
        except Exception:
            raise BridgeError("turn_error", "Turn rejected cancellation") from None
        if not accepted and self._turn_task is None:
            raise BridgeError("turn_not_cancelled", "Turn was already terminal")
        return {"accepted": bool(accepted), "run": self._snapshot()}

    @staticmethod
    def _parse_response(value: object) -> object:
        if not isinstance(value, Mapping):
            raise BridgeError("invalid_response", "turn response must be an object")
        response_type = value.get("type")
        for expected, response_class in _RESPONSE_TYPES:
            if response_type == expected:
                try:
                    return response_class.from_dict(value)  # type: ignore[attr-defined]
                except Exception:
                    raise BridgeError("invalid_response", "turn response is invalid") from None
        raise BridgeError("invalid_response", "unknown turn response type")

    async def _turn_resume(self, params: Mapping[str, object]) -> dict[str, object]:
        _require_params(params, {"response"}, method="turn.resume")
        handle = self._active_handle
        if handle is None:
            raise BridgeError("stale_response", "no active Turn has a pending response")
        pending = self._pending_pause()
        if pending is None:
            raise BridgeError("stale_response", "no active pending response")
        response = self._parse_response(params["response"])
        pending_kind = getattr(pending, "kind", None)
        response_kind = getattr(response, "pause_kind", None)
        if pending_kind is not None and response_kind is not pending_kind:
            raise BridgeError("stale_response", "response kind does not match pending interaction")
        if (
            getattr(response, "pause_id", None) != getattr(pending, "pause_id", None)
            or getattr(response, "run_id", None) != getattr(pending, "run_id", None)
            or getattr(response, "turn_id", None) != getattr(pending, "turn_id", None)
        ):
            raise BridgeError("stale_response", "response identity does not match pending interaction")
        resume = getattr(handle, "resume", None)
        if not callable(resume):
            raise BridgeError("turn_error", "Turn does not support resume")
        try:
            accepted = resume(response)
        except (TypeError, ValueError):
            # Core's PauseRequest.validate_response performs the authoritative
            # choice/permission/revision validation.  Do not clear pending on
            # any rejection.
            raise BridgeError("stale_response", "response was rejected for the pending interaction") from None
        except Exception:
            raise BridgeError("turn_error", "Turn resume failed") from None
        if not accepted:
            raise BridgeError("duplicate_response", "pending interaction was already answered")
        return {"accepted": True, "run": self._snapshot()}

    def _command_complete(self, params: Mapping[str, object]) -> dict[str, object]:
        _require_params(params, {"prefix"}, method="command.complete")
        prefix = params.get("prefix")
        if not isinstance(prefix, str):
            raise BridgeError("invalid_request", "prefix must be a string")
        if self._pending_pause() is not None:
            return {"candidates": [], "argument_candidates": [], "blocked": "interaction_pending"}
        try:
            invocation = self._parser.parse(prefix)
            candidates = self._completion.complete(prefix, application=self._application)
            argument_candidates = self._completion.argument_candidates(
                invocation,
                argument_index=_completion_argument_index(prefix, invocation),
                application=self._application,
            )
        except Exception:
            raise BridgeError("completion_error", "command completion unavailable") from None
        result_candidates: list[dict[str, object]] = []
        for candidate in candidates:
            projected = _completion_candidate(candidate)
            if projected is None:
                raise BridgeError("completion_error", "command completion unavailable")
            result_candidates.append(projected)
        projected_arguments = _strings(argument_candidates, non_empty=True)
        usage = _text(self._completion.usage_for(invocation), optional=True)
        argument_prompt = _text(self._completion.argument_prompt_for(invocation), optional=True)
        if projected_arguments is None or usage is _INVALID or argument_prompt is _INVALID:
            raise BridgeError("completion_error", "command completion unavailable")
        return {
            "candidates": result_candidates,
            "argument_candidates": projected_arguments,
            "usage": usage,
            "argument_prompt": argument_prompt,
        }

    async def _command_execute(self, params: Mapping[str, object]) -> dict[str, object]:
        _require_params(params, {"text"}, method="command.execute")
        text = _text_param(params, "text")
        if self._pending_pause() is not None:
            raise BridgeError("interaction_pending", "pending interaction captures this input")
        try:
            invocation = self._parser.parse(text)
        except Exception:
            raise BridgeError("invalid_request", "command text is invalid") from None
        if invocation.is_bare_slash:
            raise BridgeError("usage_error", "bare slash is not a command")
        canonical = invocation.canonical
        if self._active_handle is not None and canonical in _ACTIVE_COMMANDS:
            raise BridgeError("turn_active", f"/{canonical} is unavailable during an active Turn")
        candidate_run: object | None = None
        if (
            invocation.is_executable
            and canonical in _SESSION_CHANGING_COMMANDS
            and (canonical == "new" or bool(invocation.args))
        ):
            candidate_run = self._fresh_session_run(self._require_application())
        try:
            outcome = await self._dispatcher.dispatch_async(
                invocation,
                application=self._application,
            )
        except Exception:
            raise BridgeError("command_error", "command dispatch failed") from None
        if outcome is None:
            raise BridgeError("usage_error", "input is not a Slash command")
        result = self._command_result(outcome, invocation=invocation)
        action = outcome.ui_action
        if isinstance(action, SessionChanged):
            # Dispatcher owns the transactional Application Session switch;
            # the Bridge owns the associated fresh Run boundary.
            if candidate_run is None:
                # Built-in SessionChanged actions are covered by the
                # preflight above.  Do not create a Run after an arbitrary
                # dispatcher mutation, since that would reintroduce the
                # Session/Run mismatch this boundary prevents.
                raise BridgeError("session_error", "Session Run could not be prepared")
            self._run = candidate_run
        elif isinstance(action, BehaviorModeSelected):
            run = self._require_run()
            setter = getattr(run, "set_behavior_mode", None)
            if not callable(setter):
                raise BridgeError("command_error", "Run does not support behavior mode")
            try:
                setter(action.mode)
            except Exception:
                raise BridgeError("turn_active", "behavior mode cannot change during an active Turn") from None
        elif isinstance(action, PermissionModeSelected):
            run = self._require_run()
            setter = getattr(run, "set_permission_mode", None)
            if callable(setter):
                try:
                    setter(action.mode)
                except Exception:
                    raise BridgeError("command_error", "permission mode could not be selected") from None
        elif isinstance(action, QuitInterface):
            await self.shutdown(publish_state=True)
        # Build the params only after Application/UI actions have settled, so
        # Session and compaction projections describe the authoritative new
        # boundary.  The helper never inspects CommandOutcome.output/error.
        result["params"] = self._command_params(
            invocation.canonical,
            action,
            result["status"],
        )
        if isinstance(action, SessionChanged):
            params_value = result["params"]
            if isinstance(params_value, dict):
                params_value["replay"] = _replay_values(action.replay)
                params_value["run"] = self._snapshot()
        elif isinstance(action, PermissionModeSelected):
            params_value = result["params"]
            if isinstance(params_value, dict):
                params_value["run"] = self._snapshot()
        self._finalize_command_code(result)
        return result

    def _require_application(self) -> object:
        if self._application is None:
            raise BridgeError("application_required", "Application is not initialized")
        return self._application

    @staticmethod
    def _command_result(
        outcome: CommandOutcome,
        *,
        invocation: object | None = None,
    ) -> dict[str, object]:
        if not isinstance(outcome, CommandOutcome):
            raise BridgeError("command_error", "command result is invalid")
        status = _enum_value(outcome.status, OutcomeStatus)
        if status is _INVALID:
            raise BridgeError("command_error", "command result is invalid")
        source_invocation = invocation if invocation is not None else outcome.invocation
        canonical = getattr(source_invocation, "canonical", None)
        definition = getattr(source_invocation, "definition", None)
        command = canonical if isinstance(canonical, str) and definition is not None else "unknown"
        if status == OutcomeStatus.SUCCESS.value:
            code = "command_completed"
        elif status == OutcomeStatus.UNKNOWN_COMMAND.value:
            code = "command_unavailable"
        elif status == OutcomeStatus.USAGE_ERROR.value:
            code = "command_usage_error"
        else:
            code = "command_failed"
        return {
            "command": command,
            "status": status,
            "code": code,
            "params": {},
            "ui_action": _action_value(outcome.ui_action),
        }

    def _command_params(
        self,
        canonical: str | None,
        action: object | None,
        status: object,
    ) -> dict[str, object]:
        """Return the narrow, semantic params consumed by Desktop UI.

        Application command handlers intentionally continue to return their
        existing text for CLI/TUI.  This boundary does not parse or forward
        that text; known Desktop commands are projected from their canonical
        invocation, typed UI action, and existing safe status projection.
        """

        if status != OutcomeStatus.SUCCESS.value:
            return {}
        if canonical == "status":
            # `/status` and `status.get` must be the same safe source.  The
            # built-in command's diagnostic string is intentionally ignored.
            return self._status_result()
        if canonical == "help":
            # Desktop already exposes canonical command values through
            # `command.complete`; the current UI only needs the localized
            # semantic notice for `/help`.  Do not ship an unconsumed command
            # list that would become a second help contract.
            return {}
        if canonical == "compact":
            # Compaction result details are read from Application.status(),
            # never inferred from its localized handler output.
            try:
                status_result = self._status_result()
            except BridgeError:
                return {}
            application = status_result.get("application")
            if not isinstance(application, Mapping):
                return {}
            compaction = application.get("compaction_status")
            if not isinstance(compaction, Mapping):
                return {}
            projected = _json_safe(dict(compaction))
            return {"compaction_status": projected} if isinstance(projected, dict) else {}

        projected_action = _action_value(action)
        if not isinstance(projected_action, dict):
            return {}
        params = {
            key: value
            for key, value in projected_action.items()
            if key != "type"
        }
        projected = _json_safe(params)
        return projected if isinstance(projected, dict) else {}

    @staticmethod
    def _finalize_command_code(result: dict[str, object]) -> None:
        """Choose a stable result code without reading free-form text."""

        if result.get("status") != OutcomeStatus.SUCCESS.value:
            return
        command = result.get("command")
        action = result.get("ui_action")
        action_type = action.get("type") if isinstance(action, Mapping) else None
        if action_type == "clear_transcript":
            result["code"] = "transcript_cleared"
        elif action_type == "open_model_picker":
            result["code"] = "model_picker_opened"
        elif action_type == "open_permission_picker":
            result["code"] = "permission_picker_opened"
        elif action_type == "open_session_picker":
            result["code"] = "session_picker_opened"
        elif action_type == "model_selected":
            result["code"] = "model_selected"
        elif action_type == "behavior_mode_selected":
            result["code"] = "behavior_mode_selected"
        elif action_type == "permission_mode_selected":
            result["code"] = "permission_mode_selected"
        elif action_type == "session_changed":
            params = result.get("params")
            restored = params.get("restored") if isinstance(params, Mapping) else False
            result["code"] = "session_resumed" if restored is True else "session_created"
        elif action_type == "quit_interface":
            result["code"] = "interface_quit"
        elif command == "status":
            result["code"] = "status_ready"
        elif command == "compact":
            params = result.get("params")
            compaction = params.get("compaction_status") if isinstance(params, Mapping) else None
            state = compaction.get("state") if isinstance(compaction, Mapping) else None
            changed = compaction.get("changed") if isinstance(compaction, Mapping) else None
            if state == "no_change" or changed is False:
                result["code"] = "compact_no_change"
            elif state == "cancelled":
                result["code"] = "compact_cancelled"
            elif state == "failed":
                result["code"] = "compact_failed"
            else:
                result["code"] = "compact_completed"
        elif command == "help":
            result["code"] = "help_ready"

    async def _settings_save(self, params: Mapping[str, object]) -> dict[str, object]:
        configuration_fields = {
            "default_model",
            "default_permission_mode",
            "providers",
            "models",
            "provider_renames",
        }
        if "request" in params:
            _require_params(params, {"request"}, method="settings.save")
            request = params.get("request")
        else:
            extra = set(params) - configuration_fields
            if extra:
                raise BridgeError(
                    "invalid_request",
                    f"settings.save has unknown fields: {sorted(extra)!r}",
                )
            request = params
        self._ensure_no_active(method="settings.save")
        if not isinstance(request, Mapping):
            raise BridgeError("invalid_request", "request must be an object")
        try:
            # Constructing this DTO turns transient API keys into SecretValue;
            # neither its repr nor its safe projection contains the value.
            typed = UserConfigurationWriteRequest(**dict(request))
        except Exception:
            raise BridgeError("configuration_error", "configuration update is invalid") from None
        try:
            view = write_user_configuration(typed, home=self._home)
        except ConfigurationInitializationRequired:
            raise BridgeError("configuration_required", "user configuration is not initialized") from None
        except ConfigurationError:
            raise BridgeError("configuration_error", "configuration update could not be saved") from None
        except Exception:
            raise BridgeError("configuration_error", "configuration update could not be saved") from None
        return {"configuration": _configuration(view)}

    async def _settings_reveal_api_key(
        self,
        params: Mapping[str, object],
    ) -> dict[str, object]:
        """Return one explicitly requested saved key expression.

        This is the only Desktop response that may contain a configured API
        key expression.  The Application reader is user-config-only and does
        not resolve ``env:`` references or inspect Runtime Provider state.
        """

        _require_params(params, {"provider_profile_id"}, method="settings.reveal_api_key")
        provider_profile_id = _text_param(params, "provider_profile_id")
        try:
            value = read_user_api_key(
                provider_profile_id,
                home=self._home,
            )
        except ConfigurationInitializationRequired:
            raise BridgeError(
                "configuration_required",
                "user configuration is not initialized",
            ) from None
        except ConfigurationError:
            # Do not return provider IDs, paths, parser diagnostics, or any
            # exception text: all errors are intentionally secret-free.
            raise BridgeError(
                "configuration_error",
                "saved API key could not be read",
            ) from None
        except Exception:
            raise BridgeError(
                "configuration_error",
                "saved API key could not be read",
            ) from None
        return {"api_key": value}

    async def _consume_turn(self, handle: object) -> None:
        events = getattr(handle, "events", None)
        if not callable(events):
            self._publish(
                RuntimeStateEnvelope(
                    "failed",
                    ErrorPayload("turn_error", "Turn event stream unavailable"),
                )
            )
            self._active_handle = None
            return
        try:
            stream = events()
            async for event in stream:
                if not isinstance(event, AgentEvent):
                    raise RuntimeError("invalid event")
                payload = _event(event)
                if payload is None:
                    raise RuntimeError("invalid event projection")
                self._publish(AgentEventEnvelope(payload))
            result_method = getattr(handle, "result", None)
            if not callable(result_method):
                raise RuntimeError("Turn result unavailable")
            await result_method()
        except asyncio.CancelledError:
            raise
        except Exception:
            # Agent/Provider terminal failures are emitted by Application as
            # public AgentEvents.  This branch is strictly transport/runtime
            # failure and never exposes the exception payload.
            self._publish(
                RuntimeStateEnvelope(
                    "failed",
                    ErrorPayload("turn_runtime_error", "Turn runtime failed"),
                )
            )
        finally:
            if self._active_handle is handle:
                self._active_handle = None

    async def shutdown(self, *, publish_state: bool = False) -> None:
        if self._state == "stopped":
            return
        if publish_state:
            self._state = "stopping"
            self._publish(RuntimeStateEnvelope("stopping"))
        handle = self._active_handle
        if handle is not None:
            cancel = getattr(handle, "cancel", None)
            if callable(cancel):
                try:
                    cancel()
                except Exception:
                    pass
        task = self._turn_task
        if task is not None and not task.done():
            try:
                await asyncio.wait_for(asyncio.shield(task), self._shutdown_timeout)
            except asyncio.TimeoutError:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            except asyncio.CancelledError:
                raise
            except Exception:
                pass
        self._active_handle = None
        self._turn_task = None
        application = self._application
        if application is not None:
            close = getattr(application, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    self._state = "failed"
                    if publish_state:
                        self._publish(
                            RuntimeStateEnvelope(
                                "failed",
                                ErrorPayload("application_close_failed", "Application close failed"),
                            )
                        )
                    return
        self._state = "stopped"
        if publish_state:
            self._publish(RuntimeStateEnvelope("stopped"))

    async def serve_forever(
        self,
        *,
        stdin: TextIO | None = None,
        stdout: TextIO | None = None,
        stderr: TextIO | None = None,
    ) -> None:
        """Serve JSONL requests while independently flushing Agent events."""

        input_stream = sys.stdin if stdin is None else stdin
        output_stream = sys.stdout if stdout is None else stdout
        diagnostic_stream = sys.stderr if stderr is None else stderr
        self._outbox_signal = asyncio.Event()
        self._publish(RuntimeStateEnvelope("ready"))
        writer_done = asyncio.Event()

        async def writer() -> None:
            try:
                while True:
                    await self._outbox_signal.wait()
                    for envelope in self.drain_outbox():
                        try:
                            write_envelope(output_stream, envelope)
                        except Exception:
                            return
                    if self._state in {"stopped", "failed"} and not self._outbox:
                        return
            finally:
                writer_done.set()

        writer_task = asyncio.create_task(writer())
        try:
            while self._state not in {"stopped", "failed"}:
                try:
                    line = await asyncio.to_thread(input_stream.readline)
                except Exception:
                    self._publish(
                        error_response(
                            None,
                            "transport_error",
                            "Desktop input could not be read",
                        )
                    )
                    break
                if line == "":
                    break
                if not line.strip():
                    self._publish(error_response(None, "invalid_json", "JSONL line is empty"))
                    continue
                try:
                    request = parse_request_line(line)
                    response = await self.handle_request(request)
                except ProtocolError as exc:
                    self._publish(error_response(exc.request_id, exc.kind, exc.message))
                except Exception:
                    self._publish(error_response(None, "protocol_error", "Desktop request could not be processed"))
                else:
                    self._publish(response)
                if self._state == "stopped":
                    break
        finally:
            if self._state not in {"stopped", "failed"}:
                await self.shutdown(publish_state=True)
            # Let the writer flush terminal lifecycle and pending AgentEvent
            # envelopes, but never let a broken output pipe hang shutdown.
            try:
                await asyncio.wait_for(asyncio.shield(writer_done.wait()), self._shutdown_timeout)
            except asyncio.TimeoutError:
                pass
            if not writer_task.done():
                writer_task.cancel()
                await asyncio.gather(writer_task, return_exceptions=True)
            if self._outbox:
                # If the output stream closed, keep diagnostics on stderr only
                # and never print an unframed line to stdout.
                try:
                    diagnostic_stream.write("desktop bridge output closed\n")
                    diagnostic_stream.flush()
                except Exception:
                    pass


__all__ = ["BridgeError", "DesktopBridge"]
