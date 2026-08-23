from __future__ import annotations

from collections.abc import AsyncIterator, Iterable

import pytest

from uthcode.application import ApplicationRuntimeContext, EffectiveConfig, ProviderKind, create_application
from uthcode.application.tools import ApplicationToolService
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
    TextPart,
    ToolCallPart,
    ToolDefinition,
    Usage,
)
from uthcode.core.permission import PermissionMode
from uthcode.core.tool import ToolExecutionResult
from uthcode.integrations.tools.factory import create_default_tools


TEST_LIMITS = ModelLimits(max_input_tokens=1_000_000, source="test.fake")


def _configuration() -> EffectiveConfig:
    return EffectiveConfig.single_model(
        "test/ref",
        provider_profile_id="test",
        provider_kind=ProviderKind.FAKE,
        remote_id="test-model",
        context_window=1_000_000,
    )


def _completed(*parts: TextPart | ToolCallPart, finish_reason: FinishReason = FinishReason.STOP) -> GenerationCompleted:
    return GenerationCompleted(
        ProviderResponse(
            message=Message("assistant", parts),
            usage=Usage(input_tokens=1, output_tokens=1),
            finish_reason=finish_reason,
        )
    )


class _ScriptedProvider:
    identity = ProviderIdentity("fake", "script", "test-model")

    def __init__(self, scripts: Iterable[Iterable[ProviderEvent]]) -> None:
        self._scripts = tuple(tuple(script) for script in scripts)
        self.requests: list[GenerationRequest] = []

    def resolve_model_limits(self, _model: str) -> ModelLimits:
        return TEST_LIMITS

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

    async def execute(self, arguments, *, cancellation) -> ToolExecutionResult:  # type: ignore[no-untyped-def]
        cancellation.raise_if_cancelled()
        self.arguments.append(dict(arguments))
        return ToolExecutionResult(str(arguments["value"]))


@pytest.mark.asyncio
async def test_application_tools_are_exposed_and_execute_only_inside_a_turn(tmp_path) -> None:  # type: ignore[no-untyped-def]
    tool = _EchoTool()
    provider = _ScriptedProvider(
        (
            (_completed(ToolCallPart("echo-1", "Echo", {"value": "hello"}), finish_reason=FinishReason.TOOL_CALLS),),
            (_completed(TextPart("done")),),
        )
    )
    application = create_application(
        _configuration(),
        provider_builder=lambda _provider, _model: provider,
        runtime_context=ApplicationRuntimeContext.from_system(workdir=tmp_path),
        storage_root=tmp_path / "sessions",
        tools=(tool,),
    )

    run = application.create_run()
    run.set_permission_mode(PermissionMode.FULL_ACCESS)
    result = await run.start_turn("echo hello").result()

    assert result.final_text == "done"
    assert tool.arguments == [{"value": "hello"}]
    assert [definition.name for definition in application.tool_definitions()] == [
        "Echo",
        "ToolResultRead",
        "HistoryRead",
    ]
    assert [definition.name for definition in provider.requests[0].tools][:1] == ["Echo"]


@pytest.mark.parametrize("assignment", ("API_KEY", "AUTH_TOKEN", "CLIENT_SECRET"))
def test_application_tool_summary_redacts_sensitive_assignments(tmp_path, assignment: str) -> None:  # type: ignore[no-untyped-def]
    secret = "application-secret-918273"
    summary = ApplicationToolService(
        create_default_tools(tmp_path),
        workdir=tmp_path,
    ).describe_tool_call(
        ToolCallPart("bash", "Bash", {"command": f'$env:{assignment}="{secret}"'})
    )

    assert secret not in summary
    assert "<redacted>" in summary
