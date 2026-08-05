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
from uthcode.core.provider import (
    FinishReason,
    ProviderEvent,
    ProviderIdentity,
    ToolCallCompleted,
    Usage,
)
from uthcode.core.tool import ToolExecutionResult
from uthcode.integrations.providers.fake import FakeProvider


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

    _ = [event async for event in application.stream_generation(_request())]
    assert provider.recorded_requests[0].tools == ()


@pytest.mark.asyncio
async def test_default_file_tools_share_state_but_applications_are_isolated(tmp_path) -> None:
    note = tmp_path / "note.txt"
    note.write_text("before\n", encoding="utf-8")
    context = _context(tmp_path)
    first = create_application(_configuration(), runtime_context=context)
    second = create_application(_configuration(), runtime_context=_context(tmp_path))

    read = await first.execute_tool_calls(
        (ToolCallPart("read-1", "ReadFile", {"path": "note.txt"}),)
    )
    assert read == (ToolResultPart("read-1", "1\tbefore"),)

    isolated_write = await second.execute_tool_calls(
        (
            ToolCallPart(
                "write-1",
                "WriteFile",
                {"path": "note.txt", "content": "wrong\n"},
            ),
        )
    )
    assert isolated_write[0].is_error is True
    assert "has not been read" in isolated_write[0].content
    assert note.read_text(encoding="utf-8") == "before\n"

    shared_edit = await first.execute_tool_calls(
        (
            ToolCallPart(
                "edit-1",
                "EditFile",
                {"path": "note.txt", "old_string": "before", "new_string": "after"},
            ),
        )
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
    results = await application.execute_tool_calls(
        (ToolCallPart("echo-1", "Echo", {"value": "hello"}),)
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
    results = await application.execute_tool_calls((call,))
    assert len(provider.recorded_requests) == 1
    assert results[0].tool_call_id == "provider-call-1"
    assert results[0].content == "1\tfrom the fake workdir"

    assistant_message = Message("assistant", (call,))
    tool_message = Message("tool", (results[0],))
    second_request = _request(
        (Message("user", (TextPart("read the note"),)), assistant_message, tool_message),
        tools=definitions,
    )
    second_events = [
        event async for event in application.stream_generation(second_request)
    ]

    assert isinstance(second_events[-1], GenerationCompleted)
    assert len(provider.recorded_requests) == 2
    assert provider.recorded_requests[1].tools == definitions
    assert provider.recorded_requests[1].messages[-1] == tool_message
    assert provider.recorded_requests[0].system_prompt == provider.recorded_requests[1].system_prompt
    assert application.runtime_context.workdir == tmp_path.resolve()
