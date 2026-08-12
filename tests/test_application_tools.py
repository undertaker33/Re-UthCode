from __future__ import annotations

from collections.abc import AsyncIterator, Iterable

import pytest

from uthcode.application import (
    ApplicationRuntimeContext,
    CancellationToken,
    EffectiveConfig,
    GenerationCompleted,
    GenerationRequest,
    Message,
    ProviderKind,
    ProviderResponse,
    TextPart,
    ToolCallPart,
    ToolDefinition,
    ToolResultPart,
    UthCodeApplication,
    create_application,
)
from uthcode.application.tools import ApplicationToolService
from uthcode.core.provider import (
    FinishReason,
    ProviderEvent,
    ProviderIdentity,
    ToolCallCompleted,
    Usage,
)
from uthcode.core.permission import Decision, PermissionEvaluator, PermissionMode
from uthcode.core.tool import (
    PreparedToolCall,
    ToolExecutionResult,
    ToolExecutor,
    ToolRegistry,
)
from uthcode.core.interaction import ASK_USER_TOOL_DEFINITION
from uthcode.core.planning import TODO_WRITE_TOOL_DEFINITION
from uthcode.integrations.providers.fake import FakeProvider
from uthcode.integrations.tools.factory import create_default_tools


def _configuration() -> EffectiveConfig:
    return EffectiveConfig.single_model(
        "test/ref",
        provider_profile_id="test",
        provider_kind=ProviderKind.FAKE,
        remote_model_id="test-model",
    )


def _context(workdir) -> ApplicationRuntimeContext:
    return ApplicationRuntimeContext.from_system(
        workdir=workdir,
        platform_name="TestOS",
        platform_release="1.0",
        current_date="2026-08-06",
    )


def _completed(text: str = "done") -> GenerationCompleted:
    return GenerationCompleted(
        ProviderResponse(
            message=Message("assistant", (TextPart(text),)),
            usage=Usage(input_tokens=1, output_tokens=1),
            finish_reason=FinishReason.STOP,
        )
    )


def _request(
    messages: tuple[Message, ...] | None = None,
    *,
    tools: tuple[ToolDefinition, ...] = (),
) -> GenerationRequest:
    return GenerationRequest(
        messages=messages
        or (Message("user", (TextPart("read the note"),)),),
        tools=tools,
    )


async def _execute_prepared_calls(
    executor: ToolExecutor,
    calls: tuple[ToolCallPart, ...],
    *,
    cancellation: CancellationToken,
) -> tuple[ToolResultPart, ...]:
    evaluator = PermissionEvaluator()
    results: list[ToolResultPart] = []
    for call in calls:
        prepared = executor.prepare_call(call, cancellation=cancellation)
        if isinstance(prepared, ToolResultPart):
            results.append(prepared)
            continue
        assert isinstance(prepared, PreparedToolCall)
        decision = evaluator.evaluate(
            prepared.action,
            mode=PermissionMode.FULL_ACCESS,
        )
        assert decision.decision is Decision.ALLOW
        results.append(
            await executor.execute_prepared(
                prepared,
                cancellation=cancellation,
            )
        )
    return tuple(results)


class _TwoTurnFakeProvider(FakeProvider):
    """A FakeProvider fixture with a tool call on turn one and a final turn."""

    def __init__(self, scripts: Iterable[Iterable[ProviderEvent]]) -> None:
        super().__init__(
            identity=ProviderIdentity("fake", "script", "fake-model"),
            events=(),
        )
        self._scripts = tuple(tuple(script) for script in scripts)

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


@pytest.mark.asyncio
async def test_default_tools_are_ordered_and_not_injected_into_generation() -> None:
    provider = FakeProvider(events=(_completed(),))
    application = create_application(
        _configuration(),
        provider_builder=lambda _provider, _model: provider,
    )

    definitions = application.tool_definitions()
    assert isinstance(definitions, tuple)
    assert [definition.name for definition in definitions] == [
        "ReadFile",
        "WriteFile",
        "EditFile",
        "Glob",
        "Grep",
        "Bash",
    ]
    assert all(
        "effect" not in definition.parameters
        and "permission" not in definition.parameters
        for definition in definitions
    )

    _ = [event async for event in application.stream_generation(_request())]
    assert provider.recorded_requests[0].tools == ()


@pytest.mark.asyncio
async def test_default_file_tools_share_state_but_applications_are_isolated(tmp_path) -> None:
    note = tmp_path / "note.txt"
    note.write_text("before\n", encoding="utf-8")
    context = _context(tmp_path)
    first = create_application(_configuration(), runtime_context=context)
    second = create_application(_configuration(), runtime_context=_context(tmp_path))
    first_tools = ToolExecutor(ToolRegistry(create_default_tools(tmp_path)))
    second_tools = ToolExecutor(ToolRegistry(create_default_tools(tmp_path)))

    read = await _execute_prepared_calls(
        first_tools,
        (ToolCallPart("read-1", "ReadFile", {"path": "note.txt"}),),
        cancellation=CancellationToken(),
    )
    assert read == (ToolResultPart("read-1", "1\tbefore"),)

    isolated_write = await _execute_prepared_calls(
        second_tools,
        (
            ToolCallPart(
                "write-1",
                "WriteFile",
                {"path": "note.txt", "content": "wrong\n"},
            ),
        ),
        cancellation=CancellationToken(),
    )
    assert isolated_write[0].is_error is True
    assert "has not been read" in isolated_write[0].content
    assert note.read_text(encoding="utf-8") == "before\n"

    shared_edit = await _execute_prepared_calls(
        first_tools,
        (
            ToolCallPart(
                "edit-1",
                "EditFile",
                {"path": "note.txt", "old_string": "before", "new_string": "after"},
            ),
        ),
        cancellation=CancellationToken(),
    )
    assert shared_edit[0].is_error is False
    assert note.read_text(encoding="utf-8") == "after\n"
    assert first.runtime_context.workdir == tmp_path.resolve()


class _EchoTool:
    definition = ToolDefinition(
        "Echo",
        "Echo one value.",
        {
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
            "additionalProperties": False,
        },
    )

    def __init__(self) -> None:
        self.arguments: list[dict[str, object]] = []

    async def execute(self, arguments, *, cancellation) -> ToolExecutionResult:
        cancellation.raise_if_cancelled()
        self.arguments.append(dict(arguments))
        return ToolExecutionResult(str(arguments["value"]))


@pytest.mark.asyncio
async def test_explicit_tools_replace_defaults_and_use_application_core_results() -> None:
    fake_tool = _EchoTool()
    application = create_application(_configuration(), tools=(fake_tool,))

    assert [definition.name for definition in application.tool_definitions()] == ["Echo"]
    service = ToolExecutor(ToolRegistry((fake_tool,)))
    results = await _execute_prepared_calls(
        service,
        (ToolCallPart("echo-1", "Echo", {"value": "hello"}),),
        cancellation=CancellationToken(),
    )

    assert results == (ToolResultPart("echo-1", "hello"),)
    assert fake_tool.arguments == [{"value": "hello"}]


@pytest.mark.asyncio
async def test_headless_fake_provider_manual_tool_round_trip_uses_same_context(tmp_path) -> None:
    note = tmp_path / "round-trip.txt"
    note.write_text("from the fake workdir\n", encoding="utf-8")
    call_event = ToolCallCompleted(
        "provider-call-1",
        "ReadFile",
        {"path": "round-trip.txt"},
    )
    provider = _TwoTurnFakeProvider(
        ((call_event, _completed("tool call")), (_completed("final answer"),))
    )
    application = create_application(
        _configuration(),
        provider_builder=lambda _provider, _model: provider,
        runtime_context=_context(tmp_path),
    )
    definitions = application.tool_definitions()

    first_request = _request(tools=definitions)
    first_events = [
        event async for event in application.stream_generation(first_request)
    ]
    assert len(provider.recorded_requests) == 1
    assert provider.recorded_requests[0].tools == definitions

    observed_call = next(
        event for event in first_events if isinstance(event, ToolCallCompleted)
    )
    call = ToolCallPart(
        observed_call.tool_call_id,
        observed_call.name,
        observed_call.arguments,
    )
    with pytest.raises(ValueError, match="manual Tool execution is disabled"):
        await application.execute_tool_calls((call,))
    assert len(provider.recorded_requests) == 1
    assert application.runtime_context.workdir == tmp_path.resolve()


@pytest.mark.parametrize(
    "definition",
    (ASK_USER_TOOL_DEFINITION, TODO_WRITE_TOOL_DEFINITION),
)
def test_application_rejects_reserved_control_tool_from_normal_registry(
    definition: ToolDefinition,
) -> None:
    class ReservedTool:
        @property
        def definition(self) -> ToolDefinition:
            return definition

        async def execute(self, arguments, *, cancellation):
            del arguments, cancellation
            return ToolExecutionResult("must not execute")

    with pytest.raises(ValueError, match="reserved"):
        create_application(_configuration(), tools=(ReservedTool(),))


@pytest.mark.parametrize(
    "assignment",
    [
        "KEY", "MY_KEY", "SSH_KEY", "PUBLIC-KEY", "MY_AUTH", "AUTH_TOKEN",
        "API_KEY", "MY_TOKEN", "CLIENT_SECRET", "DB_PASSWORD", "MY_CREDENTIAL",
    ],
)
def test_application_bash_summary_redacts_sensitive_assignments(
    tmp_path, assignment: str
) -> None:
    secret = "application-secret-918273"
    summary = ApplicationToolService(
        create_default_tools(tmp_path), workdir=tmp_path
    ).describe_tool_call(
        ToolCallPart("bash", "Bash", {"command": f'$env:{assignment}="{secret}"'})
    )
    assert secret not in summary
    assert "<redacted>" in summary


@pytest.mark.parametrize(
    "assignment", ["MONKEY", "KEYNOTE", "HOCKEY_SCORE", "KEYBOARD_LAYOUT", "AUTHORS"]
)
def test_application_bash_summary_keeps_non_secret_name_fragments(
    tmp_path, assignment: str
) -> None:
    value = "z9Q8v7P6n5M4"
    summary = ApplicationToolService(
        create_default_tools(tmp_path), workdir=tmp_path
    ).describe_tool_call(
        ToolCallPart("bash", "Bash", {"command": f'$env:{assignment}="{value}"'})
    )
    assert value in summary
    assert "<redacted>" not in summary


@pytest.mark.asyncio
async def test_manual_tool_api_rejects_application_control_tool() -> None:
    application = create_application(_configuration())
    with pytest.raises(ValueError, match="manual Tool execution"):
        await application.execute_tool_calls(
            (ToolCallPart("ask-1", ASK_USER_TOOL_DEFINITION.name, {"questions": []}),)
        )
