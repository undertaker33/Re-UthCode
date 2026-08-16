"""Provider-independent Context Compiler contracts.

The compiler in this module deliberately knows nothing about a Provider, a
filesystem, or a UI.  It turns the typed Context sources owned by Core and
Application into one deterministic, immutable snapshot.  The 258K value is an
UthCode operating budget; it is not a model-window discovery mechanism.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from .history import CanonicalHistory, Projection, SemanticUnit
from .prompt import (
    ContextAuthority,
    ContextBlock,
    ContextPlane,
    ContextScope,
    ContextSourceKind,
    ContextStability,
    CoreRuntimeContractSource,
    EnvironmentSource,
    HistoryProjectionSource,
    ProjectInstructionSource,
    PromptAssetSource,
    RuntimeStateSource,
    ToolDefinitionSource,
    build_instruction_prefix,
    core_runtime_contract_source,
    public_prompt_source,
)
from .provider import Message, ToolCallPart, ToolDefinition, ToolResultPart


UTHCODE_CONTEXT_BUDGET_TOKENS = 258_000
_MISSING = object()


class ContextCompilationError(ValueError):
    """A Context source or compiler input violates the Core contract."""


class TokenEstimator(Protocol):
    """Provider-independent token estimate port."""

    def estimate(self, text: str) -> int:
        """Return a deterministic non-negative estimate for ``text``."""


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

    def estimate(self, text: str) -> int:
        if not isinstance(text, str):
            raise TypeError("token estimator input must be a string")
        if not text:
            return 0
        return max(1, (len(text.encode("utf-8")) + self.bytes_per_token - 1) // self.bytes_per_token)


@dataclass(frozen=True, slots=True)
class ContextSourceBundle:
    """The complete provider-independent input to one compilation.

    The fields use the named W01 source contracts where a source has a
    dedicated value type.  ``ContextBlock`` values are accepted for the
    dynamic conversation/contextual sources so Core remains independent of
    Application orchestration.
    """

    instruction_sources: tuple[object, ...] = ()
    project_instruction_source: ProjectInstructionSource | None = None
    history: CanonicalHistory | None = None
    projection: Projection | None = None
    protected_context: tuple[object, ...] = ()
    protocol_blocks: tuple[object, ...] = ()
    current_turn: tuple[object, ...] = ()
    current_turn_deltas: tuple[object, ...] = ()
    runtime_sources: tuple[object, ...] = ()
    environment_sources: tuple[object, ...] = ()
    tool_source: ToolDefinitionSource | None = None

    def __post_init__(self) -> None:
        for name in (
            "instruction_sources",
            "protected_context",
            "protocol_blocks",
            "current_turn",
            "current_turn_deltas",
            "runtime_sources",
            "environment_sources",
        ):
            value = getattr(self, name)
            if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
                raise TypeError(f"{name} must be a sequence")
            object.__setattr__(self, name, tuple(value))
        if self.project_instruction_source is not None and not isinstance(
            self.project_instruction_source, ProjectInstructionSource
        ):
            raise TypeError("project_instruction_source must be ProjectInstructionSource or None")
        if self.history is not None and not isinstance(self.history, CanonicalHistory):
            raise TypeError("history must be CanonicalHistory or None")
        if self.projection is not None and not isinstance(self.projection, Projection):
            raise TypeError("projection must be Projection or None")
        if self.tool_source is not None and not isinstance(self.tool_source, ToolDefinitionSource):
            raise TypeError("tool_source must be ToolDefinitionSource or None")
        if self.history is not None and self.projection is not None:
            if self.history.session_id != self.projection.session_id:
                raise ContextCompilationError("history and projection belong to different sessions")


@dataclass(frozen=True, slots=True)
class ContextUsage:
    """Safe usage projection for later Application/UI consumers."""

    used_tokens: int
    budget_tokens: int = UTHCODE_CONTEXT_BUDGET_TOKENS
    available: bool = True

    def __post_init__(self) -> None:
        if isinstance(self.used_tokens, bool) or not isinstance(self.used_tokens, int) or self.used_tokens < 0:
            raise ValueError("used_tokens must be a non-negative integer")
        if self.budget_tokens != UTHCODE_CONTEXT_BUDGET_TOKENS:
            raise ValueError("Context usage must use the fixed 258K Operating Budget")
        if not isinstance(self.available, bool):
            raise TypeError("available must be a boolean")

    @property
    def ratio(self) -> float | None:
        if not self.available:
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

    budget_tokens: int
    token_estimate: int
    selected_blocks: tuple[ContextBlock, ...]
    omitted_blocks: tuple[ContextBlock, ...]
    omitted_reasons: tuple[tuple[str, str], ...]
    projection_revision: int | None
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
        if self.budget_tokens != UTHCODE_CONTEXT_BUDGET_TOKENS:
            raise ValueError("ContextSnapshot must use the fixed 258K Operating Budget")
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
    def budget(self) -> int:
        return self.budget_tokens

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
        return ContextUsage(self.token_estimate)

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
            "projection_revision": self.projection_revision,
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


class ContextCompiler:
    """Compile a deterministic Working Set under the fixed 258K budget."""

    def __init__(
        self,
        *,
        budget_tokens: int = UTHCODE_CONTEXT_BUDGET_TOKENS,
        token_estimator: TokenEstimator | Callable[[str], int] | None = None,
    ) -> None:
        if budget_tokens != UTHCODE_CONTEXT_BUDGET_TOKENS:
            raise ValueError("T09 Context Compiler uses the fixed 258K Operating Budget")
        self.budget_tokens = UTHCODE_CONTEXT_BUDGET_TOKENS
        self.token_estimator = token_estimator or DeterministicTokenEstimator()
        if not callable(getattr(self.token_estimator, "estimate", None)) and not callable(self.token_estimator):
            raise TypeError("token_estimator must be callable or provide estimate()")

    def compile(
        self,
        sources: ContextSourceBundle | None = None,
        *,
        previous_snapshot: ContextSnapshot | None = None,
        instruction_sources: Sequence[object] | object = _MISSING,
        project_instruction_source: ProjectInstructionSource | None | object = _MISSING,
        history: CanonicalHistory | None | object = _MISSING,
        projection: Projection | None | object = _MISSING,
        protected_context: Sequence[object] | object = _MISSING,
        protocol_blocks: Sequence[object] | object = _MISSING,
        current_turn: Sequence[object] | object = _MISSING,
        current_user: object = _MISSING,
        current_turn_deltas: Sequence[object] | object = _MISSING,
        runtime_sources: Sequence[object] | object = _MISSING,
        environment_sources: Sequence[object] | object = _MISSING,
        tool_source: ToolDefinitionSource | None | object = _MISSING,
    ) -> ContextSnapshot:
        individual_inputs = (
            instruction_sources,
            project_instruction_source,
            history,
            projection,
            protected_context,
            protocol_blocks,
            current_turn,
            current_user,
            current_turn_deltas,
            runtime_sources,
            environment_sources,
            tool_source,
        )
        if sources is not None and any(value is not _MISSING for value in individual_inputs):
            raise TypeError("pass ContextSourceBundle or individual compiler inputs, not both")
        if sources is None:
            normalized_instruction_sources = _sequence_or_single(
                None if instruction_sources is _MISSING else instruction_sources
            )
            normalized_current_turn = tuple(() if current_turn is _MISSING else current_turn)
            if current_user is not _MISSING and current_user is not None:
                normalized_current_turn = (*normalized_current_turn, current_user)
            sources = ContextSourceBundle(
                instruction_sources=normalized_instruction_sources,
                project_instruction_source=(
                    None if project_instruction_source is _MISSING else project_instruction_source
                ),
                history=None if history is _MISSING else history,
                projection=None if projection is _MISSING else projection,
                protected_context=tuple(() if protected_context is _MISSING else protected_context),
                protocol_blocks=tuple(() if protocol_blocks is _MISSING else protocol_blocks),
                current_turn=normalized_current_turn,
                current_turn_deltas=tuple(() if current_turn_deltas is _MISSING else current_turn_deltas),
                runtime_sources=tuple(() if runtime_sources is _MISSING else runtime_sources),
                environment_sources=tuple(() if environment_sources is _MISSING else environment_sources),
                tool_source=None if tool_source is _MISSING else tool_source,
            )
        elif not isinstance(sources, ContextSourceBundle):
            raise TypeError("sources must be ContextSourceBundle or None")
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
            if required or total + estimate <= self.budget_tokens:
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
        # snapshot keeps Projection/history before runtime facts and the
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

        if sources.history is not None:
            for unit in sources.history.semantic_units(include_incomplete=True):
                if not unit.complete:
                    add_selected(
                        _semantic_unit_block(unit),
                        required=True,
                        composition_key=(3, unit.sequence_start),
                    )

        if sources.projection is not None:
            add_selected(
                _projection_block(sources.projection),
                required=False,
                composition_key=(2, 0),
            )

        complete_units = () if sources.history is None else sources.history.complete_semantic_units()
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
            projection_revision=(sources.projection.revision if sources.projection is not None else None),
            instruction_epoch=instruction_epoch,
            stable_prefix_estimated_tokens=stable_prefix_estimated_tokens,
            stable_prefix_fingerprint=stable_fingerprint,
            prefix_changed=prefix_changed,
            prefix_change_reason=prefix_reason,
            tool_schema_fingerprint=tool_fingerprint,
            tool_schema_estimated_tokens=tool_tokens,
            tool_definitions=tool_definitions,
            over_budget=total > self.budget_tokens,
        )

    def _instruction_plane(
        self,
        sources: ContextSourceBundle,
    ) -> tuple[tuple[ContextBlock, ...], int, str]:
        values: list[ContextBlock] = []
        project = sources.project_instruction_source
        for raw in (*sources.instruction_sources, *( (project,) if project is not None else () )):
            if isinstance(raw, ProjectInstructionSource):
                project = raw
                values.extend(raw.blocks)
            elif isinstance(raw, (PromptAssetSource, CoreRuntimeContractSource)):
                values.append(raw.to_context_block())
            elif isinstance(raw, ContextBlock):
                values.append(raw)
            elif hasattr(raw, "to_context_block"):
                block = raw.to_context_block()
                if not isinstance(block, ContextBlock):
                    raise TypeError("instruction source to_context_block() must return ContextBlock")
                values.append(block)
            else:
                raise TypeError(f"unsupported instruction source: {type(raw).__name__}")
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
        estimator = self.token_estimator
        value = estimator.estimate(text) if hasattr(estimator, "estimate") else estimator(text)  # type: ignore[operator]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("token estimator must return a non-negative integer")
        return value


def _sequence_or_single(value: Sequence[object] | object | None) -> tuple[object, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes, bytearray)):
        return (value,)
    if isinstance(value, Sequence):
        return tuple(value)
    return (value,)


def _semantic_unit_block(unit: SemanticUnit) -> ContextBlock:
    return ContextBlock(
        source_kind=_unit_source_kind(unit),
        authority=ContextAuthority.HISTORY,
        stability=ContextStability.DYNAMIC,
        scope=ContextScope.TURN,
        provenance=f"history:unit:{unit.unit_id}",
        content=json.dumps(unit.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        semantic_unit_id=unit.unit_id,
    )


def _unit_source_kind(unit: SemanticUnit) -> ContextSourceKind:
    if any(entry.is_tool_result for entry in unit.entries):
        return ContextSourceKind.TOOL_RESULT
    if any(entry.is_tool_call for entry in unit.entries):
        return ContextSourceKind.TOOL_CALL
    first = unit.entries[0]
    if first.kind.value == "assistant_message":
        return ContextSourceKind.ASSISTANT_MESSAGE
    return ContextSourceKind.USER_MESSAGE


def _projection_block(projection: Projection) -> ContextBlock:
    return HistoryProjectionSource(
        ContextBlock(
            source_kind=ContextSourceKind.PROJECTION,
            authority=ContextAuthority.HISTORY_PROJECTION,
            stability=ContextStability.DYNAMIC,
            scope=ContextScope.SESSION,
            provenance=f"projection:{projection.revision}",
            content=projection.to_json(),
        )
    ).to_context_block()


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
    if isinstance(raw, (RuntimeStateSource, EnvironmentSource, HistoryProjectionSource)):
        return raw.to_context_block()
    raise TypeError(f"unsupported conversation/context source: {type(raw).__name__}")


__all__ = [
    "UTHCODE_CONTEXT_BUDGET_TOKENS",
    "ContextBlock",
    "ContextCompilationError",
    "ContextCompiler",
    "ContextSnapshot",
    "ContextSourceBundle",
    "ContextUsage",
    "DeterministicTokenEstimator",
    "TokenEstimator",
    "context_block_id",
]
