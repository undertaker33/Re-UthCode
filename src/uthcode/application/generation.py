"""Headless generation use cases built on the Core Provider Port."""

from __future__ import annotations

import asyncio
from asyncio import CancelledError
import json
import inspect
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from uthcode.core.agent import (
    AgentLoop,
    AgentTurnExecution,
    PersistenceUnavailableError,
    PermissionResolver,
    RunState,
    SessionGrantSink,
)
from uthcode.core.agent_events import FailureReason
from uthcode.core.interaction import ASK_USER_TOOL_DEFINITION, PauseReason
from uthcode.core.planning import (
    BehaviorMode,
    PROPOSE_PLAN_TOOL_DEFINITION,
    TODO_WRITE_TOOL_DEFINITION,
)
from uthcode.core.provider import (
    CancellationToken,
    ContextOverflowError,
    DEFAULT_OUTPUT_RESERVE,
    GenerationCompleted,
    GenerationCancelled,
    GenerationRequest,
    InvalidProviderResponseError,
    Message,
    ModelLimits,
    ProviderConfigurationError,
    ProviderError,
    ProviderIdentity,
    ProviderPort,
    ReasoningOptions,
    ToolDefinition,
    TextPart,
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
    RuntimePromptContext,
)
from uthcode.core.context import (
    CompactionResult,
    ContextBudget,
    ContextBudgetError,
    ContextCountEstimate,
    ContextRequestSafetyError,
    ContextUsage,
    account_generation_request,
    evaluate_gates,
    preflight_safety_count,
    pressure_estimate,
    resolve_context_budget,
    fine_timeline_usage,
)
from uthcode.core.compaction import CompactionEpoch, TimelineAgingEpoch
from uthcode.core.permission import PermissionEvaluator, PermissionMode, RuleSet

from .configuration import ConfigSource, EffectiveConfig, ModelProfile, ProviderProfile
from .context import ApplicationContextService, CompactionStatus, ContextStatus
from .instructions import InstructionLoader
from .history import _transcript_entries_for_message
from .runtime_context import ApplicationRuntimeContext
from .sessions import (
    ApplicationSession,
    ApplicationSessionService,
    TimelineAppendOutcome,
    TranscriptAppendOutcome,
    SessionCatalogEntry,
    SessionMutation,
    SessionReplayRecord,
    SessionOperationError,
)
from .tools import ApplicationToolService
from .provider_usage import public_usage_diagnostics


ProviderBuilder = Callable[[ProviderProfile, ModelProfile], ProviderPort]
ModelWriter = Callable[[str], object]
PermissionWriter = Callable[[PermissionMode], object]
PermissionRulesLoader = Callable[[], RuleSet]


def failure_message(reason: FailureReason | None) -> str:
    """Return the sole safe one-line projection for a terminal failure fact."""

    try:
        if reason is not None and not isinstance(reason, FailureReason):
            reason = FailureReason(reason)
    except (TypeError, ValueError):
        reason = None
    if reason is FailureReason.AUTHENTICATION:
        return "Provider 认证失败，请检查凭据或配置。"
    if reason is FailureReason.PROVIDER_REQUEST:
        return "Provider 请求或配置无效，请检查模型和请求设置。"
    if reason is FailureReason.INVALID_PROVIDER_RESPONSE:
        return "Provider 返回了无法处理的响应，请稍后重试。"
    if reason is FailureReason.CONTEXT_UNRESOLVABLE:
        return "当前会话内容无法安全整理，请缩短请求或重试。"
    if reason is FailureReason.PERSISTENCE_UNAVAILABLE:
        return "会话无法安全保存，请检查存储后重试。"
    return "生成失败，请稍后重试。"


def pause_message(reason: PauseReason | None) -> str:
    """Return the sole safe one-line projection for a pause fact."""

    try:
        if reason is not None and not isinstance(reason, PauseReason):
            reason = PauseReason(reason)
    except (TypeError, ValueError):
        reason = None
    if reason is PauseReason.USER_REQUESTED:
        return "generation paused; resume or cancel"
    if reason is PauseReason.USER_INPUT_REQUIRED:
        return "generation requires interactive input"
    if reason is PauseReason.NETWORK_ERROR:
        return "provider temporarily unavailable"
    if reason is PauseReason.RATE_LIMITED:
        return "provider temporarily unavailable"
    if reason is PauseReason.TIMEOUT:
        return "provider request timed out; retry available"
    if reason is PauseReason.PERMISSION_REQUIRED:
        return "permission approval required; non-interactive execution was cancelled"
    if reason is PauseReason.PLAN_REVIEW_REQUIRED:
        return "plan review required before continuing"
    return "generation paused and cannot continue non-interactively"


def _reasoning_options(effort: str | None) -> ReasoningOptions | None:
    if effort is None:
        return None
    return ReasoningOptions(enabled=effort != "none", effort=effort)


def _validate_model_limits(value: object) -> ModelLimits | None:
    if value is not None and not isinstance(value, ModelLimits):
        raise TypeError("Provider model limits must be ModelLimits or None")
    return value


def _effective_output_reserve(
    request_max_output_tokens: int | None,
    model_max_output_tokens: int | None,
) -> int:
    """Resolve the one output reserve used by budget, request, and adapters."""

    if request_max_output_tokens is not None:
        return request_max_output_tokens
    if model_max_output_tokens is not None:
        return model_max_output_tokens
    return DEFAULT_OUTPUT_RESERVE


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


_COMPACTION_SYSTEM_PROMPT = (
    "You are UthCode's bounded Context compactor. Return only a JSON object with "
    "entries and coverage. Produce exactly one entry for every covered Turn, in "
    "the supplied order. Each entry must contain turn_id and a short summary. "
    "Do not add Turns, refs, or facts that are not present in the raw evidence."
)

_TIMELINE_AGING_SYSTEM_PROMPT = (
    "You are UthCode's bounded Timeline aging compactor. Return only a JSON "
    "object with summary and coverage. Produce exactly one Macro summary for "
    "all supplied Turns in order. Use only the complete raw Transcript evidence; "
    "never summarize a Fine or Macro summary and never invent refs or Turns."
)


def _compaction_input_payload(epoch: CompactionEpoch) -> str:
    """Add an explicit output contract without exposing a second state model."""

    coverage = [
        {
            "turn_id": unit.turn_id,
            "refs": [ref.to_dict()],
        }
        for unit, ref in zip(epoch.units, epoch.refs, strict=True)
    ]
    return (
        f"{epoch.input_text}\n\nRequired coverage (copy only these Turn IDs):\n"
        + json.dumps(coverage, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )


def _timeline_aging_input_payload(epoch: TimelineAgingEpoch) -> str:
    """Add the L5 Macro contract while keeping evidence raw-only."""

    coverage = [
        {
            "turn_id": unit.turn_id,
            "refs": [ref.to_dict()],
        }
        for unit, ref in zip(epoch.units, epoch.refs, strict=True)
    ]
    return (
        f"{epoch.input_text}\n\nRequired Macro coverage (copy only these Turn IDs):\n"
        + json.dumps(coverage, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )


async def _prepare_compaction_request_async(
    provider: ProviderPort,
    request: GenerationRequest,
    budget: ContextBudget,
    *,
    cancellation: CancellationToken,
) -> GenerationRequest:
    """Hard-gate an independent tool-free L4 request before sending it."""

    output_reserve = budget.compaction_output_reserve
    if budget.provider_max_output is not None:
        output_reserve = min(output_reserve, budget.provider_max_output)
    if output_reserve <= 0:
        raise ContextRequestSafetyError("compact output reserve is not provider-safe")
    compact_budget = replace(
        budget,
        requested_output_reserve=output_reserve,
        safety_allowance=0,
    )
    current = request
    for _ in range(8):
        cancellation.raise_if_cancelled()
        resolution = await _count_input_tokens_async(provider, current)
        count = resolution.value
        fallback_reason = resolution.fallback_reason
        counted = preflight_safety_count(
            current,
            compact_budget,
            provider_count=count,
        )
        accounting = account_generation_request(current)
        pressure = pressure_estimate(current, compact_budget)
        gate = evaluate_gates(
            compact_budget,
            counted,
            accounting=accounting,
            pressure_count=pressure,
        )
        if not gate.hard_safe:
            raise ContextRequestSafetyError(
                "compact request failed the preflight Hard Gate: " + gate.reason
            )
        metadata = {
            **dict(current.metadata),
            "context_compaction_request": True,
            "context_gate": gate.to_dict(),
            "context_pressure": pressure.to_dict(),
            "context_count_source": gate.count_source,
            "context_count_fallback": fallback_reason,
        }
        annotated = replace(current, metadata=metadata)
        if annotated == current:
            return current
        current = annotated
    raise ContextRequestSafetyError(
        "compact request count did not stabilize for the final request"
    )


async def _run_compaction_provider(
    provider: ProviderPort,
    request: GenerationRequest,
    *,
    cancellation: CancellationToken,
) -> str:
    """Run one validated tool-free Provider stream and return text only."""

    terminal: GenerationCompleted | None = None
    async for event in validated_provider_stream(
        provider,
        request,
        cancellation=cancellation,
    ):
        if isinstance(event, GenerationCompleted):
            terminal = event
    if terminal is None:  # pragma: no cover - validated_provider_stream guards this
        raise InvalidProviderResponseError("compact Provider response is incomplete")
    if terminal.response.message.role != "assistant":
        raise InvalidProviderResponseError("compact Provider response is not assistant text")
    text = "\n".join(
        part.text
        for part in terminal.response.message.parts
        if isinstance(part, TextPart)
    ).strip()
    if not text:
        raise InvalidProviderResponseError("compact Provider response has no text")
    return text


async def _summarize_compaction_epoch_with_provider(
    provider: ProviderPort,
    remote_model_id: str,
    budget: ContextBudget,
    epoch: CompactionEpoch | TimelineAgingEpoch,
    *,
    cancellation: CancellationToken,
    aging: bool = False,
    diagnostics: ApplicationContextService | None = None,
) -> str:
    """Run the one shared, tool-free, hard-gated Context model call."""

    output_reserve = budget.compaction_output_reserve
    if budget.provider_max_output is not None:
        output_reserve = min(output_reserve, budget.provider_max_output)
    if output_reserve <= 0:
        raise ContextRequestSafetyError("compact output reserve is not provider-safe")
    is_aging = aging or isinstance(epoch, TimelineAgingEpoch)
    if is_aging:
        payload = _timeline_aging_input_payload(epoch)  # type: ignore[arg-type]
        system_prompt = _TIMELINE_AGING_SYSTEM_PROMPT
        metadata = {
            "context_compaction_request": True,
            "context_compaction_level": "L5",
            "context_timeline_aging_request": True,
            "context_timeline_aging_epoch_turns": list(epoch.turn_ids),
        }
    else:
        payload = _compaction_input_payload(epoch)  # type: ignore[arg-type]
        system_prompt = _COMPACTION_SYSTEM_PROMPT
        metadata = {
            "context_compaction_request": True,
            "context_compaction_epoch_turns": list(epoch.turn_ids),
        }
    compact_request = GenerationRequest(
        messages=(Message("user", (TextPart(payload),)),),
        system_prompt=system_prompt,
        model=remote_model_id,
        tools=(),
        reasoning=None,
        max_output_tokens=output_reserve,
        temperature=0.0,
        metadata=metadata,
    )
    prepared = await _prepare_compaction_request_async(
        provider,
        compact_request,
        budget,
        cancellation=cancellation,
    )
    if diagnostics is not None:
        diagnostics.record_request_diagnostics(prepared, budget)
    return await _run_compaction_provider(
        provider,
        prepared,
        cancellation=cancellation,
    )


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


async def _prepare_counted_request_async(
    provider: ProviderPort,
    compose: Callable[[ContextCountEstimate | int | None, bool, str | None], GenerationRequest],
    finalize: Callable[
        [GenerationRequest, ContextCountEstimate | int | None, bool, str | None],
        GenerationRequest,
    ],
    *,
    on_counted_request: Callable[
        [GenerationRequest, ContextCountEstimate | int | None],
        bool | Awaitable[bool],
    ]
    | None = None,
) -> GenerationRequest:
    """Async counterpart of the exact final-request count/re-gate loop.

    ``on_counted_request`` is an Application-owned catch-up hook.  It runs
    only after an exact Provider count has been attached to a rebuilt request;
    returning ``True`` restarts the count loop from the current sources.  The
    hook is deliberately outside Core and cannot bypass the final Hard Gate.
    """

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

        if on_counted_request is not None:
            retry = on_counted_request(counted_request, provider_count)
            if inspect.isawaitable(retry):
                retry = await retry
            if not isinstance(retry, bool):
                raise TypeError("on_counted_request must return a boolean")
            if retry:
                # The hook may have committed a fresh Timeline.  Rebuild from
                # authoritative sources and obtain a new exact Provider count
                # before the request is allowed to reach ``finalize``.
                rebuild_from_sources = True
                continue

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
    active_session_title: str | None = None
    context_status: ContextStatus = field(default_factory=ContextStatus.unavailable)
    compaction_status: CompactionStatus = field(default_factory=CompactionStatus)

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
            "context_status": self.context_status.to_dict(),
            "compaction_status": self.compaction_status.to_dict(),
            "timeline_checkpoint_id": self.timeline_checkpoint_id,
            "active_session_title": self.active_session_title,
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
            "open_continuation": "open_continuation_not_persisted",
        }.get(self.failure_stage)


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
        # The active Session model and the process-wide default are separate
        # pieces of state.  Resuming an older Session may change the active
        # provider without changing the model used by the next new Session.
        self._default_model_ref = self._current_model_ref
        self._model_state_generation = 0
        self._last_provider_limits: ModelLimits | None = None
        self._last_provider_limits_model: str | None = None
        self._last_provider_limits_provider: ProviderPort | None = None
        self._context_budget_snapshot: tuple[
            int,
            ProviderPort,
            str,
            ContextBudget,
        ] | None = None
        self._request_boundary_counts: dict[tuple[str, str], int] = {}
        self._context_service.set_context_budget(self._context_budget_for_projection())

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

    def record_live_context_delta(self, text: str, *, source: str = "live_delta") -> None:
        """Project one streamed semantic delta into the live Context status."""

        self._context_service.record_live_delta(text, source=source)

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

    def context_usage(self, snapshot=None):
        """Return the same dynamic usage projection for headless callers."""

        if snapshot is not None:
            return self._context_service.usage(snapshot)
        context = self._context_service.context_status
        return ContextUsage(
            context.used_tokens,
            context.budget_tokens,
            available=context.available,
        )

    def create_session(self, session_id: str | None = None) -> ApplicationSession:
        if self._session_service is None:
            raise RuntimeError("durable Session storage is not configured")
        state = self._capture_model_context_state()
        session: ApplicationSession | None = None
        try:
            candidate, provider, limits, context_budget = self._preflight_new_session_model()
            self._preflight_new_session_context(context_budget)
            session = self._session_service.create_session(
                session_id,
                model_ref=self._default_model_ref,
            )
            if candidate is not None and provider is not None:
                self._commit_model_selection(
                    candidate,
                    provider,
                    limits,
                    context_budget,
                    persist_default=False,
                    persist_session=False,
                    refresh_context=False,
                )
            return session
        except BaseException:
            self._rollback_new_session(session, state)
            raise

    def ensure_session(self) -> ApplicationSession | None:
        """Open a fresh durable Session for an interactive entry point."""

        if self._session_service is None:
            return None
        active = self._session_service.active_session
        if active is not None:
            return active
        return self.new_session_for_command()

    async def ensure_session_async(self) -> ApplicationSession | None:
        """Open a fresh Session without blocking an interface event loop."""

        if self._session_service is None:
            return None
        active = self._session_service.active_session
        if active is not None:
            return active
        return await self.new_session_for_command_async()

    def resume_session(self, session_id: str) -> ApplicationSession:
        if self._session_service is None:
            raise RuntimeError("durable Session storage is not configured")
        self._preflight_session_model(session_id)
        session = self._session_service.resume_session(
            session_id,
            replay_builder=self._build_session_replay,
        )
        self._restore_session_model(session)
        # Resolve the budget after adopting the Session's model.  Resolving it
        # before the restore would recompile the resumed Session with the
        # process-wide default model's limits.
        context_budget = self._context_budget_for_projection(resolve_provider=True)
        self._refresh_context_for_session(session, context_budget=context_budget)
        return session

    def rename_session(self, session_id: str, title: str) -> SessionMutation:
        """Rename a durable Session through the Application boundary."""

        if self._session_service is None:
            raise RuntimeError("durable Session storage is not configured")
        return self._session_service.rename_session(session_id, title)

    def move_session(self, session_id: str, target_project_key: str) -> SessionMutation:
        """Move an inactive durable Session to a canonical project key."""

        if self._session_service is None:
            raise RuntimeError("durable Session storage is not configured")
        active = self._session_service.active_session
        moving_active = active is not None and active.session_id == session_id
        result = self._session_service.move_session(session_id, target_project_key)
        if moving_active and self._session_service.active_session is None:
            # The source Application no longer owns this Session, so its
            # Context projection must not continue presenting the released
            # transcript as the current working set.
            self._context_service.clear_context()
        return result

    def session_catalog(self) -> tuple[SessionCatalogEntry, ...]:
        """Return the Application-owned same-project Session Picker data."""

        if self._session_service is None:
            return ()
        return self._session_service.list_catalog()

    def new_session_for_command(self) -> ApplicationSession:
        """Create and commit a fresh Session only after staging succeeds."""

        if self._session_service is None:
            raise RuntimeError("durable Session storage is not configured")
        state = self._capture_model_context_state()
        session: ApplicationSession | None = None
        try:
            candidate, provider, limits, context_budget = self._preflight_new_session_model()
            self._preflight_new_session_context(context_budget)
            session = self._session_service.create_session_for_command(
                model_ref=self._default_model_ref,
            )
            if candidate is not None and provider is not None:
                self._commit_model_selection(
                    candidate,
                    provider,
                    limits,
                    context_budget,
                    persist_default=False,
                    persist_session=False,
                    refresh_context=False,
                )
            return session
        except BaseException:
            self._rollback_new_session(session, state)
            raise

    async def new_session_for_command_async(
        self,
        *,
        context_budget: ContextBudget | None = None,
    ) -> ApplicationSession:
        """Resolve Context before committing a new durable Session."""

        if self._session_service is None:
            raise RuntimeError("durable Session storage is not configured")
        if context_budget is not None and not isinstance(context_budget, ContextBudget):
            raise TypeError("context_budget must be a ContextBudget or None")
        state = self._capture_model_context_state()
        session: ApplicationSession | None = None
        try:
            candidate, provider, limits, prepared_budget = await self._preflight_new_session_model_async(
                context_budget=context_budget,
            )
            self._preflight_new_session_context(prepared_budget)
            session = self._session_service.create_session_for_command(
                model_ref=self._default_model_ref,
            )
            if candidate is not None and provider is not None:
                self._commit_model_selection(
                    candidate,
                    provider,
                    limits,
                    prepared_budget,
                    persist_default=False,
                    persist_session=False,
                    refresh_context=False,
                )
            return session
        except BaseException:
            self._rollback_new_session(session, state)
            raise

    def resume_session_for_command(self, session_id: str) -> ApplicationSession:
        """Lock/recover the target before committing the Session switch."""

        if self._session_service is None:
            raise RuntimeError("durable Session storage is not configured")
        self._preflight_session_model(session_id)
        session = self._session_service.resume_session_for_command(
            session_id,
            replay_builder=self._build_session_replay,
        )
        self._restore_session_model(session)
        context_budget = self._context_budget_for_projection(resolve_provider=True)
        self._refresh_context_for_session(session, context_budget=context_budget)
        return session

    async def resume_session_for_command_async(
        self,
        session_id: str,
        *,
        context_budget: ContextBudget | None = None,
    ) -> ApplicationSession:
        """Resolve Context before committing a durable Session switch."""

        if self._session_service is None:
            raise RuntimeError("durable Session storage is not configured")
        if context_budget is None:
            # The target Session may carry its own model preference. Resolve
            # the provider budget only after the Session is opened/restored so
            # the caller never compiles it against the old default model.
            context_budget = None
        elif not isinstance(context_budget, ContextBudget):
            raise TypeError("context_budget must be a ContextBudget or None")
        await self._preflight_session_model_async(session_id)
        session = self._session_service.resume_session_for_command(
            session_id,
            replay_builder=self._build_session_replay,
        )
        await self._restore_session_model_async(session)
        if context_budget is None or not self._context_budget_snapshot_matches(context_budget):
            context_budget = await self._context_budget_for_projection_async(
                resolve_provider=True,
            )
        await self._refresh_context_for_session_async(
            session,
            context_budget=context_budget,
        )
        return session

    def session_replay(
        self,
        session_id: str | None = None,
    ) -> tuple[SessionReplayRecord, ...]:
        """Return a safe replay projection without opening a Session."""

        if self._session_service is None:
            return ()
        active = self._session_service.active_session
        if session_id is None:
            return () if active is None else active.replay
        if active is not None and active.session_id == session_id:
            return active.replay
        snapshot = self._session_service.read_session(session_id)
        return self._build_session_replay(snapshot)

    def _build_session_replay(self, snapshot) -> tuple[SessionReplayRecord, ...]:
        """Build the interface-neutral replay through Application redaction."""

        if self._session_service is None:
            return ()
        return self._session_service.project_replay_snapshot(
            snapshot,
            tool_summary=self._tool_service.describe_tool_call,
        )

    async def compact_session(self) -> CompactionResult:
        """Run one manual L4 epoch through the active Turn's Context path."""

        if self._session_service is None:
            raise RuntimeError("durable Session storage is not configured")
        session = self._session_service.active_session
        if session is None:
            raise RuntimeError("no active Session")
        if session.durability_unknown:
            raise RuntimeError(
                "Session History durability is unknown; reconcile before compacting"
            )

        provider = self._provider
        model_profile = self.current_model
        remote_model_id = (
            model_profile.remote_id
            if model_profile is not None
            else provider.identity.model
        )
        configured_input_limit = (
            model_profile.context_window if model_profile is not None else None
        )
        max_output_tokens = _effective_output_reserve(
            None,
            model_profile.max_output_tokens if model_profile is not None else None,
        )
        provider_limits = await _resolve_model_limits_async(provider, remote_model_id)
        self._last_provider_limits = provider_limits
        self._last_provider_limits_model = remote_model_id
        self._last_provider_limits_provider = provider
        budget = resolve_context_budget(
            configured_input_limit=configured_input_limit,
            provider_limits=provider_limits,
            requested_output_reserve=max_output_tokens,
        )
        cancellation = CancellationToken()

        async def summarize_epoch(epoch: CompactionEpoch) -> str:
            return await _summarize_compaction_epoch_with_provider(
                provider,
                remote_model_id,
                budget,
                epoch,
                cancellation=cancellation,
                diagnostics=self._context_service,
            )

        async def commit(candidate: CompactionResult) -> CompactionResult:
            active = self._session_service.active_session
            if active is None:
                return replace(
                    candidate,
                    changed=False,
                    failure="timeline_commit_failed",
                )
            return self._commit_timeline_candidate(active, candidate)

        result = await self._context_service.compact_async(
            session.transcript,
            timeline=session.timeline,
            session_id=session.session_id,
            summarize=summarize_epoch,
            commit=commit,
            cancellation=cancellation,
            max_epochs=1,
            input_budget=budget.compaction_input_budget,
            output_reserve=(
                min(budget.compaction_output_reserve, budget.provider_max_output)
                if budget.provider_max_output is not None
                else budget.compaction_output_reserve
            ),
            summary_hard_cap=(
                min(budget.compaction_output_reserve, budget.provider_max_output)
                if budget.provider_max_output is not None
                else budget.compaction_output_reserve
            ),
            trigger="manual",
        )
        if not result.changed and result.failure in {"no_safe_epoch", "no_reduction"}:
            # A low-pressure/manual no-op is a successful no-change outcome;
            # do not fabricate a Timeline candidate or expose a retry error.
            result = replace(
                result,
                timeline=session.timeline,
                summary=(session.timeline.summary if session.timeline is not None else None),
                failure=None,
            )
            self._context_service.finalize_compaction(result)
            self._context_service.finish_compaction(result, trigger="manual")
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
                "active_session_title": None,
                "recovery_diagnostics": [],
                "last_operation": None,
                "busy": False,
            }
        )
        return {
            "schema_version": 1,
            "context": context.get("context", {"status": "not_available"}),
            "context_budget": context.get("budget"),
            "context_request_accounting": context.get("request_accounting"),
            "context_gate": context.get("gate"),
            "context_pressure": context.get("pressure"),
            "context_count_fallback": context.get("count_fallback"),
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
                converted = _transcript_entries_for_message(
                    active.session_id,
                    turn_id,
                    sequence,
                    message,
                )
                entries.extend(converted)
                sequence += len(converted)
            if any(not entry.commit_boundary for entry in entries):
                outcome = TranscriptPersistenceOutcome(
                    False,
                    False,
                    "open_continuation",
                    0,
                    transcript_metadata_synced=False,
                    transcript_reload_succeeded=False,
                    transcript_durability="not_durable",
                    failure_stages=("open_continuation",),
                )
                self._record_transcript_persistence(outcome)
                return outcome
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

        # The durable Transcript changed before the terminal Run result is
        # projected.  Invalidate any prior exact Context measurement now;
        # _complete_turn may restore exact only after it has released the
        # active-turn owner and received the matching terminal Usage.
        self._context_service.refresh_context_estimate()

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
            ),
            "error_code": outcome.error_code,
        }

    def _record_committed_turn(self) -> None:
        """Increment the durable-turn metric after the whole delta is closed."""

        self._history_persistence_diagnostics["committed_turns"] = int(
            self._history_persistence_diagnostics.get("committed_turns", 0)
        ) + 1

    def _record_formal_run_usage(
        self,
        usage: Usage,
        *,
        exact_request_boundary: bool = False,
    ) -> None:
        """Project one terminal AgentRun's observed cumulative Usage.

        ``AgentRun`` owns the terminal-result boundary, while this Application
        method owns the diagnostics state.  A terminal Turn with no observed
        Provider Usage does not erase the last observable projection, so
        cancel/failure paths cannot manufacture a measurement or hide a prior
        one merely by constructing an empty default ``Usage``.  The Core
        ``TurnResult`` usage is cumulative across Provider iterations; it is
        promoted to an exact Context measurement only when the caller proves
        that this terminal result represents one completed request boundary.
        """

        if not isinstance(exact_request_boundary, bool):
            raise TypeError("exact_request_boundary must be a boolean")
        projection = public_usage_diagnostics(usage)
        if projection.get("status") == "available":
            self._provider_usage_diagnostics = projection
            input_tokens = projection.get("input_tokens")
            if (
                exact_request_boundary
                and isinstance(input_tokens, int)
                and not isinstance(input_tokens, bool)
            ):
                # A cumulative multi-iteration Turn is not the current
                # request boundary.  Only AgentRun's explicit single-request
                # proof may upgrade the Context estimate to exact.
                self._context_service.record_exact_usage(input_tokens)

    def _consume_request_boundary_count(
        self,
        run_id: str,
        turn_id: str,
    ) -> int | None:
        """Consume the number of successfully prepared Provider requests.

        Core ``TurnResult`` intentionally reports cumulative usage rather than
        a request-attempt counter.  The Application request-preparation
        boundary is therefore the narrowest fact available here: a retry of
        the same Core iteration prepares a second request and must keep the
        terminal projection as an estimate.
        """

        return self._request_boundary_counts.pop((run_id, turn_id), None)

    def status(self) -> ApplicationStatus:
        profile = self.current_provider_profile
        provider_profile_id = (
            profile.provider_profile_id
            if profile is not None
            else self._provider.identity.provider
        )
        sources = self._configuration.sources if self._configuration is not None else ()
        snapshot = self._context_service.last_snapshot
        context_status = self._context_service.context_status
        usage = ContextUsage(
            context_status.used_tokens,
            context_status.budget_tokens,
            available=context_status.available,
        )
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
            context_status=context_status,
            compaction_status=self._context_service.compaction_status,
            timeline_checkpoint_id=timeline_checkpoint_id,
            active_session_title=(active.title if active is not None else None),
            instruction_epoch=instruction_epoch,
            compact_count=compact_count if isinstance(compact_count, int) else 0,
            stable_prefix_fingerprint=stable_prefix_fingerprint,
            prefix_changed=prefix_changed,
            prefix_change_reason=prefix_change_reason,
            tool_schema_fingerprint=tool_schema_fingerprint,
            diagnostics=diagnostics,
        )

    def _context_budget_for_projection(
        self,
        *,
        resolve_provider: bool = False,
    ) -> ContextBudget:
        """Resolve the same effective budget used by the next formal request.

        Resume and other synchronous Session boundaries are formal APIs for
        callers without an event loop, while Provider limits resolvers may be
        asynchronous.  Reuse a previously frozen limit when one exists;
        otherwise resolve the endpoint through the synchronous bridge below.
        A running interface loop must use the async Session boundary so an
        awaitable resolver remains on that loop.
        """

        model_profile = self.current_model
        remote_model_id = (
            model_profile.remote_id
            if model_profile is not None
            else self._provider.identity.model
        )
        provider_limits = (
            self._last_provider_limits
            if self._last_provider_limits_model == remote_model_id
            and self._last_provider_limits_provider is self._provider
            else None
        )
        if provider_limits is None and resolve_provider:
            provider_limits = self._resolve_model_limits_sync(remote_model_id)
            if provider_limits is not None:
                self._last_provider_limits = provider_limits
                self._last_provider_limits_model = remote_model_id
                self._last_provider_limits_provider = self._provider
        return resolve_context_budget(
            configured_input_limit=(
                model_profile.context_window if model_profile is not None else None
            ),
            provider_limits=provider_limits,
            requested_output_reserve=_effective_output_reserve(
                None,
                model_profile.max_output_tokens if model_profile is not None else None,
            ),
        )

    async def _context_budget_for_projection_async(
        self,
        *,
        resolve_provider: bool = False,
    ) -> ContextBudget:
        """Resolve a Session projection budget on the caller's event loop."""

        # Provider metadata resolution is an await boundary.  A concurrent
        # model selection may therefore replace both the provider object and
        # model ref while this method is suspended.  Never cache or return a
        # budget derived from the stale snapshot; retry once against the
        # current identity, then fail with a stable boundary error rather than
        # overwriting the current model's Context status.
        for attempt in range(2):
            state_snapshot = self._model_state_snapshot()
            model_profile = self.current_model
            provider = self._provider
            remote_model_id = (
                model_profile.remote_id
                if model_profile is not None
                else provider.identity.model
            )
            provider_limits = (
                self._last_provider_limits
                if self._last_provider_limits_model == remote_model_id
                and self._last_provider_limits_provider is provider
                else None
            )
            if provider_limits is None and resolve_provider:
                try:
                    resolved_limits = await _resolve_model_limits_async(
                        provider,
                        remote_model_id,
                    )
                except Exception:
                    # A status refresh cannot manufacture a ceiling from a
                    # failed metadata probe; retain the existing configured/
                    # default budget and let the formal request apply its own
                    # Provider error semantics.
                    resolved_limits = None
                if not self._model_state_matches(state_snapshot):
                    if attempt == 1:
                        raise RuntimeError(
                            "model changed during Context budget preflight"
                        )
                    continue
                provider_limits = resolved_limits
                if provider_limits is not None:
                    self._last_provider_limits = provider_limits
                    self._last_provider_limits_model = remote_model_id
                    self._last_provider_limits_provider = provider
            if not self._model_state_matches(state_snapshot):
                if attempt == 1:
                    raise RuntimeError("model changed during Context budget preflight")
                continue
            budget = resolve_context_budget(
                configured_input_limit=(
                    model_profile.context_window if model_profile is not None else None
                ),
                provider_limits=provider_limits,
                requested_output_reserve=_effective_output_reserve(
                    None,
                    model_profile.max_output_tokens if model_profile is not None else None,
                ),
            )
            self._context_budget_snapshot = (
                state_snapshot[0],
                state_snapshot[1],
                state_snapshot[2],
                budget,
            )
            return budget
        raise RuntimeError("model changed during Context budget preflight")

    def _model_state_snapshot(self) -> tuple[int, ProviderPort, str]:
        """Capture the minimal identity needed across an async metadata await."""

        return (
            self._model_state_generation,
            self._provider,
            self._current_model_ref,
        )

    def _model_state_matches(
        self,
        snapshot: tuple[int, ProviderPort, str],
    ) -> bool:
        return (
            snapshot[0] == self._model_state_generation
            and snapshot[1] is self._provider
            and snapshot[2] == self._current_model_ref
        )

    def _context_budget_snapshot_matches(self, budget: ContextBudget) -> bool:
        snapshot = self._context_budget_snapshot
        return bool(
            snapshot is not None
            and snapshot[0] == self._model_state_generation
            and snapshot[1] is self._provider
            and snapshot[2] == self._current_model_ref
            and snapshot[3] is budget
        )

    async def preflight_session_context_async(self) -> ContextBudget:
        """Resolve a Session boundary budget without mutating Session state."""

        return await self._context_budget_for_projection_async(resolve_provider=True)

    def _resolve_model_limits_sync(
        self,
        remote_model_id: str,
        *,
        provider: ProviderPort | None = None,
        strict: bool = False,
    ) -> ModelLimits | None:
        """Resolve an optional async Provider ceiling at a sync boundary.

        Application Session APIs are intentionally synchronous for non-async
        callers because their writer-lock and durable metadata transitions are
        synchronous.  A running interface loop must use the async Session
        boundary instead; blocking that loop or invoking the Provider from a
        second loop would violate Provider client loop affinity.
        """

        target_provider = self._provider if provider is None else provider
        resolver = getattr(target_provider, "resolve_model_limits", None)
        if not callable(resolver):
            return None

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            running_loop = False
        else:
            running_loop = True

        if running_loop and (
            inspect.iscoroutinefunction(resolver)
            or inspect.iscoroutinefunction(getattr(resolver, "__call__", None))
        ):
            raise RuntimeError(
                "async Provider model limits require an async Session boundary"
            )

        if strict:
            candidate = resolver(remote_model_id)
        else:
            try:
                candidate = resolver(remote_model_id)
            except Exception:
                return None
        if not inspect.isawaitable(candidate):
            if strict:
                return _validate_model_limits(candidate)
            try:
                return _validate_model_limits(candidate)
            except (TypeError, ValueError):
                return None

        if not running_loop:
            if strict:
                candidate = asyncio.run(candidate)
            else:
                try:
                    candidate = asyncio.run(candidate)
                except (Exception, CancelledError):
                    return None
        else:
            close = getattr(candidate, "close", None)
            if callable(close):
                close()
            raise RuntimeError(
                "async Provider model limits require an async Session boundary"
            )
        if strict:
            return _validate_model_limits(candidate)
        try:
            return _validate_model_limits(candidate)
        except (TypeError, ValueError):
            return None

    def _resolve_model_limits_sync_strict(
        self,
        remote_model_id: str,
        *,
        provider: ProviderPort | None = None,
    ) -> ModelLimits | None:
        """Resolve model-selection limits without hiding preflight failures."""

        return self._resolve_model_limits_sync(
            remote_model_id,
            provider=provider,
            strict=True,
        )

    def _refresh_context_for_session(
        self,
        session: ApplicationSession,
        *,
        context_budget: ContextBudget | None = None,
    ) -> None:
        """Refresh the stable Application usage projection at a Session boundary."""

        if context_budget is None:
            context_budget = self._context_budget_for_projection(resolve_provider=True)
        self._context_service.compile(
            instruction_loader=self._instruction_loader,
            transcript=session.transcript,
            timeline=session.timeline,
            tool_definitions=self.tool_definitions(),
            context_budget=context_budget,
            preserve_request_diagnostics=True,
        )

    async def _refresh_context_for_session_async(
        self,
        session: ApplicationSession,
        *,
        context_budget: ContextBudget | None = None,
    ) -> None:
        """Refresh Session Context after awaiting the Provider ceiling in-loop."""

        if context_budget is None:
            context_budget = await self._context_budget_for_projection_async(
                resolve_provider=True,
            )
        self._context_service.compile(
            instruction_loader=self._instruction_loader,
            transcript=session.transcript,
            timeline=session.timeline,
            tool_definitions=self.tool_definitions(),
            context_budget=context_budget,
            preserve_request_diagnostics=True,
        )

    def _model_selection_candidate(
        self,
        model_ref: str,
    ) -> tuple[ModelProfile, ProviderPort]:
        """Validate and build a model candidate without changing Application state."""

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
        return candidate_model, candidate_provider

    @staticmethod
    def _model_context_budget(
        model: ModelProfile,
        provider_limits: ModelLimits | None,
    ) -> ContextBudget:
        """Build a target model budget without committing it to Context state."""

        return resolve_context_budget(
            configured_input_limit=model.context_window,
            provider_limits=provider_limits,
            requested_output_reserve=_effective_output_reserve(
                None,
                model.max_output_tokens,
            ),
        )

    def _preflight_new_session_context(self, context_budget: ContextBudget) -> None:
        """Compile the empty target Context before creating durable metadata."""

        self._context_service.compile(
            instruction_loader=self._instruction_loader,
            transcript=None,
            timeline=None,
            tool_definitions=self.tool_definitions(),
            context_budget=context_budget,
            preserve_request_diagnostics=True,
        )

    def _capture_model_context_state(self) -> dict[str, object]:
        """Capture the mutable model/Context projection before Session creation."""

        return {
            "provider": self._provider,
            "model_ref": self._current_model_ref,
            "default_model_ref": self._default_model_ref,
            "model_state_generation": self._model_state_generation,
            "provider_limits": self._last_provider_limits,
            "provider_limits_model": self._last_provider_limits_model,
            "provider_limits_provider": self._last_provider_limits_provider,
            "context_budget_snapshot": self._context_budget_snapshot,
            "context_state": self._context_service.capture_state(),
        }

    def _restore_model_context_state(self, state: Mapping[str, object]) -> None:
        """Restore a pre-Session model/Context projection atomically."""

        self._provider = state["provider"]  # type: ignore[assignment]
        self._current_model_ref = str(state["model_ref"])
        self._default_model_ref = str(state["default_model_ref"])
        self._model_state_generation = int(state["model_state_generation"])
        self._last_provider_limits = state["provider_limits"]  # type: ignore[assignment]
        self._last_provider_limits_model = state["provider_limits_model"]  # type: ignore[assignment]
        self._last_provider_limits_provider = state["provider_limits_provider"]  # type: ignore[assignment]
        self._context_budget_snapshot = state["context_budget_snapshot"]  # type: ignore[assignment]
        self._context_service.restore_state(state["context_state"])  # type: ignore[arg-type]

    def _rollback_new_session(
        self,
        session: ApplicationSession | None,
        state: Mapping[str, object],
    ) -> None:
        """Release a failed new Session and restore the previous model projection."""

        if session is not None:
            try:
                session.close()
            except BaseException:
                # A freshly-created Session has no user transcript to sync.
                # If close-time instruction sync itself fails, release the
                # staged writer without exposing it as the active Session.
                close_staged = getattr(session, "_close_staged", None)
                if callable(close_staged):
                    try:
                        close_staged()
                    except BaseException:
                        pass
        self._restore_model_context_state(state)

    def _preflight_new_session_model(
        self,
    ) -> tuple[ModelProfile | None, ProviderPort | None, ModelLimits | None, ContextBudget]:
        """Validate the persisted default before creating its durable metadata."""

        model_ref = self._default_model_ref
        if model_ref != self._current_model_ref:
            candidate, provider = self._model_selection_candidate(model_ref)
            limits = self._resolve_model_limits_sync_strict(
                candidate.remote_id,
                provider=provider,
            )
            return candidate, provider, limits, self._model_context_budget(candidate, limits)
        model = self.current_model
        if model is None:
            return None, None, None, self._context_budget_for_projection(resolve_provider=True)
        limits = self._resolve_model_limits_sync_strict(
            model.remote_id,
            provider=self._provider,
        )
        return None, None, limits, self._model_context_budget(model, limits)

    async def _preflight_new_session_model_async(
        self,
        *,
        context_budget: ContextBudget | None = None,
    ) -> tuple[ModelProfile | None, ProviderPort | None, ModelLimits | None, ContextBudget]:
        """Async counterpart that validates Provider limits before metadata creation."""

        model_ref = self._default_model_ref
        if model_ref != self._current_model_ref:
            candidate, provider = self._model_selection_candidate(model_ref)
            limits = await _resolve_model_limits_async(provider, candidate.remote_id)
            return candidate, provider, limits, self._model_context_budget(candidate, limits)
        model = self.current_model
        if model is None:
            if context_budget is not None and self._context_budget_snapshot_matches(context_budget):
                return None, None, None, context_budget
            return None, None, None, await self._context_budget_for_projection_async(resolve_provider=True)
        if context_budget is not None and self._context_budget_snapshot_matches(context_budget):
            return None, None, self._last_provider_limits, context_budget
        limits = await _resolve_model_limits_async(self._provider, model.remote_id)
        return None, None, limits, self._model_context_budget(model, limits)

    def _commit_model_selection(
        self,
        candidate_model: ModelProfile,
        candidate_provider: ProviderPort,
        provider_limits: ModelLimits | None,
        context_budget: ContextBudget,
        *,
        persist_default: bool = True,
        persist_session: bool = True,
        refresh_context: bool = True,
    ) -> ModelProfile:
        """Commit one fully preflighted model candidate at one boundary."""

        old_provider = self._provider
        old_model_ref = self._current_model_ref
        old_default_model_ref = self._default_model_ref
        old_model_state_generation = self._model_state_generation
        old_provider_limits = self._last_provider_limits
        old_provider_limits_model = self._last_provider_limits_model
        old_provider_limits_provider = self._last_provider_limits_provider
        old_context_budget_snapshot = self._context_budget_snapshot
        old_context_state = self._context_service.capture_state()
        active = (
            self._session_service.active_session
            if self._session_service is not None
            else None
        )
        old_session_model_ref = active.model_ref if active is not None else None
        session_committed = False
        writer_committed = False
        try:
            # The user-config writer is itself atomic.  It is intentionally
            # called only after candidate Provider/limit validation and before
            # publishing the in-memory model identity.  If the synchronous
            # Context commit below fails, restore the old root preference
            # before returning the failure to the command boundary.
            if persist_default and self._model_writer is not None:
                self._model_writer(candidate_model.model_ref)
                writer_committed = True
            if active is not None and persist_session:
                active.persist_model_ref(candidate_model.model_ref)
                session_committed = True
            self._provider = candidate_provider
            self._current_model_ref = candidate_model.model_ref
            if persist_default:
                self._default_model_ref = candidate_model.model_ref
            self._last_provider_limits = provider_limits
            self._last_provider_limits_model = candidate_model.remote_id
            self._last_provider_limits_provider = candidate_provider
            if active is not None and refresh_context:
                self._refresh_context_for_session(
                    active,
                    context_budget=context_budget,
                )
            elif refresh_context:
                self._context_service.set_context_budget(context_budget)
            self._model_state_generation += 1
            self._context_budget_snapshot = (
                self._model_state_generation,
                candidate_provider,
                candidate_model.model_ref,
                context_budget,
            )
        except BaseException as original:
            # Context compilation is synchronous and normally cannot be
            # interrupted between state writes.  Restore the Application
            # identity if a validation/invariant failure nevertheless occurs.
            self._provider = old_provider
            self._current_model_ref = old_model_ref
            self._default_model_ref = old_default_model_ref
            self._model_state_generation = old_model_state_generation
            self._last_provider_limits = old_provider_limits
            self._last_provider_limits_model = old_provider_limits_model
            self._last_provider_limits_provider = old_provider_limits_provider
            self._context_budget_snapshot = old_context_budget_snapshot
            rollback_errors: list[BaseException] = []
            try:
                self._context_service.restore_state(old_context_state)
            except BaseException as exc:
                rollback_errors.append(exc)
            if session_committed and active is not None:
                try:
                    active.persist_model_ref(old_session_model_ref)
                except BaseException as exc:
                    rollback_errors.append(exc)
            if writer_committed and self._model_writer is not None:
                try:
                    self._model_writer(old_model_ref)
                except BaseException as exc:
                    rollback_errors.append(exc)
            if rollback_errors:
                raise RuntimeError("model selection rollback failed") from original
            raise
        return candidate_model

    def _preflight_session_model(self, session_id: str) -> None:
        """Validate a durable Session model before changing active ownership."""

        if self._session_service is None:
            return
        snapshot = self._session_service.read_session_for_command(session_id)
        model_ref = snapshot.metadata.model_ref
        if not model_ref or model_ref == self._current_model_ref:
            return
        candidate_model, candidate_provider = self._model_selection_candidate(model_ref)
        provider_limits = self._resolve_model_limits_sync_strict(
            candidate_model.remote_id,
            provider=candidate_provider,
        )
        self._model_context_budget(candidate_model, provider_limits)

    async def _preflight_session_model_async(self, session_id: str) -> None:
        """Async model restore preflight without mutating Session ownership."""

        if self._session_service is None:
            return
        snapshot = self._session_service.read_session_for_command(session_id)
        model_ref = snapshot.metadata.model_ref
        if not model_ref or model_ref == self._current_model_ref:
            return
        candidate_model, candidate_provider = self._model_selection_candidate(model_ref)
        provider_limits = await _resolve_model_limits_async(
            candidate_provider,
            candidate_model.remote_id,
        )
        self._model_context_budget(candidate_model, provider_limits)

    def _restore_session_model(self, session: ApplicationSession) -> None:
        """Adopt a valid Session model without changing the global default."""

        model_ref = session.model_ref
        if not model_ref or model_ref == self._current_model_ref:
            return
        candidate_model, candidate_provider = self._model_selection_candidate(model_ref)
        provider_limits = self._resolve_model_limits_sync_strict(
            candidate_model.remote_id,
            provider=candidate_provider,
        )
        context_budget = self._model_context_budget(candidate_model, provider_limits)
        self._commit_model_selection(
            candidate_model,
            candidate_provider,
            provider_limits,
            context_budget,
            persist_default=False,
            persist_session=False,
        )

    async def _restore_session_model_async(self, session: ApplicationSession) -> None:
        """Async counterpart of :meth:`_restore_session_model`."""

        model_ref = session.model_ref
        if not model_ref or model_ref == self._current_model_ref:
            return
        candidate_model, candidate_provider = self._model_selection_candidate(model_ref)
        provider_limits = await _resolve_model_limits_async(
            candidate_provider,
            candidate_model.remote_id,
        )
        context_budget = self._model_context_budget(candidate_model, provider_limits)
        self._commit_model_selection(
            candidate_model,
            candidate_provider,
            provider_limits,
            context_budget,
            persist_default=False,
            persist_session=False,
        )

    def select_model(self, model_ref: str) -> ModelProfile:
        """Synchronously select a model for callers without an event loop."""

        candidate_model, candidate_provider = self._model_selection_candidate(model_ref)
        provider_limits = self._resolve_model_limits_sync_strict(
            candidate_model.remote_id,
            provider=candidate_provider,
        )
        context_budget = self._model_context_budget(candidate_model, provider_limits)
        return self._commit_model_selection(
            candidate_model,
            candidate_provider,
            provider_limits,
            context_budget,
        )

    async def select_model_async(self, model_ref: str) -> ModelProfile:
        """Select a model after resolving its Provider ceiling on this loop."""

        candidate_model, candidate_provider = self._model_selection_candidate(model_ref)
        provider_limits = await _resolve_model_limits_async(
            candidate_provider,
            candidate_model.remote_id,
        )
        context_budget = self._model_context_budget(candidate_model, provider_limits)
        # No await follows this point: cancellation can only interrupt the
        # resolver preflight, before config/model/limit/Context publication.
        return self._commit_model_selection(
            candidate_model,
            candidate_provider,
            provider_limits,
            context_budget,
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
        persist_closed_messages: Callable[[Sequence[Message], str], int | None]
        | None = None,
    ) -> AgentTurnExecution:
        """Start a Core Turn with Application-owned snapshots.

        This is an internal composition boundary used by ``AgentRun``.  The
        Provider object, model reference, ordered definitions, and summary
        callable are captured before Core receives the Turn, so a later model
        switch cannot alter an active Turn.
        """

        # A new Turn invalidates any exact usage from the previous terminal
        # boundary before Core can emit its first event.
        self._context_service.refresh_context_estimate()
        request_boundary_key = (state.run_id, turn_id)
        self._request_boundary_counts[request_boundary_key] = 0

        provider = self._provider
        model_ref = self._current_model_ref
        model_profile = self.current_model
        remote_model_id = (
            model_profile.remote_id if model_profile is not None else provider.identity.model
        )
        reasoning = _reasoning_options(
            model_profile.reasoning_effort if model_profile is not None else None
        )
        max_output_tokens = _effective_output_reserve(
            None,
            model_profile.max_output_tokens if model_profile is not None else None,
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

        async def handle_provider_overflow() -> bool:
            """Perform one bounded async L4 recovery, never window discovery."""

            if self._session_service is None or frozen_budget is None:
                return False
            active = self._session_service.active_session
            if active is None:
                return False
            compaction_note["overflow_recovery_attempted"] = True
            compaction_note["attempted"] = True

            async def summarize(epoch: CompactionEpoch) -> str:
                compaction_note["provider_attempts"] = int(
                    compaction_note["provider_attempts"]
                ) + 1
                return await _summarize_compaction_epoch_with_provider(
                    provider,
                    remote_model_id,
                    frozen_budget,
                    epoch,
                    cancellation=cancellation,
                    diagnostics=self._context_service,
                )

            async def commit(candidate: CompactionResult) -> CompactionResult:
                current = self._session_service.active_session
                if current is None:
                    return replace(
                        candidate,
                        changed=False,
                        failure="timeline_commit_failed",
                    )
                committed = self._commit_timeline_candidate(current, candidate)
                if committed.changed:
                    compaction_note["epochs"] = int(compaction_note["epochs"]) + 1
                return committed

            result = await self._context_service.compact_async(
                active.transcript,
                timeline=active.timeline,
                session_id=active.session_id,
                summarize=summarize,
                commit=commit,
                cancellation=cancellation,
                max_epochs=1,
                active_turn_id=turn_id,
                input_budget=frozen_budget.compaction_input_budget,
                output_reserve=(
                    min(
                        frozen_budget.compaction_output_reserve,
                        frozen_budget.provider_max_output,
                    )
                    if frozen_budget.provider_max_output is not None
                    else frozen_budget.compaction_output_reserve
                ),
                summary_hard_cap=(
                    min(
                        frozen_budget.compaction_output_reserve,
                        frozen_budget.provider_max_output,
                    )
                    if frozen_budget.provider_max_output is not None
                    else frozen_budget.compaction_output_reserve
                ),
                trigger="overflow",
            )
            compaction_note.update(
                {
                    "status": (
                        "completed"
                        if result.changed and result.failure is None
                        else "unresolved"
                    ),
                    "failure": result.failure,
                    "overflow_recovery_status": (
                        "recovered" if result.changed and result.failure is None else "failed"
                    ),
                    "overflow_recovery_failure": result.failure,
                }
            )
            return result.changed and result.failure is None

        limits_ready = False
        frozen_provider_limits: ModelLimits | None = None
        frozen_budget: ContextBudget | None = None
        compaction_note: dict[str, object] = {
            "attempted": False,
            "status": "not_needed",
            "epochs": 0,
            "provider_attempts": 0,
            "epoch_limit": 4,
            "failure": None,
            "auto_pressure_unresolved": False,
            "previous_estimate": None,
            "retained_target": None,
            "low_water_reached": False,
            "overflow_recovery_attempted": False,
            "overflow_recovery_status": "not_needed",
            "overflow_recovery_failure": None,
            "timeline_aging": {
                "attempted": False,
                "status": "not_needed",
                "provider_attempts": 0,
                "failure": None,
                "previous_fine_usage": None,
                "fine_budget": None,
            },
        }
        compaction_orchestration_started = False
        timeline_aging_started = False

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
                self._last_provider_limits = frozen_provider_limits
                self._last_provider_limits_model = remote_model_id
                self._last_provider_limits_provider = provider
                frozen_budget = resolve_context_budget(
                    configured_input_limit=configured_input_limit,
                    provider_limits=frozen_provider_limits,
                    requested_output_reserve=max_output_tokens,
                )
                compaction_note["retained_target"] = frozen_budget.retained_target
                limits_ready = True
            process_messages = messages[process_message_start:]
            authoritative_gate_after_compaction: dict[str, object] | None = None
            authoritative_low_water_reached = False
            if persist_closed_messages is not None:
                persisted_cursor = persist_closed_messages(messages, turn_id)
                if persisted_cursor is not None:
                    if (
                        isinstance(persisted_cursor, bool)
                        or not isinstance(persisted_cursor, int)
                        or persisted_cursor < 0
                        or persisted_cursor > len(messages)
                    ):
                        raise TypeError(
                            "persist_closed_messages returned an invalid cursor"
                        )
                    if persisted_cursor < len(messages):
                        raise PersistenceUnavailableError(
                            "closed Transcript facts could not be durably persisted"
                        )
                    # Keep the active Turn as the current conversation tail.
                    # The Context service removes its durable copy before
                    # merging this process-local projection.
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
                    current_turn_id=turn_id if active_session_id() is not None else None,
                )
                return replace(
                    request,
                    metadata={
                        **dict(request.metadata),
                        "context_compaction": dict(compaction_note),
                    },
                )

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
                    current_turn_id=turn_id if active_session_id() is not None else None,
                )
                return replace(
                    request,
                    metadata={
                        **dict(request.metadata),
                        "context_compaction": dict(compaction_note),
                    },
                )

            def gate_from_request(request: GenerationRequest) -> Mapping[str, object] | None:
                value = request.metadata.get("context_gate")
                return value if isinstance(value, Mapping) else None

            async def summarize_epoch(epoch: CompactionEpoch) -> str:
                if frozen_budget is None:  # pragma: no cover - limits_ready guards this
                    raise ContextBudgetError("compact request has no frozen ContextBudget")
                compaction_note["provider_attempts"] = int(
                    compaction_note["provider_attempts"]
                ) + 1
                return await _summarize_compaction_epoch_with_provider(
                    provider,
                    remote_model_id,
                    frozen_budget,
                    epoch,
                    cancellation=cancellation,
                    diagnostics=self._context_service,
                )

            async def summarize_aging_epoch(epoch: TimelineAgingEpoch) -> str:
                if frozen_budget is None:  # pragma: no cover - limits_ready guards this
                    raise ContextBudgetError("timeline aging request has no frozen ContextBudget")
                aging_note = compaction_note["timeline_aging"]
                if not isinstance(aging_note, dict):  # pragma: no cover - local invariant
                    raise ContextBudgetError("timeline aging diagnostics are invalid")
                aging_note["provider_attempts"] = int(
                    aging_note["provider_attempts"]
                ) + 1
                return await _summarize_compaction_epoch_with_provider(
                    provider,
                    remote_model_id,
                    frozen_budget,
                    epoch,
                    cancellation=cancellation,
                    aging=True,
                    diagnostics=self._context_service,
                )

            async def commit_epoch(candidate: CompactionResult) -> CompactionResult:
                active = (
                    self._session_service.active_session
                    if self._session_service is not None
                    else None
                )
                if active is None:
                    return replace(
                        candidate,
                        changed=False,
                        failure="timeline_commit_failed",
                    )
                committed = self._commit_timeline_candidate(active, candidate)
                if committed.changed:
                    compaction_note["epochs"] = int(compaction_note["epochs"]) + 1
                return committed

            async def commit_aging_epoch(candidate: CompactionResult) -> CompactionResult:
                active = (
                    self._session_service.active_session
                    if self._session_service is not None
                    else None
                )
                if active is None:
                    return replace(
                        candidate,
                        changed=False,
                        failure="timeline_commit_failed",
                    )
                return self._commit_timeline_candidate(active, candidate)

            async def rebuild_after_epoch(timeline: object) -> Mapping[str, object]:
                nonlocal authoritative_gate_after_compaction
                nonlocal authoritative_low_water_reached
                del timeline
                rebuilt = compose(None, True, None)
                resolution = await _count_input_tokens_async(provider, rebuilt)
                rebuilt = compose(
                    resolution.value,
                    True,
                    resolution.fallback_reason,
                )
                gate = gate_from_request(rebuilt)
                if gate is None:
                    return {"continue": False, "reason": "gate_unavailable"}
                authoritative_gate_after_compaction = dict(gate)
                auto_pressure = bool(gate.get("auto_pressure", False))
                hard_safe = bool(gate.get("hard_safe", False))
                effective = gate.get("effective_input_limit")
                usage = gate.get("preflight_input_usage")
                retained_target = (
                    frozen_budget.retained_target
                    if frozen_budget is not None
                    else None
                )
                if isinstance(effective, int) and isinstance(usage, int):
                    compaction_note["headroom"] = max(0, effective - usage)
                low_water_reached = bool(
                    isinstance(usage, int)
                    and isinstance(retained_target, int)
                    and usage <= retained_target
                )
                authoritative_low_water_reached = low_water_reached
                compaction_note["low_water_reached"] = low_water_reached
                compaction_note["post_epoch_input_usage"] = usage
                return {
                    "continue": not low_water_reached,
                    "auto_pressure": auto_pressure,
                    "hard_safe": hard_safe,
                    "preflight_input_usage": usage,
                    "retained_target": retained_target,
                    "low_water_reached": low_water_reached,
                    "reason": gate.get("reason", "unknown"),
                }

            async def run_l4_if_needed(
                trigger_gate: Mapping[str, object] | None,
            ) -> bool:
                """Run the single bounded L4 catch-up for this active Turn."""

                nonlocal compaction_orchestration_started
                if trigger_gate is None:
                    return False
                needs_compaction = bool(
                    trigger_gate.get("auto_pressure", False)
                    or not bool(trigger_gate.get("hard_safe", False))
                )
                if not needs_compaction or compaction_orchestration_started:
                    return False
                compaction_orchestration_started = True
                compaction_note["attempted"] = True
                previous_estimate = trigger_gate.get("preflight_input_usage")
                if not isinstance(previous_estimate, int):
                    previous_estimate = trigger_gate.get("input_tokens")
                if isinstance(previous_estimate, int):
                    compaction_note["previous_estimate"] = previous_estimate
                active = (
                    self._session_service.active_session
                    if self._session_service is not None
                    else None
                )
                if active is None:
                    compaction_note.update(
                        {
                            "status": "unresolved",
                            "failure": "no_active_session",
                            "auto_pressure_unresolved": bool(
                                trigger_gate.get("auto_pressure", False)
                            ),
                        }
                    )
                    return False

                result = await self._context_service.compact_async(
                    active.transcript,
                    timeline=active.timeline,
                    session_id=active.session_id,
                    summarize=summarize_epoch,
                    commit=commit_epoch,
                    should_continue=rebuild_after_epoch,
                    cancellation=cancellation,
                    max_epochs=4,
                    active_turn_id=turn_id,
                    input_budget=frozen_budget.compaction_input_budget
                    if frozen_budget is not None
                    else None,
                    output_reserve=(
                        min(
                            frozen_budget.compaction_output_reserve,
                            frozen_budget.provider_max_output,
                        )
                        if frozen_budget is not None
                        and frozen_budget.provider_max_output is not None
                        else (
                            frozen_budget.compaction_output_reserve
                            if frozen_budget is not None
                            else None
                        )
                    ),
                    summary_hard_cap=(
                        min(
                            frozen_budget.compaction_output_reserve,
                            frozen_budget.provider_max_output,
                        )
                        if frozen_budget is not None
                        and frozen_budget.provider_max_output is not None
                        else (
                            frozen_budget.compaction_output_reserve
                            if frozen_budget is not None
                            else None
                        )
                    ),
                    trigger="auto",
                )
                final_gate = authoritative_gate_after_compaction
                if final_gate is None:
                    fallback_gate = gate_from_request(compose(None, True, None))
                    final_gate = None if fallback_gate is None else dict(fallback_gate)
                final_auto = bool(
                    final_gate is not None
                    and final_gate.get("auto_pressure", False)
                    and not authoritative_low_water_reached
                )
                final_hard = bool(
                    final_gate is not None
                    and final_gate.get("hard_safe", False)
                )
                compaction_note.update(
                    {
                        "status": (
                            "completed"
                            if result.changed and result.failure is None
                            else "unresolved"
                        ),
                        "failure": result.failure,
                        "auto_pressure_unresolved": final_auto,
                        "gate_after_compaction": (
                            None if final_gate is None else dict(final_gate)
                        ),
                    }
                )
                if final_auto:
                    compaction_note["failure"] = (
                        result.failure or "auto_pressure_unresolved"
                    )
                if result.failure is not None and not final_hard:
                    # Let the final counted ordinary request fail closed.  A
                    # Hard-safe request remains sendable with the reason kept
                    # in the bounded compaction note.
                    compaction_note["status"] = "unresolved"
                return result.changed

            async def run_l5_if_needed() -> bool:
                """Run one independent Fine Timeline aging attempt."""

                nonlocal timeline_aging_started
                aging_note = compaction_note["timeline_aging"]
                if not isinstance(aging_note, dict):  # pragma: no cover - local invariant
                    return False
                if timeline_aging_started:
                    return False
                active = (
                    self._session_service.active_session
                    if self._session_service is not None
                    else None
                )
                if active is None or frozen_budget is None:
                    aging_note.update({"status": "no_change", "failure": "no_active_session"})
                    timeline_aging_started = True
                    return False
                fine_budget = frozen_budget.fine_timeline_budget
                if fine_budget is None:
                    aging_note.update({"status": "no_change", "failure": "fine_budget_unavailable"})
                    timeline_aging_started = True
                    return False
                usage = fine_timeline_usage(
                    active.timeline,
                    self._context_service.compiler.token_estimator,
                )
                aging_note.update(
                    {
                        "previous_fine_usage": usage,
                        "fine_budget": fine_budget,
                    }
                )
                if usage <= fine_budget:
                    aging_note["status"] = "no_change"
                    timeline_aging_started = True
                    return False
                timeline_aging_started = True
                aging_note["attempted"] = True
                try:
                    result = await self._context_service.age_timeline_async(
                        active.transcript,
                        timeline=active.timeline,
                        session_id=active.session_id,
                        summarize=summarize_aging_epoch,
                        commit=commit_aging_epoch,
                        cancellation=cancellation,
                        fine_budget=fine_budget,
                        active_turn_id=turn_id,
                        input_budget=frozen_budget.compaction_input_budget,
                        output_reserve=(
                            min(
                                frozen_budget.compaction_output_reserve,
                                frozen_budget.provider_max_output,
                            )
                            if frozen_budget.provider_max_output is not None
                            else frozen_budget.compaction_output_reserve
                        ),
                        summary_hard_cap=(
                            min(
                                frozen_budget.compaction_output_reserve,
                                frozen_budget.provider_max_output,
                            )
                            if frozen_budget.provider_max_output is not None
                            else frozen_budget.compaction_output_reserve
                        ),
                        trigger="auto",
                    )
                except ContextRequestSafetyError:
                    aging_note.update(
                        {
                            "status": "unresolved",
                            "failure": "provider_request_unsafe",
                        }
                    )
                    return False
                aging_note.update(
                    {
                        "status": "completed" if result.changed and result.failure is None else "unresolved",
                        "failure": result.failure,
                    }
                )
                return result.changed and result.failure is None

            async def on_counted_request(
                counted_request: GenerationRequest,
                _provider_count: ContextCountEstimate | int | None,
            ) -> bool:
                """Catch exact-count Pressure/Hard failures before finalize."""

                return await run_l4_if_needed(gate_from_request(counted_request))

            try:
                initial_request = compose(None, True, None)
                aged = await run_l5_if_needed()
                if aged:
                    initial_request = compose(None, True, None)
                await run_l4_if_needed(gate_from_request(initial_request))
                if cancellation.cancelled:
                    raise CancelledError()
                prepared_request = await _prepare_counted_request_async(
                    provider,
                    compose,
                    finalize,
                    on_counted_request=on_counted_request,
                )
                self._request_boundary_counts[request_boundary_key] += 1
                return prepared_request
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

    def _environment_sources(
        self,
        model_ref: str,
        identity: ProviderIdentity,
    ) -> tuple[ContextBlock, ...]:
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
            ContextBlock(
                source_kind=ContextSourceKind.ENVIRONMENT_FACT,
                authority=ContextAuthority.ENVIRONMENT,
                stability=ContextStability.DYNAMIC,
                scope=ContextScope.TURN,
                provenance="application:environment",
                content=content,
            ),
        )

__all__ = [
    "ApplicationStatus",
    "UthCodeApplication",
]
