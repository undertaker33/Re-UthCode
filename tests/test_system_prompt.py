from __future__ import annotations

import dataclasses

import pytest

from uthcode.core.prompt import (
    RuntimePromptContext,
    build_runtime_prompt_section,
)
from uthcode.core.planning import (
    BehaviorMode,
    PlanState,
    RuntimeFeedback,
    RuntimeFeedbackKind,
    TaskItem,
    TaskState,
    TaskStatus,
)


def test_runtime_prompt_context_renders_distinct_plan_and_default_behavior() -> None:
    default = build_runtime_prompt_section(
        RuntimePromptContext(behavior_mode=BehaviorMode.DEFAULT)
    ).content
    plan = build_runtime_prompt_section(
        RuntimePromptContext(behavior_mode=BehaviorMode.PLAN)
    ).content

    assert default != plan
    assert "DEFAULT" in default
    assert "实施" in default
    assert "TodoWrite" in default
    assert "简单任务无需" in default
    assert "未完成" in default
    assert "PLAN" in plan
    assert "只读" in plan
    assert "普通 final" in plan
    assert "直接完成" in plan
    assert "ProposePlan" in plan
    assert "获批后" in plan
    assert "同一 Turn" in plan
    assert "Todo 表" in plan
    assert "实施修改" in plan


def test_runtime_prompt_facts_include_task_plan_and_one_shot_feedback_without_messages() -> None:
    runtime_context = RuntimePromptContext(
        behavior_mode=BehaviorMode.DEFAULT,
        task_state=TaskState(
            (
                TaskItem("inspect <entry>", TaskStatus.COMPLETED),
                TaskItem("implement `change`", TaskStatus.IN_PROGRESS),
            )
        ),
        plan_state=PlanState(2, "Keep *one* runtime.", True),
        one_shot_feedback=RuntimeFeedback(
            RuntimeFeedbackKind.USER_STEERING,
            "Review the updated goal & next action.",
        ),
    )

    section = build_runtime_prompt_section(runtime_context)
    assert section.name == "当前行为与执行状态"
    assert "inspect \\<entry\\>" in section.content
    assert "implement \\`change\\`" in section.content
    assert "Keep \\*one\\* runtime." in section.content
    assert "Review the updated goal \\& next action." in section.content
    assert "role=user" not in section.content
    assert "role=tool" not in section.content
    assert "role=system" not in section.content


def test_runtime_prompt_context_is_frozen_and_rejects_broad_objects() -> None:
    context = RuntimePromptContext()
    assert context.behavior_mode is BehaviorMode.DEFAULT
    assert context.task_state == TaskState()
    assert context.plan_state is None
    assert context.one_shot_feedback is None

    with pytest.raises(dataclasses.FrozenInstanceError):
        context.behavior_mode = BehaviorMode.PLAN  # type: ignore[misc]
    with pytest.raises(TypeError):
        RuntimePromptContext(task_state={})  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        RuntimePromptContext(plan_state={})  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        RuntimePromptContext(one_shot_feedback={})  # type: ignore[arg-type]
