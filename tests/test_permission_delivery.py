from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable, Iterable
from pathlib import Path

import pytest

from uthcode.application import (
    ApplicationRuntimeContext,
    EffectiveConfig,
    PermissionApprovalChoice,
    PermissionApprovalResponse,
    PermissionMode,
    ProviderKind,
    UthCodeApplication,
    create_application,
)
from uthcode.core.agent import AgentLoop, AgentTurnExecution, RunState, RunStatus
from uthcode.core.agent_events import ToolFinished, ToolStarted, TurnPaused, TurnResumed
from uthcode.core.permission import (
    Decision,
    Effect,
    PermissionAction,
    PermissionEvaluator,
    ResourceScope,
    RuleSet,
    SessionGrant,
)
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
    ToolCallCompleted,
    ToolCallPart,
    ToolDefinition,
    Usage,
)
from uthcode.core.tool import PreparedToolCall, ToolExecutionResult, ToolPreparation, ToolExecutor, ToolRegistry
from uthcode.integrations.permissions import (
    PermissionConfigurationError,
    default_guard_rules,
)
from uthcode.integrations.tools.factory import create_default_tools
from uthcode.integrations.tools.process_tools import BashTool


def _configuration() -> EffectiveConfig:
    return EffectiveConfig.single_model(
        "w04/ref",
        provider_profile_id="w04",
        provider_kind=ProviderKind.FAKE,
        remote_id="w04-model",
    )


def _context(workdir: Path) -> ApplicationRuntimeContext:
    return ApplicationRuntimeContext.from_system(
        workdir=workdir,
        platform_name="TestOS",
        platform_release="w04",
        current_date="2026-08-08",
    )


def _completed(*parts: object, finish_reason: FinishReason) -> GenerationCompleted:
    return GenerationCompleted(
        ProviderResponse(
            message=Message("assistant", tuple(parts)),
            usage=Usage(),
            finish_reason=finish_reason,
        )
    )


class _ScriptedProvider:
    identity = ProviderIdentity("fake", "w04-script", "w04-model")

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
        index = min(len(self.requests) - 1, len(self._scripts) - 1)
        for event in self._scripts[index]:
            cancellation.raise_if_cancelled()
            yield event


class _CountingTool:
    def __init__(self, wrapped: object) -> None:
        self._wrapped = wrapped
        self.preflight_count = 0
        self.execute_count = 0

    @property
    def definition(self) -> ToolDefinition:
        return self._wrapped.definition  # type: ignore[attr-defined]

    def preflight(self, arguments):  # type: ignore[no-untyped-def]
        self.preflight_count += 1
        return self._wrapped.preflight(arguments)  # type: ignore[attr-defined]

    async def execute(self, arguments, *, cancellation):  # type: ignore[no-untyped-def]
        self.execute_count += 1
        return await self._wrapped.execute(  # type: ignore[attr-defined]
            arguments,
            cancellation=cancellation,
        )


class _VirtualOutsideWriteTool:
    """A no-side-effect WriteFile-shaped tool for physical grant tests."""

    definition = ToolDefinition(
        "WriteFile",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
            "additionalProperties": False,
        },
    )

    def __init__(self) -> None:
        self.execute_count = 0

    def preflight(self, arguments):  # type: ignore[no-untyped-def]
        return ToolPreparation(
            PermissionAction(
                "WriteFile",
                "write",
                Effect.WRITE,
                arguments["path"],
                ResourceScope.OUTSIDE,
            ),
            arguments,
        )

    async def execute(self, arguments, *, cancellation):  # type: ignore[no-untyped-def]
        del arguments, cancellation
        self.execute_count += 1
        return ToolExecutionResult("virtual write")


class _ResourceLessTool:
    definition = ToolDefinition(
        "Custom",
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
    )

    def __init__(self) -> None:
        self.execute_count = 0

    async def execute(self, arguments, *, cancellation):  # type: ignore[no-untyped-def]
        del arguments, cancellation
        self.execute_count += 1
        return ToolExecutionResult("custom")


@pytest.mark.asyncio
async def test_formal_resourceless_tool_never_offers_session(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    provider = _ScriptedProvider(
        (
            (_completed(ToolCallPart("custom-1", "Custom", {}), finish_reason=FinishReason.TOOL_CALLS),),
            (_completed(TextPart("done"), finish_reason=FinishReason.STOP),),
        )
    )
    tool = _ResourceLessTool()
    run = _application(workspace, provider, tools=(tool,)).create_run()
    events = await _collect_turn(
        run.start_turn("custom"), lambda event: PermissionApprovalChoice.ONCE
    )
    pause = next(event for event in events if isinstance(event, TurnPaused))
    request = pause.pause.permission_request
    assert request is not None
    assert request.resource is None
    assert request.choices == (
        PermissionApprovalChoice.ONCE,
        PermissionApprovalChoice.REJECT,
    )
    assert run.session_grants == ()
    assert tool.execute_count == 1


def _application(
    workdir: Path,
    provider: _ScriptedProvider,
    *,
    tools: tuple[object, ...] | None = None,
) -> UthCodeApplication:
    kwargs: dict[str, object] = {
        "provider_builder": lambda _provider, _model: provider,
        "runtime_context": _context(workdir),
    }
    if tools is not None:
        kwargs["tools"] = tools
    return create_application(_configuration(), **kwargs)  # type: ignore[arg-type]


def _permission_response(
    event: TurnPaused,
    choice: PermissionApprovalChoice,
) -> PermissionApprovalResponse:
    request = event.pause.permission_request
    assert request is not None
    return PermissionApprovalResponse(
        event.pause.pause_id,
        event.run_id,
        event.turn_id,
        request.permission_id,
        choice,
    )


async def _collect_turn(
    handle,
    chooser: Callable[[TurnPaused], PermissionApprovalChoice],
) -> list[object]:
    events: list[object] = []
    async for event in handle.events():
        events.append(event)
        if isinstance(event, TurnPaused):
            assert handle.resume(_permission_response(event, chooser(event)))
    return events


def _write_call(call_id: str, path: str, content: str) -> ToolCallPart:
    return ToolCallPart(call_id, "WriteFile", {"path": path, "content": content})


@pytest.mark.asyncio
async def test_formal_run_loads_permission_snapshot_and_executes_prepared_write_once(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    provider = _ScriptedProvider(
        (
            (
                _completed(
                    _write_call("write-1", "created.txt", "W04-safe"),
                    finish_reason=FinishReason.TOOL_CALLS,
                ),
            ),
            (_completed(TextPart("finished"), finish_reason=FinishReason.STOP),),
        )
    )
    tools = list(create_default_tools(workspace))
    write = _CountingTool(tools[1])
    tools[1] = write
    application = _application(workspace, provider, tools=tuple(tools))

    run = application.create_run(run_id="formal-write")
    home_permissions = Path(os.environ["HOME"]) / ".uthcode" / "permissions.toml"
    project_permissions = workspace / ".uthcode" / "permissions.toml"
    assert home_permissions.is_file()
    assert project_permissions.is_file()

    handle = run.start_turn("write one file")
    events = await _collect_turn(
        handle,
        lambda event: PermissionApprovalChoice.ONCE,
    )
    result = await handle.result()

    assert result.status is RunStatus.COMPLETED
    assert (workspace / "created.txt").read_text(encoding="utf-8") == "W04-safe"
    assert write.preflight_count == 1
    assert write.execute_count == 1
    assert sum(isinstance(event, TurnPaused) for event in events) == 1
    pause = next(event for event in events if isinstance(event, TurnPaused))
    request = pause.pause.permission_request
    assert request is not None
    assert request.tool == "WriteFile"
    assert request.choices == (
        PermissionApprovalChoice.ONCE,
        PermissionApprovalChoice.SESSION,
        PermissionApprovalChoice.REJECT,
    )
    assert all("W04-safe" not in event.to_json() for event in events)
    assert events.index(next(event for event in events if isinstance(event, ToolStarted))) < events.index(pause)
    assert events.index(next(event for event in events if isinstance(event, TurnResumed))) > events.index(pause)
    assert events.index(next(event for event in events if isinstance(event, ToolFinished))) > events.index(next(event for event in events if isinstance(event, TurnResumed)))


@pytest.mark.asyncio
async def test_formal_reject_returns_error_and_continues_safe_batch(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "safe.txt").write_text("stable\n", encoding="utf-8")
    provider = _ScriptedProvider(
        (
            (
                _completed(
                    _write_call("write-1", "blocked.txt", "must-not-exist"),
                    ToolCallPart("read-1", "ReadFile", {"path": "safe.txt"}),
                    finish_reason=FinishReason.TOOL_CALLS,
                ),
            ),
            (_completed(TextPart("continued"), finish_reason=FinishReason.STOP),),
        )
    )
    tools = list(create_default_tools(workspace))
    write = _CountingTool(tools[1])
    tools[1] = write
    application = _application(workspace, provider, tools=tuple(tools))

    def choose(event: TurnPaused) -> PermissionApprovalChoice:
        assert event.pause.permission_request is not None
        assert event.pause.permission_request.tool == "WriteFile"
        return PermissionApprovalChoice.REJECT

    events = await _collect_turn(application.create_run().start_turn("reject then read"), choose)
    finished = [event for event in events if isinstance(event, ToolFinished)]

    assert [event.tool_call_id for event in finished] == ["write-1", "read-1"]
    assert [event.is_error for event in finished] == [True, False]
    assert (workspace / "blocked.txt").exists() is False
    assert write.execute_count == 0
    tool_message = provider.requests[1].messages[-1]
    assert [part.content for part in tool_message.parts] == [
        "Error: permission rejected",
        "1\tstable",
    ]


@pytest.mark.asyncio
async def test_formal_outside_write_is_unchanged_until_approval_then_writes_once(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    target = outside / "approved.txt"
    provider = _ScriptedProvider(
        (
            (_completed(_write_call("outside-1", str(target), "outside-safe"), finish_reason=FinishReason.TOOL_CALLS),),
            (_completed(TextPart("done"), finish_reason=FinishReason.STOP),),
        )
    )
    tools = list(create_default_tools(workspace))
    write = _CountingTool(tools[1])
    tools[1] = write
    application = _application(workspace, provider, tools=tuple(tools))
    observed_before_resume = False

    def choose(event: TurnPaused) -> PermissionApprovalChoice:
        nonlocal observed_before_resume
        request = event.pause.permission_request
        assert request is not None
        assert request.scope is ResourceScope.OUTSIDE
        assert request.resource == target.resolve().as_posix()
        assert not target.exists()
        observed_before_resume = True
        return PermissionApprovalChoice.ONCE

    events = await _collect_turn(application.create_run().start_turn("outside write"), choose)

    assert observed_before_resume is True
    assert target.read_text(encoding="utf-8") == "outside-safe"
    assert write.preflight_count == 1
    assert write.execute_count == 1
    assert all("outside-safe" not in event.to_json() for event in events)


@pytest.mark.asyncio
async def test_formal_read_and_grep_sensitive_resources_enter_guard_without_content_leak(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    secret = "W04-SENSITIVE-CONTENT"
    (workspace / ".env").write_text(f"TOKEN={secret}\n", encoding="utf-8")
    provider = _ScriptedProvider(
        (
            (
                _completed(
                    ToolCallPart("read-1", "ReadFile", {"path": ".env"}),
                    ToolCallPart("grep-1", "Grep", {"pattern": secret, "path": "."}),
                    finish_reason=FinishReason.TOOL_CALLS,
                ),
            ),
            (_completed(TextPart("rejected"), finish_reason=FinishReason.STOP),),
        )
    )
    application = _application(workspace, provider)
    seen_tools: list[str] = []

    def choose(event: TurnPaused) -> PermissionApprovalChoice:
        request = event.pause.permission_request
        assert request is not None
        assert request.guard is True
        assert request.choices == (
            PermissionApprovalChoice.ONCE,
            PermissionApprovalChoice.REJECT,
        )
        seen_tools.append(request.tool)
        assert secret not in event.to_json()
        assert ".env" in (request.resource or "")
        return PermissionApprovalChoice.REJECT

    events = await _collect_turn(application.create_run().start_turn("inspect secret"), choose)
    finished = [event for event in events if isinstance(event, ToolFinished)]

    assert seen_tools == ["ReadFile", "Grep"]
    assert [event.is_error for event in finished] == [True, True]
    assert all(secret not in event.to_json() for event in events)
    assert all(secret not in part.content for part in provider.requests[1].messages[-1].parts)


@pytest.mark.asyncio
async def test_formal_mode_matrix_and_session_grant_stay_on_the_same_evaluator(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    provider = _ScriptedProvider(
        (
            (_completed(_write_call("write-1", "session.txt", "one"), finish_reason=FinishReason.TOOL_CALLS),),
            (_completed(TextPart("first"), finish_reason=FinishReason.STOP),),
            (_completed(_write_call("write-2", "session.txt", "two"), finish_reason=FinishReason.TOOL_CALLS),),
            (_completed(TextPart("second"), finish_reason=FinishReason.STOP),),
        )
    )
    tools = list(create_default_tools(workspace))
    write = _CountingTool(tools[1])
    tools[1] = write
    application = _application(workspace, provider, tools=tuple(tools))
    run = application.create_run()

    first_events = await _collect_turn(
        run.start_turn("first session write"),
        lambda event: PermissionApprovalChoice.SESSION,
    )
    second_events = await _collect_turn(
        run.start_turn("second session write"),
        lambda event: PermissionApprovalChoice.ONCE,
    )

    assert sum(isinstance(event, TurnPaused) for event in first_events) == 1
    assert sum(isinstance(event, TurnPaused) for event in second_events) == 0
    assert run.session_grants
    assert (workspace / "session.txt").read_text(encoding="utf-8") == "two"
    assert write.preflight_count == 2
    assert write.execute_count == 2

    auto_provider = _ScriptedProvider(
        (
            (_completed(_write_call("auto-1", "auto.txt", "auto"), finish_reason=FinishReason.TOOL_CALLS),),
            (_completed(TextPart("auto"), finish_reason=FinishReason.STOP),),
        )
    )
    auto_application = _application(workspace, auto_provider)
    auto_run = auto_application.create_run()
    assert auto_run.set_permission_mode(PermissionMode.AUTO) is PermissionMode.AUTO
    auto_events = await _collect_turn(auto_run.start_turn("auto write"), lambda event: PermissionApprovalChoice.ONCE)
    assert sum(isinstance(event, TurnPaused) for event in auto_events) == 0
    assert (workspace / "auto.txt").read_text(encoding="utf-8") == "auto"

    guard_provider = _ScriptedProvider(
        (
            (_completed(ToolCallPart("guard-1", "ReadFile", {"path": ".env"}), finish_reason=FinishReason.TOOL_CALLS),),
            (_completed(TextPart("guard"), finish_reason=FinishReason.STOP),),
        )
    )
    (workspace / ".env").write_text("guard-content\n", encoding="utf-8")
    guard_run = _application(workspace, guard_provider).create_run()
    assert guard_run.set_permission_mode(PermissionMode.FULL_ACCESS) is PermissionMode.FULL_ACCESS
    guard_events = await _collect_turn(
        guard_run.start_turn("guarded read"),
        lambda event: PermissionApprovalChoice.REJECT,
    )
    assert sum(isinstance(event, TurnPaused) for event in guard_events) == 0


@pytest.mark.parametrize(
    ("location", "content", "not_exposed"),
    [
        (
            "user",
            "[[guard.rules]\nW04-SENSITIVE-CONTENT",
            "W04-SENSITIVE-CONTENT",
        ),
        (
            "project",
            '[ [guard.rules] ]\n',
            "guard.rules",
        ),
    ],
)
def test_formal_bootstrap_rejects_invalid_permission_sources_redacted(
    tmp_path: Path,
    location: str,
    content: str,
    not_exposed: str,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    if location == "user":
        path = Path(os.environ["HOME"]) / ".uthcode" / "permissions.toml"
    else:
        path = workspace / ".uthcode" / "permissions.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    application = _application(
        workspace,
        _ScriptedProvider(((_completed(TextPart("unused"), finish_reason=FinishReason.STOP),),)),
    )

    with pytest.raises(PermissionConfigurationError) as error:
        application.create_run()

    assert not_exposed not in str(error.value)
    assert "permission" in str(error.value)


class _SearchProbe:
    definition = ToolDefinition(
        "search",
        parameters={
            "type": "object",
            "properties": {"q": {"type": "string"}},
            "required": ["q"],
            "additionalProperties": False,
        },
    )

    def preflight(self, arguments):  # type: ignore[no-untyped-def]
        return ToolPreparation(
            PermissionAction(
                "search",
                "read",
                Effect.READ,
                "provider-parity.txt",
                ResourceScope.INSIDE,
            ),
            arguments,
        )

    async def execute(self, arguments, *, cancellation):  # type: ignore[no-untyped-def]
        del arguments, cancellation
        return ToolExecutionResult("unused")


@pytest.mark.asyncio
async def test_three_provider_adapters_normalize_tool_calls_to_same_action_and_decision() -> None:
    from tests.test_anthropic_integration import _AnthropicClient, _events
    from tests.test_openai_compat_integration import _OpenAICompatClient, _chunks
    from tests.test_openai_responses_integration import _OpenAIClient, _item_events
    from uthcode.integrations.providers.anthropic import build_anthropic_provider
    from uthcode.integrations.providers.openai_compat import build_openai_compat_provider
    from uthcode.integrations.providers.openai_responses import build_openai_responses_provider

    request = GenerationRequest(messages=(Message("user", (TextPart("search"),)),))
    providers = (
        (
            "anthropic",
            build_anthropic_provider("claude-w04", client=_AnthropicClient(_events(include_tool=True))),
        ),
        (
            "openai_compat",
            build_openai_compat_provider(
                "deepseek-w04",
                base_url="https://mock.invalid/v1",
                client=_OpenAICompatClient(_chunks()),
            ),
        ),
        (
            "openai_responses",
            build_openai_responses_provider("gpt-w04", client=_OpenAIClient(_item_events())),
        ),
    )
    observed: list[tuple[str, dict[str, object], dict[str, object]]] = []
    registry = ToolRegistry((_SearchProbe(),))
    executor = ToolExecutor(registry)

    for provider_name, provider in providers:
        events = [
            event
            async for event in provider.stream(
                request,
                cancellation=CancellationToken(),
            )
        ]
        completed = next(event for event in events if isinstance(event, ToolCallCompleted))
        call = ToolCallPart(completed.tool_call_id, completed.name, completed.arguments)
        prepared = executor.prepare_call(call, cancellation=CancellationToken())
        assert isinstance(prepared, PreparedToolCall)
        decision = PermissionEvaluator().evaluate(prepared.action)
        observed.append((provider_name, prepared.action.to_dict(), decision.to_dict()))

    assert [item[0] for item in observed] == [
        "anthropic",
        "openai_compat",
        "openai_responses",
    ]
    assert len({str(item[1]) for item in observed}) == 1
    assert len({str(item[2]) for item in observed}) == 1
    assert all(item[2]["decision"] == Decision.ALLOW.value for item in observed)


@pytest.mark.parametrize(
    ("command", "secrets"),
    [
        ("curl https://alice:s3cr3t@example.com/api", ("s3cr3t",)),
        ("curl -u alice:s3cr3t https://example.com", ("s3cr3t",)),
        ("curl --user alice:s3cr3t https://example.com", ("s3cr3t",)),
        ("curl -ualice:attached-secret https://example.com", ("attached-secret",)),
        (
            'curl -H "Authorization: Bearer header-secret" '
            '-H "Proxy-Authorization: Basic proxy-secret" https://example.com',
            ("header-secret", "proxy-secret"),
        ),
        (
            "curl https://example.com/api?token=query-secret&password=query-pass&api-key=query-key",
            ("query-secret", "query-pass", "query-key"),
        ),
        (
            "wget --user=alice --password=wget-secret https://example.com",
            ("wget-secret",),
        ),
        (
            "curl --user alice --password curl-password https://example.com",
            ("curl-password",),
        ),
        ("curl --oauth2-bearer oauth-secret https://example.com", ("oauth-secret",)),
    ],
)
@pytest.mark.asyncio
async def test_bash_credentials_are_absent_from_formal_permission_events(
    tmp_path: Path,
    command: str,
    secrets: tuple[str, ...],
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    provider = _ScriptedProvider(
        (
            (
                _completed(
                    ToolCallPart("bash-secret-1", "Bash", {"command": command}),
                    finish_reason=FinishReason.TOOL_CALLS,
                ),
            ),
            (_completed(TextPart("rejected"), finish_reason=FinishReason.STOP),),
        )
    )
    application = _application(workspace, provider)

    events = await _collect_turn(
        application.create_run().start_turn("inspect command safely"),
        lambda event: PermissionApprovalChoice.REJECT,
    )
    pause = next(event for event in events if isinstance(event, TurnPaused))
    request = pause.pause.permission_request
    assert request is not None
    payloads = [
        event.to_json()
        for event in events
    ] + [
        request.to_json(),
        pause.pause.to_json(),
        request.to_json(),
    ]
    for secret in secrets:
        assert all(secret not in payload for payload in payloads)


@pytest.mark.parametrize(
    ("command", "expected_guard"),
    [
        ("ls .env", False),
        ("stat .env", False),
        ("Get-Item .env", False),
        ("Get-ChildItem .env", False),
        ("Test-Path .env", False),
        ("ls .env | cat", False),
        ("stat .env | cat", False),
        ("echo .env | cat", False),
        ("Get-Item .env | Out-String", False),
        ("Get-ChildItem .env | Format-List", False),
        ("cat .env", True),
        ("type .env", True),
        ("Get-Content .env", True),
        ("grep TOKEN .env", True),
        ("echo changed > .env", True),
        ("cat < .env", True),
        ("ls .env | cat .env", True),
        ("ls .env && cat .env", True),
        ("Get-Item .env; Get-Content .env", True),
        ("Get-Item .env | Get-Content .env", True),
        ("Get-Item .env | ForEach-Object { Get-Content .env }", True),
        (r"find .env -exec cat {} \;", True),
        (r"ls .env; sh -c 'cat .env'", True),
    ],
)
def test_bash_sensitive_guard_distinguishes_metadata_from_content(
    tmp_path: Path,
    command: str,
    expected_guard: bool,
) -> None:
    tool = BashTool(tmp_path)
    preparation = tool.preflight({"command": command})
    evaluator = PermissionEvaluator(RuleSet(default_guard_rules()))
    ordinary = evaluator.evaluate(preparation.action, mode=PermissionMode.DEFAULT)
    full_access = evaluator.evaluate(
        preparation.action,
        mode=PermissionMode.FULL_ACCESS,
    )
    assert (ordinary.reason.value == "guard_match") is expected_guard
    assert full_access.decision is Decision.ALLOW
    assert full_access.reason.value == "mode_fallback"


@pytest.mark.asyncio
async def test_formal_outside_session_grant_is_directory_bounded_and_dimension_bound(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    neighbor = tmp_path / "outside-neighbor"
    other = tmp_path / "other"
    workspace.mkdir()
    outside.mkdir()
    neighbor.mkdir()
    other.mkdir()
    same_directory_variant = str(outside / "b.txt").replace("/", "\\").upper()
    provider = _ScriptedProvider(
        (
            (_completed(_write_call("outside-a", str(outside / "a.txt"), "a"), finish_reason=FinishReason.TOOL_CALLS),),
            (_completed(TextPart("a done"), finish_reason=FinishReason.STOP),),
            (_completed(_write_call("outside-b", same_directory_variant, "b"), finish_reason=FinishReason.TOOL_CALLS),),
            (_completed(TextPart("b done"), finish_reason=FinishReason.STOP),),
            (_completed(_write_call("neighbor-b", str(neighbor / "b.txt"), "neighbor"), finish_reason=FinishReason.TOOL_CALLS),),
            (_completed(TextPart("neighbor rejected"), finish_reason=FinishReason.STOP),),
            (_completed(_write_call("other-b", str(other / "b.txt"), "other"), finish_reason=FinishReason.TOOL_CALLS),),
            (_completed(TextPart("other rejected"), finish_reason=FinishReason.STOP),),
            (
                _completed(
                    ToolCallPart(
                        "outside-read",
                        "ReadFile",
                        {"path": str(outside / "a.txt")},
                    ),
                    finish_reason=FinishReason.TOOL_CALLS,
                ),
            ),
            (_completed(TextPart("read rejected"), finish_reason=FinishReason.STOP),),
            (
                _completed(
                    ToolCallPart(
                        "outside-edit",
                        "EditFile",
                        {
                            "path": str(outside / "a.txt"),
                            "old_string": "a",
                            "new_string": "edited",
                        },
                    ),
                    finish_reason=FinishReason.TOOL_CALLS,
                ),
            ),
            (_completed(TextPart("edit rejected"), finish_reason=FinishReason.STOP),),
        )
    )
    application = _application(workspace, provider)
    run = application.create_run(run_id="outside-grant")

    first_events = await _collect_turn(
        run.start_turn("approve outside directory"),
        lambda event: PermissionApprovalChoice.SESSION,
    )
    assert sum(isinstance(event, TurnPaused) for event in first_events) == 1
    assert (outside / "a.txt").read_text(encoding="utf-8") == "a"

    grant = run.session_grants[0]
    assert grant.resource == outside.resolve().as_posix()
    assert grant.resource_prefix is True

    def unexpected_pause(event: TurnPaused) -> PermissionApprovalChoice:
        raise AssertionError(f"same-directory target unexpectedly paused: {event}")

    second_events = await _collect_turn(
        run.start_turn("reuse outside directory grant"),
        unexpected_pause,
    )
    assert sum(isinstance(event, TurnPaused) for event in second_events) == 0
    assert (outside / "b.txt").read_text(encoding="utf-8") == "b"

    neighbor_events = await _collect_turn(
        run.start_turn("reject adjacent directory"),
        lambda event: PermissionApprovalChoice.REJECT,
    )
    other_events = await _collect_turn(
        run.start_turn("reject unrelated directory"),
        lambda event: PermissionApprovalChoice.REJECT,
    )
    assert sum(isinstance(event, TurnPaused) for event in neighbor_events) == 1
    assert sum(isinstance(event, TurnPaused) for event in other_events) == 1
    assert not (neighbor / "b.txt").exists()
    assert not (other / "b.txt").exists()

    read_events = await _collect_turn(
        run.start_turn("do not reuse grant for ReadFile"),
        lambda event: PermissionApprovalChoice.REJECT,
    )
    edit_events = await _collect_turn(
        run.start_turn("do not reuse grant for EditFile"),
        lambda event: PermissionApprovalChoice.REJECT,
    )
    assert sum(isinstance(event, TurnPaused) for event in read_events) == 1
    assert sum(isinstance(event, TurnPaused) for event in edit_events) == 1
    assert (outside / "a.txt").read_text(encoding="utf-8") == "a"


@pytest.mark.parametrize(
    ("approved_resource", "same_resource", "blocked_resource"),
    [
        ("/secret.txt", "/secret.txt", "/etc/passwd"),
        ("C:/secret.txt", "c:\\SECRET.TXT", "C:/Windows/System32/config/SAM"),
        (
            "//server/share/secret.txt",
            "//SERVER/SHARE/SECRET.TXT",
            "//server/share/other/private.txt",
        ),
    ],
)
@pytest.mark.asyncio
async def test_formal_root_outside_session_grant_is_exact_file_only(
    tmp_path: Path,
    approved_resource: str,
    same_resource: str,
    blocked_resource: str,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    provider = _ScriptedProvider(
        (
            (
                _completed(
                    _write_call("root-approved", approved_resource, "first"),
                    finish_reason=FinishReason.TOOL_CALLS,
                ),
            ),
            (_completed(TextPart("approved"), finish_reason=FinishReason.STOP),),
            (
                _completed(
                    _write_call("root-same", same_resource, "same"),
                    finish_reason=FinishReason.TOOL_CALLS,
                ),
            ),
            (_completed(TextPart("same"), finish_reason=FinishReason.STOP),),
            (
                _completed(
                    _write_call("root-blocked", blocked_resource, "blocked"),
                    finish_reason=FinishReason.TOOL_CALLS,
                ),
            ),
            (_completed(TextPart("blocked"), finish_reason=FinishReason.STOP),),
        )
    )
    virtual_tool = _VirtualOutsideWriteTool()
    application = _application(workspace, provider, tools=(virtual_tool,))
    run = application.create_run(run_id="root-outside-grant")

    first_events = await _collect_turn(
        run.start_turn("approve root file"),
        lambda event: PermissionApprovalChoice.SESSION,
    )
    assert sum(isinstance(event, TurnPaused) for event in first_events) == 1
    assert len(run.session_grants) == 1
    grant = run.session_grants[0]
    assert grant.resource == approved_resource
    assert grant.resource_prefix is False

    same_events = await _collect_turn(
        run.start_turn("reuse approved root file"),
        lambda event: (_ for _ in ()).throw(
            AssertionError(f"approved root file unexpectedly paused: {event}")
        ),
    )
    blocked_events = await _collect_turn(
        run.start_turn("reject another root file"),
        lambda event: PermissionApprovalChoice.REJECT,
    )

    assert sum(isinstance(event, TurnPaused) for event in same_events) == 0
    assert sum(isinstance(event, TurnPaused) for event in blocked_events) == 1
    assert virtual_tool.execute_count == 2


def test_session_grant_resource_prefix_never_crosses_root_or_dimension_boundaries() -> None:
    for root, other in (
        ("/", "/etc/passwd"),
        ("C:/", "C:/Windows/System32/config/SAM"),
        ("//server/share/", "//server/share/other/private.txt"),
    ):
        root_grant = SessionGrant(
            "WriteFile",
            "write",
            Effect.WRITE,
            root,
            ResourceScope.OUTSIDE,
            resource_prefix=True,
        )
        assert not root_grant.matches(
            PermissionAction("WriteFile", "write", Effect.WRITE, other, ResourceScope.OUTSIDE)
        )

    exact_grant = SessionGrant(
        "WriteFile",
        "write",
        Effect.WRITE,
        "C:/secret.txt",
        ResourceScope.OUTSIDE,
    )
    assert exact_grant.matches(
        PermissionAction(
            "WriteFile",
            "write",
            Effect.WRITE,
            "c:\\SECRET.TXT",
            ResourceScope.OUTSIDE,
        )
    )
    assert not exact_grant.matches(
        PermissionAction(
            "ReadFile",
            "read",
            Effect.READ,
            "c:/secret.txt",
            ResourceScope.OUTSIDE,
        )
    )
    assert not exact_grant.matches(
        PermissionAction(
            "WriteFile",
            "write",
            Effect.WRITE,
            "c:/secret.txt",
            ResourceScope.INSIDE,
        )
    )


def test_agent_turn_execution_has_only_constructor_permission_injection() -> None:
    assert not hasattr(AgentTurnExecution, "configure_permission")


def test_tool_executor_has_no_legacy_direct_batch_execution_entries() -> None:
    assert not hasattr(ToolExecutor, "execute_call")
    assert not hasattr(ToolExecutor, "execute_batch")


def test_agent_loop_hard_fails_before_tool_execution_without_permission_resolver() -> None:
    class OrdinaryTool:
        definition = ToolDefinition(
            "ordinary",
            parameters={
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
                "additionalProperties": False,
            },
        )

        async def execute(self, arguments, *, cancellation):  # type: ignore[no-untyped-def]
            del arguments, cancellation
            raise AssertionError("ordinary tool must not execute without permission")

    provider = _ScriptedProvider(())
    registry = ToolRegistry((OrdinaryTool(),))
    executor = ToolExecutor(registry)
    loop = AgentLoop(
        provider,
        registry,
        executor,
        lambda messages, definitions, _runtime_context: GenerationRequest(
            messages=messages,
            tools=definitions,
        ),
    )
    with pytest.raises(RuntimeError, match="permission"):
        loop.start_turn(RunState.initial("missing-permission"), "run ordinary tool")
