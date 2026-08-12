from __future__ import annotations

import gc
import warnings
from dataclasses import FrozenInstanceError, dataclass

import pytest

from uthcode.core.agent import AgentLoop, RunState, RunStatus
from uthcode.core.hooks import (
    BeforeCompletionBlock,
    BeforeCompletionContext,
    BeforeCompletionContinue,
    BeforeToolExecutionContext,
    BeforeToolExecutionContinue,
    BeforeToolExecutionReject,
    RuntimeHookReason,
    RuntimeHookSet,
    compose_runtime_hooks,
    create_default_runtime_hooks,
    plan_tool_policy,
    task_completion_hook,
)
from uthcode.core.permission import Effect, PermissionAction, ResourceScope
from uthcode.core.planning import (
    BehaviorMode,
    PlanState,
    RuntimeFeedbackKind,
    TaskItem,
    TaskState,
    TaskStatus,
)
from uthcode.core.provider import (
    CancellationToken,
    GenerationCompleted,
    GenerationRequest,
    JsonPayload,
    Message,
    ProviderIdentity,
    ProviderResponse,
    TextPart,
    ToolCallPart,
    ToolDefinition,
)
from uthcode.core.tool import PreparedToolCall, ToolExecutionResult, ToolExecutor, ToolRegistry


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


class _EqualitySensitiveHook:
    def __init__(self, result: object, *, raises: bool = False) -> None:
        self.result = result
        self.raises = raises
        self.calls = 0
        self.equality_calls = 0

    def __call__(self, context: object) -> object:
        del context
        self.calls += 1
        return self.result

    def __eq__(self, other: object) -> bool:
        del other
        self.equality_calls += 1
        if self.raises:
            raise RuntimeError("hook equality must not be inspected")
        return True


class _OneShotFinalProvider:
    @property
    def identity(self) -> ProviderIdentity:
        return ProviderIdentity("fake", "hook-test", "fake-model")

    async def stream(self, request: GenerationRequest, *, cancellation: CancellationToken):
        del request, cancellation
        yield GenerationCompleted(
            ProviderResponse(Message("assistant", (TextPart("done"),)))
        )


def test_compose_runtime_hooks_uses_identity_for_custom_hook_retention() -> None:
    custom = _EqualitySensitiveHook(BeforeToolExecutionContinue())

    composed = compose_runtime_hooks(
        RuntimeHookSet(before_tool_execution=(custom,))
    )

    assert len(composed.before_tool_execution) == 2
    assert composed.before_tool_execution[0] is plan_tool_policy
    assert composed.before_tool_execution[1] is custom
    assert isinstance(
        composed.run_before_tool_execution(_tool_context(BehaviorMode.DEFAULT, Effect.READ)),
        BeforeToolExecutionContinue,
    )
    assert custom.calls == 1
    assert custom.equality_calls == 0


@pytest.mark.asyncio
async def test_compose_runtime_hooks_does_not_inspect_raising_hook_equality() -> None:
    custom = _EqualitySensitiveHook(BeforeCompletionContinue(), raises=True)
    registry = ToolRegistry()
    loop = AgentLoop(
        _OneShotFinalProvider(),
        registry,
        ToolExecutor(registry),
        lambda messages, definitions, runtime_context: GenerationRequest(
            messages=messages,
            tools=definitions,
        ),
        runtime_hooks=RuntimeHookSet(before_completion=(custom,)),
    )

    execution = loop.start_turn(RunState.initial("run-1"), "work", turn_id="turn-1")
    segment = await execution.run_segment(pause_signal=CancellationToken())

    assert segment.terminal and segment.result is not None
    assert segment.result.status is RunStatus.COMPLETED
    assert custom.calls == 1
    assert custom.equality_calls == 0


def test_compose_runtime_hooks_deduplicates_exact_mandatory_functions() -> None:
    mandatory = create_default_runtime_hooks()
    composed = compose_runtime_hooks(mandatory)

    assert len(composed.before_tool_execution) == len(mandatory.before_tool_execution)
    assert len(composed.before_completion) == len(mandatory.before_completion)
    assert all(
        actual is expected
        for actual, expected in zip(
            composed.before_tool_execution,
            mandatory.before_tool_execution,
            strict=True,
        )
    )
    assert all(
        actual is expected
        for actual, expected in zip(
            composed.before_completion,
            mandatory.before_completion,
            strict=True,
        )
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


def test_runtime_hook_reason_enum_is_exact() -> None:
    assert [item.value for item in RuntimeHookReason] == [
        "plan_read_only",
        "unfinished_tasks",
    ]


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


def test_default_hook_set_keeps_plan_read_only_and_only_task_completion_gate() -> None:
    hook_set = create_default_runtime_hooks()

    assert hook_set.before_tool_execution == (plan_tool_policy,)
    assert hook_set.before_completion == (task_completion_hook,)

    plan_result = hook_set.run_before_completion(
        _completion_context(
            BehaviorMode.PLAN,
            task_state=TaskState((TaskItem("unfinished", TaskStatus.PENDING),)),
            plan_state=PlanState(1, "Old plan", False),
        )
    )
    assert isinstance(plan_result, BeforeCompletionContinue)


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


async def _async_tool_hook(
    context: BeforeToolExecutionContext,
) -> BeforeToolExecutionContinue:
    del context
    return BeforeToolExecutionContinue()


class _AsyncCompletionHook:
    async def __call__(
        self,
        context: BeforeCompletionContext,
    ) -> BeforeCompletionContinue:
        del context
        return BeforeCompletionContinue()


@pytest.mark.parametrize(
    "kwargs",
    (
        {"before_tool_execution": (_async_tool_hook,)},
        {"before_completion": (_AsyncCompletionHook(),)},
    ),
)
def test_hook_set_rejects_async_functions_and_async_callable_objects_at_construction(
    kwargs: dict[str, object],
) -> None:
    with pytest.raises(TypeError, match="synchronous"):
        RuntimeHookSet(**kwargs)  # type: ignore[arg-type]


def test_hook_set_closes_awaitables_returned_by_sync_looking_hooks() -> None:
    async def tool_result() -> BeforeToolExecutionContinue:
        return BeforeToolExecutionContinue()

    async def completion_result() -> BeforeCompletionContinue:
        return BeforeCompletionContinue()

    def deceptive_tool_hook(
        context: BeforeToolExecutionContext,
    ) -> object:
        del context
        return tool_result()

    def deceptive_completion_hook(
        context: BeforeCompletionContext,
    ) -> object:
        del context
        return completion_result()

    tool_hooks = RuntimeHookSet(before_tool_execution=(deceptive_tool_hook,))
    completion_hooks = RuntimeHookSet(before_completion=(deceptive_completion_hook,))

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with pytest.raises(TypeError, match="returned an awaitable"):
            tool_hooks.run_before_tool_execution(
                _tool_context(BehaviorMode.PLAN, Effect.READ)
            )
        with pytest.raises(TypeError, match="returned an awaitable"):
            completion_hooks.run_before_completion(
                _completion_context(BehaviorMode.DEFAULT)
            )
        gc.collect()

    assert not [item for item in caught if issubclass(item.category, RuntimeWarning)]


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
