"""Application-owned Provider orchestration for Context compaction.

Core owns planning, validation and candidate construction.  This module owns
only the tool-free Provider request envelope and terminal response extraction;
the caller supplies the Application diagnostics sink and remains responsible
for durable Timeline commits.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, replace

from uthcode.core.compaction import (
    CompactionEpoch,
    CompactionSubpass,
    OversizedFold,
    TimelineAgingEpoch,
)
from uthcode.core.context import (
    ContextBudget,
    ContextRequestSafetyError,
    RequestAccounting,
    account_generation_request,
    evaluate_gates,
    preflight_safety_count,
    pressure_estimate,
)
from uthcode.core.provider import (
    CancellationToken,
    GenerationCompleted,
    GenerationRequest,
    InvalidProviderResponseError,
    Message,
    ProviderPort,
    TextPart,
    Usage,
    validated_provider_stream,
)

from .request_preparation import count_input_tokens_async


_COMPACTION_SYSTEM_PROMPT = (
    "You are UthCode's bounded Context compactor. Return only a JSON object with "
    "entries and coverage. Produce exactly one entry for every covered Turn, in "
    "the supplied order. Each entry must contain turn_id, the exact refs copied "
    "from Required coverage, and a short summary. Do not add Turns or facts that "
    "are not present in the raw evidence."
)

_TIMELINE_AGING_SYSTEM_PROMPT = (
    "You are UthCode's bounded Timeline aging compactor. Return only a JSON "
    "object with summary and coverage. Produce exactly one Macro summary for "
    "all supplied Turns in order. Use only the complete raw Transcript evidence; "
    "never summarize a Fine or Macro summary and never invent refs or Turns."
)

_OVERSIZED_SUBPASS_SYSTEM_PROMPT = (
    "You are UthCode's bounded Context compactor handling one oversized Turn "
    "subpass. Return only a JSON object with a short summary. Summarize only "
    "the supplied raw evidence; do not invent a Turn, ref, or durable record."
)

_OVERSIZED_FOLD_SYSTEM_PROMPT = (
    "You are UthCode's bounded Context compactor folding intermediate summaries. "
    "Return only a JSON object with a short summary. Preserve all facts from "
    "the supplied summaries and do not add durable refs or Turn identities."
)


@dataclass(frozen=True, slots=True)
class ProviderCompactionResult:
    """Text plus terminal usage from one tool-free Provider request."""

    text: str
    usage: Usage

    def __post_init__(self) -> None:
        if not isinstance(self.text, str) or not self.text.strip():
            raise ValueError("compaction Provider text must be non-empty")
        if not isinstance(self.usage, Usage):
            raise TypeError("compaction Provider usage must be Usage")


def _coverage_payload(epoch: CompactionEpoch | TimelineAgingEpoch) -> list[dict[str, object]]:
    return [
        {
            "turn_id": unit.turn_id,
            "refs": [ref.to_dict()],
        }
        for unit, ref in zip(epoch.units, epoch.refs, strict=True)
    ]


def compaction_input_payload(epoch: CompactionEpoch) -> str:
    """Add the explicit multi-Turn output contract to raw epoch evidence."""

    return (
        f"{epoch.input_text}\n\nRequired coverage (copy only these Turn IDs):\n"
        + json.dumps(
            _coverage_payload(epoch),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )


def timeline_aging_input_payload(epoch: TimelineAgingEpoch) -> str:
    return (
        f"{epoch.input_text}\n\nRequired Macro coverage (copy only these Turn IDs):\n"
        + json.dumps(
            _coverage_payload(epoch),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )


def oversized_subpass_input_payload(subpass: CompactionSubpass) -> str:
    return (
        f"{subpass.input_text}\n\nRequired source Turn ID (do not copy into a durable record):\n"
        + json.dumps(subpass.turn_id, ensure_ascii=False)
    )


def oversized_fold_input_payload(fold: OversizedFold) -> str:
    return (
        f"{fold.input_text}\n\nFold source count (no durable refs):\n"
        + str(len(fold.input_summaries))
    )


async def prepare_compaction_request_async(
    provider: ProviderPort,
    request: GenerationRequest,
    budget: ContextBudget,
    *,
    cancellation: CancellationToken,
) -> GenerationRequest:
    """Hard-gate one independent tool-free compaction request."""

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
        resolution = await count_input_tokens_async(provider, current)
        counted = preflight_safety_count(
            current,
            compact_budget,
            provider_count=resolution.value,
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
            "context_count_fallback": resolution.fallback_reason,
        }
        annotated = replace(current, metadata=metadata)
        if annotated == current:
            return current
        current = annotated
    raise ContextRequestSafetyError(
        "compact request count did not stabilize for the final request"
    )


async def run_compaction_provider(
    provider: ProviderPort,
    request: GenerationRequest,
    *,
    cancellation: CancellationToken,
) -> ProviderCompactionResult:
    """Run a validated tool-free stream and retain only text plus terminal usage."""

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
    return ProviderCompactionResult(text, terminal.response.usage)


async def summarize_compaction_epoch_with_provider(
    provider: ProviderPort,
    remote_model_id: str,
    budget: ContextBudget,
    epoch: CompactionEpoch | TimelineAgingEpoch | CompactionSubpass | OversizedFold,
    *,
    cancellation: CancellationToken,
    aging: bool = False,
    usage_sink: Callable[[Usage], None] | None = None,
) -> str:
    """Build and run the shared tool-free Hard-gated Context Provider call."""

    output_reserve = budget.compaction_output_reserve
    if budget.provider_max_output is not None:
        output_reserve = min(output_reserve, budget.provider_max_output)
    if output_reserve <= 0:
        raise ContextRequestSafetyError("compact output reserve is not provider-safe")

    if isinstance(epoch, TimelineAgingEpoch) or aging:
        if not isinstance(epoch, TimelineAgingEpoch):
            raise TypeError("aging compaction requires a TimelineAgingEpoch")
        payload = timeline_aging_input_payload(epoch)
        system_prompt = _TIMELINE_AGING_SYSTEM_PROMPT
        metadata = {
            "context_compaction_request": True,
            "context_compaction_level": "L5",
            "context_timeline_aging_request": True,
            "context_timeline_aging_epoch_turns": list(epoch.turn_ids),
        }
    elif isinstance(epoch, CompactionSubpass):
        payload = oversized_subpass_input_payload(epoch)
        system_prompt = _OVERSIZED_SUBPASS_SYSTEM_PROMPT
        metadata = {
            "context_compaction_request": True,
            "context_compaction_level": "L4_SUBPASS",
            "context_compaction_subpass_turn_id": epoch.turn_id,
            "context_compaction_subpass_sequences": list(epoch.source_sequences),
        }
    elif isinstance(epoch, OversizedFold):
        payload = oversized_fold_input_payload(epoch)
        system_prompt = _OVERSIZED_FOLD_SYSTEM_PROMPT
        metadata = {
            "context_compaction_request": True,
            "context_compaction_level": "L4_FOLD",
            "context_compaction_fold_indices": list(epoch.source_indices),
        }
    elif isinstance(epoch, CompactionEpoch):
        payload = compaction_input_payload(epoch)
        system_prompt = _COMPACTION_SYSTEM_PROMPT
        metadata = {
            "context_compaction_request": True,
            "context_compaction_epoch_turns": list(epoch.turn_ids),
        }
    else:  # pragma: no cover - typed caller boundary
        raise TypeError("unsupported compaction epoch")

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
    prepared = await prepare_compaction_request_async(
        provider,
        compact_request,
        budget,
        cancellation=cancellation,
    )
    result = await run_compaction_provider(
        provider,
        prepared,
        cancellation=cancellation,
    )
    if usage_sink is not None:
        usage_sink(result.usage)
    return result.text


__all__ = [
    "ProviderCompactionResult",
    "compaction_input_payload",
    "oversized_fold_input_payload",
    "oversized_subpass_input_payload",
    "prepare_compaction_request_async",
    "run_compaction_provider",
    "summarize_compaction_epoch_with_provider",
    "timeline_aging_input_payload",
]
