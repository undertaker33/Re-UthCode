"""Application composition for the provider-independent Context Compiler."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from typing import Any

from uthcode.core.context import (
    CompactionResult,
    ContextCompactor,
    ContextCompiler,
    ContextSnapshot,
    ContextSourceBundle,
    ContextUsage,
    instruction_text_from_context_snapshot,
    messages_from_context_snapshot,
)
from uthcode.core.history import (
    CanonicalHistory,
    Projection,
    history_entries_from_message,
)
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
from uthcode.core.provider import GenerationRequest, Message, ToolDefinition
from uthcode.core.provider import CancellationToken

from .instructions import InstructionLoader


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
    ) -> ContextSnapshot:
        if instruction_loader is not None and not isinstance(instruction_loader, InstructionLoader):
            raise TypeError("instruction_loader must be InstructionLoader or None")
        if runtime_context is not None and not isinstance(runtime_context, RuntimePromptContext):
            raise TypeError("runtime_context must be RuntimePromptContext or None")
        ordinary_tools = tuple(tool_definitions)
        if not all(isinstance(item, ToolDefinition) for item in ordinary_tools):
            raise TypeError("tool_definitions must contain ToolDefinition values")

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
        snapshot = self._compiler.compile(
            bundle,
            previous_snapshot=(self._last_snapshot if previous_snapshot is None else previous_snapshot),
        )
        self._last_snapshot = snapshot
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
        previous_snapshot: ContextSnapshot | None = None,
    ) -> tuple[GenerationRequest, ContextSnapshot]:
        """Compile every runtime request through one fixed-budget Context path."""

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
        )
        conversation = messages_from_context_snapshot(snapshot)
        prompt = instruction_text_from_context_snapshot(snapshot)
        metadata: dict[str, object] = {
            "context_budget_tokens": snapshot.budget_tokens,
            "context_token_estimate": snapshot.token_estimate,
            "context_selected_block_ids": list(snapshot.selected_block_ids),
            "context_omitted_block_ids": list(snapshot.omitted_block_ids),
            "projection_revision": snapshot.projection_revision,
            "instruction_epoch": snapshot.instruction_epoch,
            "stable_prefix_fingerprint": snapshot.stable_prefix_fingerprint,
            "tool_schema_fingerprint": snapshot.tool_schema_fingerprint,
        }
        request = GenerationRequest(
            messages=conversation,
            system_prompt=prompt,
            model=model,
            tools=snapshot.tool_definitions,
            metadata=metadata,
        )
        return request, snapshot


def _history_for_messages(session_id: str, messages: Sequence[Message]) -> CanonicalHistory:
    history = CanonicalHistory(session_id)
    sequence = 1
    for index, message in enumerate(messages):
        turn_id = f"runtime-{index + 1}"
        entries = history_entries_from_message(session_id, turn_id, sequence, message)
        for entry in entries:
            payload: dict[str, Any] = dict(entry.payload)
            payload["message"] = message.to_dict()
            history = history.append(replace(entry, payload=payload))
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
