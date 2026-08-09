from __future__ import annotations

from dataclasses import FrozenInstanceError, dataclass

import pytest

from uthcode.core.hooks import (
    BeforeCompletionBlock,
    BeforeCompletionContext,
    BeforeCompletionContinue,
    BeforeCompletionRequestPause,
    BeforeToolExecutionContext,
    BeforeToolExecutionContinue,
    BeforeToolExecutionReject,
    RuntimeHookReason,
    RuntimeHookSet,
    create_default_runtime_hooks,
    plan_completion_hook,
    plan_tool_policy,
    task_completion_hook,
)
from uthcode.core.interaction import PauseKind, PauseReason, PlanReviewRequest
from uthcode.core.permission import Effect, PermissionAction, ResourceScope
from uthcode.core.planning import (
    BehaviorMode,
    PlanState,
    RuntimeFeedbackKind,
    TaskItem,
    TaskState,
    TaskStatus,
)
from uthcode.core.provider import CancellationToken, JsonPayload, ToolCallPart, ToolDefinition
from uthcode.core.tool import PreparedToolCall, ToolExecutionResult


@dataclass
class FakePreparedTool:
    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition("Fake", parameters={"type": "object"})

    async def execute(
        self,
        arguments: JsonPayload,
        *,
        cancellation: CancellationToken,
    ) -> ToolExecutionResult:
        del arguments, cancellation
        return ToolExecutionResult("unused")


def _prepared(effect: Effect) -> PreparedToolCall:
    call = ToolCallPart("call-1", "Fake", {})
    return PreparedToolCall(
        call=call,
        tool=FakePreparedTool(),
        action=PermissionAction(
            tool="Fake",
            action="execute",
            effect=effect,
            resource="project/item",
            scope=ResourceScope.INSIDE,
        ),
        execution_arguments=call.arguments,
    )


def _tool_context(mode: BehaviorMode, effect: Effect) -> BeforeToolExecutionContext:
    return BeforeToolExecutionContext("run-1", "turn-1", mode, _prepared(effect))


def _completion_context(
    mode: BehaviorMode,
    *,
    task_state: TaskState = TaskState(),
    plan_state: PlanState | None = None,
) -> BeforeCompletionContext:
    return BeforeCompletionContext(
        "run-1",
        "turn-1",
        mode,
        "Candidate final",
        task_state,
        plan_state,
    )


def test_plan_tool_policy_allows_default_and_plan_read_only() -> None:
    assert isinstance(
        plan_tool_policy(_tool_context(BehaviorMode.DEFAULT, Effect.WRITE)),
        BeforeToolExecutionContinue,
    )
    assert isinstance(
        plan_tool_policy(_tool_context(BehaviorMode.PLAN, Effect.READ)),
        BeforeToolExecutionContinue,
    )


@pytest.mark.parametrize(
    "effect",
    (Effect.WRITE, Effect.DESTRUCTIVE, Effect.EXTERNAL, Effect.UNKNOWN),
)
def test_plan_tool_policy_rejects_every_non_read_effect(effect: Effect) -> None:
    result = plan_tool_policy(_tool_context(BehaviorMode.PLAN, effect))

    assert isinstance(result, BeforeToolExecutionReject)
    assert result.reason is RuntimeHookReason.PLAN_READ_ONLY
    assert result.error_text.startswith("Error:")
    assert "project/item" not in result.error_text


def test_plan_completion_precedes_task_completion_in_default_hook_set() -> None:
    hook_set = create_default_runtime_hooks()

    assert hook_set.before_tool_execution == (plan_tool_policy,)
    assert hook_set.before_completion == (
        plan_completion_hook,
        task_completion_hook,
    )

    plan_result = hook_set.run_before_completion(
        _completion_context(
            BehaviorMode.PLAN,
            task_state=TaskState((TaskItem("unfinished", TaskStatus.PENDING),)),
            plan_state=PlanState(1, "Old plan", False),
        )
    )
    assert isinstance(plan_result, BeforeCompletionRequestPause)
    assert plan_result.kind is PauseKind.PLAN_REVIEW_REQUIRED
    assert plan_result.reason is PauseReason.PLAN_REVIEW_REQUIRED
    assert plan_result.request == PlanReviewRequest(2, "Candidate final")


def test_task_completion_blocks_only_default_with_unfinished_items() -> None:
    unfinished = TaskState(
        (
            TaskItem("done", TaskStatus.COMPLETED),
            TaskItem("next", TaskStatus.IN_PROGRESS),
        )
    )
    blocked = task_completion_hook(
        _completion_context(BehaviorMode.DEFAULT, task_state=unfinished)
    )

    assert isinstance(blocked, BeforeCompletionBlock)
    assert blocked.reason is RuntimeHookReason.UNFINISHED_TASKS
    assert blocked.feedback.kind is RuntimeFeedbackKind.COMPLETION_BLOCKED
    assert "next" not in blocked.feedback.text

    for context in (
        _completion_context(BehaviorMode.DEFAULT),
        _completion_context(
            BehaviorMode.DEFAULT,
            task_state=TaskState((TaskItem("done", TaskStatus.COMPLETED),)),
        ),
        _completion_context(BehaviorMode.PLAN, task_state=unfinished),
    ):
        assert isinstance(task_completion_hook(context), BeforeCompletionContinue)


def test_hook_set_runs_synchronously_in_order_and_short_circuits() -> None:
    calls: list[str] = []

    def first_tool(context: BeforeToolExecutionContext):
        calls.append(f"tool-1:{context.prepared_call.action.effect.value}")
        return BeforeToolExecutionContinue()

    def second_tool(context: BeforeToolExecutionContext):
        calls.append(f"tool-2:{context.prepared_call.action.effect.value}")
        return BeforeToolExecutionReject("Error: stopped", RuntimeHookReason.PLAN_READ_ONLY)

    def never_tool(context: BeforeToolExecutionContext):
        calls.append("never-tool")
        return BeforeToolExecutionContinue()

    def first_completion(context: BeforeCompletionContext):
        calls.append(f"completion-1:{context.candidate_text}")
        return BeforeCompletionContinue()

    hooks = RuntimeHookSet(
        before_tool_execution=(first_tool, second_tool, never_tool),
        before_completion=(first_completion,),
    )

    tool_result = hooks.run_before_tool_execution(
        _tool_context(BehaviorMode.DEFAULT, Effect.READ)
    )
    completion_result = hooks.run_before_completion(
        _completion_context(BehaviorMode.DEFAULT)
    )

    assert isinstance(tool_result, BeforeToolExecutionReject)
    assert isinstance(completion_result, BeforeCompletionContinue)
    assert calls == [
        "tool-1:read",
        "tool-2:read",
        "completion-1:Candidate final",
    ]


def test_hook_exceptions_propagate_for_the_caller_to_fail_closed() -> None:
    def broken(context: BeforeToolExecutionContext):
        del context
        raise RuntimeError("boom")

    hooks = RuntimeHookSet(before_tool_execution=(broken,))

    with pytest.raises(RuntimeError, match="boom"):
        hooks.run_before_tool_execution(_tool_context(BehaviorMode.PLAN, Effect.READ))


def test_hook_contract_values_are_frozen_and_strictly_typed() -> None:
    context = _completion_context(BehaviorMode.DEFAULT)
    result = BeforeCompletionContinue()

    with pytest.raises(FrozenInstanceError):
        context.candidate_text = "changed"  # type: ignore[misc]
    with pytest.raises((FrozenInstanceError, TypeError)):
        result.marker = True  # type: ignore[attr-defined]
    with pytest.raises(TypeError):
        RuntimeHookSet(before_completion=("not-callable",))  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        BeforeCompletionContext(
            "run",
            "turn",
            BehaviorMode.DEFAULT,
            "candidate",
            {},  # type: ignore[arg-type]
            None,
        )
