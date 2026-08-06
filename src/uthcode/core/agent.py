"""Core Agent policy, immutable state, and the explicit sequential Loop."""

from __future__ import annotations

import asyncio
import inspect
import json
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from enum import Enum

from .agent_events import (
    AgentEvent,
    AssistantMessageCompleted,
    AssistantMessageDelta,
    AssistantMessageKind,
    IterationStarted,
    ReasoningDelta as AgentReasoningDelta,
    ReasoningFinished,
    ReasoningStarted,
    ToolBatchFinished,
    ToolBatchStarted,
    ToolFinished,
    ToolStarted,
    TerminationReason,
    TurnCancelled,
    TurnCompleted,
    TurnFailed,
    TurnStarted,
    UsageUpdated,
)
from .provider import (
    CancellationToken,
    FinishReason,
    GenerationCancelled,
    GenerationCompleted,
    GenerationRequest,
    InvalidProviderResponseError,
    Message,
    ProviderError,
    ProviderPort,
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
from .tool import ToolExecutor, ToolRegistry


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
    def initial(cls, run_id: str, *, turn_id: str = "initial") -> RunState:
        return cls(run_id=run_id, turn_id=turn_id)

    def new_turn(self, turn_id: str, user_input: str) -> RunState:
        """Create the next immutable Turn while retaining the conversation."""

        _require_text(turn_id, "turn_id")
        if not isinstance(user_input, str) or not user_input.strip():
            raise ValueError("user_input must be a non-empty string")
        user_message = Message(role="user", parts=(TextPart(user_input),))
        return RunState(
            run_id=self.run_id,
            turn_id=turn_id,
            messages=self.messages + (user_message,),
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
        )

    @classmethod
    def from_json(cls, value: str) -> TurnResult:
        parsed = json.loads(value)
        if not isinstance(parsed, Mapping):
            raise TypeError("TurnResult JSON must contain an object")
        return cls.from_dict(parsed)


RequestPreparer = Callable[
    [tuple[Message, ...], tuple[ToolDefinition, ...]],
    GenerationRequest | Awaitable[GenerationRequest],
]
ToolCallDescriber = Callable[[ToolCallPart], str]


_END = object()


def _message_text(message: Message) -> str:
    return "".join(part.text for part in message.parts if isinstance(part, TextPart))


def _public_assistant_message(message: Message) -> Message:
    """Project a terminal assistant message to display-safe text parts."""

    return Message(
        role="assistant",
        parts=tuple(part for part in message.parts if isinstance(part, (TextPart, ReasoningPart))),
    )


def _add_usage(previous: Usage, current: Usage) -> Usage:
    details: dict[str, object] = dict(previous.details.items())
    for key, value in current.details.items():
        old_value = details.get(key)
        if (
            isinstance(old_value, (int, float))
            and not isinstance(old_value, bool)
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
        ):
            details[key] = old_value + value
        else:
            details[key] = value
    return Usage(
        input_tokens=previous.input_tokens + current.input_tokens,
        output_tokens=previous.output_tokens + current.output_tokens,
        total_tokens=previous.total_tokens + current.total_tokens,
        cache_read_tokens=previous.cache_read_tokens + current.cache_read_tokens,
        cache_write_tokens=previous.cache_write_tokens + current.cache_write_tokens,
        details=details,
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
        self._provider = provider
        self._tool_registry = tool_registry
        self._tool_executor = tool_executor
        self._request_preparer = request_preparer
        self._config = config
        self._tool_call_describer = tool_call_describer

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
        turn_state = state.new_turn(turn_id, user_input)
        return AgentTurnExecution(
            loop=self,
            state=turn_state,
            tool_definitions=self._tool_registry.definitions(),
            cancellation=cancellation,
        )


class AgentTurnExecution:
    """One lazily started execution with a single event producer."""

    __slots__ = (
        "_loop",
        "_state",
        "_tool_definitions",
        "_cancellation",
        "_events_claimed",
        "_queue",
        "_task",
        "_result_future",
        "_result_value",
        "_terminal_emitted",
        "_completion_listeners",
        "_completion_notified",
        "_batch_number",
        "_reasoning_segment",
        "_reasoning_open",
    )

    def __init__(
        self,
        *,
        loop: AgentLoop,
        state: RunState,
        tool_definitions: tuple[ToolDefinition, ...],
        cancellation: CancellationToken,
    ) -> None:
        self._loop = loop
        self._state = state
        self._tool_definitions = tuple(tool_definitions)
        self._cancellation = cancellation
        self._events_claimed = False
        self._queue: asyncio.Queue[object] | None = None
        self._task: asyncio.Task[None] | None = None
        self._result_future: asyncio.Future[TurnResult] | None = None
        self._result_value: TurnResult | None = None
        self._terminal_emitted = False
        self._completion_listeners: list[Callable[[TurnResult], object]] = []
        self._completion_notified = False
        self._batch_number = 0
        self._reasoning_segment = 0
        self._reasoning_open = False

    @property
    def state(self) -> RunState:
        return self._state

    @property
    def cancellation(self) -> CancellationToken:
        return self._cancellation

    def snapshot(self) -> RunSnapshot:
        return RunSnapshot.from_state(self._state)

    def cancel(self) -> bool:
        return self._cancellation.cancel()

    def cancelled(self) -> bool:
        return self._cancellation.cancelled

    def start(self) -> None:
        """Start the single Core producer in the current event loop."""

        self._ensure_started()

    def add_completion_listener(
        self,
        listener: Callable[[TurnResult], object],
    ) -> None:
        """Notify one synchronous listener when this Turn reaches a terminal.

        Registration itself is synchronous so Application can attach the
        listener during ``start_turn()``.  If the terminal already exists, the
        listener is invoked immediately; otherwise it is called exactly once
        by the Core producer.  Listener failures are isolated from the Agent
        Loop and never become user-visible diagnostics.
        """

        if not callable(listener):
            raise TypeError("listener must be callable")
        if self._completion_notified:
            result = self._result_value
            if result is not None:
                self._invoke_completion_listener(listener, result)
            return
        self._completion_listeners.append(listener)

    async def run(self) -> TurnResult:
        return await self.result()

    async def result(self) -> TurnResult:
        self._ensure_started()
        assert self._result_future is not None
        return await asyncio.shield(self._result_future)

    async def events(self) -> AsyncIterator[AgentEvent]:
        if self._events_claimed:
            raise RuntimeError("AgentTurnExecution.events() can only be consumed once")
        self._events_claimed = True
        self._ensure_started()
        assert self._queue is not None
        while True:
            item = await self._queue.get()
            if item is _END:
                assert self._result_future is not None
                if self._result_future.cancelled():
                    raise asyncio.CancelledError
                if self._result_future.exception() is not None:
                    raise self._result_future.exception()  # type: ignore[misc]
                return
            if not isinstance(item, AgentEvent):
                raise RuntimeError("Agent execution produced an invalid event")
            yield item

    def _ensure_started(self) -> None:
        if self._task is not None:
            return
        loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue()
        self._result_future = loop.create_future()
        self._task = loop.create_task(self._produce())

    async def _produce(self) -> None:
        assert self._queue is not None
        assert self._result_future is not None
        try:
            result = await self._execute()
        except asyncio.CancelledError:
            if not self._terminal_emitted:
                self._cancellation.cancel()
                result = await self._cancel_turn()
            else:
                if not self._result_future.done():
                    self._result_future.cancel()
                await self._queue.put(_END)
                return
        except Exception:
            if self._terminal_emitted:
                if not self._result_future.done():
                    self._result_future.cancel()
                await self._queue.put(_END)
                return
            result = await self._fail_turn(TerminationReason.INTERNAL_ERROR)
        self._result_value = result
        self._notify_completion(result)
        if not self._result_future.done():
            self._result_future.set_result(result)
        await self._queue.put(_END)

    async def _emit(self, event: AgentEvent) -> None:
        assert self._queue is not None
        await self._queue.put(event)

    def _set_state(self, **changes: object) -> None:
        self._state = replace(self._state, **changes)

    async def _execute(self) -> TurnResult:
        user_message = self._state.messages[-1]
        user_message_id = uuid.uuid4().hex
        await self._emit(
            TurnStarted(
                self._state.run_id,
                self._state.turn_id,
                user_message_id,
                user_message,
            )
        )

        while True:
            if self._cancellation.cancelled:
                return await self._cancel_turn()
            if self._state.iteration_count >= self._loop.config.max_iterations:
                return await self._fail_turn(TerminationReason.MAX_ITERATIONS)

            iteration = self._state.iteration_count + 1
            self._set_state(iteration_count=iteration)
            await self._emit(IterationStarted(self._state.run_id, self._state.turn_id, iteration))

            try:
                request_value = self._loop._request_preparer(
                    self._state.messages,
                    self._tool_definitions,
                )
                request = await request_value if inspect.isawaitable(request_value) else request_value
                if not isinstance(request, GenerationRequest):
                    raise TypeError("request_preparer must return GenerationRequest")
            except Exception:
                return await self._fail_turn(TerminationReason.INTERNAL_ERROR)

            assistant_message_id = uuid.uuid4().hex
            try:
                response = await self._consume_provider(
                    request,
                    iteration,
                    assistant_message_id,
                )
            except GenerationCancelled:
                return await self._cancel_turn()
            except asyncio.CancelledError:
                if self._cancellation.cancelled:
                    return await self._cancel_turn()
                raise
            except InvalidProviderResponseError:
                return await self._fail_turn(TerminationReason.INVALID_PROVIDER_RESPONSE)
            except ProviderError:
                return await self._fail_turn(TerminationReason.PROVIDER_ERROR)
            except Exception:
                return await self._fail_turn(TerminationReason.INTERNAL_ERROR)

            if self._cancellation.cancelled:
                return await self._cancel_turn()
            try:
                calls = _validate_response(response)
            except InvalidProviderResponseError:
                return await self._fail_turn(TerminationReason.INVALID_PROVIDER_RESPONSE)
            provider_response = response.response
            self._set_state(usage=_add_usage(self._state.usage, provider_response.usage))
            await self._emit(UsageUpdated(self._state.run_id, self._state.turn_id, iteration, self._state.usage))

            finish_reason = provider_response.finish_reason
            if finish_reason is FinishReason.ERROR:
                return await self._fail_turn(TerminationReason.PROVIDER_ERROR)
            if finish_reason is FinishReason.CANCELLED:
                return await self._cancel_turn()
            if finish_reason is FinishReason.UNKNOWN:
                return await self._fail_turn(TerminationReason.INVALID_PROVIDER_RESPONSE)

            if finish_reason in {FinishReason.LENGTH, FinishReason.INCOMPLETE}:
                kind = AssistantMessageKind.INCOMPLETE
            elif calls:
                kind = AssistantMessageKind.PROGRESS
            else:
                kind = AssistantMessageKind.FINAL

            self._set_state(messages=self._state.messages + (provider_response.message,))
            await self._emit(
                AssistantMessageCompleted(
                    self._state.run_id,
                    self._state.turn_id,
                    assistant_message_id,
                    iteration,
                    kind,
                    _public_assistant_message(provider_response.message),
                )
            )

            if self._cancellation.cancelled:
                if calls:
                    await self._finish_tool_batch(calls, iteration)
                return await self._cancel_turn()

            if kind is AssistantMessageKind.FINAL:
                return await self._complete_turn(_message_text(provider_response.message))

            if kind is AssistantMessageKind.INCOMPLETE:
                if calls:
                    await self._finish_tool_batch(
                        calls,
                        iteration,
                        control_reason="Error: tool call not executed because provider response was incomplete",
                    )
                if self._cancellation.cancelled:
                    return await self._cancel_turn()
                return await self._fail_turn(TerminationReason.MAX_OUTPUT_TOKENS)

            if len(calls) > self._loop.config.max_tool_calls_per_iteration:
                await self._finish_tool_batch(
                    calls,
                    iteration,
                    control_reason="Error: tool call limit exceeded",
                )
                if self._cancellation.cancelled:
                    return await self._cancel_turn()
                return await self._fail_turn(TerminationReason.MAX_TOOL_CALLS)

            batch_status = await self._finish_tool_batch(calls, iteration)
            if self._cancellation.cancelled:
                return await self._cancel_turn()
            if self._state.consecutive_unknown_tools >= self._loop.config.max_consecutive_unknown_tools:
                return await self._fail_turn(TerminationReason.CONSECUTIVE_UNKNOWN_TOOLS)
            if batch_status == "cancelled":
                return await self._cancel_turn()

    async def _consume_provider(
        self,
        request: GenerationRequest,
        iteration: int,
        message_id: str,
    ) -> GenerationCompleted:
        response: GenerationCompleted | None = None
        self._reasoning_segment = 0

        async def close_reasoning() -> None:
            if self._reasoning_open:
                await self._emit(
                    ReasoningFinished(
                        self._state.run_id,
                        self._state.turn_id,
                        message_id,
                        iteration,
                        self._reasoning_segment,
                    )
                )
                self._reasoning_open = False

        try:
            async for event in validated_provider_stream(
                self._loop._provider,
                request,
                cancellation=self._cancellation,
            ):
                if isinstance(event, ProviderReasoningDelta):
                    if not event.text:
                        continue
                    if not self._reasoning_open:
                        self._reasoning_segment += 1
                        self._reasoning_open = True
                        await self._emit(
                            ReasoningStarted(
                                self._state.run_id,
                                self._state.turn_id,
                                message_id,
                                iteration,
                                self._reasoning_segment,
                            )
                        )
                    await self._emit(
                        AgentReasoningDelta(
                            self._state.run_id,
                            self._state.turn_id,
                            message_id,
                            iteration,
                            event.text,
                        )
                    )
                    continue

                await close_reasoning()
                if isinstance(event, TextDelta) and event.text:
                    await self._emit(
                        AssistantMessageDelta(
                            self._state.run_id,
                            self._state.turn_id,
                            message_id,
                            iteration,
                            event.text,
                        )
                    )
                if isinstance(event, GenerationCompleted):
                    if self._cancellation.cancelled:
                        raise GenerationCancelled()
                    response = event
                    break
        except BaseException:
            await close_reasoning()
            raise

        if response is None:
            raise InvalidProviderResponseError("Provider stream ended without a terminal response")
        return response

    def _safe_command(self, call: ToolCallPart, *, known: bool) -> str:
        if not known:
            return "<unknown tool>"
        describer = self._loop._tool_call_describer
        if describer is None:
            command = call.name
        else:
            try:
                command = describer(call)
            except Exception:
                command = "<tool summary unavailable>"
        if not isinstance(command, str) or not command:
            command = "<tool summary unavailable>"
        if len(command) > 240:
            command = command[:239] + "…"
        return command

    async def _finish_tool_batch(
        self,
        calls: tuple[ToolCallPart, ...],
        iteration: int,
        *,
        control_reason: str | None = None,
    ) -> str:
        self._batch_number += 1
        batch_id = f"batch-{self._batch_number}"
        call_ids = tuple(call.tool_call_id for call in calls)
        self._set_state(tool_call_count=self._state.tool_call_count + len(calls))
        await self._emit(
            ToolBatchStarted(
                self._state.run_id,
                self._state.turn_id,
                iteration,
                batch_id,
                call_ids,
            )
        )

        results: list[ToolResultPart] = []
        batch_status = "finished"
        for call in calls:
            known = self._loop._tool_registry.get(call.name) is not None
            command = self._safe_command(call, known=known)
            await self._emit(
                ToolStarted(
                    self._state.run_id,
                    self._state.turn_id,
                    iteration,
                    batch_id,
                    call.tool_call_id,
                    call.name,
                    command,
                )
            )

            controlled_status = False
            if self._cancellation.cancelled:
                result = _controlled_tool_result(call, "Error: tool call cancelled")
                controlled_status = True
                batch_status = "cancelled"
            elif control_reason is not None:
                result = _controlled_tool_result(call, control_reason)
                controlled_status = True
            else:
                if known:
                    self._set_state(consecutive_unknown_tools=0)
                else:
                    self._set_state(
                        consecutive_unknown_tools=self._state.consecutive_unknown_tools + 1
                    )
                try:
                    result = await self._loop._tool_executor.execute_call(
                        call,
                        cancellation=self._cancellation,
                    )
                    if not isinstance(result, ToolResultPart) or result.tool_call_id != call.tool_call_id:
                        result = _controlled_tool_result(call, "Error: tool execution returned an invalid result")
                except (GenerationCancelled, asyncio.CancelledError):
                    self._cancellation.cancel()
                    result = _controlled_tool_result(call, "Error: tool call cancelled")
                    controlled_status = True
                    batch_status = "cancelled" if self._cancellation.cancelled else "finished"
                except Exception:
                    result = _controlled_tool_result(call, "Error: tool execution failed")

            if result.is_error and not controlled_status:
                batch_status = "finished"
            if self._cancellation.cancelled and len(results) < len(calls) - 1:
                batch_status = "cancelled"
            if controlled_status and self._cancellation.cancelled:
                batch_status = "cancelled"
            status = "cancelled" if controlled_status and self._cancellation.cancelled else (
                "failed" if result.is_error else "finished"
            )
            if control_reason is not None:
                status = "failed"
                batch_status = "failed"
            results.append(result)
            await self._emit(
                ToolFinished(
                    self._state.run_id,
                    self._state.turn_id,
                    iteration,
                    batch_id,
                    call.tool_call_id,
                    call.name,
                    command,
                    status,
                    result.is_error,
                )
            )

        self._set_state(
            messages=self._state.messages + (Message(role="tool", parts=tuple(results)),)
        )
        if self._cancellation.cancelled and control_reason is None:
            batch_status = "cancelled"
        await self._emit(
            ToolBatchFinished(
                self._state.run_id,
                self._state.turn_id,
                iteration,
                batch_id,
                call_ids,
                batch_status,
            )
        )
        return batch_status

    async def _complete_turn(self, final_text: str) -> TurnResult:
        return await self._terminal_result(
            RunStatus.COMPLETED,
            TerminationReason.FINAL_ANSWER,
            final_text,
        )

    async def _fail_turn(self, reason: TerminationReason) -> TurnResult:
        return await self._terminal_result(RunStatus.FAILED, reason, None)

    async def _cancel_turn(self) -> TurnResult:
        return await self._terminal_result(
            RunStatus.CANCELLED,
            TerminationReason.USER_CANCELLED,
            None,
        )

    async def _terminal_result(
        self,
        status: RunStatus,
        reason: TerminationReason,
        final_text: str | None,
    ) -> TurnResult:
        if self._terminal_emitted:
            if self._result_value is None:
                raise RuntimeError("Agent Turn already terminated without a result")
            return self._result_value
        self._terminal_emitted = True
        self._set_state(status=status, termination_reason=reason)
        result = TurnResult(
            run_id=self._state.run_id,
            turn_id=self._state.turn_id,
            status=status,
            termination_reason=reason,
            final_text=final_text,
            usage=self._state.usage,
            iteration_count=self._state.iteration_count,
            tool_call_count=self._state.tool_call_count,
        )
        self._result_value = result
        self._notify_completion(result)
        if status is RunStatus.COMPLETED:
            await self._emit(TurnCompleted(self._state.run_id, self._state.turn_id, final_text or ""))
        elif status is RunStatus.CANCELLED:
            await self._emit(TurnCancelled(self._state.run_id, self._state.turn_id))
        else:
            await self._emit(TurnFailed(self._state.run_id, self._state.turn_id, reason))
        return result

    def _notify_completion(self, result: TurnResult) -> None:
        if self._completion_notified:
            return
        self._completion_notified = True
        listeners = tuple(self._completion_listeners)
        self._completion_listeners.clear()
        for listener in listeners:
            self._invoke_completion_listener(listener, result)

    @staticmethod
    def _invoke_completion_listener(
        listener: Callable[[TurnResult], object],
        result: TurnResult,
    ) -> None:
        try:
            listener(result)
        except Exception:
            # Completion is a Core fact.  A consumer callback must not change
            # terminal semantics or expose an exception from this boundary.
            return


__all__ = [
    "AgentLoop",
    "AgentLoopConfig",
    "AgentLoopConfigError",
    "AgentTurnExecution",
    "AssistantMessageKind",
    "RunSnapshot",
    "RunState",
    "RunStatus",
    "TerminationReason",
    "TurnResult",
]
