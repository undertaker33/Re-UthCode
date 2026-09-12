from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import pytest

from uthcode.core.agent import AgentLoop, RunState, RunStatus, TerminationReason
from uthcode.core.agent_events import ToolProgress, agent_event_from_dict
from uthcode.core.provider import (
    CancellationToken,
    FinishReason,
    FilePart,
    GenerationRequest,
    ImagePart,
    Message,
    MessageInput,
    ProviderIdentity,
    ProviderResponse,
    SourcePart,
    TextPart,
    ToolCallPart,
    ToolResultPart,
    GenerationCompleted,
    Usage,
)
from uthcode.core.permission import PermissionMode, PermissionEvaluator
from uthcode.core.tool import (
    Tool,
    ToolExecutor,
    ToolRegistry,
    ToolDefinition,
    ToolExecutionResult,
    ToolFailure,
    ToolFailureKind,
    ToolProgress as CoreToolProgress,
    ToolSideEffect,
)
from uthcode.integrations.providers.anthropic import _request_messages as anthropic_messages
from uthcode.integrations.providers.openai_compat import _request_messages as compat_messages
from uthcode.integrations.providers.openai_responses import _request_input as responses_input


def _request(message: Message) -> GenerationRequest:
    return GenerationRequest(messages=(message,))


def _response(*parts: object, finish_reason: FinishReason = FinishReason.STOP) -> GenerationCompleted:
    return GenerationCompleted(
        ProviderResponse(
            message=Message("assistant", tuple(parts)),
            usage=Usage(),
            finish_reason=finish_reason,
        )
    )


class _ScriptedProvider:
    identity = ProviderIdentity("fake", "script", "model")

    def __init__(self, response: GenerationCompleted) -> None:
        self.response = response
        self.requests: list[GenerationRequest] = []

    async def stream(self, request: GenerationRequest, *, cancellation: CancellationToken):
        self.requests.append(request)
        cancellation.raise_if_cancelled()
        yield self.response


@dataclass
class _RaisingTool:
    calls: list[str] = field(default_factory=list)

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            "first",
            parameters={
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
                "additionalProperties": False,
            },
        )

    async def execute(self, arguments, *, cancellation: CancellationToken) -> ToolExecutionResult:
        del cancellation
        self.calls.append(str(arguments["value"]))
        raise RuntimeError("execution state is unknown")


@dataclass
class _SecondTool:
    calls: list[str] = field(default_factory=list)

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            "second",
            parameters={
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
                "additionalProperties": False,
            },
        )

    async def execute(self, arguments, *, cancellation: CancellationToken) -> ToolExecutionResult:
        del cancellation
        self.calls.append(str(arguments["value"]))
        return ToolExecutionResult("unexpected")


@pytest.mark.asyncio
async def test_unknown_side_effect_closes_remaining_fifo_calls() -> None:
    first = _RaisingTool()
    second = _SecondTool()
    provider = _ScriptedProvider(
        _response(
            ToolCallPart("call-1", "first", {"value": "one"}),
            ToolCallPart("call-2", "second", {"value": "two"}),
            finish_reason=FinishReason.TOOL_CALLS,
        )
    )
    registry = ToolRegistry((first, second))
    evaluator = PermissionEvaluator()
    loop = AgentLoop(
        provider,
        registry,
        ToolExecutor(registry),
        lambda messages, definitions, _context: GenerationRequest(
            messages=messages,
            tools=definitions,
        ),
        permission_resolver=lambda action: evaluator.evaluate(action, mode=PermissionMode.FULL_ACCESS),
    )
    execution = loop.start_turn(RunState.initial("run-unknown"), "run", turn_id="turn-unknown")
    segment = await execution.run_segment(pause_signal=CancellationToken())

    assert segment.terminal
    assert segment.result is not None
    assert segment.result.status is RunStatus.FAILED
    assert segment.result.termination_reason is TerminationReason.SIDE_EFFECT_UNKNOWN
    assert first.calls == ["one"]
    assert second.calls == []
    tool_message = segment.state.messages[-1]
    assert tool_message.role == "tool"
    assert len(tool_message.parts) == 2
    assert isinstance(tool_message.parts[1], ToolResultPart)
    assert tool_message.parts[1].metadata["failure"]["kind"] == "not_executed"


def test_content_parts_and_formal_input_round_trip() -> None:
    image = ImagePart("asset://image-1", "image/png", 640, 480)
    message = Message(
        "user",
        (
            TextPart("inspect"),
            image,
            FilePart("asset://file-1", "report.pdf", "application/pdf", 12),
            SourcePart("asset://file-1", page=2),
        ),
    )
    assert Message.from_dict(message.to_dict()) == message

    tool_result = ToolResultPart("call-1", (TextPart("done"), image))
    restored = ToolResultPart.from_dict(tool_result.to_dict()) if hasattr(ToolResultPart, "from_dict") else ToolResultPart(
        "call-1",
        tuple(
            TextPart(item["text"]) if item["type"] == "text" else image
            for item in tool_result.to_dict()["content"]
        ),
    )
    assert restored.to_dict() == tool_result.to_dict()

    text_input = MessageInput.from_text("same formal value")
    assert text_input.to_message() == Message("user", (TextPart("same formal value"),))


def test_tool_failure_side_effect_and_progress_are_structured() -> None:
    progress = CoreToolProgress("copy", "copied 1 file", current=1, total=2, stream="status")
    result = ToolExecutionResult(
        "partial",
        True,
        ToolFailure(ToolFailureKind.PROCESS_FAILED.value, retryable=True),
        ToolSideEffect.PARTIAL,
        resource="workspace/file.txt",
        process_id="proc-1",
        progress=(progress,),
    )
    assert result.content == "partial"
    assert result.failure is not None and result.failure.retryable is True
    assert result.side_effect is ToolSideEffect.PARTIAL
    assert result.progress == (progress,)

    event = ToolProgress("run-1", "turn-1", 1, "batch-1", "call-1", "Bash", "copy", "safe output")
    restored = agent_event_from_dict(event.to_dict())
    assert restored == event


def test_three_provider_adapters_project_images_and_tool_identity() -> None:
    identity = ProviderIdentity("anthropic", "messages", "model")
    image = ImagePart("https://example.test/image.png", "image/png")
    user = Message("user", (TextPart("look"), image))
    tool = Message("tool", (ToolResultPart("call-1", (TextPart("result"), image)),))

    anthropic = anthropic_messages(_request(user), identity)
    assert anthropic[0]["content"] == [
        {"type": "text", "text": "look"},
        {"type": "image", "source": {"type": "url", "url": image.asset_ref}},
    ]
    anthropic_tool = anthropic_messages(_request(tool), identity)[0]["content"][0]
    assert anthropic_tool["tool_use_id"] == "call-1"
    assert anthropic_tool["content"][1]["type"] == "image"

    responses = responses_input(_request(user), ProviderIdentity("openai", "responses", "model"))
    assert responses[0]["content"][1] == {
        "type": "input_image",
        "image_url": image.asset_ref,
        "detail": "auto",
    }
    response_tool = responses_input(_request(tool), ProviderIdentity("openai", "responses", "model"))[0]
    assert response_tool["call_id"] == "call-1"
    assert response_tool["output"][1]["type"] == "input_image"

    compatible = compat_messages(_request(user), ProviderIdentity("openai-compatible", "chat", "model"))
    assert compatible[0]["content"][1]["type"] == "image_url"
    compatible_tool = compat_messages(_request(tool), ProviderIdentity("openai-compatible", "chat", "model"))
    assert compatible_tool[0]["role"] == "tool"
    assert compatible_tool[0]["tool_call_id"] == "call-1"
    assert compatible_tool[1]["role"] == "user"
    assert compatible_tool[1]["content"][1]["image_url"]["url"] == image.asset_ref
