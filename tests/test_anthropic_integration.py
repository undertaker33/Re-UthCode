from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from anthropic.types.beta import (
    BetaRawContentBlockDeltaEvent,
    BetaRawContentBlockStartEvent,
    BetaRawContentBlockStopEvent,
    BetaRawMessageDeltaEvent,
    BetaRawMessageStartEvent,
    BetaRawMessageStopEvent,
)

from uthcode.core.provider import (
    AuthenticationError,
    CancellationToken,
    GenerationCancelled,
    GenerationCompleted,
    GenerationRequest,
    InvalidProviderResponseError,
    Message,
    NativeItemCompleted,
    NetworkError,
    ProviderIdentity,
    RateLimitError,
    ReasoningPart,
    TextDelta,
    TextPart,
    ToolCallPart,
    ToolCallCompleted,
    ToolDefinition,
    ToolResultPart,
)
from uthcode.integrations.providers.anthropic import AnthropicCodec, build_anthropic_provider


class _AsyncStream:
    def __init__(self, events: list[Any], *, delay: float = 0) -> None:
        self._events = iter(events)
        self.delay = delay
        self.closed = False

    async def __aenter__(self) -> _AsyncStream:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    def __aiter__(self) -> _AsyncStream:
        return self

    async def __anext__(self) -> Any:
        if self.delay:
            await asyncio.sleep(self.delay)
        try:
            return next(self._events)
        except StopIteration as exc:
            raise StopAsyncIteration from exc

    async def close(self) -> None:
        self.closed = True


class _AnthropicClient:
    def __init__(self, events: list[Any], *, delay: float = 0) -> None:
        self.base_url = "https://mock.invalid"
        self.stream = _AsyncStream(events, delay=delay)
        self.calls: list[dict[str, Any]] = []
        self.error: BaseException | None = None
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    async def create(self, **kwargs: Any) -> _AsyncStream:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.stream


class _AuthSDKError(Exception):
    status_code = 401


class _RateSDKError(Exception):
    status_code = 429


def _events(*, stop_reason: str = "end_turn", include_stop: bool = True) -> list[Any]:
    events: list[Any] = [
        BetaRawMessageStartEvent(
            type="message_start",
            message={
                "id": "msg-1",
                "type": "message",
                "role": "assistant",
                "content": [],
                "model": "claude-test",
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {"input_tokens": 11, "output_tokens": 0},
            },
        ),
        BetaRawContentBlockStartEvent(
            type="content_block_start",
            index=0,
            content_block={"type": "text", "text": ""},
        ),
        BetaRawContentBlockDeltaEvent(
            type="content_block_delta",
            index=0,
            delta={"type": "text_delta", "text": "hello"},
        ),
        BetaRawContentBlockStopEvent(type="content_block_stop", index=0),
        BetaRawMessageDeltaEvent(
            type="message_delta",
            delta={"stop_reason": stop_reason},
            usage={
                "input_tokens": 0,
                "output_tokens": 3,
                "cache_read_input_tokens": 5,
                "cache_creation_input_tokens": 2,
            },
        ),
    ]
    if include_stop:
        events.append(BetaRawMessageStopEvent(type="message_stop"))
    return events


def _rich_events() -> list[Any]:
    events = _events()[:1]
    events.extend(
        [
            BetaRawContentBlockStartEvent(
                type="content_block_start",
                index=0,
                content_block={"type": "thinking", "thinking": "", "signature": ""},
            ),
            BetaRawContentBlockDeltaEvent(
                type="content_block_delta",
                index=0,
                delta={"type": "thinking_delta", "thinking": "plan"},
            ),
            BetaRawContentBlockDeltaEvent(
                type="content_block_delta",
                index=0,
                delta={"type": "signature_delta", "signature": "sig-1"},
            ),
            BetaRawContentBlockStopEvent(type="content_block_stop", index=0),
            BetaRawContentBlockStartEvent(
                type="content_block_start",
                index=1,
                content_block={"type": "redacted_thinking", "data": "redacted-sig"},
            ),
            BetaRawContentBlockStopEvent(type="content_block_stop", index=1),
            BetaRawContentBlockStartEvent(
                type="content_block_start",
                index=2,
                content_block={"type": "text", "text": ""},
            ),
            BetaRawContentBlockDeltaEvent(
                type="content_block_delta",
                index=2,
                delta={"type": "text_delta", "text": "answer"},
            ),
            BetaRawContentBlockStopEvent(type="content_block_stop", index=2),
            BetaRawContentBlockStartEvent(
                type="content_block_start",
                index=3,
                content_block={
                    "type": "tool_use",
                    "id": "call-1",
                    "name": "search",
                    "input": {},
                },
            ),
            BetaRawContentBlockDeltaEvent(
                type="content_block_delta",
                index=3,
                delta={"type": "input_json_delta", "partial_json": '{"q":"uth"}'},
            ),
            BetaRawContentBlockStopEvent(type="content_block_stop", index=3),
            BetaRawMessageDeltaEvent(
                type="message_delta",
                delta={"stop_reason": "tool_use"},
                usage={
                    "input_tokens": 4,
                    "output_tokens": 8,
                    "cache_read_input_tokens": 3,
                    "cache_creation_input_tokens": 1,
                },
            ),
            BetaRawMessageStopEvent(type="message_stop"),
        ]
    )
    return events


def _request(*messages: Message, tools: tuple[ToolDefinition, ...] = ()) -> GenerationRequest:
    return GenerationRequest(messages=messages, tools=tools)


async def _collect(provider: Any, request: GenerationRequest, token: CancellationToken | None = None) -> list[Any]:
    return [
        event
        async for event in provider.stream(
            request,
            cancellation=token or CancellationToken(),
        )
    ]


@pytest.mark.asyncio
async def test_anthropic_actual_model_maps_text_usage_and_closes_stream() -> None:
    client = _AnthropicClient(_events())
    provider = build_anthropic_provider("claude-test", client=client)

    events = await _collect(provider, _request(Message("user", (TextPart("hi"),))))

    assert any(isinstance(event, TextDelta) and event.text == "hello" for event in events)
    completed = next(event for event in events if isinstance(event, GenerationCompleted))
    assert completed.response.usage.input_tokens == 7
    assert completed.response.usage.output_tokens == 3
    assert completed.response.usage.cache_read_tokens == 5
    assert completed.response.usage.cache_write_tokens == 2
    assert client.stream.closed is True
    assert client.calls[0]["stream"] is True


@pytest.mark.asyncio
async def test_anthropic_missing_terminal_is_rejected() -> None:
    client = _AnthropicClient(_events(include_stop=False))
    provider = build_anthropic_provider("claude-test", client=client)

    with pytest.raises(InvalidProviderResponseError):
        await _collect(provider, _request(Message("user", (TextPart("hi"),))))


@pytest.mark.asyncio
async def test_anthropic_preserves_thinking_signature_redaction_and_tool_order() -> None:
    client = _AnthropicClient(_rich_events())
    provider = build_anthropic_provider("claude-test", client=client)

    events = await _collect(provider, _request(Message("user", (TextPart("hi"),))))
    completed = next(event for event in events if isinstance(event, GenerationCompleted))
    response = completed.response

    assert response.message.parts[:3] == (
        ReasoningPart("plan"),
        ReasoningPart(""),
        TextPart("answer"),
    )
    assert isinstance(response.message.parts[3], ToolCallPart)
    assert response.message.parts[3].to_dict() == {
        "type": "tool_call",
        "tool_call_id": "call-1",
        "name": "search",
        "arguments": {"q": "uth"},
    }
    assert [item.kind for item in response.native_items] == [
        "thinking",
        "redacted_thinking",
        "text",
        "tool_use",
    ]
    assert response.native_items[0].payload["signature"] == "sig-1"
    assert response.native_items[1].payload["data"] == "redacted-sig"
    assert response.usage.cache_read_tokens == 3
    assert response.usage.cache_write_tokens == 1
    assert any(isinstance(event, ToolCallCompleted) for event in events)
    assert sum(isinstance(event, NativeItemCompleted) for event in events) == 4


@pytest.mark.asyncio
async def test_anthropic_same_protocol_history_replays_signature_redaction_and_tool_use() -> None:
    client = _AnthropicClient(_rich_events())
    provider = build_anthropic_provider("claude-test", client=client)
    first = await _collect(provider, _request(Message("user", (TextPart("hi"),))))
    response = next(event.response for event in first if isinstance(event, GenerationCompleted))

    client.stream = _AsyncStream(_events())
    await _collect(
        provider,
        _request(
            Message("user", (TextPart("continue"),)),
            response.message,
            Message("tool", (ToolResultPart("call-1", "result"),)),
        ),
    )
    replayed = client.calls[-1]["messages"]
    assistant = next(message for message in replayed if message["role"] == "assistant")
    assert [block["type"] for block in assistant["content"]] == [
        "thinking",
        "redacted_thinking",
        "text",
        "tool_use",
    ]
    assert assistant["content"][0]["signature"] == "sig-1"
    assert assistant["content"][1]["data"] == "redacted-sig"
    assert assistant["content"][3]["id"] == "call-1"
    assert assistant["content"][3]["input"] == {"q": "uth"}
    tool = next(
        message
        for message in replayed
        if message["role"] == "user"
        and any(block.get("type") == "tool_result" for block in message["content"])
    )
    assert any(block.get("type") == "tool_result" for block in tool["content"])


@pytest.mark.asyncio
async def test_anthropic_native_items_are_not_replayed_to_another_provider() -> None:
    client = _AnthropicClient(_rich_events())
    provider = build_anthropic_provider("claude-test", client=client)
    first = await _collect(provider, _request(Message("user", (TextPart("hi"),))))
    response = next(event.response for event in first if isinstance(event, GenerationCompleted))

    other_identity = ProviderIdentity("openai", "responses", "other-model")
    encoded = AnthropicCodec().encode_message(response.message, other_identity)
    assert response.message.native_items_for(other_identity) == ()
    assert getattr(encoded.parts[0], "signature", None) is None
    assert getattr(encoded.parts[1], "id", None) != "redacted_thinking"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error, expected",
    [
        (_AuthSDKError("authentication"), AuthenticationError),
        (_RateSDKError("rate limit"), RateLimitError),
        (OSError("network"), NetworkError),
    ],
)
async def test_anthropic_sdk_failures_map_to_uthcode_errors(
    error: BaseException, expected: type[BaseException]
) -> None:
    client = _AnthropicClient(_events())
    client.error = error
    provider = build_anthropic_provider("claude-test", client=client)

    with pytest.raises(expected):
        await _collect(provider, _request(Message("user", (TextPart("hi"),))))


@pytest.mark.asyncio
async def test_anthropic_explicit_cancellation_closes_stream() -> None:
    client = _AnthropicClient(_events(), delay=0.05)
    provider = build_anthropic_provider("claude-test", client=client)
    token = CancellationToken()
    task = asyncio.create_task(_collect(provider, _request(Message("user", (TextPart("hi"),))), token))
    await asyncio.sleep(0.01)
    token.cancel()

    with pytest.raises(GenerationCancelled):
        await task
    assert client.stream.closed is True


def test_anthropic_builder_does_not_call_the_client() -> None:
    client = _AnthropicClient([])
    build_anthropic_provider("claude-test", client=client)
    assert client.calls == []
