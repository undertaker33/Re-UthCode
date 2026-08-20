"""Pure, deterministic System Prompt semantics owned by UthCode Core."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar, Sequence

from uthcode.prompt_assets import read_public_coding_prompt

from .provider import ToolDefinition
from .planning import BehaviorMode, PlanState, RuntimeFeedback, TaskState


class ContextPlane(str, Enum):
    """The provider-independent plane to which a source may contribute."""

    INSTRUCTION = "instruction"
    CONVERSATION = "conversation"
    CONTEXTUAL = "contextual"


class ContextAuthority(str, Enum):
    """Authority used by Core policy, never a new Provider role."""

    PUBLIC_PROMPT = "public_prompt"
    CORE = "core"
    USER_INSTRUCTION = "user_instruction"
    PROJECT_INSTRUCTION = "project_instruction"
    DIRECTORY_INSTRUCTION = "directory_instruction"
    HISTORY = "history"
    TIMELINE = "timeline"
    RUNTIME = "runtime"
    ENVIRONMENT = "environment"
    TOOL_SYSTEM = "tool_system"


class ContextStability(str, Enum):
    """Whether a source may participate in a stable instruction prefix."""

    STABLE = "stable"
    DYNAMIC = "dynamic"


class ContextSourceKind(str, Enum):
    """Known source kinds and their ownership semantics."""

    PUBLIC_PROMPT = "public_prompt"
    CORE_CONTRACT = "core_contract"
    USER_INSTRUCTION = "user_instruction"
    PROJECT_INSTRUCTION = "project_instruction"
    DIRECTORY_INSTRUCTION = "directory_instruction"
    TIMELINE_ENTRY = "timeline_entry"
    TIMELINE_MACRO = "timeline_macro"
    USER_MESSAGE = "user_message"
    ASSISTANT_MESSAGE = "assistant_message"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    SUMMARY = "summary"
    RUNTIME_FACT = "runtime_fact"
    ENVIRONMENT_FACT = "environment_fact"
    TOOL_DEFINITION = "tool_definition"


class ContextScope(str, Enum):
    """Common scope labels; arbitrary normalized scope identifiers are allowed."""

    GLOBAL = "global"
    USER = "user"
    PROJECT = "project"
    DIRECTORY = "directory"
    SESSION = "session"
    TURN = "turn"


_INSTRUCTION_AUTHORITIES = frozenset(
    {
        ContextAuthority.PUBLIC_PROMPT,
        ContextAuthority.CORE,
        ContextAuthority.USER_INSTRUCTION,
        ContextAuthority.PROJECT_INSTRUCTION,
        ContextAuthority.DIRECTORY_INSTRUCTION,
    }
)
_SOURCE_AUTHORITY = {
    ContextSourceKind.PUBLIC_PROMPT: ContextAuthority.PUBLIC_PROMPT,
    ContextSourceKind.CORE_CONTRACT: ContextAuthority.CORE,
    ContextSourceKind.USER_INSTRUCTION: ContextAuthority.USER_INSTRUCTION,
    ContextSourceKind.PROJECT_INSTRUCTION: ContextAuthority.PROJECT_INSTRUCTION,
    ContextSourceKind.DIRECTORY_INSTRUCTION: ContextAuthority.DIRECTORY_INSTRUCTION,
    ContextSourceKind.TIMELINE_ENTRY: ContextAuthority.TIMELINE,
    ContextSourceKind.TIMELINE_MACRO: ContextAuthority.TIMELINE,
    ContextSourceKind.SUMMARY: ContextAuthority.TIMELINE,
    ContextSourceKind.USER_MESSAGE: ContextAuthority.HISTORY,
    ContextSourceKind.ASSISTANT_MESSAGE: ContextAuthority.HISTORY,
    ContextSourceKind.TOOL_CALL: ContextAuthority.HISTORY,
    ContextSourceKind.TOOL_RESULT: ContextAuthority.HISTORY,
    ContextSourceKind.RUNTIME_FACT: ContextAuthority.RUNTIME,
    ContextSourceKind.ENVIRONMENT_FACT: ContextAuthority.ENVIRONMENT,
    ContextSourceKind.TOOL_DEFINITION: ContextAuthority.TOOL_SYSTEM,
}


def _coerce_enum(value: object, enum_type: type[Enum], field_name: str) -> Enum:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)  # type: ignore[call-arg]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"unknown {field_name}: {value!r}") from exc


@dataclass(frozen=True, slots=True)
class ContextBlock:
    """A typed text source before provider-specific mapping.

    A block's authority is derived from its source kind and is checked here so
    ordinary history cannot promote itself by placing an instruction-looking
    label in its payload or metadata.
    """

    source_kind: ContextSourceKind | str
    authority: ContextAuthority | str
    stability: ContextStability | str
    scope: ContextScope | str
    provenance: str
    content: str
    estimated_tokens: int = 0
    semantic_unit_id: str | None = None
    plane: ContextPlane | str | None = None

    def __post_init__(self) -> None:
        source_kind = _coerce_enum(self.source_kind, ContextSourceKind, "source_kind")
        authority = _coerce_enum(self.authority, ContextAuthority, "authority")
        stability = _coerce_enum(self.stability, ContextStability, "stability")
        plane = (
            None
            if self.plane is None
            else _coerce_enum(self.plane, ContextPlane, "plane")
        )
        if not isinstance(self.scope, (ContextScope, str)) or not str(self.scope).strip():
            raise ValueError("scope must be a non-empty string")
        if not isinstance(self.provenance, str) or not self.provenance.strip():
            raise ValueError("provenance must be a non-empty string")
        if not isinstance(self.content, str):
            raise TypeError("content must be a string")
        if (
            isinstance(self.estimated_tokens, bool)
            or not isinstance(self.estimated_tokens, int)
            or self.estimated_tokens < 0
        ):
            raise ValueError("estimated_tokens must be a non-negative integer")
        if self.semantic_unit_id is not None and (
            not isinstance(self.semantic_unit_id, str) or not self.semantic_unit_id.strip()
        ):
            raise ValueError("semantic_unit_id must be a non-empty string or None")
        expected = _SOURCE_AUTHORITY[source_kind]
        if authority is not expected:
            raise ValueError(
                f"authority {authority.value!r} is not valid for source kind "
                f"{source_kind.value!r}; expected {expected.value!r}"
            )
        expected_plane = _plane_for_authority(authority)
        if plane is not None and plane is not expected_plane:
            raise ValueError(
                f"plane {plane.value!r} is not valid for authority {authority.value!r}"
            )
        object.__setattr__(self, "source_kind", source_kind)
        object.__setattr__(self, "authority", authority)
        object.__setattr__(self, "stability", stability)
        object.__setattr__(self, "plane", expected_plane)

    @property
    def is_instruction(self) -> bool:
        return self.authority in _INSTRUCTION_AUTHORITIES

    @property
    def is_history(self) -> bool:
        return self.plane is ContextPlane.CONVERSATION

    def to_dict(self) -> dict[str, object]:
        return {
            "source_kind": self.source_kind.value,
            "authority": self.authority.value,
            "stability": self.stability.value,
            "scope": self.scope.value if isinstance(self.scope, Enum) else self.scope,
            "provenance": self.provenance,
            "content": self.content,
            "estimated_tokens": self.estimated_tokens,
            "semantic_unit_id": self.semantic_unit_id,
            "plane": self.plane.value if self.plane is not None else None,
        }


def _plane_for_authority(authority: ContextAuthority) -> ContextPlane:
    if authority in _INSTRUCTION_AUTHORITIES:
        return ContextPlane.INSTRUCTION
    if authority in {
        ContextAuthority.HISTORY,
        ContextAuthority.TIMELINE,
    }:
        return ContextPlane.CONVERSATION
    return ContextPlane.CONTEXTUAL


@dataclass(frozen=True, slots=True)
class ToolDefinitionSource:
    """The Tool System's structured source; it is never text in a Prompt."""

    definitions: tuple[ToolDefinition, ...]
    estimated_tokens: int = 0
    provenance: str = "tool-system"
    schema_fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        definitions = tuple(self.definitions)
        if not all(isinstance(item, ToolDefinition) for item in definitions):
            raise TypeError("definitions must contain ToolDefinition values")
        names = [item.name for item in definitions]
        if len(names) != len(set(names)):
            raise ValueError("definitions must have unique names")
        if (
            isinstance(self.estimated_tokens, bool)
            or not isinstance(self.estimated_tokens, int)
            or self.estimated_tokens < 0
        ):
            raise ValueError("estimated_tokens must be a non-negative integer")
        estimated_tokens = self.estimated_tokens
        if estimated_tokens == 0 and definitions:
            estimated_tokens = estimate_tool_schema_tokens(definitions)
        if not isinstance(self.provenance, str) or not self.provenance.strip():
            raise ValueError("provenance must be a non-empty string")
        payload = json.dumps(
            [item.to_dict() for item in definitions],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        object.__setattr__(self, "definitions", definitions)
        object.__setattr__(self, "estimated_tokens", estimated_tokens)
        object.__setattr__(self, "schema_fingerprint", hashlib.sha256(payload).hexdigest())

    @property
    def source_kind(self) -> ContextSourceKind:
        return ContextSourceKind.TOOL_DEFINITION

    @property
    def authority(self) -> ContextAuthority:
        return ContextAuthority.TOOL_SYSTEM

    @property
    def plane(self) -> ContextPlane:
        return ContextPlane.CONTEXTUAL

    @property
    def tool_schema_fingerprint(self) -> str:
        return self.schema_fingerprint

    def to_dict(self) -> dict[str, object]:
        return {
            "source_kind": self.source_kind.value,
            "authority": self.authority.value,
            "definitions": [item.to_dict() for item in self.definitions],
            "estimated_tokens": self.estimated_tokens,
            "provenance": self.provenance,
            "schema_fingerprint": self.schema_fingerprint,
        }


def estimate_tool_schema_tokens(definitions: Sequence[ToolDefinition]) -> int:
    """Use a stable provider-independent estimate for a Tool schema."""

    payload = json.dumps(
        [item.to_dict() for item in definitions],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return max(1, (len(payload) + 3) // 4) if payload else 0


@dataclass(frozen=True, slots=True)
class StableInstructionPrefixEpoch:
    """Version and fingerprint of the ordered stable Instruction Plane."""

    value: int
    fingerprint: str
    reason: str = "initial"
    changed: bool = False

    def __post_init__(self) -> None:
        if isinstance(self.value, bool) or not isinstance(self.value, int) or self.value < 0:
            raise ValueError("epoch value must be a non-negative integer")
        if not isinstance(self.fingerprint, str) or not self.fingerprint.strip():
            raise ValueError("epoch fingerprint must be a non-empty string")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("epoch reason must be a non-empty string")
        if not isinstance(self.changed, bool):
            raise TypeError("epoch changed must be a boolean")

    @property
    def epoch(self) -> int:
        return self.value

    @property
    def instruction_epoch(self) -> int:
        return self.value


@dataclass(frozen=True, slots=True)
class InstructionPrefix:
    """Ordered stable blocks plus the epoch that names the prefix."""

    blocks: tuple[ContextBlock, ...]
    epoch: StableInstructionPrefixEpoch

    def __post_init__(self) -> None:
        blocks = tuple(self.blocks)
        if not all(isinstance(item, ContextBlock) and item.is_instruction for item in blocks):
            raise ValueError("InstructionPrefix accepts only Instruction Plane blocks")
        if not isinstance(self.epoch, StableInstructionPrefixEpoch):
            raise TypeError("epoch must be StableInstructionPrefixEpoch")
        object.__setattr__(self, "blocks", blocks)

    @property
    def instruction_epoch(self) -> int:
        return self.epoch.value

    @property
    def fingerprint(self) -> str:
        return self.epoch.fingerprint

    @property
    def content(self) -> str:
        return "\n\n".join(block.content for block in self.blocks if block.content.strip())

    def to_dict(self) -> dict[str, object]:
        return {
            "blocks": [block.to_dict() for block in self.blocks],
            "epoch": {
                "value": self.epoch.value,
                "fingerprint": self.epoch.fingerprint,
                "reason": self.epoch.reason,
                "changed": self.epoch.changed,
            },
        }


def instruction_prefix_fingerprint(blocks: Sequence[ContextBlock]) -> str:
    """Hash semantic prefix inputs, excluding dynamic Runtime facts."""

    payload = [
        {
            "source_kind": block.source_kind.value,
            "authority": block.authority.value,
            "stability": block.stability.value,
            "scope": block.scope.value if isinstance(block.scope, Enum) else block.scope,
            "provenance": block.provenance,
            "content": block.content,
        }
        for block in blocks
    ]
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def build_instruction_prefix(
    blocks: Sequence[ContextBlock],
    *,
    instruction_epoch: int = 0,
    reason: str = "initial",
    changed: bool = False,
) -> InstructionPrefix:
    """Validate and order the only sources allowed in the stable prefix."""

    values = tuple(blocks)
    if not all(isinstance(item, ContextBlock) for item in values):
        raise TypeError("blocks must contain ContextBlock values")
    if any(not item.is_instruction for item in values):
        raise ValueError("ordinary history and runtime facts cannot enter Instruction Plane")
    priority = {
        ContextSourceKind.PUBLIC_PROMPT: 0,
        ContextSourceKind.CORE_CONTRACT: 1,
        ContextSourceKind.USER_INSTRUCTION: 2,
        ContextSourceKind.PROJECT_INSTRUCTION: 3,
        ContextSourceKind.DIRECTORY_INSTRUCTION: 4,
    }
    ordered = tuple(
        item
        for _index, item in sorted(
            enumerate(values),
            key=lambda pair: (priority.get(pair[1].source_kind, 5), pair[0]),
        )
    )
    fingerprint = instruction_prefix_fingerprint(ordered)
    return InstructionPrefix(
        ordered,
        StableInstructionPrefixEpoch(
            value=instruction_epoch,
            fingerprint=fingerprint,
            reason=reason,
            changed=changed,
        ),
    )


def public_prompt_source() -> ContextBlock:
    return ContextBlock(
        source_kind=ContextSourceKind.PUBLIC_PROMPT,
        authority=ContextAuthority.PUBLIC_PROMPT,
        stability=ContextStability.STABLE,
        scope=ContextScope.GLOBAL,
        provenance="package:uthcode/prompt_assets/coding_agent.md",
        content=read_public_coding_prompt(),
    )


_CORE_RUNTIME_CONTRACT = (
    "Core 维护 provider-independent 的运行契约：只接受经过验证的 UthCode 数据，"
    "保持唯一状态写入者、严格结果配对和可观测事实；动态运行事实不改变稳定指令前缀。"
)


def core_runtime_contract_source() -> ContextBlock:
    """Return the non-editable Core contract as a typed Instruction source."""

    return ContextBlock(
        source_kind=ContextSourceKind.CORE_CONTRACT,
        authority=ContextAuthority.CORE,
        stability=ContextStability.STABLE,
        scope=ContextScope.GLOBAL,
        provenance="uthcode.core.prompt",
        content=_CORE_RUNTIME_CONTRACT,
    )


@dataclass(frozen=True, slots=True)
class _TextContextSource:
    """Small typed wrapper used by the named Context Source contracts."""

    block: ContextBlock
    expected_source_kind: ClassVar[ContextSourceKind]

    def __post_init__(self) -> None:
        if not isinstance(self.block, ContextBlock):
            raise TypeError("block must be a ContextBlock")
        if self.block.source_kind is not self.expected_source_kind:
            raise ValueError(
                f"{type(self).__name__} requires source kind "
                f"{self.expected_source_kind.value!r}"
            )

    @property
    def source_kind(self) -> ContextSourceKind:
        return self.block.source_kind

    @property
    def authority(self) -> ContextAuthority:
        return self.block.authority

    @property
    def plane(self) -> ContextPlane:
        return self.block.plane

    @property
    def stability(self) -> ContextStability:
        return self.block.stability

    @property
    def scope(self) -> ContextScope | str:
        return self.block.scope

    @property
    def provenance(self) -> str:
        return self.block.provenance

    @property
    def content(self) -> str:
        return self.block.content

    @property
    def estimated_tokens(self) -> int:
        return self.block.estimated_tokens

    @property
    def semantic_unit_id(self) -> str | None:
        return self.block.semantic_unit_id

    def to_context_block(self) -> ContextBlock:
        return self.block

    def to_dict(self) -> dict[str, object]:
        return self.block.to_dict()


@dataclass(frozen=True, slots=True)
class PromptAssetSource(_TextContextSource):
    """Public editable prompt asset source."""

    block: ContextBlock = field(default_factory=public_prompt_source)
    expected_source_kind: ClassVar[ContextSourceKind] = ContextSourceKind.PUBLIC_PROMPT


@dataclass(frozen=True, slots=True)
class CoreRuntimeContractSource(_TextContextSource):
    """Core-owned, non-editable runtime contract source."""

    block: ContextBlock = field(default_factory=core_runtime_contract_source)
    expected_source_kind: ClassVar[ContextSourceKind] = ContextSourceKind.CORE_CONTRACT


@dataclass(frozen=True, slots=True)
class TimelineSource(_TextContextSource):
    """Derived Timeline text that remains in the conversation plane."""

    expected_source_kind: ClassVar[ContextSourceKind] = ContextSourceKind.TIMELINE_ENTRY


@dataclass(frozen=True, slots=True)
class RuntimeStateSource(_TextContextSource):
    """Current runtime facts; never a stable instruction source."""

    expected_source_kind: ClassVar[ContextSourceKind] = ContextSourceKind.RUNTIME_FACT


@dataclass(frozen=True, slots=True)
class EnvironmentSource(_TextContextSource):
    """Environment facts kept in the contextual plane."""

    expected_source_kind: ClassVar[ContextSourceKind] = ContextSourceKind.ENVIRONMENT_FACT


@dataclass(frozen=True, slots=True)
class ProjectInstructionSource:
    """Application-produced ordered instruction set and epoch facts."""

    effective_instruction_set: tuple[ContextBlock, ...]
    instruction_epoch: int
    stable_prefix_fingerprint: str
    change_reason: str = "initial"

    def __post_init__(self) -> None:
        blocks = tuple(self.effective_instruction_set)
        if not all(
            isinstance(block, ContextBlock)
            and block.authority
            in {
                ContextAuthority.USER_INSTRUCTION,
                ContextAuthority.PROJECT_INSTRUCTION,
                ContextAuthority.DIRECTORY_INSTRUCTION,
            }
            for block in blocks
        ):
            raise ValueError(
                "ProjectInstructionSource accepts only user/project/directory blocks"
            )
        if (
            isinstance(self.instruction_epoch, bool)
            or not isinstance(self.instruction_epoch, int)
            or self.instruction_epoch < 0
        ):
            raise ValueError("instruction_epoch must be a non-negative integer")
        if not isinstance(self.stable_prefix_fingerprint, str):
            raise TypeError("stable_prefix_fingerprint must be a string")
        if not isinstance(self.change_reason, str) or not self.change_reason.strip():
            raise ValueError("change_reason must be a non-empty string")
        object.__setattr__(self, "effective_instruction_set", blocks)

    @property
    def blocks(self) -> tuple[ContextBlock, ...]:
        return self.effective_instruction_set

    @property
    def epoch(self) -> int:
        return self.instruction_epoch

    @property
    def fingerprint(self) -> str:
        return self.stable_prefix_fingerprint


def _require_text(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


@dataclass(frozen=True, slots=True)
class PromptSection:
    """An immutable, ordered unit of System Prompt content."""

    name: str
    priority: int
    content: str

    def __post_init__(self) -> None:
        _require_text(self.name, "name")
        if isinstance(self.priority, bool) or not isinstance(self.priority, int):
            raise TypeError("priority must be an integer")
        if not isinstance(self.content, str):
            raise TypeError("content must be a string")


@dataclass(frozen=True, slots=True)
class SystemPromptContext:
    """Explicit runtime values used by the Core System Prompt."""

    workdir: str
    platform_name: str
    platform_release: str
    current_date: str
    model_ref: str
    provider_protocol: str
    remote_model_id: str

    def __post_init__(self) -> None:
        for field_name in self.__dataclass_fields__:
            _require_text(getattr(self, field_name), field_name)


@dataclass(frozen=True, slots=True)
class RuntimePromptContext:
    """Only the current structured facts needed by runtime prompt semantics."""

    behavior_mode: BehaviorMode = BehaviorMode.DEFAULT
    task_state: TaskState = TaskState()
    plan_state: PlanState | None = None
    one_shot_feedback: RuntimeFeedback | None = None

    def __post_init__(self) -> None:
        mode = self.behavior_mode
        if not isinstance(mode, BehaviorMode):
            try:
                mode = BehaviorMode(mode)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"unknown behavior mode: {self.behavior_mode!r}") from exc
            object.__setattr__(self, "behavior_mode", mode)
        if not isinstance(self.task_state, TaskState):
            raise TypeError("task_state must be a TaskState")
        if self.plan_state is not None and not isinstance(self.plan_state, PlanState):
            raise TypeError("plan_state must be a PlanState or None")
        if self.one_shot_feedback is not None and not isinstance(
            self.one_shot_feedback,
            RuntimeFeedback,
        ):
            raise TypeError("one_shot_feedback must be a RuntimeFeedback or None")


def _escape_runtime_value(value: str) -> str:
    """Render a runtime value without allowing it to create Markdown structure."""

    replacements = {
        "\\": "\\\\",
        "\r": "\\r",
        "\n": "\\n",
        "\t": "\\t",
        "`": "\\`",
        "*": "\\*",
        "_": "\\_",
        "[": "\\[",
        "]": "\\]",
        "<": "\\<",
        ">": "\\>",
        "&": "\\&",
        "|": "\\|",
    }
    return "".join(replacements.get(character, character) for character in value)


def _render_sections(sections: Sequence[PromptSection]) -> str:
    rendered: list[str] = []
    for section in sorted(sections, key=lambda item: item.priority):
        content = section.content.strip()
        if not content:
            continue
        rendered.append(f"## {section.name}\n{content}")
    return "\n\n".join(rendered).rstrip()


def _public_prompt_sections() -> tuple[PromptSection, ...]:
    """Parse the versioned public asset without copying its prose into Core."""

    sections: list[PromptSection] = []
    current_name: str | None = None
    current_lines: list[str] = []
    priority = 0
    for line in read_public_coding_prompt().splitlines():
        if line.startswith("## "):
            if current_name is not None:
                sections.append(
                    PromptSection(current_name, priority, "\n".join(current_lines).strip())
                )
                priority += 10
            current_name = line[3:].strip()
            current_lines = []
            continue
        if current_name is None:
            if line.strip():
                current_name = "公共编码提示"
                current_lines = [line]
            continue
        current_lines.append(line)
    if current_name is not None:
        sections.append(
            PromptSection(current_name, priority, "\n".join(current_lines).strip())
        )
    if not sections:  # pragma: no cover - the asset loader already rejects empty text.
        raise RuntimeError("public coding prompt asset contains no sections")
    return tuple(sections)


def _instruction_prompt_sections(
    blocks: Sequence[ContextBlock],
) -> tuple[PromptSection, ...]:
    sections: list[PromptSection] = []
    for index, block in enumerate(blocks):
        if not isinstance(block, ContextBlock):
            raise TypeError("instruction_blocks must contain ContextBlock values")
        if not block.is_instruction:
            raise ValueError("only Instruction Plane blocks may be rendered as instructions")
        scope = block.scope.value if isinstance(block.scope, Enum) else block.scope
        sections.append(
            PromptSection(
                f"项目指令（{scope}）",
                45 + index,
                block.content,
            )
        )
    return tuple(sections)


def build_runtime_prompt_section(context: RuntimePromptContext) -> PromptSection:
    """Render Behavior, Task, Plan, and one-shot facts without fake messages."""

    if not isinstance(context, RuntimePromptContext):
        raise TypeError("context must be a RuntimePromptContext")

    if context.behavior_mode is BehaviorMode.PLAN:
        lines = [
            "- 当前行为模式：PLAN（规划模式）。",
            "- 只研究、澄清和设计；不得实施修改。可使用当前可见的只读工具探索事实，必要时使用 AskUserQuestion。",
            "- 普通只读问答、调查、解释、定位或只交付 Plan 文本时使用普通 final 直接完成，不进入 Plan Review。",
            "- 只有提交一份获批后要在同一 Turn 立即实施的完整方案时，才调用 ProposePlan；不得用普通 final 冒充正式提交。",
            "- 用户要求 REVISE 后，ProposePlan 必须提交完整替代版；revision 由 Core 计算，不得自行指定。",
            "- 不使用 Todo 表代替自然语言 Plan。",
        ]
    else:
        lines = [
            "- 当前行为模式：DEFAULT（实施模式）。",
            "- 简单任务无需强制创建 Todo；需要持续跟踪多步骤工作时使用 TodoWrite。",
            "- TaskState 是当前执行事实，应随真实进度更新；新事实或用户 Steering 可能要求整体重写。",
            "- 存在已批准 Plan 时以其为当前实施依据；实质改变批准范围前使用 AskUserQuestion。",
            "- 已知工作未完成时不得声明任务完成。",
        ]

    if context.task_state.is_empty:
        lines.append("- 当前 TaskState：空。")
    else:
        lines.append("- 当前 TaskState（保持顺序）：")
        lines.extend(
            f"  - [{item.status.value}] {_escape_runtime_value(item.content)}"
            for item in context.task_state.items
        )

    if context.plan_state is None:
        lines.append("- 当前 PlanState：空。")
    else:
        approval = "approved" if context.plan_state.approved else "awaiting_review"
        lines.extend(
            (
                f"- 当前 PlanState：revision={context.plan_state.revision}, {approval}。",
                f"- Plan 正文：{_escape_runtime_value(context.plan_state.text)}",
            )
        )

    if context.one_shot_feedback is not None:
        lines.extend(
            (
                f"- 一次性运行反馈类型：{context.one_shot_feedback.kind.value}。",
                f"- 一次性运行反馈：{_escape_runtime_value(context.one_shot_feedback.text)}",
            )
        )

    return PromptSection(
        name="当前行为与执行状态",
        priority=40,
        content="\n".join(lines),
    )


def build_system_prompt(
    context: SystemPromptContext,
    *,
    runtime_context: RuntimePromptContext | None = None,
    instruction_blocks: Sequence[ContextBlock] | None = None,
) -> str:
    """Build the asset-backed prompt plus Core and runtime-owned sections.

    ``instruction_blocks`` is intentionally limited to trusted Instruction
    Plane blocks.
    """

    if not isinstance(context, SystemPromptContext):
        raise TypeError("context must be a SystemPromptContext")
    if runtime_context is None:
        runtime_context = RuntimePromptContext()
    if not isinstance(runtime_context, RuntimePromptContext):
        raise TypeError("runtime_context must be a RuntimePromptContext or None")

    sections = (
        *_public_prompt_sections(),
        PromptSection(
            name="核心运行契约",
            priority=35,
            content=_CORE_RUNTIME_CONTRACT,
        ),
        *(
            _instruction_prompt_sections(instruction_blocks)
            if instruction_blocks is not None
            else ()
        ),
        build_runtime_prompt_section(runtime_context),
        PromptSection(
            name="当前运行环境",
            priority=100,
            content=(
                f"- 工作目录：{_escape_runtime_value(context.workdir)}\n"
                f"- 平台：{_escape_runtime_value(context.platform_name)} / "
                f"{_escape_runtime_value(context.platform_release)}\n"
                f"- 当前日期：{_escape_runtime_value(context.current_date)}\n"
                f"- 模型选择：{_escape_runtime_value(context.model_ref)}\n"
                f"- Provider 协议：{_escape_runtime_value(context.provider_protocol)}\n"
                f"- 远端模型：{_escape_runtime_value(context.remote_model_id)}"
            ),
        ),
    )
    return _render_sections(sections)


__all__ = [
    "CoreRuntimeContractSource",
    "ContextAuthority",
    "ContextBlock",
    "ContextPlane",
    "ContextScope",
    "ContextSourceKind",
    "ContextStability",
    "EnvironmentSource",
    "TimelineSource",
    "InstructionPrefix",
    "PromptSection",
    "PromptAssetSource",
    "ProjectInstructionSource",
    "RuntimePromptContext",
    "RuntimeStateSource",
    "StableInstructionPrefixEpoch",
    "SystemPromptContext",
    "ToolDefinitionSource",
    "build_instruction_prefix",
    "build_runtime_prompt_section",
    "build_system_prompt",
    "core_runtime_contract_source",
    "estimate_tool_schema_tokens",
    "instruction_prefix_fingerprint",
    "public_prompt_source",
]
