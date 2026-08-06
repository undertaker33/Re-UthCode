from __future__ import annotations

import json
from pathlib import Path

import pytest

from uthcode.core.agent import AssistantMessageKind, TerminationReason
from uthcode.core.agent_events import (
    AgentEvent,
    AssistantMessageCompleted,
    AssistantMessageDelta,
    IterationStarted,
    ReasoningDelta,
    ReasoningFinished,
    ReasoningStarted,
    ToolBatchFinished,
    ToolBatchStarted,
    ToolFinished,
    ToolStarted,
    TurnCancelled,
    TurnCompleted,
    TurnFailed,
    TurnStarted,
    UsageUpdated,
    agent_event_from_dict,
    agent_event_from_json,
)
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
        TurnFailed("run-1", "turn-2", TerminationReason.PROVIDER_ERROR),
        TurnCancelled("run-1", "turn-3"),
    )


def test_all_agent_events_are_frozen_and_json_round_trip() -> None:
    for event in _events():
        restored = agent_event_from_json(event.to_json())
        assert restored == event
        assert json.loads(event.to_json())["type"] == event.event_type
        assert isinstance(restored, AgentEvent)


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
