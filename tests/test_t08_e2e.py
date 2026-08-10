from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterable
from pathlib import Path

import pytest

from uthcode.application import (
    ApplicationRuntimeContext,
    EffectiveConfig,
    PlanReviewChoice,
    PlanReviewResponse,
    ProviderKind,
    PermissionMode,
    create_application,
)
from uthcode.core import (
    AgentEvent,
    AssistantMessageCompleted,
    AssistantMessageKind,
    BehaviorMode,
    CancellationToken,
    CompletionBlocked,
    FinishReason,
    GenerationCancelled,
    GenerationCompleted,
    Message,
    PauseKind,
    PermissionApprovalChoice,
    PermissionApprovalResponse,
    PlanProposed,
    ProviderIdentity,
    ProviderResponse,
    TaskStateChanged,
    TextPart,
    ToolCallPart,
    ToolDefinition,
    ToolExecutionResult,
    ToolFinished,
    ToolPreparation,
    ToolPlanningAccess,
    ToolStarted,
    TurnCancelled,
    TurnCompleted,
    TurnFailed,
    TurnPaused,
    TurnResumed,
    Usage,
)
from uthcode.core.permission import Effect, PermissionAction, ResourceScope
from uthcode.core.provider import GenerationRequest, JsonPayload, ProviderEvent
from uthcode.integrations.tools.factory import create_default_tools


def _completed(
    *parts: object,
    finish_reason: FinishReason = FinishReason.STOP,
    usage: Usage | None = None,
) -> GenerationCompleted:
    return GenerationCompleted(
        ProviderResponse(
            message=Message("assistant", tuple(parts)),
            finish_reason=finish_reason,
            usage=usage or Usage(input_tokens=1, output_tokens=1),
        )
    )


class _ScriptedFakeProvider:
    """Offline Provider that exposes every formal Application request."""

    def __init__(self, scripts: Iterable[Iterable[ProviderEvent]]) -> None:
        self.identity = ProviderIdentity("fake", "e2e", "fake-model")
        self._scripts = tuple(tuple(script) for script in scripts)
        self.requests: list[GenerationRequest] = []

    async def stream(
        self,
        request: GenerationRequest,
        *,
        cancellation: CancellationToken,
    ) -> AsyncIterator[ProviderEvent]:
        self.requests.append(request)
        cancellation.raise_if_cancelled()
        index = len(self.requests) - 1
        if index >= len(self._scripts):
            raise AssertionError(f"unexpected Provider request {index + 1}")
        for event in self._scripts[index]:
            cancellation.raise_if_cancelled()
            yield event


class _GatedReadTool:
    """A read-only test tool used only to create a real Tool safe boundary."""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            "WaitForSteering",
            "Wait for the E2E driver to submit a steering request.",
            {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        )

    @property
    def planning_access(self) -> ToolPlanningAccess:
        return ToolPlanningAccess.HIDDEN

    def preflight(self, arguments: JsonPayload) -> ToolPreparation:
        del arguments
        return ToolPreparation(
            PermissionAction(
                tool="WaitForSteering",
                action="read",
                effect=Effect.READ,
                resource="workspace/steering-gate",
                scope=ResourceScope.INSIDE,
            ),
            {},
        )

    async def execute(
        self,
        arguments: JsonPayload,
        *,
        cancellation: CancellationToken,
    ) -> ToolExecutionResult:
        del arguments
        self.started.set()
        await self.release.wait()
        cancellation.raise_if_cancelled()
        return ToolExecutionResult("steering gate released")


def _context(workdir: Path) -> ApplicationRuntimeContext:
    return ApplicationRuntimeContext.from_system(
        workdir=workdir,
        platform_name="TestOS",
        platform_release="1.0",
        current_date="2026-08-10",
    )


def _config() -> EffectiveConfig:
    return EffectiveConfig.single_model(
        "local/ref",
        provider_profile_id="local",
        provider_kind=ProviderKind.FAKE,
        remote_model_id="fake-model",
    )


def _tool_call(
    call_id: str,
    name: str,
    arguments: dict[str, object],
) -> ToolCallPart:
    return ToolCallPart(call_id, name, arguments)


def _tool_names(provider: _ScriptedFakeProvider, index: int) -> tuple[str, ...]:
    return tuple(tool.name for tool in provider.requests[index].tools)


@pytest.mark.asyncio
async def test_t08_formal_application_e2e_plan_execution_steering_and_reset(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    notes = workspace / "notes.txt"
    notes.write_text("seed\n", encoding="utf-8")
    stale = workspace / "stale.txt"
    result_file = workspace / "result.txt"
    gate = _GatedReadTool()

    provider = _ScriptedFakeProvider(
        (
            (
                _completed(
                    _tool_call("plan-read", "ReadFile", {"path": "notes.txt"}),
                    finish_reason=FinishReason.TOOL_CALLS,
                ),
            ),
            (_completed(TextPart("Plan v1: inspect and implement.")),),
            (_completed(TextPart("Plan v2: preserve the public API and verify output.")),),
            (
                _completed(
                    _tool_call(
                        "todo-start",
                        "TodoWrite",
                        {
                            "todos": [
                                {"content": "write result", "status": "in_progress"},
                                {"content": "verify result", "status": "pending"},
                            ]
                        },
                    ),
                    finish_reason=FinishReason.TOOL_CALLS,
                ),
            ),
            (_completed(TextPart("premature final")),),
            (
                _completed(
                    _tool_call("gate", "WaitForSteering", {}),
                    _tool_call(
                        "stale-write",
                        "WriteFile",
                        {"path": "stale.txt", "content": "must not run"},
                    ),
                    finish_reason=FinishReason.TOOL_CALLS,
                ),
            ),
            (
                _completed(
                    _tool_call(
                        "write-result",
                        "WriteFile",
                        {"path": "result.txt", "content": "implemented"},
                    ),
                    _tool_call(
                        "edit-notes",
                        "EditFile",
                        {
                            "path": "notes.txt",
                            "old_string": "seed",
                            "new_string": "seed + steered",
                        },
                    ),
                    finish_reason=FinishReason.TOOL_CALLS,
                ),
            ),
            (
                _completed(
                    _tool_call("verify-read", "ReadFile", {"path": "notes.txt"}),
                    _tool_call(
                        "todo-complete",
                        "TodoWrite",
                        {
                            "todos": [
                                {"content": "write result", "status": "completed"},
                                {"content": "verify result", "status": "completed"},
                            ]
                        },
                    ),
                    finish_reason=FinishReason.TOOL_CALLS,
                ),
            ),
            (_completed(TextPart("completed after steering")),),
            (_completed(TextPart("next turn is reset")),),
        )
    )
    application = create_application(
        _config(),
        provider_builder=lambda _profile, _model: provider,
        runtime_context=_context(workspace),
        tools=(*create_default_tools(workspace), gate),
    )
    run = application.create_run(run_id="e2e-run")
    run.set_behavior_mode(BehaviorMode.PLAN)
    run.set_permission_mode(PermissionMode.AUTO)
    handle = run.start_turn("implement the requested change")
    events: list[AgentEvent] = []

    async for event in handle.events():
        events.append(event)
        if isinstance(event, PlanProposed) and event.revision == 1:
            pending = handle.pending_pause
            assert pending is not None
            assert pending.kind is PauseKind.PLAN_REVIEW_REQUIRED
            assert handle.steer("bypass typed Plan review") is False
            with pytest.raises(ValueError):
                handle.resume(
                    PlanReviewResponse(
                        "stale-pause",
                        pending.run_id,
                        pending.turn_id,
                        event.revision,
                        PlanReviewChoice.APPROVE,
                    )
                )
            assert handle.resume(
                PlanReviewResponse(
                    pending.pause_id,
                    pending.run_id,
                    pending.turn_id,
                    event.revision,
                    PlanReviewChoice.REVISE,
                    "preserve the public API",
                )
            )
        elif isinstance(event, PlanProposed) and event.revision == 2:
            pending = handle.pending_pause
            assert pending is not None
            assert run.behavior_mode is BehaviorMode.PLAN
            assert handle.resume(
                PlanReviewResponse(
                    pending.pause_id,
                    pending.run_id,
                    pending.turn_id,
                    event.revision,
                    PlanReviewChoice.APPROVE,
                )
            )
            assert run.behavior_mode is BehaviorMode.DEFAULT
        elif isinstance(event, ToolStarted) and event.tool_call_id == "gate":
            assert handle.steer("also verify the result") is True
            gate.release.set()

    result = await handle.result()
    assert result.final_text == "completed after steering"
    assert result.status.value == "completed"

    assert _tool_names(provider, 0) == (
        "ReadFile",
        "Glob",
        "Grep",
        "Bash",
        "AskUserQuestion",
    )
    assert _tool_names(provider, 3) == (
        "ReadFile",
        "WriteFile",
        "EditFile",
        "Glob",
        "Grep",
        "Bash",
        "WaitForSteering",
        "AskUserQuestion",
        "TodoWrite",
    )
    assert _tool_names(provider, 6) == _tool_names(provider, 3)

    plan_events = [event for event in events if isinstance(event, PlanProposed)]
    assert [(event.run_id, event.revision) for event in plan_events] == [
        ("e2e-run", 1),
        ("e2e-run", 2),
    ]
    assert len({event.turn_id for event in plan_events}) == 1
    assert len([event for event in events if isinstance(event, CompletionBlocked)]) == 1
    assert len([event for event in events if isinstance(event, TaskStateChanged)]) >= 2
    assert len([event for event in events if isinstance(event, TurnResumed)]) == 2
    assert sum(
        isinstance(event, AssistantMessageCompleted)
        and event.kind is AssistantMessageKind.FINAL
        for event in events
    ) == 1
    terminals = [
        event
        for event in events
        if isinstance(event, (TurnCompleted, TurnFailed, TurnCancelled))
    ]
    assert len(terminals) == 1
    assert isinstance(terminals[0], TurnCompleted)

    stale_finished = [
        event
        for event in events
        if isinstance(event, ToolFinished) and event.tool_call_id == "stale-write"
    ]
    assert len(stale_finished) == 1
    assert stale_finished[0].status == "skipped"
    assert not stale.exists()
    assert result_file.read_text(encoding="utf-8") == "implemented"
    assert notes.read_text(encoding="utf-8") == "seed + steered\n"

    steering_occurrences = [
        sum(
            isinstance(part, TextPart) and part.text == "also verify the result"
            for message in request.messages
            if message.role == "user"
            for part in message.parts
        )
        for request in provider.requests
    ]
    assert steering_occurrences[:6] == [0] * 6
    assert all(count == 1 for count in steering_occurrences[6:])
    steering_request = provider.requests[6]
    assert "一次性运行反馈类型：user_steering" in (steering_request.system_prompt or "")

    next_handle = run.start_turn("check the next turn")
    next_events = [event async for event in next_handle.events()]
    next_result = await next_handle.result()
    assert next_result.final_text == "next turn is reset"
    assert run.behavior_mode is BehaviorMode.DEFAULT
    next_request = provider.requests[-1]
    assert "当前 TaskState：空。" in (next_request.system_prompt or "")
    assert "当前 PlanState：空。" in (next_request.system_prompt or "")
    assert "一次性运行反馈类型：" not in (next_request.system_prompt or "")
    assert any(
        message.role == "user"
        and any(
            isinstance(part, TextPart) and part.text == "implement the requested change"
            for part in message.parts
        )
        for message in next_request.messages
    )
    assert any(isinstance(event, TurnCompleted) for event in next_events)


@pytest.mark.asyncio
async def test_t08_plan_full_access_rejects_hidden_write_before_permission(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    protected = workspace / "protected.txt"
    provider = _ScriptedFakeProvider(
        (
            (
                _completed(
                    _tool_call(
                        "hidden-write",
                        "WriteFile",
                        {"path": "protected.txt", "content": "must not write"},
                    ),
                    finish_reason=FinishReason.TOOL_CALLS,
                ),
            ),
            (_completed(TextPart("read-only plan")),),
        )
    )
    application = create_application(
        _config(),
        provider_builder=lambda _profile, _model: provider,
        runtime_context=_context(workspace),
        tools=create_default_tools(workspace),
    )
    run = application.create_run(run_id="plan-full-access")
    run.set_behavior_mode(BehaviorMode.PLAN)
    run.set_permission_mode(PermissionMode.FULL_ACCESS)
    handle = run.start_turn("plan without writes")
    events: list[AgentEvent] = []

    async for event in handle.events():
        events.append(event)
        if isinstance(event, PlanProposed):
            assert handle.cancel() is True

    result = await handle.result()
    assert result.status.value == "cancelled"
    assert not protected.exists()
    assert _tool_names(provider, 0) == (
        "ReadFile",
        "Glob",
        "Grep",
        "Bash",
        "AskUserQuestion",
    )
    finished = [
        event
        for event in events
        if isinstance(event, ToolFinished) and event.tool_call_id == "hidden-write"
    ]
    assert len(finished) == 1
    assert finished[0].status == "failed"
    assert len([event for event in events if isinstance(event, TurnCancelled)]) == 1
    assert not any(isinstance(event, TurnCompleted) for event in events)


@pytest.mark.asyncio
async def test_t08_sensitive_read_pause_and_typed_interaction_precedence(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    secret = "W04-SECRET-CONTENT"
    (workspace / ".env").write_text(f"TOKEN={secret}\n", encoding="utf-8")
    provider = _ScriptedFakeProvider(
        (
            (
                _completed(
                    _tool_call("sensitive-read", "ReadFile", {"path": ".env"}),
                    finish_reason=FinishReason.TOOL_CALLS,
                ),
            ),
            (_completed(TextPart("guarded plan")),),
        )
    )
    application = create_application(
        _config(),
        provider_builder=lambda _profile, _model: provider,
        runtime_context=_context(workspace),
        tools=create_default_tools(workspace),
    )
    run = application.create_run(run_id="sensitive-plan")
    run.set_behavior_mode(BehaviorMode.PLAN)
    handle = run.start_turn("inspect the configuration safely")
    events: list[AgentEvent] = []

    async for event in handle.events():
        events.append(event)
        if isinstance(event, TurnPaused) and event.pause.kind is PauseKind.PERMISSION_REQUIRED:
            request = event.pause.permission_request
            assert request is not None
            assert request.guard is True
            assert request.tool == "ReadFile"
            assert handle.steer("bypass this approval") is False
            assert handle.resume(
                PermissionApprovalResponse(
                    event.pause.pause_id,
                    event.pause.run_id,
                    event.pause.turn_id,
                    request.permission_id,
                    PermissionApprovalChoice.REJECT,
                )
            )
        elif isinstance(event, PlanProposed):
            assert handle.cancel() is True

    result = await handle.result()
    assert result.status.value == "cancelled"
    assert all(secret not in event.to_json() for event in events)
    assert len([event for event in events if isinstance(event, TurnCancelled)]) == 1


@pytest.mark.asyncio
async def test_t08_cancel_wins_over_pending_steering_generation(
    tmp_path: Path,
) -> None:
    class _BlockingProvider:
        def __init__(self) -> None:
            self.identity = ProviderIdentity("fake", "cancel-race", "fake-model")
            self.entered = asyncio.Event()
            self.requests: list[GenerationRequest] = []

        async def stream(
            self,
            request: GenerationRequest,
            *,
            cancellation: CancellationToken,
        ) -> AsyncIterator[ProviderEvent]:
            self.requests.append(request)
            self.entered.set()
            await cancellation.wait()
            raise GenerationCancelled()
            if False:
                yield _completed(TextPart("unreachable"))

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    provider = _BlockingProvider()
    application = create_application(
        _config(),
        provider_builder=lambda _profile, _model: provider,
        runtime_context=_context(workspace),
        tools=create_default_tools(workspace),
    )
    handle = application.create_run(run_id="cancel-race").start_turn("initial goal")
    observer = asyncio.create_task(handle.result())
    await provider.entered.wait()
    assert handle.steer("updated goal") is True
    assert handle.cancel() is True
    result = await observer
    assert result.status.value == "cancelled"
    assert len(provider.requests) == 1
    assert handle.steer("after cancel") is False
