"""Provider-independent Context compilation and request-safety contracts.

The compiler deliberately knows nothing about a Provider, a filesystem, or a
UI.  Runtime limits and request counts arrive as UthCode-owned values; this
module applies deterministic working-set and gate policy without guessing a
model window.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from .history import (
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
from .compaction import (
    CompactionEntry,
    CompactionEpoch,
    CompactionStructuredResult,
    CompactionValidationError,
    TimelineAgingEpoch,
    TimelineAgingResult,
    parse_compaction_result,
    parse_timeline_aging_result,
)
from .prompt import (
    ContextAuthority,
    ContextBlock,
    ContextPlane,
    ContextScope,
    ContextSourceKind,
    ContextStability,
    ProjectInstructionSource,
    ToolDefinitionSource,
    build_instruction_prefix,
    core_runtime_contract_source,
    public_prompt_source,
)
from .provider import (
    CancellationToken,
    ContextCountEstimate,
    GenerationRequest,
    Message,
    ModelLimits,
    TextPart,
    ToolCallPart,
    ToolDefinition,
    ToolResultPart,
)

class ContextCompilationError(ValueError):
    """A Context source or compiler input violates the Core contract."""


class ContextBudgetError(ValueError):
    """The known input limits cannot form a safe operating budget."""


class ContextRequestSafetyError(ContextBudgetError):
    """A final Provider-visible request is not safe to send."""


DEFAULT_CONTEXT_INPUT_LIMIT = 256_000
_DEFAULT_CONTEXT_WORKING_HEADROOM = 48_000
_DEFAULT_CONTEXT_RETAINED_TARGET = 96_000
_DEFAULT_CONTEXT_COMPACTION_OUTPUT_RESERVE = 4_096
_DEFAULT_CONTEXT_SAFETY_ALLOWANCE = 8_192


def adaptive_working_headroom(effective_input_limit: int) -> int:
    """Return the proactive reserve for one effective input limit.

    The selected 256K Operating Profile uses its measured fixed reserve;
    other windows use the bounded adaptive policy.  The reserve is a policy
    input to Auto Gate, never a Provider safety proof or a percentage-only
    rule.
    """

    if (
        isinstance(effective_input_limit, bool)
        or not isinstance(effective_input_limit, int)
        or effective_input_limit <= 0
    ):
        raise ValueError("effective_input_limit must be a positive integer")
    if effective_input_limit == DEFAULT_CONTEXT_INPUT_LIMIT:
        return _DEFAULT_CONTEXT_WORKING_HEADROOM
    return min(
        48_000,
        max(512, effective_input_limit // 20),
        # Leave two tokens for the strict High/Low pair.  With an effective
        # limit of N >= 3 this guarantees High >= 2, so the default Low can
        # remain a positive integer strictly below it.
        max(1, effective_input_limit - 2),
    )


def safety_allowance_for(
    effective_input_limit: int,
    *,
    kind: str,
) -> int:
    """Return the centralized uncertainty allowance for a count source."""

    if kind == "pressure_estimate":
        return min(4_096, max(64, effective_input_limit // 50), max(0, effective_input_limit - 1))
    if kind == "preflight_provider_count":
        return min(2_048, max(32, effective_input_limit // 100), max(0, effective_input_limit - 1))
    if kind == "preflight_local_estimate":
        return min(8_192, max(128, effective_input_limit // 20), max(0, effective_input_limit - 1))
    raise ValueError("unsupported count kind")


@dataclass(frozen=True, slots=True)
class ContextBudget:
    """The independent dimensions used to govern one request."""

    configured_input_limit: int | None = None
    provider_max_input: int | None = None
    default_input_limit: int = field(default=DEFAULT_CONTEXT_INPUT_LIMIT, init=False)
    effective_input_limit: int | None = None
    observed_input_sources: tuple[str, ...] = field(default=(), init=False)
    effective_input_source: str | None = field(default=None, init=False)
    tightened_input_sources: tuple[str, ...] = field(default=(), init=False)
    provider_max_output: int | None = None
    provider_combined_limit: int | None = None
    requested_output_reserve: int = 0
    safety_allowance: int = 0
    working_headroom: int | None = None
    auto_gate_limit: int | None = None
    fine_timeline_budget: int | None = None
    retained_target: int | None = None
    compaction_input_budget: int | None = None
    compaction_output_reserve: int | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "configured_input_limit",
            "provider_max_input",
            "default_input_limit",
            "provider_max_output",
            "provider_combined_limit",
        ):
            value = getattr(self, field_name)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value <= 0
            ):
                raise ValueError(f"{field_name} must be a positive integer or None")
        observed_sources = tuple(
            source
            for source, value in (
                ("configured", self.configured_input_limit),
                ("provider", self.provider_max_input),
            )
            if value is not None
        )
        if self.configured_input_limit is not None:
            resolved_effective = self.configured_input_limit
            resolved_source = "configured"
            tightened_sources: tuple[str, ...] = ()
            if (
                self.provider_max_input is not None
                and self.provider_max_input < resolved_effective
            ):
                resolved_effective = self.provider_max_input
                resolved_source = "provider"
                tightened_sources = ("provider",)
        else:
            resolved_effective = self.default_input_limit
            resolved_source = "default"
            tightened_sources = ()
            if self.provider_max_input is not None:
                if self.provider_max_input < resolved_effective:
                    resolved_effective = self.provider_max_input
                    resolved_source = "provider"
                    tightened_sources = ("provider",)
                elif self.provider_max_input > resolved_effective:
                    tightened_sources = ("default",)

        effective = self.effective_input_limit
        if effective is None:
            effective = resolved_effective
            object.__setattr__(self, "effective_input_limit", effective)
        elif effective != resolved_effective:
            raise ContextBudgetError(
                "effective_input_limit must equal the resolved operating limit"
            )
        object.__setattr__(self, "observed_input_sources", observed_sources)
        object.__setattr__(self, "effective_input_source", resolved_source)
        object.__setattr__(self, "tightened_input_sources", tightened_sources)
        if (
            isinstance(effective, bool)
            or not isinstance(effective, int)
            or effective <= 0
        ):
            raise ValueError("effective_input_limit must be a positive integer")
        if effective < 3:
            raise ContextBudgetError(
                "effective input limit must be at least 3 to separate High and Low Water"
            )
        for field_name in ("requested_output_reserve", "safety_allowance"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")

        reserve = self.working_headroom
        if reserve is None:
            reserve = adaptive_working_headroom(effective)
            object.__setattr__(self, "working_headroom", reserve)
        if isinstance(reserve, bool) or not isinstance(reserve, int) or not 0 < reserve < effective:
            raise ValueError("working_headroom must be positive and smaller than the input limit")
        auto_gate = self.auto_gate_limit
        if auto_gate is None:
            auto_gate = effective - reserve
            object.__setattr__(self, "auto_gate_limit", auto_gate)
        if isinstance(auto_gate, bool) or not isinstance(auto_gate, int) or not 0 < auto_gate < effective:
            raise ValueError("auto_gate_limit must be positive and smaller than the input limit")

        fine = self.fine_timeline_budget
        if fine is None:
            fine = min(effective, max(1, min(16_000, max(64, effective // 16))))
            object.__setattr__(self, "fine_timeline_budget", fine)
        if isinstance(fine, bool) or not isinstance(fine, int) or fine <= 0:
            raise ValueError("fine_timeline_budget must be a positive integer")

        retained_target = self.retained_target
        if retained_target is None:
            if effective == DEFAULT_CONTEXT_INPUT_LIMIT:
                retained_target = _DEFAULT_CONTEXT_RETAINED_TARGET
            else:
                # Keep the bounded adaptive policy for configured/provider
                # windows that are smaller or larger than the 256K target.
                retained_target = min(
                    auto_gate - 1,
                    min(48_000, max(128, effective // 5))
                    + fine
                    + min(8_000, max(64, effective // 32)),
                )
            object.__setattr__(self, "retained_target", retained_target)
        if (
            isinstance(retained_target, bool)
            or not isinstance(retained_target, int)
            or retained_target <= 0
            or retained_target >= auto_gate
        ):
            raise ValueError(
                "retained_target must be positive and strictly smaller than auto_gate_limit"
            )

        compact_input = self.compaction_input_budget
        if compact_input is None:
            compact_input = min(effective, min(64_000, max(256, effective // 4)))
            object.__setattr__(self, "compaction_input_budget", compact_input)
        compact_output = self.compaction_output_reserve
        if compact_output is None:
            if effective == DEFAULT_CONTEXT_INPUT_LIMIT:
                compact_output = _DEFAULT_CONTEXT_COMPACTION_OUTPUT_RESERVE
            else:
                compact_output = min(
                    max(1, compact_input - 1),
                    min(4_096, max(32, effective // 64)),
                )
            object.__setattr__(self, "compaction_output_reserve", compact_output)
        if (
            isinstance(compact_input, bool)
            or not isinstance(compact_input, int)
            or compact_input <= 0
            or isinstance(compact_output, bool)
            or not isinstance(compact_output, int)
            or compact_output <= 0
            or compact_output >= compact_input
        ):
            raise ValueError("compaction budgets are invalid")

    @classmethod
    def from_limits(
        cls,
        *,
        configured_input_limit: int | None,
        provider_limits: ModelLimits | None,
        requested_output_reserve: int = 0,
        safety_allowance: int | None = None,
    ) -> "ContextBudget":
        if provider_limits is not None and not isinstance(provider_limits, ModelLimits):
            raise TypeError("provider_limits must be ModelLimits or None")
        # An omitted allowance selects the tuned default only for the 256K
        # operating window; callers that need a zero allowance pass 0.
        budget = cls(
            configured_input_limit=configured_input_limit,
            provider_max_input=(
                provider_limits.max_input_tokens if provider_limits is not None else None
            ),
            provider_max_output=(
                provider_limits.max_output_tokens if provider_limits is not None else None
            ),
            provider_combined_limit=(
                provider_limits.max_combined_tokens if provider_limits is not None else None
            ),
            requested_output_reserve=requested_output_reserve,
            safety_allowance=(0 if safety_allowance is None else safety_allowance),
        )
        if (
            safety_allowance is None
            and budget.effective_input_limit == DEFAULT_CONTEXT_INPUT_LIMIT
        ):
            object.__setattr__(budget, "safety_allowance", _DEFAULT_CONTEXT_SAFETY_ALLOWANCE)
        return budget

    def to_dict(self) -> dict[str, object]:
        return {
            "configured_input_limit": self.configured_input_limit,
            "provider_max_input": self.provider_max_input,
            "default_input_limit": self.default_input_limit,
            "effective_input_limit": self.effective_input_limit,
            "observed_input_sources": list(self.observed_input_sources),
            "effective_input_source": self.effective_input_source,
            "tightened_input_sources": list(self.tightened_input_sources),
            "provider_max_output": self.provider_max_output,
            "provider_combined_limit": self.provider_combined_limit,
            "requested_output_reserve": self.requested_output_reserve,
            "safety_allowance": self.safety_allowance,
            "working_headroom": self.working_headroom,
            "auto_gate_limit": self.auto_gate_limit,
            "fine_timeline_budget": self.fine_timeline_budget,
            "retained_target": self.retained_target,
            "compaction_input_budget": self.compaction_input_budget,
            "compaction_output_reserve": self.compaction_output_reserve,
        }


@dataclass(frozen=True, slots=True)
class GateDecision:
    """One transparent Pressure/Preflight result for a final request."""

    input_tokens: int
    count_source: str
    requested_output_reserve: int
    safety_allowance: int
    preflight_input_usage: int
    auto_pressure: bool
    hard_safe: bool
    auto_gate_limit: int
    effective_input_limit: int
    provider_output_limit: int | None
    provider_combined_limit: int | None
    input_safe: bool
    output_safe: bool
    combined_safe: bool
    reason: str
    framing_tokens: int = 0

    def __post_init__(self) -> None:
        for field_name in (
            "input_tokens",
            "requested_output_reserve",
            "safety_allowance",
            "preflight_input_usage",
            "auto_gate_limit",
            "effective_input_limit",
            "framing_tokens",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")
        for field_name in (
            "auto_pressure",
            "hard_safe",
            "input_safe",
            "output_safe",
            "combined_safe",
        ):
            if not isinstance(getattr(self, field_name), bool):
                raise TypeError(f"{field_name} must be a boolean")
        if self.provider_output_limit is not None and self.provider_output_limit <= 0:
            raise ValueError("provider_output_limit must be positive or None")
        if self.provider_combined_limit is not None and self.provider_combined_limit <= 0:
            raise ValueError("provider_combined_limit must be positive or None")
        if not isinstance(self.count_source, str) or not self.count_source:
            raise ValueError("count_source must be a non-empty string")
        if not isinstance(self.reason, str) or not self.reason:
            raise ValueError("reason must be a non-empty string")

    def to_dict(self) -> dict[str, object]:
        return {
            "input_tokens": self.input_tokens,
            "count_source": self.count_source,
            "requested_output_reserve": self.requested_output_reserve,
            "safety_allowance": self.safety_allowance,
            "preflight_input_usage": self.preflight_input_usage,
            "auto_pressure": self.auto_pressure,
            "hard_safe": self.hard_safe,
            "auto_gate_limit": self.auto_gate_limit,
            "effective_input_limit": self.effective_input_limit,
            "provider_output_limit": self.provider_output_limit,
            "provider_combined_limit": self.provider_combined_limit,
            "input_safe": self.input_safe,
            "output_safe": self.output_safe,
            "combined_safe": self.combined_safe,
            "reason": self.reason,
            "framing_tokens": self.framing_tokens,
        }


class CompactionError(ValueError):
    """A bounded Compaction request could not produce a safe Timeline."""


class CompactionInProgress(CompactionError):
    """A second Compaction for the same Session was rejected by single-flight."""


@dataclass(frozen=True, slots=True)
class CompactionPolicy:
    """Provider-independent hard limits for one Compactor invocation."""

    input_budget: int = 64_000
    output_reserve: int = 4_096
    summary_hard_cap: int = 2_048

    def __post_init__(self) -> None:
        for field_name in ("input_budget", "output_reserve", "summary_hard_cap"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{field_name} must be a positive integer")
        if self.output_reserve >= self.input_budget:
            raise ValueError("output_reserve must be smaller than input_budget")
        if self.summary_hard_cap > self.input_budget - self.output_reserve:
            raise ValueError("summary_hard_cap must fit inside the Compaction input budget")

    @property
    def compaction_input_budget(self) -> int:
        return self.input_budget

    @property
    def compaction_output_reserve(self) -> int:
        return self.output_reserve

    @property
    def available_input_budget(self) -> int:
        return self.input_budget - self.output_reserve


@dataclass(frozen=True, slots=True)
class CompactionBatch:
    """One complete-semantic-unit batch sent to a tool-free summarizer."""

    unit_ids: tuple[str, ...]
    sequence_start: int
    sequence_end: int
    input_text: str
    input_tokens: int
    output_summary: str


@dataclass(frozen=True, slots=True)
class CompactionResult:
    """A bounded Timeline candidate; failed candidates retain old records."""

    timeline: Timeline | None
    summary: str | None
    batches: tuple[CompactionBatch, ...] = ()
    changed: bool = False
    failure: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0

    def __post_init__(self) -> None:
        if self.timeline is not None and not isinstance(self.timeline, Timeline):
            raise TypeError("timeline must be a Timeline or None")
        if self.summary is not None and not isinstance(self.summary, str):
            raise TypeError("summary must be a string or None")
        if not isinstance(self.changed, bool):
            raise TypeError("changed must be a boolean")
        if self.failure is not None and not isinstance(self.failure, str):
            raise TypeError("failure must be a string or None")
        for field_name in ("input_tokens", "output_tokens"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")
        object.__setattr__(self, "batches", tuple(self.batches))


SummaryFunction = Callable[[str], str]


@dataclass(frozen=True, slots=True)
class DeterministicTokenEstimator:
    """Stable fallback estimator used when no tokenizer is injected.

    Four UTF-8 bytes per estimated token is intentionally only an operating
    estimate.  It is never presented as Provider billing or a remote context
    window.
    """

    bytes_per_token: int = 4

    def __post_init__(self) -> None:
        if (
            isinstance(self.bytes_per_token, bool)
            or not isinstance(self.bytes_per_token, int)
            or self.bytes_per_token <= 0
        ):
            raise ValueError("bytes_per_token must be a positive integer")

    def __call__(self, text: str) -> int:
        if not isinstance(text, str):
            raise TypeError("token estimator input must be a string")
        if not text:
            return 0
        return max(1, (len(text.encode("utf-8")) + self.bytes_per_token - 1) // self.bytes_per_token)


def _resolve_token_estimator(
    value: Callable[[str], int] | None,
) -> Callable[[str], int]:
    estimator = DeterministicTokenEstimator() if value is None else value
    if not callable(estimator):
        raise TypeError("token_estimator must be callable")
    return estimator


def _estimate_tokens(estimator: Callable[[str], int], text: str) -> int:
    value = estimator(text)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("token estimator must return a non-negative integer")
    return value


@dataclass(frozen=True, slots=True)
class RequestAccounting:
    """Deterministic accounting for the complete Provider-visible input.

    The fields are deliberately structural rather than Provider billing facts.
    They make it possible for Application diagnostics and tests to prove that
    instruction, messages, tools, and known framing were all considered.
    """

    instruction_tokens: int
    messages_tokens: int
    tools_tokens: int
    framing_tokens: int

    def __post_init__(self) -> None:
        for field_name in (
            "instruction_tokens",
            "messages_tokens",
            "tools_tokens",
            "framing_tokens",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")

    @property
    def input_tokens(self) -> int:
        return (
            self.instruction_tokens
            + self.messages_tokens
            + self.tools_tokens
            + self.framing_tokens
        )

    def to_dict(self) -> dict[str, int]:
        return {
            "instruction_tokens": self.instruction_tokens,
            "messages_tokens": self.messages_tokens,
            "tools_tokens": self.tools_tokens,
            "framing_tokens": self.framing_tokens,
            "input_tokens": self.input_tokens,
        }


def account_generation_request(
    request: GenerationRequest,
    *,
    token_estimator: Callable[[str], int] | None = None,
) -> RequestAccounting:
    """Count one complete request using a stable local serialization.

    This is an estimate, not a claim about Provider tokenizer exactness.  The
    serialization includes the same UthCode-owned instruction, message, and
    tool structures that the integrations receive, plus explicit role/schema
    framing.  Provider integrations may replace the numeric estimate with a
    structured count while retaining the same Gate contract.
    """

    if not isinstance(request, GenerationRequest):
        raise TypeError("request must be a GenerationRequest")
    estimator = _resolve_token_estimator(token_estimator)

    instruction = request.system_prompt or ""
    messages = json.dumps(
        [message.to_dict() for message in request.messages],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    tools = json.dumps(
        [tool.to_dict() for tool in request.tools],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    framing = json.dumps(
        {
            "instruction_channel": "system" if request.system_prompt else "none",
            "message_roles": [message.role for message in request.messages],
            "message_count": len(request.messages),
            "tool_count": len(request.tools),
            "markers": ["request_start", "role", "part", "request_end"],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return RequestAccounting(
        instruction_tokens=_estimate_tokens(estimator, instruction),
        messages_tokens=_estimate_tokens(estimator, messages),
        tools_tokens=_estimate_tokens(estimator, tools),
        framing_tokens=_estimate_tokens(estimator, framing),
    )


def _count_estimate(
    value: ContextCountEstimate | int | None,
    *,
    kind: str,
    source: str,
    effective_input_limit: int,
    fallback_request: GenerationRequest | None = None,
    token_estimator: Callable[[str], int] | None = None,
) -> ContextCountEstimate:
    if isinstance(value, ContextCountEstimate):
        input_tokens = value.input_tokens
        count_source = value.source
    elif value is None:
        if fallback_request is None:
            raise ContextBudgetError("a preflight count or final request is required")
        input_tokens = account_generation_request(
            fallback_request,
            token_estimator=token_estimator,
        ).input_tokens
        count_source = source
    elif isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise TypeError("token count must be ContextCountEstimate, non-negative int, or None")
    else:
        input_tokens = value
        count_source = source
    return ContextCountEstimate(
        input_tokens=input_tokens,
        source=count_source,
        kind=kind,
        safety_allowance=safety_allowance_for(
            effective_input_limit,
            kind=kind,
        ),
    )


def pressure_estimate(
    request: GenerationRequest,
    budget: ContextBudget,
    *,
    token_estimator: Callable[[str], int] | None = None,
) -> ContextCountEstimate:
    """Return the proactive Auto Gate estimate for a final request."""

    if not isinstance(budget, ContextBudget):
        raise TypeError("budget must be a ContextBudget")
    return _count_estimate(
        None,
        kind="pressure_estimate",
        source="local.pressure_estimate",
        effective_input_limit=budget.effective_input_limit,
        fallback_request=request,
        token_estimator=token_estimator,
    )


def preflight_safety_count(
    request: GenerationRequest,
    budget: ContextBudget,
    *,
    provider_count: ContextCountEstimate | int | None = None,
    token_estimator: Callable[[str], int] | None = None,
) -> ContextCountEstimate:
    """Count the final request for the fail-closed Hard Gate."""

    if not isinstance(budget, ContextBudget):
        raise TypeError("budget must be a ContextBudget")
    return _count_estimate(
        provider_count,
        kind=(
            "preflight_provider_count"
            if provider_count is not None
            else "preflight_local_estimate"
        ),
        source=(
            "provider.preflight_count"
            if provider_count is not None
            else "local.preflight_estimate"
        ),
        effective_input_limit=budget.effective_input_limit,
        fallback_request=request,
        token_estimator=token_estimator,
    )


def evaluate_gates(
    budget: ContextBudget,
    count: ContextCountEstimate,
    *,
    accounting: RequestAccounting | None = None,
    pressure_count: ContextCountEstimate | None = None,
) -> GateDecision:
    """Evaluate independent Auto and Hard decisions for one request."""

    if not isinstance(budget, ContextBudget):
        raise TypeError("budget must be a ContextBudget")
    if not isinstance(count, ContextCountEstimate):
        raise TypeError("count must be a ContextCountEstimate")
    if pressure_count is not None and not isinstance(
        pressure_count, ContextCountEstimate
    ):
        raise TypeError("pressure_count must be a ContextCountEstimate or None")
    allowance = max(budget.safety_allowance, count.safety_allowance)
    preflight_usage = count.input_tokens + allowance
    input_safe = preflight_usage <= budget.effective_input_limit
    output_safe = (
        budget.provider_max_output is None
        or budget.requested_output_reserve <= budget.provider_max_output
    )
    combined_safe = (
        budget.provider_combined_limit is None
        or preflight_usage + budget.requested_output_reserve
        <= budget.provider_combined_limit
    )
    pressure = count if pressure_count is None else pressure_count
    pressure_allowance = max(budget.safety_allowance, pressure.safety_allowance)
    auto_pressure = (
        pressure.input_tokens + pressure_allowance > budget.auto_gate_limit
    )
    reasons: list[str] = []
    if not input_safe:
        reasons.append("input_limit_exceeded")
    if not output_safe:
        reasons.append("output_limit_exceeded")
    if not combined_safe:
        reasons.append("combined_limit_exceeded")
    if not reasons:
        reasons.append("auto_pressure" if auto_pressure else "safe")
    return GateDecision(
        input_tokens=count.input_tokens,
        count_source=count.source,
        requested_output_reserve=budget.requested_output_reserve,
        safety_allowance=allowance,
        preflight_input_usage=preflight_usage,
        auto_pressure=auto_pressure,
        hard_safe=input_safe and output_safe and combined_safe,
        auto_gate_limit=budget.auto_gate_limit,
        effective_input_limit=budget.effective_input_limit,
        provider_output_limit=budget.provider_max_output,
        provider_combined_limit=budget.provider_combined_limit,
        input_safe=input_safe,
        output_safe=output_safe,
        combined_safe=combined_safe,
        reason="+".join(reasons),
        framing_tokens=(accounting.framing_tokens if accounting is not None else 0),
    )


def preflight_gate(
    budget: ContextBudget,
    count: ContextCountEstimate,
    *,
    accounting: RequestAccounting | None = None,
    pressure_count: ContextCountEstimate | None = None,
) -> GateDecision:
    """Named alias for the final Preflight Hard Gate calculation."""

    return evaluate_gates(
        budget,
        count,
        accounting=accounting,
        pressure_count=pressure_count,
    )


def resolve_context_budget(
    *,
    configured_input_limit: int | None,
    provider_limits: ModelLimits | None,
    requested_output_reserve: int = 0,
    safety_allowance: int | None = None,
) -> ContextBudget:
    """Build the one dynamic budget authority used by Application."""

    return ContextBudget.from_limits(
        configured_input_limit=configured_input_limit,
        provider_limits=provider_limits,
        requested_output_reserve=requested_output_reserve,
        safety_allowance=safety_allowance,
    )


@dataclass(frozen=True, slots=True)
class ContextSourceBundle:
    """The complete, strongly typed input to one Context compilation."""

    instruction_sources: tuple[ContextBlock, ...] = ()
    project_instruction_source: ProjectInstructionSource | None = None
    transcript: Transcript | None = None
    timeline: Timeline | None = None
    protected_context: tuple[ContextBlock, ...] = ()
    protocol_blocks: tuple[ContextBlock, ...] = ()
    current_turn: tuple[ContextBlock | Message | str, ...] = ()
    current_turn_deltas: tuple[ContextBlock | Message | str, ...] = ()
    runtime_sources: tuple[ContextBlock, ...] = ()
    environment_sources: tuple[ContextBlock, ...] = ()
    tool_source: ToolDefinitionSource | None = None

    def __post_init__(self) -> None:
        def values_for(name: str) -> tuple[object, ...]:
            value = getattr(self, name)
            if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
                raise TypeError(f"{name} must be a sequence")
            return tuple(value)

        def context_blocks(
            name: str,
            *,
            authority: ContextAuthority | None = None,
        ) -> tuple[ContextBlock, ...]:
            values = values_for(name)
            if not all(isinstance(item, ContextBlock) for item in values):
                raise TypeError(f"{name} must contain ContextBlock values")
            blocks = tuple(values)
            if any(block.plane is ContextPlane.INSTRUCTION for block in blocks):
                raise ContextCompilationError(
                    f"{name} cannot contain Instruction Plane blocks"
                )
            if authority is not None and any(
                block.authority is not authority for block in blocks
            ):
                raise ContextCompilationError(
                    f"{name} must contain {authority.value} ContextBlock values"
                )
            return blocks

        instruction_sources = values_for("instruction_sources")
        if not all(isinstance(item, ContextBlock) for item in instruction_sources):
            raise TypeError("instruction_sources must contain ContextBlock values")
        if any(not item.is_instruction for item in instruction_sources):
            raise ContextCompilationError(
                "instruction_sources must contain Instruction Plane blocks"
            )
        object.__setattr__(self, "instruction_sources", tuple(instruction_sources))
        object.__setattr__(
            self,
            "protected_context",
            context_blocks("protected_context"),
        )
        object.__setattr__(
            self,
            "protocol_blocks",
            context_blocks("protocol_blocks"),
        )
        for name in ("current_turn", "current_turn_deltas"):
            values = values_for(name)
            if not all(isinstance(item, (ContextBlock, Message, str)) for item in values):
                raise TypeError(
                    f"{name} must contain ContextBlock, Message, or string values"
                )
            if any(
                isinstance(item, ContextBlock)
                and item.plane is ContextPlane.INSTRUCTION
                for item in values
            ):
                raise ContextCompilationError(
                    f"{name} cannot contain Instruction Plane blocks"
                )
            object.__setattr__(self, name, tuple(values))
        object.__setattr__(
            self,
            "runtime_sources",
            context_blocks("runtime_sources", authority=ContextAuthority.RUNTIME),
        )
        object.__setattr__(
            self,
            "environment_sources",
            context_blocks("environment_sources", authority=ContextAuthority.ENVIRONMENT),
        )
        if self.project_instruction_source is not None and not isinstance(
            self.project_instruction_source, ProjectInstructionSource
        ):
            raise TypeError("project_instruction_source must be ProjectInstructionSource or None")
        if self.transcript is not None and not isinstance(self.transcript, Transcript):
            raise TypeError("transcript must be Transcript or None")
        if self.timeline is not None and not isinstance(self.timeline, Timeline):
            raise TypeError("timeline must be Timeline or None")
        if self.tool_source is not None and not isinstance(self.tool_source, ToolDefinitionSource):
            raise TypeError("tool_source must be ToolDefinitionSource or None")
        if self.transcript is not None and self.timeline is not None:
            if self.transcript.session_id != self.timeline.session_id:
                raise ContextCompilationError("transcript and timeline belong to different sessions")


@dataclass(frozen=True, slots=True)
class ContextUsage:
    """Safe usage projection for later Application/UI consumers."""

    used_tokens: int
    budget_tokens: int | None = None
    available: bool = True

    def __post_init__(self) -> None:
        if isinstance(self.used_tokens, bool) or not isinstance(self.used_tokens, int) or self.used_tokens < 0:
            raise ValueError("used_tokens must be a non-negative integer")
        if self.budget_tokens is not None and (
            isinstance(self.budget_tokens, bool)
            or not isinstance(self.budget_tokens, int)
            or self.budget_tokens <= 0
        ):
            raise ValueError("budget_tokens must be a positive integer or None")
        if not isinstance(self.available, bool):
            raise TypeError("available must be a boolean")

    @property
    def ratio(self) -> float | None:
        if not self.available:
            return None
        if self.budget_tokens is None:
            return None
        return self.used_tokens / self.budget_tokens

    def to_dict(self) -> dict[str, object]:
        return {
            "used_tokens": self.used_tokens,
            "budget_tokens": self.budget_tokens,
            "ratio": self.ratio,
            "available": self.available,
        }


@dataclass(frozen=True, slots=True)
class ContextSnapshot:
    """Immutable result of one deterministic Context compilation."""

    budget_tokens: int | None
    token_estimate: int
    selected_blocks: tuple[ContextBlock, ...]
    omitted_blocks: tuple[ContextBlock, ...]
    omitted_reasons: tuple[tuple[str, str], ...]
    timeline_checkpoint: ActiveCheckpoint | None
    instruction_epoch: int
    stable_prefix_estimated_tokens: int
    stable_prefix_fingerprint: str
    prefix_changed: bool
    prefix_change_reason: str
    tool_schema_fingerprint: str | None = None
    tool_schema_estimated_tokens: int = 0
    tool_definitions: tuple[ToolDefinition, ...] = ()
    over_budget: bool = False

    def __post_init__(self) -> None:
        if self.budget_tokens is not None and (
            isinstance(self.budget_tokens, bool)
            or not isinstance(self.budget_tokens, int)
            or self.budget_tokens <= 0
        ):
            raise ValueError("budget_tokens must be a positive integer or None")
        if isinstance(self.token_estimate, bool) or not isinstance(self.token_estimate, int) or self.token_estimate < 0:
            raise ValueError("token_estimate must be a non-negative integer")
        selected = tuple(self.selected_blocks)
        omitted = tuple(self.omitted_blocks)
        if not all(isinstance(block, ContextBlock) for block in (*selected, *omitted)):
            raise TypeError("selected_blocks and omitted_blocks must contain ContextBlock values")
        if isinstance(self.instruction_epoch, bool) or not isinstance(self.instruction_epoch, int) or self.instruction_epoch < 0:
            raise ValueError("instruction_epoch must be a non-negative integer")
        if isinstance(self.stable_prefix_estimated_tokens, bool) or not isinstance(self.stable_prefix_estimated_tokens, int) or self.stable_prefix_estimated_tokens < 0:
            raise ValueError("stable_prefix_estimated_tokens must be a non-negative integer")
        if not isinstance(self.stable_prefix_fingerprint, str) or not self.stable_prefix_fingerprint.strip():
            raise ValueError("stable_prefix_fingerprint must be a non-empty string")
        if not isinstance(self.prefix_changed, bool):
            raise TypeError("prefix_changed must be a boolean")
        if not isinstance(self.prefix_change_reason, str) or not self.prefix_change_reason.strip():
            raise ValueError("prefix_change_reason must be a non-empty string")
        if isinstance(self.tool_schema_estimated_tokens, bool) or not isinstance(self.tool_schema_estimated_tokens, int) or self.tool_schema_estimated_tokens < 0:
            raise ValueError("tool_schema_estimated_tokens must be a non-negative integer")
        definitions = tuple(self.tool_definitions)
        if not all(isinstance(item, ToolDefinition) for item in definitions):
            raise TypeError("tool_definitions must contain ToolDefinition values")
        if not isinstance(self.over_budget, bool):
            raise TypeError("over_budget must be a boolean")
        if self.timeline_checkpoint is not None and not isinstance(self.timeline_checkpoint, ActiveCheckpoint):
            raise TypeError("timeline_checkpoint must be ActiveCheckpoint or None")
        object.__setattr__(self, "selected_blocks", selected)
        object.__setattr__(self, "omitted_blocks", omitted)
        object.__setattr__(self, "omitted_reasons", tuple((str(key), str(value)) for key, value in self.omitted_reasons))
        object.__setattr__(self, "tool_definitions", definitions)

    @property
    def used_tokens(self) -> int:
        return self.token_estimate

    @property
    def estimated_tokens(self) -> int:
        return self.token_estimate

    @property
    def budget(self) -> int | None:
        return self.budget_tokens

    @property
    def timeline_checkpoint_id(self) -> str | None:
        return self.timeline_checkpoint.turn_id if self.timeline_checkpoint is not None else None

    @property
    def selected_block_ids(self) -> tuple[str, ...]:
        return tuple(context_block_id(block) for block in self.selected_blocks)

    @property
    def omitted_block_ids(self) -> tuple[str, ...]:
        return tuple(context_block_id(block) for block in self.omitted_blocks)

    @property
    def instruction_plane(self) -> tuple[ContextBlock, ...]:
        return tuple(block for block in self.selected_blocks if block.plane is ContextPlane.INSTRUCTION)

    @property
    def conversation_plane(self) -> tuple[ContextBlock, ...]:
        return tuple(block for block in self.selected_blocks if block.plane is ContextPlane.CONVERSATION)

    @property
    def contextual_plane(self) -> tuple[ContextBlock, ...]:
        return tuple(block for block in self.selected_blocks if block.plane is ContextPlane.CONTEXTUAL)

    @property
    def usage(self) -> ContextUsage:
        return ContextUsage(
            self.token_estimate,
            self.budget_tokens,
            available=self.budget_tokens is not None,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "budget_tokens": self.budget_tokens,
            "token_estimate": self.token_estimate,
            "selected_blocks": [block.to_dict() for block in self.selected_blocks],
            "selected_block_ids": list(self.selected_block_ids),
            "omitted_block_ids": list(self.omitted_block_ids),
            "omitted_reasons": [
                {"block_id": block_id, "reason": reason}
                for block_id, reason in self.omitted_reasons
            ],
            "timeline_checkpoint": (
                self.timeline_checkpoint.to_dict()
                if self.timeline_checkpoint is not None
                else None
            ),
            "instruction_epoch": self.instruction_epoch,
            "stable_prefix_estimated_tokens": self.stable_prefix_estimated_tokens,
            "stable_prefix_fingerprint": self.stable_prefix_fingerprint,
            "prefix_changed": self.prefix_changed,
            "prefix_change_reason": self.prefix_change_reason,
            "tool_schema_fingerprint": self.tool_schema_fingerprint,
            "tool_schema_estimated_tokens": self.tool_schema_estimated_tokens,
            "tool_definitions": [item.to_dict() for item in self.tool_definitions],
            "over_budget": self.over_budget,
        }


def context_block_id(block: ContextBlock) -> str:
    """Return a stable opaque identifier without exposing block text."""

    if not isinstance(block, ContextBlock):
        raise TypeError("block must be a ContextBlock")
    payload = {
        "source_kind": block.source_kind.value,
        "authority": block.authority.value,
        "stability": block.stability.value,
        "scope": block.scope.value if isinstance(block.scope, ContextScope) else str(block.scope),
        "provenance": block.provenance,
        "semantic_unit_id": block.semantic_unit_id,
        "content": block.content,
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


class ContextCompactor:
    """Create bounded Timeline candidates without Provider or Tool access."""

    def __init__(
        self,
        policy: CompactionPolicy | None = None,
        *,
        token_estimator: Callable[[str], int] | None = None,
    ) -> None:
        self.policy = policy or CompactionPolicy()
        if not isinstance(self.policy, CompactionPolicy):
            raise TypeError("policy must be a CompactionPolicy or None")
        self.token_estimator = _resolve_token_estimator(token_estimator)
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def compact(
        self,
        transcript: Transcript,
        *,
        timeline: Timeline | None = None,
        session_id: str | None = None,
        summarize: SummaryFunction | None = None,
        cancellation: CancellationToken | None = None,
    ) -> CompactionResult:
        """Compact complete units in chronological bounded rolling batches.

        The method returns a failed candidate with the previous Timeline
        untouched when the summary callback or budget contract fails.  The
        caller is responsible for the later durable Timeline append.
        """

        if not isinstance(transcript, Transcript):
            raise TypeError("transcript must be a Transcript")
        if timeline is not None and not isinstance(timeline, Timeline):
            raise TypeError("timeline must be a Timeline or None")
        if timeline is not None and timeline.session_id != transcript.session_id:
            raise CompactionError("transcript and timeline belong to different Sessions")
        owner = transcript.session_id if session_id is None else session_id
        if not isinstance(owner, str) or not owner:
            raise ValueError("session_id must be a non-empty string")
        if owner != transcript.session_id:
            raise CompactionError("Compaction Session does not own the supplied Transcript")
        if cancellation is not None and not isinstance(cancellation, CancellationToken):
            raise TypeError("cancellation must be a CancellationToken or None")

        lock = self._acquire_single_flight(owner)
        try:
            return self._compact_locked(
                transcript,
                timeline=timeline,
                summarize=summarize,
                cancellation=cancellation,
            )
        finally:
            lock.release()

    def plan_epoch(
        self,
        transcript: Transcript,
        *,
        timeline: Timeline | None = None,
        session_id: str | None = None,
        input_budget: int | None = None,
        output_reserve: int | None = None,
    ) -> CompactionEpoch | None:
        """Derive the next bounded complete raw epoch.

        This is intentionally a pure derivation from the current Transcript
        and committed Timeline.  It does not allocate a durable pointer and
        it never includes an earlier Fine summary as model evidence.
        """

        if not isinstance(transcript, Transcript):
            raise TypeError("transcript must be a Transcript")
        if timeline is not None and not isinstance(timeline, Timeline):
            raise TypeError("timeline must be a Timeline or None")
        if timeline is not None and timeline.session_id != transcript.session_id:
            raise CompactionError("transcript and timeline belong to different Sessions")
        owner = transcript.session_id if session_id is None else session_id
        if not isinstance(owner, str) or not owner:
            raise ValueError("session_id must be a non-empty string")
        if owner != transcript.session_id:
            raise CompactionError("Compaction Session does not own the supplied Transcript")

        selected_input_budget = self.policy.input_budget if input_budget is None else input_budget
        selected_output_reserve = (
            self.policy.output_reserve if output_reserve is None else output_reserve
        )
        if (
            isinstance(selected_input_budget, bool)
            or not isinstance(selected_input_budget, int)
            or selected_input_budget <= 0
            or isinstance(selected_output_reserve, bool)
            or not isinstance(selected_output_reserve, int)
            or selected_output_reserve <= 0
            or selected_output_reserve >= selected_input_budget
        ):
            raise ValueError("epoch compaction budgets are invalid")

        covered_end = timeline.sequence_end if timeline is not None else 0
        pending_units: list[SemanticUnit] = []
        for unit in transcript.semantic_units():
            if unit.sequence_end <= covered_end:
                continue
            # A later complete unit must not leap over an open unit: doing so
            # would advance the Timeline checkpoint past uncovered evidence.
            if not unit.complete:
                break
            pending_units.append(unit)
        units = tuple(pending_units)
        if not units:
            return None

        available = selected_input_budget - selected_output_reserve
        selected: list[SemanticUnit] = []
        for unit in units:
            candidate = (*selected, unit)
            candidate_text = _compaction_input_text("", candidate)
            candidate_tokens = self._estimate(candidate_text)
            if not selected and candidate_tokens > available:
                return None
            if candidate_tokens > available:
                break
            selected.append(unit)
        if not selected:
            return None
        input_text = _compaction_input_text("", selected)
        input_tokens = self._estimate(input_text)
        return CompactionEpoch(
            session_id=transcript.session_id,
            units=tuple(selected),
            input_text=input_text,
            input_tokens=input_tokens,
            input_budget=selected_input_budget,
            output_reserve=selected_output_reserve,
            sequence_start=selected[0].sequence_start,
            sequence_end=selected[-1].sequence_end,
        )

    def build_epoch_candidate(
        self,
        transcript: Transcript,
        *,
        epoch: CompactionEpoch,
        result: CompactionStructuredResult,
        timeline: Timeline | None = None,
    ) -> CompactionResult:
        """Validate one structured L4 result and build a checkpoint candidate."""

        if not isinstance(transcript, Transcript):
            raise TypeError("transcript must be a Transcript")
        if not isinstance(epoch, CompactionEpoch):
            raise TypeError("epoch must be a CompactionEpoch")
        if epoch.session_id != transcript.session_id:
            raise CompactionError("Compaction epoch belongs to another Session")
        if timeline is not None and (
            not isinstance(timeline, Timeline) or timeline.session_id != transcript.session_id
        ):
            raise CompactionError("transcript and timeline belong to different Sessions")
        if not isinstance(result, CompactionStructuredResult):
            raise TypeError("result must be a CompactionStructuredResult")
        if tuple(result.coverage) != epoch.turn_ids:
            raise CompactionValidationError("compaction coverage does not match the raw epoch")

        derived: list[SemanticEntry] = []
        batches: list[CompactionBatch] = []
        for entry, unit, expected_ref in zip(result.entries, epoch.units, epoch.refs, strict=True):
            if (
                not isinstance(entry, CompactionEntry)
                or entry.turn_id != unit.turn_id
                or entry.refs != (expected_ref,)
            ):
                raise CompactionValidationError("compaction entry does not match raw evidence")
            derived.append(
                SemanticEntry(
                    turn_id=entry.turn_id,
                    summary=entry.summary,
                    refs=entry.refs,
                    session_id=transcript.session_id,
                )
            )
            batches.append(
                CompactionBatch(
                    unit_ids=(unit.unit_id,),
                    sequence_start=unit.sequence_start,
                    sequence_end=unit.sequence_end,
                    input_text=epoch.input_text,
                    input_tokens=epoch.input_tokens,
                    output_summary=entry.summary,
                )
            )
        checkpoint = ActiveCheckpoint(
            turn_id=derived[-1].turn_id,
            active_turns=tuple(entry.turn_id for entry in derived),
            session_id=transcript.session_id,
        )
        candidate_timeline = (timeline or Timeline(transcript.session_id)).append_transaction(
            tuple(derived), checkpoint
        )
        output_tokens = sum(self._estimate(entry.summary) for entry in result.entries)
        return CompactionResult(
            timeline=candidate_timeline,
            summary=result.summary or result.entries[-1].summary,
            batches=tuple(batches),
            changed=True,
            input_tokens=epoch.input_tokens,
            output_tokens=output_tokens,
        )

    def plan_timeline_aging_epoch(
        self,
        transcript: Transcript,
        *,
        timeline: Timeline | None = None,
        session_id: str | None = None,
        input_budget: int | None = None,
        output_reserve: int | None = None,
    ) -> TimelineAgingEpoch | None:
        """Select the oldest safe committed Fine epoch for L5 aging.

        Selection is fail-closed.  A malformed or oversized oldest Fine
        transaction returns ``None`` instead of skipping ahead to a later
        epoch, and the model receives only the raw Transcript units resolved
        from each Fine reference.
        """

        if not isinstance(transcript, Transcript):
            raise TypeError("transcript must be a Transcript")
        if timeline is None:
            return None
        if not isinstance(timeline, Timeline) or timeline.session_id != transcript.session_id:
            raise CompactionError("transcript and timeline belong to different Sessions")
        owner = transcript.session_id if session_id is None else session_id
        if not isinstance(owner, str) or not owner:
            raise ValueError("session_id must be a non-empty string")
        if owner != transcript.session_id:
            raise CompactionError("Timeline aging Session does not own the supplied Transcript")

        selected_input_budget = self.policy.input_budget if input_budget is None else input_budget
        selected_output_reserve = (
            self.policy.output_reserve if output_reserve is None else output_reserve
        )
        if (
            isinstance(selected_input_budget, bool)
            or not isinstance(selected_input_budget, int)
            or selected_input_budget <= 0
            or isinstance(selected_output_reserve, bool)
            or not isinstance(selected_output_reserve, int)
            or selected_output_reserve <= 0
            or selected_output_reserve >= selected_input_budget
        ):
            raise ValueError("timeline aging budgets are invalid")

        active_fine = timeline.fine_entries
        active_by_turn = {entry.turn_id: entry for entry in active_fine}
        if not active_by_turn or len(active_by_turn) != len(active_fine):
            return None
        units_by_range = {
            (unit.sequence_start, unit.sequence_end): unit
            for unit in transcript.semantic_units(complete_only=True)
        }
        available = selected_input_budget - selected_output_reserve

        for group in timeline.transaction_groups():
            if not group or not isinstance(group[-1], ActiveCheckpoint):
                continue
            derived = tuple(record for record in group[:-1] if isinstance(record, (SemanticEntry, EpochMacroSummary)))
            if not derived:
                continue
            # Macro transactions are already aged.  A mixed or partially
            # superseded transaction is not safe evidence for a new Macro.
            if any(isinstance(record, EpochMacroSummary) for record in derived):
                continue
            fine_records = tuple(record for record in derived if isinstance(record, SemanticEntry))
            if len(fine_records) != len(derived):
                return None
            if len({record.turn_id for record in fine_records}) != len(fine_records):
                return None
            active_flags = tuple(
                record.turn_id in active_by_turn and active_by_turn[record.turn_id] == record
                for record in fine_records
            )
            if not any(active_flags):
                # This physical Fine transaction has already been fully
                # superseded by a committed Macro; retain it for audit but do
                # not select it again.
                continue
            if not all(active_flags):
                return None

            units: list[SemanticUnit] = []
            for fine in fine_records:
                if len(fine.refs) != 1:
                    return None
                ref = fine.refs[0]
                if ref.session_id != transcript.session_id or fine.session_id not in (None, owner):
                    return None
                unit = units_by_range.get((ref.sequence_start, ref.sequence_end))
                if unit is None or unit.turn_id != fine.turn_id:
                    return None
                try:
                    transcript.select(ref.sequence_start, ref.sequence_end, complete_only=True)
                except (TypeError, ValueError):
                    return None
                units.append(unit)
            if not units:
                continue
            if tuple(unit.sequence_start for unit in units) != tuple(sorted(unit.sequence_start for unit in units)):
                return None
            if any(
                current.sequence_start != previous.sequence_end + 1
                for previous, current in zip(units, units[1:], strict=False)
            ):
                return None
            raw_units = tuple(units)
            input_text = _timeline_aging_input_text(raw_units)
            input_tokens = self._estimate(input_text)
            if input_tokens > available:
                return None
            try:
                return TimelineAgingEpoch(
                    session_id=owner,
                    fine_entries=fine_records,
                    units=raw_units,
                    input_text=input_text,
                    input_tokens=input_tokens,
                    input_budget=selected_input_budget,
                    output_reserve=selected_output_reserve,
                    sequence_start=raw_units[0].sequence_start,
                    sequence_end=raw_units[-1].sequence_end,
                )
            except (TypeError, ValueError):
                return None
        return None

    def parse_timeline_aging_result(
        self,
        value: object,
        *,
        epoch: TimelineAgingEpoch,
        summary_hard_cap: int | None = None,
    ) -> TimelineAgingResult:
        """Validate one Macro-only L5 result using this Compactor's estimator."""

        if not isinstance(epoch, TimelineAgingEpoch):
            raise TypeError("epoch must be a TimelineAgingEpoch")
        return parse_timeline_aging_result(
            value,
            epoch,
            summary_hard_cap=(
                self.policy.summary_hard_cap
                if summary_hard_cap is None
                else summary_hard_cap
            ),
            token_estimator=self._estimate,
        )

    def build_timeline_aging_candidate(
        self,
        transcript: Transcript,
        *,
        epoch: TimelineAgingEpoch,
        result: TimelineAgingResult,
        timeline: Timeline,
    ) -> CompactionResult:
        """Build one append-only Macro transaction with a last checkpoint."""

        if not isinstance(transcript, Transcript):
            raise TypeError("transcript must be a Transcript")
        if not isinstance(epoch, TimelineAgingEpoch):
            raise TypeError("epoch must be a TimelineAgingEpoch")
        if not isinstance(result, TimelineAgingResult):
            raise TypeError("result must be a TimelineAgingResult")
        if not isinstance(timeline, Timeline) or timeline.session_id != transcript.session_id:
            raise CompactionError("transcript and timeline belong to different Sessions")
        if epoch.session_id != transcript.session_id or result.coverage != epoch.turn_ids:
            raise CompactionValidationError("Timeline aging result does not match raw evidence")
        active_fine = timeline.fine_entries
        if any(entry not in active_fine for entry in epoch.fine_entries):
            raise CompactionValidationError("Timeline aging Fine evidence is no longer active")
        for fine, unit, ref in zip(epoch.fine_entries, epoch.units, epoch.refs, strict=True):
            if fine.turn_id != unit.turn_id or fine.refs != (ref,):
                raise CompactionValidationError("Timeline aging Fine evidence is not exact")
            try:
                transcript.select(ref.sequence_start, ref.sequence_end, complete_only=True)
            except (TypeError, ValueError) as exc:
                raise CompactionValidationError("Timeline aging raw evidence is invalid") from exc

        macro = EpochMacroSummary(
            turn_id=epoch.turn_ids[-1],
            summary=result.summary,
            refs=epoch.refs,
            coverage=result.coverage,
            session_id=transcript.session_id,
        )
        checkpoint = ActiveCheckpoint(
            turn_id=epoch.turn_ids[-1],
            active_turns=epoch.turn_ids,
            session_id=transcript.session_id,
        )
        candidate_timeline = timeline.append_transaction((macro,), checkpoint)
        batch = CompactionBatch(
            unit_ids=epoch.unit_ids,
            sequence_start=epoch.sequence_start,
            sequence_end=epoch.sequence_end,
            input_text=epoch.input_text,
            input_tokens=epoch.input_tokens,
            output_summary=result.summary,
        )
        return CompactionResult(
            timeline=candidate_timeline,
            summary=result.summary,
            batches=(batch,),
            changed=True,
            input_tokens=epoch.input_tokens,
            output_tokens=self._estimate(result.summary),
        )

    def parse_epoch_result(
        self,
        value: object,
        *,
        epoch: CompactionEpoch,
        summary_hard_cap: int | None = None,
    ) -> CompactionStructuredResult:
        """Validate a provider response using this Compactor's estimator."""

        if not isinstance(epoch, CompactionEpoch):
            raise TypeError("epoch must be a CompactionEpoch")
        return parse_compaction_result(
            value,
            epoch,
            summary_hard_cap=(
                self.policy.summary_hard_cap
                if summary_hard_cap is None
                else summary_hard_cap
            ),
            token_estimator=self._estimate,
        )

    def _acquire_single_flight(self, session_id: str) -> threading.Lock:
        with self._locks_guard:
            lock = self._locks.setdefault(session_id, threading.Lock())
        if not lock.acquire(blocking=False):
            raise CompactionInProgress(f"Compaction already running for Session {session_id}")
        return lock

    def _compact_locked(
        self,
        transcript: Transcript,
        *,
        timeline: Timeline | None,
        summarize: SummaryFunction | None,
        cancellation: CancellationToken | None,
    ) -> CompactionResult:
        if cancellation is not None and cancellation.cancelled:
            return self._failed_result(
                timeline,
                timeline.summary if timeline is not None else "",
                "compaction_cancelled",
                (),
                0,
            )
        previous_summary = timeline.summary if timeline is not None else ""
        units = list(transcript.semantic_units(complete_only=True))
        if timeline is not None:
            units = [unit for unit in units if unit.sequence_end > timeline.sequence_end]
        if not units:
            return CompactionResult(
                timeline=timeline,
                summary=previous_summary or None,
                changed=False,
            )

        if summarize is None:
            return self._failed_result(
                timeline,
                previous_summary,
                "summary_function_required",
                (),
                0,
            )
        summary_fn = summarize
        if not callable(summary_fn):
            raise TypeError("summarize must be callable or None")
        batches: list[CompactionBatch] = []
        rolling_summary = previous_summary
        pending = []
        input_tokens = 0

        def flush_pending() -> str | None:
            nonlocal pending, rolling_summary, input_tokens
            if not pending:
                return None
            if cancellation is not None and cancellation.cancelled:
                return "compaction_cancelled"
            input_text = _compaction_input_text(rolling_summary, pending)
            estimated = self._estimate(input_text)
            if estimated > self.policy.available_input_budget:
                return "compaction_input_overflow"
            try:
                generated = summary_fn(input_text)
            except Exception:
                return "summary_generation_failed"
            if cancellation is not None and cancellation.cancelled:
                return "compaction_cancelled"
            if not isinstance(generated, str):
                return "summary_generation_returned_non_text"
            if not generated.strip():
                return "summary_empty"
            if self._estimate(generated) > self.policy.summary_hard_cap:
                return "summary_hard_cap_exceeded"
            batches.append(
                CompactionBatch(
                    unit_ids=tuple(unit.unit_id for unit in pending),
                    sequence_start=pending[0].sequence_start,
                    sequence_end=pending[-1].sequence_end,
                    input_text=input_text,
                    input_tokens=estimated,
                    output_summary=generated,
                )
            )
            input_tokens += estimated
            rolling_summary = generated
            pending = []
            return None

        for unit in units:
            if cancellation is not None and cancellation.cancelled:
                return self._failed_result(
                    timeline,
                    previous_summary,
                    "compaction_cancelled",
                    batches,
                    input_tokens,
                )
            candidate = (*pending, unit)
            candidate_text = _compaction_input_text(rolling_summary, candidate)
            candidate_tokens = self._estimate(candidate_text)
            if candidate_tokens <= self.policy.available_input_budget:
                pending.append(unit)
                continue
            failure = flush_pending()
            if failure is not None:
                return self._failed_result(timeline, previous_summary, failure, batches, input_tokens)
            single_text = _compaction_input_text(rolling_summary, (unit,))
            if self._estimate(single_text) > self.policy.available_input_budget:
                return self._failed_result(
                    timeline,
                    previous_summary,
                    "single_semantic_unit_exceeds_compaction_budget",
                    batches,
                    input_tokens,
                )
            pending.append(unit)
        failure = flush_pending()
        if failure is not None:
            return self._failed_result(timeline, previous_summary, failure, batches, input_tokens)
        if not batches:
            return CompactionResult(timeline, previous_summary or None)

        try:
            derived: list[SemanticEntry] = []
            for batch in batches:
                covered = tuple(unit for unit in units if unit.unit_id in batch.unit_ids)
                if not covered:
                    return self._failed_result(
                        timeline,
                        previous_summary,
                        "compaction_coverage_invalid",
                        batches,
                        input_tokens,
                    )
                for unit in covered:
                    derived.append(
                        SemanticEntry(
                            turn_id=unit.turn_id,
                            summary=batch.output_summary,
                            refs=(transcript.reference(unit.sequence_start, unit.sequence_end),),
                            session_id=transcript.session_id,
                        )
                    )
            checkpoint = ActiveCheckpoint(
                turn_id=derived[-1].turn_id,
                active_turns=tuple(record.turn_id for record in derived),
                session_id=transcript.session_id,
            )
            candidate_timeline = (timeline or Timeline(transcript.session_id)).append_transaction(
                derived, checkpoint
            )
        except (TypeError, ValueError):
            return self._failed_result(
                timeline,
                previous_summary,
                "timeline_boundary_invalid",
                batches,
                input_tokens,
            )
        output_tokens = self._estimate(rolling_summary)
        return CompactionResult(
            timeline=candidate_timeline,
            summary=rolling_summary,
            batches=tuple(batches),
            changed=True,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    def _failed_result(
        self,
        timeline: Timeline | None,
        previous_summary: str,
        failure: str,
        batches: Sequence[CompactionBatch],
        input_tokens: int,
    ) -> CompactionResult:
        return CompactionResult(
            timeline=timeline,
            summary=previous_summary or None,
            batches=tuple(batches),
            changed=False,
            failure=failure,
            input_tokens=input_tokens,
            output_tokens=self._estimate(previous_summary) if previous_summary else 0,
        )

    def _estimate(self, text: str) -> int:
        return _estimate_tokens(self.token_estimator, text)


def _timeline_aging_input_text(units: Sequence[SemanticUnit]) -> str:
    """Serialize only raw complete Transcript units for an L5 request."""

    encoded_units = "\n".join(
        json.dumps(unit.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        for unit in units
    )
    return f"Complete raw semantic units:\n{encoded_units}"


def fine_timeline_usage(
    timeline: Timeline,
    token_estimator: Callable[[str], int] | None = None,
) -> int:
    """Estimate the current logical Fine Timeline payload in tokens."""

    if not isinstance(timeline, Timeline):
        raise TypeError("timeline must be a Timeline")
    estimator = _resolve_token_estimator(token_estimator)
    text = "\n".join(
        json.dumps(entry.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        for entry in timeline.fine_entries
    )
    return _estimate_tokens(estimator, text)


def _compaction_input_text(summary: str, units: Sequence[SemanticUnit]) -> str:
    previous = summary or "(no prior summary)"
    encoded_units = "\n".join(
        json.dumps(unit.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        for unit in units
    )
    return f"Summary so far:\n{previous}\nComplete semantic units:\n{encoded_units}"


def messages_from_context_snapshot(snapshot: ContextSnapshot) -> tuple[Message, ...]:
    """Project selected Conversation/Context blocks into Provider messages.

    This is a structural conversion only.  It ignores Instruction blocks and
    never promotes ordinary history into the Instruction Plane.
    """

    if not isinstance(snapshot, ContextSnapshot):
        raise TypeError("snapshot must be a ContextSnapshot")
    result: list[Message] = []
    contextual_texts: list[str] = []
    last_history_identity: tuple[str, ...] | None = None
    last_history_was_full_message = False

    def append(message: Message) -> None:
        result.append(message)

    def append_transcript_entry(entry: TranscriptEntry) -> None:
        nonlocal last_history_identity, last_history_was_full_message
        identity, message, is_full_message = _transcript_entry_message(entry)
        if identity == last_history_identity:
            if last_history_was_full_message or is_full_message:
                # _history_for_messages may persist the complete Message on
                # every part entry.  This is an identity-local reconstruction
                # rule, not content-based de-duplication.
                last_history_was_full_message = True
                return
            previous = result[-1]
            if previous.role == message.role:
                result[-1] = Message(
                    previous.role,
                    previous.parts + message.parts,
                    previous.native_items,
                )
                return
        append(message)
        last_history_identity = identity
        last_history_was_full_message = is_full_message

    def break_history_identity() -> None:
        nonlocal last_history_identity, last_history_was_full_message
        last_history_identity = None
        last_history_was_full_message = False

    for block in snapshot.selected_blocks:
        if block.plane is ContextPlane.INSTRUCTION:
            continue
        if block.source_kind in {
            ContextSourceKind.TIMELINE_ENTRY,
            ContextSourceKind.TIMELINE_MACRO,
        }:
            break_history_identity()
            try:
                record = timeline_record_from_dict(json.loads(block.content))
            except (TypeError, ValueError, json.JSONDecodeError):
                raise ContextCompilationError("selected Timeline block is malformed") from None
            if isinstance(record, ActiveCheckpoint):
                continue
            label = "Timeline macro" if isinstance(record, EpochMacroSummary) else "Timeline entry"
            append(Message("user", (TextPart(f"[{label}]\n{record.summary}"),)))
            continue
        if block.provenance.startswith("transcript:unit:"):
            try:
                unit = SemanticUnit.from_dict(json.loads(block.content))
            except (TypeError, ValueError, json.JSONDecodeError):
                raise ContextCompilationError("selected semantic unit block is malformed") from None
            for entry in unit.entries:
                append_transcript_entry(entry)
            continue
        if block.provenance.startswith("message:") or block.provenance == "current:user":
            break_history_identity()
            try:
                value = json.loads(block.content)
            except json.JSONDecodeError:
                value = None
            if isinstance(value, Mapping) and "role" in value and "parts" in value:
                try:
                    append(Message.from_dict(value))
                except (TypeError, ValueError, KeyError):
                    raise ContextCompilationError("selected message block is malformed") from None
            else:
                append(Message("user", (TextPart(block.content),)))
            continue
        if block.plane is ContextPlane.CONTEXTUAL:
            break_history_identity()
            contextual_texts.append(block.content)
            continue
        break_history_identity()
        append(Message("user", (TextPart(block.content),)))
    if contextual_texts:
        user_index = next(
            (index for index in range(len(result) - 1, -1, -1) if result[index].role == "user"),
            None,
        )
        if user_index is not None:
            current = result[user_index]
            context_parts = tuple(TextPart(f"[Context]\n{value}") for value in contextual_texts)
            result[user_index] = Message("user", context_parts + current.parts, current.native_items)
        else:
            result.append(
                Message(
                    "user",
                    tuple(TextPart(f"[Context]\n{value}") for value in contextual_texts),
                )
            )
    return tuple(result)


def _transcript_entry_message(
    entry: TranscriptEntry,
) -> tuple[tuple[str, ...], Message, bool]:
    if not hasattr(entry, "payload") or not hasattr(entry, "kind"):
        raise ContextCompilationError("Transcript entry is malformed")
    payload = entry.payload
    if isinstance(payload, Mapping):
        def identity_for(message: Message) -> tuple[str, ...]:
            # The turn is a recovery scope, not a Message identity.  A single
            # Turn may contain multiple adjacent user Messages (for example
            # Steering) and multiple independent structured Messages with
            # the same role.  Application/Core history writers persist the
            # deterministic ``message_id`` created from each message's first
            # sequence; use it when present and never fall back to text.
            message_id = payload.get("message_id")
            if isinstance(message_id, str) and message_id.strip():
                return (entry.session_id, entry.turn_id, message.role, message_id)
            # Core also accepts standalone atomic History entries that do not
            # claim to represent a reconstructable full Message.  Keep those
            # entry-local; only the full-message persistence envelope below
            # requires an explicit Message identity.
            return (entry.session_id, entry.turn_id, message.role, f"entry:{entry.sequence}")

        message_value = payload.get("message")
        if isinstance(message_value, Mapping):
            message_id = payload.get("message_id")
            if not isinstance(message_id, str) or not message_id.strip():
                raise ContextCompilationError("history message identity is missing")
            try:
                message = Message.from_dict(message_value)
                return identity_for(message), message, True
            except (TypeError, ValueError, KeyError):
                raise ContextCompilationError("history message payload is malformed") from None
        part_value = payload.get("part")
        if isinstance(part_value, Mapping):
            role = payload.get("role", "user")
            try:
                message = Message.from_dict({"role": role, "parts": [part_value]})
                return identity_for(message), message, False
            except (TypeError, ValueError, KeyError):
                raise ContextCompilationError("history part payload is malformed") from None
        if payload.get("type") == "tool_call":
            try:
                message = Message.from_dict({"role": "assistant", "parts": [dict(payload)]})
                return identity_for(message), message, False
            except (TypeError, ValueError, KeyError):
                raise ContextCompilationError("history ToolCall payload is malformed") from None
        if payload.get("type") == "tool_result":
            try:
                message = Message.from_dict({"role": "tool", "parts": [dict(payload)]})
                return identity_for(message), message, False
            except (TypeError, ValueError, KeyError):
                raise ContextCompilationError("history ToolResult payload is malformed") from None
    raise ContextCompilationError("history entry does not carry a Message payload")


def instruction_text_from_context_snapshot(snapshot: ContextSnapshot) -> str:
    if not isinstance(snapshot, ContextSnapshot):
        raise TypeError("snapshot must be a ContextSnapshot")
    text = "\n\n".join(block.content for block in snapshot.instruction_plane if block.content.strip())
    if not text.strip():
        raise ContextCompilationError("Instruction Plane cannot be empty")
    return text


class ContextCompiler:
    """Compile a deterministic Working Set under an optional input budget.

    ``None`` means that this provider-independent compiler has no operating
    limit yet and therefore does not omit sources on its own.  The formal
    Application request path resolves a ``ContextBudget`` before it sends a
    Provider request; the compiler never invents a model window.
    """

    def __init__(
        self,
        *,
        budget_tokens: int | None = None,
        token_estimator: Callable[[str], int] | None = None,
    ) -> None:
        if budget_tokens is not None and (
            isinstance(budget_tokens, bool)
            or not isinstance(budget_tokens, int)
            or budget_tokens <= 0
        ):
            raise ValueError("budget_tokens must be a positive integer or None")
        self.budget_tokens = budget_tokens
        self.token_estimator = _resolve_token_estimator(token_estimator)

    def compile(
        self,
        sources: ContextSourceBundle,
        *,
        previous_snapshot: ContextSnapshot | None = None,
    ) -> ContextSnapshot:
        if not isinstance(sources, ContextSourceBundle):
            raise TypeError("sources must be ContextSourceBundle")
        if previous_snapshot is not None and not isinstance(previous_snapshot, ContextSnapshot):
            raise TypeError("previous_snapshot must be ContextSnapshot or None")

        instruction_blocks, instruction_epoch, requested_reason = self._instruction_plane(sources)
        prefix = build_instruction_prefix(
            instruction_blocks,
            instruction_epoch=instruction_epoch,
            reason=requested_reason,
            changed=False,
        )
        instruction_epoch = prefix.instruction_epoch
        stable_fingerprint = prefix.fingerprint
        stable_prefix_estimated_tokens = sum(self._estimate_block(block) for block in prefix.blocks)
        prefix_changed, prefix_reason = self._prefix_diagnostics(
            previous_snapshot,
            instruction_epoch=instruction_epoch,
            stable_fingerprint=stable_fingerprint,
            requested_reason=requested_reason,
        )

        tool_source_value = sources.tool_source
        tool_tokens = 0
        tool_fingerprint: str | None = None
        tool_definitions: tuple[ToolDefinition, ...] = ()
        if tool_source_value is not None:
            tool_tokens = self._estimate_tool_source(tool_source_value)
            tool_fingerprint = tool_source_value.tool_schema_fingerprint
            tool_definitions = tool_source_value.definitions

        selected: list[ContextBlock] = []
        omitted: list[ContextBlock] = []
        omission_reasons: list[tuple[str, str]] = []
        selected_ids: set[str] = set()
        composition_order: dict[str, tuple[int, int]] = {}
        total = tool_tokens

        def add_selected(
            block: ContextBlock,
            *,
            required: bool,
            composition_key: tuple[int, int],
        ) -> bool:
            nonlocal total
            identifier = context_block_id(block)
            if identifier in selected_ids:
                return True
            estimate = self._estimate_block(block)
            if required or self.budget_tokens is None or total + estimate <= self.budget_tokens:
                selected.append(block)
                selected_ids.add(identifier)
                composition_order[identifier] = composition_key
                total += estimate
                return True
            omitted.append(block)
            omission_reasons.append((identifier, "budget_exceeded"))
            return False

        # Selection priority and final composition order are deliberately
        # separate.  Protected sources are selected first, while the final
        # snapshot keeps Timeline/Transcript before runtime facts and the
        # current user turn at the conversation tail.
        for index, block in enumerate(prefix.blocks):
            add_selected(block, required=True, composition_key=(0, index))
        for index, raw in enumerate(sources.protocol_blocks):
            add_selected(
                _conversation_block(raw),
                required=True,
                composition_key=(1, index),
            )
        for index, raw in enumerate(sources.protected_context):
            add_selected(
                _conversation_block(raw),
                required=True,
                composition_key=(4, index),
            )
        for index, raw in enumerate(sources.current_turn):
            add_selected(
                _conversation_block(raw),
                required=True,
                composition_key=(7, index),
            )

        if sources.transcript is not None:
            for unit in sources.transcript.semantic_units(complete_only=False):
                if not unit.complete:
                    add_selected(
                        _semantic_unit_block(unit),
                        required=True,
                        composition_key=(3, unit.sequence_start),
                    )

        if sources.timeline is not None:
            for index, record in enumerate(sources.timeline.logical_records):
                if isinstance(record, ActiveCheckpoint):
                    continue
                add_selected(
                    _timeline_block(record),
                    required=True,
                    composition_key=(2, index),
                )

        complete_units = () if sources.transcript is None else sources.transcript.semantic_units(complete_only=True)
        covered_ranges = () if sources.timeline is None else tuple(
            (ref.sequence_start, ref.sequence_end)
            for record in sources.timeline.logical_records
            if isinstance(record, (SemanticEntry, EpochMacroSummary))
            for ref in record.refs
        )
        complete_units = tuple(
            unit for unit in complete_units
            if not any(start <= unit.sequence_start and unit.sequence_end <= end for start, end in covered_ranges)
        )
        remaining_units = list(reversed(complete_units))
        for position, unit in enumerate(remaining_units):
            if add_selected(
                _semantic_unit_block(unit),
                required=False,
                composition_key=(3, unit.sequence_start),
            ):
                continue
            # Once the newest complete unit cannot fit, older units are not
            # allowed to leapfrog it.  This is a recency boundary, not a task
            # ranking algorithm.
            for older in remaining_units[position + 1 :]:
                block = _semantic_unit_block(older)
                identifier = context_block_id(block)
                if identifier not in selected_ids:
                    omitted.append(block)
                    omission_reasons.append((identifier, "older_than_budget_boundary"))
            break

        for index, raw in enumerate((*sources.current_turn_deltas, *sources.runtime_sources)):
            add_selected(
                _conversation_block(raw),
                required=False,
                composition_key=(5, index),
            )
        for index, raw in enumerate(sources.environment_sources):
            add_selected(
                _conversation_block(raw),
                required=False,
                composition_key=(6, index),
            )

        selected.sort(key=lambda block: composition_order[context_block_id(block)])

        return ContextSnapshot(
            budget_tokens=self.budget_tokens,
            token_estimate=total,
            selected_blocks=tuple(selected),
            omitted_blocks=tuple(omitted),
            omitted_reasons=tuple(omission_reasons),
            timeline_checkpoint=(sources.timeline.active_checkpoint if sources.timeline is not None else None),
            instruction_epoch=instruction_epoch,
            stable_prefix_estimated_tokens=stable_prefix_estimated_tokens,
            stable_prefix_fingerprint=stable_fingerprint,
            prefix_changed=prefix_changed,
            prefix_change_reason=prefix_reason,
            tool_schema_fingerprint=tool_fingerprint,
            tool_schema_estimated_tokens=tool_tokens,
            tool_definitions=tool_definitions,
            over_budget=(
                self.budget_tokens is not None and total > self.budget_tokens
            ),
        )

    def _instruction_plane(
        self,
        sources: ContextSourceBundle,
    ) -> tuple[tuple[ContextBlock, ...], int, str]:
        values = list(sources.instruction_sources)
        project = sources.project_instruction_source
        if project is not None:
            values.extend(project.blocks)
        if not any(block.source_kind is ContextSourceKind.PUBLIC_PROMPT for block in values):
            values.insert(0, public_prompt_source())
        if not any(block.source_kind is ContextSourceKind.CORE_CONTRACT for block in values):
            values.insert(1 if values else 0, core_runtime_contract_source())
        if any(not block.is_instruction for block in values):
            raise ContextCompilationError("ordinary history/runtime blocks cannot enter Instruction Plane")
        epoch = project.instruction_epoch if project is not None else 0
        reason = project.change_reason if project is not None else "initial"
        return tuple(values), epoch, reason

    def _prefix_diagnostics(
        self,
        previous: ContextSnapshot | None,
        *,
        instruction_epoch: int,
        stable_fingerprint: str,
        requested_reason: str,
    ) -> tuple[bool, str]:
        if previous is None:
            return False, requested_reason or "initial"
        changed = (
            instruction_epoch != previous.instruction_epoch
            or stable_fingerprint != previous.stable_prefix_fingerprint
        )
        if not changed:
            return False, "stable"
        if requested_reason in {
            "instruction_scope_added",
            "instruction_content_changed",
            "instruction_source_added",
            "instruction_source_removed",
        }:
            return True, requested_reason
        return True, "instruction_content_changed"

    def _estimate_block(self, block: ContextBlock) -> int:
        if block.estimated_tokens:
            return block.estimated_tokens
        return self._estimate_text(block.content)

    def _estimate_tool_source(self, source: ToolDefinitionSource) -> int:
        if source.estimated_tokens:
            return source.estimated_tokens
        payload = json.dumps(
            [item.to_dict() for item in source.definitions],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return self._estimate_text(payload)

    def _estimate_text(self, text: str) -> int:
        return _estimate_tokens(self.token_estimator, text)


def _semantic_unit_block(unit: SemanticUnit) -> ContextBlock:
    return ContextBlock(
        source_kind=_unit_source_kind(unit),
        authority=ContextAuthority.HISTORY,
        stability=ContextStability.DYNAMIC,
        scope=ContextScope.TURN,
        provenance=f"transcript:unit:{unit.unit_id}",
        content=json.dumps(unit.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        semantic_unit_id=unit.unit_id,
    )


def _unit_source_kind(unit: SemanticUnit) -> ContextSourceKind:
    if any(entry.is_tool_result for entry in unit.entries):
        return ContextSourceKind.TOOL_RESULT
    if any(entry.is_tool_call for entry in unit.entries):
        return ContextSourceKind.TOOL_CALL
    first = unit.entries[0]
    if first.kind is TranscriptKind.ASSISTANT_MESSAGE:
        return ContextSourceKind.ASSISTANT_MESSAGE
    return ContextSourceKind.USER_MESSAGE


def _timeline_block(record: SemanticEntry | EpochMacroSummary) -> ContextBlock:
    source_kind = (
        ContextSourceKind.TIMELINE_MACRO
        if isinstance(record, EpochMacroSummary)
        else ContextSourceKind.TIMELINE_ENTRY
    )
    block = ContextBlock(
        source_kind=source_kind,
        authority=ContextAuthority.TIMELINE,
        stability=ContextStability.DYNAMIC,
        scope=ContextScope.SESSION,
        provenance=f"timeline:{record.record_type}:{record.turn_id}",
        content=json.dumps(record.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")),
    )
    return block


def _conversation_block(raw: object) -> ContextBlock:
    if isinstance(raw, ContextBlock):
        if raw.plane is ContextPlane.INSTRUCTION:
            raise ContextCompilationError("conversation/context source cannot be an Instruction block")
        return raw
    if isinstance(raw, Message):
        source_kind = ContextSourceKind.USER_MESSAGE
        if raw.role == "assistant":
            source_kind = ContextSourceKind.ASSISTANT_MESSAGE
        elif raw.role == "tool":
            source_kind = (
                ContextSourceKind.TOOL_CALL
                if any(isinstance(part, ToolCallPart) for part in raw.parts)
                else ContextSourceKind.TOOL_RESULT
            )
        return ContextBlock(
            source_kind=source_kind,
            authority=ContextAuthority.HISTORY,
            stability=ContextStability.DYNAMIC,
            scope=ContextScope.TURN,
            provenance=f"message:{raw.role}",
            content=json.dumps(raw.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        )
    if isinstance(raw, str):
        return ContextBlock(
            source_kind=ContextSourceKind.USER_MESSAGE,
            authority=ContextAuthority.HISTORY,
            stability=ContextStability.DYNAMIC,
            scope=ContextScope.TURN,
            provenance="current:user",
            content=raw,
        )
    raise TypeError(f"unsupported conversation/context source: {type(raw).__name__}")


__all__ = [
    "CompactionBatch",
    "CompactionEntry",
    "CompactionEpoch",
    "CompactionError",
    "CompactionInProgress",
    "CompactionPolicy",
    "CompactionResult",
    "CompactionStructuredResult",
    "CompactionValidationError",
    "TimelineAgingEpoch",
    "TimelineAgingResult",
    "ContextBlock",
    "ContextBudget",
    "ContextBudgetError",
    "ContextCompilationError",
    "ContextCompactor",
    "ContextCompiler",
    "ContextRequestSafetyError",
    "ContextSnapshot",
    "ContextSourceBundle",
    "ContextUsage",
    "DeterministicTokenEstimator",
    "GateDecision",
    "RequestAccounting",
    "account_generation_request",
    "context_block_id",
    "evaluate_gates",
    "instruction_text_from_context_snapshot",
    "messages_from_context_snapshot",
    "preflight_gate",
    "preflight_safety_count",
    "pressure_estimate",
    "resolve_context_budget",
    "safety_allowance_for",
    "adaptive_working_headroom",
    "fine_timeline_usage",
]
