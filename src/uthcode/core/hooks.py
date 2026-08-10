"""Synchronous, immutable control hooks for two concrete lifecycle points."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Protocol, TypeAlias

from .interaction import PauseKind, PauseReason, PlanReviewRequest
from .permission import Effect
from .planning import (
    BehaviorMode,
    PlanState,
    RuntimeFeedback,
    RuntimeFeedbackKind,
    TaskState,
)
from .tool import PreparedToolCall


def _require_text(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _coerce_behavior_mode(value: object) -> BehaviorMode:
    if isinstance(value, BehaviorMode):
        return value
    try:
        return BehaviorMode(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"unknown behavior mode: {value!r}") from exc


class RuntimeHookReason(str, Enum):
    PLAN_READ_ONLY = "plan_read_only"
    UNFINISHED_TASKS = "unfinished_tasks"


@dataclass(frozen=True, slots=True)
class BeforeToolExecutionContext:
    run_id: str
    turn_id: str
    behavior_mode: BehaviorMode
    prepared_call: PreparedToolCall

    def __post_init__(self) -> None:
        _require_text(self.run_id, "run_id")
        _require_text(self.turn_id, "turn_id")
        object.__setattr__(
            self,
            "behavior_mode",
            _coerce_behavior_mode(self.behavior_mode),
        )
        if not isinstance(self.prepared_call, PreparedToolCall):
            raise TypeError("prepared_call must be a PreparedToolCall")


@dataclass(frozen=True, slots=True)
class BeforeToolExecutionContinue:
    pass


@dataclass(frozen=True, slots=True)
class BeforeToolExecutionReject:
    error_text: str
    reason: RuntimeHookReason

    def __post_init__(self) -> None:
        _require_text(self.error_text, "error_text")
        if not isinstance(self.reason, RuntimeHookReason):
            try:
                object.__setattr__(self, "reason", RuntimeHookReason(self.reason))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"unknown hook reason: {self.reason!r}") from exc


BeforeToolExecutionResult: TypeAlias = (
    BeforeToolExecutionContinue | BeforeToolExecutionReject
)


class BeforeToolExecutionHook(Protocol):
    def __call__(
        self,
        context: BeforeToolExecutionContext,
    ) -> BeforeToolExecutionResult:
        ...


@dataclass(frozen=True, slots=True)
class BeforeCompletionContext:
    run_id: str
    turn_id: str
    behavior_mode: BehaviorMode
    candidate_text: str
    task_state: TaskState
    plan_state: PlanState | None

    def __post_init__(self) -> None:
        _require_text(self.run_id, "run_id")
        _require_text(self.turn_id, "turn_id")
        object.__setattr__(
            self,
            "behavior_mode",
            _coerce_behavior_mode(self.behavior_mode),
        )
        if not isinstance(self.candidate_text, str):
            raise TypeError("candidate_text must be a string")
        if not isinstance(self.task_state, TaskState):
            raise TypeError("task_state must be a TaskState")
        if self.plan_state is not None and not isinstance(self.plan_state, PlanState):
            raise TypeError("plan_state must be a PlanState or None")


@dataclass(frozen=True, slots=True)
class BeforeCompletionContinue:
    pass


@dataclass(frozen=True, slots=True)
class BeforeCompletionBlock:
    feedback: RuntimeFeedback
    reason: RuntimeHookReason

    def __post_init__(self) -> None:
        if not isinstance(self.feedback, RuntimeFeedback):
            raise TypeError("feedback must be RuntimeFeedback")
        if not isinstance(self.reason, RuntimeHookReason):
            try:
                object.__setattr__(self, "reason", RuntimeHookReason(self.reason))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"unknown hook reason: {self.reason!r}") from exc


@dataclass(frozen=True, slots=True)
class BeforeCompletionRequestPause:
    kind: PauseKind
    request: PlanReviewRequest
    reason: PauseReason

    def __post_init__(self) -> None:
        if self.kind is not PauseKind.PLAN_REVIEW_REQUIRED:
            raise ValueError("completion pause kind must be plan_review_required")
        if not isinstance(self.request, PlanReviewRequest):
            raise TypeError("request must be a PlanReviewRequest")
        if self.reason is not PauseReason.PLAN_REVIEW_REQUIRED:
            raise ValueError("completion pause reason must be plan_review_required")


BeforeCompletionResult: TypeAlias = (
    BeforeCompletionContinue | BeforeCompletionBlock | BeforeCompletionRequestPause
)


class BeforeCompletionHook(Protocol):
    def __call__(self, context: BeforeCompletionContext) -> BeforeCompletionResult:
        ...


def _hook_tuple(value: object, field_name: str) -> tuple[Callable[..., object], ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise TypeError(f"{field_name} must be a sequence of callables")
    hooks = tuple(value)
    if not all(callable(hook) for hook in hooks):
        raise TypeError(f"{field_name} must contain only callables")
    if any(_is_async_callable(hook) for hook in hooks):
        raise TypeError(f"{field_name} must contain only synchronous callables")
    return hooks


def _is_async_callable(value: Callable[..., object]) -> bool:
    return inspect.iscoroutinefunction(value) or inspect.iscoroutinefunction(
        getattr(value, "__call__", None)
    )


def _call_sync_hook(
    hook: Callable[[object], object],
    context: object,
    field_name: str,
) -> object:
    result = hook(context)
    if inspect.isawaitable(result):
        close = getattr(result, "close", None)
        if callable(close):
            close()
        raise TypeError(f"{field_name} hook returned an awaitable")
    return result


@dataclass(frozen=True, slots=True)
class RuntimeHookSet:
    before_tool_execution: tuple[BeforeToolExecutionHook, ...] = ()
    before_completion: tuple[BeforeCompletionHook, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "before_tool_execution",
            _hook_tuple(self.before_tool_execution, "before_tool_execution"),
        )
        object.__setattr__(
            self,
            "before_completion",
            _hook_tuple(self.before_completion, "before_completion"),
        )

    def run_before_tool_execution(
        self,
        context: BeforeToolExecutionContext,
    ) -> BeforeToolExecutionResult:
        if not isinstance(context, BeforeToolExecutionContext):
            raise TypeError("context must be BeforeToolExecutionContext")
        for hook in self.before_tool_execution:
            result = _call_sync_hook(hook, context, "before_tool_execution")
            if not isinstance(
                result,
                (BeforeToolExecutionContinue, BeforeToolExecutionReject),
            ):
                raise TypeError("before_tool_execution hook returned an invalid result")
            if isinstance(result, BeforeToolExecutionReject):
                return result
        return BeforeToolExecutionContinue()

    def run_before_completion(
        self,
        context: BeforeCompletionContext,
    ) -> BeforeCompletionResult:
        if not isinstance(context, BeforeCompletionContext):
            raise TypeError("context must be BeforeCompletionContext")
        for hook in self.before_completion:
            result = _call_sync_hook(hook, context, "before_completion")
            if not isinstance(
                result,
                (
                    BeforeCompletionContinue,
                    BeforeCompletionBlock,
                    BeforeCompletionRequestPause,
                ),
            ):
                raise TypeError("before_completion hook returned an invalid result")
            if not isinstance(result, BeforeCompletionContinue):
                return result
        return BeforeCompletionContinue()


def plan_tool_policy(
    context: BeforeToolExecutionContext,
) -> BeforeToolExecutionResult:
    if (
        context.behavior_mode is BehaviorMode.PLAN
        and context.prepared_call.action.effect is not Effect.READ
    ):
        return BeforeToolExecutionReject(
            "Error: PLAN mode allows only trusted read actions",
            RuntimeHookReason.PLAN_READ_ONLY,
        )
    return BeforeToolExecutionContinue()


def plan_completion_hook(context: BeforeCompletionContext) -> BeforeCompletionResult:
    if context.behavior_mode is not BehaviorMode.PLAN:
        return BeforeCompletionContinue()
    revision = 1 if context.plan_state is None else context.plan_state.revision + 1
    return BeforeCompletionRequestPause(
        PauseKind.PLAN_REVIEW_REQUIRED,
        PlanReviewRequest(revision, context.candidate_text),
        PauseReason.PLAN_REVIEW_REQUIRED,
    )


def task_completion_hook(context: BeforeCompletionContext) -> BeforeCompletionResult:
    if (
        context.behavior_mode is BehaviorMode.DEFAULT
        and context.task_state.has_unfinished
    ):
        return BeforeCompletionBlock(
            RuntimeFeedback(
                RuntimeFeedbackKind.COMPLETION_BLOCKED,
                "Known execution tasks remain unfinished. Continue the work or replace "
                "the complete task state before submitting a final answer.",
            ),
            RuntimeHookReason.UNFINISHED_TASKS,
        )
    return BeforeCompletionContinue()


def create_default_runtime_hooks() -> RuntimeHookSet:
    """Build the one fixed production order for the two lifecycle points."""

    return RuntimeHookSet(
        before_tool_execution=(plan_tool_policy,),
        before_completion=(plan_completion_hook, task_completion_hook),
    )


__all__ = [
    "BeforeCompletionBlock",
    "BeforeCompletionContext",
    "BeforeCompletionContinue",
    "BeforeCompletionHook",
    "BeforeCompletionRequestPause",
    "BeforeCompletionResult",
    "BeforeToolExecutionContext",
    "BeforeToolExecutionContinue",
    "BeforeToolExecutionHook",
    "BeforeToolExecutionReject",
    "BeforeToolExecutionResult",
    "RuntimeHookReason",
    "RuntimeHookSet",
    "create_default_runtime_hooks",
    "plan_completion_hook",
    "plan_tool_policy",
    "task_completion_hook",
]
