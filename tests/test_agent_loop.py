from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any

import pytest

from uthcode.core.agent import (
    AgentLoop,
    AgentLoopConfig,
    AssistantMessageKind,
    RunState,
    RunStatus,
    TerminationReason,
)
from uthcode.core.agent_events import (
    AssistantMessageCompleted,
    AssistantMessageDelta,
    ReasoningDelta,
    ReasoningFinished,
    ReasoningStarted,
    ToolBatchFinished,
    ToolFinished,
    ToolStarted,
    TurnCancelled,
    TurnCompleted,
    TurnFailed,
    UsageUpdated,
)
from uthcode.core.provider import (
    CancellationToken,
    FinishReason,
    GenerationCancelled,
    GenerationCompleted,
    GenerationRequest,
    Message,
    ProviderError,
    ProviderIdentity,
    ProviderResponse,
    ReasoningDelta as ProviderReasoningDelta,
    TextDelta,
    TextPart,
    ToolCallPart,
    ToolDefinition,
    ToolResultPart,
    Usage,
)
from uthcode.core.agent_events import agent_event_from_json
from uthcode.core.tool import Tool, ToolExecutionResult, ToolExecutor, ToolRegistry


def _response(
    *parts: object,
    finish_reason: FinishReason = FinishReason.STOP,
    usage: Usage | None = None,
) -> GenerationCompleted:
    return GenerationCompleted(
        ProviderResponse(
            message=Message(role="assistant", parts=tuple(parts)),
            finish_reason=finish_reason,
            usage=usage or Usage(),
        )
    )


class ScriptedProvider:
    def __init__(self, scripts: list[object]) -> None:
        self.identity = ProviderIdentity("fake", "script", "fake-model")
        self.scripts = list(scripts)
        self.requests: list[GenerationRequest] = []
        self.call_count = 0

    async def stream(self, request: GenerationRequest, *, cancellation: CancellationToken):
        index = self.call_count
        self.call_count += 1
        self.requests.append(request)
        cancellation.raise_if_cancelled()
        script = self.scripts[index] if index < len(self.scripts) else self.scripts[-1]
        if isinstance(script, BaseException):
            raise script
        for event in script:
            cancellation.raise_if_cancelled()
            yield event


@dataclass
class RecordingTool:
    name: str
    output: str = "ok"
    error: bool = False
    started: list[str] = field(default_factory=list)
    active: int = 0
    peak_active: int = 0
    cancel_on_execute: bool = False
    delay: float = 0.0

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            self.name,
            parameters={
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
                "additionalProperties": False,
            },
        )

    async def execute(self, arguments, *, cancellation: CancellationToken) -> ToolExecutionResult:
        self.started.append(str(arguments["value"]))
        self.active += 1
        self.peak_active = max(self.peak_active, self.active)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            if self.cancel_on_execute:
                cancellation.cancel()
            return ToolExecutionResult(self.output, self.error)
        finally:
            self.active -= 1


def _loop(
    provider: ScriptedProvider,
    tools: tuple[Tool, ...] = (),
    *,
    config: AgentLoopConfig | None = None,
    descriptions: dict[str, str] | None = None,
):
    registry = ToolRegistry(tools)
    executor = ToolExecutor(registry)
    descriptions = descriptions or {}

    def prepare(messages: tuple[Message, ...], definitions: tuple[ToolDefinition, ...]) -> GenerationRequest:
        return GenerationRequest(messages=messages, tools=definitions)

    def describe(call: ToolCallPart) -> str:
        return descriptions.get(call.name, call.name)

    return AgentLoop(
        provider,
        registry,
        executor,
        prepare,
        config=config,
        tool_call_describer=describe,
    )


async def _collect(execution) -> tuple[list[Any], Any]:
    events = [event async for event in execution.events()]
    return events, await execution.result()


@pytest.mark.asyncio
async def test_normal_answer_has_one_provider_call_one_iteration_and_one_terminal() -> None:
    provider = ScriptedProvider([[TextDelta("partial"), _response(TextPart("answer"), usage=Usage(2, 3))]])
    execution = _loop(provider).start_turn(RunState.initial("run-1"), "hello", turn_id="turn-1")

    events, result = await _collect(execution)

    assert provider.call_count == 1
    assert result.status is RunStatus.COMPLETED
    assert result.termination_reason is TerminationReason.FINAL_ANSWER
    assert result.final_text == "answer"
    assert result.iteration_count == 1
    assert [type(event) for event in events].count(TurnCompleted) == 1
    assert not [event for event in events if isinstance(event, TurnFailed | TurnCancelled)]


@pytest.mark.asyncio
async def test_reasoning_segments_and_tool_result_are_ordered_and_authoritative() -> None:
    tool = RecordingTool("read", output="tool-result")
    secret = "W01-R1-UNIQUE-SECRET"
    call = ToolCallPart("call-1", "read", {"value": secret})
    provider = ScriptedProvider(
        [
            [
                ProviderReasoningDelta("think"),
                TextDelta("progress"),
                _response(
                    TextPart("progress"),
                    call,
                    finish_reason=FinishReason.TOOL_CALLS,
                    usage=Usage(1, 2),
                ),
            ],
            [
                ProviderReasoningDelta("done-think"),
                _response(TextPart("final"), usage=Usage(3, 4)),
            ],
        ]
    )

    execution = _loop(provider, (tool,), descriptions={"read": "read one"}).start_turn(
        RunState.initial("run-1"), "hello", turn_id="turn-1"
    )
    events, result = await _collect(execution)

    assert result.final_text == "final"
    assert provider.call_count == 2
    assert {(event.run_id, event.turn_id) for event in events} == {("run-1", "turn-1")}
    turn_started = next(event for event in events if event.event_type == "turn_started")
    assert isinstance(turn_started.message_id, str)
    assert turn_started.message_id
    assert provider.requests[1].messages[-1].role == "tool"
    requested_assistant = provider.requests[1].messages[-2]
    requested_call = next(
        part for part in requested_assistant.parts if isinstance(part, ToolCallPart)
    )
    assert requested_call.tool_call_id == "call-1"
    assert requested_call.arguments == {"value": secret}
    tool_message = provider.requests[1].messages[-1]
    assert isinstance(tool_message.parts[0], ToolResultPart)
    assert tool_message.parts[0].tool_call_id == "call-1"
    assert tool_message.parts[0].content == "tool-result"
    assert tool.started == [secret]
    authoritative_assistant = next(
        message for message in execution.state.messages if message.role == "assistant"
    )
    authoritative_call = next(
        part for part in authoritative_assistant.parts if isinstance(part, ToolCallPart)
    )
    assert authoritative_call.tool_call_id == "call-1"
    assert authoritative_call.arguments == {"value": secret}
    assert [event.event_type for event in events if isinstance(event, (ReasoningStarted, ReasoningDelta, ReasoningFinished))] == [
        "reasoning_started",
        "reasoning_delta",
        "reasoning_finished",
        "reasoning_started",
        "reasoning_delta",
        "reasoning_finished",
    ]
    completed = [event for event in events if isinstance(event, AssistantMessageCompleted)]
    assert [event.kind for event in completed] == [AssistantMessageKind.PROGRESS, AssistantMessageKind.FINAL]
    assert completed[0].message.parts == (TextPart("progress"),)
    assert all(
        not isinstance(part, (ToolCallPart, ToolResultPart))
        for event in completed
        for part in event.message.parts
    )
    assistant_events = [
        event
        for event in events
        if isinstance(
            event,
            (ReasoningStarted, ReasoningDelta, ReasoningFinished, AssistantMessageDelta, AssistantMessageCompleted),
        )
    ]
    ids_by_iteration: dict[int, set[str]] = {}
    for event in assistant_events:
        ids_by_iteration.setdefault(event.iteration, set()).add(event.message_id)
    for event in events:
        assert agent_event_from_json(event.to_json()) == event
    assert set(ids_by_iteration) == {1, 2}
    assert all(len(message_ids) == 1 for message_ids in ids_by_iteration.values())
    assert ids_by_iteration[1].isdisjoint(ids_by_iteration[2])
    assert len({event.message_id for event in assistant_events}) == 2
    started = next(event for event in events if isinstance(event, ToolStarted))
    finished = next(event for event in events if isinstance(event, ToolFinished))
    assert (started.batch_id, started.tool_call_id, started.tool_name, started.command) == (
        finished.batch_id,
        finished.tool_call_id,
        finished.tool_name,
        finished.command,
    ) == ("batch-1", "call-1", "read", "read one")
    for event in events:
        encoded = json.dumps(event.to_dict(), ensure_ascii=False, sort_keys=True)
        assert secret not in encoded
        assert "arguments" not in encoded
    assert all("tool-result" not in event.to_json() for event in events if isinstance(event, ToolFinished))


@pytest.mark.asyncio
async def test_message_ids_are_scoped_to_real_turns_and_runs() -> None:
    first_provider = ScriptedProvider([[_response(TextPart("first"))]])
    first_execution = _loop(first_provider).start_turn(
        RunState.initial("a"), "hello", turn_id="b:turn:c"
    )
    first_events, _ = await _collect(first_execution)
    assert {(event.run_id, event.turn_id) for event in first_events} == {("a", "b:turn:c")}

    second_provider = ScriptedProvider([[_response(TextPart("second"))]])
    second_execution = _loop(second_provider).start_turn(
        RunState.initial("a:turn:b"), "hello", turn_id="c"
    )
    second_events, _ = await _collect(second_execution)
    assert {(event.run_id, event.turn_id) for event in second_events} == {("a:turn:b", "c")}

    third_provider = ScriptedProvider([[_response(TextPart("third"))]])
    third_execution = _loop(third_provider).start_turn(
        RunState.initial("run-2"), "hello", turn_id="turn-1"
    )
    third_events, _ = await _collect(third_execution)
    assert {(event.run_id, event.turn_id) for event in third_events} == {("run-2", "turn-1")}

    first_started = next(event for event in first_events if event.event_type == "turn_started")
    second_started = next(event for event in second_events if event.event_type == "turn_started")
    third_started = next(event for event in third_events if event.event_type == "turn_started")
    user_message_ids = {
        first_started.message_id,
        second_started.message_id,
        third_started.message_id,
    }
    assert len(user_message_ids) == 3
    assert all(isinstance(message_id, str) and message_id for message_id in user_message_ids)

    first_assistant = next(event for event in first_events if isinstance(event, AssistantMessageCompleted))
    second_assistant = next(event for event in second_events if isinstance(event, AssistantMessageCompleted))
    third_assistant = next(event for event in third_events if isinstance(event, AssistantMessageCompleted))
    assistant_message_ids = {
        first_assistant.message_id,
        second_assistant.message_id,
        third_assistant.message_id,
    }
    assert len(assistant_message_ids) == 3
    assert all(isinstance(message_id, str) and message_id for message_id in assistant_message_ids)
    for events in (first_events, second_events, third_events):
        for event in events:
            assert agent_event_from_json(event.to_json()) == event


@pytest.mark.asyncio
async def test_multiple_tools_are_fifo_and_never_parallel() -> None:
    first = RecordingTool("first", output="one", delay=0.01)
    second = RecordingTool("second", output="two", delay=0.01)
    calls = (
        ToolCallPart("call-1", "first", {"value": "one"}),
        ToolCallPart("call-2", "second", {"value": "two"}),
    )
    provider = ScriptedProvider(
        [[_response(*calls, finish_reason=FinishReason.TOOL_CALLS)], [_response(TextPart("done"))]]
    )
    execution = _loop(provider, (first, second)).start_turn(RunState.initial("run-1"), "hello")

    events, result = await _collect(execution)

    assert result.status is RunStatus.COMPLETED
    assert first.started == ["one"]
    assert second.started == ["two"]
    assert first.peak_active == second.peak_active == 1
    finished = [event for event in events if isinstance(event, ToolFinished)]
    assert [event.tool_call_id for event in finished] == ["call-1", "call-2"]


@pytest.mark.asyncio
async def test_tool_errors_and_truncated_results_are_recoverable() -> None:
    failing = RecordingTool("failing", error=True)
    calls = (
        ToolCallPart("unknown", "missing", {"value": "secret"}),
        ToolCallPart("invalid", "failing", {}),
        ToolCallPart("error", "failing", {"value": "three"}),
    )
    provider = ScriptedProvider(
        [[_response(*calls, finish_reason=FinishReason.TOOL_CALLS)], [_response(TextPart("corrected"))]]
    )
    execution = _loop(provider, (failing,)).start_turn(RunState.initial("run-1"), "hello")

    events, result = await _collect(execution)

    assert result.final_text == "corrected"
    tool_message = provider.requests[1].messages[-1]
    assert [part.tool_call_id for part in tool_message.parts] == ["unknown", "invalid", "error"]
    assert all(part.is_error for part in tool_message.parts)
    assert failing.started == ["three"]
    assert any(isinstance(event, ToolFinished) and event.status == "failed" for event in events)


@pytest.mark.asyncio
async def test_truncated_tool_output_is_closed_and_available_to_next_provider_request() -> None:
    tool = RecordingTool("large", output="x" * 10_500)
    call = ToolCallPart("large-call", "large", {"value": "input"})
    provider = ScriptedProvider(
        [[_response(call, finish_reason=FinishReason.TOOL_CALLS)], [_response(TextPart("done"))]]
    )
    execution = _loop(provider, (tool,)).start_turn(RunState.initial("run-1"), "hello")

    events, result = await _collect(execution)

    assert result.status is RunStatus.COMPLETED
    content = provider.requests[1].messages[-1].parts[0].content
    assert len(content) <= 10_000
    assert content.endswith("[Output truncated to 10000 characters]")
    assert all("Output truncated" not in event.to_json() for event in events if isinstance(event, ToolFinished))


@pytest.mark.asyncio
async def test_unknown_streak_resets_on_known_tool_and_fails_after_closed_batch_limit() -> None:
    known = RecordingTool("known")
    provider = ScriptedProvider(
        [
            [_response(ToolCallPart("u1", "missing", {"value": "x"}), finish_reason=FinishReason.TOOL_CALLS)],
            [_response(ToolCallPart("k", "known", {"value": "x"}), finish_reason=FinishReason.TOOL_CALLS)],
            [_response(ToolCallPart("u2", "missing", {"value": "x"}), finish_reason=FinishReason.TOOL_CALLS)],
            [_response(ToolCallPart("u3", "missing", {"value": "x"}), finish_reason=FinishReason.TOOL_CALLS)],
            [_response(ToolCallPart("u4", "missing", {"value": "x"}), finish_reason=FinishReason.TOOL_CALLS)],
        ]
    )
    execution = _loop(provider, (known,)).start_turn(RunState.initial("run-1"), "hello")

    events, result = await _collect(execution)

    assert result.status is RunStatus.FAILED
    assert result.termination_reason is TerminationReason.CONSECUTIVE_UNKNOWN_TOOLS
    assert provider.call_count == 5
    assert known.started == ["x"]
    assert [event.tool_call_id for event in events if isinstance(event, ToolFinished)] == ["u1", "k", "u2", "u3", "u4"]


@pytest.mark.asyncio
async def test_tool_call_limit_zero_executes_entire_batch_and_closes_each_id() -> None:
    tool = RecordingTool("known")
    calls = tuple(ToolCallPart(f"call-{index}", "known", {"value": str(index)}) for index in range(17))
    provider = ScriptedProvider([[_response(*calls, finish_reason=FinishReason.TOOL_CALLS)]])
    execution = _loop(provider, (tool,)).start_turn(RunState.initial("run-1"), "hello")

    events, result = await _collect(execution)

    assert result.termination_reason is TerminationReason.MAX_TOOL_CALLS
    assert tool.started == []
    assert [event.tool_call_id for event in events if isinstance(event, ToolFinished)] == [call.tool_call_id for call in calls]
    tool_message = execution.state.messages[-1]
    assert [part.tool_call_id for part in tool_message.parts] == [call.tool_call_id for call in calls]


@pytest.mark.asyncio
async def test_incomplete_tool_calls_are_not_executed_but_are_closed() -> None:
    tool = RecordingTool("known")
    call = ToolCallPart("call-1", "known", {"value": "do-not-run"})
    provider = ScriptedProvider([[_response(call, finish_reason=FinishReason.LENGTH)]])
    execution = _loop(provider, (tool,)).start_turn(RunState.initial("run-1"), "hello")

    _, result = await _collect(execution)

    assert result.termination_reason is TerminationReason.MAX_OUTPUT_TOKENS
    assert tool.started == []
    assert execution.state.messages[-1].role == "tool"
    assert execution.state.messages[-1].parts[0].tool_call_id == "call-1"


@pytest.mark.asyncio
async def test_max_iterations_stops_after_closed_tool_batch() -> None:
    tool = RecordingTool("known")
    call = ToolCallPart("call-1", "known", {"value": "one"})
    provider = ScriptedProvider([[_response(call, finish_reason=FinishReason.TOOL_CALLS)]])
    execution = _loop(
        provider,
        (tool,),
        config=AgentLoopConfig(max_iterations=1),
    ).start_turn(RunState.initial("run-1"), "hello")

    _, result = await _collect(execution)

    assert result.termination_reason is TerminationReason.MAX_ITERATIONS
    assert provider.call_count == 1
    assert execution.state.messages[-1].role == "tool"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "script,reason",
    [
        ([TextDelta("partial")], TerminationReason.INVALID_PROVIDER_RESPONSE),
        ([TextDelta("partial"), _response(TextPart("done")), TextDelta("after")], TerminationReason.INVALID_PROVIDER_RESPONSE),
        ([TextDelta("partial"), _response(TextPart("done"), finish_reason=FinishReason.UNKNOWN)], TerminationReason.INVALID_PROVIDER_RESPONSE),
        ([TextDelta("partial"), _response(TextPart("done"), finish_reason=FinishReason.ERROR)], TerminationReason.PROVIDER_ERROR),
    ],
)
async def test_provider_protocol_errors_do_not_commit_partial_assistant(script: list[object], reason: TerminationReason) -> None:
    provider = ScriptedProvider([script])
    execution = _loop(provider).start_turn(RunState.initial("run-1"), "hello")

    _, result = await _collect(execution)

    assert result.status is RunStatus.FAILED
    assert result.termination_reason is reason
    assert [message.role for message in execution.state.messages] == ["user"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        GenerationCompleted(
            ProviderResponse(message=Message(role="user", parts=(TextPart("wrong role"),)))
        ),
        _response(
            ToolCallPart("duplicate", "one", {"value": "x"}),
            ToolCallPart("duplicate", "two", {"value": "y"}),
            finish_reason=FinishReason.TOOL_CALLS,
        ),
        _response(TextPart("wrong finish"), finish_reason=FinishReason.TOOL_CALLS),
    ],
)
async def test_provider_response_contradictions_fail_as_invalid_without_state_commit(
    response: GenerationCompleted,
) -> None:
    provider = ScriptedProvider([[response]])
    execution = _loop(provider).start_turn(RunState.initial("run-1"), "hello")

    _, result = await _collect(execution)

    assert result.termination_reason is TerminationReason.INVALID_PROVIDER_RESPONSE
    assert [message.role for message in execution.state.messages] == ["user"]


@pytest.mark.asyncio
async def test_provider_cancellation_discards_partial_conversation_and_has_one_cancelled_terminal() -> None:
    cancellation = CancellationToken()
    provider = ScriptedProvider([GenerationCancelled()])
    execution = _loop(provider).start_turn(
        RunState.initial("run-1"),
        "hello",
        cancellation=cancellation,
    )
    cancellation.cancel()

    events, result = await _collect(execution)

    assert result.status is RunStatus.CANCELLED
    assert sum(isinstance(event, TurnCancelled) for event in events) == 1
    assert not [event for event in events if isinstance(event, (TurnCompleted, TurnFailed))]
    assert [message.role for message in execution.state.messages] == ["user"]


@pytest.mark.asyncio
async def test_tool_cancellation_closes_current_and_remaining_calls_without_next_provider_call() -> None:
    cancelling = RecordingTool("first", cancel_on_execute=True)
    later = RecordingTool("later")
    calls = (
        ToolCallPart("call-1", "first", {"value": "one"}),
        ToolCallPart("call-2", "later", {"value": "two"}),
        ToolCallPart("call-3", "later", {"value": "three"}),
    )
    provider = ScriptedProvider([[_response(*calls, finish_reason=FinishReason.TOOL_CALLS)], [_response(TextPart("bad"))]])
    execution = _loop(provider, (cancelling, later)).start_turn(RunState.initial("run-1"), "hello")

    events, result = await _collect(execution)

    assert result.status is RunStatus.CANCELLED
    assert provider.call_count == 1
    assert cancelling.started == ["one"]
    assert later.started == []
    tool_message = execution.state.messages[-1]
    assert [part.tool_call_id for part in tool_message.parts] == ["call-1", "call-2", "call-3"]
    assert tool_message.parts[0].is_error is False
    assert tool_message.parts[1].is_error is True
    assert tool_message.parts[2].is_error is True
    assert sum(isinstance(event, TurnCancelled) for event in events) == 1


@pytest.mark.asyncio
async def test_middle_tool_cancellation_closes_the_later_calls_in_order() -> None:
    first = RecordingTool("first")
    cancelling = RecordingTool("cancelling", cancel_on_execute=True)
    later = RecordingTool("later")
    calls = (
        ToolCallPart("call-1", "first", {"value": "one"}),
        ToolCallPart("call-2", "cancelling", {"value": "two"}),
        ToolCallPart("call-3", "later", {"value": "three"}),
    )
    provider = ScriptedProvider([[_response(*calls, finish_reason=FinishReason.TOOL_CALLS)]])
    execution = _loop(provider, (first, cancelling, later)).start_turn(
        RunState.initial("run-1"), "hello"
    )

    events, result = await _collect(execution)

    assert result.status is RunStatus.CANCELLED
    assert provider.call_count == 1
    assert first.started == ["one"]
    assert cancelling.started == ["two"]
    assert later.started == []
    tool_message = execution.state.messages[-1]
    assert [part.tool_call_id for part in tool_message.parts] == ["call-1", "call-2", "call-3"]
    assert tool_message.parts[0].is_error is False
    assert tool_message.parts[1].is_error is False
    assert tool_message.parts[2].is_error is True
    assert sum(isinstance(event, TurnCancelled) for event in events) == 1


@pytest.mark.asyncio
async def test_usage_accumulates_only_authoritative_terminals_and_resets_next_turn() -> None:
    provider = ScriptedProvider(
        [
            [TextDelta("partial"), _response(TextPart("first"), usage=Usage(2, 3))],
            [_response(TextPart("second"), usage=Usage(5, 7))],
        ]
    )
    loop = _loop(provider)
    first = loop.start_turn(RunState.initial("run-1"), "first", turn_id="turn-1")
    first_events, first_result = await _collect(first)

    assert first_result.usage == Usage(input_tokens=2, output_tokens=3)
    assert [event.usage for event in first_events if isinstance(event, UsageUpdated)] == [Usage(2, 3)]

    second = loop.start_turn(first.state, "second", turn_id="turn-2")
    _, second_result = await _collect(second)
    assert second_result.usage == Usage(input_tokens=5, output_tokens=7)
    assert second.state.usage == Usage(input_tokens=5, output_tokens=7)


@pytest.mark.asyncio
async def test_events_has_one_consumer_and_result_can_be_read_repeatedly() -> None:
    provider = ScriptedProvider([[_response(TextPart("done"))]])
    execution = _loop(provider).start_turn(RunState.initial("run-1"), "hello")
    first_consumer = execution.events()
    events = [event async for event in first_consumer]
    with pytest.raises(RuntimeError):
        _ = [event async for event in execution.events()]
    first = await execution.result()
    second = await execution.result()
    assert first == second
    assert events[-1].event_type == "turn_completed"
