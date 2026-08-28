from __future__ import annotations

from collections.abc import AsyncIterator, Iterable
from pathlib import Path

import pytest

from uthcode.application import (
    ApplicationRuntimeContext,
    EffectiveConfig,
    PermissionApprovalChoice,
    PermissionApprovalResponse,
    PermissionMode,
    ProviderKind,
    create_application,
)
from uthcode.core.agent_events import ToolFinished, TurnPaused
from uthcode.core.provider import (
    CancellationToken,
    FinishReason,
    GenerationCompleted,
    GenerationRequest,
    Message,
    ProviderEvent,
    ProviderIdentity,
    ProviderResponse,
    TextPart,
    ToolCallPart,
    Usage,
)
from uthcode.core.tool import ToolExecutionResult
from uthcode.integrations.tools.process_tools import BashTool


def _completed(*parts: object, finish_reason: FinishReason) -> GenerationCompleted:
    return GenerationCompleted(
        ProviderResponse(Message("assistant", tuple(parts)), Usage(), finish_reason)
    )


def _latest_tool_message(request: GenerationRequest) -> Message:
    for message in reversed(request.messages):
        if message.role == "tool":
            return message
    raise AssertionError("request has no tool message")


class _ScriptedProvider:
    identity = ProviderIdentity("fake", "t07-1", "offline")

    def __init__(self, scripts: Iterable[Iterable[ProviderEvent]]) -> None:
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
        for event in self._scripts[len(self.requests) - 1]:
            yield event


class _SafeBash:
    def __init__(self, workdir: Path) -> None:
        self._tool = BashTool(workdir)
        self.definition = self._tool.definition
        self.preflight_count = 0
        self.execute_count = 0

    def preflight(self, arguments):  # type: ignore[no-untyped-def]
        self.preflight_count += 1
        return self._tool.preflight(arguments)

    async def execute(self, arguments, *, cancellation):  # type: ignore[no-untyped-def]
        del arguments, cancellation
        self.execute_count += 1
        return ToolExecutionResult("stubbed Bash execution")


def _application(workdir: Path, provider: _ScriptedProvider, tool: _SafeBash):
    configuration = EffectiveConfig.single_model(
        "t07-1/ref",
        provider_profile_id="t07-1",
        provider_kind=ProviderKind.FAKE,
        remote_id="offline",
        context_window=1_000_000,
    )
    context = ApplicationRuntimeContext.from_system(
        workdir=workdir,
        platform_name="Windows",
        platform_release="test",
        current_date="2026-08-13",
    )
    return create_application(
        configuration,
        provider_builder=lambda _provider, _model: provider,
        runtime_context=context,
        tools=(tool,),
    )


async def _run(handle, choice: PermissionApprovalChoice | None = None):
    events: list[object] = []
    async for event in handle.events():
        events.append(event)
        if isinstance(event, TurnPaused):
            request = event.pause.permission_request
            assert request is not None
            assert choice is not None
            assert handle.resume(
                PermissionApprovalResponse(
                    event.pause.pause_id,
                    event.run_id,
                    event.turn_id,
                    request.permission_id,
                    choice,
                )
            )
    return events, await handle.result()


@pytest.mark.asyncio
async def test_full_access_skips_builtin_guard_through_formal_application(
    tmp_path: Path,
) -> None:
    provider = _ScriptedProvider(
        (
            (
                _completed(
                    ToolCallPart("ordinary", "Bash", {"command": "cat .env"}),
                    finish_reason=FinishReason.TOOL_CALLS,
                ),
            ),
            (_completed(TextPart("done"), finish_reason=FinishReason.STOP),),
        )
    )
    tool = _SafeBash(tmp_path)
    run = _application(tmp_path, provider, tool).create_run()
    run.set_permission_mode(PermissionMode.FULL_ACCESS)

    events, _ = await _run(run.start_turn("inspect"))

    assert not any(isinstance(event, TurnPaused) for event in events)
    assert tool.preflight_count == tool.execute_count == 1
    assert _latest_tool_message(provider.requests[1]).parts[0].tool_call_id == "ordinary"


@pytest.mark.asyncio
async def test_auto_runs_static_cd_d_and_cmd_read_group_without_pause(
    tmp_path: Path,
) -> None:
    child = tmp_path / "child"
    child.mkdir()
    provider = _ScriptedProvider(
        (
            (
                _completed(
                    ToolCallPart(
                        "navigation",
                        "Bash",
                        {"command": f'cd /d "{child}" && git status'},
                    ),
                    ToolCallPart(
                        "group",
                        "Bash",
                        {"command": "(git status && echo clean) | findstr clean"},
                    ),
                    finish_reason=FinishReason.TOOL_CALLS,
                ),
            ),
            (_completed(TextPart("done"), finish_reason=FinishReason.STOP),),
        )
    )
    tool = _SafeBash(tmp_path)
    run = _application(tmp_path, provider, tool).create_run()
    run.set_permission_mode(PermissionMode.AUTO)

    events, _ = await _run(run.start_turn("inspect workspace"))

    assert not any(isinstance(event, TurnPaused) for event in events)
    assert tool.preflight_count == tool.execute_count == 2
    result_ids = {
        part.tool_call_id
        for part in _latest_tool_message(provider.requests[1]).parts
    }
    assert result_ids == {"navigation", "group"}


@pytest.mark.asyncio
async def test_full_access_rejects_nested_circuit_breakers_before_execute(
    tmp_path: Path,
) -> None:
    commands = (
        'bash -c "rm -rf /"',
        'bash -c "sh -c \'rm -rf /\'"',
        "sh -c 'rm -rf ~'",
        'cmd /c "rd /s /q C:\\\\"',
        'powershell -Command "Remove-Item -Recurse -Force $env:USERPROFILE"',
        "echo $(rm -rf /)",
        "echo clean | diskpart",
    )
    calls = tuple(
        ToolCallPart(f"nested-{index}", "Bash", {"command": command})
        for index, command in enumerate(commands)
    )
    provider = _ScriptedProvider(
        (
            (_completed(*calls, finish_reason=FinishReason.TOOL_CALLS),),
            (_completed(TextPart("closed"), finish_reason=FinishReason.STOP),),
        )
    )
    tool = _SafeBash(tmp_path)
    run = _application(tmp_path, provider, tool).create_run()
    run.set_permission_mode(PermissionMode.FULL_ACCESS)

    events, _ = await _run(
        run.start_turn("nested danger"), PermissionApprovalChoice.REJECT
    )

    pauses = [event for event in events if isinstance(event, TurnPaused)]
    assert len(pauses) == len(commands)
    assert all(
        event.pause.permission_request is not None
        and event.pause.permission_request.choices
        == (PermissionApprovalChoice.ONCE, PermissionApprovalChoice.REJECT)
        for event in pauses
    )
    assert tool.preflight_count == len(commands)
    assert tool.execute_count == 0
    result_ids = {
        part.tool_call_id
        for part in _latest_tool_message(provider.requests[1]).parts
    }
    assert result_ids == {f"nested-{index}" for index in range(len(commands))}


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", list(PermissionMode))
async def test_circuit_breaker_rejects_before_execute_in_every_mode(
    tmp_path: Path, mode: PermissionMode
) -> None:
    provider = _ScriptedProvider(
        (
            (
                _completed(
                    ToolCallPart("breaker", "Bash", {"command": "rm -rf /"}),
                    finish_reason=FinishReason.TOOL_CALLS,
                ),
            ),
            (_completed(TextPart("closed"), finish_reason=FinishReason.STOP),),
        )
    )
    tool = _SafeBash(tmp_path)
    run = _application(tmp_path, provider, tool).create_run()
    run.set_permission_mode(mode)

    events, _ = await _run(
        run.start_turn("danger"), PermissionApprovalChoice.REJECT
    )

    pause = next(event for event in events if isinstance(event, TurnPaused))
    request = pause.pause.permission_request
    assert request is not None
    assert request.choices == (
        PermissionApprovalChoice.ONCE,
        PermissionApprovalChoice.REJECT,
    )
    assert tool.preflight_count == 1
    assert tool.execute_count == 0
    finished = next(event for event in events if isinstance(event, ToolFinished))
    assert finished.tool_call_id == "breaker"
    assert _latest_tool_message(provider.requests[1]).parts[0].tool_call_id == "breaker"


@pytest.mark.asyncio
async def test_configured_guard_still_asks_in_full_access(tmp_path: Path) -> None:
    permission_file = tmp_path / ".uthcode" / "permissions.toml"
    permission_file.parent.mkdir()
    permission_file.write_text(
        '''[guard]
[[guard.rules]]
id = "explicit-bash"
decision = "ask"
tool = "Bash"
action = "execute"

[policy]
''',
        encoding="utf-8",
    )
    provider = _ScriptedProvider(
        (
            (
                _completed(
                    ToolCallPart("explicit", "Bash", {"command": "git status"}),
                    finish_reason=FinishReason.TOOL_CALLS,
                ),
            ),
            (_completed(TextPart("closed"), finish_reason=FinishReason.STOP),),
        )
    )
    tool = _SafeBash(tmp_path)
    run = _application(tmp_path, provider, tool).create_run()
    run.set_permission_mode(PermissionMode.FULL_ACCESS)

    events, _ = await _run(
        run.start_turn("explicit"), PermissionApprovalChoice.REJECT
    )

    pause = next(event for event in events if isinstance(event, TurnPaused))
    request = pause.pause.permission_request
    assert request is not None
    assert request.guard is True
    assert request.choices == (
        PermissionApprovalChoice.ONCE,
        PermissionApprovalChoice.REJECT,
    )
    assert tool.execute_count == 0
