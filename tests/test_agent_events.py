from __future__ import annotations

import json
from pathlib import Path

import pytest

from uthcode.core.agent import (
    AssistantMessageKind,
    RunStatus,
    TerminationReason,
    TurnResult,
)
from uthcode.core.agent_events import (
    AgentEvent,
    AssistantMessageCompleted,
    AssistantMessageDelta,
    BehaviorModeChanged,
    CompletionBlocked,
    IterationStarted,
    PlanProposed,
    ReasoningDelta,
    ReasoningFinished,
    ReasoningStarted,
    ToolBatchFinished,
    ToolBatchStarted,
    ToolFinished,
    ToolStarted,
    TaskStateChanged,
    TurnCancelled,
    TurnCompleted,
    TurnFailed,
    TurnStarted,
    FailureReason,
    UsageUpdated,
    UserSteeringApplied,
    UserSteeringRequested,
    agent_event_from_dict,
    agent_event_from_json,
    TurnPausing,
    PlanContentDelta,
)
from uthcode.core.interaction import PauseKind, PauseReason
from uthcode.core.planning import BehaviorMode, TaskItem, TaskState, TaskStatus
from uthcode.core.provider import Message, NativeItem, TextPart, ToolCallPart, ToolResultPart, Usage


def _events() -> tuple[AgentEvent, ...]:
    return (
        TurnStarted(
            "run-1",
            "turn-1",
            "user-message-1",
            Message(role="user", parts=(TextPart("hello"),)),
        ),
        IterationStarted("run-1", "turn-1", 1),
        ReasoningStarted("run-1", "turn-1", "assistant-message-1", 1, 1),
        ReasoningDelta("run-1", "turn-1", "assistant-message-1", 1, "thinking"),
        ReasoningFinished("run-1", "turn-1", "assistant-message-1", 1, 1),
        AssistantMessageDelta("run-1", "turn-1", "assistant-message-1", 1, "answer"),
        AssistantMessageCompleted(
            "run-1",
            "turn-1",
            "assistant-message-1",
            1,
            AssistantMessageKind.FINAL,
            Message(role="assistant", parts=(TextPart("answer"),)),
        ),
        UsageUpdated("run-1", "turn-1", 1, Usage(input_tokens=2, output_tokens=3)),
        BehaviorModeChanged(
            "run-1",
            "turn-1",
            BehaviorMode.PLAN,
            BehaviorMode.DEFAULT,
        ),
        TaskStateChanged(
            "run-1",
            "turn-1",
            1,
            TaskState((TaskItem("verify", TaskStatus.IN_PROGRESS),)),
        ),
        PlanContentDelta("run-1", "turn-1", 1, "plan-call-1", "Partial plan"),
        PlanProposed("run-1", "turn-1", 1, 2, "Complete replacement plan"),
        CompletionBlocked("run-1", "turn-1", 1, 2),
        UserSteeringRequested("run-1", "turn-1", "steer-1"),
        UserSteeringApplied("run-1", "turn-1", "steer-1"),
        ToolBatchStarted("run-1", "turn-1", 1, "batch-1", ("call-1",)),
        ToolStarted("run-1", "turn-1", 1, "batch-1", "call-1", "read_file", "read path"),
        ToolFinished(
            "run-1",
            "turn-1",
            1,
            "batch-1",
            "call-1",
            "read_file",
            "read path",
            "finished",
            False,
        ),
        ToolBatchFinished("run-1", "turn-1", 1, "batch-1", ("call-1",), "finished"),
        TurnCompleted("run-1", "turn-1", "answer"),
        TurnFailed(
            "run-1",
            "turn-2",
            TerminationReason.PROVIDER_ERROR,
            FailureReason.AUTHENTICATION,
        ),
        TurnCancelled("run-1", "turn-3"),
    )


def test_all_agent_events_are_frozen_and_json_round_trip() -> None:
    for event in _events():
        restored = agent_event_from_json(event.to_json())
        assert restored == event
        assert json.loads(event.to_json())["type"] == event.event_type
        assert isinstance(restored, AgentEvent)


def test_timeout_provider_pause_event_is_public_and_round_trips() -> None:
    event = TurnPausing(
        "run-1",
        "turn-1",
        "pause-1",
        PauseKind.PROVIDER_UNAVAILABLE,
        PauseReason.TIMEOUT,
        1,
    )

    payload = event.to_dict()
    assert payload["kind"] == "provider_unavailable"
    assert payload["reason"] == "timeout"
    assert agent_event_from_json(event.to_json()) == event

    with pytest.raises(ValueError):
        TurnPausing(
            "run-1",
            "turn-1",
            "pause-1",
            PauseKind.PROVIDER_UNAVAILABLE,
            PauseReason.USER_REQUESTED,
            1,
        )


def test_failure_reason_is_distinct_from_termination_and_round_trips() -> None:
    failed_event = TurnFailed(
        "run-1",
        "turn-2",
        TerminationReason.PROVIDER_ERROR,
        FailureReason.AUTHENTICATION,
    )
    assert agent_event_from_json(failed_event.to_json()) == failed_event
    assert failed_event.to_dict()["termination_reason"] == "provider_error"
    assert failed_event.to_dict()["failure_reason"] == "authentication"

    failed_result = TurnResult(
        run_id="run-1",
        turn_id="turn-2",
        status=RunStatus.FAILED,
        termination_reason=TerminationReason.PROVIDER_ERROR,
        final_text=None,
        usage=Usage(),
        iteration_count=1,
        tool_call_count=0,
        failure_reason=FailureReason.AUTHENTICATION,
    )
    assert TurnResult.from_json(failed_result.to_json()) == failed_result

    cancelled_result = TurnResult(
        run_id="run-1",
        turn_id="turn-3",
        status=RunStatus.CANCELLED,
        termination_reason=TerminationReason.USER_CANCELLED,
        final_text=None,
        usage=Usage(),
        iteration_count=0,
        tool_call_count=0,
    )
    assert cancelled_result.failure_reason is None
    with pytest.raises(ValueError):
        TurnResult(
            run_id="run-1",
            turn_id="turn-4",
            status=RunStatus.COMPLETED,
            termination_reason=TerminationReason.FINAL_ANSWER,
            final_text="done",
            usage=Usage(),
            iteration_count=1,
            tool_call_count=0,
            failure_reason=FailureReason.INTERNAL,
        )


def test_reasoning_events_can_represent_multiple_ordered_segments() -> None:
    events = [
        ReasoningStarted("run-1", "turn-1", "assistant-message-1", 1, 1),
        ReasoningDelta("run-1", "turn-1", "assistant-message-1", 1, "one"),
        ReasoningFinished("run-1", "turn-1", "assistant-message-1", 1, 1),
        ReasoningStarted("run-1", "turn-1", "assistant-message-1", 1, 2),
        ReasoningDelta("run-1", "turn-1", "assistant-message-1", 1, "two"),
        ReasoningFinished("run-1", "turn-1", "assistant-message-1", 1, 2),
    ]
    assert [event.event_type for event in events] == [
        "reasoning_started",
        "reasoning_delta",
        "reasoning_finished",
        "reasoning_started",
        "reasoning_delta",
        "reasoning_finished",
    ]


def test_tool_finished_exposes_only_safe_fields() -> None:
    event = ToolFinished(
        "run-1",
        "turn-1",
        1,
        "batch-1",
        "call-1",
        "write_file",
        "write secret.txt",
        "failed",
        True,
    )
    payload = event.to_dict()
    assert payload["command"] == "write secret.txt"
    assert "content" not in payload
    assert "result" not in payload
    assert "arguments" not in payload


def test_t08_events_are_strict_display_safe_and_carry_required_projection() -> None:
    task_state = TaskState(
        (
            TaskItem("implement", TaskStatus.IN_PROGRESS),
            TaskItem("test", TaskStatus.PENDING),
        )
    )
    events = (
        BehaviorModeChanged("run", "turn", BehaviorMode.PLAN, BehaviorMode.DEFAULT),
        TaskStateChanged("run", "turn", 3, task_state),
        PlanContentDelta("run", "turn", 3, "plan-call", "Partial plan"),
        PlanProposed("run", "turn", 3, 4, "Full Plan v4"),
        CompletionBlocked("run", "turn", 3, 2),
        UserSteeringRequested("run", "turn", "steer-secret-free"),
        UserSteeringApplied("run", "turn", "steer-secret-free"),
    )

    for event in events:
        payload = event.to_dict()
        assert agent_event_from_dict(payload) == event
        assert agent_event_from_json(event.to_json()) == event
        assert "raw_payload" not in payload
        assert "arguments" not in payload
        assert "candidate_text" not in payload
        with pytest.raises((TypeError, ValueError, KeyError)):
            agent_event_from_dict({**payload, "unexpected": True})

    assert events[1].to_dict()["task_state"] == task_state.to_dict()
    assert events[2].to_dict() == {
        "type": "plan_content_delta",
        "run_id": "run",
        "turn_id": "turn",
        "iteration": 3,
        "tool_call_id": "plan-call",
        "text": "Partial plan",
    }
    assert events[3].to_dict()["revision"] == 4
    assert events[3].to_dict()["plan_text"] == "Full Plan v4"
    assert "text" not in events[5].to_dict()
    assert "text" not in events[6].to_dict()


@pytest.mark.parametrize(
    "factory",
    (
        lambda: BehaviorModeChanged("run", "turn", BehaviorMode.PLAN, BehaviorMode.PLAN),
        lambda: TaskStateChanged("run", "turn", 0, TaskState()),
        lambda: PlanProposed("run", "turn", 1, 0, "plan"),
        lambda: PlanProposed("run", "turn", 1, 1, ""),
        lambda: PlanContentDelta("run", "turn", 1, "", "plan"),
        lambda: PlanContentDelta("run", "turn", 1, "call", ""),
        lambda: CompletionBlocked("run", "turn", 1, 0),
        lambda: UserSteeringRequested("run", "turn", ""),
        lambda: UserSteeringApplied("run", "turn", ""),
    ),
)
def test_t08_events_reject_invalid_values(factory) -> None:
    with pytest.raises((TypeError, ValueError)):
        factory()


@pytest.mark.parametrize(
    "payload",
    [
        {"type": "future_event", "run_id": "run-1", "turn_id": "turn-1"},
        {"type": "turn_completed", "run_id": "run-1", "turn_id": "turn-1"},
        {
            "type": "reasoning_delta",
            "run_id": "run-1",
            "turn_id": "turn-1",
            "iteration": 1,
            "text": Path("secret.txt"),
        },
        {
            "type": "reasoning_delta",
            "run_id": "run-1",
            "turn_id": "turn-1",
            "message_id": 123,
            "iteration": 1,
            "text": "thinking",
        },
        {
            "type": "reasoning_delta",
            "run_id": "run-1",
            "turn_id": "turn-1",
            "iteration": 1,
            "text": "thinking",
        },
        {
            "type": "turn_completed",
            "run_id": "run-1",
            "turn_id": "turn-1",
            "final_text": "answer",
            "unexpected": True,
        },
        {
            "type": "turn_completed",
            "run_id": "run-1",
            "turn_id": "turn-1",
            "final_text": "answer",
            "message_id": "unexpected-message-id",
        },
    ],
)
def test_agent_event_from_dict_rejects_unknown_missing_non_json_or_extra_payload(payload: dict[str, object]) -> None:
    with pytest.raises((TypeError, ValueError, KeyError)):
        agent_event_from_dict(payload)


def test_agent_event_message_rejects_native_items_tool_results_and_tool_calls() -> None:
    with pytest.raises(ValueError):
        AssistantMessageCompleted(
            "run-1",
            "turn-1",
            "assistant-message-1",
            1,
            AssistantMessageKind.FINAL,
            Message(
                role="assistant",
                parts=(TextPart("answer"),),
                native_items=(NativeItem("fake", "script", "model"),),
            ),
        )
    with pytest.raises(ValueError):
        AssistantMessageCompleted(
            "run-1",
            "turn-1",
            "assistant-message-1",
            1,
            AssistantMessageKind.FINAL,
            Message(role="assistant", parts=(ToolResultPart("call-1", "secret"),)),
        )
    with pytest.raises(ValueError):
        AssistantMessageCompleted(
            "run-1",
            "turn-1",
            "assistant-message-1",
            1,
            AssistantMessageKind.PROGRESS,
            Message(
                role="assistant",
                parts=(ToolCallPart("call-1", "read", {"value": "W01-R1-SECRET"}),),
            ),
        )


def test_no_empty_reasoning_delta_can_be_constructed() -> None:
    with pytest.raises(ValueError):
        ReasoningDelta("run-1", "turn-1", "assistant-message-1", 1, "")
