from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from collections.abc import AsyncIterator, Iterable
from pathlib import Path

import pytest

from uthcode.application import (
    AgentEvent,
    AgentRun,
    ApplicationRuntimeContext,
    EffectiveConfig,
    ModelProfile,
    ProviderKind,
    ProviderProfile,
    RunSnapshot,
    RunStatus,
    TextPart,
    TurnHandle,
    TurnResult,
    UthCodeApplication,
    create_application,
)
from uthcode.core.agent_events import (
    AssistantMessageDelta,
    AssistantMessageCompleted,
    AssistantMessageKind,
    BehaviorModeChanged,
    CompletionBlocked,
    IterationStarted,
    PlanProposed,
    TaskStateChanged,
    ReasoningDelta as AgentReasoningDelta,
    ToolBatchFinished,
    ToolFinished,
    ToolStarted,
    TurnCancelled,
    TurnCompleted,
    TurnFailed,
    TurnPaused,
    TurnResumed,
    TurnPausing,
    TerminationReason,
    UsageUpdated,
    UserSteeringApplied,
    UserSteeringRequested,
    TurnStarted,
    FailureReason,
)
from uthcode.core.context import ContextCompilationError
from uthcode.core.agent import AgentTurnExecution
from uthcode.core.interaction import (
    ASK_USER_TOOL_DEFINITION,
    PauseKind,
    PlanReviewChoice,
    PlanReviewResponse,
    RetryProviderResponse,
    ResumeTurnResponse,
    QuestionKind,
    UserInputRequest,
    UserInputResponse,
    UserQuestion,
)
from uthcode.core.planning import (
    BehaviorMode,
    PROPOSE_PLAN_TOOL_DEFINITION,
    RuntimeFeedbackKind,
    TODO_WRITE_TOOL_DEFINITION,
)
from uthcode.core.permission import (
    Effect,
    PermissionAction,
    PermissionEvaluator,
    PermissionMode,
    ResourceScope,
)
from uthcode.core.provider import (
    CancellationToken,
    FinishReason,
    GenerationCompleted,
    GenerationRequest,
    Message,
    ModelLimits,
    ProviderEvent,
    ProviderIdentity,
    ProviderResponse,
    ProviderError,
    NetworkError,
    ReasoningDelta as ProviderReasoningDelta,
    TextDelta,
    TextPart,
    ToolCallPart,
    ToolDefinition,
    ToolResultPart,
    Usage,
)
from uthcode.integrations.providers.fake import FakeProvider
from uthcode.integrations.tools.factory import create_default_tools
from uthcode.application.tools import ApplicationToolService
from uthcode.core.tool import ToolExecutionResult, ToolPlanningAccess, ToolPreparation


TEST_LIMITS = ModelLimits(max_input_tokens=1_000_000, source="test.fake")


def _response(
    *parts: object,
    finish_reason: FinishReason = FinishReason.STOP,
    usage: Usage | None = None,
) -> GenerationCompleted:
    return GenerationCompleted(
        ProviderResponse(
            message=Message("assistant", tuple(parts)),
            finish_reason=finish_reason,
            usage=usage or Usage(),
        )
    )


def _request_text(request: GenerationRequest) -> str:
    return "\n".join(
        part.text
        for message in request.messages
        for part in message.parts
        if isinstance(part, TextPart)
    )


def _is_context_message(message: Message) -> bool:
    return (
        message.role == "user"
        and bool(message.parts)
        and all(
            isinstance(part, TextPart) and part.text.startswith("[Context]\n")
            for part in message.parts
        )
    )


def _latest_user_text(request: GenerationRequest) -> str:
    for message in reversed(request.messages):
        if message.role == "user" and not _is_context_message(message):
            return "\n".join(
                part.text for part in message.parts if isinstance(part, TextPart)
            )
    return ""


def _context_text(request: GenerationRequest) -> str:
    return "\n".join(
        part.text
        for message in request.messages
        if _is_context_message(message)
        for part in message.parts
        if isinstance(part, TextPart)
    )


def _latest_message(request: GenerationRequest, role: str) -> Message:
    for message in reversed(request.messages):
        if message.role == role:
            return message
    raise AssertionError(f"request has no {role!r} message")


def _without_context(message: Message) -> Message:
    return Message(
        message.role,
        tuple(
            part
            for part in message.parts
            if not (
                isinstance(part, TextPart)
                and part.text.startswith("[Context]\n")
            )
        ),
        message.native_items,
    )


class _ScriptedProvider:
    def __init__(self, scripts: Iterable[Iterable[ProviderEvent]], *, model: str = "fake-model") -> None:
        self.identity = ProviderIdentity("fake", "script", model)
        self.scripts = tuple(tuple(script) for script in scripts)
        self.requests: list[GenerationRequest] = []

    def resolve_model_limits(self, _model: str) -> ModelLimits:
        return ModelLimits(max_input_tokens=1_000_000, source="test.runtime")

    async def stream(
        self,
        request: GenerationRequest,
        *,
        cancellation: CancellationToken,
    ) -> AsyncIterator[ProviderEvent]:
        self.requests.append(request)
        cancellation.raise_if_cancelled()
        index = min(len(self.requests) - 1, len(self.scripts) - 1)
        for event in self.scripts[index]:
            cancellation.raise_if_cancelled()
            yield event


class _RefreshingLimitsProvider(_ScriptedProvider):
    def __init__(self) -> None:
        super().__init__(
            (
                (
                    _response(
                        ToolCallPart("unknown-1", "MissingTool", {}),
                        finish_reason=FinishReason.TOOL_CALLS,
                    ),
                ),
                (_response(TextPart("first turn done")),),
                (_response(TextPart("second turn done")),),
            )
        )
        self.limit_resolutions: list[str] = []

    def resolve_model_limits(self, model: str) -> ModelLimits:
        self.limit_resolutions.append(model)
        limit = 300_000 if len(self.limit_resolutions) == 1 else 100_000
        return ModelLimits(max_input_tokens=limit, source="test.refreshing")


class _GatedProvider:
    def __init__(self, responses: Iterable[GenerationCompleted]) -> None:
        self.identity = ProviderIdentity("fake", "gated", "fake-model")
        self.responses = tuple(responses)
        self.requests: list[GenerationRequest] = []
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    def resolve_model_limits(self, _model: str) -> ModelLimits:
        return ModelLimits(max_input_tokens=1_000_000, source="test.runtime")

    async def stream(
        self,
        request: GenerationRequest,
        *,
        cancellation: CancellationToken,
    ) -> AsyncIterator[ProviderEvent]:
        self.requests.append(request)
        index = min(len(self.requests) - 1, len(self.responses) - 1)
        self.entered.set()
        yield ProviderReasoningDelta("partial")
        await self.release.wait()
        cancellation.raise_if_cancelled()
        yield self.responses[index]


class _StreamingGatedProvider:
    def __init__(self, response: GenerationCompleted) -> None:
        self.identity = ProviderIdentity("fake", "streaming-gated", "fake-model")
        self.response = response
        self.requests: list[GenerationRequest] = []
        self.partial_emitted = asyncio.Event()
        self.release = asyncio.Event()

    def resolve_model_limits(self, _model: str) -> ModelLimits:
        return ModelLimits(max_input_tokens=1_000_000, source="test.runtime")

    async def stream(
        self,
        request: GenerationRequest,
        *,
        cancellation: CancellationToken,
    ) -> AsyncIterator[ProviderEvent]:
        self.requests.append(request)
        cancellation.raise_if_cancelled()
        yield ProviderReasoningDelta("thinking")
        yield TextDelta("partial")
        self.partial_emitted.set()
        await self.release.wait()
        cancellation.raise_if_cancelled()
        yield self.response


class _FailThenProvider:
    def __init__(self, failure: ProviderError, response: GenerationCompleted) -> None:
        self.identity = ProviderIdentity("fake", "retry", "fake-model")
        self.failure = failure
        self.response = response
        self.requests: list[GenerationRequest] = []

    def resolve_model_limits(self, _model: str) -> ModelLimits:
        return ModelLimits(max_input_tokens=1_000_000, source="test.runtime")

    async def stream(
        self,
        request: GenerationRequest,
        *,
        cancellation: CancellationToken,
    ) -> AsyncIterator[ProviderEvent]:
        self.requests.append(request)
        if len(self.requests) == 1:
            raise self.failure
        cancellation.raise_if_cancelled()
        yield self.response


class _SteeringRaceProvider:
    def __init__(self, first_outcome: str) -> None:
        self.identity = ProviderIdentity("fake", "steering-race", "fake-model")
        self.first_outcome = first_outcome
        self.requests: list[GenerationRequest] = []
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    def resolve_model_limits(self, _model: str) -> ModelLimits:
        return ModelLimits(max_input_tokens=1_000_000, source="test.runtime")

    async def stream(
        self,
        request: GenerationRequest,
        *,
        cancellation: CancellationToken,
    ) -> AsyncIterator[ProviderEvent]:
        self.requests.append(request)
        if len(self.requests) == 1:
            self.entered.set()
            yield ProviderReasoningDelta("partial")
            await self.release.wait()
            if self.first_outcome == "cancelled":
                cancellation.raise_if_cancelled()
            elif self.first_outcome == "error":
                raise NetworkError("synthetic steering race")
            else:
                yield _response(TextPart("stale completion"))
            return
        cancellation.raise_if_cancelled()
        yield _response(TextPart("updated answer"))


class _ApplicationGateTool:
    def __init__(self, name: str = "Work", *, gated: bool = False) -> None:
        self._name = name
        self.gated = gated
        self.trace: list[str] = []
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    @property
    def definition(self):
        return ToolDefinition(
            self._name,
            parameters={
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
                "additionalProperties": False,
            },
        )

    @property
    def planning_access(self) -> ToolPlanningAccess:
        return ToolPlanningAccess.READ_ONLY

    def preflight(self, arguments) -> ToolPreparation:
        self.trace.append(f"preflight:{arguments['value']}")
        return ToolPreparation(
            PermissionAction(
                tool=self._name,
                action="execute",
                effect=Effect.READ,
                resource="workspace/item",
                scope=ResourceScope.INSIDE,
            ),
            arguments,
        )

    async def execute(self, arguments, *, cancellation: CancellationToken) -> ToolExecutionResult:
        cancellation.raise_if_cancelled()
        self.trace.append(f"execute:{arguments['value']}")
        self.entered.set()
        if self.gated:
            await self.release.wait()
        return ToolExecutionResult(str(arguments["value"]))


class _RecordingPermissionEvaluator(PermissionEvaluator):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[PermissionAction] = []

    def evaluate(self, action, mode=PermissionMode.DEFAULT, session_grants=()):
        self.calls.append(action)
        return super().evaluate(action, mode=mode, session_grants=session_grants)


@pytest.mark.asyncio
async def test_context_limits_resolve_once_per_turn_and_refresh_next_turn() -> None:
    provider = _RefreshingLimitsProvider()
    application = UthCodeApplication(provider)
    run = application.create_run(run_id="frozen-context-limits")

    first = await run.start_turn("first").result()
    second = await run.start_turn("second").result()

    assert first.status is RunStatus.COMPLETED
    assert second.status is RunStatus.COMPLETED
    assert provider.limit_resolutions == ["fake-model", "fake-model"]
    assert len(provider.requests) == 3
    assert [
        request.metadata["context_gate"]["effective_input_limit"]
        for request in provider.requests
    ] == [256_000, 256_000, 100_000]
    assert [
        request.metadata["context_budget"]["effective_input_source"]
        for request in provider.requests
    ] == ["default", "default", "provider"]


def test_application_status_uses_configured_context_window_before_first_turn() -> None:
    config = EffectiveConfig(
        default_model="configured/ref",
        providers={"configured": ProviderProfile("configured", ProviderKind.FAKE)},
        models={
            "configured/ref": ModelProfile(
                "configured/ref",
                "configured",
                "remote-configured",
                context_window=1_000_000,
            )
        },
    )
    application = UthCodeApplication(FakeProvider(), configuration=config)
    status = application.status().context_status
    assert status.available is False
    assert status.measurement == "unavailable"
    assert status.budget_tokens == 1_000_000


@pytest.mark.asyncio
async def test_context_compilation_failure_is_projected_without_provider_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _ScriptedProvider(((_response(TextPart("must not run")),),))
    application = UthCodeApplication(provider)

    def fail_compose(*_args: object, **_kwargs: object) -> object:
        raise ContextCompilationError(
            "context-secret traceback and raw provider body must stay private"
        )

    monkeypatch.setattr(
        application._context_service,
        "compose_generation_request",
        fail_compose,
    )
    result = await application.create_run().start_turn("context failure").result()

    assert result.status is RunStatus.FAILED
    assert result.failure_reason is FailureReason.CONTEXT_UNRESOLVABLE
    assert provider.requests == []
    serialized = result.to_json()
    assert "context-secret" not in serialized
    assert "traceback" not in serialized
    assert "raw provider body" not in serialized


async def _collect(handle: TurnHandle) -> list[AgentEvent]:
    return [event async for event in handle.events()]


async def _start_after_release(run: AgentRun, user_input: str) -> TurnHandle:
    for _ in range(200):
        try:
            return run.start_turn(user_input)
        except RuntimeError as exc:
            if "active Turn" not in str(exc):
                raise
            await asyncio.sleep(0)
    raise AssertionError("terminal Turn did not release the Run")


def _config() -> EffectiveConfig:
    return EffectiveConfig.single_model(
        "local/ref",
        provider_profile_id="local",
        provider_kind=ProviderKind.FAKE,
        remote_id="fake-model",
    )


def _context(workdir: Path) -> ApplicationRuntimeContext:
    return ApplicationRuntimeContext.from_system(
        workdir=workdir,
        platform_name="TestOS",
        platform_release="1.0",
        current_date="2026-08-06",
    )


@pytest.mark.asyncio
async def test_turn_can_start_without_an_event_loop_and_result_is_reusable() -> None:
    application = UthCodeApplication(
        FakeProvider(events=(_response(TextPart("answer")),), model_limits=TEST_LIMITS)
    )
    run = application.create_run(run_id="run-1")
    handle = run.start_turn("hello")

    assert isinstance(run, AgentRun)
    assert isinstance(handle, TurnHandle)
    assert isinstance(run.snapshot(), RunSnapshot)
    assert run.snapshot().status is RunStatus.RUNNING
    assert isinstance(await handle.result(), TurnResult)
    first = await handle.result()
    second = await handle.result()

    assert first is second
    assert first.status is RunStatus.COMPLETED
    assert run.snapshot().status is RunStatus.COMPLETED
    assert handle.cancel() is False


@pytest.mark.asyncio
async def test_events_and_result_share_one_execution_and_events_are_single_consumer() -> None:
    provider = FakeProvider(events=(_response(TextPart("answer")),), model_limits=TEST_LIMITS)
    run = UthCodeApplication(provider).create_run()
    handle = run.start_turn("hello")

    events_task = asyncio.create_task(_collect(handle))
    result_task = asyncio.create_task(handle.result())
    events = await events_task
    result = await result_task

    assert isinstance(events[-1], TurnCompleted)
    assert result.final_text == "answer"
    assert len(provider.recorded_requests) == 1
    with pytest.raises(RuntimeError, match="only be consumed once"):
        handle.events()


@pytest.mark.asyncio
async def test_active_turn_is_exclusive_and_cancel_is_idempotent() -> None:
    provider = FakeProvider(
        events=(_response(TextPart("answer")),), delay=0.05, model_limits=TEST_LIMITS
    )
    run = UthCodeApplication(provider).create_run()
    active = run.start_turn("first")

    with pytest.raises(RuntimeError, match="active Turn"):
        run.start_turn("second")
    assert active.cancel() is True
    assert active.cancel() is False
    result = await active.result()

    assert result.status is RunStatus.CANCELLED
    assert run.snapshot().status is RunStatus.CANCELLED
    assert isinstance((await run.start_turn("after cancel").result()), TurnResult)


@pytest.mark.asyncio
async def test_completed_turn_releases_run_when_event_iterator_is_closed_after_first_event() -> None:
    provider = FakeProvider(
        events=(_response(TextPart("answer")),), delay=0.01, model_limits=TEST_LIMITS
    )
    run = UthCodeApplication(provider).create_run()
    handle = run.start_turn("first")
    event_iterator = handle.events()

    assert (await anext(event_iterator)).event_type == "turn_started"
    await event_iterator.aclose()

    next_handle = await _start_after_release(run, "second")
    assert (await next_handle.result()).status is RunStatus.COMPLETED
    assert len(provider.recorded_requests) == 2


@pytest.mark.asyncio
async def test_events_call_without_iteration_starts_and_releases_the_run() -> None:
    provider = FakeProvider(
        events=(_response(TextPart("answer")),), delay=0.01, model_limits=TEST_LIMITS
    )
    run = UthCodeApplication(provider).create_run()
    event_iterator = run.start_turn("first").events()

    next_handle = await _start_after_release(run, "second")
    assert (await next_handle.result()).status is RunStatus.COMPLETED
    await event_iterator.aclose()
    assert len(provider.recorded_requests) == 2


@pytest.mark.asyncio
async def test_cancelled_event_consumer_does_not_hold_a_completed_run() -> None:
    provider = FakeProvider(
        events=(_response(TextPart("answer")),), delay=0.01, model_limits=TEST_LIMITS
    )
    run = UthCodeApplication(provider).create_run()
    handle = run.start_turn("first")
    first_event_seen = asyncio.Event()

    async def consume_until_cancelled() -> None:
        async for _event in handle.events():
            first_event_seen.set()
            await asyncio.Future()

    consumer = asyncio.create_task(consume_until_cancelled())
    await asyncio.wait_for(first_event_seen.wait(), timeout=1)
    consumer.cancel()
    with pytest.raises(asyncio.CancelledError):
        await consumer

    next_handle = await _start_after_release(run, "second")
    assert (await next_handle.result()).status is RunStatus.COMPLETED
    assert len(provider.recorded_requests) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal_path", ("completed", "failed", "cancelled"))
async def test_every_provider_terminal_path_releases_run_once(terminal_path: str) -> None:
    if terminal_path == "failed":
        provider = FakeProvider(
            error=ProviderError("synthetic provider failure"), model_limits=TEST_LIMITS
        )
    elif terminal_path == "cancelled":
        provider = FakeProvider(
            events=(_response(TextPart("answer")),),
            delay=0.02,
            model_limits=TEST_LIMITS,
        )
    else:
        provider = FakeProvider(events=(_response(TextPart("answer")),), model_limits=TEST_LIMITS)

    run = UthCodeApplication(provider).create_run()
    handle = run.start_turn("first")
    if terminal_path == "cancelled":
        result_task = asyncio.create_task(handle.result())
        await asyncio.sleep(0.005)
        assert handle.cancel() is True
        result = await result_task
    else:
        result = await handle.result()
    expected_status = {
        "completed": RunStatus.COMPLETED,
        "failed": RunStatus.FAILED,
        "cancelled": RunStatus.CANCELLED,
    }[terminal_path]
    assert result.status is expected_status

    next_handle = await _start_after_release(run, "second")
    await next_handle.result()
    assert len(provider.recorded_requests) == 2


@pytest.mark.asyncio
async def test_same_run_history_is_retained_and_different_runs_are_isolated() -> None:
    provider = _ScriptedProvider(
        (
            (_response(TextPart("first answer")),),
            (_response(TextPart("second answer")),),
            (_response(TextPart("other answer")),),
        )
    )
    application = UthCodeApplication(provider)
    first_run = application.create_run(run_id="first-run")
    second_run = application.create_run(run_id="second-run")

    await first_run.start_turn("first question").result()
    await first_run.start_turn("second question").result()
    await second_run.start_turn("isolated question").result()

    first_second_request = provider.requests[1]
    isolated_request = provider.requests[2]
    first_second_conversation = tuple(
        message
        for message in first_second_request.messages
        if not _is_context_message(message)
    )
    assert [message.role for message in first_second_conversation] == [
        "user",
        "assistant",
        "user",
    ]
    assert first_second_conversation[0].parts == (
        TextPart("first question"),
    )
    assert _latest_user_text(isolated_request) == "isolated question"
    assert len(
        tuple(message for message in isolated_request.messages if not _is_context_message(message))
    ) == 1
    assert first_run.snapshot().run_id == "first-run"
    assert second_run.snapshot().run_id == "second-run"


@pytest.mark.asyncio
async def test_model_switch_after_start_does_not_change_active_turn(tmp_path: Path) -> None:
    first_provider = _ScriptedProvider(((_response(TextPart("old answer")),),), model="remote-one")
    second_provider = _ScriptedProvider(((_response(TextPart("new answer")),),), model="remote-two")
    config = EffectiveConfig(
        default_model="one/ref",
        providers={
            "one": ProviderProfile("one", ProviderKind.FAKE),
            "two": ProviderProfile("two", ProviderKind.FAKE),
        },
        models={
            "one/ref": ModelProfile("one/ref", "one", "remote-one"),
            "two/ref": ModelProfile("two/ref", "two", "remote-two"),
        },
    )
    providers = {"one/ref": first_provider, "two/ref": second_provider}

    def build(_provider, model):
        return providers[model.model_ref]

    application = create_application(
        config,
        provider_builder=build,
        model_writer=lambda _model_ref: None,
        runtime_context=_context(tmp_path),
    )
    run = application.create_run()
    active = run.start_turn("keep old snapshot")
    application.select_model("two/ref")
    await active.result()

    assert len(first_provider.requests) == 1
    assert len(second_provider.requests) == 0
    assert "模型选择：one/ref" not in (first_provider.requests[0].system_prompt or "")
    assert "模型选择：one/ref" in _request_text(first_provider.requests[0])

    await run.start_turn("use new snapshot").result()
    assert len(second_provider.requests) == 1
    assert "模型选择：two/ref" not in (second_provider.requests[0].system_prompt or "")
    assert "模型选择：two/ref" in _request_text(second_provider.requests[0])


@pytest.mark.asyncio
async def test_application_formal_headless_e2e_hides_tool_result_and_uses_real_read_file(
    tmp_path: Path,
) -> None:
    hidden_content = "W02-HIDDEN-READFILE-CONTENT"
    note = tmp_path / "note.txt"
    note.write_text(hidden_content + "\n", encoding="utf-8")
    call = ToolCallPart("read-call", "ReadFile", {"path": "note.txt"})
    provider = _ScriptedProvider(
        (
            (
                ProviderReasoningDelta("I will read the note."),
                _response(
                    TextPart("Reading the note."),
                    call,
                    finish_reason=FinishReason.TOOL_CALLS,
                    usage=Usage(input_tokens=2, output_tokens=3),
                ),
            ),
            (
                ProviderReasoningDelta("I have the result."),
                _response(
                    TextPart("The note says exactly what was requested."),
                    usage=Usage(input_tokens=4, output_tokens=5),
                ),
            ),
        )
    )
    application = create_application(
        _config(),
        provider_builder=lambda _provider, _model: provider,
        runtime_context=_context(tmp_path),
    )

    run = application.create_run(run_id="headless-run")
    handle = run.start_turn("Read note.txt")
    events = await _collect(handle)
    result = await handle.result()

    assert [event.event_type for event in events].index("reasoning_delta") < [
        event.event_type for event in events
    ].index("tool_started")
    assert sum(isinstance(event, ToolFinished) for event in events) == 1
    assert sum(isinstance(event, TurnCompleted) for event in events) == 1
    assert not any(isinstance(event, TurnCancelled) for event in events)
    tool_finished = next(event for event in events if isinstance(event, ToolFinished))
    assert tool_finished.command == "note.txt"
    assert hidden_content not in tool_finished.to_json()
    assert hidden_content not in result.to_json()
    assert hidden_content not in run.snapshot().to_json()

    second_request = provider.requests[1]
    assert second_request.tools == application.tool_definitions() + (
        ASK_USER_TOOL_DEFINITION,
        TODO_WRITE_TOOL_DEFINITION,
    )
    assert _latest_message(second_request, "assistant").role == "assistant"
    tool_message = _latest_message(second_request, "tool")
    assert tool_message.parts == (ToolResultPart("read-call", f"1\t{hidden_content}"),)
    assert result.final_text == "The note says exactly what was requested."
    assert "I have the result." not in (result.final_text or "")


@pytest.mark.asyncio
async def test_application_tool_activity_is_fifo_and_names_have_one_owner(
    tmp_path: Path,
) -> None:
    first = _ApplicationGateTool("First")
    second = _ApplicationGateTool("Second")
    provider = _ScriptedProvider(
        (
            (
                _response(
                    ToolCallPart("first-call", "First", {"value": "one"}),
                    ToolCallPart("second-call", "Second", {"value": "two"}),
                    finish_reason=FinishReason.TOOL_CALLS,
                ),
            ),
            (_response(TextPart("done")),),
        )
    )
    application = create_application(
        _config(),
        provider_builder=lambda _provider, _model: provider,
        runtime_context=_context(tmp_path),
        tools=(first, second),
    )
    run = application.create_run()
    run.set_permission_mode(PermissionMode.FULL_ACCESS)

    events = await _collect(run.start_turn("run both tools"))
    started = [event for event in events if isinstance(event, ToolStarted)]
    finished = [event for event in events if isinstance(event, ToolFinished)]

    assert [event.tool_call_id for event in started] == ["first-call", "second-call"]
    assert [event.tool_call_id for event in finished] == ["first-call", "second-call"]
    assert [event.status for event in finished] == ["finished", "finished"]
    assert [event.tool_name for event in finished] == ["First", "Second"]
    assert [event.command for event in finished] == ["<arguments hidden>", "<arguments hidden>"]
    assert all(event.tool_name not in event.command for event in (*started, *finished))
    assert first.trace == ["preflight:one", "execute:one"]
    assert second.trace == ["preflight:two", "execute:two"]


@pytest.mark.asyncio
async def test_t09_2_formal_headless_run_turn_keeps_tool_plan_todo_gate_and_final_answer(
    tmp_path: Path,
) -> None:
    (tmp_path / "evidence.txt").write_text("verified fact\n", encoding="utf-8")
    pending_todo = {"todos": [{"content": "verify the fact", "status": "in_progress"}]}
    completed_todo = {"todos": [{"content": "verify the fact", "status": "completed"}]}
    provider = _ScriptedProvider(
        (
            (
                _response(
                    ToolCallPart("read-evidence", "ReadFile", {"path": "evidence.txt"}),
                    finish_reason=FinishReason.TOOL_CALLS,
                ),
            ),
            (
                _response(
                    ToolCallPart("plan-1", "ProposePlan", {"plan": "Read, verify, answer."}),
                    finish_reason=FinishReason.TOOL_CALLS,
                ),
            ),
            (
                _response(
                    ToolCallPart("todo-pending", "TodoWrite", pending_todo),
                    finish_reason=FinishReason.TOOL_CALLS,
                ),
            ),
            (_response(TextPart("premature answer")),),
            (
                _response(
                    ToolCallPart("todo-complete", "TodoWrite", completed_todo),
                    finish_reason=FinishReason.TOOL_CALLS,
                ),
            ),
            (_response(TextPart("final verified answer")),),
        )
    )
    application = create_application(
        _config(),
        provider_builder=lambda _provider, _model: provider,
        runtime_context=_context(tmp_path),
    )
    run = application.create_run(run_id="t09-2-headless")
    assert run.set_behavior_mode(BehaviorMode.PLAN) is BehaviorMode.PLAN
    handle = run.start_turn("read, plan, and verify")
    events_task = asyncio.create_task(_collect(handle))

    for _ in range(100):
        if handle.pending_pause is not None:
            break
        await asyncio.sleep(0)
    plan_pause = handle.pending_pause
    assert plan_pause is not None and plan_pause.plan_review_request is not None
    assert handle.resume(
        PlanReviewResponse(
            plan_pause.pause_id,
            plan_pause.run_id,
            plan_pause.turn_id,
            1,
            PlanReviewChoice.APPROVE,
        )
    ) is True

    events = await asyncio.wait_for(events_task, timeout=1)
    result = await asyncio.wait_for(handle.result(), timeout=1)

    assert result.status is RunStatus.COMPLETED
    assert result.final_text == "final verified answer"
    assert [event.tool_call_id for event in events if isinstance(event, ToolFinished)] == [
        "read-evidence",
        "plan-1",
        "todo-pending",
        "todo-complete",
    ]
    assert [event.unfinished_count for event in events if isinstance(event, CompletionBlocked)] == [1]
    assert [event.task_state.has_unfinished for event in events if isinstance(event, TaskStateChanged)] == [
        True,
        False,
    ]
    assert "一次性运行反馈类型：completion_blocked" in _context_text(provider.requests[4])
    completed_result = _latest_message(provider.requests[-1], "tool").parts[0]
    assert isinstance(completed_result, ToolResultPart)
    assert completed_result.tool_call_id == "todo-complete"
    assert '"status": "completed"' in completed_result.content


@pytest.mark.asyncio
async def test_tool_summary_failure_does_not_block_tool_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hidden_content = "W02-SUMMARY-FAILURE-READ-CONTENT"
    (tmp_path / "note.txt").write_text(hidden_content + "\n", encoding="utf-8")
    call = ToolCallPart("read-call", "ReadFile", {"path": "note.txt"})
    provider = _ScriptedProvider(
        (
            (_response(call, finish_reason=FinishReason.TOOL_CALLS),),
            (_response(TextPart("done")),),
        )
    )

    def fail_summary(_self: ApplicationToolService, _call: ToolCallPart) -> str:
        raise RuntimeError("summary failed")

    monkeypatch.setattr(ApplicationToolService, "describe_tool_call", fail_summary)
    application = create_application(
        _config(),
        provider_builder=lambda _provider, _model: provider,
        runtime_context=_context(tmp_path),
    )

    events = await _collect(application.create_run().start_turn("read"))

    tool_finished = next(event for event in events if isinstance(event, ToolFinished))
    assert tool_finished.command == "<tool summary unavailable>"
    assert _latest_message(provider.requests[1], "tool").parts == (
        ToolResultPart("read-call", f"1\t{hidden_content}"),
    )


def test_headless_application_import_does_not_load_interfaces() -> None:
    source_root = str(Path(__file__).parents[1] / "src")
    environment = os.environ.copy()
    environment["PYTHONPATH"] = source_root + os.pathsep + environment.get("PYTHONPATH", "")
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys, uthcode.application; "
            "assert 'uthcode.interfaces' not in sys.modules",
        ],
        cwd=Path(__file__).parents[1],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_tool_descriptions_are_bounded_and_do_not_echo_write_content_or_unknown_arguments(
    tmp_path: Path,
) -> None:
    service = ApplicationToolService(
        create_default_tools(tmp_path),
        workdir=tmp_path,
    )
    secret = "W02-SECRET-DO-NOT-DISPLAY"

    write_summary = service.describe_tool_call(
        ToolCallPart("write", "WriteFile", {"path": "note.txt", "content": secret})
    )
    read_summary = service.describe_tool_call(
        ToolCallPart("read", "ReadFile", {"path": "note.txt", "offset": 4})
    )
    edit_summary = service.describe_tool_call(
        ToolCallPart(
            "edit",
            "EditFile",
            {"path": "note.txt", "old_string": secret, "new_string": secret},
        )
    )
    bash_summary = service.describe_tool_call(
        ToolCallPart("bash", "Bash", {"command": f"echo {secret}"})
    )
    grep_summary = service.describe_tool_call(
        ToolCallPart("grep", "Grep", {"pattern": "needle", "path": "src"})
    )
    unknown_summary = service.describe_tool_call(
        ToolCallPart("unknown", "Missing", {"value": secret})
    )
    long_summary = service.describe_tool_call(
        ToolCallPart("glob", "Glob", {"pattern": "x" * 500, "path": "."})
    )

    assert write_summary == "note.txt"
    assert read_summary == "note.txt"
    assert edit_summary == "note.txt"
    assert secret not in bash_summary
    assert grep_summary == "path=src"
    assert unknown_summary == "<unknown tool>"
    assert len(long_summary) == 240
    assert long_summary.endswith("…")


@pytest.mark.asyncio
async def test_tool_summaries_redact_known_values_and_common_credentials_in_both_events(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment_value = "W02-ENV-PLAIN-VALUE-ALPHA-123456"
    short_environment_value = "q7z"
    two_character_environment_value = "qz"
    one_character_environment_value = "q"
    bare_api_key = "sk-W02SyntheticKeyValue123456789"
    bearer_token = "W02BearerTokenValue123456789"
    spaced_token = "W02PlainCredential739184"
    assigned_api_key = "W02AssignedCredential846291"
    basic_credential = "W02BasicCredential517293"
    monkeypatch.setenv("W02_RUNTIME_VALUE_SOURCE", environment_value)
    monkeypatch.setenv("W02_SHORT_RUNTIME_VALUE_SOURCE", short_environment_value)
    monkeypatch.setenv("W02_TWO_CHARACTER_VALUE_SOURCE", two_character_environment_value)
    monkeypatch.setenv("W02_ONE_CHARACTER_VALUE_SOURCE", one_character_environment_value)
    call = ToolCallPart(
        "bash-call",
        "Bash",
        {
            "command": (
                f"echo {environment_value} {short_environment_value} "
                f"{two_character_environment_value} {one_character_environment_value} "
                f"{bare_api_key} "
                f"--token {spaced_token} --api-key={assigned_api_key} "
                f'Authorization: Bearer {bearer_token} '
                f'-H "Authorization: Basic {basic_credential}"'
            )
        },
    )
    provider = _ScriptedProvider(
        (
            (_response(call, finish_reason=FinishReason.TOOL_CALLS),),
            (_response(TextPart("done")),),
        )
    )
    application = create_application(
        _config(),
        provider_builder=lambda _provider, _model: provider,
        runtime_context=_context(tmp_path),
    )

    events = await _collect(application.create_run().start_turn("run safe Bash"))
    tool_events = [
        event for event in events if isinstance(event, (ToolStarted, ToolFinished))
    ]

    assert len(tool_events) == 2
    assert all(event.command.startswith("echo") for event in tool_events)
    serialized = " ".join(event.to_json() for event in tool_events)
    assert environment_value not in serialized
    assert short_environment_value not in serialized
    assert two_character_environment_value not in serialized
    assert all(
        f" {one_character_environment_value} " not in event.command
        for event in tool_events
    )
    assert bare_api_key not in serialized
    assert bearer_token not in serialized
    assert spaced_token not in serialized
    assert "PlainCredential739184" not in serialized
    assert assigned_api_key not in serialized
    assert "AssignedCredential846291" not in serialized
    assert basic_credential not in serialized
    assert "BasicCredential517293" not in serialized
    assert "W02" not in serialized
    assert all("<redacted>" in event.command for event in tool_events)

    monkeypatch.setenv("W02_SHORT_ZERO", "0")
    monkeypatch.setenv("W02_SHORT_ONE", "1")
    ordinary_summary = ApplicationToolService(
        create_default_tools(tmp_path),
        workdir=tmp_path,
    ).describe_tool_call(
        ToolCallPart("ordinary", "Bash", {"command": "echo 2026-08-06"})
    )
    assert ordinary_summary == "echo 2026-08-06"

    configured_secret = "xy7"
    monkeypatch.setenv("W02_CONFIG_SECRET_SOURCE", configured_secret)
    configured_summary = ApplicationToolService(
        create_default_tools(tmp_path),
        workdir=tmp_path,
        secret_env_names=("W02_CONFIG_SECRET_SOURCE",),
    ).describe_tool_call(
        ToolCallPart("configured", "Bash", {"command": f"echo {configured_secret}"})
    )
    assert configured_summary == "echo <redacted>"


def test_tool_summary_has_a_single_display_owner(tmp_path: Path) -> None:
    service = ApplicationToolService(create_default_tools(tmp_path), workdir=tmp_path)

    cases = (
        ("Bash", {"command": "echo hello"}, "echo hello"),
        ("ReadFile", {"path": "note.txt"}, "note.txt"),
        ("WriteFile", {"path": "note.txt", "content": "hidden"}, "note.txt"),
        (
            "EditFile",
            {"path": "note.txt", "old_string": "hidden", "new_string": "new"},
            "note.txt",
        ),
        ("Glob", {"pattern": "*.py", "path": "src"}, "pattern=*.py path=src"),
        ("Grep", {"pattern": "secret", "path": "src"}, "path=src"),
    )

    for name, arguments, expected in cases:
        summary = service.describe_tool_call(ToolCallPart("call", name, arguments))
        assert summary == expected
        assert name not in summary

    session_service = ApplicationToolService(
        create_default_tools(tmp_path),
        workdir=tmp_path,
        session_provider=lambda: None,
    )
    for name, arguments in (
        ("ToolResultRead", {"ref": "opaque-ref"}),
        ("HistoryRead", {"ref": "opaque-ref"}),
    ):
        summary = session_service.describe_tool_call(
            ToolCallPart("call", name, arguments)
        )
        assert summary.startswith("ref=opaque-ref")
        assert name not in summary


@pytest.mark.asyncio
async def test_application_stream_events_are_visible_before_segment_boundary_and_not_repeated() -> None:
    provider = _StreamingGatedProvider(_response(TextPart("done"), usage=Usage(2, 3)))
    run = UthCodeApplication(provider).create_run()
    handle = run.start_turn("stream before release")
    observed: list[AgentEvent] = []
    delta_seen = asyncio.Event()

    async def consume() -> None:
        async for event in handle.events():
            observed.append(event)
            if isinstance(event, (AgentReasoningDelta, AssistantMessageDelta)):
                delta_seen.set()

    consumer = asyncio.create_task(consume())
    await provider.partial_emitted.wait()
    try:
        try:
            await asyncio.wait_for(delta_seen.wait(), timeout=0.2)
            visible_before_release = True
        except asyncio.TimeoutError:
            visible_before_release = False
    finally:
        provider.release.set()

    await asyncio.wait_for(consumer, timeout=1)
    result = await asyncio.wait_for(handle.result(), timeout=1)

    assert visible_before_release is True
    assert result.status is RunStatus.COMPLETED
    assert [event.event_type for event in observed] == [
        "turn_started",
        "iteration_started",
        "reasoning_started",
        "reasoning_delta",
        "reasoning_finished",
        "assistant_message_delta",
        "usage_updated",
        "assistant_message_completed",
        "turn_completed",
    ]
    serialized = [event.to_json() for event in observed]
    assert len(serialized) == len(set(serialized))
    assert sum(isinstance(event, UsageUpdated) for event in observed) == 1
    assert sum(isinstance(event, IterationStarted) for event in observed) == 1
    assert all(
        getattr(part, "text", None) != "partial"
        for message in handle._driver.execution.state.messages
        for part in message.parts
    )
    assert handle._driver.execution.state.usage == Usage(2, 3)


@pytest.mark.asyncio
async def test_application_pause_resume_keeps_one_live_event_consumer() -> None:
    provider = _GatedProvider((_response(TextPart("done"), usage=Usage(2, 3)),))
    run = UthCodeApplication(provider).create_run()
    handle = run.start_turn("pause in one stream")
    event_iterator = handle.events()

    first = await asyncio.wait_for(anext(event_iterator), timeout=1)
    assert isinstance(first, TurnStarted)
    await provider.entered.wait()
    assert handle.pause() is True
    provider.release.set()
    for _ in range(100):
        if handle.pending_pause is not None:
            break
        await asyncio.sleep(0)
    pending = handle.pending_pause
    assert pending is not None
    assert handle.resume(ResumeTurnResponse(pending.pause_id, pending.run_id, pending.turn_id)) is True

    remaining = [event async for event in event_iterator]
    events = [first, *remaining]
    result = await handle.result()

    assert result.status is RunStatus.COMPLETED
    assert events[0] is first
    assert sum(isinstance(event, TurnStarted) for event in events) == 1
    assert sum(isinstance(event, TurnPaused) for event in events) == 1
    assert sum(isinstance(event, TurnResumed) for event in events) == 1
    assert sum(isinstance(event, TurnCompleted) for event in events) == 1
    assert len([event.to_json() for event in events]) == len(
        {event.to_json() for event in events}
    )


@pytest.mark.asyncio
async def test_application_driver_task_cancellation_closes_turn_without_unhandled_exception() -> None:
    provider = _GatedProvider((_response(TextPart("done")),))
    run = UthCodeApplication(provider).create_run()
    handle = run.start_turn("cancel driver task")
    events_task = asyncio.create_task(_collect(handle))
    await provider.entered.wait()
    driver_task = handle._driver._task
    assert driver_task is not None
    driver_task.cancel()

    events = await asyncio.wait_for(events_task, timeout=1)
    result = await asyncio.wait_for(handle.result(), timeout=1)

    assert result.status is RunStatus.CANCELLED
    assert sum(isinstance(event, TurnCancelled) for event in events) == 1
    assert handle._driver._result_future is not None
    assert handle._driver._result_future.done()
    assert handle._driver._task is None
    assert handle._driver._response_waiter is None
    assert handle._driver._segment_signal is None
    assert handle.pending_pause is None
    provider.release.set()
    next_handle = run.start_turn("after driver task cancellation")
    assert (await next_handle.result()).status is RunStatus.COMPLETED


@pytest.mark.asyncio
async def test_application_driver_unexpected_exception_closes_result_events_and_active_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = FakeProvider(events=(_response(TextPart("done")),), model_limits=TEST_LIMITS)
    run = UthCodeApplication(provider).create_run(run_id="exception-run")
    handle = run.start_turn("unexpected exception")
    target = handle._driver.execution
    original_run_segment = AgentTurnExecution.run_segment

    async def fail_once(self: AgentTurnExecution, *args: object, **kwargs: object):
        if self is target:
            raise RuntimeError("synthetic internal failure")
        return await original_run_segment(self, *args, **kwargs)

    monkeypatch.setattr(AgentTurnExecution, "run_segment", fail_once)
    loop = asyncio.get_running_loop()
    loop_errors: list[dict[str, object]] = []
    previous_handler = loop.get_exception_handler()
    loop.set_exception_handler(lambda _loop, context: loop_errors.append(context))
    events_task = asyncio.create_task(_collect(handle))
    try:
        result = await asyncio.wait_for(handle.result(), timeout=1)
        events = await asyncio.wait_for(events_task, timeout=1)
        await asyncio.sleep(0)
    finally:
        loop.set_exception_handler(previous_handler)

    assert result.status is RunStatus.FAILED
    assert result.termination_reason is TerminationReason.INTERNAL_ERROR
    assert run.snapshot().status is RunStatus.FAILED
    assert len([event for event in events if event.event_type == "turn_failed"]) == 1
    assert not any(isinstance(event, TurnCancelled) for event in events)
    assert all("synthetic internal failure" not in event.to_json() for event in events)
    assert handle._driver._result_future is not None
    assert handle._driver._result_future.done()
    assert handle._driver._task is None
    assert handle._driver._response_waiter is None
    assert handle._driver._segment_signal is None
    assert handle.pending_pause is None
    assert not any(
        context.get("message") == "Task exception was never retrieved"
        for context in loop_errors
    )

    next_handle = run.start_turn("after internal exception")
    next_result = await asyncio.wait_for(next_handle.result(), timeout=1)
    assert next_result.status is RunStatus.COMPLETED


@pytest.mark.asyncio
async def test_application_driver_exposes_pending_after_paused_event_and_resumes_once() -> None:
    provider = _GatedProvider((_response(TextPart("done"), usage=Usage(2, 3)),))
    run = UthCodeApplication(provider).create_run()
    handle = run.start_turn("pause me")
    events_task = asyncio.create_task(_collect(handle))
    await provider.entered.wait()

    assert handle.pause() is True
    provider.release.set()
    for _ in range(100):
        if handle.pending_pause is not None:
            break
        await asyncio.sleep(0)
    pending = handle.pending_pause
    assert pending is not None
    assert pending.kind is PauseKind.USER_REQUESTED
    assert run.snapshot().status is RunStatus.RUNNING
    with pytest.raises(RuntimeError, match="active Turn"):
        run.start_turn("second")
    with pytest.raises(ValueError):
        handle.resume(RetryProviderResponse(pending.pause_id, pending.run_id, pending.turn_id))
    assert handle.pending_pause == pending

    valid = ResumeTurnResponse(pending.pause_id, pending.run_id, pending.turn_id)
    assert handle.resume(valid) is True
    assert handle.resume(valid) is False
    events = await events_task
    result = await handle.result()

    assert result.status is RunStatus.COMPLETED
    assert len(provider.requests) == 2
    assert sum(isinstance(event, TurnStarted) for event in events) == 1
    assert sum(isinstance(event, IterationStarted) for event in events) == 1
    assert sum(isinstance(event, UsageUpdated) for event in events) == 1
    assert sum(isinstance(event, TurnPausing) for event in events) == 1
    assert sum(isinstance(event, TurnPaused) for event in events) == 1
    assert sum(isinstance(event, TurnResumed) for event in events) == 1
    assert sum(isinstance(event, TurnCompleted) for event in events) == 1
    assert handle.pending_pause is None
    assert handle._driver._task is None
    assert handle._driver._response_waiter is None
    assert handle._driver._segment_signal is None


@pytest.mark.asyncio
async def test_application_network_retry_rejects_stale_response_without_mutating_pending() -> None:
    provider = _FailThenProvider(NetworkError("offline"), _response(TextPart("done"), usage=Usage(1, 1)))
    application = UthCodeApplication(provider)
    run = application.create_run()
    handle = run.start_turn("retry")
    events_task = asyncio.create_task(_collect(handle))
    for _ in range(100):
        if handle.pending_pause is not None:
            break
        await asyncio.sleep(0)
    pending = handle.pending_pause
    assert pending is not None
    assert pending.kind is PauseKind.PROVIDER_UNAVAILABLE
    before = pending
    with pytest.raises(ValueError):
        handle.resume(RetryProviderResponse("wrong", pending.run_id, pending.turn_id))
    assert handle.pending_pause == before
    assert handle.resume(RetryProviderResponse(pending.pause_id, pending.run_id, pending.turn_id)) is True
    events = await events_task
    result = await handle.result()

    assert result.status is RunStatus.COMPLETED
    assert len(provider.requests) == 2
    assert len([event for event in events if isinstance(event, IterationStarted)]) == 1
    assert len([event for event in events if isinstance(event, UsageUpdated)]) == 1
    assert len([event for event in events if isinstance(event, TurnResumed)]) == 1
    assert application.status().context_status.measurement == "estimate"


@pytest.mark.asyncio
async def test_headless_ask_user_round_trip_resumes_same_turn() -> None:
    question = UserQuestion("answer", "Answer", "What should be used?", QuestionKind.TEXT)
    request = UserInputRequest((question,))
    ask_call = ToolCallPart("ask-1", "AskUserQuestion", request.to_dict())
    later_call = ToolCallPart("later-1", "missing", {})
    provider = _ScriptedProvider(
        (
            (_response(ask_call, later_call, finish_reason=FinishReason.TOOL_CALLS),),
            (_response(TextPart("done")),),
        )
    )
    application = UthCodeApplication(provider)
    run = application.create_run(run_id="ask-run")
    handle = run.start_turn("ask")
    events_task = asyncio.create_task(_collect(handle))
    for _ in range(100):
        if handle.pending_pause is not None:
            break
        await asyncio.sleep(0)
    pending = handle.pending_pause
    assert pending is not None
    assert pending.kind is PauseKind.USER_INPUT_REQUIRED
    assert pending.tool_call_id == "ask-1"
    assert pending.run_id == "ask-run"
    assert all(definition.name != ASK_USER_TOOL_DEFINITION.name for definition in application.tool_definitions())
    assert provider.requests[0].tools[-2:] == (
        ASK_USER_TOOL_DEFINITION,
        TODO_WRITE_TOOL_DEFINITION,
    )

    assert handle.resume(
        UserInputResponse(
            pending.pause_id,
            pending.run_id,
            pending.turn_id,
            "ask-1",
            {"answer": ["Ada"]},
        )
    ) is True
    events = await events_task
    result = await handle.result()

    assert result.status is RunStatus.COMPLETED
    assert result.run_id == pending.run_id
    assert result.turn_id == pending.turn_id
    started = next(event for event in events if isinstance(event, TurnStarted))
    assert started.run_id == pending.run_id
    assert started.turn_id == pending.turn_id
    assert provider.requests[1].tools[-2:] == (
        ASK_USER_TOOL_DEFINITION,
        TODO_WRITE_TOOL_DEFINITION,
    )
    tool_message = _latest_message(provider.requests[1], "tool")
    assert tool_message.parts[0] == ToolResultPart(
        "ask-1", '{"answers": {"answer": ["Ada"]}}'
    )
    assert tool_message.parts[1] == ToolResultPart(
        "later-1", "Error: unknown tool: missing", is_error=True
    )
    assert [event.tool_call_id for event in events if isinstance(event, ToolFinished)] == [
        "ask-1",
        "later-1",
    ]
    event_types = [event.event_type for event in events]
    assert event_types.count("turn_started") == 1
    assert event_types.count("turn_paused") == 1
    assert event_types.count("turn_resumed") == 1
    assert event_types.count("turn_completed") == 1
    assert event_types.index("turn_paused") < event_types.index("turn_resumed")
    assert event_types.index("turn_resumed") < event_types.index("turn_completed")
    assert len([event for event in events if isinstance(event, TurnResumed)]) == 1
    assert len([event for event in events if isinstance(event, TurnCompleted)]) == 1


@pytest.mark.asyncio
async def test_headless_two_ask_user_prompts_resume_fifo_in_one_turn() -> None:
    first_request = UserInputRequest(
        (UserQuestion("first", "First", "What is the first value?", QuestionKind.TEXT),)
    )
    second_request = UserInputRequest(
        (UserQuestion("second", "Second", "What is the second value?", QuestionKind.TEXT),)
    )
    provider = _ScriptedProvider(
        (
            (
                _response(
                    ToolCallPart("ask-1", "AskUserQuestion", first_request.to_dict()),
                    ToolCallPart("ask-2", "AskUserQuestion", second_request.to_dict()),
                    finish_reason=FinishReason.TOOL_CALLS,
                ),
            ),
            (_response(TextPart("done")),),
        )
    )
    application = UthCodeApplication(provider)
    run = application.create_run(run_id="two-ask-run")
    handle = run.start_turn("ask twice")
    events_task = asyncio.create_task(_collect(handle))

    for _ in range(100):
        if handle.pending_pause is not None:
            break
        await asyncio.sleep(0)
    first_pause = handle.pending_pause
    assert first_pause is not None
    assert first_pause.tool_call_id == "ask-1"
    assert handle.resume(
        UserInputResponse(
            first_pause.pause_id,
            first_pause.run_id,
            first_pause.turn_id,
            "ask-1",
            {"first": ["Ada"]},
        )
    ) is True

    for _ in range(100):
        pending = handle.pending_pause
        if pending is not None and pending.tool_call_id == "ask-2":
            break
        await asyncio.sleep(0)
    second_pause = handle.pending_pause
    assert second_pause is not None
    assert second_pause.tool_call_id == "ask-2"
    assert second_pause.pause_id != first_pause.pause_id
    assert second_pause.run_id == first_pause.run_id == "two-ask-run"
    assert second_pause.turn_id == first_pause.turn_id
    assert handle.resume(
        UserInputResponse(
            second_pause.pause_id,
            second_pause.run_id,
            second_pause.turn_id,
            "ask-2",
            {"second": ["Grace"]},
        )
    ) is True

    events = await events_task
    result = await handle.result()

    assert result.status is RunStatus.COMPLETED
    assert result.run_id == first_pause.run_id
    assert result.turn_id == first_pause.turn_id
    assert len(provider.requests) == 2
    assert _latest_message(provider.requests[1], "tool").parts == (
        ToolResultPart("ask-1", '{"answers": {"first": ["Ada"]}}'),
        ToolResultPart("ask-2", '{"answers": {"second": ["Grace"]}}'),
    )
    assert [
        event.tool_call_id for event in events if isinstance(event, ToolFinished)
    ] == ["ask-1", "ask-2"]
    event_types = [event.event_type for event in events]
    assert event_types.count("turn_paused") == 2
    assert event_types.count("turn_resumed") == 2
    assert event_types.count("turn_completed") == 1


@pytest.mark.asyncio
async def test_application_ask_cancel_closes_ids_once_and_releases_active_slot() -> None:
    question = UserQuestion("answer", "Answer", "What should be used?", QuestionKind.TEXT)
    request = UserInputRequest((question,))
    calls = (
        ToolCallPart("ask-1", "AskUserQuestion", request.to_dict()),
        ToolCallPart("later-1", "missing", {}),
    )
    provider = _ScriptedProvider(
        (
            (_response(*calls, finish_reason=FinishReason.TOOL_CALLS),),
            (_response(TextPart("after")),),
        )
    )
    run = UthCodeApplication(provider).create_run()
    handle = run.start_turn("ask and cancel")
    events_task = asyncio.create_task(_collect(handle))
    for _ in range(100):
        if handle.pending_pause is not None:
            break
        await asyncio.sleep(0)
    assert handle.pending_pause is not None
    assert handle.cancel() is True
    assert handle.cancel() is False
    events = await events_task
    result = await handle.result()

    assert result.status is RunStatus.CANCELLED
    assert not any(isinstance(event, TurnResumed) for event in events)
    assert [event.tool_call_id for event in events if isinstance(event, ToolFinished)] == [
        "ask-1",
        "later-1",
    ]
    assert len([event for event in events if isinstance(event, ToolBatchFinished)]) == 1
    assert next(event for event in events if isinstance(event, ToolBatchFinished)).status == "cancelled"
    assert len([event for event in events if isinstance(event, TurnCancelled)]) == 1
    next_handle = run.start_turn("after cancellation")
    assert (await next_handle.result()).status is RunStatus.COMPLETED


@pytest.mark.asyncio
async def test_application_resume_cancel_race_is_cancel_wins_without_resumed_event() -> None:
    provider = _GatedProvider((_response(TextPart("done")),))
    handle = UthCodeApplication(provider).create_run().start_turn("race")
    events_task = asyncio.create_task(_collect(handle))
    await provider.entered.wait()
    assert handle.pause() is True
    provider.release.set()
    for _ in range(100):
        if handle.pending_pause is not None:
            break
        await asyncio.sleep(0)
    pending = handle.pending_pause
    assert pending is not None
    assert handle.resume(ResumeTurnResponse(pending.pause_id, pending.run_id, pending.turn_id)) is True
    assert handle.cancel() is True
    events = await events_task
    result = await handle.result()

    assert result.status is RunStatus.CANCELLED
    assert not any(isinstance(event, TurnResumed) for event in events)
    assert len([event for event in events if isinstance(event, TurnCancelled)]) == 1
    assert handle.pending_pause is None


@pytest.mark.asyncio
async def test_application_terminal_controls_are_rejected_without_new_events() -> None:
    provider = FakeProvider(events=(_response(TextPart("done")),), model_limits=TEST_LIMITS)
    handle = UthCodeApplication(provider).create_run().start_turn("done")
    events = await _collect(handle)
    result = await handle.result()
    assert result.status is RunStatus.COMPLETED
    assert handle.pause() is False
    assert handle.cancel() is False
    assert handle.resume(ResumeTurnResponse("stale", result.run_id, result.turn_id)) is False
    assert handle.pending_pause is None
    assert len(events) == len([event for event in events if event.run_id == result.run_id])


@pytest.mark.asyncio
async def test_t08_application_mode_selects_exact_builtin_tool_view_and_prompt(
    tmp_path: Path,
) -> None:
    provider = _ScriptedProvider(
        (
            (_response(TextPart("plan done"), finish_reason=FinishReason.ERROR),),
            (_response(TextPart("default done")),),
        )
    )
    application = create_application(
        _config(),
        provider_builder=lambda _provider, _model: provider,
        runtime_context=_context(tmp_path),
    )

    plan_run = application.create_run(run_id="plan-run")
    assert plan_run.behavior_mode is BehaviorMode.DEFAULT
    permission_before = plan_run.permission_mode
    assert plan_run.set_behavior_mode(BehaviorMode.PLAN) is BehaviorMode.PLAN
    assert plan_run.set_behavior_mode(BehaviorMode.PLAN) is BehaviorMode.PLAN
    assert plan_run.permission_mode is permission_before
    plan_handle = plan_run.start_turn("plan")
    with pytest.raises(RuntimeError, match="active Turn"):
        plan_run.set_behavior_mode(BehaviorMode.DEFAULT)
    await plan_handle.result()

    default_run = application.create_run(run_id="default-run")
    await default_run.start_turn("build").result()

    assert [item.name for item in provider.requests[0].tools] == [
        "ReadFile",
        "Glob",
            "Grep",
            "Bash",
            "ToolResultRead",
            "HistoryRead",
            "AskUserQuestion",
            "ProposePlan",
        ]
    assert [item.name for item in provider.requests[1].tools] == [
        "ReadFile",
        "WriteFile",
        "EditFile",
        "Glob",
        "Grep",
        "Bash",
        "ToolResultRead",
        "HistoryRead",
        "AskUserQuestion",
        "TodoWrite",
    ]
    assert "当前行为模式：PLAN" in _context_text(provider.requests[0])
    assert "当前行为模式：DEFAULT" in _context_text(provider.requests[1])


@pytest.mark.asyncio
async def test_t08_application_plan_review_revise_approve_uses_same_handle_and_turn(
    tmp_path: Path,
) -> None:
    provider = _ScriptedProvider(
        (
            (_response(ToolCallPart("plan-1", "ProposePlan", {"plan": "Plan v1"}), finish_reason=FinishReason.TOOL_CALLS, usage=Usage(1, 1)),),
            (_response(ToolCallPart("plan-2", "ProposePlan", {"plan": "Plan v2"}), finish_reason=FinishReason.TOOL_CALLS, usage=Usage(2, 2)),),
            (_response(TextPart("implemented"), usage=Usage(3, 3)),),
        )
    )
    application = create_application(
        _config(),
        provider_builder=lambda _provider, _model: provider,
        runtime_context=_context(tmp_path),
    )
    run = application.create_run(run_id="plan-run")
    run.set_behavior_mode(BehaviorMode.PLAN)
    handle = run.start_turn("plan then implement")
    resumed_states: list[object] = []

    async def collect_with_resume_assertions() -> list[AgentEvent]:
        events: list[AgentEvent] = []
        async for event in handle.events():
            events.append(event)
            if isinstance(event, TurnResumed):
                state = handle._driver.execution.state
                if not resumed_states:
                    assert state.messages[-1].role == "user"
                    assert state.messages[-1].parts == (TextPart("include verification"),)
                    assert [message.role for message in state.messages[-2:]] == ["tool", "user"]
                    assert state.runtime_feedback is not None
                    assert state.runtime_feedback.kind is RuntimeFeedbackKind.PLAN_REVISION
                else:
                    assert state.behavior_mode is BehaviorMode.DEFAULT
                    assert state.plan_state is not None and state.plan_state.approved
                resumed_states.append(state)
        return events

    events_task = asyncio.create_task(collect_with_resume_assertions())

    for _ in range(100):
        if handle.pending_pause is not None:
            break
        await asyncio.sleep(0)
    pause_v1 = handle.pending_pause
    assert pause_v1 is not None and pause_v1.plan_review_request is not None
    turn_id = pause_v1.turn_id
    stale = PlanReviewResponse(
        pause_v1.pause_id,
        pause_v1.run_id,
        pause_v1.turn_id,
        2,
        PlanReviewChoice.REVISE,
        "stale",
    )
    with pytest.raises(ValueError, match="Plan revision"):
        handle.resume(stale)
    assert handle.pending_pause == pause_v1
    assert handle.resume(
        PlanReviewResponse(
            pause_v1.pause_id,
            pause_v1.run_id,
            pause_v1.turn_id,
            1,
            PlanReviewChoice.REVISE,
            "include verification",
        )
    ) is True

    for _ in range(100):
        pending = handle.pending_pause
        if pending is not None and pending.pause_id != pause_v1.pause_id:
            break
        await asyncio.sleep(0)
    pause_v2 = handle.pending_pause
    assert pause_v2 is not None and pause_v2.plan_review_request is not None
    assert pause_v2.plan_review_request.revision == 2
    assert pause_v2.turn_id == turn_id
    assert handle.resume(
        PlanReviewResponse(
            pause_v2.pause_id,
            pause_v2.run_id,
            pause_v2.turn_id,
            2,
            PlanReviewChoice.APPROVE,
        )
    ) is True

    events = await asyncio.wait_for(events_task, timeout=1)
    result = await asyncio.wait_for(handle.result(), timeout=1)

    assert result.status is RunStatus.COMPLETED
    assert result.run_id == "plan-run" and result.turn_id == turn_id
    assert result.final_text == "implemented"
    assert result.usage == Usage(6, 6)
    assert run.behavior_mode is BehaviorMode.DEFAULT
    assert [event.revision for event in events if isinstance(event, PlanProposed)] == [1, 2]
    assert sum(isinstance(event, TurnPaused) for event in events) == 2
    assert sum(isinstance(event, TurnResumed) for event in events) == 2
    assert len(resumed_states) == 2
    assert sum(isinstance(event, TurnStarted) for event in events) == 1
    assert sum(isinstance(event, TurnCompleted) for event in events) == 1
    assert sum(
        isinstance(event, AssistantMessageCompleted)
        and event.kind is AssistantMessageKind.FINAL
        for event in events
    ) == 1
    assert not any(
        isinstance(event, AssistantMessageDelta) and "plan" in event.text
        for event in events
    )
    assert [event.behavior_mode for event in events if isinstance(event, BehaviorModeChanged)] == [
        BehaviorMode.DEFAULT
    ]
    assert [definition.name for definition in provider.requests[2].tools] == [
        "ReadFile",
        "WriteFile",
        "EditFile",
        "Glob",
        "Grep",
        "Bash",
        "ToolResultRead",
        "HistoryRead",
        "AskUserQuestion",
        "TodoWrite",
    ]


@pytest.mark.asyncio
async def test_t08_application_cancel_wins_while_plan_review_is_pending(tmp_path: Path) -> None:
    provider = _ScriptedProvider(((_response(ToolCallPart("plan-1", "ProposePlan", {"plan": "Plan v1"}), finish_reason=FinishReason.TOOL_CALLS),),))
    application = create_application(
        _config(),
        provider_builder=lambda _provider, _model: provider,
        runtime_context=_context(tmp_path),
    )
    run = application.create_run(run_id="cancel-plan")
    run.set_behavior_mode(BehaviorMode.PLAN)
    handle = run.start_turn("plan")
    events_task = asyncio.create_task(_collect(handle))

    for _ in range(100):
        if handle.pending_pause is not None:
            break
        await asyncio.sleep(0)
    pending = handle.pending_pause
    assert pending is not None and pending.plan_review_request is not None
    assert handle.steer("ordinary steering is blocked") is False
    assert handle.cancel() is True
    assert handle.resume(
        PlanReviewResponse(
            pending.pause_id,
            pending.run_id,
            pending.turn_id,
            pending.plan_review_request.revision,
            PlanReviewChoice.APPROVE,
        )
    ) is False

    events = await asyncio.wait_for(events_task, timeout=1)
    result = await asyncio.wait_for(handle.result(), timeout=1)
    assert result.status is RunStatus.CANCELLED
    assert sum(isinstance(event, TurnCancelled) for event in events) == 1
    assert not any(isinstance(event, BehaviorModeChanged) for event in events)


@pytest.mark.asyncio
async def test_t08_application_todo_completion_gate_continues_without_exposing_candidate(
    tmp_path: Path,
) -> None:
    pending = {"todos": [{"content": "verify", "status": "in_progress"}]}
    completed = {"todos": [{"content": "verify", "status": "completed"}]}
    provider = _ScriptedProvider(
        (
            (
                _response(
                    ToolCallPart("todo-1", "TodoWrite", pending),
                    finish_reason=FinishReason.TOOL_CALLS,
                ),
            ),
            (TextDelta("hidden premature"), _response(TextPart("premature"), usage=Usage(1, 2))),
            (
                _response(
                    ToolCallPart("todo-2", "TodoWrite", completed),
                    finish_reason=FinishReason.TOOL_CALLS,
                ),
            ),
            (_response(TextPart("done")),),
        )
    )
    application = create_application(
        _config(),
        provider_builder=lambda _provider, _model: provider,
        runtime_context=_context(tmp_path),
    )
    run = application.create_run(run_id="todo-run")
    handle = run.start_turn("implement")

    events = await asyncio.wait_for(_collect(handle), timeout=1)
    result = await asyncio.wait_for(handle.result(), timeout=1)

    assert result.status is RunStatus.COMPLETED and result.final_text == "done"
    assert [event.unfinished_count for event in events if isinstance(event, CompletionBlocked)] == [1]
    assert len([event for event in events if isinstance(event, TaskStateChanged)]) == 2
    assert sum(isinstance(event, TurnCompleted) for event in events) == 1
    assert not any(
        isinstance(event, AssistantMessageDelta) and event.text == "hidden premature"
        for event in events
    )
    assert "一次性运行反馈类型：completion_blocked" in _context_text(provider.requests[2])
    assert "[completed] verify" in _context_text(provider.requests[3])
    snapshot_payload = run.snapshot().to_dict()
    assert "task_state" not in snapshot_payload and "plan_state" not in snapshot_payload
    next_handle = run.start_turn("next turn")
    next_result = await asyncio.wait_for(next_handle.result(), timeout=1)
    assert next_result.status is RunStatus.COMPLETED
    assert "当前 TaskState：空" in _context_text(provider.requests[4])
    assert "一次性运行反馈类型" not in _context_text(provider.requests[4])


@pytest.mark.asyncio
async def test_t08_application_steering_interrupts_provider_and_cleans_coordination(
    tmp_path: Path,
) -> None:
    provider = _StreamingGatedProvider(
        _response(TextPart("updated answer"), usage=Usage(2, 3))
    )
    application = create_application(
        _config(),
        provider_builder=lambda _provider, _model: provider,
        runtime_context=_context(tmp_path),
    )
    run = application.create_run(run_id="steer-run")
    handle = run.start_turn("implement")
    events_task = asyncio.create_task(_collect(handle))
    await provider.partial_emitted.wait()

    with pytest.raises(TypeError, match="string"):
        handle.steer(123)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="non-empty"):
        handle.steer("   ")
    assert handle.steer("also verify tests") is True
    assert handle.steer("duplicate pending request") is False
    provider.release.set()

    events = await asyncio.wait_for(events_task, timeout=1)
    result = await asyncio.wait_for(handle.result(), timeout=1)

    assert result.status is RunStatus.COMPLETED
    assert result.run_id == "steer-run" and result.final_text == "updated answer"
    assert len(provider.requests) == 2
    conversation = tuple(
        message
        for message in provider.requests[1].messages
        if not _is_context_message(message)
    )
    assert [message.role for message in conversation] == ["user", "user"]
    assert _latest_user_text(provider.requests[1]) == "also verify tests"
    requested = [event for event in events if isinstance(event, UserSteeringRequested)]
    applied = [event for event in events if isinstance(event, UserSteeringApplied)]
    assert len(requested) == len(applied) == 1
    assert requested[0].steering_id == applied[0].steering_id
    assert sum(isinstance(event, TurnStarted) for event in events) == 1
    assert sum(isinstance(event, TurnCompleted) for event in events) == 1
    assert "一次性运行反馈类型：user_steering" in _context_text(provider.requests[1])
    assert handle.steer("after terminal") is False
    assert handle._driver.execution.pending_steering is None
    assert handle._driver._response_waiter is None
    assert handle._driver._segment_signal is None


@pytest.mark.asyncio
async def test_t08_application_plan_generation_accepts_steering_but_review_pause_does_not(
    tmp_path: Path,
) -> None:
    provider = _StreamingGatedProvider(
        _response(
            ToolCallPart("plan-steered", "ProposePlan", {"plan": "Plan after steering"}),
            finish_reason=FinishReason.TOOL_CALLS,
        )
    )
    application = create_application(
        _config(),
        provider_builder=lambda _provider, _model: provider,
        runtime_context=_context(tmp_path),
    )
    run = application.create_run(run_id="plan-steer")
    run.set_behavior_mode(BehaviorMode.PLAN)
    handle = run.start_turn("make a plan")
    events_task = asyncio.create_task(_collect(handle))
    await provider.partial_emitted.wait()

    assert handle.steer("also cover rollback") is True
    provider.release.set()
    for _ in range(100):
        if handle.pending_pause is not None:
            break
        await asyncio.sleep(0)
    pending = handle.pending_pause
    assert pending is not None and pending.kind is PauseKind.PLAN_REVIEW_REQUIRED
    assert pending.plan_review_request is not None
    assert pending.plan_review_request.plan_text == "Plan after steering"
    assert run.behavior_mode is BehaviorMode.PLAN
    assert handle.steer("must use typed revise now") is False
    conversation = tuple(
        message
        for message in provider.requests[1].messages
        if not _is_context_message(message)
    )
    assert [message.role for message in conversation] == ["user", "user"]
    assert _latest_user_text(provider.requests[1]) == "also cover rollback"
    assert [item.name for item in provider.requests[1].tools] == [
        "ReadFile",
        "Glob",
        "Grep",
        "Bash",
        "ToolResultRead",
        "HistoryRead",
        "AskUserQuestion",
        "ProposePlan",
    ]
    assert "一次性运行反馈类型：user_steering" in _context_text(provider.requests[1])
    assert handle.cancel() is True

    events = await asyncio.wait_for(events_task, timeout=1)
    result = await asyncio.wait_for(handle.result(), timeout=1)
    assert result.status is RunStatus.CANCELLED
    assert len([event for event in events if isinstance(event, UserSteeringApplied)]) == 1
    assert len([event for event in events if isinstance(event, PlanProposed)]) == 1
    assert handle._driver.execution.pending_steering is None


@pytest.mark.asyncio
async def test_t08_plan_approval_updates_active_run_and_next_turn_keeps_default_mode(
    tmp_path: Path,
) -> None:
    question = UserQuestion("scope", "Scope", "Proceed?", QuestionKind.TEXT)
    ask_request = UserInputRequest((question,))
    provider = _ScriptedProvider(
        (
            (_response(ToolCallPart("plan-1", "ProposePlan", {"plan": "Plan v1"}), finish_reason=FinishReason.TOOL_CALLS),),
            (
                _response(
                    ToolCallPart(
                        "ask-after-approve",
                        "AskUserQuestion",
                        ask_request.to_dict(),
                    ),
                    finish_reason=FinishReason.TOOL_CALLS,
                ),
            ),
            (_response(TextPart("implemented")),),
            (_response(TextPart("next turn")),),
        )
    )
    application = create_application(
        _config(),
        provider_builder=lambda _provider, _model: provider,
        runtime_context=_context(tmp_path),
    )
    run = application.create_run(run_id="mode-persist")
    run.set_behavior_mode(BehaviorMode.PLAN)
    handle = run.start_turn("plan then implement")
    events_task = asyncio.create_task(_collect(handle))

    for _ in range(100):
        if handle.pending_pause is not None:
            break
        await asyncio.sleep(0)
    plan_pause = handle.pending_pause
    assert plan_pause is not None and plan_pause.plan_review_request is not None
    assert handle.resume(
        PlanReviewResponse(
            plan_pause.pause_id,
            plan_pause.run_id,
            plan_pause.turn_id,
            1,
            PlanReviewChoice.APPROVE,
        )
    ) is True

    for _ in range(100):
        pending = handle.pending_pause
        if pending is not None and pending.kind is PauseKind.USER_INPUT_REQUIRED:
            break
        await asyncio.sleep(0)
    ask_pause = handle.pending_pause
    assert ask_pause is not None and ask_pause.kind is PauseKind.USER_INPUT_REQUIRED
    assert run.behavior_mode is BehaviorMode.DEFAULT
    assert handle.steer("typed input wins") is False
    assert [item.name for item in provider.requests[1].tools] == [
        "ReadFile",
        "WriteFile",
        "EditFile",
        "Glob",
        "Grep",
        "Bash",
        "ToolResultRead",
        "HistoryRead",
        "AskUserQuestion",
        "TodoWrite",
    ]
    assert handle.resume(
        UserInputResponse(
            ask_pause.pause_id,
            ask_pause.run_id,
            ask_pause.turn_id,
            "ask-after-approve",
            {"scope": ["yes"]},
        )
    ) is True
    first_events = await asyncio.wait_for(events_task, timeout=1)
    first_result = await asyncio.wait_for(handle.result(), timeout=1)
    assert first_result.status is RunStatus.COMPLETED
    assert run.behavior_mode is BehaviorMode.DEFAULT
    assert sum(isinstance(event, BehaviorModeChanged) for event in first_events) == 1

    next_handle = run.start_turn("next")
    next_result = await asyncio.wait_for(next_handle.result(), timeout=1)
    assert next_result.status is RunStatus.COMPLETED
    assert run.behavior_mode is BehaviorMode.DEFAULT
    next_prompt = _context_text(provider.requests[3])
    assert "当前行为模式：DEFAULT" in next_prompt
    assert "当前 TaskState：空" in next_prompt
    assert "当前 PlanState：空" in next_prompt
    assert "一次性运行反馈类型" not in next_prompt


@pytest.mark.asyncio
async def test_t08_approved_plan_todo_state_survives_typed_pause_then_resets_next_turn(
    tmp_path: Path,
) -> None:
    pending_todo = {"todos": [{"content": "verify", "status": "in_progress"}]}
    completed_todo = {"todos": [{"content": "verify", "status": "completed"}]}
    question = UserQuestion("confirm", "Confirm", "Continue?", QuestionKind.TEXT)
    ask_request = UserInputRequest((question,))
    provider = _ScriptedProvider(
        (
            (_response(ToolCallPart("plan-1", "ProposePlan", {"plan": "Plan v1"}), finish_reason=FinishReason.TOOL_CALLS),),
            (
                _response(
                    ToolCallPart("todo-pending", "TodoWrite", pending_todo),
                    finish_reason=FinishReason.TOOL_CALLS,
                ),
            ),
            (
                _response(
                    ToolCallPart("ask-1", "AskUserQuestion", ask_request.to_dict()),
                    finish_reason=FinishReason.TOOL_CALLS,
                ),
            ),
            (
                _response(
                    ToolCallPart("todo-complete", "TodoWrite", completed_todo),
                    finish_reason=FinishReason.TOOL_CALLS,
                ),
            ),
            (_response(TextPart("done")),),
            (_response(TextPart("next")),),
        )
    )
    application = create_application(
        _config(),
        provider_builder=lambda _provider, _model: provider,
        runtime_context=_context(tmp_path),
    )
    run = application.create_run(run_id="plan-todo-pause")
    run.set_behavior_mode(BehaviorMode.PLAN)
    handle = run.start_turn("plan and execute")
    events_task = asyncio.create_task(_collect(handle))

    for _ in range(100):
        if handle.pending_pause is not None:
            break
        await asyncio.sleep(0)
    plan_pause = handle.pending_pause
    assert plan_pause is not None and plan_pause.plan_review_request is not None
    assert handle.resume(
        PlanReviewResponse(
            plan_pause.pause_id,
            plan_pause.run_id,
            plan_pause.turn_id,
            1,
            PlanReviewChoice.APPROVE,
        )
    ) is True

    for _ in range(100):
        pending = handle.pending_pause
        if pending is not None and pending.kind is PauseKind.USER_INPUT_REQUIRED:
            break
        await asyncio.sleep(0)
    ask_pause = handle.pending_pause
    assert ask_pause is not None and ask_pause.kind is PauseKind.USER_INPUT_REQUIRED
    active_state = handle._driver.execution.state
    assert active_state.plan_state is not None and active_state.plan_state.approved
    assert active_state.task_state.has_unfinished
    assert handle.resume(
        UserInputResponse(
            ask_pause.pause_id,
            ask_pause.run_id,
            ask_pause.turn_id,
            "ask-1",
            {"confirm": ["yes"]},
        )
    ) is True
    events = await asyncio.wait_for(events_task, timeout=1)
    result = await asyncio.wait_for(handle.result(), timeout=1)

    assert result.status is RunStatus.COMPLETED
    assert [event.task_state.has_unfinished for event in events if isinstance(event, TaskStateChanged)] == [
        True,
        False,
    ]
    assert "[in_progress] verify" in _context_text(provider.requests[2])
    assert "revision=1, approved" in _context_text(provider.requests[2])

    next_handle = run.start_turn("next")
    assert (await asyncio.wait_for(next_handle.result(), timeout=1)).status is RunStatus.COMPLETED
    assert "当前 TaskState：空" in _context_text(provider.requests[5])
    assert "当前 PlanState：空" in _context_text(provider.requests[5])


@pytest.mark.asyncio
async def test_t08_steering_preserves_task_state_until_model_explicitly_rewrites_it(
    tmp_path: Path,
) -> None:
    pending_todo = {"todos": [{"content": "old goal", "status": "in_progress"}]}
    completed_todo = {"todos": [{"content": "new goal", "status": "completed"}]}

    class GateSecondRequestProvider:
        identity = ProviderIdentity("fake", "gate-second", "fake-model")

        def resolve_model_limits(self, _model: str) -> ModelLimits:
            return ModelLimits(max_input_tokens=1_000_000, source="test.runtime")

        def __init__(self) -> None:
            self.requests: list[GenerationRequest] = []
            self.entered = asyncio.Event()
            self.release = asyncio.Event()

        async def stream(self, request, *, cancellation):
            self.requests.append(request)
            index = len(self.requests) - 1
            if index == 0:
                yield _response(
                    ToolCallPart("todo-old", "TodoWrite", pending_todo),
                    finish_reason=FinishReason.TOOL_CALLS,
                )
                return
            if index == 1:
                yield TextDelta("stale candidate")
                self.entered.set()
                await self.release.wait()
                cancellation.raise_if_cancelled()
                yield _response(TextPart("stale"))
                return
            if index == 2:
                yield _response(
                    ToolCallPart("todo-new", "TodoWrite", completed_todo),
                    finish_reason=FinishReason.TOOL_CALLS,
                )
                return
            yield _response(TextPart("done"))

    provider = GateSecondRequestProvider()
    application = create_application(
        _config(),
        provider_builder=lambda _provider, _model: provider,
        runtime_context=_context(tmp_path),
    )
    run = application.create_run(run_id="steer-task-state")
    handle = run.start_turn("old goal")
    events_task = asyncio.create_task(_collect(handle))
    await provider.entered.wait()
    assert handle._driver.execution.state.task_state.items[0].content == "old goal"
    assert handle.steer("replace with new goal") is True
    provider.release.set()

    events = await asyncio.wait_for(events_task, timeout=1)
    result = await asyncio.wait_for(handle.result(), timeout=1)
    assert result.status is RunStatus.COMPLETED
    assert [event.task_state.items[0].content for event in events if isinstance(event, TaskStateChanged)] == [
        "old goal",
        "new goal",
    ]
    steering_prompt = _context_text(provider.requests[2])
    assert "[in_progress] old goal" in steering_prompt
    assert "一次性运行反馈类型：user_steering" in steering_prompt

@pytest.mark.asyncio
@pytest.mark.parametrize("first_outcome", ["cancelled", "error", "completed"])
async def test_t08_steering_pending_makes_provider_pause_rejection_truthful(
    first_outcome: str,
) -> None:
    provider = _SteeringRaceProvider(first_outcome)
    run = UthCodeApplication(provider).create_run(run_id=f"steer-{first_outcome}")
    handle = run.start_turn("initial goal")
    events_task = asyncio.create_task(_collect(handle))
    await provider.entered.wait()

    assert handle.steer("updated goal") is True
    assert handle.pause() is False
    provider.release.set()

    events = await asyncio.wait_for(events_task, timeout=1)
    result = await asyncio.wait_for(handle.result(), timeout=1)
    assert result.status is RunStatus.COMPLETED
    assert result.final_text == "updated answer"
    assert len(provider.requests) == 2
    assert _latest_user_text(provider.requests[1]) == "updated goal"
    assert sum(isinstance(event, UserSteeringApplied) for event in events) == 1
    assert not any(isinstance(event, TurnPaused) for event in events)


@pytest.mark.asyncio
async def test_t08_steering_pending_makes_tool_boundary_pause_rejection_truthful() -> None:
    tool = _ApplicationGateTool(gated=True)
    service = ApplicationToolService((tool,))
    calls = (
        ToolCallPart("tool-1", "Work", {"value": "one"}),
        ToolCallPart("tool-2", "Work", {"value": "two"}),
    )
    provider = _ScriptedProvider(
        (
            (_response(*calls, finish_reason=FinishReason.TOOL_CALLS),),
            (_response(TextPart("updated answer")),),
        )
    )
    run = UthCodeApplication(provider, tool_service=service).create_run(run_id="tool-steer")
    run.set_permission_mode(PermissionMode.FULL_ACCESS)
    handle = run.start_turn("initial goal")
    events_task = asyncio.create_task(_collect(handle))
    await tool.entered.wait()

    assert handle.steer("skip stale remainder") is True
    assert handle.pause() is False
    tool.release.set()

    events = await asyncio.wait_for(events_task, timeout=1)
    result = await asyncio.wait_for(handle.result(), timeout=1)
    assert result.status is RunStatus.COMPLETED
    assert tool.trace == ["preflight:one", "execute:one"]
    finished = [event for event in events if isinstance(event, ToolFinished)]
    assert [event.tool_call_id for event in finished] == ["tool-1", "tool-2"]
    assert [event.status for event in finished] == ["finished", "skipped"]
    assert [event.status for event in events if isinstance(event, ToolBatchFinished)] == [
        "steered"
    ]
    assert not any(isinstance(event, TurnPaused) for event in events)


def test_t08_idle_behavior_mode_is_run_local_without_runstate_replacement() -> None:
    run = UthCodeApplication(
        FakeProvider(events=(), model_limits=TEST_LIMITS)
    ).create_run(run_id="local-mode")
    initial_state = run._state
    initial_payload = initial_state.to_dict()

    assert run.set_behavior_mode(BehaviorMode.PLAN) is BehaviorMode.PLAN

    assert run._state is initial_state
    assert run._state.to_dict() == initial_payload
    assert run.behavior_mode is BehaviorMode.PLAN
    assert run.snapshot().behavior_mode is BehaviorMode.PLAN


@pytest.mark.asyncio
async def test_t08_plan_approve_applies_default_before_resumed_is_public(
    tmp_path: Path,
) -> None:
    provider = _ScriptedProvider(
        (
            (_response(ToolCallPart("plan-1", "ProposePlan", {"plan": "Plan v1"}), finish_reason=FinishReason.TOOL_CALLS),),
            (_response(TextPart("implemented")),),
        )
    )
    application = create_application(
        _config(),
        provider_builder=lambda _provider, _model: provider,
        runtime_context=_context(tmp_path),
    )
    run = application.create_run(run_id="approve-order")
    run.set_behavior_mode(BehaviorMode.PLAN)
    handle = run.start_turn("plan then implement")
    events_task = asyncio.create_task(_collect(handle))
    for _ in range(100):
        if handle.pending_pause is not None:
            break
        await asyncio.sleep(0)
    pending = handle.pending_pause
    assert pending is not None and pending.plan_review_request is not None

    assert handle.resume(
        PlanReviewResponse(
            pending.pause_id,
            pending.run_id,
            pending.turn_id,
            pending.plan_review_request.revision,
            PlanReviewChoice.APPROVE,
        )
    ) is True
    assert run.behavior_mode is BehaviorMode.DEFAULT
    assert handle._driver.execution.state.plan_state is not None
    assert handle._driver.execution.state.plan_state.approved

    events = await asyncio.wait_for(events_task, timeout=1)
    result = await asyncio.wait_for(handle.result(), timeout=1)
    assert result.status is RunStatus.COMPLETED
    event_types = [event.event_type for event in events]
    assert event_types.index("behavior_mode_changed") < event_types.index("turn_resumed")
    assert event_types.count("turn_resumed") == 1


@pytest.mark.asyncio
async def test_t08_plan_approve_then_cancel_is_cancel_wins_without_resumed(
    tmp_path: Path,
) -> None:
    provider = _ScriptedProvider(((_response(ToolCallPart("plan-1", "ProposePlan", {"plan": "Plan v1"}), finish_reason=FinishReason.TOOL_CALLS),),))
    application = create_application(
        _config(),
        provider_builder=lambda _provider, _model: provider,
        runtime_context=_context(tmp_path),
    )
    run = application.create_run(run_id="approve-cancel")
    run.set_behavior_mode(BehaviorMode.PLAN)
    handle = run.start_turn("plan")
    events_task = asyncio.create_task(_collect(handle))
    for _ in range(100):
        if handle.pending_pause is not None:
            break
        await asyncio.sleep(0)
    pending = handle.pending_pause
    assert pending is not None and pending.plan_review_request is not None

    assert handle.resume(
        PlanReviewResponse(
            pending.pause_id,
            pending.run_id,
            pending.turn_id,
            pending.plan_review_request.revision,
            PlanReviewChoice.APPROVE,
        )
    ) is True
    assert run.behavior_mode is BehaviorMode.DEFAULT
    assert handle.cancel() is True

    events = await asyncio.wait_for(events_task, timeout=1)
    result = await asyncio.wait_for(handle.result(), timeout=1)
    assert result.status is RunStatus.CANCELLED
    assert not any(isinstance(event, TurnResumed) for event in events)
    assert sum(isinstance(event, TurnCancelled) for event in events) == 1
