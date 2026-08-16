"""Application composition for the provider-independent Context Compiler."""

from __future__ import annotations

from collections.abc import Sequence

from uthcode.core.context import (
    ContextCompiler,
    ContextSnapshot,
    ContextSourceBundle,
    ContextUsage,
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
from uthcode.core.provider import Message, ToolDefinition

from .instructions import InstructionLoader


class ApplicationContextService:
    """Assemble current Application sources without owning Context policy."""

    def __init__(self, compiler: ContextCompiler | None = None) -> None:
        self._compiler = compiler or ContextCompiler()
        self._last_snapshot: ContextSnapshot | None = None

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


__all__ = ["ApplicationContextService"]
