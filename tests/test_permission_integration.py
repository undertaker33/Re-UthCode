from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Iterable

import pytest

from uthcode.application import (
    AgentRun,
    PermissionApprovalChoice,
    PermissionApprovalRequest,
    PermissionApprovalResponse,
    PermissionMode,
    TurnHandle,
    UthCodeApplication,
)
from uthcode.core.agent_events import ToolFinished, TurnCompleted, TurnPaused
from uthcode.core.permission import (
    Decision,
    Effect,
    PermissionAction,
    PermissionEvaluator,
    ResourceScope,
    Rule,
    RuleKind,
    RuleSet,
)
from uthcode.core.provider import (
    CancellationToken,
    FinishReason,
    GenerationCompleted,
    GenerationRequest,
    Message,
    ModelLimits,
    ProviderIdentity,
    ProviderResponse,
    TextPart,
    ToolCallPart,
    Usage,
)
from uthcode.core.tool import ToolExecutionResult, ToolPreparation
from uthcode.core.provider import ToolDefinition
from uthcode.application.tools import ApplicationToolService


def _completed(*parts: object, finish_reason: FinishReason) -> GenerationCompleted:
    return GenerationCompleted(
        ProviderResponse(
            message=Message("assistant", tuple(parts)),
            usage=Usage(),
            finish_reason=finish_reason,
        )
    )


class _ScriptedProvider:
    identity = ProviderIdentity("fake", "permission", "model")

    def __init__(self, scripts: Iterable[Iterable[object]]) -> None:
        self.scripts = tuple(tuple(script) for script in scripts)
        self.requests: list[GenerationRequest] = []

    def resolve_model_limits(self, model: str) -> ModelLimits:
        del model
        return ModelLimits(max_input_tokens=1_000_000, source="test.runtime")

    async def stream(
        self,
        request: GenerationRequest,
        *,
        cancellation: CancellationToken,
    ):
        self.requests.append(request)
        cancellation.raise_if_cancelled()
        index = min(len(self.requests) - 1, len(self.scripts) - 1)
        for event in self.scripts[index]:
            cancellation.raise_if_cancelled()
            yield event


@dataclass
class _PreparedTool:
    name: str = "Write"
    resource: str = "safe.txt"
    started: list[str] = field(default_factory=list)
    preflight_count: int = 0

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

    def preflight(self, arguments):  # type: ignore[no-untyped-def]
        self.preflight_count += 1
        return ToolPreparation(
            PermissionAction(
                self.name,
                "write",
                Effect.WRITE,
                self.resource,
                ResourceScope.INSIDE,
            ),
            arguments,
        )

    async def execute(self, arguments, *, cancellation: CancellationToken):  # type: ignore[no-untyped-def]
        cancellation.raise_if_cancelled()
        self.started.append(str(arguments["value"]))
        return ToolExecutionResult("written")


@dataclass
class _ReadTool:
    started: list[str] = field(default_factory=list)

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            "Read",
            parameters={
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
                "additionalProperties": False,
            },
        )

    def preflight(self, arguments):  # type: ignore[no-untyped-def]
        return ToolPreparation(
            PermissionAction(
                "Read",
                "read",
                Effect.READ,
                "safe.txt",
                ResourceScope.INSIDE,
            ),
            arguments,
        )

    async def execute(self, arguments, *, cancellation: CancellationToken):  # type: ignore[no-untyped-def]
        cancellation.raise_if_cancelled()
        self.started.append(str(arguments["value"]))
        return ToolExecutionResult("read")


def _application(
    provider: _ScriptedProvider,
    *tools: object,
) -> UthCodeApplication:
    return UthCodeApplication(
        provider,
        tool_service=ApplicationToolService(tuple(tools)),  # type: ignore[arg-type]
    )


async def _collect_until_end(
    handle: TurnHandle,
    *,
    run: AgentRun | None = None,
    response_choice: PermissionApprovalChoice | None = None,
    mode_after_pause: PermissionMode | None = None,
) -> list[object]:
    events: list[object] = []
    async for event in handle.events():
        events.append(event)
        if isinstance(event, TurnPaused):
            if mode_after_pause is not None:
                assert run is not None
                run.set_permission_mode(mode_after_pause)
            if response_choice is not None:
                request = event.pause.permission_request
                assert request is not None
                assert handle.resume(
                    PermissionApprovalResponse(
                        pause_id=event.pause.pause_id,
                        run_id=event.pause.run_id,
                        turn_id=event.pause.turn_id,
                        permission_id=request.permission_id,
                        choice=response_choice,
                    )
                )
    return events


@pytest.mark.asyncio
async def test_permission_pause_round_trip_uses_prepared_call_once_and_snapshots_mode() -> None:
    tool = _PreparedTool()
    call = ToolCallPart("write-1", "Write", {"value": "one"})
    provider = _ScriptedProvider(
        (
            (_completed(call, finish_reason=FinishReason.TOOL_CALLS),),
            (_completed(TextPart("done"), finish_reason=FinishReason.STOP),),
        )
    )
    run = AgentRun(
        _application(provider, tool),
        run_id="run-1",
        permission_evaluator=PermissionEvaluator(),
    )
    handle = run.start_turn("write")

    events = await _collect_until_end(
        handle,
        run=run,
        response_choice=PermissionApprovalChoice.ONCE,
        mode_after_pause=PermissionMode.FULL_ACCESS,
    )

    pause = next(event for event in events if isinstance(event, TurnPaused))
    assert pause.pause.permission_request is not None
    assert pause.pause.permission_request.mode is PermissionMode.DEFAULT
    assert tool.preflight_count == 1
    assert tool.started == ["one"]
    assert isinstance(events[-1], TurnCompleted)


@pytest.mark.asyncio
async def test_reject_finishes_one_call_and_continues_the_same_batch() -> None:
    write = _PreparedTool()
    read = _ReadTool()
    first = ToolCallPart("write-1", "Write", {"value": "blocked"})
    second = ToolCallPart("read-1", "Read", {"value": "safe"})
    provider = _ScriptedProvider(
        (
            (_completed(first, second, finish_reason=FinishReason.TOOL_CALLS),),
            (_completed(TextPart("continued"), finish_reason=FinishReason.STOP),),
        )
    )
    run = AgentRun(_application(provider, write, read), run_id="run-1")
    handle = run.start_turn("continue")

    events = await _collect_until_end(
        handle,
        response_choice=PermissionApprovalChoice.REJECT,
    )

    finished = [event for event in events if isinstance(event, ToolFinished)]
    assert [event.tool_call_id for event in finished] == ["write-1", "read-1"]
    assert finished[0].is_error is True
    assert finished[1].is_error is False
    assert write.started == []
    assert read.started == ["safe"]


@pytest.mark.asyncio
async def test_policy_deny_returns_error_without_pause_or_execution() -> None:
    tool = _PreparedTool()
    call = ToolCallPart("write-1", "Write", {"value": "blocked"})
    provider = _ScriptedProvider(
        (
            (_completed(call, finish_reason=FinishReason.TOOL_CALLS),),
            (_completed(TextPart("denied"), finish_reason=FinishReason.STOP),),
        )
    )
    evaluator = PermissionEvaluator(
        RuleSet(
            (
                Rule(
                    kind=RuleKind.POLICY,
                    decision=Decision.DENY,
                    tool="Write",
                    action="write",
                    source="test-policy",
                ),
            )
        )
    )
    run = AgentRun(
        _application(provider, tool),
        run_id="run-1",
        permission_evaluator=evaluator,
    )

    events = await _collect_until_end(run.start_turn("deny"))

    finished = [event for event in events if isinstance(event, ToolFinished)]
    assert not any(isinstance(event, TurnPaused) for event in events)
    assert len(finished) == 1
    assert finished[0].is_error is True
    assert tool.started == []


@pytest.mark.asyncio
async def test_session_grant_is_run_local_and_exact() -> None:
    tool = _PreparedTool()
    call = ToolCallPart("write-1", "Write", {"value": "first"})
    later = ToolCallPart("write-2", "Write", {"value": "second"})
    provider = _ScriptedProvider(
        (
            (_completed(call, finish_reason=FinishReason.TOOL_CALLS),),
            (_completed(TextPart("first done"), finish_reason=FinishReason.STOP),),
            (_completed(later, finish_reason=FinishReason.TOOL_CALLS),),
            (_completed(TextPart("second done"), finish_reason=FinishReason.STOP),),
            (_completed(later, finish_reason=FinishReason.TOOL_CALLS),),
            (_completed(TextPart("new run done"), finish_reason=FinishReason.STOP),),
        )
    )
    application = _application(provider, tool)
    evaluator = PermissionEvaluator()
    run = AgentRun(application, run_id="run-1", permission_evaluator=evaluator)

    await _collect_until_end(
        run.start_turn("first"),
        response_choice=PermissionApprovalChoice.SESSION,
    )
    assert len(run.session_grants) == 1
    second_events = await _collect_until_end(run.start_turn("second"))
    assert not any(isinstance(event, TurnPaused) for event in second_events)

    new_run = AgentRun(application, run_id="run-2", permission_evaluator=evaluator)
    third_handle = new_run.start_turn("new run")
    third_events_task = asyncio.create_task(_collect_until_end(third_handle))
    for _ in range(100):
        if third_handle.pending_pause is not None:
            break
        await asyncio.sleep(0)
    assert third_handle.pending_pause is not None
    third_handle.cancel()
    await third_events_task
    assert new_run.permission_mode is PermissionMode.DEFAULT


def test_guard_approval_has_no_session_choice() -> None:
    action = PermissionAction(
        "Write",
        "write",
        Effect.WRITE,
        "safe.txt",
        ResourceScope.INSIDE,
    )
    evaluator = PermissionEvaluator(
        RuleSet(
            (
                Rule(
                    kind=RuleKind.GUARD,
                    decision=Decision.ASK,
                    tool="Write",
                    source="test",
                ),
            )
        )
    )
    decision = evaluator.evaluate(action)
    assert decision.decision is Decision.ASK
    request = PermissionApprovalRequest.from_decision(
        decision,
        permission_id="permission-guard",
        run_id="run-1",
        turn_id="turn-1",
        tool_call_id="call-1",
    )
    assert request.choices == (
        PermissionApprovalChoice.ONCE,
        PermissionApprovalChoice.REJECT,
    )


@pytest.mark.asyncio
async def test_cancel_wins_while_permission_is_pending() -> None:
    tool = _PreparedTool()
    call = ToolCallPart("write-1", "Write", {"value": "never"})
    provider = _ScriptedProvider(
        ((_completed(call, finish_reason=FinishReason.TOOL_CALLS),),)
    )
    run = AgentRun(_application(provider, tool), run_id="run-1")
    handle = run.start_turn("cancel")
    events_task = asyncio.create_task(_collect_until_end(handle))
    for _ in range(100):
        if handle.pending_pause is not None:
            break
        await asyncio.sleep(0)
    assert handle.pending_pause is not None
    assert handle.cancel() is True
    await events_task
    assert handle.pending_pause is None
    assert tool.started == []
    assert handle.cancelled() is True
