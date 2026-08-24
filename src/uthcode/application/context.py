"""Application composition for the provider-independent Context Compiler."""

from __future__ import annotations

import inspect
from asyncio import CancelledError
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from uthcode.core.context import (
    ContextBudget,
    CompactionEpoch,
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
    fine_timeline_usage,
)
from uthcode.core.compaction import TimelineAgingEpoch
from uthcode.core.history import Timeline, Transcript
from uthcode.core.prompt import (
    ContextAuthority,
    ContextBlock,
    ContextScope,
    ContextSourceKind,
    ContextStability,
    ProjectInstructionSource,
    RuntimePromptContext,
    ToolDefinitionSource,
    build_runtime_prompt_section,
    core_runtime_contract_source,
    public_prompt_source,
)
from uthcode.core.provider import (
    CancellationToken,
    GenerationCancelled,
    GenerationRequest,
    Message,
    ModelLimits,
    ReasoningOptions,
    ReasoningPart,
    ToolDefinition,
    ToolResultPart,
    TextPart,
)

from .instructions import InstructionLoader
from .history import _transcript_entries_for_message


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
        instruction_loader: InstructionLoader | ProjectInstructionSource | None = None,
        transcript: Transcript | None = None,
        timeline: Timeline | None = None,
        current_turn: Sequence[ContextBlock | Message | str] = (),
        current_user: str | Message | None = None,
        current_turn_deltas: Sequence[ContextBlock | Message | str] = (),
        runtime_context: RuntimePromptContext | None = None,
        protected_context: Sequence[ContextBlock] = (),
        protocol_blocks: Sequence[ContextBlock] = (),
        environment_sources: Sequence[ContextBlock] = (),
        tool_definitions: Sequence[ToolDefinition] = (),
        previous_snapshot: ContextSnapshot | None = None,
        context_budget: ContextBudget | None = None,
        preserve_request_diagnostics: bool = False,
    ) -> ContextSnapshot:
        if instruction_loader is not None and not isinstance(
            instruction_loader,
            (InstructionLoader, ProjectInstructionSource),
        ):
            raise TypeError(
                "instruction_loader must be an InstructionLoader, "
                "ProjectInstructionSource, or None"
            )
        if runtime_context is not None and not isinstance(runtime_context, RuntimePromptContext):
            raise TypeError("runtime_context must be RuntimePromptContext or None")
        ordinary_tools = tuple(tool_definitions)
        if not all(isinstance(item, ToolDefinition) for item in ordinary_tools):
            raise TypeError("tool_definitions must contain ToolDefinition values")
        if context_budget is not None and not isinstance(context_budget, ContextBudget):
            raise TypeError("context_budget must be a ContextBudget or None")

        project_source = None
        if isinstance(instruction_loader, ProjectInstructionSource):
            project_source = instruction_loader
        elif instruction_loader is not None:
            project_source = ProjectInstructionSource(
                effective_instruction_set=instruction_loader.effective_instruction_set,
                instruction_epoch=instruction_loader.instruction_epoch,
                stable_prefix_fingerprint=instruction_loader.stable_prefix_fingerprint,
                change_reason=instruction_loader.change_reason,
            )

        runtime_sources: list[ContextBlock] = []
        if runtime_context is not None:
            section = build_runtime_prompt_section(runtime_context)
            runtime_sources.append(
                ContextBlock(
                    source_kind=ContextSourceKind.RUNTIME_FACT,
                    authority=ContextAuthority.RUNTIME,
                    stability=ContextStability.DYNAMIC,
                    scope=ContextScope.TURN,
                    provenance="application:runtime-state",
                    content=section.content,
                )
            )

        tool_source = ToolDefinitionSource(ordinary_tools)
        normalized_current_turn = tuple(current_turn)
        if current_user is not None:
            normalized_current_turn = (*normalized_current_turn, current_user)
        bundle = ContextSourceBundle(
            instruction_sources=(public_prompt_source(), core_runtime_contract_source()),
            project_instruction_source=project_source,
            transcript=transcript,
            timeline=timeline,
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
        if not preserve_request_diagnostics:
            self._last_budget = context_budget
        return snapshot

    def usage(self, snapshot: ContextSnapshot | None = None) -> ContextUsage:
        value = self._last_snapshot if snapshot is None else snapshot
        if value is None:
            return ContextUsage(0, available=False)
        return value.usage

    def stable_transcript_for_compaction(
        self,
        transcript: Transcript,
        *,
        active_turn_id: str | None = None,
    ) -> Transcript:
        """Return only the stable Transcript prefix for one compaction pass.

        Closed facts from the active Turn are durably appended before ordinary
        Provider calls, but that Turn is still an open semantic unit until its
        terminal assistant message is persisted.  Compaction therefore removes
        the whole active Turn by its stable identity, and only when that
        identity forms the Transcript suffix expected by the single-writer
        lifecycle.  It never guesses from roles, message positions, or the
        final entry alone.
        """

        if not isinstance(transcript, Transcript):
            raise TypeError("transcript must be a Transcript")
        if active_turn_id is None:
            return transcript
        if not isinstance(active_turn_id, str) or not active_turn_id:
            raise ValueError("active_turn_id must be a non-empty string or None")

        matching_indexes = tuple(
            index
            for index, entry in enumerate(transcript.entries)
            if entry.turn_id == active_turn_id
        )
        if not matching_indexes:
            return transcript
        first_index = matching_indexes[0]
        if any(
            entry.turn_id != active_turn_id
            for entry in transcript.entries[first_index:]
        ):
            raise ContextRequestSafetyError(
                "active Turn is not a stable Transcript suffix"
            )
        return Transcript(
            transcript.session_id,
            transcript.entries[:first_index],
            transcript.schema_version,
        )

    @staticmethod
    def _non_reducing_result(
        candidate: CompactionResult,
        previous_timeline: Timeline | None,
    ) -> CompactionResult | None:
        """Turn an equal-or-larger candidate into an uncommittable result."""

        if candidate.output_tokens < candidate.input_tokens:
            return None
        return replace(
            candidate,
            timeline=previous_timeline,
            summary=(
                previous_timeline.summary
                if previous_timeline is not None
                else None
            ),
            batches=(),
            changed=False,
            failure="no_reduction",
        )

    def record_request_diagnostics(
        self,
        request: GenerationRequest,
        budget: ContextBudget,
    ) -> None:
        """Project one already-gated request into safe status dimensions."""

        if not isinstance(request, GenerationRequest):
            raise TypeError("request must be a GenerationRequest")
        if not isinstance(budget, ContextBudget):
            raise TypeError("budget must be a ContextBudget")
        self._last_budget = budget
        self._last_accounting = account_generation_request(request)
        gate = request.metadata.get("context_gate")
        self._last_gate = dict(gate) if isinstance(gate, Mapping) else None
        pressure = request.metadata.get("context_pressure")
        if isinstance(pressure, Mapping):
            self._last_pressure = ContextCountEstimate(
                input_tokens=pressure.get("input_tokens", 0),
                source=pressure.get("source", "local.pressure_estimate"),
                kind=pressure.get("kind", "pressure_estimate"),
                safety_allowance=pressure.get("safety_allowance", 0),
            )
        else:
            self._last_pressure = None
        fallback = request.metadata.get("context_count_fallback")
        self._last_count_fallback = fallback if isinstance(fallback, str) else None

    @property
    def compactor(self) -> ContextCompactor:
        return self._compactor

    async def compact_async(
        self,
        transcript: Transcript,
        *,
        timeline: Timeline | None = None,
        session_id: str | None = None,
        summarize: Callable[[CompactionEpoch], object | Awaitable[object]],
        commit: Callable[
            [CompactionResult],
            bool | CompactionResult | Awaitable[bool | CompactionResult],
        ] | None = None,
        should_continue: Callable[
            [Timeline],
            bool | Mapping[str, object] | Awaitable[bool | Mapping[str, object]],
        ] | None = None,
        cancellation: CancellationToken | None = None,
        max_epochs: int = 4,
        input_budget: int | None = None,
        output_reserve: int | None = None,
        summary_hard_cap: int | None = None,
        active_turn_id: str | None = None,
    ) -> CompactionResult:
        """Run bounded tool-free L4 epochs in one Application call stack.

        Each successful epoch is committed before the next epoch is derived.
        ``should_continue`` is called with the freshly committed Timeline so
        the caller can rebuild the ordinary request and re-run Auto/Hard Gate.
        No loop cursor is written to durable Session state.
        """

        if not isinstance(transcript, Transcript):
            raise TypeError("transcript must be a Transcript")
        if timeline is not None and (
            not isinstance(timeline, Timeline)
            or timeline.session_id != transcript.session_id
        ):
            raise ValueError("transcript and timeline must belong to the same Session")
        if not callable(summarize):
            raise TypeError("summarize must be callable")
        if cancellation is not None and not isinstance(cancellation, CancellationToken):
            raise TypeError("cancellation must be a CancellationToken or None")
        if (
            isinstance(max_epochs, bool)
            or not isinstance(max_epochs, int)
            or max_epochs <= 0
        ):
            raise ValueError("max_epochs must be a positive integer")

        transcript = self.stable_transcript_for_compaction(
            transcript,
            active_turn_id=active_turn_id,
        )

        owner = transcript.session_id if session_id is None else session_id
        if owner != transcript.session_id:
            raise ValueError("Compaction Session does not own the supplied Transcript")
        lock = self._compactor._acquire_single_flight(owner)
        self._compact_count += 1
        orchestration_attempt = self._compact_count
        current_timeline = timeline
        committed_any = False
        last_success: CompactionResult | None = None
        last_failure: str | None = None
        previous_sequence_end = current_timeline.sequence_end if current_timeline is not None else 0
        failure_streak = 0

        def outcome(
            *,
            result: CompactionResult | None,
            failure: str | None,
            epoch: int,
            attempt: int = 0,
        ) -> None:
            coverage_count = 0 if result is None else len(result.batches)
            self._record_compaction(
                {
                    "attempt": orchestration_attempt,
                    "epoch": epoch,
                    "epoch_limit": max_epochs,
                    "epoch_attempt": attempt,
                    "status": "failed" if failure is not None else "completed",
                    "changed": False if result is None else result.changed,
                    "failure": failure,
                    "coverage_count": coverage_count,
                    "input_tokens": 0 if result is None else result.input_tokens,
                    "output_tokens": 0 if result is None else result.output_tokens,
                }
            )

        try:
            for epoch_number in range(1, max_epochs + 1):
                if cancellation is not None and cancellation.cancelled:
                    last_failure = "compaction_cancelled"
                    outcome(result=last_success, failure=last_failure, epoch=epoch_number)
                    break

                epoch = self._compactor.plan_epoch(
                    transcript,
                    timeline=current_timeline,
                    session_id=owner,
                    input_budget=input_budget,
                    output_reserve=output_reserve,
                )
                if epoch is None:
                    last_failure = "no_safe_epoch"
                    outcome(result=last_success, failure=last_failure, epoch=epoch_number)
                    break

                candidate_result: CompactionResult | None = None
                failure_streak = 0
                for epoch_attempt in range(1, 3):
                    if cancellation is not None and cancellation.cancelled:
                        last_failure = "compaction_cancelled"
                        break
                    try:
                        generated = summarize(epoch)
                        if inspect.isawaitable(generated):
                            generated = await generated
                        if cancellation is not None and cancellation.cancelled:
                            last_failure = "compaction_cancelled"
                            break
                        parsed = self._compactor.parse_epoch_result(
                            generated,
                            epoch=epoch,
                            summary_hard_cap=summary_hard_cap,
                        )
                        candidate_result = self._compactor.build_epoch_candidate(
                            transcript,
                            epoch=epoch,
                            result=parsed,
                            timeline=current_timeline,
                        )
                        # A parse/validation failure from the first attempt is
                        # transient once the retry produces a valid candidate.
                        # Later terminal breakers still set their own reason.
                        last_failure = None
                        break
                    except GenerationCancelled:
                        # Provider cancellation is a control-flow exit, not
                        # an invalid structured compaction result.  Let the
                        # existing Application/AgentRun cancellation path
                        # handle it without retrying this epoch.
                        raise
                    except CancelledError:
                        # Preserve asyncio cancellation even when the shared
                        # Core token has not been marked cancelled yet.
                        raise
                    except Exception as exc:
                        if cancellation is not None and cancellation.cancelled:
                            last_failure = "compaction_cancelled"
                            break
                        failure_streak += 1
                        if epoch_attempt == 2:
                            # Keep the public reason stable; exception text may
                            # contain provider payload or other sensitive data.
                            del exc
                            last_failure = "repeated_failure"
                        else:
                            last_failure = "compaction_result_invalid"
                if candidate_result is None:
                    outcome(
                        result=last_success,
                        failure=last_failure or "repeated_failure",
                        epoch=epoch_number,
                        attempt=failure_streak,
                    )
                    break

                if cancellation is not None and cancellation.cancelled:
                    last_failure = "compaction_cancelled"
                    outcome(
                        result=last_success,
                        failure=last_failure,
                        epoch=epoch_number,
                        attempt=epoch_attempt,
                    )
                    break

                non_reducing = self._non_reducing_result(
                    candidate_result,
                    current_timeline,
                )
                if non_reducing is not None:
                    last_failure = "no_reduction"
                    outcome(
                        result=non_reducing,
                        failure=last_failure,
                        epoch=epoch_number,
                        attempt=epoch_attempt,
                    )
                    break

                if candidate_result.timeline is None or not candidate_result.changed:
                    last_failure = "no_progress"
                    outcome(
                        result=candidate_result,
                        failure=last_failure,
                        epoch=epoch_number,
                        attempt=epoch_attempt,
                    )
                    break

                committed_result = candidate_result
                if commit is not None:
                    committed = commit(candidate_result)
                    if inspect.isawaitable(committed):
                        committed = await committed
                    if isinstance(committed, CompactionResult):
                        committed_result = committed
                        committed_ok = (
                            committed.changed
                            and committed.failure is None
                            and committed.timeline is not None
                        )
                    elif isinstance(committed, bool):
                        committed_ok = committed
                    else:
                        committed_ok = False
                    if not committed_ok:
                        last_failure = "timeline_commit_failed"
                        outcome(
                            result=committed_result,
                            failure=last_failure,
                            epoch=epoch_number,
                        )
                        break

                next_timeline = committed_result.timeline or candidate_result.timeline
                if next_timeline is None or next_timeline.sequence_end <= previous_sequence_end:
                    last_failure = "no_progress"
                    outcome(
                        result=committed_result,
                        failure=last_failure,
                        epoch=epoch_number,
                    )
                    break

                current_timeline = next_timeline
                previous_sequence_end = current_timeline.sequence_end
                committed_any = True
                last_success = replace(
                    committed_result,
                    timeline=current_timeline,
                    changed=True,
                    failure=None,
                )
                outcome(
                    result=last_success,
                    failure=None,
                    epoch=epoch_number,
                    attempt=epoch_attempt,
                )

                if should_continue is None:
                    break
                decision = should_continue(current_timeline)
                if inspect.isawaitable(decision):
                    decision = await decision
                if isinstance(decision, Mapping):
                    continue_value = decision.get("continue", False)
                elif isinstance(decision, bool):
                    continue_value = decision
                else:
                    raise TypeError("should_continue must return bool or a mapping")
                if not isinstance(continue_value, bool):
                    raise TypeError("should_continue mapping must contain boolean 'continue'")
                if not continue_value:
                    break
            else:
                last_failure = "epoch_limit_reached"
                outcome(
                    result=last_success,
                    failure=last_failure,
                    epoch=max_epochs,
                )
        finally:
            lock.release()

        if last_success is not None:
            # Preserve a bounded terminal reason even when earlier epochs
            # committed successfully.  The durable Timeline remains the
            # successful result, while callers can distinguish a complete
            # catch-up from a partial one that stopped at no-safe-epoch,
            # no-progress, cancellation, or the epoch breaker.
            return replace(last_success, failure=last_failure)
        return CompactionResult(
            timeline=current_timeline,
            summary=current_timeline.summary if current_timeline is not None else None,
            changed=committed_any,
            failure=last_failure or "no_safe_epoch",
        )

    async def age_timeline_async(
        self,
        transcript: Transcript,
        *,
        timeline: Timeline,
        session_id: str | None = None,
        summarize: Callable[[TimelineAgingEpoch], object | Awaitable[object]],
        commit: Callable[
            [CompactionResult],
            bool | CompactionResult | Awaitable[bool | CompactionResult],
        ] | None = None,
        cancellation: CancellationToken | None = None,
        fine_budget: int,
        input_budget: int | None = None,
        output_reserve: int | None = None,
        summary_hard_cap: int | None = None,
        active_turn_id: str | None = None,
    ) -> CompactionResult:
        """Run at most one tool-free L5 Fine-to-Macro aging epoch.

        The method deliberately has no durable cursor and never loops over
        multiple epochs.  Every retry revalidates the same raw epoch; a failed
        or ambiguous boundary leaves the previous Timeline untouched.
        """

        if not isinstance(transcript, Transcript):
            raise TypeError("transcript must be a Transcript")
        if not isinstance(timeline, Timeline) or timeline.session_id != transcript.session_id:
            raise ValueError("transcript and timeline must belong to the same Session")
        if not callable(summarize):
            raise TypeError("summarize must be callable")
        if cancellation is not None and not isinstance(cancellation, CancellationToken):
            raise TypeError("cancellation must be a CancellationToken or None")
        if isinstance(fine_budget, bool) or not isinstance(fine_budget, int) or fine_budget <= 0:
            raise ValueError("fine_budget must be a positive integer")
        owner = transcript.session_id if session_id is None else session_id
        if owner != transcript.session_id:
            raise ValueError("Timeline aging Session does not own the supplied Transcript")
        transcript = self.stable_transcript_for_compaction(
            transcript,
            active_turn_id=active_turn_id,
        )

        def record(
            *,
            status: str,
            failure: str | None,
            changed: bool,
            usage: int,
            epoch: TimelineAgingEpoch | None = None,
            attempt: int = 0,
        ) -> None:
            self._record_compaction(
                {
                    "level": "L5",
                    "status": status,
                    "changed": changed,
                    "failure": failure,
                    "fine_usage": usage,
                    "fine_budget": fine_budget,
                    "coverage_count": 0 if epoch is None else len(epoch.turn_ids),
                    "epoch_attempt": attempt,
                }
            )

        usage = fine_timeline_usage(timeline, self._compiler.token_estimator)
        if usage <= fine_budget:
            record(status="no_change", failure=None, changed=False, usage=usage)
            return CompactionResult(
                timeline=timeline,
                summary=timeline.summary or None,
                changed=False,
            )
        if cancellation is not None and cancellation.cancelled:
            record(status="failed", failure="compaction_cancelled", changed=False, usage=usage)
            return CompactionResult(
                timeline=timeline,
                summary=timeline.summary or None,
                changed=False,
                failure="compaction_cancelled",
            )

        lock = self._compactor._acquire_single_flight(owner)
        try:
            epoch = self._compactor.plan_timeline_aging_epoch(
                transcript,
                timeline=timeline,
                session_id=owner,
                input_budget=input_budget,
                output_reserve=output_reserve,
            )
            if epoch is None:
                record(status="failed", failure="no_safe_epoch", changed=False, usage=usage)
                return CompactionResult(
                    timeline=timeline,
                    summary=timeline.summary or None,
                    changed=False,
                    failure="no_safe_epoch",
                )

            candidate: CompactionResult | None = None
            failure = "repeated_failure"
            failure_attempt = 0
            for attempt in range(1, 3):
                failure_attempt = attempt
                if cancellation is not None and cancellation.cancelled:
                    raise CancelledError()
                try:
                    generated = summarize(epoch)
                    if inspect.isawaitable(generated):
                        generated = await generated
                    if cancellation is not None and cancellation.cancelled:
                        raise CancelledError()
                    parsed = self._compactor.parse_timeline_aging_result(
                        generated,
                        epoch=epoch,
                        summary_hard_cap=summary_hard_cap,
                    )
                    candidate = self._compactor.build_timeline_aging_candidate(
                        transcript,
                        epoch=epoch,
                        result=parsed,
                        timeline=timeline,
                    )
                    failure = ""
                    break
                except (GenerationCancelled, CancelledError):
                    raise
                except Exception:
                    failure = "repeated_failure" if attempt == 2 else "compaction_result_invalid"

            if candidate is None:
                record(
                    status="failed",
                    failure=failure,
                    changed=False,
                    usage=usage,
                    epoch=epoch,
                    attempt=failure_attempt,
                )
                return CompactionResult(
                    timeline=timeline,
                    summary=timeline.summary or None,
                    changed=False,
                    failure=failure,
                )

            non_reducing = self._non_reducing_result(candidate, timeline)
            if non_reducing is not None:
                record(
                    status="failed",
                    failure="no_reduction",
                    changed=False,
                    usage=usage,
                    epoch=epoch,
                    attempt=failure_attempt,
                )
                return non_reducing

            committed_result = candidate
            if commit is not None:
                try:
                    committed = commit(candidate)
                    if inspect.isawaitable(committed):
                        committed = await committed
                    if isinstance(committed, CompactionResult):
                        committed_result = committed
                        committed_ok = (
                            committed.changed
                            and committed.failure is None
                            and committed.timeline is not None
                        )
                    elif isinstance(committed, bool):
                        committed_ok = committed
                    else:
                        committed_ok = False
                except (GenerationCancelled, CancelledError):
                    raise
                except Exception:
                    committed_ok = False
                if not committed_ok:
                    record(
                        status="failed",
                        failure="timeline_commit_failed",
                        changed=False,
                        usage=usage,
                        epoch=epoch,
                    )
                    return CompactionResult(
                        timeline=timeline,
                        summary=timeline.summary or None,
                        changed=False,
                        failure="timeline_commit_failed",
                    )

            next_timeline = committed_result.timeline or candidate.timeline
            if next_timeline is None or len(next_timeline.records) <= len(timeline.records):
                record(
                    status="failed",
                    failure="no_progress",
                    changed=False,
                    usage=usage,
                    epoch=epoch,
                )
                return CompactionResult(
                    timeline=timeline,
                    summary=timeline.summary or None,
                    changed=False,
                    failure="no_progress",
                )
            result = replace(
                committed_result,
                timeline=next_timeline,
                changed=True,
                failure=None,
            )
            record(
                status="completed",
                failure=None,
                changed=True,
                usage=usage,
                epoch=epoch,
                attempt=failure_attempt,
            )
            return result
        finally:
            lock.release()

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
                "timeline_checkpoint_id": snapshot.timeline_checkpoint_id,
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
                # A resumed Session may already carry a durable Timeline
                # revision before this process performs a compaction.  Keep
                # the public count compatible with that durable fact while
                # still counting current-process attempts.
                "count": max(
                    self._compact_count,
                    (
                        1 if snapshot is not None and snapshot.timeline_checkpoint is not None else 0
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
        persists its Timeline.  A failed append must replace that provisional
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
        transcript: Transcript | None = None,
        instruction_loader: InstructionLoader | ProjectInstructionSource | None = None,
        runtime_context: RuntimePromptContext | None = None,
        timeline: Timeline | None = None,
        tool_definitions: Sequence[ToolDefinition] = (),
        environment_sources: Sequence[ContextBlock] = (),
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
        current_turn_id: str | None = None,
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
        if transcript is not None and not isinstance(transcript, Transcript):
            raise TypeError("transcript must be a Transcript or None")
        history_session_id = (
            session_id
            if session_id is not None
            else (
                timeline.session_id
                if timeline is not None
                else (
                    transcript.session_id
                    if transcript is not None
                    else f"run:{run_id}"
                )
            )
        )
        if timeline is not None and history_session_id != timeline.session_id:
            raise ValueError("session_id must match the supplied Timeline")
        if transcript is not None and history_session_id != transcript.session_id:
            raise ValueError("session_id must match the supplied Transcript")
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
        if current_turn_id is not None and (
            not isinstance(current_turn_id, str) or not current_turn_id
        ):
            raise ValueError("current_turn_id must be a non-empty string or None")
        reduction_levels = tuple(reduction_levels)
        if any(not isinstance(level, str) or not level for level in reduction_levels):
            raise ValueError("reduction_levels must contain non-empty strings")
        if context_budget is not None and (
            configured_input_limit is not None or provider_limits is not None
        ):
            raise TypeError("pass context_budget or individual limits, not both")
        if context_budget is None:
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
        process_transcript = _transcript_for_messages(history_session_id, history_messages)
        context_transcript = transcript
        if context_transcript is not None and current_turn_id is not None:
            # The active Turn is durably appended incrementally, but it must
            # remain the current conversation tail rather than become a
            # second history copy (or an optional budget candidate).
            context_transcript = self.stable_transcript_for_compaction(
                context_transcript,
                active_turn_id=current_turn_id,
            )
        merged_transcript = _merge_transcript(context_transcript, process_transcript)
        snapshot = self.compile(
            instruction_loader=instruction_loader,
            transcript=merged_transcript,
            timeline=timeline,
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
        instruction_change_reason = (
            instruction_loader.change_reason
            if isinstance(instruction_loader, (InstructionLoader, ProjectInstructionSource))
            else snapshot.prefix_change_reason
        )
        base_metadata: dict[str, object] = {
            "context_budget_tokens": snapshot.budget_tokens,
            "context_token_estimate": snapshot.token_estimate,
            "context_selected_block_ids": list(snapshot.selected_block_ids),
            "context_omitted_block_ids": list(snapshot.omitted_block_ids),
            "timeline_checkpoint_id": snapshot.timeline_checkpoint_id,
            "instruction_epoch": snapshot.instruction_epoch,
            "stable_prefix_fingerprint": snapshot.stable_prefix_fingerprint,
            "prefix_change_reason": instruction_change_reason,
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


def _transcript_for_messages(session_id: str, messages: Sequence[Message]) -> Transcript:
    transcript = Transcript(session_id)
    sequence = 1
    for index, message in enumerate(messages):
        turn_id = f"runtime-{index + 1}"
        entries = _transcript_entries_for_message(session_id, turn_id, sequence, message)
        for entry in entries:
            # These entries are a deterministic, process-local projection of
            # the messages supplied to request preparation.  Wall-clock
            # timestamps here would make an otherwise identical rebuild
            # Provider-visible only through diagnostics/block IDs, defeating
            # exact count -> rebuild -> re-gate verification.
            transcript = transcript.append(
                replace(entry, created_at=f"runtime:{entry.sequence:08d}")
            )
        sequence += len(entries)
    return transcript


def _merge_transcript(
    transcript: Transcript | None,
    process_transcript: Transcript,
) -> Transcript:
    """Join durable Transcript with this Run's ordered process-local delta.

    The two inputs are separate ownership domains: durable Transcript is the
    restored base, while ``process_transcript`` contains only this process's
    Run/Turn delta.  Its
    entries are always appended, including equal payloads, because message
    content cannot identify whether two same-text Turns are the same fact.
    """

    if transcript is None:
        return process_transcript
    if transcript.session_id != process_transcript.session_id:
        raise ValueError("Transcript and process messages belong to different Sessions")
    if not process_transcript.entries:
        return transcript
    if not transcript.entries:
        return process_transcript

    merged = transcript
    for entry in process_transcript.entries:
        merged = merged.append(
            replace(
                entry,
                session_id=merged.session_id,
                sequence=merged.last_sequence + 1,
            )
        )
    return merged


__all__ = ["ApplicationContextService"]
