"""Headless generation use cases built on the Core Provider Port."""

from __future__ import annotations

from asyncio import CancelledError
import inspect
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from uthcode.core.agent import (
    AgentLoop,
    AgentTurnExecution,
    PermissionResolver,
    RunState,
    SessionGrantSink,
)
from uthcode.core.interaction import ASK_USER_TOOL_DEFINITION
from uthcode.core.planning import (
    BehaviorMode,
    PROPOSE_PLAN_TOOL_DEFINITION,
    TODO_WRITE_TOOL_DEFINITION,
)
from uthcode.core.provider import (
    CancellationToken,
    ContextOverflowError,
    GenerationCompleted,
    GenerationCancelled,
    GenerationRequest,
    InvalidProviderResponseError,
    Message,
    ModelLimits,
    ProviderConfigurationError,
    ProviderError,
    ProviderEvent,
    ProviderIdentity,
    ProviderPort,
    ReasoningOptions,
    ToolCallPart,
    ToolDefinition,
    ToolResultPart,
    Usage,
    validated_provider_stream,
)
from uthcode.core.history import TranscriptEntry
from uthcode.core.prompt import (
    ContextAuthority,
    ContextBlock,
    ContextScope,
    ContextSourceKind,
    ContextStability,
    EnvironmentSource,
    RuntimePromptContext,
)
from uthcode.core.context import (
    CompactionResult,
    ContextBudget,
    ContextBudgetError,
    ContextCountEstimate,
    ContextRequestSafetyError,
    ContextUsage,
    resolve_context_budget,
)
from uthcode.core.permission import PermissionEvaluator, PermissionMode, RuleSet

from .configuration import ConfigSource, EffectiveConfig, ModelProfile, ProviderProfile
from .context import ApplicationContextService
from .instructions import InstructionLoader
from .history import transcript_entries_for_message
from .runtime_context import ApplicationRuntimeContext
from .sessions import (
    ApplicationSession,
    ApplicationSessionService,
    TimelineAppendOutcome,
    TranscriptAppendOutcome,
    SessionCatalogEntry,
)
from .tools import ApplicationToolService
from .provider_usage import public_usage_diagnostics


ProviderBuilder = Callable[[ProviderProfile, ModelProfile], ProviderPort]
ModelWriter = Callable[[str], object]
PermissionWriter = Callable[[PermissionMode], object]
PermissionRulesLoader = Callable[[], RuleSet]


def _reasoning_options(effort: str | None) -> ReasoningOptions | None:
    if effort is None:
        return None
    return ReasoningOptions(enabled=effort != "none", effort=effort)


def _validate_model_limits(value: object) -> ModelLimits | None:
    if value is not None and not isinstance(value, ModelLimits):
        raise TypeError("Provider model limits must be ModelLimits or None")
    return value


def _resolve_model_limits_sync(
    provider: ProviderPort,
    model: str,
) -> ModelLimits | None:
    resolver = getattr(provider, "resolve_model_limits", None)
    if not callable(resolver):
        return None
    value = resolver(model)
    if inspect.isawaitable(value):
        # A synchronous start_generation cannot safely run an async metadata
        # operation.  Close coroutine objects to avoid an un-awaited warning;
        # the configured limit, if present, remains usable for this path.
        close = getattr(value, "close", None)
        if callable(close):
            close()
        return None
    return _validate_model_limits(value)


async def _resolve_model_limits_async(
    provider: ProviderPort,
    model: str,
) -> ModelLimits | None:
    resolver = getattr(provider, "resolve_model_limits", None)
    if not callable(resolver):
        return None
    value = resolver(model)
    if inspect.isawaitable(value):
        value = await value
    return _validate_model_limits(value)


def _validate_provider_count(value: object) -> ContextCountEstimate | int | None:
    if value is not None and not isinstance(value, (ContextCountEstimate, int)):
        raise TypeError(
            "Provider input count must be ContextCountEstimate, int, or None"
        )
    if isinstance(value, bool):
        raise TypeError("Provider input count must not be boolean")
    return value


def _request_reduction_levels(request: GenerationRequest) -> tuple[str, ...]:
    raw = request.metadata.get("context_reduction_levels", ())
    if isinstance(raw, (str, bytes, bytearray)) or not isinstance(raw, Sequence):
        return ()
    return tuple(value for value in raw if isinstance(value, str) and value)


@dataclass(frozen=True, slots=True)
class _CountResolution:
    value: ContextCountEstimate | int | None
    fallback_reason: str | None = None


def _is_controlled_count_failure(error: Exception) -> bool:
    """Return whether a count endpoint outage may use the local estimate.

    Type/value errors, provider configuration errors, malformed responses and
    limit/overflow authority errors must remain visible to the request
    preparer.  Only operational unavailability is eligible for a conservative
    local fallback.
    """

    if isinstance(
        error,
        (
            TypeError,
            ValueError,
            ContextBudgetError,
            ProviderConfigurationError,
            ContextOverflowError,
            InvalidProviderResponseError,
            GenerationCancelled,
        ),
    ):
        return False
    return isinstance(error, (ProviderError, OSError, TimeoutError))


def _count_input_tokens_sync(
    provider: ProviderPort,
    request: GenerationRequest,
) -> _CountResolution:
    counter = getattr(provider, "count_input_tokens", None)
    if not callable(counter):
        return _CountResolution(None, "capability_missing")
    try:
        value = counter(request)
    except (GenerationCancelled, CancelledError):
        raise
    except Exception as exc:
        if _is_controlled_count_failure(exc):
            return _CountResolution(None, "provider_count_failure")
        raise
    if inspect.isawaitable(value):
        close = getattr(value, "close", None)
        if callable(close):
            close()
        return _CountResolution(None, "capability_unavailable")
    validated = _validate_provider_count(value)
    if validated is None:
        return _CountResolution(None, "provider_count_unavailable")
    return _CountResolution(validated)


async def _count_input_tokens_async(
    provider: ProviderPort,
    request: GenerationRequest,
) -> _CountResolution:
    counter = getattr(provider, "count_input_tokens", None)
    if not callable(counter):
        return _CountResolution(None, "capability_missing")
    try:
        value = counter(request)
        while inspect.isawaitable(value):
            value = await value
    except (GenerationCancelled, CancelledError):
        raise
    except Exception as exc:
        if _is_controlled_count_failure(exc):
            return _CountResolution(None, "provider_count_failure")
        raise
    validated = _validate_provider_count(value)
    if validated is None:
        return _CountResolution(None, "provider_count_unavailable")
    return _CountResolution(validated)


def _prepare_counted_request_sync(
    provider: ProviderPort,
    compose: Callable[[ContextCountEstimate | int | None, bool, str | None], GenerationRequest],
    finalize: Callable[
        [GenerationRequest, ContextCountEstimate | int | None, bool, str | None],
        GenerationRequest,
    ],
) -> GenerationRequest:
    """Count, rebuild and re-gate until one exact request is ready to send."""

    counted_request = compose(None, True, None)
    resolution = _count_input_tokens_sync(provider, counted_request)
    if resolution.fallback_reason is not None:
        return compose(None, False, resolution.fallback_reason)

    provider_count = resolution.value
    rebuild_from_sources = True
    for _ in range(8):
        if rebuild_from_sources:
            candidate = compose(provider_count, True, None)
            if candidate != counted_request:
                counted_request = candidate
                resolution = _count_input_tokens_sync(provider, counted_request)
                if resolution.fallback_reason is not None:
                    return compose(None, False, resolution.fallback_reason)
                provider_count = resolution.value
            rebuild_from_sources = False

        final_request = finalize(counted_request, provider_count, False, None)
        if final_request == counted_request:
            # Return the exact immutable object that the Provider just counted.
            # Equality is sufficient for semantics, while identity makes the
            # count/send correspondence explicit for request-capturing ports.
            return counted_request
        counted_request = final_request
        resolution = _count_input_tokens_sync(provider, counted_request)
        if resolution.fallback_reason is not None:
            return compose(None, False, resolution.fallback_reason)
        provider_count = resolution.value

    raise ContextRequestSafetyError(
        "Provider input count did not stabilize for the final request"
    )


async def _prepare_counted_request_async(
    provider: ProviderPort,
    compose: Callable[[ContextCountEstimate | int | None, bool, str | None], GenerationRequest],
    finalize: Callable[
        [GenerationRequest, ContextCountEstimate | int | None, bool, str | None],
        GenerationRequest,
    ],
) -> GenerationRequest:
    """Async counterpart of the exact final-request count/re-gate loop."""

    counted_request = compose(None, True, None)
    resolution = await _count_input_tokens_async(provider, counted_request)
    if resolution.fallback_reason is not None:
        return compose(None, False, resolution.fallback_reason)

    provider_count = resolution.value
    rebuild_from_sources = True
    for _ in range(8):
        if rebuild_from_sources:
            candidate = compose(provider_count, True, None)
            if candidate != counted_request:
                counted_request = candidate
                resolution = await _count_input_tokens_async(provider, counted_request)
                if resolution.fallback_reason is not None:
                    return compose(None, False, resolution.fallback_reason)
                provider_count = resolution.value
            rebuild_from_sources = False

        final_request = finalize(counted_request, provider_count, False, None)
        if final_request == counted_request:
            return counted_request
        counted_request = final_request
        resolution = await _count_input_tokens_async(provider, counted_request)
        if resolution.fallback_reason is not None:
            return compose(None, False, resolution.fallback_reason)
        provider_count = resolution.value

    raise ContextRequestSafetyError(
        "Provider input count did not stabilize for the final request"
    )


@dataclass(frozen=True, slots=True)
class ApplicationStatus:
    """Safe read-only runtime status for interfaces and headless callers."""

    current_model: str
    provider_profile: str
    provider_identity: ProviderIdentity
    configuration_sources: tuple[ConfigSource, ...]
    state: str = "ready"
    context_usage: ContextUsage = ContextUsage(0, available=False)
    timeline_checkpoint_id: str | None = None
    instruction_epoch: int = 0
    compact_count: int = 0
    stable_prefix_fingerprint: str | None = None
    prefix_changed: bool | None = None
    prefix_change_reason: str | None = None
    tool_schema_fingerprint: str | None = None
    diagnostics: Mapping[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "current_model": self.current_model,
            "provider_profile": self.provider_profile,
            "provider_identity": self.provider_identity.to_dict(),
            "configuration_sources": [
                {
                    "kind": source.kind,
                    "path": str(source.path) if source.path is not None else None,
                }
                for source in self.configuration_sources
            ],
            "state": self.state,
            "context_usage": self.context_usage.to_dict(),
            "timeline_checkpoint_id": self.timeline_checkpoint_id,
            "instruction_epoch": self.instruction_epoch,
            "compact_count": self.compact_count,
            "stable_prefix_fingerprint": self.stable_prefix_fingerprint,
            "prefix_changed": self.prefix_changed,
            "prefix_change_reason": self.prefix_change_reason,
            "tool_schema_fingerprint": self.tool_schema_fingerprint,
            "diagnostics": dict(self.diagnostics),
        }


@dataclass(frozen=True, slots=True)
class TranscriptPersistenceOutcome:
    """Describe the two durable boundaries of one terminal Run delta."""

    transcript_appended: bool
    instruction_state_synced: bool
    failure_stage: str | None
    persisted_message_count: int
    transcript_metadata_synced: bool = True
    transcript_reload_succeeded: bool = True
    transcript_durability: str = "durable"
    failure_stages: tuple[str, ...] = ()

    @property
    def status(self) -> str:
        if (
            self.transcript_appended
            and self.instruction_state_synced
            and self.transcript_metadata_synced
            and self.transcript_durability == "durable"
            and not self.failure_stages
        ):
            return "committed"
        if self.transcript_appended:
            return "partial"
        if self.failure_stage is None:
            return "not_available"
        return "failed"

    @property
    def error_code(self) -> str | None:
        return {
            "transcript_append": "transcript_persistence_failed",
            "transcript_append_reconciled": "transcript_append_reconciled",
            "transcript_reload": "transcript_reload_failed",
            "transcript_metadata_sync": "transcript_metadata_sync_failed",
            "transcript_durability_unknown": "transcript_durability_unknown",
            "instruction_state_sync": "instruction_state_sync_failed",
            "session_boundary": "session_boundary",
            "invalid_message": "invalid_message",
        }.get(self.failure_stage)


class GenerationHandle:
    """One independently cancellable Application generation."""

    __slots__ = (
        "_application",
        "_provider",
        "_request",
        "_cancellation",
        "_started",
    )

    def __init__(
        self,
        application: UthCodeApplication,
        provider: ProviderPort,
        request: GenerationRequest,
        cancellation: CancellationToken,
    ) -> None:
        self._application = application
        self._provider = provider
        self._request = request
        self._cancellation = cancellation
        self._started = False

    @property
    def cancelled(self) -> bool:
        return self._cancellation.cancelled

    def cancel(self) -> bool:
        """Cancel this handle once; repeated calls are harmless."""

        return self._cancellation.cancel()

    async def events(self) -> AsyncIterator[ProviderEvent]:
        if self._started:
            raise RuntimeError("GenerationHandle.events() can only be consumed once")
        self._started = True
        async for event in self._application._stream_with_token(
            self._provider,
            self._request,
            self._cancellation,
        ):
            yield event


class UthCodeApplication:
    """Application boundary for configuration-backed provider generation."""

    def __init__(
        self,
        provider: ProviderPort,
        *,
        configuration: EffectiveConfig | None = None,
        provider_builder: ProviderBuilder | None = None,
        model_writer: ModelWriter | None = None,
        permission_writer: PermissionWriter | None = None,
        runtime_context: ApplicationRuntimeContext | None = None,
        tool_service: ApplicationToolService | None = None,
        permission_rules_loader: PermissionRulesLoader | None = None,
        instruction_loader: InstructionLoader | None = None,
        context_service: ApplicationContextService | None = None,
        session_service: ApplicationSessionService | None = None,
    ) -> None:
        self._provider = provider
        self._configuration = configuration
        self._provider_builder = provider_builder
        self._model_writer = model_writer
        self._permission_writer = permission_writer
        self._default_permission_mode = (
            configuration.default_permission_mode
            if configuration is not None
            else PermissionMode.DEFAULT
        )
        if runtime_context is None:
            runtime_context = ApplicationRuntimeContext.from_system()
        if not isinstance(runtime_context, ApplicationRuntimeContext):
            raise TypeError("runtime_context must be ApplicationRuntimeContext")
        self._runtime_context = runtime_context
        if tool_service is None:
            tool_service = ApplicationToolService(())
        if not isinstance(tool_service, ApplicationToolService):
            raise TypeError("tool_service must be an ApplicationToolService")
        if permission_rules_loader is not None and not callable(permission_rules_loader):
            raise TypeError("permission_rules_loader must be callable or None")
        if instruction_loader is not None and not isinstance(instruction_loader, InstructionLoader):
            raise TypeError("instruction_loader must be InstructionLoader or None")
        if context_service is not None and not isinstance(context_service, ApplicationContextService):
            raise TypeError("context_service must be ApplicationContextService or None")
        if session_service is not None and not isinstance(session_service, ApplicationSessionService):
            raise TypeError("session_service must be ApplicationSessionService or None")
        self._tool_service = tool_service
        self._permission_rules_loader = permission_rules_loader
        self._instruction_loader = instruction_loader
        self._context_service = context_service or ApplicationContextService()
        self._session_service = session_service
        self._provider_usage_diagnostics = public_usage_diagnostics(None)
        self._history_persistence_diagnostics: dict[str, object] = {
            "status": "not_available",
            "transcript_appended": False,
            "instruction_state_synced": False,
            "transcript_metadata_synced": False,
            "transcript_reload_succeeded": False,
            "transcript_durability": "not_available",
            "failure_stage": None,
            "failure_stages": [],
            "persisted_message_count": 0,
            "committed_turns": 0,
            "error_code": None,
        }
        if self._instruction_loader is not None:
            # Application construction may collect diagnostics for the
            # interactive shell.  Formal create/resume/refresh boundaries
            # below rebuild with strict=True before a Session becomes active,
            # so this diagnostic prefix is never persisted or adopted there.
            self._instruction_loader.load_session(strict=False)
        self._current_model_ref = (
            configuration.default_model
            if configuration is not None
            else provider.identity.model
        )

    @property
    def provider(self) -> ProviderPort:
        return self._provider

    @property
    def configuration(self) -> EffectiveConfig | None:
        return self._configuration

    @property
    def runtime_context(self) -> ApplicationRuntimeContext:
        return self._runtime_context

    @property
    def instruction_loader(self) -> InstructionLoader | None:
        """Return the Application-owned current instruction state service."""

        return self._instruction_loader

    @property
    def context_service(self) -> ApplicationContextService:
        """Return the Application-owned Context composition service."""

        return self._context_service

    @property
    def session_service(self) -> ApplicationSessionService | None:
        """Return the optional durable Session lifecycle service."""

        return self._session_service

    @property
    def current_model_ref(self) -> str:
        return self._current_model_ref

    @property
    def current_model(self) -> ModelProfile | None:
        if self._configuration is None:
            return None
        return self._configuration.models[self._current_model_ref]

    @property
    def current_provider_profile(self) -> ProviderProfile | None:
        model = self.current_model
        if model is None or self._configuration is None:
            return None
        return self._configuration.providers[model.provider_profile_id]

    def model_catalog(self) -> tuple[ModelProfile, ...]:
        if self._configuration is None:
            return ()
        return self._configuration.model_catalog()

    def tool_definitions(self) -> tuple[ToolDefinition, ...]:
        """Return the Application's immutable, ordered Tool definitions."""

        return self._tool_service.definitions()

    def compile_context(self, **kwargs: Any):
        """Compile a dynamic Context Snapshot from current sources."""

        if "instruction_loader" not in kwargs:
            kwargs["instruction_loader"] = self._instruction_loader
        if "tool_definitions" not in kwargs:
            kwargs["tool_definitions"] = self.tool_definitions()
        return self._context_service.compile(**kwargs)

    def context_usage(self, snapshot=None):
        """Return the same dynamic usage projection for headless callers."""

        return self._context_service.usage(snapshot)

    def create_session(self, session_id: str | None = None) -> ApplicationSession:
        if self._session_service is None:
            raise RuntimeError("durable Session storage is not configured")
        return self._session_service.create_session(session_id)

    def ensure_session(self) -> ApplicationSession | None:
        """Open a fresh durable Session for an interactive entry point."""

        if self._session_service is None:
            return None
        active = self._session_service.active_session
        if active is not None:
            return active
        return self.new_session_for_command()

    def resume_session(self, session_id: str) -> ApplicationSession:
        if self._session_service is None:
            raise RuntimeError("durable Session storage is not configured")
        return self._session_service.resume_session(session_id)

    def session_catalog(self) -> tuple[SessionCatalogEntry, ...]:
        """Return the Application-owned same-project Session Picker data."""

        if self._session_service is None:
            return ()
        return self._session_service.list_catalog()

    def new_session_for_command(self) -> ApplicationSession:
        """Create and commit a fresh Session only after staging succeeds."""

        if self._session_service is None:
            raise RuntimeError("durable Session storage is not configured")
        session = self._session_service.create_session_for_command()
        self._refresh_context_for_session(session)
        return session

    def resume_session_for_command(self, session_id: str) -> ApplicationSession:
        """Lock/recover the target before committing the Session switch."""

        if self._session_service is None:
            raise RuntimeError("durable Session storage is not configured")
        session = self._session_service.resume_session_for_command(session_id)
        self._refresh_context_for_session(session)
        return session

    def compact_session(
        self,
        *,
        summarize: Callable[[str], str] | None = None,
    ) -> CompactionResult:
        """Compact the active Session without mutating its Transcript."""

        if self._session_service is None:
            raise RuntimeError("durable Session storage is not configured")
        session = self._session_service.active_session
        if session is None:
            raise RuntimeError("no active Session")
        result = self._context_service.compact(
            session.transcript,
            timeline=session.timeline,
            session_id=session.session_id,
            summarize=summarize,
        )
        if result.changed and result.timeline is not None:
            result = self._commit_timeline_candidate(session, result)
        return result

    def _commit_timeline_candidate(
        self,
        session: ApplicationSession,
        result: CompactionResult,
    ) -> CompactionResult:
        """Commit a Timeline candidate without confusing persistence failure with success."""

        def finish(final: CompactionResult) -> CompactionResult:
            self._context_service.finalize_compaction(final)
            return final

        candidate = result.timeline
        if candidate is None:
            return finish(result)
        try:
            outcome = session.append_timeline(candidate)
        except Exception:
            # Validation or a pre-append failure means no Timeline was
            # committed.  The writer remains the authority for whether a
            # retry is safe; do not expose the in-memory candidate as active.
            return finish(replace(
                result,
                timeline=session.timeline,
                summary=(session.timeline.summary if session.timeline is not None else None),
                changed=False,
                failure="timeline_append_failed",
            ))
        if not isinstance(outcome, TimelineAppendOutcome):
            session._quarantine_unknown_durability()
            return finish(replace(
                result,
                timeline=session.timeline,
                summary=(session.timeline.summary if session.timeline is not None else None),
                changed=False,
                failure="timeline_durability_unknown",
            ))
        if outcome.durability == "unknown":
            return finish(replace(
                result,
                timeline=session.timeline,
                summary=(session.timeline.summary if session.timeline is not None else None),
                changed=False,
                failure="timeline_durability_unknown",
            ))
        if not outcome.timeline_appended:
            return finish(replace(
                result,
                timeline=session.timeline,
                summary=(session.timeline.summary if session.timeline is not None else None),
                changed=False,
                failure=outcome.failure_stage or "timeline_append_failed",
            ))
        self._refresh_context_for_session(session)
        return finish(result)

    def list_sessions(self):
        if self._session_service is None:
            return ()
        return self._session_service.list_sessions()

    def close(self) -> None:
        """Release any Application-held Session writer lock."""

        if self._session_service is not None:
            self._session_service.close()

    def create_run(self, *, run_id: str | None = None) -> AgentRun:
        """Create one isolated in-memory Agent Run."""

        from .runs import AgentRun

        return AgentRun(
            self,
            run_id=run_id,
            permission_evaluator=self._permission_evaluator_for_run(),
            permission_mode=self._default_permission_mode,
        )

    def _require_run_start_allowed(self) -> None:
        """Reject Provider work while the active Session writer is quarantined."""

        if self._session_service is None:
            return
        active = self._session_service.active_session
        if active is not None and active.durability_unknown:
            raise RuntimeError(
                "Session History durability is unknown; close and reopen the "
                "Session to reconcile before starting a new Turn"
            )

    @property
    def default_permission_mode(self) -> PermissionMode:
        return self._default_permission_mode

    def set_default_permission_mode(self, mode: PermissionMode | str) -> PermissionMode:
        if not isinstance(mode, PermissionMode):
            mode = PermissionMode(mode)
        if mode is PermissionMode.FULL_ACCESS:
            raise ValueError("full_access cannot be an Application default")
        if self._permission_writer is None:
            raise RuntimeError("permission selection has no user configuration writer")
        self._permission_writer(mode)
        self._default_permission_mode = mode
        return mode

    def _permission_evaluator_for_run(self) -> PermissionEvaluator:
        """Load exactly one immutable permission snapshot for a new Run."""

        if self._permission_rules_loader is None:
            return PermissionEvaluator()
        rules = self._permission_rules_loader()
        if not isinstance(rules, RuleSet):
            raise TypeError("permission_rules_loader must return a RuleSet")
        return PermissionEvaluator(rules)

    async def execute_tool_calls(
        self,
        calls: Sequence[ToolCallPart],
        *,
        cancellation: CancellationToken | None = None,
    ) -> tuple[ToolResultPart, ...]:
        """Reject the manual Tool path at the Application boundary.

        Ordinary Tool execution needs a Run-local mode, RuleSet snapshot and
        T06 pause/resume channel.  This API has none of those contracts, so
        accepting a call here would create a permission bypass.  Callers must
        use ``create_run().start_turn()`` instead.
        """

        del calls, cancellation
        raise ValueError(
            "manual Tool execution is disabled; use AgentRun.start_turn"
        )

    def diagnostics(self) -> dict[str, object]:
        """Return the safe public diagnostics projection for Eval and UIs."""

        context = self._context_service.public_diagnostics()
        tools = self._tool_service.public_diagnostics()
        session = (
            self._session_service.public_diagnostics()
            if self._session_service is not None
            else {
                "schema_version": 1,
                "status": "not_available",
                "active": False,
                "active_session_id": None,
                "recovery_diagnostics": [],
                "last_operation": None,
                "busy": False,
            }
        )
        return {
            "schema_version": 1,
            "context": context.get("context", {"status": "not_available"}),
            "compaction": context.get("compaction", {"count": 0, "events": []}),
            "externalization": tools.get(
                "externalization", {"status": "not_available"}
            ),
            "session": session,
            "provider_usage": dict(self._provider_usage_diagnostics),
            "history_persistence": dict(self._history_persistence_diagnostics),
        }

    def _active_session_id(self) -> str | None:
        if self._session_service is None:
            return None
        active = self._session_service.active_session
        return None if active is None else active.session_id

    def _persist_run_messages(
        self,
        messages: Sequence[Message],
        *,
        session_id: str | None,
        turn_id: str,
    ) -> TranscriptPersistenceOutcome:
        """Commit one terminal Run delta through separate durable boundaries."""

        if session_id is None or self._session_service is None:
            return TranscriptPersistenceOutcome(
                False,
                False,
                None,
                0,
                transcript_durability="not_available",
            )
        active = self._session_service.active_session
        if active is None or active.session_id != session_id:
            outcome = TranscriptPersistenceOutcome(
                False,
                False,
                "session_boundary",
                0,
                transcript_metadata_synced=False,
                transcript_reload_succeeded=False,
                transcript_durability="not_durable",
                failure_stages=("session_boundary",),
            )
            self._record_transcript_persistence(outcome)
            return outcome
        if active.durability_unknown:
            outcome = TranscriptPersistenceOutcome(
                False,
                False,
                "transcript_durability_unknown",
                0,
                transcript_metadata_synced=False,
                transcript_reload_succeeded=False,
                transcript_durability="unknown",
                failure_stages=("transcript_durability_unknown",),
            )
            self._record_transcript_persistence(outcome)
            return outcome
        if not all(isinstance(message, Message) for message in messages):
            outcome = TranscriptPersistenceOutcome(
                False,
                False,
                "invalid_message",
                0,
                transcript_metadata_synced=False,
                transcript_reload_succeeded=False,
                transcript_durability="not_durable",
                failure_stages=("invalid_message",),
            )
            self._record_transcript_persistence(outcome)
            return outcome

        entries: list[TranscriptEntry] = []
        try:
            sequence = active.transcript.last_sequence + 1
            for message in messages:
                converted = transcript_entries_for_message(
                    active.session_id,
                    turn_id,
                    sequence,
                    message,
                )
                entries.extend(converted)
                sequence += len(converted)
            if entries:
                append_outcome = active.append_transcript(tuple(entries))
        except Exception:
            outcome = TranscriptPersistenceOutcome(
                False,
                False,
                "transcript_append",
                0,
                transcript_metadata_synced=False,
                transcript_reload_succeeded=False,
                transcript_durability="not_durable",
                failure_stages=("transcript_append",),
            )
            self._record_transcript_persistence(outcome)
            return outcome

        if not isinstance(append_outcome, TranscriptAppendOutcome):
            active._quarantine_unknown_durability()
            outcome = TranscriptPersistenceOutcome(
                False,
                False,
                "transcript_durability_unknown",
                0,
                transcript_metadata_synced=False,
                transcript_reload_succeeded=False,
                transcript_durability="unknown",
                failure_stages=("transcript_durability_unknown",),
            )
            self._record_transcript_persistence(outcome)
            return outcome
        if append_outcome.durability == "unknown":
            active._quarantine_unknown_durability()
            outcome = TranscriptPersistenceOutcome(
                False,
                False,
                "transcript_durability_unknown",
                0,
                transcript_metadata_synced=False,
                transcript_reload_succeeded=append_outcome.reload_succeeded,
                transcript_durability="unknown",
                failure_stages=("transcript_durability_unknown",),
            )
            self._record_transcript_persistence(outcome)
            return outcome
        if not append_outcome.transcript_appended:
            failure_stage = append_outcome.failure_stage or "transcript_append"
            outcome = TranscriptPersistenceOutcome(
                False,
                False,
                failure_stage,
                0,
                transcript_metadata_synced=False,
                transcript_reload_succeeded=append_outcome.reload_succeeded,
                transcript_durability=append_outcome.durability,
                failure_stages=(failure_stage,),
            )
            self._record_transcript_persistence(outcome)
            return outcome

        append_failures = (
            (append_outcome.failure_stage,)
            if append_outcome.failure_stage is not None
            else ()
        )
        transcript_outcome = TranscriptPersistenceOutcome(
            True,
            False,
            append_outcome.failure_stage or "instruction_state_sync",
            len(messages),
            transcript_metadata_synced=append_outcome.metadata_synced,
            transcript_reload_succeeded=append_outcome.reload_succeeded,
            transcript_durability=append_outcome.durability,
            failure_stages=append_failures,
        )
        try:
            active.persist_instruction_state()
        except Exception:
            failure_stages = append_failures + ("instruction_state_sync",)
            outcome = replace(
                transcript_outcome,
                failure_stage=append_outcome.failure_stage or "instruction_state_sync",
                failure_stages=failure_stages,
            )
            self._record_transcript_persistence(outcome)
            return outcome

        outcome = replace(
            transcript_outcome,
            instruction_state_synced=True,
            failure_stage=append_outcome.failure_stage,
            failure_stages=append_failures,
        )
        self._record_transcript_persistence(outcome)
        return outcome

    def _record_transcript_persistence(
        self,
        outcome: TranscriptPersistenceOutcome,
    ) -> None:
        self._history_persistence_diagnostics = {
            "status": outcome.status,
            "transcript_appended": outcome.transcript_appended,
            "instruction_state_synced": outcome.instruction_state_synced,
            "transcript_metadata_synced": outcome.transcript_metadata_synced,
            "transcript_reload_succeeded": outcome.transcript_reload_succeeded,
            "transcript_durability": outcome.transcript_durability,
            "failure_stage": outcome.failure_stage,
            "failure_stages": list(outcome.failure_stages),
            "persisted_message_count": outcome.persisted_message_count,
            "committed_turns": int(
                self._history_persistence_diagnostics.get("committed_turns", 0)
            ) + (1 if outcome.transcript_appended and outcome.persisted_message_count else 0),
            "error_code": outcome.error_code,
        }

    def _record_formal_run_usage(self, usage: Usage) -> None:
        """Project one terminal AgentRun's observed cumulative Usage.

        ``AgentRun`` owns the terminal-result boundary, while this Application
        method owns the diagnostics state.  A terminal Turn with no observed
        Provider Usage does not erase the last observable projection, so
        cancel/failure paths cannot manufacture a measurement or hide a prior
        one merely by constructing an empty default ``Usage``.
        """

        projection = public_usage_diagnostics(usage)
        if projection.get("status") == "available":
            self._provider_usage_diagnostics = projection

    def status(self) -> ApplicationStatus:
        profile = self.current_provider_profile
        provider_profile_id = (
            profile.provider_profile_id
            if profile is not None
            else self._provider.identity.provider
        )
        sources = self._configuration.sources if self._configuration is not None else ()
        snapshot = self._context_service.last_snapshot
        usage = self._context_service.usage(snapshot)
        active = (
            self._session_service.active_session
            if self._session_service is not None
            else None
        )
        timeline_checkpoint_id = (
            snapshot.timeline_checkpoint_id
            if snapshot is not None
            else (
                active.timeline.active_checkpoint.turn_id
                if active and active.timeline.active_checkpoint is not None
                else None
            )
        )
        instruction_epoch = (
            snapshot.instruction_epoch
            if snapshot is not None
            else (
                self._instruction_loader.instruction_epoch
                if self._instruction_loader is not None
                else 0
            )
        )
        stable_prefix_fingerprint = (
            snapshot.stable_prefix_fingerprint
            if snapshot is not None
            else (
                self._instruction_loader.stable_prefix_fingerprint
                if self._instruction_loader is not None
                else None
            )
        )
        prefix_changed = snapshot.prefix_changed if snapshot is not None else None
        prefix_change_reason = (
            snapshot.prefix_change_reason if snapshot is not None else None
        )
        tool_schema_fingerprint = (
            snapshot.tool_schema_fingerprint if snapshot is not None else None
        )
        diagnostics = self.diagnostics()
        compaction = diagnostics.get("compaction")
        compact_count = (
            compaction.get("count", 0)
            if isinstance(compaction, Mapping)
            else 0
        )
        return ApplicationStatus(
            current_model=self._current_model_ref,
            provider_profile=provider_profile_id,
            provider_identity=self._provider.identity,
            configuration_sources=sources,
            context_usage=usage,
            timeline_checkpoint_id=timeline_checkpoint_id,
            instruction_epoch=instruction_epoch,
            compact_count=compact_count if isinstance(compact_count, int) else 0,
            stable_prefix_fingerprint=stable_prefix_fingerprint,
            prefix_changed=prefix_changed,
            prefix_change_reason=prefix_change_reason,
            tool_schema_fingerprint=tool_schema_fingerprint,
            diagnostics=diagnostics,
        )

    def _refresh_context_for_session(self, session: ApplicationSession) -> None:
        """Refresh the stable Application usage projection at a Session boundary."""

        self._context_service.compile(
            instruction_loader=self._instruction_loader,
            transcript=session.transcript,
            timeline=session.timeline,
            tool_definitions=self.tool_definitions(),
        )

    def select_model(self, model_ref: str) -> ModelProfile:
        """Switch Provider and model only after candidate and persistence succeed."""

        if self._configuration is None:
            raise ValueError("model selection requires an EffectiveConfig")
        if not isinstance(model_ref, str) or not model_ref.strip():
            raise ValueError("model_ref must be a non-empty string")
        candidate_model = self._configuration.models.get(model_ref)
        if candidate_model is None:
            raise ValueError(f"unknown model reference: {model_ref!r}")
        if self._provider_builder is None:
            raise RuntimeError("model selection has no Provider builder")
        candidate_provider = self._provider_builder(
            self._configuration.providers[candidate_model.provider_profile_id],
            candidate_model,
        )
        if not isinstance(candidate_provider, ProviderPort):
            raise TypeError("Provider builder must return a ProviderPort")
        if self._model_writer is not None:
            self._model_writer(model_ref)
        self._provider = candidate_provider
        self._current_model_ref = model_ref
        return candidate_model

    def start_generation(
        self,
        request: GenerationRequest,
    ) -> GenerationHandle:
        """Create one request handle with an independently owned token."""

        provider = self._provider
        prepared_request = self._prepare_request(request, provider)
        return GenerationHandle(
            self,
            provider,
            prepared_request,
            CancellationToken(),
        )

    def _start_agent_turn(
        self,
        state: RunState,
        user_input: str,
        *,
        turn_id: str,
        cancellation: CancellationToken,
        behavior_mode: BehaviorMode,
        permission_resolver: PermissionResolver,
        session_grant_sink: SessionGrantSink,
        process_message_start: int = 0,
    ) -> AgentTurnExecution:
        """Start a Core Turn with Application-owned snapshots.

        This is an internal composition boundary used by ``AgentRun``.  The
        Provider object, model reference, ordered definitions, and summary
        callable are captured before Core receives the Turn, so a later model
        switch cannot alter an active Turn.
        """

        provider = self._provider
        model_ref = self._current_model_ref
        model_profile = self.current_model
        remote_model_id = (
            model_profile.remote_id if model_profile is not None else provider.identity.model
        )
        reasoning = _reasoning_options(
            model_profile.reasoning_effort if model_profile is not None else None
        )
        max_output_tokens = (
            model_profile.max_output_tokens if model_profile is not None else None
        )
        configured_input_limit = (
            model_profile.context_window if model_profile is not None else None
        )
        ordinary_tool_definitions = self._tool_service.definitions()
        tool_definitions = ordinary_tool_definitions + (ASK_USER_TOOL_DEFINITION,)
        tool_definitions += (TODO_WRITE_TOOL_DEFINITION,)
        tool_definitions += (PROPOSE_PLAN_TOOL_DEFINITION,)

        def active_timeline():
            if self._session_service is None:
                return None
            active = self._session_service.active_session
            return None if active is None else active.timeline

        def active_session_id():
            if self._session_service is None:
                return None
            active = self._session_service.active_session
            return None if active is None else active.session_id

        def active_transcript():
            if self._session_service is None:
                return None
            active = self._session_service.active_session
            return None if active is None else active.transcript

        def handle_provider_overflow() -> bool:
            """Perform one bounded compaction attempt, never window discovery."""

            if self._session_service is not None:
                active = self._session_service.active_session
                if active is not None:
                    candidate = self._context_service.compact(
                        active.transcript,
                        timeline=active.timeline,
                        session_id=active.session_id,
                    )
                    if candidate.changed and candidate.timeline is not None:
                        committed = self._commit_timeline_candidate(active, candidate)
                        return committed.changed
            return False

        limits_ready = False
        frozen_provider_limits: ModelLimits | None = None
        frozen_budget: ContextBudget | None = None

        async def prepare(
            messages: tuple[Message, ...],
            visible_definitions: tuple[ToolDefinition, ...],
            runtime_context: RuntimePromptContext,
        ) -> GenerationRequest:
            nonlocal limits_ready, frozen_provider_limits, frozen_budget
            if not limits_ready:
                frozen_provider_limits = await _resolve_model_limits_async(
                    provider,
                    remote_model_id,
                )
                frozen_budget = resolve_context_budget(
                    configured_input_limit=configured_input_limit,
                    provider_limits=frozen_provider_limits,
                    requested_output_reserve=(max_output_tokens or 0),
                )
                limits_ready = True
            process_messages = messages[process_message_start:]

            def compose(
                provider_count: ContextCountEstimate | int | None,
                defer_hard_gate: bool,
                count_fallback: str | None,
            ) -> GenerationRequest:
                request, _snapshot = self._context_service.compose_generation_request(
                    process_messages,
                    run_id=state.run_id,
                    session_id=active_session_id(),
                    transcript=active_transcript(),
                    instruction_loader=self._instruction_loader,
                    runtime_context=runtime_context,
                    timeline=active_timeline(),
                    tool_definitions=visible_definitions,
                    environment_sources=self._environment_sources(model_ref, provider.identity),
                    model=remote_model_id,
                    reasoning=reasoning,
                    max_output_tokens=max_output_tokens,
                    context_budget=frozen_budget,
                    provider_count=provider_count,
                    defer_hard_gate=defer_hard_gate,
                    count_fallback=count_fallback,
                )
                return request

            def finalize(
                candidate: GenerationRequest,
                provider_count: ContextCountEstimate | int | None,
                defer_hard_gate: bool,
                count_fallback: str | None,
            ) -> GenerationRequest:
                request, _snapshot = self._context_service.compose_generation_request(
                    process_messages,
                    run_id=state.run_id,
                    session_id=active_session_id(),
                    transcript=active_transcript(),
                    instruction_loader=self._instruction_loader,
                    runtime_context=runtime_context,
                    timeline=active_timeline(),
                    tool_definitions=visible_definitions,
                    environment_sources=self._environment_sources(model_ref, provider.identity),
                    model=remote_model_id,
                    reasoning=reasoning,
                    max_output_tokens=max_output_tokens,
                    context_budget=frozen_budget,
                    provider_count=provider_count,
                    defer_hard_gate=defer_hard_gate,
                    count_fallback=count_fallback,
                    candidate_messages=candidate.messages,
                    disable_reductions=True,
                    reduction_levels=_request_reduction_levels(candidate),
                )
                return request

            try:
                return await _prepare_counted_request_async(provider, compose, finalize)
            except GenerationCancelled:
                # AgentLoop treats asyncio cancellation as the cooperative
                # cancellation channel around request preparation.  A
                # Provider count endpoint may expose its own Core cancellation
                # exception, so translate it without entering local fallback.
                raise CancelledError()

        loop = self._tool_service._create_agent_loop(
            provider,
            prepare,
            permission_resolver=permission_resolver,
            session_grant_sink=session_grant_sink,
            overflow_handler=handle_provider_overflow,
        )
        execution = loop.start_turn(
            state,
            user_input,
            turn_id=turn_id,
            cancellation=cancellation,
            behavior_mode=behavior_mode,
            tool_definitions=tool_definitions,
        )
        if execution.state.messages[-1].role != "user":  # pragma: no cover
            raise RuntimeError("Agent Loop did not append the user message")
        return execution

    def _prepare_request(
        self,
        request: GenerationRequest,
        provider: ProviderPort,
        *,
        model_ref: str | None = None,
        runtime_context: RuntimePromptContext | None = None,
    ) -> GenerationRequest:
        if not isinstance(request, GenerationRequest):
            raise TypeError("request must be GenerationRequest")
        if request.system_prompt is not None:
            raise ValueError(
                "Application owns system_prompt; caller must leave it unset"
            )
        if request.model is not None:
            raise ValueError("Application owns model; caller must leave it unset")

        identity = provider.identity
        selected_model_ref = (
            self._current_model_ref if model_ref is None else model_ref
        )
        selected_profile = (
            self._configuration.models.get(selected_model_ref)
            if self._configuration is not None
            else None
        )
        remote_model_id = (
            selected_profile.remote_id
            if selected_profile is not None
            else identity.model
        )
        reasoning = (
            _reasoning_options(selected_profile.reasoning_effort)
            if selected_profile is not None and selected_profile.reasoning_effort is not None
            else request.reasoning
        )
        max_output_tokens = (
            request.max_output_tokens
            if request.max_output_tokens is not None
            else selected_profile.max_output_tokens
            if selected_profile is not None
            else None
        )
        configured_input_limit = (
            selected_profile.context_window if selected_profile is not None else None
        )
        provider_limits = _resolve_model_limits_sync(provider, remote_model_id)
        budget = resolve_context_budget(
            configured_input_limit=configured_input_limit,
            provider_limits=provider_limits,
            requested_output_reserve=(max_output_tokens or 0),
        )
        def compose(
            provider_count: ContextCountEstimate | int | None,
            defer_hard_gate: bool,
            count_fallback: str | None,
        ) -> GenerationRequest:
            compiled_request, _snapshot = self._context_service.compose_generation_request(
                request.messages,
                run_id="generation",
                instruction_loader=self._instruction_loader,
                runtime_context=runtime_context,
                tool_definitions=request.tools,
                environment_sources=self._environment_sources(selected_model_ref, identity),
                model=remote_model_id,
                reasoning=reasoning,
                max_output_tokens=max_output_tokens,
                temperature=request.temperature,
                context_budget=budget,
                provider_count=provider_count,
                defer_hard_gate=defer_hard_gate,
                count_fallback=count_fallback,
            )
            return compiled_request

        def finalize(
            candidate: GenerationRequest,
            provider_count: ContextCountEstimate | int | None,
            defer_hard_gate: bool,
            count_fallback: str | None,
        ) -> GenerationRequest:
            compiled_request, _snapshot = self._context_service.compose_generation_request(
                request.messages,
                run_id="generation",
                instruction_loader=self._instruction_loader,
                runtime_context=runtime_context,
                tool_definitions=request.tools,
                environment_sources=self._environment_sources(selected_model_ref, identity),
                model=remote_model_id,
                reasoning=reasoning,
                max_output_tokens=max_output_tokens,
                temperature=request.temperature,
                context_budget=budget,
                provider_count=provider_count,
                defer_hard_gate=defer_hard_gate,
                count_fallback=count_fallback,
                candidate_messages=candidate.messages,
                disable_reductions=True,
                reduction_levels=_request_reduction_levels(candidate),
            )
            return compiled_request

        return _prepare_counted_request_sync(provider, compose, finalize)

    def _environment_sources(
        self,
        model_ref: str,
        identity: ProviderIdentity,
    ) -> tuple[EnvironmentSource, ...]:
        content = "\n".join(
            (
                f"- 工作目录：{self._runtime_context.workdir}",
                f"- 平台：{self._runtime_context.platform_name} / {self._runtime_context.platform_release}",
                f"- 当前日期：{self._runtime_context.current_date}",
                f"- Provider 协议：{identity.protocol}",
                f"- 远端模型：{identity.model}",
                f"- 模型选择：{model_ref}",
            )
        )
        return (
            EnvironmentSource(
                ContextBlock(
                    source_kind=ContextSourceKind.ENVIRONMENT_FACT,
                    authority=ContextAuthority.ENVIRONMENT,
                    stability=ContextStability.DYNAMIC,
                    scope=ContextScope.TURN,
                    provenance="application:environment",
                    content=content,
                )
            ),
        )

    async def stream_generation(
        self,
        request: GenerationRequest,
    ) -> AsyncIterator[ProviderEvent]:
        """Convenience stream implemented by the formal GenerationHandle."""

        handle = self.start_generation(request)
        async for event in handle.events():
            yield event

    async def _stream_with_token(
        self,
        provider: ProviderPort,
        request: GenerationRequest,
        token: CancellationToken,
    ) -> AsyncIterator[ProviderEvent]:
        """Yield one provider stream through the shared Core validator."""

        async for event in validated_provider_stream(
            provider,
            request,
            cancellation=token,
        ):
            if isinstance(event, GenerationCompleted):
                self._provider_usage_diagnostics = public_usage_diagnostics(
                    event.response.usage
                )
            yield event


__all__ = [
    "ApplicationStatus",
    "GenerationHandle",
    "UthCodeApplication",
]
