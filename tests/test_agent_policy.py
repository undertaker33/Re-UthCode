from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from uthcode.core.agent import (
    AgentLoop,
    AgentLoopConfig,
    AgentLoopConfigError,
    AgentTurnExecution,
    RunSnapshot,
    RunState,
    RunStatus,
    TerminationReason,
    TurnResult,
)
from uthcode.core.provider import Message, TextPart, Usage


def test_agent_loop_config_has_the_confirmed_limits() -> None:
    assert AgentLoopConfig() == AgentLoopConfig(50, 16, 3)


@pytest.mark.parametrize(
    "field_name",
    ["max_iterations", "max_tool_calls_per_iteration", "max_consecutive_unknown_tools"],
)
@pytest.mark.parametrize("value", [0, -1])
def test_agent_loop_config_rejects_non_positive_values(field_name: str, value: int) -> None:
    with pytest.raises(AgentLoopConfigError):
        AgentLoopConfig(**{field_name: value})


@pytest.mark.parametrize(
    "field_name",
    ["max_iterations", "max_tool_calls_per_iteration", "max_consecutive_unknown_tools"],
)
@pytest.mark.parametrize("value", [True, False, 1.5, "3", None])
def test_agent_loop_config_rejects_bool_and_invalid_types(field_name: str, value: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        AgentLoopConfig(**{field_name: value})  # type: ignore[arg-type]


def test_run_state_is_deeply_immutable_and_new_turn_resets_turn_values() -> None:
    previous_message = Message(role="assistant", parts=(TextPart("previous"),))
    state = RunState(
        run_id="run-1",
        turn_id="turn-1",
        messages=(previous_message,),
        iteration_count=4,
        tool_call_count=2,
        consecutive_unknown_tools=2,
        usage=Usage(input_tokens=8, output_tokens=5),
        status=RunStatus.FAILED,
        termination_reason=TerminationReason.MAX_ITERATIONS,
    )

    next_state = state.new_turn("turn-2", "continue")

    assert next_state is not state
    assert next_state.messages[:1] == (previous_message,)
    assert next_state.messages[-1] == Message(role="user", parts=(TextPart("continue"),))
    assert next_state.iteration_count == 0
    assert next_state.tool_call_count == 0
    assert next_state.consecutive_unknown_tools == 0
    assert next_state.usage == Usage()
    assert next_state.status is RunStatus.RUNNING
    assert next_state.termination_reason is None

    with pytest.raises(FrozenInstanceError):
        next_state.messages = ()  # type: ignore[misc]
    with pytest.raises((AttributeError, TypeError)):
        next_state.messages.append(previous_message)  # type: ignore[attr-defined]
    with pytest.raises(TypeError):
        next_state.usage.details.update({"secret": "blocked"})


def test_snapshot_is_safe_and_does_not_expose_conversation() -> None:
    state = RunState(
        run_id="run-1",
        turn_id="turn-1",
        messages=(Message(role="user", parts=(TextPart("secret conversation"),)),),
        usage=Usage(input_tokens=2, output_tokens=3),
        status=RunStatus.COMPLETED,
        termination_reason=TerminationReason.FINAL_ANSWER,
    )

    snapshot = RunSnapshot.from_state(state)
    payload = snapshot.to_dict()

    assert payload["run_id"] == "run-1"
    assert payload["status"] == "completed"
    assert "messages" not in payload
    assert "secret conversation" not in snapshot.to_json()
    assert "native_items" not in snapshot.to_json()


def test_turn_result_is_terminal_and_serializable_without_reasoning_history() -> None:
    result = TurnResult(
        run_id="run-1",
        turn_id="turn-1",
        status=RunStatus.COMPLETED,
        termination_reason=TerminationReason.FINAL_ANSWER,
        final_text="answer",
        usage=Usage(input_tokens=1, output_tokens=2),
        iteration_count=1,
        tool_call_count=0,
    )

    assert result.to_dict()["final_text"] == "answer"
    assert "reasoning" not in result.to_json()
    with pytest.raises(FrozenInstanceError):
        result.final_text = "changed"  # type: ignore[misc]


def test_public_execution_names_are_owned_by_core() -> None:
    assert AgentLoop is not None
    assert AgentTurnExecution is not None
