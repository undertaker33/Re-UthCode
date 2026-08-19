"""Application composition for the provider-independent Context Compiler."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any

from uthcode.core.context import (
    ContextBudget,
    CompactionResult,
    ContextCompactor,
    ContextCompiler,
    ContextCountEstimate,
    ContextRequestSafetyError,
    ContextSnapshot,
    ContextSourceBundle,
    ContextUsage,
    RequestAccounting,
    account_generation_request,
    evaluate_gates,
    instruction_text_from_context_snapshot,
    messages_from_context_snapshot,
    preflight_safety_count,
    pressure_estimate,
    resolve_context_budget,
)
from uthcode.core.history import CanonicalHistory, Projection
from uthcode.core.prompt import (
    ContextAuthority,
    ContextBlock,
    ContextScope,
    ContextSourceKind,
    ContextStability,
    CoreRuntimeContractSource,
    EnvironmentSource,
    ProjectInstructionSource,
    PromptAssetSource,
    RuntimePromptContext,
    RuntimeStateSource,
    ToolDefinitionSource,
    build_runtime_prompt_section,
)
from uthcode.core.provider import (
    GenerationRequest,
    Message,
    ModelLimits,
    ReasoningOptions,
    ReasoningPart,
    ToolDefinition,
    ToolResultPart,
    TextPart,
)
from uthcode.core.provider import CancellationToken

from .instructions import InstructionLoader
from .history import history_entries_for_message


class ApplicationContextService:
    """Assemble current Application sources without owning Context policy."""

    def __init__(
        self,
        compiler: ContextCompiler | None = None,
        compactor: ContextCompactor | None = None,
    ) -> None:
        self._compiler = compiler or ContextCompiler()
        self._compactor = compactor or ContextCompactor(
            token_estimator=self._compiler.token_estimator
        )
        self._last_snapshot: ContextSnapshot | None = None
        self._compact_count = 0
        self._compaction_events: list[dict[str, object]] = []
        self._last_compaction: dict[str, object] | None = None
        self._last_budget: ContextBudget | None = None
        self._last_gate: dict[str, object] | None = None
        self._last_pressure: ContextCountEstimate | None = None
        self._last_accounting: RequestAccounting | None = None
        self._last_count_fallback: str | None = None

    @property
    def compiler(self) -> ContextCompiler:
        return self._compiler

    @property
    def last_snapshot(self) -> ContextSnapshot | None:
        return self._last_snapshot

    def compile(
        self,
        *,
        instruction_loader: InstructionLoader | None = None,
        history: CanonicalHistory | None = None,
        projection: Projection | None = None,
        current_turn: Sequence[object] = (),
        current_user: str | Message | None = None,
        current_turn_deltas: Sequence[object] = (),
        runtime_context: RuntimePromptContext | None = None,
        protected_context: Sequence[object] = (),
        protocol_blocks: Sequence[object] = (),
        environment_sources: Sequence[object] = (),
        tool_definitions: Sequence[ToolDefinition] = (),
        previous_snapshot: ContextSnapshot | None = None,
        context_budget: ContextBudget | None = None,
    ) -> ContextSnapshot:
        if instruction_loader is not None and not isinstance(instruction_loader, InstructionLoader):
            raise TypeError("instruction_loader must be InstructionLoader or None")
        if runtime_context is not None and not isinstance(runtime_context, RuntimePromptContext):
            raise TypeError("runtime_context must be RuntimePromptContext or None")
        ordinary_tools = tuple(tool_definitions)
        if not all(isinstance(item, ToolDefinition) for item in ordinary_tools):
            raise TypeError("tool_definitions must contain ToolDefinition values")
        if context_budget is not None and not isinstance(context_budget, ContextBudget):
            raise TypeError("context_budget must be a ContextBudget or None")

        project_source = None
        if instruction_loader is not None:
            project_source = ProjectInstructionSource(
                effective_instruction_set=instruction_loader.effective_instruction_set,
                instruction_epoch=instruction_loader.instruction_epoch,
                stable_prefix_fingerprint=instruction_loader.stable_prefix_fingerprint,
                change_reason=instruction_loader.change_reason,
            )

        runtime_sources: list[object] = []
        if runtime_context is not None:
            section = build_runtime_prompt_section(runtime_context)
            runtime_sources.append(
                RuntimeStateSource(
                    ContextBlock(
                        source_kind=ContextSourceKind.RUNTIME_FACT,
                        authority=ContextAuthority.RUNTIME,
                        stability=ContextStability.DYNAMIC,
                        scope=ContextScope.TURN,
                        provenance="application:runtime-state",
                        content=section.content,
                    )
                )
            )

        tool_source = ToolDefinitionSource(ordinary_tools)
        normalized_current_turn = tuple(current_turn)
        if current_user is not None:
            normalized_current_turn = (*normalized_current_turn, current_user)
        bundle = ContextSourceBundle(
            instruction_sources=(PromptAssetSource(), CoreRuntimeContractSource()),
            project_instruction_source=project_source,
            history=history,
            projection=projection,
            protected_context=tuple(protected_context),
            protocol_blocks=tuple(protocol_blocks),
            current_turn=normalized_current_turn,
            current_turn_deltas=tuple(current_turn_deltas),
            runtime_sources=tuple(runtime_sources),
            environment_sources=tuple(environment_sources),
            tool_source=tool_source,
        )
        compiler = self._compiler
        if context_budget is not None and compiler.budget_tokens != context_budget.effective_input_limit:
            compiler = ContextCompiler(
                budget_tokens=context_budget.effective_input_limit,
                token_estimator=compiler.token_estimator,
            )
        snapshot = compiler.compile(
            bundle,
            previous_snapshot=(self._last_snapshot if previous_snapshot is None else previous_snapshot),
        )
        self._last_snapshot = snapshot
        self._last_budget = context_budget
        return snapshot

    def usage(self, snapshot: ContextSnapshot | None = None) -> ContextUsage:
        value = self._last_snapshot if snapshot is None else snapshot
        if value is None:
            return ContextUsage(0, available=False)
        return value.usage

    @property
    def compactor(self) -> ContextCompactor:
        return self._compactor

    def compact(
        self,
        history: CanonicalHistory,
        *,
        projection: Projection | None = None,
        session_id: str | None = None,
        summarize=None,
        cancellation: CancellationToken | None = None,
    ) -> CompactionResult:
        """Return a safe Projection candidate without mutating History."""

        self._compact_count += 1
        attempt = self._compact_count
        try:
            result = self._compactor.compact(
                history,
                projection=projection,
                session_id=session_id,
                summarize=summarize,
                cancellation=cancellation,
            )
        except Exception:
            self._record_compaction(
                {
                    "attempt": attempt,
                    "status": "failed",
                    "changed": False,
                    "failure": "compaction_error",
                    "batch_count": 0,
                }
            )
            raise
        self._record_compaction(
            {
                "attempt": attempt,
                "status": (
                    "failed"
                    if result.failure is not None
                    else ("completed" if result.changed else "no_change")
                ),
                "changed": result.changed,
                "failure": result.failure,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "batch_count": len(result.batches),
            }
        )
        return result

    def public_diagnostics(self) -> dict[str, object]:
        """Return a bounded diagnostics projection without Context content."""

        snapshot = self._last_snapshot
        if snapshot is None:
            context: dict[str, object] = {"status": "not_available"}
        else:
            context = {
                "status": "available",
                "budget_tokens": snapshot.budget_tokens,
                "used_tokens": snapshot.used_tokens,
                "token_estimate": snapshot.token_estimate,
                "selected_block_ids": list(snapshot.selected_block_ids),
                "omitted_block_ids": list(snapshot.omitted_block_ids),
                "selected_count": len(snapshot.selected_blocks),
                "omitted_count": len(snapshot.omitted_blocks),
                "omitted_reasons": [
                    {"block_id": block_id, "reason": reason}
                    for block_id, reason in snapshot.omitted_reasons
                ],
                "projection_revision": snapshot.projection_revision,
                "instruction_epoch": snapshot.instruction_epoch,
                "stable_prefix_estimated_tokens": snapshot.stable_prefix_estimated_tokens,
                "stable_prefix_fingerprint": snapshot.stable_prefix_fingerprint,
                "prefix_changed": snapshot.prefix_changed,
                "prefix_change_reason": snapshot.prefix_change_reason,
                "tool_schema_fingerprint": snapshot.tool_schema_fingerprint,
                "tool_schema_estimated_tokens": snapshot.tool_schema_estimated_tokens,
                "over_budget": snapshot.over_budget,
            }
        return {
            "schema_version": 1,
            "context": context,
            "budget": (
                None if self._last_budget is None else self._last_budget.to_dict()
            ),
            "request_accounting": (
                None
                if self._last_accounting is None
                else self._last_accounting.to_dict()
            ),
            "gate": None if self._last_gate is None else dict(self._last_gate),
            "pressure": (
                None
                if self._last_pressure is None
                else self._last_pressure.to_dict()
            ),
            "count_fallback": self._last_count_fallback,
            "compaction": {
                # A resumed Session may already carry a durable Projection
                # revision before this process performs a compaction.  Keep
                # the public count compatible with that durable fact while
                # still counting current-process attempts.
                "count": max(
                    self._compact_count,
                    (
                        snapshot.projection_revision or 0
                        if snapshot is not None
                        else 0
                    ),
                ),
                "last": None if self._last_compaction is None else dict(self._last_compaction),
                "events": [dict(item) for item in self._compaction_events],
            },
        }

    def _record_compaction(self, event: dict[str, object]) -> None:
        self._last_compaction = dict(event)
        self._compaction_events.append(dict(event))
        del self._compaction_events[:-16]

    def finalize_compaction(self, result: CompactionResult) -> None:
        """Reconcile diagnostics with the final persistence outcome.

        ``compact()`` records the in-memory candidate before Application
        persists its Projection.  A failed append must replace that provisional
        completed event so public diagnostics describe the same result callers
        receive.
        """

        if not isinstance(result, CompactionResult):
            raise TypeError("result must be a CompactionResult")
        if self._last_compaction is None:
            return
        event = dict(self._last_compaction)
        event.update(
            {
                "status": (
                    "failed"
                    if result.failure is not None
                    else ("completed" if result.changed else "no_change")
                ),
                "changed": result.changed,
                "failure": result.failure,
                "batch_count": len(result.batches),
            }
        )
        self._last_compaction = event
        if self._compaction_events:
            self._compaction_events[-1] = dict(event)

    def compose_generation_request(
        self,
        messages: Sequence[Message],
        *,
        run_id: str,
        session_id: str | None = None,
        canonical_history: CanonicalHistory | None = None,
        instruction_loader: InstructionLoader | None = None,
        runtime_context: RuntimePromptContext | None = None,
        projection: Projection | None = None,
        tool_definitions: Sequence[ToolDefinition] = (),
        environment_sources: Sequence[object] = (),
        model: str | None = None,
        reasoning: ReasoningOptions | None = None,
        max_output_tokens: int | None = None,
        temperature: float | None = None,
        previous_snapshot: ContextSnapshot | None = None,
        configured_input_limit: int | None = None,
        provider_limits: ModelLimits | None = None,
        context_budget: ContextBudget | None = None,
        provider_count: ContextCountEstimate | int | None = None,
        defer_hard_gate: bool = False,
        count_fallback: str | None = None,
        candidate_messages: Sequence[Message] | None = None,
        disable_reductions: bool = False,
        reduction_levels: Sequence[str] = (),
    ) -> tuple[GenerationRequest, ContextSnapshot]:
        """Compile and, when limits are supplied, preflight one final request.

        The service is also used by read-only Context tests and diagnostics,
        so callers may omit limits when they only need a provider-independent
        snapshot.  The formal Application generation path always supplies a
        resolved ``ContextBudget`` before it can hand this request to a
        Provider.
        """

        values = tuple(messages)
        if not all(isinstance(message, Message) for message in values):
            raise TypeError("messages must contain Message values")
        if not isinstance(run_id, str) or not run_id:
            raise ValueError("run_id must be a non-empty string")
        if session_id is not None and (not isinstance(session_id, str) or not session_id):
            raise ValueError("session_id must be a non-empty string or None")
        if canonical_history is not None and not isinstance(canonical_history, CanonicalHistory):
            raise TypeError("canonical_history must be a CanonicalHistory or None")
        history_session_id = (
            session_id
            if session_id is not None
            else (
                projection.session_id
                if projection is not None
                else (
                    canonical_history.session_id
                    if canonical_history is not None
                    else f"run:{run_id}"
                )
            )
        )
        if projection is not None and history_session_id != projection.session_id:
            raise ValueError("session_id must match the supplied Projection")
        if (
            canonical_history is not None
            and history_session_id != canonical_history.session_id
        ):
            raise ValueError("session_id must match the supplied Canonical History")
        ordinary_tools = tuple(tool_definitions)
        if not all(isinstance(item, ToolDefinition) for item in ordinary_tools):
            raise TypeError("tool_definitions must contain ToolDefinition values")
        if provider_limits is not None and not isinstance(provider_limits, ModelLimits):
            raise TypeError("provider_limits must be ModelLimits or None")
        if context_budget is not None and not isinstance(context_budget, ContextBudget):
            raise TypeError("context_budget must be a ContextBudget or None")
        if not isinstance(defer_hard_gate, bool):
            raise TypeError("defer_hard_gate must be a boolean")
        if not isinstance(disable_reductions, bool):
            raise TypeError("disable_reductions must be a boolean")
        if count_fallback is not None and (
            not isinstance(count_fallback, str) or not count_fallback
        ):
            raise ValueError("count_fallback must be a non-empty string or None")
        if candidate_messages is not None:
            candidate_messages = tuple(candidate_messages)
            if not all(isinstance(message, Message) for message in candidate_messages):
                raise TypeError("candidate_messages must contain Message values")
        reduction_levels = tuple(reduction_levels)
        if any(not isinstance(level, str) or not level for level in reduction_levels):
            raise ValueError("reduction_levels must contain non-empty strings")
        if context_budget is not None and (
            configured_input_limit is not None or provider_limits is not None
        ):
            raise TypeError("pass context_budget or individual limits, not both")
        if context_budget is None and (
            configured_input_limit is not None or provider_limits is not None
        ):
            context_budget = resolve_context_budget(
                configured_input_limit=configured_input_limit,
                provider_limits=provider_limits,
                requested_output_reserve=(max_output_tokens or 0),
            )

        current_user: Message | None = None
        history_messages = values
        if values and values[-1].role == "user":
            current_user = values[-1]
            history_messages = values[:-1]
        process_history = _history_for_messages(history_session_id, history_messages)
        history = _merge_canonical_history(canonical_history, process_history)
        snapshot = self.compile(
            instruction_loader=instruction_loader,
            history=history,
            projection=projection,
            current_user=current_user,
            runtime_context=runtime_context,
            environment_sources=environment_sources,
            tool_definitions=ordinary_tools,
            previous_snapshot=previous_snapshot,
            context_budget=context_budget,
        )
        conversation = (
            tuple(candidate_messages)
            if candidate_messages is not None
            else messages_from_context_snapshot(snapshot)
        )
        prompt = instruction_text_from_context_snapshot(snapshot)
        base_metadata: dict[str, object] = {
            "context_budget_tokens": snapshot.budget_tokens,
            "context_token_estimate": snapshot.token_estimate,
            "context_selected_block_ids": list(snapshot.selected_block_ids),
            "context_omitted_block_ids": list(snapshot.omitted_block_ids),
            "projection_revision": snapshot.projection_revision,
            "instruction_epoch": snapshot.instruction_epoch,
            "stable_prefix_fingerprint": snapshot.stable_prefix_fingerprint,
            "tool_schema_fingerprint": snapshot.tool_schema_fingerprint,
        }

        def build_candidate(candidate_messages: Sequence[Message]) -> GenerationRequest:
            return GenerationRequest(
                messages=tuple(candidate_messages),
                system_prompt=prompt,
                model=model,
                tools=snapshot.tool_definitions,
                reasoning=reasoning,
                max_output_tokens=max_output_tokens,
                temperature=temperature,
                metadata=base_metadata,
            )

        request = build_candidate(conversation)
        accounting = account_generation_request(request)
        gate = None
        pressure_count = None
        reduction_steps: list[str] = list(reduction_levels)
        candidate_messages = tuple(conversation)
        if context_budget is not None:
            if disable_reductions:
                count = preflight_safety_count(
                    request,
                    context_budget,
                    provider_count=provider_count,
                )
                pressure_count = pressure_estimate(request, context_budget)
                gate = evaluate_gates(
                    context_budget,
                    count,
                    accounting=accounting,
                    pressure_count=pressure_count,
                )
            else:
                for level, reducer in (
                    ("L1", _externalize_tool_result_previews),
                    ("L2", _shrink_inactive_previews),
                ):
                    count = preflight_safety_count(
                        request,
                        context_budget,
                        provider_count=(provider_count if not reduction_steps else None),
                    )
                    pressure_count = pressure_estimate(request, context_budget)
                    gate = evaluate_gates(
                        context_budget,
                        count,
                        accounting=accounting,
                        pressure_count=pressure_count,
                    )
                    if gate.hard_safe and not gate.auto_pressure:
                        break
                    reduced = reducer(candidate_messages)
                    if not reduced.changed:
                        continue
                    candidate_messages = reduced.messages
                    reduction_steps.append(level)
                    request = build_candidate(candidate_messages)
                    accounting = account_generation_request(request)
                if gate is None or reduction_steps:
                    count = preflight_safety_count(
                        request,
                        context_budget,
                        provider_count=None,
                    )
                    pressure_count = pressure_estimate(request, context_budget)
                    gate = evaluate_gates(
                        context_budget,
                        count,
                        accounting=accounting,
                        pressure_count=pressure_count,
                    )
            if not gate.hard_safe and not defer_hard_gate:
                raise ContextRequestSafetyError(
                    "final request failed the preflight Hard Gate: " + gate.reason
                )

        metadata = dict(base_metadata)
        metadata["request_accounting"] = accounting.to_dict()
        if context_budget is not None and gate is not None:
            metadata["context_budget"] = context_budget.to_dict()
            metadata["context_gate"] = gate.to_dict()
            metadata["context_pressure"] = (
                None if pressure_count is None else pressure_count.to_dict()
            )
            metadata["context_reduction_levels"] = list(reduction_steps)
            metadata["context_count_source"] = gate.count_source
            metadata["context_count_fallback"] = count_fallback
            self._last_budget = context_budget
            self._last_gate = gate.to_dict()
            self._last_pressure = pressure_count
            self._last_count_fallback = count_fallback
        else:
            self._last_gate = None
            self._last_pressure = None
            self._last_count_fallback = None
        self._last_accounting = accounting
        request = replace(request, metadata=metadata)
        return request, snapshot


@dataclass(frozen=True, slots=True)
class _ReductionResult:
    messages: tuple[Message, ...]
    changed: bool


def _externalize_tool_result_previews(
    messages: Sequence[Message],
    *,
    threshold: int = 8_192,
) -> _ReductionResult:
    """Apply the deterministic L1 request-side preview reduction.

    The normal Application tool path already materializes oversized results
    before they enter durable History.  This bounded fallback covers embedded
    callers that supply a raw ``GenerationRequest`` directly; it keeps every
    ToolCall/ToolResult part and changes only the provider-visible preview.
    """

    changed = False
    result: list[Message] = []
    for message in messages:
        parts: list[object] = []
        for part in message.parts:
            if isinstance(part, ToolResultPart) and len(part.content) > threshold:
                changed = True
                parts.append(
                    replace(
                        part,
                        content=(
                            f"[externalized tool result {part.tool_call_id}; "
                            "use the bounded result reader for the full value]"
                        ),
                        metadata={
                            **dict(part.metadata),
                            "context_reduction": "L1_externalized_preview",
                            "original_characters": len(part.content),
                        },
                    )
                )
            else:
                parts.append(part)
        result.append(replace(message, parts=tuple(parts)))
    return _ReductionResult(tuple(result), changed)


def _bounded_preview(text: str, *, limit: int = 2_048) -> str:
    if len(text) <= limit:
        return text
    left = max(1, (limit - 64) // 2)
    right = max(1, limit - 64 - left)
    return (
        text[:left]
        + "\n[… context preview reduced deterministically …]\n"
        + text[-right:]
    )


def _shrink_inactive_previews(
    messages: Sequence[Message],
    *,
    limit: int = 2_048,
) -> _ReductionResult:
    """Apply bounded L2 previews without splitting ToolCall/ToolResult pairs."""

    changed = False
    result: list[Message] = []
    current_user_index = next(
        (
            index
            for index in range(len(messages) - 1, -1, -1)
            if messages[index].role == "user"
        ),
        None,
    )
    for index, message in enumerate(messages):
        parts: list[object] = []
        for part in message.parts:
            if (
                index != current_user_index
                and isinstance(part, (TextPart, ReasoningPart, ToolResultPart))
            ):
                preview = _bounded_preview(part.text if isinstance(part, (TextPart, ReasoningPart)) else part.content, limit=limit)
                original = part.text if isinstance(part, (TextPart, ReasoningPart)) else part.content
                if preview != original:
                    changed = True
                    if isinstance(part, TextPart):
                        parts.append(replace(part, text=preview))
                    elif isinstance(part, ReasoningPart):
                        parts.append(replace(part, text=preview))
                    else:
                        parts.append(
                            replace(
                                part,
                                content=preview,
                                metadata={
                                    **dict(part.metadata),
                                    "context_reduction": "L2_bounded_preview",
                                    "original_characters": len(original),
                                },
                            )
                        )
                    continue
            parts.append(part)
        result.append(replace(message, parts=tuple(parts)))
    return _ReductionResult(tuple(result), changed)


def _history_for_messages(session_id: str, messages: Sequence[Message]) -> CanonicalHistory:
    history = CanonicalHistory(session_id)
    sequence = 1
    for index, message in enumerate(messages):
        turn_id = f"runtime-{index + 1}"
        entries = history_entries_for_message(session_id, turn_id, sequence, message)
        for entry in entries:
            # These entries are a deterministic, process-local projection of
            # the messages supplied to request preparation.  Wall-clock
            # timestamps here would make an otherwise identical rebuild
            # Provider-visible only through diagnostics/block IDs, defeating
            # exact count -> rebuild -> re-gate verification.
            history = history.append(
                replace(entry, created_at=f"runtime:{entry.sequence:08d}")
            )
        sequence += len(entries)
    return history


def _merge_canonical_history(
    canonical_history: CanonicalHistory | None,
    process_history: CanonicalHistory,
) -> CanonicalHistory:
    """Join durable History with this Run's ordered process-local delta.

    The compiler needs one Canonical History so Projection can filter its
    covered range and leave the raw tail visible.  The two inputs are separate
    ownership domains: durable History is the restored base, while
    ``process_history`` contains only this process's Run/Turn delta.  Its
    entries are always appended, including equal payloads, because message
    content cannot identify whether two same-text Turns are the same fact.
    """

    if canonical_history is None:
        return process_history
    if canonical_history.session_id != process_history.session_id:
        raise ValueError("Canonical History and process messages belong to different Sessions")
    if not process_history.entries:
        return canonical_history
    if not canonical_history.entries:
        return process_history

    merged = canonical_history
    for entry in process_history.entries:
        merged = merged.append(
            replace(
                entry,
                session_id=merged.session_id,
                sequence=merged.last_sequence + 1,
            )
        )
    return merged


__all__ = ["ApplicationContextService"]
