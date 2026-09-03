"""Pure Provider request-preparation helpers owned by the Application layer.

The helpers in this module deliberately operate on caller supplied request
builders and immutable Core values.  They do not hold Application, Session or
Timeline state; the generation facade remains responsible for composing those
inputs and for publishing any resulting status.
"""

from __future__ import annotations

from asyncio import CancelledError
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
import inspect

from uthcode.core.context import (
    ContextBudget,
    ContextBudgetError,
    ContextCountEstimate,
    ContextRequestSafetyError,
    RequestAccounting,
    account_generation_request,
    evaluate_gates,
    preflight_safety_count,
    pressure_estimate,
)
from uthcode.core.provider import (
    CancellationToken,
    ContextOverflowError,
    GenerationCancelled,
    GenerationRequest,
    InvalidProviderResponseError,
    ModelLimits,
    ProviderConfigurationError,
    ProviderError,
    ProviderPort,
    DEFAULT_OUTPUT_RESERVE,
)


def effective_output_reserve(
    request_max_output_tokens: int | None,
    model_max_output_tokens: int | None,
) -> int:
    """Resolve the one output reserve used by budget, request and adapters."""

    if request_max_output_tokens is not None:
        return request_max_output_tokens
    if model_max_output_tokens is not None:
        return model_max_output_tokens
    return DEFAULT_OUTPUT_RESERVE


def validate_model_limits(value: object) -> ModelLimits | None:
    if value is not None and not isinstance(value, ModelLimits):
        raise TypeError("Provider model limits must be ModelLimits or None")
    return value


async def resolve_model_limits_async(
    provider: ProviderPort,
    model: str,
) -> ModelLimits | None:
    resolver = getattr(provider, "resolve_model_limits", None)
    if not callable(resolver):
        return None
    value = resolver(model)
    if inspect.isawaitable(value):
        value = await value
    return validate_model_limits(value)


def validate_provider_count(value: object) -> ContextCountEstimate | int | None:
    if value is not None and not isinstance(value, (ContextCountEstimate, int)):
        raise TypeError(
            "Provider input count must be ContextCountEstimate, int, or None"
        )
    if isinstance(value, bool):
        raise TypeError("Provider input count must not be boolean")
    return value


def request_reduction_levels(request: GenerationRequest) -> tuple[str, ...]:
    raw = request.metadata.get("context_reduction_levels", ())
    if isinstance(raw, (str, bytes, bytearray)) or not isinstance(raw, Sequence):
        return ()
    return tuple(value for value in raw if isinstance(value, str) and value)


@dataclass(frozen=True, slots=True)
class CountResolution:
    """A Provider count and its controlled fallback reason, if any."""

    value: ContextCountEstimate | int | None
    fallback_reason: str | None = None


def is_controlled_count_failure(error: Exception) -> bool:
    """Return whether a count endpoint outage may use local accounting."""

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


async def count_input_tokens_async(
    provider: ProviderPort,
    request: GenerationRequest,
) -> CountResolution:
    """Use the Provider count capability or return a controlled local fallback."""

    counter = getattr(provider, "count_input_tokens", None)
    if not callable(counter):
        return CountResolution(None, "capability_missing")
    try:
        value = counter(request)
        while inspect.isawaitable(value):
            value = await value
    except (GenerationCancelled, CancelledError):
        raise
    except Exception as exc:
        if is_controlled_count_failure(exc):
            return CountResolution(None, "provider_count_failure")
        raise
    validated = validate_provider_count(value)
    if validated is None:
        return CountResolution(None, "provider_count_unavailable")
    return CountResolution(validated)


async def prepare_counted_request_async(
    provider: ProviderPort,
    compose: Callable[
        [ContextCountEstimate | int | None, bool, str | None],
        GenerationRequest,
    ],
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
    """Prepare one final ordinary request with a stable count/gate boundary."""

    counted_request = compose(None, True, None)
    resolution = await count_input_tokens_async(provider, counted_request)
    if resolution.fallback_reason is not None:
        return compose(None, False, resolution.fallback_reason)

    provider_count = resolution.value
    rebuild_from_sources = True
    for _ in range(8):
        if rebuild_from_sources:
            candidate = compose(provider_count, True, None)
            if candidate != counted_request:
                counted_request = candidate
                resolution = await count_input_tokens_async(provider, counted_request)
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
                rebuild_from_sources = True
                continue

        final_request = finalize(counted_request, provider_count, False, None)
        if final_request == counted_request:
            return counted_request
        counted_request = final_request
        resolution = await count_input_tokens_async(provider, counted_request)
        if resolution.fallback_reason is not None:
            return compose(None, False, resolution.fallback_reason)
        provider_count = resolution.value

    raise ContextRequestSafetyError(
        "Provider input count did not stabilize for the final request"
    )


async def prepare_prospective_request_async(
    provider: ProviderPort,
    compose: Callable[
        [ContextCountEstimate | int | None, bool, str | None],
        GenerationRequest,
    ],
    finalize: Callable[
        [GenerationRequest, ContextCountEstimate | int | None, bool, str | None],
        GenerationRequest,
    ],
) -> tuple[GenerationRequest, str]:
    """Build one prospective ordinary request and report ``exact`` or ``local``.

    ``compose`` is expected to be a side-effect-free builder for this helper.
    The returned source is intentionally only the two values needed by the
    Application candidate validator so before/after comparisons cannot mix
    Provider and local measurements.
    """

    def prospective_finalize(
        request: GenerationRequest,
        provider_count: ContextCountEstimate | int | None,
        _defer_hard_gate: bool,
        count_fallback: str | None,
    ) -> GenerationRequest:
        # A prospective baseline is allowed to remain Hard-unsafe: its count
        # is evidence for the before/after decision, never a request sent to a
        # Provider.  The actual candidate commit path still uses the ordinary
        # final Hard Gate.
        return finalize(request, provider_count, True, count_fallback)

    request = await prepare_counted_request_async(
        provider,
        compose,
        prospective_finalize,
    )
    gate = request.metadata.get("context_gate")
    source = gate.get("count_source") if isinstance(gate, Mapping) else None
    if source == "provider.preflight_count":
        return request, "exact"
    return request, "local"


__all__ = [
    "CountResolution",
    "count_input_tokens_async",
    "effective_output_reserve",
    "is_controlled_count_failure",
    "prepare_counted_request_async",
    "prepare_prospective_request_async",
    "request_reduction_levels",
    "resolve_model_limits_async",
    "validate_model_limits",
    "validate_provider_count",
]
