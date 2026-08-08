"""Provider-independent, display-safe Agent events.

The event contract is deliberately smaller than the Provider contract.  It is
safe to hand to an interface or serialize for a headless consumer: provider
SDK values, native payloads, exceptions, and ToolResult content never cross
this boundary.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields
from enum import Enum
from typing import Any, ClassVar, TypeAlias

from .interaction import (
    PauseKind,
    PauseReason,
    PauseRequest,
    PermissionApprovalRequest,
    PermissionApprovalResponse,
    UserInputRequest,
)
from .provider import (
    JsonPayload,
    Message,
    ReasoningPart,
    TextPart,
    ToolCallPart,
    ToolResultPart,
    Usage,
)


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


def _require_positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be a positive integer")
    if value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")
    return value


def _as_tuple(value: object, field_name: str) -> tuple[Any, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise TypeError(f"{field_name} must be a sequence")
    return tuple(value)


def _public_message(message: object, *, role: str) -> Message:
    """Validate the message subset that is safe for an AgentEvent."""

    if not isinstance(message, Message):
        raise TypeError("message must be a Message")
    if message.role != role:
        raise ValueError(f"message role must be {role!r}")
    if message.native_items:
        raise ValueError("AgentEvent messages must not contain native_items")
    if not all(isinstance(part, (TextPart, ReasoningPart)) for part in message.parts):
        raise ValueError("AgentEvent messages must contain only display-safe text parts")
    return message


def _json_value(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (Message, Usage)):
        return value.to_dict()
    if isinstance(
        value,
        (
            PauseRequest,
            PermissionApprovalRequest,
            PermissionApprovalResponse,
            UserInputRequest,
        ),
    ):
        return value.to_dict()
    if isinstance(value, JsonPayload):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    raise TypeError(f"AgentEvent value of type {type(value).__name__} is not JSON-safe")


def _event_dict(event: AgentEvent) -> dict[str, object]:
    return {
        "type": event.event_type,
        **{
            item.name: _json_value(getattr(event, item.name))
            for item in fields(event)
        },
    }


def _expect_mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError("AgentEvent payload must be a mapping")
    return value


def _expect_keys(value: Mapping[str, object], expected: set[str]) -> None:
    actual = set(value)
    missing = expected - actual
    if missing:
        raise ValueError(f"AgentEvent payload is missing fields: {sorted(missing)!r}")
    extra = actual - expected
    if extra:
        raise ValueError(f"AgentEvent payload has unknown fields: {sorted(extra)!r}")


def _required(value: Mapping[str, object], field_name: str) -> object:
    try:
        return value[field_name]
    except KeyError as exc:
        raise ValueError(f"AgentEvent payload is missing field: {field_name}") from exc


@dataclass(frozen=True, slots=True)
class AgentEvent:
    """Base class for all public Agent events."""

    run_id: str
    turn_id: str
    event_type: ClassVar[str]

    def __post_init__(self) -> None:
        _require_text(self.run_id, "run_id")
        _require_text(self.turn_id, "turn_id")

    @property
    def type(self) -> str:
        return self.event_type

    def to_dict(self) -> dict[str, object]:
        return _event_dict(self)

    def model_dump(self, *, mode: str = "python") -> dict[str, object]:
        del mode
        return self.to_dict()

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)


@dataclass(frozen=True, slots=True)
class TurnStarted(AgentEvent):
    event_type: ClassVar[str] = "turn_started"
    message_id: str
    message: Message

    def __post_init__(self) -> None:
        AgentEvent.__post_init__(self)
        _require_text(self.message_id, "message_id")
        _public_message(self.message, role="user")


@dataclass(frozen=True, slots=True)
class IterationStarted(AgentEvent):
    event_type: ClassVar[str] = "iteration_started"
    iteration: int

    def __post_init__(self) -> None:
        AgentEvent.__post_init__(self)
        _require_positive_int(self.iteration, "iteration")


@dataclass(frozen=True, slots=True)
class ReasoningStarted(AgentEvent):
    event_type: ClassVar[str] = "reasoning_started"
    message_id: str
    iteration: int
    segment_index: int

    def __post_init__(self) -> None:
        AgentEvent.__post_init__(self)
        _require_text(self.message_id, "message_id")
        _require_positive_int(self.iteration, "iteration")
        _require_positive_int(self.segment_index, "segment_index")


@dataclass(frozen=True, slots=True)
class ReasoningDelta(AgentEvent):
    event_type: ClassVar[str] = "reasoning_delta"
    message_id: str
    iteration: int
    text: str

    def __post_init__(self) -> None:
        AgentEvent.__post_init__(self)
        _require_text(self.message_id, "message_id")
        _require_positive_int(self.iteration, "iteration")
        _require_text(self.text, "text")


@dataclass(frozen=True, slots=True)
class ReasoningFinished(AgentEvent):
    event_type: ClassVar[str] = "reasoning_finished"
    message_id: str
    iteration: int
    segment_index: int

    def __post_init__(self) -> None:
        AgentEvent.__post_init__(self)
        _require_text(self.message_id, "message_id")
        _require_positive_int(self.iteration, "iteration")
        _require_positive_int(self.segment_index, "segment_index")


@dataclass(frozen=True, slots=True)
class AssistantMessageDelta(AgentEvent):
    event_type: ClassVar[str] = "assistant_message_delta"
    message_id: str
    iteration: int
    text: str

    def __post_init__(self) -> None:
        AgentEvent.__post_init__(self)
        _require_text(self.message_id, "message_id")
        _require_positive_int(self.iteration, "iteration")
        _require_text(self.text, "text")


class AssistantMessageKind(str, Enum):
    PROGRESS = "progress"
    FINAL = "final"
    INCOMPLETE = "incomplete"


@dataclass(frozen=True, slots=True)
class AssistantMessageCompleted(AgentEvent):
    event_type: ClassVar[str] = "assistant_message_completed"
    message_id: str
    iteration: int
    kind: AssistantMessageKind
    message: Message

    def __post_init__(self) -> None:
        AgentEvent.__post_init__(self)
        _require_text(self.message_id, "message_id")
        _require_positive_int(self.iteration, "iteration")
        kind = self.kind
        if not isinstance(kind, AssistantMessageKind):
            try:
                kind = AssistantMessageKind(kind)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"unknown assistant message kind: {self.kind!r}") from exc
            object.__setattr__(self, "kind", kind)
        _public_message(self.message, role="assistant")


@dataclass(frozen=True, slots=True)
class UsageUpdated(AgentEvent):
    event_type: ClassVar[str] = "usage_updated"
    iteration: int
    usage: Usage

    def __post_init__(self) -> None:
        AgentEvent.__post_init__(self)
        _require_positive_int(self.iteration, "iteration")
        if not isinstance(self.usage, Usage):
            raise TypeError("usage must be Usage")


@dataclass(frozen=True, slots=True)
class TurnPausing(AgentEvent):
    event_type: ClassVar[str] = "turn_pausing"
    pause_id: str
    kind: PauseKind
    reason: PauseReason
    iteration: int

    def __post_init__(self) -> None:
        AgentEvent.__post_init__(self)
        _require_text(self.pause_id, "pause_id")
        kind = self.kind
        if not isinstance(kind, PauseKind):
            try:
                kind = PauseKind(kind)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"unknown pause kind: {self.kind!r}") from exc
            object.__setattr__(self, "kind", kind)
        reason = self.reason
        if not isinstance(reason, PauseReason):
            try:
                reason = PauseReason(reason)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"unknown pause reason: {self.reason!r}") from exc
            object.__setattr__(self, "reason", reason)
        PauseRequest(
            pause_id=self.pause_id,
            run_id=self.run_id,
            turn_id=self.turn_id,
            kind=kind,
            reason=reason,
            iteration=self.iteration,
            created_at="event",
        )


@dataclass(frozen=True, slots=True)
class UserInputRequested(AgentEvent):
    event_type: ClassVar[str] = "user_input_requested"
    pause_id: str
    tool_call_id: str
    request: UserInputRequest

    def __post_init__(self) -> None:
        AgentEvent.__post_init__(self)
        _require_text(self.pause_id, "pause_id")
        _require_text(self.tool_call_id, "tool_call_id")
        if not isinstance(self.request, UserInputRequest):
            raise TypeError("request must be UserInputRequest")

    @property
    def user_input_request(self) -> UserInputRequest:
        return self.request


@dataclass(frozen=True, slots=True)
class TurnPaused(AgentEvent):
    event_type: ClassVar[str] = "turn_paused"
    pause: PauseRequest

    def __post_init__(self) -> None:
        AgentEvent.__post_init__(self)
        if not isinstance(self.pause, PauseRequest):
            raise TypeError("pause must be PauseRequest")
        if self.pause.run_id != self.run_id or self.pause.turn_id != self.turn_id:
            raise ValueError("pause IDs must match TurnPaused IDs")

    @property
    def pause_request(self) -> PauseRequest:
        return self.pause

    @property
    def pause_id(self) -> str:
        return self.pause.pause_id

    @property
    def kind(self) -> PauseKind:
        return self.pause.kind

    @property
    def reason(self) -> PauseReason:
        return self.pause.reason


@dataclass(frozen=True, slots=True)
class TurnResumed(AgentEvent):
    event_type: ClassVar[str] = "turn_resumed"
    pause_id: str
    kind: PauseKind

    def __post_init__(self) -> None:
        AgentEvent.__post_init__(self)
        _require_text(self.pause_id, "pause_id")
        kind = self.kind
        if not isinstance(kind, PauseKind):
            try:
                kind = PauseKind(kind)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"unknown pause kind: {self.kind!r}") from exc
            object.__setattr__(self, "kind", kind)


def _validate_tool_ids(value: object) -> tuple[str, ...]:
    values = _as_tuple(value, "tool_call_ids")
    result: list[str] = []
    for item in values:
        result.append(_require_text(item, "tool_call_id"))
    if len(set(result)) != len(result):
        raise ValueError("tool_call_ids must be unique")
    return tuple(result)


@dataclass(frozen=True, slots=True)
class ToolBatchStarted(AgentEvent):
    event_type: ClassVar[str] = "tool_batch_started"
    iteration: int
    batch_id: str
    tool_call_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        AgentEvent.__post_init__(self)
        _require_positive_int(self.iteration, "iteration")
        _require_text(self.batch_id, "batch_id")
        object.__setattr__(self, "tool_call_ids", _validate_tool_ids(self.tool_call_ids))


@dataclass(frozen=True, slots=True)
class ToolStarted(AgentEvent):
    event_type: ClassVar[str] = "tool_started"
    iteration: int
    batch_id: str
    tool_call_id: str
    tool_name: str
    command: str

    def __post_init__(self) -> None:
        AgentEvent.__post_init__(self)
        _require_positive_int(self.iteration, "iteration")
        _require_text(self.batch_id, "batch_id")
        _require_text(self.tool_call_id, "tool_call_id")
        _require_text(self.tool_name, "tool_name")
        _require_text(self.command, "command")


@dataclass(frozen=True, slots=True)
class ToolFinished(AgentEvent):
    event_type: ClassVar[str] = "tool_finished"
    iteration: int
    batch_id: str
    tool_call_id: str
    tool_name: str
    command: str
    status: str
    is_error: bool

    def __post_init__(self) -> None:
        AgentEvent.__post_init__(self)
        _require_positive_int(self.iteration, "iteration")
        _require_text(self.batch_id, "batch_id")
        _require_text(self.tool_call_id, "tool_call_id")
        _require_text(self.tool_name, "tool_name")
        _require_text(self.command, "command")
        _require_text(self.status, "status")
        if not isinstance(self.is_error, bool):
            raise TypeError("is_error must be a boolean")


@dataclass(frozen=True, slots=True)
class ToolBatchFinished(AgentEvent):
    event_type: ClassVar[str] = "tool_batch_finished"
    iteration: int
    batch_id: str
    tool_call_ids: tuple[str, ...]
    status: str

    def __post_init__(self) -> None:
        AgentEvent.__post_init__(self)
        _require_positive_int(self.iteration, "iteration")
        _require_text(self.batch_id, "batch_id")
        object.__setattr__(self, "tool_call_ids", _validate_tool_ids(self.tool_call_ids))
        _require_text(self.status, "status")


class TerminationReason(str, Enum):
    FINAL_ANSWER = "final_answer"
    MAX_ITERATIONS = "max_iterations"
    MAX_TOOL_CALLS = "max_tool_calls"
    CONSECUTIVE_UNKNOWN_TOOLS = "consecutive_unknown_tools"
    MAX_OUTPUT_TOKENS = "max_output_tokens"
    PROVIDER_ERROR = "provider_error"
    INVALID_PROVIDER_RESPONSE = "invalid_provider_response"
    USER_CANCELLED = "user_cancelled"
    INTERNAL_ERROR = "internal_error"


@dataclass(frozen=True, slots=True)
class TurnCompleted(AgentEvent):
    event_type: ClassVar[str] = "turn_completed"
    final_text: str

    def __post_init__(self) -> None:
        AgentEvent.__post_init__(self)
        if not isinstance(self.final_text, str):
            raise TypeError("final_text must be a string")


@dataclass(frozen=True, slots=True)
class TurnFailed(AgentEvent):
    event_type: ClassVar[str] = "turn_failed"
    termination_reason: TerminationReason

    def __post_init__(self) -> None:
        AgentEvent.__post_init__(self)
        reason = self.termination_reason
        if not isinstance(reason, TerminationReason):
            try:
                reason = TerminationReason(reason)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"unknown termination reason: {self.termination_reason!r}") from exc
            object.__setattr__(self, "termination_reason", reason)


@dataclass(frozen=True, slots=True)
class TurnCancelled(AgentEvent):
    event_type: ClassVar[str] = "turn_cancelled"
    termination_reason: TerminationReason = TerminationReason.USER_CANCELLED

    def __post_init__(self) -> None:
        AgentEvent.__post_init__(self)
        reason = self.termination_reason
        if not isinstance(reason, TerminationReason):
            try:
                reason = TerminationReason(reason)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"unknown termination reason: {self.termination_reason!r}") from exc
            object.__setattr__(self, "termination_reason", reason)
        if reason is not TerminationReason.USER_CANCELLED:
            raise ValueError("TurnCancelled must use user_cancelled")


AgentEventValue: TypeAlias = (
    TurnStarted
    | IterationStarted
    | ReasoningStarted
    | ReasoningDelta
    | ReasoningFinished
    | AssistantMessageDelta
    | AssistantMessageCompleted
    | UsageUpdated
    | TurnPausing
    | UserInputRequested
    | TurnPaused
    | TurnResumed
    | ToolBatchStarted
    | ToolStarted
    | ToolFinished
    | ToolBatchFinished
    | TurnCompleted
    | TurnFailed
    | TurnCancelled
)


_EVENT_TYPES: dict[str, type[AgentEvent]] = {
    event_type: event_class
    for event_class in (
        TurnStarted,
        IterationStarted,
        ReasoningStarted,
        ReasoningDelta,
        ReasoningFinished,
        AssistantMessageDelta,
        AssistantMessageCompleted,
        UsageUpdated,
        TurnPausing,
        UserInputRequested,
        TurnPaused,
        TurnResumed,
        ToolBatchStarted,
        ToolStarted,
        ToolFinished,
        ToolBatchFinished,
        TurnCompleted,
        TurnFailed,
        TurnCancelled,
    )
    for event_type in (event_class.event_type,)
}


def _base_payload(value: Mapping[str, object], *, fields_: set[str]) -> tuple[str, str]:
    _expect_keys(value, {"type", "run_id", "turn_id", *fields_})
    if value.get("type") not in _EVENT_TYPES:
        raise ValueError(f"unknown agent event type: {value.get('type')!r}")
    return (
        _require_text(_required(value, "run_id"), "run_id"),
        _require_text(_required(value, "turn_id"), "turn_id"),
    )


def agent_event_from_dict(value: Mapping[str, object]) -> AgentEventValue:
    """Restore one frozen AgentEvent from its type-tagged JSON object."""

    payload = _expect_mapping(value)
    event_type = payload.get("type")
    if not isinstance(event_type, str) or event_type not in _EVENT_TYPES:
        raise ValueError(f"unknown agent event type: {event_type!r}")
    run_id = _require_text(_required(payload, "run_id"), "run_id")
    turn_id = _require_text(_required(payload, "turn_id"), "turn_id")

    if event_type == TurnStarted.event_type:
        _expect_keys(payload, {"type", "run_id", "turn_id", "message_id", "message"})
        return TurnStarted(
            run_id,
            turn_id,
            _required(payload, "message_id"),  # type: ignore[arg-type]
            Message.from_dict(_required(payload, "message")),
        )
    if event_type == IterationStarted.event_type:
        _expect_keys(payload, {"type", "run_id", "turn_id", "iteration"})
        return IterationStarted(run_id, turn_id, _required(payload, "iteration"))  # type: ignore[arg-type]
    if event_type == ReasoningStarted.event_type:
        _expect_keys(payload, {"type", "run_id", "turn_id", "message_id", "iteration", "segment_index"})
        return ReasoningStarted(
            run_id,
            turn_id,
            _required(payload, "message_id"),  # type: ignore[arg-type]
            _required(payload, "iteration"),  # type: ignore[arg-type]
            _required(payload, "segment_index"),  # type: ignore[arg-type]
        )
    if event_type == ReasoningDelta.event_type:
        _expect_keys(payload, {"type", "run_id", "turn_id", "message_id", "iteration", "text"})
        return ReasoningDelta(
            run_id,
            turn_id,
            _required(payload, "message_id"),  # type: ignore[arg-type]
            _required(payload, "iteration"),  # type: ignore[arg-type]
            _required(payload, "text"),  # type: ignore[arg-type]
        )
    if event_type == ReasoningFinished.event_type:
        _expect_keys(payload, {"type", "run_id", "turn_id", "message_id", "iteration", "segment_index"})
        return ReasoningFinished(
            run_id,
            turn_id,
            _required(payload, "message_id"),  # type: ignore[arg-type]
            _required(payload, "iteration"),  # type: ignore[arg-type]
            _required(payload, "segment_index"),  # type: ignore[arg-type]
        )
    if event_type == AssistantMessageDelta.event_type:
        _expect_keys(payload, {"type", "run_id", "turn_id", "message_id", "iteration", "text"})
        return AssistantMessageDelta(
            run_id,
            turn_id,
            _required(payload, "message_id"),  # type: ignore[arg-type]
            _required(payload, "iteration"),  # type: ignore[arg-type]
            _required(payload, "text"),  # type: ignore[arg-type]
        )
    if event_type == AssistantMessageCompleted.event_type:
        _expect_keys(payload, {"type", "run_id", "turn_id", "message_id", "iteration", "kind", "message"})
        return AssistantMessageCompleted(
            run_id,
            turn_id,
            _required(payload, "message_id"),  # type: ignore[arg-type]
            _required(payload, "iteration"),  # type: ignore[arg-type]
            _required(payload, "kind"),  # type: ignore[arg-type]
            Message.from_dict(_required(payload, "message")),
        )
    if event_type == UsageUpdated.event_type:
        _expect_keys(payload, {"type", "run_id", "turn_id", "iteration", "usage"})
        return UsageUpdated(
            run_id,
            turn_id,
            _required(payload, "iteration"),  # type: ignore[arg-type]
            Usage.from_dict(_required(payload, "usage")),
        )
    if event_type == TurnPausing.event_type:
        _expect_keys(payload, {"type", "run_id", "turn_id", "pause_id", "kind", "reason", "iteration"})
        return TurnPausing(
            run_id,
            turn_id,
            _required(payload, "pause_id"),  # type: ignore[arg-type]
            _required(payload, "kind"),  # type: ignore[arg-type]
            _required(payload, "reason"),  # type: ignore[arg-type]
            _required(payload, "iteration"),  # type: ignore[arg-type]
        )
    if event_type == UserInputRequested.event_type:
        _expect_keys(payload, {"type", "run_id", "turn_id", "pause_id", "tool_call_id", "request"})
        return UserInputRequested(
            run_id,
            turn_id,
            _required(payload, "pause_id"),  # type: ignore[arg-type]
            _required(payload, "tool_call_id"),  # type: ignore[arg-type]
            UserInputRequest.from_dict(_required(payload, "request")),  # type: ignore[arg-type]
        )
    if event_type == TurnPaused.event_type:
        _expect_keys(payload, {"type", "run_id", "turn_id", "pause"})
        return TurnPaused(
            run_id,
            turn_id,
            PauseRequest.from_dict(_required(payload, "pause")),  # type: ignore[arg-type]
        )
    if event_type == TurnResumed.event_type:
        _expect_keys(payload, {"type", "run_id", "turn_id", "pause_id", "kind"})
        return TurnResumed(
            run_id,
            turn_id,
            _required(payload, "pause_id"),  # type: ignore[arg-type]
            _required(payload, "kind"),  # type: ignore[arg-type]
        )
    if event_type == ToolBatchStarted.event_type:
        _expect_keys(payload, {"type", "run_id", "turn_id", "iteration", "batch_id", "tool_call_ids"})
        return ToolBatchStarted(
            run_id,
            turn_id,
            _required(payload, "iteration"),  # type: ignore[arg-type]
            _required(payload, "batch_id"),  # type: ignore[arg-type]
            _required(payload, "tool_call_ids"),  # type: ignore[arg-type]
        )
    if event_type == ToolStarted.event_type:
        _expect_keys(
            payload,
            {"type", "run_id", "turn_id", "iteration", "batch_id", "tool_call_id", "tool_name", "command"},
        )
        return ToolStarted(
            run_id,
            turn_id,
            _required(payload, "iteration"),  # type: ignore[arg-type]
            _required(payload, "batch_id"),  # type: ignore[arg-type]
            _required(payload, "tool_call_id"),  # type: ignore[arg-type]
            _required(payload, "tool_name"),  # type: ignore[arg-type]
            _required(payload, "command"),  # type: ignore[arg-type]
        )
    if event_type == ToolFinished.event_type:
        _expect_keys(
            payload,
            {
                "type",
                "run_id",
                "turn_id",
                "iteration",
                "batch_id",
                "tool_call_id",
                "tool_name",
                "command",
                "status",
                "is_error",
            },
        )
        return ToolFinished(
            run_id,
            turn_id,
            _required(payload, "iteration"),  # type: ignore[arg-type]
            _required(payload, "batch_id"),  # type: ignore[arg-type]
            _required(payload, "tool_call_id"),  # type: ignore[arg-type]
            _required(payload, "tool_name"),  # type: ignore[arg-type]
            _required(payload, "command"),  # type: ignore[arg-type]
            _required(payload, "status"),  # type: ignore[arg-type]
            _required(payload, "is_error"),  # type: ignore[arg-type]
        )
    if event_type == ToolBatchFinished.event_type:
        _expect_keys(payload, {"type", "run_id", "turn_id", "iteration", "batch_id", "tool_call_ids", "status"})
        return ToolBatchFinished(
            run_id,
            turn_id,
            _required(payload, "iteration"),  # type: ignore[arg-type]
            _required(payload, "batch_id"),  # type: ignore[arg-type]
            _required(payload, "tool_call_ids"),  # type: ignore[arg-type]
            _required(payload, "status"),  # type: ignore[arg-type]
        )
    if event_type == TurnCompleted.event_type:
        _expect_keys(payload, {"type", "run_id", "turn_id", "final_text"})
        return TurnCompleted(run_id, turn_id, _required(payload, "final_text"))  # type: ignore[arg-type]
    if event_type == TurnFailed.event_type:
        _expect_keys(payload, {"type", "run_id", "turn_id", "termination_reason"})
        return TurnFailed(run_id, turn_id, _required(payload, "termination_reason"))  # type: ignore[arg-type]

    _expect_keys(payload, {"type", "run_id", "turn_id", "termination_reason"})
    return TurnCancelled(run_id, turn_id, _required(payload, "termination_reason"))  # type: ignore[arg-type]


def agent_event_from_json(value: str) -> AgentEventValue:
    parsed = json.loads(value)
    if not isinstance(parsed, Mapping):
        raise TypeError("AgentEvent JSON must contain an object")
    return agent_event_from_dict(parsed)


__all__ = [
    "AgentEvent",
    "AgentEventValue",
    "AssistantMessageKind",
    "AssistantMessageCompleted",
    "AssistantMessageDelta",
    "IterationStarted",
    "ReasoningDelta",
    "ReasoningFinished",
    "ReasoningStarted",
    "ToolBatchFinished",
    "ToolBatchStarted",
    "ToolFinished",
    "ToolStarted",
    "TurnCancelled",
    "TurnCompleted",
    "TurnFailed",
    "TurnStarted",
    "TerminationReason",
    "UsageUpdated",
    "TurnPausing",
    "UserInputRequested",
    "TurnPaused",
    "TurnResumed",
    "agent_event_from_dict",
    "agent_event_from_json",
]
