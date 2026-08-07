from __future__ import annotations

import asyncio
import inspect
import json
from dataclasses import dataclass, field, fields
from typing import Any

import pytest

from uthcode.core.agent import (
    AgentExecutionSegment,
    AgentLoop,
    AgentLoopConfig,
    AssistantMessageKind,
    ExecutionBoundary,
    RunState,
    RunStatus,
    TerminationReason,
)
from uthcode.core.agent_events import (
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
    TurnPaused,
    TurnPausing,
    TurnResumed,
    TurnStarted,
    UsageUpdated,
    UserInputRequested,
    agent_event_from_json,
)
from uthcode.core.interaction import (
    ASK_USER_TOOL_DEFINITION,
    PauseKind,
    RetryProviderResponse,
    ResumeTurnResponse,
    QuestionKind,
    UserInputRequest,
    UserInputResponse,
    UserQuestion,
)
from uthcode.core.provider import (
    AuthenticationError,
    CancellationToken,
    FinishReason,
    GenerationCompleted,
    GenerationRequest,
    InvalidProviderResponseError,
    Message,
    MissingSecretError,
    NetworkError,
    ProviderConfigurationError,
    ProviderError,
    ProviderIdentity,
    ProviderResponse,
    RateLimitError,
    ReasoningDelta as ProviderReasoningDelta,
    TextDelta,
    TextPart,
    ToolCallArgumentsDelta,
    ToolCallPart,
    ToolCallStarted,
    ToolDefinition,
    ToolResultPart,
    Usage,
)
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
        self.started.append(str(arguments.get("value", "missing")))
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


@dataclass
class PauseAwareTool:
    name: str
    started: list[str] = field(default_factory=list)
    entered: asyncio.Event = field(default_factory=asyncio.Event)
    release: asyncio.Event = field(default_factory=asyncio.Event)

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
        del cancellation
        self.started.append(str(arguments["value"]))
        self.entered.set()
        await self.release.wait()
        return ToolExecutionResult(str(arguments["value"]))


class PausableProvider:
    def __init__(self, response: GenerationCompleted) -> None:
        self.identity = ProviderIdentity("fake", "pause", "fake-model")
        self.response = response
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.call_count = 0
        self.requests: list[GenerationRequest] = []

    async def stream(self, request: GenerationRequest, *, cancellation: CancellationToken):
        self.requests.append(request)
        index = self.call_count
        self.call_count += 1
        if index == 0:
            self.entered.set()
            yield ProviderReasoningDelta("partial reasoning")
            yield TextDelta("partial text")
            await self.release.wait()
            cancellation.raise_if_cancelled()
        yield self.response


def _loop(
    provider,
    tools: tuple[Tool, ...] = (),
    *,
    config: AgentLoopConfig | None = None,
    descriptions: dict[str, str] | None = None,
) -> AgentLoop:
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


def _start(loop: AgentLoop, *, ask: bool = False, run_id: str = "run-1", turn_id: str = "turn-1"):
    definitions = None
    if ask:
        definitions = loop._tool_registry.definitions() + (ASK_USER_TOOL_DEFINITION,)
    return loop.start_turn(
        RunState.initial(run_id),
        "hello",
        turn_id=turn_id,
        tool_definitions=definitions,
    )


async def _drive(
    execution,
    *,
    response_for_pause=None,
) -> tuple[list[Any], Any, list[AgentExecutionSegment]]:
    events: list[Any] = []
    segments: list[AgentExecutionSegment] = []
    response = None
    while True:
        segment = await execution.run_segment(
            pause_signal=CancellationToken(),
            response=response,
        )
        segments.append(segment)
        events.extend(segment.events)
        if segment.terminal:
            assert segment.result is not None
            return events, segment.result, segments
        assert segment.continuation is not None
        pause = segment.continuation.pending_pause
        assert pause is not None
        if response_for_pause is None:
            raise AssertionError(f"unexpected pause: {pause.kind}")
        response = response_for_pause(pause)


def _resume_response(pause):
    if pause.kind is PauseKind.USER_REQUESTED:
        return ResumeTurnResponse(pause.pause_id, pause.run_id, pause.turn_id)
    if pause.kind is PauseKind.PROVIDER_UNAVAILABLE:
        return RetryProviderResponse(pause.pause_id, pause.run_id, pause.turn_id)
    request = pause.user_input_request
    assert request is not None
    answers = {question.question_id: ["Ada"] for question in request.questions}
    return UserInputResponse(
        pause.pause_id,
        pause.run_id,
        pause.turn_id,
        pause.tool_call_id,
        answers,
    )


@pytest.mark.asyncio
async def test_normal_answer_is_one_terminal_segment_with_authoritative_usage() -> None:
    provider = ScriptedProvider([[_response(TextPart("answer"), usage=Usage(2, 3))]])
    execution = _start(_loop(provider))

    segment = await execution.run_segment(pause_signal=CancellationToken())

    assert segment.boundary is ExecutionBoundary.TERMINAL
    assert segment.terminal
    assert provider.call_count == 1
    assert segment.result is not None
    assert segment.result.status is RunStatus.COMPLETED
    assert segment.result.final_text == "answer"
    assert segment.result.iteration_count == 1
    assert segment.result.usage == Usage(2, 3)
    assert sum(isinstance(event, TurnStarted) for event in segment.events) == 1
    assert sum(isinstance(event, IterationStarted) for event in segment.events) == 1
    assert sum(isinstance(event, UsageUpdated) for event in segment.events) == 1
    assert sum(isinstance(event, TurnCompleted) for event in segment.events) == 1

    after_terminal = await execution.run_segment(pause_signal=CancellationToken())
    assert after_terminal.terminal
    assert after_terminal.events == ()
    assert after_terminal.result is segment.result


@pytest.mark.asyncio
async def test_async_request_preparer_pause_returns_boundary_before_provider() -> None:
    provider = ScriptedProvider([[_response(TextPart("done"), usage=Usage(2, 3))]])
    entered = asyncio.Event()
    release = asyncio.Event()

    async def prepare(messages, definitions):
        entered.set()
        await release.wait()
        return GenerationRequest(messages=messages, tools=definitions)

    registry = ToolRegistry()
    execution = AgentLoop(provider, registry, ToolExecutor(registry), prepare).start_turn(
        RunState.initial("run-1"), "hello", turn_id="turn-1"
    )
    pause_signal = CancellationToken()
    running = asyncio.create_task(execution.run_segment(pause_signal=pause_signal))
    await entered.wait()
    pause_signal.cancel()
    release.set()

    paused = await running

    assert paused.paused
    assert paused.continuation is not None
    assert paused.continuation.stage == "provider"
    assert paused.continuation.iteration == 1
    assert paused.continuation.pending_pause is not None
    assert provider.call_count == 0
    assert sum(isinstance(event, TurnStarted) for event in paused.events) == 1
    assert sum(isinstance(event, IterationStarted) for event in paused.events) == 1
    assert not any(isinstance(event, UsageUpdated) for event in paused.events)
    assert not hasattr(execution, "pending_pause")
    assert not hasattr(execution, "resume")
    assert not hasattr(execution, "pause")

    response = ResumeTurnResponse(
        paused.continuation.pending_pause.pause_id,
        "run-1",
        "turn-1",
    )
    resumed = await execution.run_segment(
        pause_signal=CancellationToken(),
        response=response,
    )
    assert resumed.terminal
    assert provider.call_count == 1
    assert sum(isinstance(event, IterationStarted) for event in resumed.events) == 0
    assert sum(isinstance(event, UsageUpdated) for event in resumed.events) == 1
    assert resumed.result is not None
    assert resumed.result.iteration_count == 1


@pytest.mark.asyncio
async def test_async_request_preparer_cancel_wins_without_provider_call() -> None:
    provider = ScriptedProvider([[_response(TextPart("must not run"))]])
    entered = asyncio.Event()
    release = asyncio.Event()

    async def prepare(messages, definitions):
        entered.set()
        await release.wait()
        return GenerationRequest(messages=messages, tools=definitions)

    registry = ToolRegistry()
    execution = AgentLoop(provider, registry, ToolExecutor(registry), prepare).start_turn(
        RunState.initial("run-1"), "hello", turn_id="turn-1"
    )
    signal = CancellationToken()
    running = asyncio.create_task(execution.run_segment(pause_signal=signal))
    await entered.wait()
    signal.cancel()
    assert execution.cancel() is True
    release.set()
    segment = await running

    assert segment.terminal
    assert segment.result is not None
    assert segment.result.status is RunStatus.CANCELLED
    assert provider.call_count == 0
    assert not any(isinstance(event, TurnPaused | TurnResumed) for event in segment.events)
    assert sum(isinstance(event, TurnCancelled) for event in segment.events) == 1


@pytest.mark.asyncio
async def test_async_request_preparer_failure_remains_internal_failure() -> None:
    provider = ScriptedProvider([[_response(TextPart("must not run"))]])

    async def prepare(messages, definitions):
        del messages, definitions
        raise RuntimeError("preparer failed")

    registry = ToolRegistry()
    execution = AgentLoop(provider, registry, ToolExecutor(registry), prepare).start_turn(
        RunState.initial("run-1"), "hello"
    )
    segment = await execution.run_segment(pause_signal=CancellationToken())

    assert segment.terminal
    assert segment.result is not None
    assert segment.result.termination_reason is TerminationReason.INTERNAL_ERROR
    assert provider.call_count == 0
    assert sum(isinstance(event, TurnFailed) for event in segment.events) == 1


@pytest.mark.asyncio
async def test_reasoning_tool_and_provider_events_preserve_authoritative_order() -> None:
    tool = RecordingTool("read", output="tool-result")
    call = ToolCallPart("call-1", "read", {"value": "secret"})
    provider = ScriptedProvider(
        [
            [
                ProviderReasoningDelta("think"),
                TextDelta("progress"),
                _response(TextPart("progress"), call, finish_reason=FinishReason.TOOL_CALLS, usage=Usage(1, 2)),
            ],
            [ProviderReasoningDelta("done"), _response(TextPart("final"), usage=Usage(3, 4))],
        ]
    )
    execution = _start(_loop(provider, (tool,), descriptions={"read": "read one"}))

    events, result, segments = await _drive(execution)

    assert result.status is RunStatus.COMPLETED
    assert len(segments) == 1
    assert provider.call_count == 2
    assert tool.started == ["secret"]
    assert tool.peak_active == 1
    assert provider.requests[1].messages[-1].parts == (ToolResultPart("call-1", "tool-result"),)
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
    assert sum(isinstance(event, (TurnCompleted, TurnFailed, TurnCancelled)) for event in events) == 1
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
    provider = ScriptedProvider([[_response(*calls, finish_reason=FinishReason.TOOL_CALLS)], [_response(TextPart("done"))]])
    events, result, _ = await _drive(_start(_loop(provider, (first, second))))

    assert result.status is RunStatus.COMPLETED
    assert first.started == ["one"]
    assert second.started == ["two"]
    assert first.peak_active == second.peak_active == 1
    assert [event.tool_call_id for event in events if isinstance(event, ToolFinished)] == ["call-1", "call-2"]


@pytest.mark.asyncio
async def test_tool_errors_close_every_original_call_id_and_continue() -> None:
    failing = RecordingTool("failing", error=True)
    calls = (
        ToolCallPart("unknown", "missing", {"value": "secret"}),
        ToolCallPart("invalid", "failing", {}),
        ToolCallPart("error", "failing", {"value": "three"}),
    )
    provider = ScriptedProvider([[_response(*calls, finish_reason=FinishReason.TOOL_CALLS)], [_response(TextPart("corrected"))]])
    events, result, _ = await _drive(_start(_loop(provider, (failing,))))

    assert result.final_text == "corrected"
    assert [part.tool_call_id for part in provider.requests[1].messages[-1].parts] == ["unknown", "invalid", "error"]
    assert all(part.is_error for part in provider.requests[1].messages[-1].parts)
    assert failing.started == ["three"]
    assert any(isinstance(event, ToolFinished) and event.status == "failed" for event in events)


@pytest.mark.asyncio
async def test_max_limits_close_tool_batch_before_terminal_failure() -> None:
    calls = (
        ToolCallPart("one", "missing", {}),
        ToolCallPart("two", "missing", {}),
    )
    provider = ScriptedProvider([[_response(*calls, finish_reason=FinishReason.TOOL_CALLS)]])
    execution = _start(
        _loop(provider, config=AgentLoopConfig(max_tool_calls_per_iteration=1))
    )
    events, result, _ = await _drive(execution)

    assert result.termination_reason is TerminationReason.MAX_TOOL_CALLS
    assert [event.tool_call_id for event in events if isinstance(event, ToolFinished)] == ["one", "two"]
    batch = [event for event in events if isinstance(event, ToolBatchFinished)]
    assert len(batch) == 1
    assert batch[0].status == "failed"


@pytest.mark.asyncio
async def test_provider_partial_protocol_failure_does_not_commit_message_or_usage() -> None:
    scripts = [
        [TextDelta("partial"), ToolCallStarted("partial", "read"), ToolCallArgumentsDelta("partial", "{}")],
        [ProviderReasoningDelta("partial-2")],
    ]
    provider = ScriptedProvider(scripts)
    execution = _start(_loop(provider))
    segment = await execution.run_segment(pause_signal=CancellationToken())

    assert segment.terminal
    assert segment.result is not None
    assert segment.result.termination_reason is TerminationReason.INVALID_PROVIDER_RESPONSE
    assert execution.state.messages == (execution.state.messages[0],)
    assert execution.state.usage == Usage()
    assert not any(isinstance(event, UsageUpdated) for event in segment.events)


@pytest.mark.asyncio
async def test_provider_response_contradictions_fail_without_state_commit() -> None:
    call = ToolCallPart("call", "missing", {})
    provider = ScriptedProvider([[_response(call, finish_reason=FinishReason.STOP)]])
    execution = _start(_loop(provider))
    segment = await execution.run_segment(pause_signal=CancellationToken())

    assert segment.result is not None
    assert segment.result.termination_reason is TerminationReason.INVALID_PROVIDER_RESPONSE
    assert execution.state.messages == (execution.state.messages[0],)
    assert execution.state.usage == Usage()


@pytest.mark.asyncio
async def test_tool_cancel_closes_current_and_remaining_calls_without_next_provider() -> None:
    first = RecordingTool("first", output="one", delay=0.01)
    calls = (
        ToolCallPart("first", "first", {"value": "one"}),
        ToolCallPart("second", "missing", {}),
        ToolCallPart("third", "missing", {}),
    )
    provider = ScriptedProvider([[_response(*calls, finish_reason=FinishReason.TOOL_CALLS)]])
    execution = _start(_loop(provider, (first,)))
    signal = CancellationToken()
    running = asyncio.create_task(execution.run_segment(pause_signal=signal))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert execution.cancel() is True
    signal.cancel()
    segment = await running

    assert segment.result is not None
    assert segment.result.status is RunStatus.CANCELLED
    assert provider.call_count == 1
    finished = [event for event in segment.events if isinstance(event, ToolFinished)]
    assert [event.tool_call_id for event in finished] == ["first", "second", "third"]
    assert len([event for event in segment.events if isinstance(event, ToolBatchFinished)]) == 1
    assert sum(isinstance(event, TurnCancelled) for event in segment.events) == 1


@pytest.mark.asyncio
async def test_provider_pause_discards_partial_and_retries_same_iteration() -> None:
    provider = PausableProvider(_response(TextPart("done"), usage=Usage(2, 3)))
    execution = _start(_loop(provider))
    signal = CancellationToken()
    running = asyncio.create_task(execution.run_segment(pause_signal=signal))
    await provider.entered.wait()
    signal.cancel()
    provider.release.set()
    paused = await running

    assert paused.paused
    assert paused.continuation is not None
    assert paused.continuation.stage == "provider"
    assert provider.call_count == 1
    assert not any(isinstance(event, UsageUpdated) for event in paused.events)
    assert len(execution.state.messages) == 1
    pending = paused.continuation.pending_pause
    assert pending is not None and pending.kind is PauseKind.USER_REQUESTED

    resumed = await execution.run_segment(
        pause_signal=CancellationToken(),
        response=ResumeTurnResponse(pending.pause_id, pending.run_id, pending.turn_id),
    )
    assert resumed.terminal
    assert provider.call_count == 2
    assert resumed.result is not None
    assert resumed.result.iteration_count == 1
    assert sum(isinstance(event, IterationStarted) for event in paused.events + resumed.events) == 1
    assert sum(isinstance(event, UsageUpdated) for event in paused.events + resumed.events) == 1
    assert len(execution.state.messages) == 2


@pytest.mark.asyncio
async def test_tool_pause_waits_for_current_call_and_continues_fifo() -> None:
    first = PauseAwareTool("first")
    second = RecordingTool("second", output="two")
    calls = (
        ToolCallPart("first-1", "first", {"value": "one"}),
        ToolCallPart("second-1", "second", {"value": "two"}),
    )
    provider = ScriptedProvider([[_response(*calls, finish_reason=FinishReason.TOOL_CALLS)], [_response(TextPart("done"))]])
    execution = _start(_loop(provider, (first, second)))
    signal = CancellationToken()
    running = asyncio.create_task(execution.run_segment(pause_signal=signal))
    await first.entered.wait()
    signal.cancel()
    first.release.set()
    paused = await running

    assert paused.paused
    assert first.started == ["one"]
    assert second.started == []
    assert [event.tool_call_id for event in paused.events if isinstance(event, ToolFinished)] == ["first-1"]
    pending = paused.continuation.pending_pause
    assert pending is not None and pending.kind is PauseKind.USER_REQUESTED

    resumed = await execution.run_segment(
        pause_signal=CancellationToken(),
        response=ResumeTurnResponse(pending.pause_id, pending.run_id, pending.turn_id),
    )
    assert resumed.terminal
    assert second.started == ["two"]
    assert provider.call_count == 2
    all_events = paused.events + resumed.events
    assert len([event for event in all_events if isinstance(event, ToolBatchStarted)]) == 1
    assert [event.tool_call_id for event in all_events if isinstance(event, ToolFinished)] == [
        "first-1",
        "second-1",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure, expected_reason",
    (
        (AuthenticationError("bad credentials"), TerminationReason.PROVIDER_ERROR),
        (ProviderConfigurationError("bad configuration"), TerminationReason.PROVIDER_ERROR),
        (MissingSecretError("secret"), TerminationReason.PROVIDER_ERROR),
        (InvalidProviderResponseError("invalid"), TerminationReason.INVALID_PROVIDER_RESPONSE),
        (ProviderError("other"), TerminationReason.PROVIDER_ERROR),
    ),
)
async def test_non_recoverable_provider_errors_fail_without_pause(failure, expected_reason) -> None:
    provider = ScriptedProvider([failure])
    segment = await _start(_loop(provider)).run_segment(pause_signal=CancellationToken())

    assert segment.result is not None
    assert segment.result.termination_reason is expected_reason
    assert not any(isinstance(event, TurnPaused) for event in segment.events)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure, reason", ((NetworkError("offline"), "network_error"), (RateLimitError("busy"), "rate_limited")))
async def test_network_and_rate_limit_return_retry_pause_without_new_iteration(failure, reason) -> None:
    provider = ScriptedProvider([failure, [_response(TextPart("done"), usage=Usage(1, 1))]])
    execution = _start(_loop(provider))
    paused = await execution.run_segment(pause_signal=CancellationToken())

    assert paused.paused
    pause = paused.continuation.pending_pause
    assert pause is not None
    assert pause.kind is PauseKind.PROVIDER_UNAVAILABLE
    assert pause.reason.value == reason
    resumed = await execution.run_segment(
        pause_signal=CancellationToken(),
        response=RetryProviderResponse(pause.pause_id, pause.run_id, pause.turn_id),
    )
    assert resumed.terminal
    assert provider.call_count == 2
    all_events = paused.events + resumed.events
    assert [event.iteration for event in all_events if isinstance(event, IterationStarted)] == [1]
    assert len([event for event in all_events if isinstance(event, UsageUpdated)]) == 1


@pytest.mark.asyncio
async def test_network_pause_cancel_wins_without_resume() -> None:
    provider = ScriptedProvider([NetworkError("offline")])
    execution = _start(_loop(provider))
    paused = await execution.run_segment(pause_signal=CancellationToken())
    assert paused.paused
    assert execution.cancel() is True
    terminal = await execution.run_segment(pause_signal=CancellationToken())

    assert terminal.result is not None
    assert terminal.result.status is RunStatus.CANCELLED
    assert not any(isinstance(event, TurnResumed) for event in paused.events + terminal.events)
    assert sum(isinstance(event, TurnCancelled) for event in terminal.events) == 1


def _ask_request() -> UserInputRequest:
    return UserInputRequest(
        (UserQuestion("answer", "Answer", "What should be used?", QuestionKind.TEXT),)
    )


@pytest.mark.asyncio
async def test_ask_user_pause_and_answer_uses_original_call_id_and_fifo() -> None:
    request = _ask_request()
    ask_call = ToolCallPart("ask-1", "AskUserQuestion", request.to_dict())
    later_call = ToolCallPart("later-1", "missing", {})
    provider = ScriptedProvider([[_response(ask_call, later_call, finish_reason=FinishReason.TOOL_CALLS)], [_response(TextPart("done"))]])
    execution = _start(_loop(provider), ask=True)
    paused = await execution.run_segment(pause_signal=CancellationToken())

    assert paused.paused
    assert any(isinstance(event, UserInputRequested) for event in paused.events)
    assert any(isinstance(event, TurnPaused) for event in paused.events)
    pause = paused.continuation.pending_pause
    assert pause is not None
    assert pause.kind is PauseKind.USER_INPUT_REQUIRED
    assert pause.tool_call_id == "ask-1"
    before = paused.continuation
    for bad_ids in (
        ("wrong-pause", pause.run_id, pause.turn_id, "ask-1"),
        (pause.pause_id, "wrong-run", pause.turn_id, "ask-1"),
        (pause.pause_id, pause.run_id, "wrong-turn", "ask-1"),
        (pause.pause_id, pause.run_id, pause.turn_id, "wrong-call"),
    ):
        with pytest.raises(ValueError):
            await execution.run_segment(
                pause_signal=CancellationToken(),
                response=UserInputResponse(*bad_ids, {"answer": ["Ada"]}),
            )
        assert execution._continuation is before
        assert provider.call_count == 1
    response = UserInputResponse(pause.pause_id, pause.run_id, pause.turn_id, "ask-1", {"answer": ["Ada"]})
    resumed = await execution.run_segment(pause_signal=CancellationToken(), response=response)

    assert resumed.terminal
    assert provider.call_count == 2
    all_events = paused.events + resumed.events
    assert [event.tool_call_id for event in all_events if isinstance(event, ToolStarted)] == ["ask-1", "later-1"]
    assert [event.tool_call_id for event in all_events if isinstance(event, ToolFinished)] == ["ask-1", "later-1"]
    tool_message = provider.requests[1].messages[-1]
    assert [part.tool_call_id for part in tool_message.parts] == ["ask-1", "later-1"]
    assert tool_message.parts[0].is_error is False
    assert json.loads(tool_message.parts[0].content) == {"answers": {"answer": ["Ada"]}}


@pytest.mark.asyncio
async def test_ask_user_cancel_closes_current_and_remaining_original_ids() -> None:
    request = _ask_request()
    calls = (
        ToolCallPart("ask-1", "AskUserQuestion", request.to_dict()),
        ToolCallPart("later-1", "missing", {}),
    )
    provider = ScriptedProvider([[_response(*calls, finish_reason=FinishReason.TOOL_CALLS)]])
    execution = _start(_loop(provider), ask=True)
    paused = await execution.run_segment(pause_signal=CancellationToken())
    assert paused.paused
    assert execution.cancel() is True
    terminal = await execution.run_segment(pause_signal=CancellationToken())

    assert terminal.result is not None
    assert terminal.result.status is RunStatus.CANCELLED
    all_events = paused.events + terminal.events
    finished = [event for event in all_events if isinstance(event, ToolFinished)]
    assert [event.tool_call_id for event in finished] == ["ask-1", "later-1"]
    assert [event.status for event in finished] == ["cancelled", "cancelled"]
    batches = [event for event in all_events if isinstance(event, ToolBatchFinished)]
    assert len(batches) == 1 and batches[0].status == "cancelled"
    assert sum(isinstance(event, TurnCancelled) for event in all_events) == 1
    assert provider.call_count == 1
    assert [part.tool_call_id for part in execution.state.messages[-1].parts] == ["ask-1", "later-1"]


@pytest.mark.asyncio
async def test_invalid_response_ids_do_not_change_continuation_or_provider_calls() -> None:
    provider = ScriptedProvider([NetworkError("offline"), [_response(TextPart("done"))]])
    execution = _start(_loop(provider), run_id="run-1", turn_id="turn-1")
    paused = await execution.run_segment(pause_signal=CancellationToken())
    pause = paused.continuation.pending_pause
    assert pause is not None
    before = paused.continuation
    with pytest.raises(ValueError):
        await execution.run_segment(pause_signal=CancellationToken())
    assert execution._continuation is before
    assert provider.call_count == 1
    invalid = (
        RetryProviderResponse("wrong-pause", pause.run_id, pause.turn_id),
        RetryProviderResponse(pause.pause_id, "wrong-run", pause.turn_id),
        RetryProviderResponse(pause.pause_id, pause.run_id, "wrong-turn"),
        ResumeTurnResponse(pause.pause_id, pause.run_id, pause.turn_id),
    )
    for response in invalid:
        with pytest.raises((TypeError, ValueError)):
            await execution.run_segment(pause_signal=CancellationToken(), response=response)
        assert execution._continuation is before
        assert provider.call_count == 1

    resumed = await execution.run_segment(
        pause_signal=CancellationToken(),
        response=RetryProviderResponse(pause.pause_id, pause.run_id, pause.turn_id),
    )
    assert resumed.terminal
    assert provider.call_count == 2
    duplicate = await execution.run_segment(pause_signal=CancellationToken())
    assert duplicate.events == ()
    assert duplicate.result is resumed.result


@pytest.mark.asyncio
async def test_segment_event_sink_is_temporary_and_core_keeps_only_event_facts() -> None:
    provider = ScriptedProvider([NetworkError("offline")])
    execution = _start(_loop(provider))
    emitted: list[object] = []

    def sink(event: object) -> None:
        emitted.append(event)

    paused = await execution.run_segment(
        pause_signal=CancellationToken(),
        event_sink=sink,
    )

    assert paused.paused
    assert emitted == list(paused.events)
    slots = set(getattr(type(execution), "__slots__", ()))
    assert "event_sink" not in slots
    assert "_event_sink" not in slots
    assert "_segment_event_buffer" not in slots
    assert not any(getattr(execution, slot, None) is sink for slot in slots)
    assert not any("Future" in repr(value) or "Task" in repr(value) for value in fields(paused.continuation))


@pytest.mark.asyncio
async def test_continuation_is_explicit_business_facts_and_core_has_no_waiter_api() -> None:
    provider = ScriptedProvider([NetworkError("offline")])
    execution = _start(_loop(provider))
    paused = await execution.run_segment(pause_signal=CancellationToken())

    assert isinstance(paused, AgentExecutionSegment)
    assert paused.paused
    continuation = paused.continuation
    assert continuation is not None
    assert [item.name for item in fields(continuation)] == [
        "stage",
        "iteration",
        "provider_retry_pending",
        "assistant_tool_message",
        "tool_calls",
        "completed_tool_results",
        "next_tool_index",
        "pending_pause",
    ]
    assert all("asyncio" not in repr(value) for value in fields(continuation))
    assert not any(
        name in dir(execution)
        for name in ("pending_pause", "pause", "resume", "_resume_future", "_wait_for_pause")
    )
    slots = set(getattr(type(execution), "__slots__", ()))
    assert not {"_queue", "_task", "_result_future", "_resume_future", "_waiter"} & slots
    assert execution._active_segment_signal is None
    assert inspect.iscoroutinefunction(execution.run_segment)


@pytest.mark.asyncio
async def test_terminal_cancel_has_one_terminal_and_no_events_after_boundary() -> None:
    provider = ScriptedProvider([[_response(TextPart("done"))]])
    execution = _start(_loop(provider))
    first = await execution.run_segment(pause_signal=CancellationToken())
    assert first.terminal
    assert execution.cancel() is False
    after_cancel = await execution.run_segment(pause_signal=CancellationToken())
    assert after_cancel.events == ()
    assert after_cancel.result is first.result
    assert sum(isinstance(event, (TurnCompleted, TurnFailed, TurnCancelled)) for event in first.events) == 1
