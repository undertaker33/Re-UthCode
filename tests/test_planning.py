from __future__ import annotations

import json
from dataclasses import FrozenInstanceError

import pytest
from jsonschema import Draft202012Validator

from uthcode.core.planning import (
    BehaviorMode,
    PlanState,
    RuntimeFeedback,
    RuntimeFeedbackKind,
    TODO_WRITE_TOOL_DEFINITION,
    TaskItem,
    TaskState,
    TaskStatus,
    parse_todo_write_arguments,
)


def test_planning_enums_are_exact_and_json_safe() -> None:
    assert [item.value for item in BehaviorMode] == ["default", "plan"]
    assert [item.value for item in TaskStatus] == [
        "pending",
        "in_progress",
        "completed",
    ]
    assert [item.value for item in RuntimeFeedbackKind] == [
        "completion_blocked",
        "user_steering",
        "plan_revision",
    ]


def test_todo_replace_all_preserves_order_and_supports_explicit_clear() -> None:
    state = parse_todo_write_arguments(
        {
            "todos": [
                {"content": "explore", "status": "completed"},
                {"content": "implement", "status": "in_progress"},
                {"content": "verify", "status": "pending"},
            ]
        }
    )

    assert state.items == (
        TaskItem("explore", TaskStatus.COMPLETED),
        TaskItem("implement", TaskStatus.IN_PROGRESS),
        TaskItem("verify", TaskStatus.PENDING),
    )
    assert state.unfinished_count == 2
    assert state.has_unfinished is True
    assert state.is_empty is False
    assert parse_todo_write_arguments({"todos": []}) == TaskState()
    assert TaskState().is_empty is True
    assert TaskState().has_unfinished is False


@pytest.mark.parametrize(
    "payload",
    (
        {},
        {"todos": [], "unexpected": True},
        {"todos": "not-a-list"},
        {"todos": [1]},
        {"todos": [{"content": "x"}]},
        {"todos": [{"content": "x", "status": "pending", "extra": True}]},
        {"todos": [{"content": "", "status": "pending"}]},
        {"todos": [{"content": "  ", "status": "pending"}]},
        {"todos": [{"content": "x", "status": "unknown"}]},
        {
            "todos": [
                {"content": "one", "status": "in_progress"},
                {"content": "two", "status": "in_progress"},
            ]
        },
    ),
)
def test_todo_replace_all_rejects_invalid_arguments(payload: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        parse_todo_write_arguments(payload)  # type: ignore[arg-type]


def test_planning_values_are_frozen_and_round_trip_strictly() -> None:
    task_state = TaskState(
        (
            TaskItem("one", TaskStatus.IN_PROGRESS),
            TaskItem("two", TaskStatus.PENDING),
        )
    )
    plan_state = PlanState(2, "Implement the approved design.", True)
    feedback = RuntimeFeedback(
        RuntimeFeedbackKind.USER_STEERING,
        "Re-check the updated user goal before continuing.",
    )

    for value in (task_state, plan_state, feedback):
        restored = type(value).from_json(value.to_json())
        assert restored == value
        assert json.loads(value.to_json()) == value.to_dict()
        with pytest.raises((TypeError, ValueError, KeyError)):
            type(value).from_dict({**value.to_dict(), "unexpected": True})

    with pytest.raises(FrozenInstanceError):
        task_state.items = ()  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        plan_state.approved = False  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        feedback.text = "changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    "factory",
    (
        lambda: TaskItem("", TaskStatus.PENDING),
        lambda: TaskItem("x", "unknown"),
        lambda: TaskState((TaskItem("one", TaskStatus.IN_PROGRESS), TaskItem("two", TaskStatus.IN_PROGRESS))),
        lambda: PlanState(0, "plan", False),
        lambda: PlanState(True, "plan", False),
        lambda: PlanState(1, "", False),
        lambda: PlanState(1, "plan", 1),
        lambda: RuntimeFeedback("unknown", "text"),
        lambda: RuntimeFeedback(RuntimeFeedbackKind.PLAN_REVISION, ""),
    ),
)
def test_planning_values_reject_invalid_construction(factory) -> None:
    with pytest.raises((TypeError, ValueError)):
        factory()


def test_todo_write_definition_is_strict_and_contains_no_runtime_metadata() -> None:
    definition = TODO_WRITE_TOOL_DEFINITION
    schema = definition.to_dict()["parameters"]

    assert definition.name == "TodoWrite"
    assert definition.parameters["additionalProperties"] is False
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    assert validator.is_valid({"todos": []})
    assert validator.is_valid(
        {"todos": [{"content": "verify", "status": "pending"}]}
    )
    assert not validator.is_valid(
        {"todos": [{"content": "verify", "status": "pending", "extra": True}]}
    )
    assert "planning_access" not in definition.to_dict()
    assert "planning_access" not in definition.parameters
