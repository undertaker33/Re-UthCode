"""Core Agent policy, immutable state, and explicit execution segments."""

from __future__ import annotations

from asyncio import CancelledError, sleep
import inspect
import json
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum

from .agent_events import (
    AgentEvent,
    AssistantMessageCompleted,
    AssistantMessageDelta,
    AssistantMessageKind,
    BehaviorModeChanged,
    CompletionBlocked,
    FailureReason,
    IterationStarted,
    PlanProposed,
    ReasoningDelta as AgentReasoningDelta,
    ReasoningFinished,
    ReasoningStarted,
    ToolBatchFinished,
    ToolBatchStarted,
    ToolFinished,
    ToolStarted,
    TaskStateChanged,
    TerminationReason,
    TurnPausing,
    UserInputRequested,
    TurnPaused,
    TurnCancelled,
    TurnCompleted,
    TurnFailed,
    TurnStarted,
    UsageUpdated,
    UserSteeringApplied,
    UserSteeringRequested,
)
from .provider import (
    CancellationToken,
    ContextOverflowError,
    AuthenticationError,
    FinishReason,
    GenerationCancelled,
    GenerationCompleted,
    GenerationRequest,
    InvalidProviderResponseError,
    Message,
    NetworkError,
    ProviderConfigurationError,
    ProviderError,
    ProviderPort,
    RateLimitError,
    ProviderTimeoutError,
    ReasoningDelta as ProviderReasoningDelta,
    ReasoningPart,
    TextDelta,
    TextPart,
    ToolCallPart,
    ToolDefinition,
    ToolResultPart,
    Usage,
    validated_provider_stream,
)
from .context import (
    ContextBudgetError,
    ContextCompilationError,
    ContextRequestSafetyError,
)
from .interaction import (
    ASK_USER_TOOL_DEFINITION,
    PauseKind,
    PauseReason,
    PauseRequest,
    PauseResponse,
    PlanReviewChoice,
    PlanReviewRequest,
    PlanReviewResponse,
    PermissionApprovalChoice,
    PermissionApprovalRequest,
    PermissionApprovalResponse,
    RetryProviderResponse,
    ResumeTurnResponse,
    SteeringRequest,
    UserInputRequest,
    UserInputResponse,
)
from .permission import Decision, Effect, PermissionAction, PermissionDecision
from .planning import (
    BehaviorMode,
    PlanState,
    PROPOSE_PLAN_TOOL_DEFINITION,
    RuntimeFeedback,
    RuntimeFeedbackKind,
    TODO_WRITE_TOOL_DEFINITION,
    TaskState,
    parse_propose_plan_arguments,
    parse_todo_write_arguments,
)
from .prompt import RuntimePromptContext
from .tool import (
    PreparedToolCall,
    ToolExecutor,
    ToolPlanningAccess,
    ToolRegistry,
    ToolResultMaterialization,
    ToolResultMaterializer,
)


AgentEventSink = Callable[[AgentEvent], None]
PermissionResolver = Callable[[PermissionAction], PermissionDecision]
SessionGrantSink = Callable[[PermissionAction], None]
OverflowHandler = Callable[[], bool | Awaitable[bool]]


_STEERING_FEEDBACK_TEXT = (
    "用户已更新当前任务要求；在继续执行前重新审查当前目标、已批准 Plan 与 "
    "TaskState，按需更新执行计划。"
)

_PLAN_READ_ONLY_ERROR = "Error: PLAN mode allows only trusted read actions"
_UNFINISHED_TASKS_FEEDBACK = (
    "Known execution tasks remain unfinished. Continue the work or replace "
    "the complete task state before submitting a final answer."
)


class _SegmentEventBuffer(list[AgentEvent]):
    """Temporary event buffer that emits only during one Core segment call."""

    __slots__ = ("sink",)

    def __init__(self, sink: AgentEventSink | None) -> None:
        super().__init__()
        self.sink = sink


def _require_text(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value:
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _require_non_negative_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be a non-negative integer")
    if value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return value


def _encode(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (Message, Usage)):
        return value.to_dict()
    if isinstance(value, tuple):
        return [_encode(item) for item in value]
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    raise TypeError(f"value of type {type(value).__name__} is not JSON-safe")


class AgentLoopConfigError(ValueError):
    """Invalid Agent policy configuration."""


class PersistenceUnavailableError(RuntimeError):
    """A stable Application fact that closed Turn state is not durable."""


class _ResponseRejected(ValueError):
    """A response did not match the current continuation facts."""


@dataclass(frozen=True, slots=True)
class AgentLoopConfig:
    """Business limits for one explicit Agent Loop."""

    max_iterations: int = 50
    max_tool_calls_per_iteration: int = 16
    max_consecutive_unknown_tools: int = 3

    def __post_init__(self) -> None:
        for field_name in (
            "max_iterations",
            "max_tool_calls_per_iteration",
            "max_consecutive_unknown_tools",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{field_name} must be a positive integer")
            if value <= 0:
                raise AgentLoopConfigError(f"{field_name} must be a positive integer")


class RunStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class RunState:
    """The authoritative immutable Core state for one Run/Turn."""

    run_id: str
    turn_id: str
    messages: tuple[Message, ...] = ()
    iteration_count: int = 0
    tool_call_count: int = 0
    consecutive_unknown_tools: int = 0
    usage: Usage = Usage()
    behavior_mode: BehaviorMode = BehaviorMode.DEFAULT
    task_state: TaskState = TaskState()
    plan_state: PlanState | None = None
    runtime_feedback: RuntimeFeedback | None = None
    status: RunStatus = RunStatus.RUNNING
    termination_reason: TerminationReason | None = None

    def __post_init__(self) -> None:
        _require_text(self.run_id, "run_id")
        _require_text(self.turn_id, "turn_id")
        if isinstance(self.messages, (str, bytes, bytearray)) or not isinstance(self.messages, Sequence):
            raise TypeError("messages must be a sequence")
        messages = tuple(self.messages)
        if not all(isinstance(message, Message) for message in messages):
            raise TypeError("messages must contain Message values")
        object.__setattr__(self, "messages", messages)
        for field_name in (
            "iteration_count",
            "tool_call_count",
            "consecutive_unknown_tools",
        ):
            _require_non_negative_int(getattr(self, field_name), field_name)
        if not isinstance(self.usage, Usage):
            raise TypeError("usage must be Usage")
        mode = self.behavior_mode
        if not isinstance(mode, BehaviorMode):
            try:
                mode = BehaviorMode(mode)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"unknown behavior mode: {self.behavior_mode!r}") from exc
            object.__setattr__(self, "behavior_mode", mode)
        if not isinstance(self.task_state, TaskState):
            raise TypeError("task_state must be TaskState")
        if self.plan_state is not None and not isinstance(self.plan_state, PlanState):
            raise TypeError("plan_state must be PlanState or None")
        if self.runtime_feedback is not None and not isinstance(
            self.runtime_feedback,
            RuntimeFeedback,
        ):
            raise TypeError("runtime_feedback must be RuntimeFeedback or None")
        status = self.status
        if not isinstance(status, RunStatus):
            try:
                status = RunStatus(status)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"unknown run status: {self.status!r}") from exc
            object.__setattr__(self, "status", status)
        reason = self.termination_reason
        if reason is not None and not isinstance(reason, TerminationReason):
            try:
                reason = TerminationReason(reason)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"unknown termination reason: {self.termination_reason!r}") from exc
            object.__setattr__(self, "termination_reason", reason)
        if status is RunStatus.RUNNING and reason is not None:
            raise ValueError("running state cannot have a termination reason")
        if status is not RunStatus.RUNNING and reason is None:
            raise ValueError("terminal state requires a termination reason")
        if status is RunStatus.COMPLETED and reason is not TerminationReason.FINAL_ANSWER:
            raise ValueError("completed state must use final_answer")
        if status is RunStatus.CANCELLED and reason is not TerminationReason.USER_CANCELLED:
            raise ValueError("cancelled state must use user_cancelled")

    @classmethod
    def initial(
        cls,
        run_id: str,
        *,
        turn_id: str = "initial",
        behavior_mode: BehaviorMode = BehaviorMode.DEFAULT,
    ) -> RunState:
        return cls(run_id=run_id, turn_id=turn_id, behavior_mode=behavior_mode)

    def new_turn(
        self,
        turn_id: str,
        user_input: str,
        *,
        behavior_mode: BehaviorMode | None = None,
    ) -> RunState:
        """Create the next immutable Turn while retaining the conversation."""

        _require_text(turn_id, "turn_id")
        if not isinstance(user_input, str) or not user_input.strip():
            raise ValueError("user_input must be a non-empty string")
        user_message = Message(role="user", parts=(TextPart(user_input),))
        next_mode = self.behavior_mode if behavior_mode is None else behavior_mode
        return RunState(
            run_id=self.run_id,
            turn_id=turn_id,
            messages=self.messages + (user_message,),
            behavior_mode=next_mode,
            task_state=TaskState(),
            plan_state=None,
            runtime_feedback=None,
            status=RunStatus.RUNNING,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "turn_id": self.turn_id,
            "messages": [message.to_dict() for message in self.messages],
            "iteration_count": self.iteration_count,
            "tool_call_count": self.tool_call_count,
            "consecutive_unknown_tools": self.consecutive_unknown_tools,
            "usage": self.usage.to_dict(),
            "behavior_mode": self.behavior_mode.value,
            "task_state": self.task_state.to_dict(),
            "plan_state": self.plan_state.to_dict() if self.plan_state is not None else None,
            "runtime_feedback": (
                self.runtime_feedback.to_dict()
                if self.runtime_feedback is not None
                else None
            ),
            "status": self.status.value,
            "termination_reason": (
                self.termination_reason.value if self.termination_reason is not None else None
            ),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> RunState:
        if not isinstance(value, Mapping):
            raise TypeError("RunState payload must be a mapping")
        return cls(
            run_id=value["run_id"],  # type: ignore[arg-type]
            turn_id=value["turn_id"],  # type: ignore[arg-type]
            messages=tuple(Message.from_dict(item) for item in value.get("messages", ())),  # type: ignore[arg-type]
            iteration_count=value.get("iteration_count", 0),  # type: ignore[arg-type]
            tool_call_count=value.get("tool_call_count", 0),  # type: ignore[arg-type]
            consecutive_unknown_tools=value.get("consecutive_unknown_tools", 0),  # type: ignore[arg-type]
            usage=Usage.from_dict(value.get("usage", {})),  # type: ignore[arg-type]
            behavior_mode=value.get("behavior_mode", BehaviorMode.DEFAULT),  # type: ignore[arg-type]
            task_state=TaskState.from_dict(value.get("task_state", {"items": []})),  # type: ignore[arg-type]
            plan_state=(
                PlanState.from_dict(value["plan_state"])  # type: ignore[arg-type]
                if value.get("plan_state") is not None
                else None
            ),
            runtime_feedback=(
                RuntimeFeedback.from_dict(value["runtime_feedback"])  # type: ignore[arg-type]
                if value.get("runtime_feedback") is not None
                else None
            ),
            status=value.get("status", RunStatus.RUNNING),  # type: ignore[arg-type]
            termination_reason=value.get("termination_reason"),  # type: ignore[arg-type]
        )

    @classmethod
    def from_json(cls, value: str) -> RunState:
        parsed = json.loads(value)
        if not isinstance(parsed, Mapping):
            raise TypeError("RunState JSON must contain an object")
        return cls.from_dict(parsed)


@dataclass(frozen=True, slots=True)
class RunSnapshot:
    """Safe state projection for callers that must not receive conversation."""

    run_id: str
    turn_id: str
    iteration_count: int
    tool_call_count: int
    consecutive_unknown_tools: int
    usage: Usage
    behavior_mode: BehaviorMode
    status: RunStatus
    termination_reason: TerminationReason | None

    def __post_init__(self) -> None:
        _require_text(self.run_id, "run_id")
        _require_text(self.turn_id, "turn_id")
        _require_non_negative_int(self.iteration_count, "iteration_count")
        _require_non_negative_int(self.tool_call_count, "tool_call_count")
        _require_non_negative_int(self.consecutive_unknown_tools, "consecutive_unknown_tools")
        if not isinstance(self.usage, Usage):
            raise TypeError("usage must be Usage")
        mode = self.behavior_mode
        if not isinstance(mode, BehaviorMode):
            try:
                mode = BehaviorMode(mode)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"unknown behavior mode: {self.behavior_mode!r}") from exc
            object.__setattr__(self, "behavior_mode", mode)
        status = self.status
        if not isinstance(status, RunStatus):
            try:
                status = RunStatus(status)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"unknown run status: {self.status!r}") from exc
            object.__setattr__(self, "status", status)
        reason = self.termination_reason
        if reason is not None and not isinstance(reason, TerminationReason):
            try:
                reason = TerminationReason(reason)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"unknown termination reason: {self.termination_reason!r}") from exc
            object.__setattr__(self, "termination_reason", reason)
        if status is RunStatus.RUNNING and reason is not None:
            raise ValueError("running snapshot cannot have a termination reason")
        if status is not RunStatus.RUNNING and reason is None:
            raise ValueError("terminal snapshot requires a termination reason")
        if status is RunStatus.COMPLETED and reason is not TerminationReason.FINAL_ANSWER:
            raise ValueError("completed snapshot must use final_answer")
        if status is RunStatus.CANCELLED and reason is not TerminationReason.USER_CANCELLED:
            raise ValueError("cancelled snapshot must use user_cancelled")

    @classmethod
    def from_state(cls, state: RunState) -> RunSnapshot:
        if not isinstance(state, RunState):
            raise TypeError("state must be RunState")
        return cls(
            run_id=state.run_id,
            turn_id=state.turn_id,
            iteration_count=state.iteration_count,
            tool_call_count=state.tool_call_count,
            consecutive_unknown_tools=state.consecutive_unknown_tools,
            usage=state.usage,
            behavior_mode=state.behavior_mode,
            status=state.status,
            termination_reason=state.termination_reason,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "turn_id": self.turn_id,
            "iteration_count": self.iteration_count,
            "tool_call_count": self.tool_call_count,
            "consecutive_unknown_tools": self.consecutive_unknown_tools,
            "usage": self.usage.to_dict(),
            "behavior_mode": self.behavior_mode.value,
            "status": self.status.value,
            "termination_reason": (
                self.termination_reason.value if self.termination_reason is not None else None
            ),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> RunSnapshot:
        if not isinstance(value, Mapping):
            raise TypeError("RunSnapshot payload must be a mapping")
        return cls(
            run_id=value["run_id"],  # type: ignore[arg-type]
            turn_id=value["turn_id"],  # type: ignore[arg-type]
            iteration_count=value.get("iteration_count", 0),  # type: ignore[arg-type]
            tool_call_count=value.get("tool_call_count", 0),  # type: ignore[arg-type]
            consecutive_unknown_tools=value.get("consecutive_unknown_tools", 0),  # type: ignore[arg-type]
            usage=Usage.from_dict(value.get("usage", {})),  # type: ignore[arg-type]
            behavior_mode=value.get("behavior_mode", BehaviorMode.DEFAULT),  # type: ignore[arg-type]
            status=value.get("status", RunStatus.RUNNING),  # type: ignore[arg-type]
            termination_reason=value.get("termination_reason"),  # type: ignore[arg-type]
        )

    @classmethod
    def from_json(cls, value: str) -> RunSnapshot:
        parsed = json.loads(value)
        if not isinstance(parsed, Mapping):
            raise TypeError("RunSnapshot JSON must contain an object")
        return cls.from_dict(parsed)


@dataclass(frozen=True, slots=True)
class TurnResult:
    """The stable, content-safe result of one terminal Turn."""

    run_id: str
    turn_id: str
    status: RunStatus
    termination_reason: TerminationReason
    final_text: str | None
    usage: Usage
    iteration_count: int
    tool_call_count: int
    failure_reason: FailureReason | None = None

    def __post_init__(self) -> None:
        _require_text(self.run_id, "run_id")
        _require_text(self.turn_id, "turn_id")
        status = self.status
        if not isinstance(status, RunStatus):
            try:
                status = RunStatus(status)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"unknown run status: {self.status!r}") from exc
            object.__setattr__(self, "status", status)
        if status is RunStatus.RUNNING:
            raise ValueError("TurnResult must be terminal")
        reason = self.termination_reason
        if not isinstance(reason, TerminationReason):
            try:
                reason = TerminationReason(reason)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"unknown termination reason: {self.termination_reason!r}") from exc
            object.__setattr__(self, "termination_reason", reason)
        if not isinstance(self.final_text, (str, type(None))):
            raise TypeError("final_text must be a string or None")
        if status is RunStatus.COMPLETED and self.final_text is None:
            raise ValueError("completed TurnResult requires final_text")
        if status is not RunStatus.COMPLETED and self.final_text is not None:
            raise ValueError("failed or cancelled TurnResult cannot contain final_text")
        if status is RunStatus.COMPLETED and reason is not TerminationReason.FINAL_ANSWER:
            raise ValueError("completed TurnResult must use final_answer")
        if status is RunStatus.CANCELLED and reason is not TerminationReason.USER_CANCELLED:
            raise ValueError("cancelled TurnResult must use user_cancelled")
        failure_reason = self.failure_reason
        if failure_reason is not None and not isinstance(failure_reason, FailureReason):
            try:
                failure_reason = FailureReason(failure_reason)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"unknown failure reason: {self.failure_reason!r}") from exc
            object.__setattr__(self, "failure_reason", failure_reason)
        if status is not RunStatus.FAILED and failure_reason is not None:
            raise ValueError("only failed TurnResult may contain a failure reason")
        if not isinstance(self.usage, Usage):
            raise TypeError("usage must be Usage")
        _require_non_negative_int(self.iteration_count, "iteration_count")
        _require_non_negative_int(self.tool_call_count, "tool_call_count")

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "turn_id": self.turn_id,
            "status": self.status.value,
            "termination_reason": self.termination_reason.value,
            "final_text": self.final_text,
            "usage": self.usage.to_dict(),
            "iteration_count": self.iteration_count,
            "tool_call_count": self.tool_call_count,
            "failure_reason": (
                self.failure_reason.value if self.failure_reason is not None else None
            ),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> TurnResult:
        if not isinstance(value, Mapping):
            raise TypeError("TurnResult payload must be a mapping")
        return cls(
            run_id=value["run_id"],  # type: ignore[arg-type]
            turn_id=value["turn_id"],  # type: ignore[arg-type]
            status=value["status"],  # type: ignore[arg-type]
            termination_reason=value["termination_reason"],  # type: ignore[arg-type]
            final_text=value.get("final_text"),  # type: ignore[arg-type]
            usage=Usage.from_dict(value.get("usage", {})),  # type: ignore[arg-type]
            iteration_count=value.get("iteration_count", 0),  # type: ignore[arg-type]
            tool_call_count=value.get("tool_call_count", 0),  # type: ignore[arg-type]
            failure_reason=value.get("failure_reason"),  # type: ignore[arg-type]
        )

    @classmethod
    def from_json(cls, value: str) -> TurnResult:
        parsed = json.loads(value)
        if not isinstance(parsed, Mapping):
            raise TypeError("TurnResult JSON must contain an object")
        return cls.from_dict(parsed)


def _failure_reason_for_exception(error: BaseException) -> FailureReason:
    """Map only stable Core/Application facts to the public failure enum."""

    if isinstance(error, AuthenticationError):
        return FailureReason.AUTHENTICATION
    if isinstance(error, ProviderConfigurationError):
        return FailureReason.PROVIDER_REQUEST
    if isinstance(error, InvalidProviderResponseError):
        return FailureReason.INVALID_PROVIDER_RESPONSE
    if isinstance(
        error,
        (
            ContextOverflowError,
            ContextBudgetError,
            ContextCompilationError,
            ContextRequestSafetyError,
        ),
    ):
        return FailureReason.CONTEXT_UNRESOLVABLE
    if isinstance(error, PersistenceUnavailableError):
        return FailureReason.PERSISTENCE_UNAVAILABLE
    return FailureReason.INTERNAL


RequestPreparer = Callable[
    [
        tuple[Message, ...],
        tuple[ToolDefinition, ...],
        RuntimePromptContext,
    ],
    GenerationRequest | Awaitable[GenerationRequest],
]
ToolCallDescriber = Callable[[ToolCallPart], str]


def _message_text(message: Message) -> str:
    return "".join(part.text for part in message.parts if isinstance(part, TextPart))


def _public_assistant_message(message: Message) -> Message:
    """Project a terminal assistant message to display-safe text parts."""

    return Message(
        role="assistant",
        parts=tuple(part for part in message.parts if isinstance(part, (TextPart, ReasoningPart))),
    )


def _merge_usage_details(previous: object, current: object) -> object:
    """Merge provider-independent Usage evidence across Provider iterations."""

    if isinstance(previous, Mapping) and isinstance(current, Mapping):
        merged: dict[object, object] = dict(previous.items())
        for key, value in current.items():
            if key in merged:
                merged[key] = _merge_usage_details(merged[key], value)
            else:
                merged[key] = value
        return merged
    if (
        isinstance(previous, (int, float))
        and not isinstance(previous, bool)
        and isinstance(current, (int, float))
        and not isinstance(current, bool)
    ):
        return previous + current
    return current


def _add_usage(previous: Usage, current: Usage) -> Usage:
    details = _merge_usage_details(previous.details, current.details)
    return Usage(
        input_tokens=previous.input_tokens + current.input_tokens,
        output_tokens=previous.output_tokens + current.output_tokens,
        total_tokens=previous.total_tokens + current.total_tokens,
        cache_read_tokens=previous.cache_read_tokens + current.cache_read_tokens,
        cache_write_tokens=previous.cache_write_tokens + current.cache_write_tokens,
        details=details,  # type: ignore[arg-type]
    )


def _validate_response(response: object) -> tuple[ToolCallPart, ...]:
    if not isinstance(response, GenerationCompleted):
        raise InvalidProviderResponseError("Provider terminal event has an invalid type")
    message = response.response.message
    if message.role != "assistant":
        raise InvalidProviderResponseError("Provider response message must have role assistant")
    if not all(isinstance(part, (TextPart, ReasoningPart, ToolCallPart)) for part in message.parts):
        raise InvalidProviderResponseError("Provider assistant message contains an invalid part")
    calls = tuple(part for part in message.parts if isinstance(part, ToolCallPart))
    call_ids = [call.tool_call_id for call in calls]
    if len(set(call_ids)) != len(call_ids):
        raise InvalidProviderResponseError("Provider response contains duplicate ToolCall IDs")
    finish_reason = response.response.finish_reason
    if finish_reason is FinishReason.STOP and not any(
        isinstance(part, TextPart) and bool(part.text)
        for part in message.parts
    ):
        raise InvalidProviderResponseError(
            "Provider STOP response must contain a non-empty formal TextPart"
        )
    if finish_reason is FinishReason.TOOL_CALLS and not calls:
        raise InvalidProviderResponseError("Provider marked tool calls without a ToolCall")
    if calls and finish_reason not in {
        FinishReason.TOOL_CALLS,
        FinishReason.LENGTH,
        FinishReason.INCOMPLETE,
    }:
        raise InvalidProviderResponseError("Provider ToolCall response has a contradictory finish reason")
    return calls


def _controlled_tool_result(call: ToolCallPart, reason: str) -> ToolResultPart:
    return ToolResultPart(
        tool_call_id=call.tool_call_id,
        content=reason,
        is_error=True,
    )


class ExecutionBoundary(str, Enum):
    PAUSED = "paused"
    TERMINAL = "terminal"


@dataclass(frozen=True, slots=True)
class _TurnContinuation:
    """Business facts needed to invoke the next Core segment."""

    stage: str
    iteration: int
    provider_retry_pending: bool
    assistant_tool_message: Message | None
    tool_calls: tuple[ToolCallPart, ...]
    completed_tool_results: tuple[ToolResultPart, ...]
    next_tool_index: int
    pending_pause: PauseRequest | None

    def __post_init__(self) -> None:
        if self.stage not in {"provider", "tool_batch"}:
            raise ValueError("continuation stage is invalid")
        if isinstance(self.iteration, bool) or not isinstance(self.iteration, int) or self.iteration <= 0:
            raise ValueError("continuation iteration is invalid")
        if not isinstance(self.provider_retry_pending, bool):
            raise TypeError("provider_retry_pending must be a boolean")
        if self.assistant_tool_message is not None:
            if not isinstance(self.assistant_tool_message, Message):
                raise TypeError("assistant_tool_message must be Message or None")
            if self.assistant_tool_message.role != "assistant":
                raise ValueError("assistant_tool_message must have assistant role")
        if not isinstance(self.tool_calls, tuple) or not all(
            isinstance(call, ToolCallPart) for call in self.tool_calls
        ):
            raise TypeError("tool_calls must contain ToolCallPart values")
        if not isinstance(self.completed_tool_results, tuple) or not all(
            isinstance(result, ToolResultPart) for result in self.completed_tool_results
        ):
            raise TypeError("completed_tool_results must contain ToolResultPart values")
        if isinstance(self.next_tool_index, bool) or not isinstance(self.next_tool_index, int):
            raise TypeError("next_tool_index must be an integer")
        if not 0 <= self.next_tool_index <= len(self.tool_calls):
            raise ValueError("next_tool_index is outside tool_calls")
        if len(self.completed_tool_results) != self.next_tool_index:
            raise ValueError("completed_tool_results must match next_tool_index")
        if self.stage == "tool_batch" and self.assistant_tool_message is None:
            raise ValueError("tool_batch continuation requires assistant_tool_message")
        if self.pending_pause is not None and not isinstance(self.pending_pause, PauseRequest):
            raise TypeError("pending_pause must be PauseRequest or None")


@dataclass(frozen=True, slots=True)
class AgentExecutionSegment:
    """The complete result of one Core execution segment."""

    events: tuple[AgentEvent, ...]
    state: RunState
    boundary: ExecutionBoundary
    continuation: object | None = None
    result: TurnResult | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.events, tuple) or not all(
            isinstance(event, AgentEvent) for event in self.events
        ):
            raise TypeError("events must contain AgentEvent values")
        if not isinstance(self.state, RunState):
            raise TypeError("state must be RunState")
        boundary = self.boundary
        if not isinstance(boundary, ExecutionBoundary):
            try:
                boundary = ExecutionBoundary(boundary)
            except (TypeError, ValueError) as exc:
                raise ValueError("unknown execution boundary") from exc
            object.__setattr__(self, "boundary", boundary)
        if boundary is ExecutionBoundary.PAUSED:
            if not isinstance(self.continuation, _TurnContinuation):
                raise TypeError("paused segment requires a Core continuation")
            if self.continuation.pending_pause is None:
                raise ValueError("paused segment requires pending pause facts")
            if self.result is not None:
                raise ValueError("paused segment cannot contain a terminal result")
        else:
            if self.continuation is not None:
                raise ValueError("terminal segment cannot contain continuation facts")
            if not isinstance(self.result, TurnResult):
                raise TypeError("terminal segment requires a terminal result")

    @property
    def paused(self) -> bool:
        return self.boundary is ExecutionBoundary.PAUSED

    @property
    def terminal(self) -> bool:
        return self.boundary is ExecutionBoundary.TERMINAL


class AgentLoop:
    """The single Provider-independent, sequential ReAct loop."""

    def __init__(
        self,
        provider: ProviderPort,
        tool_registry: ToolRegistry,
        tool_executor: ToolExecutor,
        request_preparer: RequestPreparer,
        *,
        config: AgentLoopConfig | None = None,
        tool_call_describer: ToolCallDescriber | None = None,
        permission_resolver: PermissionResolver | None = None,
        session_grant_sink: SessionGrantSink | None = None,
        result_materializer: ToolResultMaterializer | None = None,
        overflow_handler: OverflowHandler | None = None,
    ) -> None:
        if not isinstance(provider, ProviderPort):
            raise TypeError("provider must implement ProviderPort")
        if not isinstance(tool_registry, ToolRegistry):
            raise TypeError("tool_registry must be ToolRegistry")
        if not isinstance(tool_executor, ToolExecutor):
            raise TypeError("tool_executor must be ToolExecutor")
        if not callable(request_preparer):
            raise TypeError("request_preparer must be callable")
        if config is None:
            config = AgentLoopConfig()
        if not isinstance(config, AgentLoopConfig):
            raise TypeError("config must be AgentLoopConfig")
        if tool_call_describer is not None and not callable(tool_call_describer):
            raise TypeError("tool_call_describer must be callable or None")
        if permission_resolver is not None and not callable(permission_resolver):
            raise TypeError("permission_resolver must be callable or None")
        if session_grant_sink is not None and not callable(session_grant_sink):
            raise TypeError("session_grant_sink must be callable or None")
        if result_materializer is not None and not callable(result_materializer):
            raise TypeError("result_materializer must be callable or None")
        if overflow_handler is not None and not callable(overflow_handler):
            raise TypeError("overflow_handler must be callable or None")
        self._provider = provider
        self._tool_registry = tool_registry
        self._tool_executor = tool_executor
        self._request_preparer = request_preparer
        self._config = config
        self._tool_call_describer = tool_call_describer
        self._permission_resolver = permission_resolver
        self._session_grant_sink = session_grant_sink
        self._result_materializer = result_materializer
        self._overflow_handler = overflow_handler

    @property
    def config(self) -> AgentLoopConfig:
        return self._config

    def start_turn(
        self,
        state: RunState,
        user_input: str,
        *,
        turn_id: str | None = None,
        cancellation: CancellationToken | None = None,
        behavior_mode: BehaviorMode | None = None,
        tool_definitions: Sequence[ToolDefinition] | None = None,
    ) -> AgentTurnExecution:
        if not isinstance(state, RunState):
            raise TypeError("state must be RunState")
        if turn_id is None:
            turn_id = uuid.uuid4().hex
        if not isinstance(turn_id, str) or not turn_id:
            raise ValueError("turn_id must be a non-empty string")
        if cancellation is None:
            cancellation = CancellationToken()
        if not isinstance(cancellation, CancellationToken):
            raise TypeError("cancellation must be CancellationToken")
        if self._tool_registry.list_tools() and self._permission_resolver is None:
            raise RuntimeError(
                "permission resolver is required before starting an ordinary Tool turn"
            )
        if tool_definitions is None:
            definitions = self._tool_registry.definitions()
        else:
            if isinstance(tool_definitions, (str, bytes, bytearray)):
                raise TypeError("tool_definitions must be a sequence")
            definitions = tuple(tool_definitions)
            if not all(isinstance(definition, ToolDefinition) for definition in definitions):
                raise TypeError("tool_definitions must contain ToolDefinition values")
            names = [definition.name for definition in definitions]
            if len(set(names)) != len(names):
                raise ValueError("tool_definitions must have unique names")
        if behavior_mode is None:
            behavior_mode = state.behavior_mode
        elif not isinstance(behavior_mode, BehaviorMode):
            try:
                behavior_mode = BehaviorMode(behavior_mode)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"unknown behavior mode: {behavior_mode!r}") from exc
        turn_state = state.new_turn(
            turn_id,
            user_input,
            behavior_mode=behavior_mode,
        )
        return AgentTurnExecution(
            loop=self,
            state=turn_state,
            tool_definitions=definitions,
            cancellation=cancellation,
            permission_resolver=self._permission_resolver,
            session_grant_sink=self._session_grant_sink,
        )


class AgentTurnExecution:
    """One Core turn advanced explicitly from boundary to boundary."""

    __slots__ = (
        "_loop",
        "_state",
        "_tool_definitions",
        "_cancellation",
        "_terminal_result",
        "_started",
        "_user_message_id",
        "_batch_number",
        "_batch_id",
        "_batch_control_reason",
        "_active_segment_signal",
        "_active_pause_signal",
        "_active_event_buffer",
        "_continuation",
        "_permission_resolver",
        "_session_grant_sink",
        "_pending_prepared_call",
        "_pending_permission_choice",
        "_pending_steering",
        "_steering_requested_emitted",
        "_overflow_retry_used",
    )

    def __init__(
        self,
        *,
        loop: AgentLoop,
        state: RunState,
        tool_definitions: tuple[ToolDefinition, ...],
        cancellation: CancellationToken,
        permission_resolver: PermissionResolver | None = None,
        session_grant_sink: SessionGrantSink | None = None,
    ) -> None:
        self._loop = loop
        self._state = state
        self._tool_definitions = tuple(tool_definitions)
        self._cancellation = cancellation
        self._terminal_result: TurnResult | None = None
        self._started = False
        self._user_message_id = uuid.uuid4().hex
        self._batch_number = 0
        self._batch_id: str | None = None
        self._batch_control_reason: str | None = None
        self._active_segment_signal: CancellationToken | None = None
        self._active_pause_signal: CancellationToken | None = None
        self._active_event_buffer: list[AgentEvent] | None = None
        self._continuation: _TurnContinuation | None = None
        self._permission_resolver = permission_resolver
        self._session_grant_sink = session_grant_sink
        self._pending_prepared_call: PreparedToolCall | None = None
        self._pending_permission_choice: PermissionApprovalChoice | None = None
        self._pending_steering: SteeringRequest | None = None
        self._steering_requested_emitted = False
        self._overflow_retry_used = False

    @property
    def state(self) -> RunState:
        return self._state

    @property
    def cancellation(self) -> CancellationToken:
        return self._cancellation

    def snapshot(self) -> RunSnapshot:
        return RunSnapshot.from_state(self._state)

    @property
    def pending_steering(self) -> SteeringRequest | None:
        return self._pending_steering

    def request_steering(self, request: SteeringRequest) -> bool:
        """Queue one immutable same-Turn user update at the next safe boundary."""

        if not isinstance(request, SteeringRequest):
            raise TypeError("request must be a SteeringRequest")
        if request.run_id != self._state.run_id or request.turn_id != self._state.turn_id:
            raise ValueError("steering request IDs do not match the active Turn")
        if (
            self._terminal_result is not None
            or self._state.status is not RunStatus.RUNNING
            or self._cancellation.cancelled
        ):
            return False
        continuation = self._continuation
        if continuation is not None and continuation.pending_pause is not None:
            return False
        if self._pending_steering is not None:
            return False
        self._pending_steering = request
        self._steering_requested_emitted = False
        if self._active_event_buffer is not None:
            self._emit_steering_requested(self._active_event_buffer)
        if self._active_segment_signal is not None:
            self._active_segment_signal.cancel()
        return True

    def interrupt_for_pause(self) -> None:
        """Interrupt the active attempt so a requested safe pause can surface."""

        if self._active_pause_signal is not None:
            self._active_pause_signal.cancel()
        if self._active_segment_signal is not None:
            self._active_segment_signal.cancel()

    def apply_pause_response(
        self,
        response: PauseResponse,
        *,
        event_sink: AgentEventSink | None = None,
    ) -> tuple[AgentEvent, ...]:
        """Apply one typed response before Application publishes resume."""

        if not isinstance(
            response,
            (
                RetryProviderResponse,
                ResumeTurnResponse,
                UserInputResponse,
                PermissionApprovalResponse,
                PlanReviewResponse,
            ),
        ):
            raise TypeError("response must be a typed PauseResponse")
        if self._terminal_result is not None or self._cancellation.cancelled:
            raise ValueError("cancelled or terminal execution cannot apply a response")
        events: list[AgentEvent] = _SegmentEventBuffer(event_sink)
        self._apply_response(response, events)
        return tuple(events)

    def _visible_tool_definitions(self) -> tuple[ToolDefinition, ...]:
        """Return this iteration's mode-filtered view of the captured universe."""

        if self._state.behavior_mode is BehaviorMode.DEFAULT:
            return tuple(
                definition
                for definition in self._tool_definitions
                if definition.name != PROPOSE_PLAN_TOOL_DEFINITION.name
            )
        return tuple(
            definition
            for definition in self._tool_definitions
            if definition.name in {
                ASK_USER_TOOL_DEFINITION.name,
                PROPOSE_PLAN_TOOL_DEFINITION.name,
            }
            or self._loop._tool_registry.planning_access_for(definition.name)
            is ToolPlanningAccess.READ_ONLY
        )

    def cancel(self) -> bool:
        """Mark this turn cancelled and interrupt only the active attempt."""

        if self._terminal_result is not None:
            return False
        changed = self._cancellation.cancel()
        self._pending_steering = None
        self._steering_requested_emitted = False
        if self._active_segment_signal is not None:
            self._active_segment_signal.cancel()
        return changed

    def cancelled(self) -> bool:
        return self._cancellation.cancelled

    def fail_internal(self, *, event_sink: AgentEventSink | None = None) -> AgentExecutionSegment:
        """Close an execution after an Application driver failure.

        The driver uses this only when its call to ``run_segment`` itself
        fails unexpectedly.  The failure remains a Core terminal fact and
        exposes no exception details through the event or result payload.
        """

        if self._terminal_result is not None:
            return self._terminal_segment(())
        events: list[AgentEvent] = _SegmentEventBuffer(event_sink)
        return self._fail_segment(events, TerminationReason.INTERNAL_ERROR)

    def cancelled_segment(self, *, event_sink: AgentEventSink | None = None) -> AgentExecutionSegment:
        """Return the cancellation terminal used when a driver task is cancelled."""

        if self._terminal_result is not None:
            return self._terminal_segment(())
        self._cancellation.cancel()
        events: list[AgentEvent] = _SegmentEventBuffer(event_sink)
        return self._cancel_segment(events)

    async def run_segment(
        self,
        *,
        pause_signal: CancellationToken,
        response: PauseResponse | None = None,
        event_sink: AgentEventSink | None = None,
    ) -> AgentExecutionSegment:
        """Run until a paused or terminal boundary, then return all facts.

        A segment never waits for a response.  After this coroutine returns,
        the Core retains only immutable business state and continuation facts.
        """

        if not isinstance(pause_signal, CancellationToken):
            raise TypeError("pause_signal must be CancellationToken")
        if self._terminal_result is not None:
            if response is not None:
                raise ValueError("terminal execution does not accept a response")
            return self._terminal_segment(())

        events: list[AgentEvent] = _SegmentEventBuffer(event_sink)
        self._active_event_buffer = events
        self._active_pause_signal = pause_signal
        try:
            if not self._started:
                user_message = self._state.messages[-1]
                self._append(
                    events,
                    TurnStarted(
                        self._state.run_id,
                        self._state.turn_id,
                        self._user_message_id,
                        user_message,
                    ),
                )
                self._started = True

            if self._cancellation.cancelled:
                return self._cancel_segment(events)

            if self._continuation is not None:
                if self._continuation.pending_pause is None:
                    if response is not None:
                        raise _ResponseRejected("response does not match an active pause")
                elif response is None:
                    raise _ResponseRejected("a paused execution requires a typed response")
                else:
                    try:
                        self._apply_response(response, events)
                    except (TypeError, ValueError) as exc:
                        raise _ResponseRejected(str(exc)) from exc
            elif response is not None:
                raise _ResponseRejected("response does not match an active pause")

            while True:
                if self._cancellation.cancelled:
                    return self._cancel_segment(events)

                if (
                    self._pending_steering is not None
                    and (
                        self._continuation is None
                        or self._continuation.stage != "tool_batch"
                    )
                ):
                    self._apply_pending_steering(events)
                    continue

                continuation = self._continuation
                if continuation is not None and continuation.stage == "tool_batch":
                    batch_status = await self._run_tool_batch(events, pause_signal)
                    if batch_status == "paused":
                        return self._paused_segment(events)
                    if batch_status == "cancelled":
                        return self._cancel_segment(events)
                    if batch_status == "internal_error":
                        return self._fail_segment(events, TerminationReason.INTERNAL_ERROR)
                    if self._state.consecutive_unknown_tools >= self._loop.config.max_consecutive_unknown_tools:
                        return self._fail_segment(events, TerminationReason.CONSECUTIVE_UNKNOWN_TOOLS)
                    continue

                if continuation is not None:
                    iteration = continuation.iteration
                else:
                    iteration = self._state.iteration_count + 1
                if iteration > self._loop.config.max_iterations:
                    return self._fail_segment(events, TerminationReason.MAX_ITERATIONS)
                if self._state.iteration_count < iteration:
                    self._set_state(iteration_count=iteration)
                    self._append(
                        events,
                        IterationStarted(self._state.run_id, self._state.turn_id, iteration),
                    )

                if self._cancellation.cancelled:
                    return self._cancel_segment(events)
                if pause_signal.cancelled:
                    self._set_provider_continuation(iteration)
                    return self._pause_user_segment(events, iteration)

                try:
                    runtime_context = RuntimePromptContext(
                        behavior_mode=self._state.behavior_mode,
                        task_state=self._state.task_state,
                        plan_state=self._state.plan_state,
                        one_shot_feedback=self._state.runtime_feedback,
                    )
                    request_value = self._loop._request_preparer(
                        self._state.messages,
                        self._visible_tool_definitions(),
                        runtime_context,
                    )
                    request = (
                        await request_value
                        if inspect.isawaitable(request_value)
                        else request_value
                    )
                    if not isinstance(request, GenerationRequest):
                        raise TypeError("request_preparer must return GenerationRequest")
                except Exception as error:
                    return self._fail_segment(
                        events,
                        TerminationReason.INTERNAL_ERROR,
                        _failure_reason_for_exception(error),
                    )

                # A preparer may yield after pause/cancel was requested.  This
                # is the safe boundary before any Provider attempt exists.
                if self._cancellation.cancelled:
                    return self._cancel_segment(events)
                if self._pending_steering is not None:
                    self._apply_pending_steering(events)
                    continue
                if pause_signal.cancelled:
                    self._set_provider_continuation(iteration)
                    return self._pause_user_segment(events, iteration)

                # One-shot feedback belongs to the first real Provider
                # attempt. Prepared requests discarded at this boundary do
                # not consume it.
                if self._state.runtime_feedback is not None:
                    self._set_state(runtime_feedback=None)
                assistant_message_id = uuid.uuid4().hex
                self._continuation = None
                self._active_segment_signal = pause_signal
                try:
                    response_value, buffered_text_deltas = await self._consume_provider(
                        request,
                        iteration,
                        assistant_message_id,
                        pause_signal,
                        events,
                        buffer_assistant_text=(
                            self._state.behavior_mode is BehaviorMode.PLAN
                            or self._state.task_state.has_unfinished
                        ),
                    )
                except GenerationCancelled:
                    if self._cancellation.cancelled:
                        return self._cancel_segment(events)
                    if self._pending_steering is not None:
                        self._apply_pending_steering(events)
                        pause_signal = self._renew_pause_signal_after_steering()
                        continue
                    if pause_signal.cancelled:
                        self._set_provider_continuation(iteration)
                        return self._pause_user_segment(events, iteration)
                    return self._cancel_segment(events)
                except NetworkError:
                    if self._cancellation.cancelled:
                        return self._cancel_segment(events)
                    if self._pending_steering is not None:
                        self._apply_pending_steering(events)
                        pause_signal = self._renew_pause_signal_after_steering()
                        continue
                    if pause_signal.cancelled:
                        self._set_provider_continuation(iteration)
                        return self._pause_user_segment(events, iteration)
                    self._set_provider_continuation(iteration, provider_retry_pending=True)
                    return self._pause_provider_segment(events, iteration, PauseReason.NETWORK_ERROR)
                except ProviderTimeoutError:
                    if self._cancellation.cancelled:
                        return self._cancel_segment(events)
                    if self._pending_steering is not None:
                        self._apply_pending_steering(events)
                        pause_signal = self._renew_pause_signal_after_steering()
                        continue
                    if pause_signal.cancelled:
                        self._set_provider_continuation(iteration)
                        return self._pause_user_segment(events, iteration)
                    self._set_provider_continuation(iteration, provider_retry_pending=True)
                    return self._pause_provider_segment(events, iteration, PauseReason.TIMEOUT)
                except RateLimitError:
                    if self._cancellation.cancelled:
                        return self._cancel_segment(events)
                    if self._pending_steering is not None:
                        self._apply_pending_steering(events)
                        pause_signal = self._renew_pause_signal_after_steering()
                        continue
                    if pause_signal.cancelled:
                        self._set_provider_continuation(iteration)
                        return self._pause_user_segment(events, iteration)
                    self._set_provider_continuation(iteration, provider_retry_pending=True)
                    return self._pause_provider_segment(events, iteration, PauseReason.RATE_LIMITED)
                except InvalidProviderResponseError:
                    if self._pending_steering is not None:
                        self._apply_pending_steering(events)
                        pause_signal = self._renew_pause_signal_after_steering()
                        continue
                    return self._fail_segment(events, TerminationReason.INVALID_PROVIDER_RESPONSE)
                except ContextOverflowError:
                    if self._pending_steering is not None:
                        self._apply_pending_steering(events)
                        pause_signal = self._renew_pause_signal_after_steering()
                        continue
                    if self._overflow_retry_used or self._loop._overflow_handler is None:
                        return self._fail_segment(
                            events,
                            TerminationReason.PROVIDER_ERROR,
                            FailureReason.CONTEXT_UNRESOLVABLE,
                        )
                    self._overflow_retry_used = True
                    try:
                        retry_value = self._loop._overflow_handler()
                        can_retry = (
                            await retry_value
                            if inspect.isawaitable(retry_value)
                            else retry_value
                        )
                    except Exception:
                        can_retry = False
                    if not isinstance(can_retry, bool) or not can_retry:
                        return self._fail_segment(
                            events,
                            TerminationReason.PROVIDER_ERROR,
                            FailureReason.CONTEXT_UNRESOLVABLE,
                        )
                    self._continuation = None
                    continue
                except ProviderError as error:
                    if self._pending_steering is not None:
                        self._apply_pending_steering(events)
                        pause_signal = self._renew_pause_signal_after_steering()
                        continue
                    return self._fail_segment(
                        events,
                        TerminationReason.PROVIDER_ERROR,
                        _failure_reason_for_exception(error),
                    )
                except CancelledError:
                    self._cancellation.cancel()
                    return self._cancel_segment(events)
                except Exception:
                    return self._fail_segment(
                        events,
                        TerminationReason.INTERNAL_ERROR,
                        FailureReason.INTERNAL,
                    )
                finally:
                    if self._active_segment_signal is pause_signal:
                        self._active_segment_signal = None

                if self._cancellation.cancelled:
                    return self._cancel_segment(events)
                if self._pending_steering is not None:
                    self._record_usage(events, iteration, response_value.response.usage)
                    self._apply_pending_steering(events)
                    pause_signal = self._renew_pause_signal_after_steering()
                    continue
                if pause_signal.cancelled:
                    self._set_provider_continuation(iteration)
                    return self._pause_user_segment(events, iteration)

                try:
                    calls = _validate_response(response_value)
                except InvalidProviderResponseError:
                    return self._fail_segment(events, TerminationReason.INVALID_PROVIDER_RESPONSE)

                provider_response = response_value.response
                self._record_usage(events, iteration, provider_response.usage)

                finish_reason = provider_response.finish_reason
                if finish_reason is FinishReason.ERROR:
                    return self._fail_segment(
                        events,
                        TerminationReason.PROVIDER_ERROR,
                        FailureReason.INTERNAL,
                    )
                if finish_reason is FinishReason.CANCELLED:
                    return self._cancel_segment(events)
                if finish_reason is FinishReason.UNKNOWN:
                    return self._fail_segment(events, TerminationReason.INVALID_PROVIDER_RESPONSE)

                if finish_reason in {FinishReason.LENGTH, FinishReason.INCOMPLETE}:
                    kind = AssistantMessageKind.INCOMPLETE
                elif calls:
                    kind = AssistantMessageKind.PROGRESS
                else:
                    kind = AssistantMessageKind.FINAL

                if (
                    kind is AssistantMessageKind.FINAL
                    and self._state.behavior_mode is BehaviorMode.DEFAULT
                    and self._state.task_state.has_unfinished
                ):
                    self._set_state(
                        runtime_feedback=RuntimeFeedback(
                            RuntimeFeedbackKind.COMPLETION_BLOCKED,
                            _UNFINISHED_TASKS_FEEDBACK,
                        )
                    )
                    self._append(
                        events,
                        CompletionBlocked(
                            self._state.run_id,
                            self._state.turn_id,
                            iteration,
                            self._state.task_state.unfinished_count,
                        ),
                    )
                    self._continuation = None
                    continue

                for delta_text in buffered_text_deltas:
                    self._append(
                        events,
                        AssistantMessageDelta(
                            self._state.run_id,
                            self._state.turn_id,
                            assistant_message_id,
                            iteration,
                            delta_text,
                        ),
                    )
                self._set_state(messages=self._state.messages + (provider_response.message,))
                self._append(
                    events,
                    AssistantMessageCompleted(
                        self._state.run_id,
                        self._state.turn_id,
                        assistant_message_id,
                        iteration,
                        kind,
                        _public_assistant_message(provider_response.message),
                    ),
                )

                if self._cancellation.cancelled:
                    if calls:
                        self._begin_tool_batch(calls, iteration, provider_response.message, events)
                        self._batch_control_reason = "Error: tool call cancelled"
                        await self._run_tool_batch(events, pause_signal)
                    return self._cancel_segment(events)

                if kind is AssistantMessageKind.FINAL:
                    return self._complete_segment(events, _message_text(provider_response.message))

                if kind is AssistantMessageKind.INCOMPLETE:
                    if calls:
                        self._begin_tool_batch(calls, iteration, provider_response.message, events)
                        self._batch_control_reason = (
                            "Error: tool call not executed because provider response was incomplete"
                        )
                        batch_status = await self._run_tool_batch(events, pause_signal)
                        if batch_status == "cancelled":
                            return self._cancel_segment(events)
                    return self._fail_segment(events, TerminationReason.MAX_OUTPUT_TOKENS)

                if len(calls) > self._loop.config.max_tool_calls_per_iteration:
                    self._begin_tool_batch(calls, iteration, provider_response.message, events)
                    self._batch_control_reason = "Error: tool call limit exceeded"
                    batch_status = await self._run_tool_batch(events, pause_signal)
                    if batch_status == "cancelled":
                        return self._cancel_segment(events)
                    return self._fail_segment(events, TerminationReason.MAX_TOOL_CALLS)

                self._begin_tool_batch(calls, iteration, provider_response.message, events)
                batch_status = await self._run_tool_batch(events, pause_signal)
                if batch_status == "paused":
                    return self._paused_segment(events)
                if batch_status == "cancelled":
                    return self._cancel_segment(events)
                if batch_status == "internal_error":
                    return self._fail_segment(events, TerminationReason.INTERNAL_ERROR)
                if self._state.consecutive_unknown_tools >= self._loop.config.max_consecutive_unknown_tools:
                    return self._fail_segment(events, TerminationReason.CONSECUTIVE_UNKNOWN_TOOLS)
        except CancelledError:
            self._cancellation.cancel()
            return self._cancel_segment(events)
        except _ResponseRejected:
            raise
        except (TypeError, ValueError):
            if self._terminal_result is None:
                return self._fail_segment(events, TerminationReason.INTERNAL_ERROR)
            return self._terminal_segment(events)
        except Exception:
            if self._terminal_result is None:
                return self._fail_segment(events, TerminationReason.INTERNAL_ERROR)
            return self._terminal_segment(events)
        finally:
            if self._active_event_buffer is events:
                self._active_event_buffer = None
            self._active_pause_signal = None

    def _append(self, events: list[AgentEvent], event: AgentEvent) -> None:
        events.append(event)
        if isinstance(events, _SegmentEventBuffer) and events.sink is not None:
            events.sink(event)

    def _set_state(self, **changes: object) -> None:
        self._state = replace(self._state, **changes)

    def _emit_steering_requested(self, events: list[AgentEvent]) -> None:
        request = self._pending_steering
        if request is None or self._steering_requested_emitted:
            return
        self._append(
            events,
            UserSteeringRequested(
                self._state.run_id,
                self._state.turn_id,
                request.steering_id,
            ),
        )
        self._steering_requested_emitted = True

    def _apply_pending_steering(self, events: list[AgentEvent]) -> bool:
        if self._cancellation.cancelled:
            self._pending_steering = None
            self._steering_requested_emitted = False
            return False
        request = self._pending_steering
        if request is None:
            return False
        self._emit_steering_requested(events)
        self._set_state(
            messages=self._state.messages
            + (Message(role="user", parts=(TextPart(request.text),)),),
            runtime_feedback=RuntimeFeedback(
                RuntimeFeedbackKind.USER_STEERING,
                _STEERING_FEEDBACK_TEXT,
            ),
        )
        self._append(
            events,
            UserSteeringApplied(
                self._state.run_id,
                self._state.turn_id,
                request.steering_id,
            ),
        )
        self._pending_steering = None
        self._steering_requested_emitted = False
        self._continuation = None
        return True

    def _record_usage(
        self,
        events: list[AgentEvent],
        iteration: int,
        usage: Usage,
    ) -> None:
        self._set_state(usage=_add_usage(self._state.usage, usage))
        self._append(
            events,
            UsageUpdated(
                self._state.run_id,
                self._state.turn_id,
                iteration,
                self._state.usage,
            ),
        )

    def _renew_pause_signal_after_steering(self) -> CancellationToken:
        self._active_segment_signal = None
        signal = CancellationToken()
        self._active_pause_signal = signal
        return signal

    def _set_provider_continuation(
        self,
        iteration: int,
        *,
        provider_retry_pending: bool = False,
    ) -> None:
        self._continuation = _TurnContinuation(
            stage="provider",
            iteration=iteration,
            provider_retry_pending=provider_retry_pending,
            assistant_tool_message=None,
            tool_calls=(),
            completed_tool_results=(),
            next_tool_index=0,
            pending_pause=None,
        )
    def _make_pause(
        self,
        *,
        iteration: int,
        kind: PauseKind,
        reason: PauseReason,
        tool_call_id: str | None = None,
        user_input_request: UserInputRequest | None = None,
        permission_request: PermissionApprovalRequest | None = None,
        plan_review_request: PlanReviewRequest | None = None,
    ) -> PauseRequest:
        return PauseRequest(
            pause_id=uuid.uuid4().hex,
            run_id=self._state.run_id,
            turn_id=self._state.turn_id,
            kind=kind,
            reason=reason,
            iteration=iteration,
            created_at=datetime.now(timezone.utc).isoformat(),
            tool_call_id=tool_call_id,
            user_input_request=user_input_request,
            permission_request=permission_request,
            plan_review_request=plan_review_request,
        )

    def _pause_user_segment(self, events: list[AgentEvent], iteration: int) -> AgentExecutionSegment:
        pause = self._make_pause(
            iteration=iteration,
            kind=PauseKind.USER_REQUESTED,
            reason=PauseReason.USER_REQUESTED,
        )
        assert self._continuation is not None
        self._continuation = replace(self._continuation, pending_pause=pause)
        self._append(
            events,
            TurnPausing(
                self._state.run_id,
                self._state.turn_id,
                pause.pause_id,
                pause.kind,
                pause.reason,
                pause.iteration,
            ),
        )
        self._append(events, TurnPaused(self._state.run_id, self._state.turn_id, pause))
        return self._paused_segment(events)

    def _pause_provider_segment(
        self,
        events: list[AgentEvent],
        iteration: int,
        reason: PauseReason,
    ) -> AgentExecutionSegment:
        pause = self._make_pause(
            iteration=iteration,
            kind=PauseKind.PROVIDER_UNAVAILABLE,
            reason=reason,
        )
        assert self._continuation is not None
        self._continuation = replace(self._continuation, pending_pause=pause)
        self._append(events, TurnPaused(self._state.run_id, self._state.turn_id, pause))
        return self._paused_segment(events)

    def _pause_input_segment(
        self,
        events: list[AgentEvent],
        iteration: int,
        call: ToolCallPart,
        request: UserInputRequest,
    ) -> AgentExecutionSegment:
        pause = self._make_pause(
            iteration=iteration,
            kind=PauseKind.USER_INPUT_REQUIRED,
            reason=PauseReason.USER_INPUT_REQUIRED,
            tool_call_id=call.tool_call_id,
            user_input_request=request,
        )
        assert self._continuation is not None
        self._continuation = replace(self._continuation, pending_pause=pause)
        self._append(
            events,
            UserInputRequested(
                self._state.run_id,
                self._state.turn_id,
                pause.pause_id,
                call.tool_call_id,
                request,
            ),
        )
        self._append(events, TurnPaused(self._state.run_id, self._state.turn_id, pause))
        return self._paused_segment(events)

    def _pause_permission_segment(
        self,
        events: list[AgentEvent],
        iteration: int,
        call: ToolCallPart,
        decision: PermissionDecision,
    ) -> AgentExecutionSegment:
        permission_request = PermissionApprovalRequest.from_decision(
            decision,
            permission_id=uuid.uuid4().hex,
            run_id=self._state.run_id,
            turn_id=self._state.turn_id,
            tool_call_id=call.tool_call_id,
        )
        pause = self._make_pause(
            iteration=iteration,
            kind=PauseKind.PERMISSION_REQUIRED,
            reason=PauseReason.PERMISSION_REQUIRED,
            tool_call_id=call.tool_call_id,
            permission_request=permission_request,
        )
        assert self._continuation is not None
        self._continuation = replace(self._continuation, pending_pause=pause)
        self._append(events, TurnPaused(self._state.run_id, self._state.turn_id, pause))
        return self._paused_segment(events)

    def _pause_plan_review_segment(
        self,
        events: list[AgentEvent],
        iteration: int,
        request: PlanReviewRequest,
    ) -> AgentExecutionSegment:
        pause = self._make_pause(
            iteration=iteration,
            kind=PauseKind.PLAN_REVIEW_REQUIRED,
            reason=PauseReason.PLAN_REVIEW_REQUIRED,
            plan_review_request=request,
        )
        if self._continuation is None:
            raise RuntimeError("Plan review pause has no Tool continuation")
        self._continuation = replace(self._continuation, pending_pause=pause)
        self._append(events, TurnPaused(self._state.run_id, self._state.turn_id, pause))
        return self._paused_segment(events)

    def _apply_response(self, response: PauseResponse, events: list[AgentEvent]) -> None:
        continuation = self._continuation
        if continuation is None or continuation.pending_pause is None:
            raise ValueError("response does not match an active pause")
        pause = continuation.pending_pause
        pause.validate_response(response)
        if isinstance(response, UserInputResponse):
            if continuation.stage != "tool_batch":
                raise ValueError("user input response requires a Tool continuation")
            index = continuation.next_tool_index
            call = continuation.tool_calls[index]
            request = pause.user_input_request
            if request is None:
                raise ValueError("user input pause has no request")
            result = ToolResultPart(
                tool_call_id=call.tool_call_id,
                content=request.answers_to_json(response.answers),
                is_error=False,
            )
            self._continuation = replace(
                continuation,
                completed_tool_results=continuation.completed_tool_results + (result,),
                next_tool_index=index + 1,
                pending_pause=None,
            )
            batch_id = self._require_batch_id()
            self._append(
                events,
                ToolFinished(
                    self._state.run_id,
                    self._state.turn_id,
                    continuation.iteration,
                    batch_id,
                    call.tool_call_id,
                    call.name,
                    self._safe_command(call, known=True),
                    "finished",
                    False,
                ),
            )
            return
        if isinstance(response, PermissionApprovalResponse):
            if continuation.stage != "tool_batch":
                raise ValueError("permission response requires a Tool continuation")
            if self._pending_prepared_call is None:
                raise ValueError("permission response has no prepared Tool call")
            self._pending_permission_choice = response.choice
            self._continuation = replace(continuation, pending_pause=None)
            return
        if isinstance(response, PlanReviewResponse):
            if continuation.stage != "tool_batch":
                raise ValueError("Plan review response requires a Tool continuation")
            index = continuation.next_tool_index
            if index >= len(continuation.tool_calls):
                raise ValueError("Plan review response has no ProposePlan call")
            call = continuation.tool_calls[index]
            if call.name != PROPOSE_PLAN_TOOL_DEFINITION.name:
                raise ValueError("Plan review response does not match ProposePlan")
            plan_state = self._state.plan_state
            if plan_state is None or plan_state.revision != response.revision:
                raise ValueError("response does not match the authoritative Plan revision")
            if response.choice is PlanReviewChoice.REVISE:
                assert response.feedback is not None
                feedback = RuntimeFeedback(
                    RuntimeFeedbackKind.PLAN_REVISION,
                    response.feedback,
                )
            else:
                previous_mode = self._state.behavior_mode
                self._set_state(
                    behavior_mode=BehaviorMode.DEFAULT,
                    plan_state=replace(plan_state, approved=True),
                )
                if previous_mode is not BehaviorMode.DEFAULT:
                    self._append(
                        events,
                        BehaviorModeChanged(
                            self._state.run_id,
                            self._state.turn_id,
                            previous_mode,
                            BehaviorMode.DEFAULT,
                        ),
                    )
            result = ToolResultPart(
                call.tool_call_id,
                json.dumps(
                    {
                        "choice": response.choice.value,
                        "revision": plan_state.revision,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                False,
            )
            self._continuation = replace(
                continuation,
                completed_tool_results=continuation.completed_tool_results + (result,),
                next_tool_index=index + 1,
                pending_pause=None,
            )
            self._append(
                events,
                ToolFinished(
                    self._state.run_id,
                    self._state.turn_id,
                    continuation.iteration,
                    self._require_batch_id(),
                    call.tool_call_id,
                    call.name,
                    self._safe_command(call, known=True),
                    "finished",
                    False,
                ),
            )
            if response.choice is PlanReviewChoice.REVISE:
                self._close_tool_batch(events, status="finished")
                self._set_state(
                    messages=self._state.messages
                    + (Message(role="user", parts=(TextPart(response.feedback),)),),
                    runtime_feedback=feedback,
                )
            return
        self._continuation = replace(continuation, pending_pause=None)

    async def _consume_provider(
        self,
        request: GenerationRequest,
        iteration: int,
        message_id: str,
        pause_signal: CancellationToken,
        events: list[AgentEvent],
        *,
        buffer_assistant_text: bool,
    ) -> tuple[GenerationCompleted, tuple[str, ...]]:
        response: GenerationCompleted | None = None
        buffered_text_deltas: list[str] = []
        reasoning_segment = 0
        reasoning_open = False

        def close_reasoning() -> None:
            nonlocal reasoning_open
            if reasoning_open:
                self._append(
                    events,
                    ReasoningFinished(
                        self._state.run_id,
                        self._state.turn_id,
                        message_id,
                        iteration,
                        reasoning_segment,
                    ),
                )
                reasoning_open = False

        try:
            async for event in validated_provider_stream(
                self._loop._provider,
                request,
                cancellation=pause_signal,
            ):
                if isinstance(event, ProviderReasoningDelta):
                    if not event.text:
                        continue
                    if not reasoning_open:
                        reasoning_segment += 1
                        reasoning_open = True
                        self._append(
                            events,
                            ReasoningStarted(
                                self._state.run_id,
                                self._state.turn_id,
                                message_id,
                                iteration,
                                reasoning_segment,
                            ),
                        )
                    self._append(
                        events,
                        AgentReasoningDelta(
                            self._state.run_id,
                            self._state.turn_id,
                            message_id,
                            iteration,
                            event.text,
                        ),
                    )
                    continue

                close_reasoning()
                if isinstance(event, TextDelta) and event.text:
                    if buffer_assistant_text:
                        buffered_text_deltas.append(event.text)
                    else:
                        self._append(
                            events,
                            AssistantMessageDelta(
                                self._state.run_id,
                                self._state.turn_id,
                                message_id,
                                iteration,
                                event.text,
                            ),
                        )
                if isinstance(event, GenerationCompleted):
                    if self._cancellation.cancelled:
                        raise GenerationCancelled()
                    response = event
                    break
        except BaseException:
            close_reasoning()
            raise

        if response is None:
            raise InvalidProviderResponseError("Provider stream ended without a terminal response")
        return response, tuple(buffered_text_deltas)

    def _begin_tool_batch(
        self,
        calls: tuple[ToolCallPart, ...],
        iteration: int,
        assistant_message: Message,
        events: list[AgentEvent],
    ) -> None:
        self._batch_number += 1
        self._batch_id = f"batch-{self._batch_number}"
        self._batch_control_reason = None
        self._pending_prepared_call = None
        self._pending_permission_choice = None
        self._set_state(tool_call_count=self._state.tool_call_count + len(calls))
        self._append(
            events,
            ToolBatchStarted(
                self._state.run_id,
                self._state.turn_id,
                iteration,
                self._batch_id,
                tuple(call.tool_call_id for call in calls),
            ),
        )
        self._continuation = _TurnContinuation(
            stage="tool_batch",
            iteration=iteration,
            provider_retry_pending=False,
            assistant_tool_message=assistant_message,
            tool_calls=calls,
            completed_tool_results=(),
            next_tool_index=0,
            pending_pause=None,
        )
        propose_count = sum(
            call.name == PROPOSE_PLAN_TOOL_DEFINITION.name for call in calls
        )
        if propose_count and (len(calls) != 1 or propose_count != 1):
            self._batch_control_reason = (
                "Error: ProposePlan must be the only ToolCall in its response"
            )

    def _require_batch_id(self) -> str:
        if self._batch_id is None:
            raise RuntimeError("Tool batch is not active")
        return self._batch_id

    def _ask_enabled(self) -> bool:
        return any(definition.name == ASK_USER_TOOL_DEFINITION.name for definition in self._tool_definitions)

    def _todo_enabled(self) -> bool:
        return any(definition.name == TODO_WRITE_TOOL_DEFINITION.name for definition in self._tool_definitions)

    def _safe_command(self, call: ToolCallPart, *, known: bool) -> str:
        if not known:
            return "<unknown tool>"
        if call.name in {
            ASK_USER_TOOL_DEFINITION.name,
            TODO_WRITE_TOOL_DEFINITION.name,
            PROPOSE_PLAN_TOOL_DEFINITION.name,
        }:
            command = call.name
        elif self._loop._tool_call_describer is None:
            command = call.name
        else:
            try:
                command = self._loop._tool_call_describer(call)
            except Exception:
                command = "<tool summary unavailable>"
        if not isinstance(command, str) or not command:
            command = "<tool summary unavailable>"
        if len(command) > 240:
            command = command[:239] + "…"
        return command

    def _append_cancelled_call(
        self,
        events: list[AgentEvent],
        call: ToolCallPart,
        *,
        started: bool,
        iteration: int,
    ) -> ToolResultPart:
        batch_id = self._require_batch_id()
        known = (
            call.name == ASK_USER_TOOL_DEFINITION.name and self._ask_enabled()
        ) or (
            call.name == TODO_WRITE_TOOL_DEFINITION.name and self._todo_enabled()
        ) or self._loop._tool_registry.get(call.name) is not None
        if not started:
            self._append(
                events,
                ToolStarted(
                    self._state.run_id,
                    self._state.turn_id,
                    iteration,
                    batch_id,
                    call.tool_call_id,
                    call.name,
                    self._safe_command(call, known=known),
                ),
            )
        result = _controlled_tool_result(call, "Error: tool call cancelled")
        self._append(
            events,
            ToolFinished(
                self._state.run_id,
                self._state.turn_id,
                iteration,
                batch_id,
                call.tool_call_id,
                call.name,
                self._safe_command(call, known=known),
                "cancelled",
                True,
            ),
        )
        return result

    def _cancel_remaining_tools(self, events: list[AgentEvent]) -> None:
        continuation = self._continuation
        if continuation is None or continuation.stage != "tool_batch":
            return
        results = list(continuation.completed_tool_results)
        index = continuation.next_tool_index
        pending_input = (
            continuation.pending_pause is not None
            and continuation.pending_pause.kind
            in {PauseKind.USER_INPUT_REQUIRED, PauseKind.PERMISSION_REQUIRED}
        )
        pending_prepared = self._pending_prepared_call is not None
        if pending_prepared:
            pending_input = True
        self._pending_prepared_call = None
        self._pending_permission_choice = None
        if pending_input and index < len(continuation.tool_calls):
            results.append(
                self._append_cancelled_call(
                    events,
                    continuation.tool_calls[index],
                    started=True,
                    iteration=continuation.iteration,
                )
            )
            index += 1
        while index < len(continuation.tool_calls):
            results.append(
                self._append_cancelled_call(
                    events,
                    continuation.tool_calls[index],
                    started=False,
                    iteration=continuation.iteration,
                )
            )
            index += 1
        self._continuation = replace(
            continuation,
            completed_tool_results=tuple(results),
            next_tool_index=index,
            pending_pause=None,
        )
        self._close_tool_batch(events, status="cancelled")

    async def _execute_prepared(
        self,
        prepared: PreparedToolCall,
    ) -> tuple[ToolResultPart, bool, str]:
        """Execute exactly one already-prepared call and normalize failures."""

        call = prepared.call
        outcome = None
        try:
            outcome = await self._loop._tool_executor.execute_prepared_outcome(
                prepared,
                cancellation=self._cancellation,
            )
            if self._loop._result_materializer is None:
                result = outcome.result
            else:
                materialized_value = self._loop._result_materializer(outcome)
                materialized = (
                    await materialized_value
                    if inspect.isawaitable(materialized_value)
                    else materialized_value
                )
                if isinstance(materialized, ToolResultMaterialization):
                    result = materialized.result
                elif isinstance(materialized, ToolResultPart):
                    result = materialized
                else:
                    raise TypeError("result_materializer must return a ToolResultMaterialization or ToolResultPart")
            if not isinstance(result, ToolResultPart) or result.tool_call_id != call.tool_call_id:
                return (
                    _controlled_tool_result(
                        call,
                        "Error: tool execution returned an invalid result",
                    ),
                    True,
                    "failed",
                )
        except (GenerationCancelled, CancelledError):
            self._cancellation.cancel()
            return (
                _controlled_tool_result(call, "Error: tool call cancelled"),
                True,
                "cancelled",
            )
        except Exception:
            execution_status = "unknown" if outcome is None else outcome.status.value
            message = (
                "Error: tool result materialization failed after execution; "
                "the Tool already ran and will not be retried"
                if outcome is not None
                else "Error: tool execution failed"
            )
            return (
                ToolResultPart(
                    call.tool_call_id,
                    message,
                    True,
                    {"execution_status": execution_status, "persistence_status": "failed"},
                ),
                True,
                "failed",
            )
        return result, False, "failed" if result.is_error else "finished"

    def _close_stale_tools_for_steering(self, events: list[AgentEvent]) -> None:
        """Close every not-yet-started call without executing stale side effects."""

        continuation = self._continuation
        if continuation is None or continuation.stage != "tool_batch":
            raise RuntimeError("Steering has no active Tool batch")
        results = list(continuation.completed_tool_results)
        index = continuation.next_tool_index
        batch_id = self._require_batch_id()
        while index < len(continuation.tool_calls):
            call = continuation.tool_calls[index]
            known = (
                call.name == ASK_USER_TOOL_DEFINITION.name and self._ask_enabled()
            ) or (
                call.name == TODO_WRITE_TOOL_DEFINITION.name and self._todo_enabled()
            ) or (
                call.name == PROPOSE_PLAN_TOOL_DEFINITION.name
            ) or self._loop._tool_registry.get(call.name) is not None
            command = self._safe_command(call, known=known)
            self._append(
                events,
                ToolStarted(
                    self._state.run_id,
                    self._state.turn_id,
                    continuation.iteration,
                    batch_id,
                    call.tool_call_id,
                    call.name,
                    command,
                ),
            )
            result = _controlled_tool_result(
                call,
                "Error: tool call skipped after user steering",
            )
            results.append(result)
            self._append(
                events,
                ToolFinished(
                    self._state.run_id,
                    self._state.turn_id,
                    continuation.iteration,
                    batch_id,
                    call.tool_call_id,
                    call.name,
                    command,
                    "skipped",
                    True,
                ),
            )
            index += 1
        self._continuation = replace(
            continuation,
            completed_tool_results=tuple(results),
            next_tool_index=index,
            pending_pause=None,
        )
        self._close_tool_batch(events, status="steered")

    async def _run_tool_batch(
        self,
        events: list[AgentEvent],
        pause_signal: CancellationToken,
    ) -> str:
        continuation = self._continuation
        if continuation is None or continuation.stage != "tool_batch":
            raise RuntimeError("Tool batch continuation is missing")

        results = list(continuation.completed_tool_results)
        index = continuation.next_tool_index
        control_reason = self._batch_control_reason
        while index < len(continuation.tool_calls):
            continuation = self._continuation
            assert continuation is not None
            if self._cancellation.cancelled:
                self._cancel_remaining_tools(events)
                return "cancelled"
            if control_reason is None and self._pending_steering is not None:
                self._close_stale_tools_for_steering(events)
                self._apply_pending_steering(events)
                return "steered"
            if control_reason is None and pause_signal.cancelled:
                self._continuation = replace(continuation, pending_pause=None)
                self._pause_user_segment(events, continuation.iteration)
                return "paused"

            call = continuation.tool_calls[index]
            known = (
                call.name == ASK_USER_TOOL_DEFINITION.name and self._ask_enabled()
            ) or (
                call.name == TODO_WRITE_TOOL_DEFINITION.name and self._todo_enabled()
            ) or (
                call.name == PROPOSE_PLAN_TOOL_DEFINITION.name
            ) or self._loop._tool_registry.get(call.name) is not None
            command = self._safe_command(call, known=known)
            batch_id = self._require_batch_id()
            resumed_prepared = self._pending_prepared_call
            if resumed_prepared is not None and resumed_prepared.call.tool_call_id != call.tool_call_id:
                self._pending_prepared_call = None
                self._pending_permission_choice = None
                result = _controlled_tool_result(call, "Error: permission continuation mismatch")
                controlled = True
                status = "failed"
            else:
                if resumed_prepared is None:
                    self._append(
                        events,
                        ToolStarted(
                            self._state.run_id,
                            self._state.turn_id,
                            continuation.iteration,
                            batch_id,
                            call.tool_call_id,
                            call.name,
                            command,
                        ),
                    )

                controlled = False
                status = "finished"
                if self._cancellation.cancelled:
                    result = _controlled_tool_result(call, "Error: tool call cancelled")
                    controlled = True
                    status = "cancelled"
                elif control_reason is not None:
                    result = _controlled_tool_result(call, control_reason)
                    controlled = True
                    status = "failed"
                elif call.name == ASK_USER_TOOL_DEFINITION.name and self._ask_enabled():
                    self._set_state(consecutive_unknown_tools=0)
                    try:
                        request = UserInputRequest.from_dict(call.arguments)
                    except (TypeError, ValueError, KeyError):
                        result = _controlled_tool_result(call, "Error: invalid AskUserQuestion arguments")
                        controlled = True
                        status = "failed"
                    else:
                        self._continuation = replace(
                            continuation,
                            completed_tool_results=tuple(results),
                            next_tool_index=index,
                            pending_pause=None,
                        )
                        self._pause_input_segment(events, continuation.iteration, call, request)
                        return "paused"
                elif call.name == TODO_WRITE_TOOL_DEFINITION.name and self._todo_enabled():
                    self._set_state(consecutive_unknown_tools=0)
                    if self._state.behavior_mode is BehaviorMode.PLAN:
                        result = _controlled_tool_result(
                            call,
                            "Error: TodoWrite is unavailable in PLAN mode",
                        )
                        controlled = True
                        status = "failed"
                    else:
                        try:
                            task_state = parse_todo_write_arguments(call.arguments)
                        except (TypeError, ValueError, KeyError):
                            result = _controlled_tool_result(
                                call,
                                "Error: invalid TodoWrite arguments",
                            )
                            controlled = True
                            status = "failed"
                        else:
                            self._set_state(task_state=task_state)
                            self._append(
                                events,
                                TaskStateChanged(
                                    self._state.run_id,
                                    self._state.turn_id,
                                    continuation.iteration,
                                    task_state,
                                ),
                            )
                            result = ToolResultPart(
                                call.tool_call_id,
                                task_state.to_json(),
                                False,
                            )
                elif call.name == PROPOSE_PLAN_TOOL_DEFINITION.name:
                    self._set_state(consecutive_unknown_tools=0)
                    if (
                        self._state.behavior_mode is not BehaviorMode.PLAN
                        or len(continuation.tool_calls) != 1
                    ):
                        result = _controlled_tool_result(
                            call,
                            "Error: ProposePlan requires PLAN mode and must be the only ToolCall",
                        )
                        controlled = True
                        status = "failed"
                    else:
                        try:
                            plan_text = parse_propose_plan_arguments(call.arguments)
                        except (TypeError, ValueError, KeyError):
                            result = _controlled_tool_result(
                                call,
                                "Error: invalid ProposePlan arguments",
                            )
                            controlled = True
                            status = "failed"
                        else:
                            revision = (
                                1
                                if self._state.plan_state is None
                                else self._state.plan_state.revision + 1
                            )
                            plan_state = PlanState(revision, plan_text)
                            self._set_state(plan_state=plan_state)
                            self._append(
                                events,
                                PlanProposed(
                                    self._state.run_id,
                                    self._state.turn_id,
                                    continuation.iteration,
                                    revision,
                                    plan_text,
                                ),
                            )
                            self._continuation = replace(
                                continuation,
                                completed_tool_results=tuple(results),
                                next_tool_index=index,
                                pending_pause=None,
                            )
                            self._pause_plan_review_segment(
                                events,
                                continuation.iteration,
                                PlanReviewRequest(revision, plan_text),
                            )
                            return "paused"
                elif resumed_prepared is not None:
                    choice = self._pending_permission_choice
                    self._pending_prepared_call = None
                    self._pending_permission_choice = None
                    if choice is None:
                        result = _controlled_tool_result(call, "Error: permission response missing")
                        controlled = True
                        status = "failed"
                    elif choice is PermissionApprovalChoice.REJECT:
                        result = _controlled_tool_result(call, "Error: permission rejected")
                        controlled = True
                        status = "failed"
                    else:
                        result, controlled, status = await self._execute_prepared(resumed_prepared)
                        if (
                            choice is PermissionApprovalChoice.SESSION
                            and not result.is_error
                            and not self._cancellation.cancelled
                            and self._session_grant_sink is not None
                        ):
                            try:
                                self._session_grant_sink(resumed_prepared.action)
                            except Exception:
                                # The current approved call remains the
                                # authoritative result; a failed in-memory
                                # grant must not trigger a second execution.
                                pass
                else:
                    if known:
                        self._set_state(consecutive_unknown_tools=0)
                    else:
                        self._set_state(
                            consecutive_unknown_tools=self._state.consecutive_unknown_tools + 1
                        )
                    prepared_or_result = self._loop._tool_executor.prepare_call(
                        call,
                        cancellation=self._cancellation,
                    )
                    if isinstance(prepared_or_result, ToolResultPart):
                        result = prepared_or_result
                        controlled = True
                        status = "failed" if result.is_error else "finished"
                    else:
                        if (
                            self._state.behavior_mode is BehaviorMode.PLAN
                            and prepared_or_result.action.effect is not Effect.READ
                        ):
                            result = _controlled_tool_result(call, _PLAN_READ_ONLY_ERROR)
                            controlled = True
                            status = "failed"
                        else:
                            if self._permission_resolver is None:
                                raise RuntimeError(
                                    "permission resolver is required before executing an ordinary Tool"
                                )
                            try:
                                decision = self._permission_resolver(
                                    prepared_or_result.action
                                )
                            except Exception:
                                result = _controlled_tool_result(call, "Error: permission check failed")
                                controlled = True
                                status = "failed"
                            else:
                                if (
                                    not isinstance(decision, PermissionDecision)
                                    or decision.action != prepared_or_result.action
                                ):
                                    result = _controlled_tool_result(
                                        call,
                                        "Error: permission check failed",
                                    )
                                    controlled = True
                                    status = "failed"
                                elif decision.decision is Decision.ALLOW:
                                    result, controlled, status = await self._execute_prepared(
                                        prepared_or_result
                                    )
                                elif decision.decision is Decision.DENY:
                                    result = _controlled_tool_result(
                                        call,
                                        "Error: permission denied",
                                    )
                                    controlled = True
                                    status = "failed"
                                else:
                                    self._pending_prepared_call = prepared_or_result
                                    self._continuation = replace(
                                        continuation,
                                        completed_tool_results=tuple(results),
                                        next_tool_index=index,
                                        pending_pause=None,
                                    )
                                    self._pause_permission_segment(
                                        events,
                                        continuation.iteration,
                                        call,
                                        decision,
                                    )
                                    return "paused"

            if not controlled:
                status = "failed" if result.is_error else "finished"
            results.append(result)
            self._append(
                events,
                ToolFinished(
                    self._state.run_id,
                    self._state.turn_id,
                    continuation.iteration,
                    batch_id,
                    call.tool_call_id,
                    call.name,
                    command,
                    status,
                    result.is_error,
                ),
            )
            index += 1
            self._continuation = replace(
                continuation,
                completed_tool_results=tuple(results),
                next_tool_index=index,
                pending_pause=None,
            )
            await sleep(0)
            if self._cancellation.cancelled:
                self._cancel_remaining_tools(events)
                return "cancelled"
            if control_reason is None and self._pending_steering is not None:
                self._close_stale_tools_for_steering(events)
                self._apply_pending_steering(events)
                return "steered"
            if control_reason is None and pause_signal.cancelled:
                continuation = self._continuation
                assert continuation is not None
                if index < len(continuation.tool_calls):
                    self._pause_user_segment(events, continuation.iteration)
                    return "paused"

        continuation = self._continuation
        assert continuation is not None
        self._close_tool_batch(events, status="failed" if control_reason is not None else "finished")
        if control_reason is None and pause_signal.cancelled and self._terminal_result is None:
            next_iteration = self._state.iteration_count + 1
            if next_iteration > self._loop.config.max_iterations:
                return "finished"
            self._set_provider_continuation(next_iteration)
            self._pause_user_segment(events, next_iteration)
            return "paused"
        return "finished"

    def _close_tool_batch(self, events: list[AgentEvent], *, status: str) -> None:
        continuation = self._continuation
        if continuation is None or continuation.stage != "tool_batch":
            return
        results = continuation.completed_tool_results
        self._set_state(messages=self._state.messages + (Message(role="tool", parts=results),))
        self._append(
            events,
            ToolBatchFinished(
                self._state.run_id,
                self._state.turn_id,
                continuation.iteration,
                self._require_batch_id(),
                tuple(call.tool_call_id for call in continuation.tool_calls),
                status,
            ),
        )
        self._continuation = None
        self._batch_id = None
        self._batch_control_reason = None
        self._pending_prepared_call = None
        self._pending_permission_choice = None

    def _complete_segment(self, events: list[AgentEvent], final_text: str) -> AgentExecutionSegment:
        self._set_terminal(RunStatus.COMPLETED, TerminationReason.FINAL_ANSWER, final_text)
        self._append(events, TurnCompleted(self._state.run_id, self._state.turn_id, final_text))
        return self._terminal_segment(events)

    def _fail_segment(
        self,
        events: list[AgentEvent],
        reason: TerminationReason,
        failure_reason: FailureReason | None = None,
    ) -> AgentExecutionSegment:
        if failure_reason is None:
            if reason is TerminationReason.INTERNAL_ERROR:
                failure_reason = FailureReason.INTERNAL
            elif reason is TerminationReason.INVALID_PROVIDER_RESPONSE:
                failure_reason = FailureReason.INVALID_PROVIDER_RESPONSE
        self._set_terminal(RunStatus.FAILED, reason, None, failure_reason)
        self._append(
            events,
            TurnFailed(
                self._state.run_id,
                self._state.turn_id,
                reason,
                failure_reason,
            ),
        )
        return self._terminal_segment(events)

    def _cancel_segment(self, events: list[AgentEvent]) -> AgentExecutionSegment:
        self._cancellation.cancel()
        self._pending_steering = None
        self._steering_requested_emitted = False
        if self._continuation is not None and self._continuation.stage == "tool_batch":
            self._cancel_remaining_tools(events)
        self._set_terminal(RunStatus.CANCELLED, TerminationReason.USER_CANCELLED, None)
        self._append(events, TurnCancelled(self._state.run_id, self._state.turn_id))
        return self._terminal_segment(events)

    def _set_terminal(
        self,
        status: RunStatus,
        reason: TerminationReason,
        final_text: str | None,
        failure_reason: FailureReason | None = None,
    ) -> None:
        if self._terminal_result is not None:
            return
        self._set_state(status=status, termination_reason=reason)
        self._terminal_result = TurnResult(
            run_id=self._state.run_id,
            turn_id=self._state.turn_id,
            status=status,
            termination_reason=reason,
            final_text=final_text,
            usage=self._state.usage,
            iteration_count=self._state.iteration_count,
            tool_call_count=self._state.tool_call_count,
            failure_reason=failure_reason,
        )
        self._continuation = None
        self._batch_id = None
        self._batch_control_reason = None
        self._pending_prepared_call = None
        self._pending_permission_choice = None
        self._pending_steering = None
        self._steering_requested_emitted = False

    def _paused_segment(self, events: list[AgentEvent]) -> AgentExecutionSegment:
        if self._continuation is None or self._continuation.pending_pause is None:
            raise RuntimeError("paused segment has no continuation facts")
        return AgentExecutionSegment(
            events=tuple(events),
            state=self._state,
            boundary=ExecutionBoundary.PAUSED,
            continuation=self._continuation,
        )

    def _terminal_segment(self, events: tuple[AgentEvent, ...] | list[AgentEvent]) -> AgentExecutionSegment:
        if self._terminal_result is None:
            raise RuntimeError("terminal segment has no terminal result")
        return AgentExecutionSegment(
            events=tuple(events),
            state=self._state,
            boundary=ExecutionBoundary.TERMINAL,
            result=self._terminal_result,
        )


__all__ = [
    "AgentExecutionSegment",
    "AgentLoop",
    "AgentLoopConfig",
    "AgentLoopConfigError",
    "AgentTurnExecution",
    "AssistantMessageKind",
    "ExecutionBoundary",
    "RunSnapshot",
    "RunState",
    "RunStatus",
    "TerminationReason",
    "TurnResult",
]
