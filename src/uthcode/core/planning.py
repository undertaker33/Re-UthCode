"""Immutable planning and execution-control domain values."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any

from .provider import ToolDefinition


def _require_text(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _require_positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be a positive integer")
    if value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")
    return value


def _as_mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    return value


def _as_tuple(value: object, field_name: str) -> tuple[Any, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise TypeError(f"{field_name} must be a sequence")
    return tuple(value)


def _expect_keys(value: Mapping[str, object], expected: set[str]) -> None:
    actual = set(value)
    missing = expected - actual
    if missing:
        raise ValueError(f"payload is missing fields: {sorted(missing)!r}")
    extra = actual - expected
    if extra:
        raise ValueError(f"payload has unknown fields: {sorted(extra)!r}")


def _required(value: Mapping[str, object], field_name: str) -> object:
    try:
        return value[field_name]
    except KeyError as exc:
        raise ValueError(f"payload is missing field: {field_name}") from exc


def _coerce_enum(enum_type: type[Enum], value: object, field_name: str) -> Enum:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"unknown {field_name}: {value!r}") from exc


def _json_object(value: str, field_name: str) -> Mapping[str, object]:
    parsed = json.loads(value)
    if not isinstance(parsed, Mapping):
        raise TypeError(f"{field_name} JSON must contain an object")
    return parsed


class _JsonModel:
    def to_dict(self) -> dict[str, object]:
        raise NotImplementedError

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)


class BehaviorMode(str, Enum):
    """The Agent behavior selected independently from permission mode."""

    DEFAULT = "default"
    PLAN = "plan"


class TaskStatus(str, Enum):
    """The complete set of execution-task states."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


@dataclass(frozen=True, slots=True)
class TaskItem(_JsonModel):
    content: str
    status: TaskStatus

    def __post_init__(self) -> None:
        _require_text(self.content, "content")
        object.__setattr__(
            self,
            "status",
            _coerce_enum(TaskStatus, self.status, "task status"),
        )

    def to_dict(self) -> dict[str, object]:
        return {"content": self.content, "status": self.status.value}

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> TaskItem:
        payload = _as_mapping(value, "task item")
        _expect_keys(payload, {"content", "status"})
        return cls(
            _required(payload, "content"),  # type: ignore[arg-type]
            _required(payload, "status"),  # type: ignore[arg-type]
        )

    @classmethod
    def from_json(cls, value: str) -> TaskItem:
        return cls.from_dict(_json_object(value, "TaskItem"))


@dataclass(frozen=True, slots=True)
class TaskState(_JsonModel):
    """The ordered, replace-all task projection for the current Turn."""

    items: tuple[TaskItem, ...] = ()

    def __post_init__(self) -> None:
        items = _as_tuple(self.items, "items")
        if not all(isinstance(item, TaskItem) for item in items):
            raise TypeError("items must contain TaskItem values")
        if sum(item.status is TaskStatus.IN_PROGRESS for item in items) > 1:
            raise ValueError("TaskState allows at most one in_progress item")
        object.__setattr__(self, "items", items)

    @property
    def is_empty(self) -> bool:
        return not self.items

    @property
    def unfinished_count(self) -> int:
        return sum(item.status is not TaskStatus.COMPLETED for item in self.items)

    @property
    def has_unfinished(self) -> bool:
        return self.unfinished_count > 0

    def to_dict(self) -> dict[str, object]:
        return {"items": [item.to_dict() for item in self.items]}

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> TaskState:
        payload = _as_mapping(value, "task state")
        _expect_keys(payload, {"items"})
        return cls(
            tuple(
                TaskItem.from_dict(item)  # type: ignore[arg-type]
                for item in _as_tuple(_required(payload, "items"), "items")
            )
        )

    @classmethod
    def from_json(cls, value: str) -> TaskState:
        return cls.from_dict(_json_object(value, "TaskState"))


@dataclass(frozen=True, slots=True)
class PlanState(_JsonModel):
    """The latest complete natural-language Plan for the current Turn."""

    revision: int
    text: str
    approved: bool = False

    def __post_init__(self) -> None:
        _require_positive_int(self.revision, "revision")
        _require_text(self.text, "text")
        if not isinstance(self.approved, bool):
            raise TypeError("approved must be a boolean")

    def to_dict(self) -> dict[str, object]:
        return {
            "revision": self.revision,
            "text": self.text,
            "approved": self.approved,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> PlanState:
        payload = _as_mapping(value, "plan state")
        _expect_keys(payload, {"revision", "text", "approved"})
        return cls(
            _required(payload, "revision"),  # type: ignore[arg-type]
            _required(payload, "text"),  # type: ignore[arg-type]
            _required(payload, "approved"),  # type: ignore[arg-type]
        )

    @classmethod
    def from_json(cls, value: str) -> PlanState:
        return cls.from_dict(_json_object(value, "PlanState"))


class RuntimeFeedbackKind(str, Enum):
    COMPLETION_BLOCKED = "completion_blocked"
    USER_STEERING = "user_steering"
    PLAN_REVISION = "plan_revision"


@dataclass(frozen=True, slots=True)
class RuntimeFeedback(_JsonModel):
    """One request's structured runtime feedback, separate from conversation."""

    kind: RuntimeFeedbackKind
    text: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "kind",
            _coerce_enum(RuntimeFeedbackKind, self.kind, "runtime feedback kind"),
        )
        _require_text(self.text, "text")

    def to_dict(self) -> dict[str, object]:
        return {"kind": self.kind.value, "text": self.text}

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> RuntimeFeedback:
        payload = _as_mapping(value, "runtime feedback")
        _expect_keys(payload, {"kind", "text"})
        return cls(
            _required(payload, "kind"),  # type: ignore[arg-type]
            _required(payload, "text"),  # type: ignore[arg-type]
        )

    @classmethod
    def from_json(cls, value: str) -> RuntimeFeedback:
        return cls.from_dict(_json_object(value, "RuntimeFeedback"))


TODO_WRITE_TOOL_DEFINITION = ToolDefinition(
    name="TodoWrite",
    description=(
        "Replace the complete current execution task list. Use an empty todos "
        "array to explicitly clear it."
    ),
    parameters={
        "type": "object",
        "properties": {
            "todos": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string", "minLength": 1},
                        "status": {"enum": [item.value for item in TaskStatus]},
                    },
                    "required": ["content", "status"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["todos"],
        "additionalProperties": False,
    },
)


def parse_todo_write_arguments(arguments: Mapping[str, object]) -> TaskState:
    """Validate a TodoWrite replace-all payload and return its immutable state."""

    payload = _as_mapping(arguments, "TodoWrite arguments")
    _expect_keys(payload, {"todos"})
    todos = _as_tuple(_required(payload, "todos"), "todos")
    return TaskState(tuple(TaskItem.from_dict(item) for item in todos))  # type: ignore[arg-type]


__all__ = [
    "BehaviorMode",
    "PlanState",
    "RuntimeFeedback",
    "RuntimeFeedbackKind",
    "TODO_WRITE_TOOL_DEFINITION",
    "TaskItem",
    "TaskState",
    "TaskStatus",
    "parse_todo_write_arguments",
]
