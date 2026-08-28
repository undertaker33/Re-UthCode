from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace

import httpx
import pytest
from anthropic import (
    APIConnectionError as SDKAPIConnectionError,
    APIStatusError as SDKAPIStatusError,
    APITimeoutError as SDKAPITimeoutError,
    AuthenticationError as SDKAuthenticationError,
    PermissionDeniedError as SDKPermissionDeniedError,
    RateLimitError as SDKRateLimitError,
)
from anthropic.types import (
    RawContentBlockDeltaEvent as AnthropicRawContentBlockDeltaEvent,
    RawContentBlockStartEvent as AnthropicRawContentBlockStartEvent,
    RawContentBlockStopEvent as AnthropicRawContentBlockStopEvent,
    RawMessageDeltaEvent as AnthropicRawMessageDeltaEvent,
    RawMessageStartEvent as AnthropicRawMessageStartEvent,
    RawMessageStopEvent as AnthropicRawMessageStopEvent,
)
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
    FinishReason,
    GenerationCancelled,
    GenerationCompleted,
    GenerationRequest,
    InvalidProviderResponseError,
    Message,
    NativeItemCompleted,
    NetworkError,
    ProviderConfigurationError,
    ProviderIdentity,
    ProviderError,
    ProviderTimeoutError,
    RateLimitError,
    ReasoningPart,
    TextDelta,
    TextPart,
    ToolCallCompleted,
    ToolCallPart,
    ToolDefinition,
    ToolResultPart,
)
from uthcode.integrations.providers.anthropic import build_anthropic_provider


class _AsyncStream:
    def __init__(self, events: list[object], *, delay: float = 0.0) -> None:
        self._events = iter(events)
        self.delay = delay
        self.closed = False

    def __aiter__(self) -> _AsyncStream:
        return self

    async def __anext__(self) -> object:
        if self.delay:
            await asyncio.sleep(self.delay)
        try:
            return next(self._events)
        except StopIteration as exc:
            raise StopAsyncIteration from exc

    async def close(self) -> None:
        self.closed = True


class _AnthropicClient:
    def __init__(self, events: list[object], *, delay: float = 0.0) -> None:
        self.stream = _AsyncStream(events, delay=delay)
        self.calls: list[dict[str, object]] = []
        self.count_calls: list[dict[str, object]] = []
        self.error: BaseException | None = None
        self.messages = SimpleNamespace(
            create=self.create,
            count_tokens=self.count_tokens,
        )

    async def create(self, **kwargs: object) -> _AsyncStream:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.stream

    async def count_tokens(self, **kwargs: object) -> SimpleNamespace:
        self.count_calls.append(kwargs)
        return SimpleNamespace(input_tokens=42)


def _events(*, include_stop: bool = True, include_tool: bool = False) -> list[object]:
    events: list[object] = [
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
    ]
    if include_tool:
        events.extend(
            [
                BetaRawContentBlockStartEvent(
                    type="content_block_start",
                    index=1,
                    content_block={
                        "type": "tool_use",
                        "id": "call-1",
                        "name": "search",
                        "input": {},
                    },
                ),
                BetaRawContentBlockDeltaEvent(
                    type="content_block_delta",
                    index=1,
                    delta={"type": "input_json_delta", "partial_json": '{"q":"uth"}'},
                ),
                BetaRawContentBlockStopEvent(type="content_block_stop", index=1),
            ]
        )
    events.append(
        BetaRawMessageDeltaEvent(
            type="message_delta",
            delta={"stop_reason": "tool_use" if include_tool else "end_turn"},
            usage={
                "input_tokens": 0,
                "output_tokens": 3,
                "cache_read_input_tokens": 5,
                "cache_creation_input_tokens": 2,
            },
        )
    )
    if include_stop:
        events.append(BetaRawMessageStopEvent(type="message_stop"))
    return events


def _rich_events() -> list[object]:
    events = _events(include_stop=False)[:1]
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
                    "input_tokens": 0,
                    "output_tokens": 8,
                    "cache_read_input_tokens": 3,
                    "cache_creation_input_tokens": 1,
                },
            ),
            BetaRawMessageStopEvent(type="message_stop"),
        ]
    )
    return events


def _request(
    *messages: Message,
    system_prompt: str | None = None,
    tools: tuple[ToolDefinition, ...] = (),
    metadata: dict[str, object] | None = None,
    model: str | None = None,
) -> GenerationRequest:
    return GenerationRequest(
        messages=messages,
        system_prompt=system_prompt,
        tools=tools,
        metadata=metadata or {},
        model=model,
    )


async def _collect(provider: object, request: GenerationRequest, token: CancellationToken | None = None) -> list[object]:
    return [
        event
        async for event in provider.stream(  # type: ignore[attr-defined]
            request,
            cancellation=token or CancellationToken(),
        )
    ]


@pytest.mark.asyncio
async def test_anthropic_public_stream_maps_text_usage_and_closes() -> None:
    client = _AnthropicClient(_events())
    provider = build_anthropic_provider("claude-test", client=client)

    events = await _collect(provider, _request(Message("user", (TextPart("hi"),))))

    assert any(isinstance(event, TextDelta) and event.text == "hello" for event in events)
    completed = next(event for event in events if isinstance(event, GenerationCompleted))
    assert completed.response.usage.input_tokens == 11
    assert completed.response.usage.output_tokens == 3
    assert completed.response.usage.cache_read_tokens == 5
    assert completed.response.usage.cache_write_tokens == 2
    assert completed.response.finish_reason is FinishReason.STOP
    assert "system" not in client.calls[0]
    assert all(message["role"] != "system" for message in client.calls[0]["messages"])
    assert client.stream.closed is True


@pytest.mark.asyncio
async def test_anthropic_request_keeps_context_steering_duplicates_and_current_user_separate() -> None:
    client = _AnthropicClient(_events())
    provider = build_anthropic_provider("claude-test", client=client)

    await _collect(
        provider,
        _request(
            Message("user", (TextPart("[Context] runtime"),)),
            Message("user", (TextPart("steering"),)),
            Message("user", (TextPart("duplicate"),)),
            Message("user", (TextPart("duplicate"),)),
            Message("user", (TextPart("？"),)),
        ),
    )

    sent = client.calls[0]["messages"]
    assert [message["content"][0]["text"] for message in sent] == [
        "[Context] runtime",
        "steering",
        "duplicate",
        "duplicate",
        "？",
    ]
    assert sent[-1] == {
        "role": "user",
        "content": [{"type": "text", "text": "？"}],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_max_output", (8_192, 128))
async def test_anthropic_async_limits_are_awaited_by_provider(
    provider_max_output: int,
) -> None:
    client = _AnthropicClient(_events())
    retrieved: list[str] = []

    async def retrieve(model: str) -> SimpleNamespace:
        retrieved.append(model)
        return SimpleNamespace(
            max_input_tokens=32_000,
            max_tokens=provider_max_output,
        )

    client.models = SimpleNamespace(retrieve=retrieve)
    provider = build_anthropic_provider("claude-test", client=client)
    limits = await provider.resolve_model_limits("claude-test")

    assert retrieved == ["claude-test"]
    assert limits is not None
    assert limits.max_input_tokens == 32_000
    assert limits.max_output_tokens == provider_max_output


@pytest.mark.asyncio
async def test_anthropic_system_prompt_maps_only_to_top_level_system() -> None:
    client = _AnthropicClient(_events())
    provider = build_anthropic_provider("claude-test", client=client)

    await _collect(
        provider,
        _request(
            Message("user", (TextPart("hi"),)),
            system_prompt="rules",
        ),
    )

    call = client.calls[0]
    assert call["system"] == "rules"
    assert all(message["role"] != "system" for message in call["messages"])


@pytest.mark.asyncio
async def test_anthropic_explicit_cache_breakpoint_matches_count_shape_and_order() -> None:
    metadata = {
        "stable_prefix_fingerprint": "prefix-v1",
        "tool_schema_fingerprint": "tools-v1",
    }
    tool = ToolDefinition(
        "search",
        "Search docs",
        {"type": "object", "properties": {"q": {"type": "string"}}},
    )
    client = _AnthropicClient(_events())
    provider = build_anthropic_provider("claude-test", client=client)
    request = _request(
        Message("user", (TextPart("hi"),)),
        system_prompt="rules",
        tools=(tool,),
        metadata=metadata,
    )

    await _collect(provider, request)
    call = client.calls[-1]
    system = call["system"]
    assert system == [
        {
            "type": "text",
            "text": "rules",
            "cache_control": {"type": "ephemeral"},
        }
    ]
    assert call["tools"][-1].get("cache_control") is None
    assert system[0]["text"] == "rules"
    assert "input_schema" not in system[0]

    counted = await provider.count_input_tokens(request)
    assert counted is not None
    assert counted.input_tokens == 42
    assert client.count_calls[-1]["system"] == call["system"]
    assert client.count_calls[-1]["tools"] == call["tools"]
    assert client.count_calls[-1]["messages"] == call["messages"]

    client.stream = _AsyncStream(_events())
    await _collect(
        provider,
        _request(
            Message("user", (TextPart("hi"),)),
            tools=(tool,),
            metadata=metadata,
        ),
    )
    tool_only_call = client.calls[-1]
    assert tool_only_call["tools"][-1]["cache_control"] == {"type": "ephemeral"}
    assert "system" not in tool_only_call


@pytest.mark.asyncio
async def test_anthropic_reads_cache_usage_from_non_beta_message_start() -> None:
    events: list[object] = [
        AnthropicRawMessageStartEvent(
            type="message_start",
            message={
                "id": "msg-cache",
                "type": "message",
                "role": "assistant",
                "content": [],
                "model": "claude-test",
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {
                    "input_tokens": 11,
                    "output_tokens": 0,
                    "cache_read_input_tokens": 7,
                    "cache_creation_input_tokens": 4,
                },
            },
        ),
        AnthropicRawContentBlockStartEvent(
            type="content_block_start",
            index=0,
            content_block={"type": "text", "text": ""},
        ),
        AnthropicRawContentBlockDeltaEvent(
            type="content_block_delta",
            index=0,
            delta={"type": "text_delta", "text": "cached"},
        ),
        AnthropicRawContentBlockStopEvent(type="content_block_stop", index=0),
        AnthropicRawMessageDeltaEvent(
            type="message_delta",
            delta={"stop_reason": "end_turn", "stop_sequence": None},
            usage={"output_tokens": 2},
        ),
        AnthropicRawMessageStopEvent(type="message_stop"),
    ]
    client = _AnthropicClient(events)
    provider = build_anthropic_provider("claude-test", client=client)

    result = await _collect(
        provider,
        _request(Message("user", (TextPart("hi"),))),
    )

    completed = next(event for event in result if isinstance(event, GenerationCompleted))
    assert completed.response.usage.input_tokens == 11
    assert completed.response.usage.output_tokens == 2
    assert completed.response.usage.cache_read_tokens == 7
    assert completed.response.usage.cache_write_tokens == 4
    assert client.stream.closed is True
    assert client.calls[0]["stream"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("ping_positions", [(0,), (0, 2, 4)])
async def test_anthropic_interleaved_ping_events_are_ignored(ping_positions: tuple[int, ...]) -> None:
    source_events = _events()
    events: list[object] = []
    for index, event in enumerate(source_events):
        events.append(event)
        if index in ping_positions:
            events.append(SimpleNamespace(type="ping"))

    client = _AnthropicClient(events)
    provider = build_anthropic_provider("claude-test", client=client)

    collected = await _collect(provider, _request(Message("user", (TextPart("hi"),))))

    assert any(isinstance(event, TextDelta) and event.text == "hello" for event in collected)
    assert sum(isinstance(event, GenerationCompleted) for event in collected) == 1
    assert client.stream.closed is True


@pytest.mark.asyncio
async def test_anthropic_unknown_stream_event_remains_rejected() -> None:
    events = _events()
    events.insert(1, SimpleNamespace(type="unknown"))
    client = _AnthropicClient(events)
    provider = build_anthropic_provider("claude-test", client=client)

    with pytest.raises(InvalidProviderResponseError):
        await _collect(provider, _request(Message("user", (TextPart("hi"),))))
    assert client.stream.closed is True


@pytest.mark.asyncio
async def test_anthropic_preserves_thinking_redaction_tool_order_and_native_items() -> None:
    client = _AnthropicClient(_rich_events())
    provider = build_anthropic_provider("claude-test", client=client)

    events = await _collect(provider, _request(Message("user", (TextPart("hi"),))))
    response = next(event.response for event in events if isinstance(event, GenerationCompleted))

    assert response.message.parts == (
        ReasoningPart("plan"),
        ReasoningPart(""),
        TextPart("answer"),
        ToolCallPart("call-1", "search", {"q": "uth"}),
    )
    assert [item.kind for item in response.native_items] == [
        "thinking",
        "redacted_thinking",
        "text",
        "tool_use",
    ]
    assert response.native_items[0].payload["signature"] == "sig-1"
    assert response.native_items[1].payload["data"] == "redacted-sig"
    assert sum(isinstance(event, NativeItemCompleted) for event in events) == 4
    assert any(isinstance(event, ToolCallCompleted) for event in events)


@pytest.mark.asyncio
async def test_anthropic_same_identity_replays_native_history_and_other_identity_falls_back() -> None:
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
    assistant = next(
        message for message in client.calls[-1]["messages"] if message["role"] == "assistant"
    )
    assert [block["type"] for block in assistant["content"]] == [
        "thinking",
        "redacted_thinking",
        "text",
        "tool_use",
    ]
    assert assistant["content"][0]["signature"] == "sig-1"
    assert assistant["content"][3]["input"] == {"q": "uth"}
    assert any(
        message["role"] == "user"
        and any(block["type"] == "tool_result" for block in message["content"])
        for message in client.calls[-1]["messages"]
    )

    other_client = _AnthropicClient(_events())
    other = build_anthropic_provider("different-model", client=other_client)
    await _collect(other, _request(response.message))
    other_assistant = next(
        message
        for message in other_client.calls[-1]["messages"]
        if message["role"] == "assistant"
    )
    assert all(block["type"] == "text" or block["type"] == "tool_use" for block in other_assistant["content"])
    assert [
        block["text"]
        for block in other_assistant["content"]
        if block["type"] == "text"
    ] == ["answer"]
    assert not any(block["type"] == "redacted_thinking" for block in other_assistant["content"])


@pytest.mark.asyncio
async def test_anthropic_plan_revision_maps_tool_result_before_user_feedback() -> None:
    client = _AnthropicClient(_events())
    provider = build_anthropic_provider("claude-test", client=client)

    await _collect(
        provider,
        _request(
            Message("user", (TextPart("make a plan"),)),
            Message("assistant", (ToolCallPart("plan-1", "ProposePlan", {"plan": "v1"}),)),
            Message("tool", (ToolResultPart("plan-1", '{"choice":"revise","revision":1}'),)),
            Message("user", (TextPart("include verification"),)),
        ),
    )

    messages = client.calls[-1]["messages"]
    tool_use_index = next(
        index
        for index, message in enumerate(messages)
        if any(block["type"] == "tool_use" for block in message["content"])
    )
    tool_result_index = next(
        index
        for index, message in enumerate(messages)
        if any(block["type"] == "tool_result" for block in message["content"])
    )
    feedback_index = next(
        index
        for index, message in enumerate(messages)
        if any(block.get("text") == "include verification" for block in message["content"])
    )
    assert tool_use_index < tool_result_index < feedback_index


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "events",
    [_events(include_stop=False), _events(include_tool=True)[:-2]],
)
async def test_anthropic_missing_terminal_or_open_block_is_rejected(events: list[object]) -> None:
    client = _AnthropicClient(events)
    provider = build_anthropic_provider("claude-test", client=client)
    with pytest.raises(InvalidProviderResponseError):
        await _collect(provider, _request(Message("user", (TextPart("hi"),))))
    assert client.stream.closed is True


@pytest.mark.asyncio
async def test_anthropic_invalid_tool_arguments_are_rejected() -> None:
    events = _rich_events()
    invalid = events.copy()
    invalid[-3] = BetaRawContentBlockDeltaEvent(
        type="content_block_delta",
        index=3,
        delta={"type": "input_json_delta", "partial_json": "not-json"},
    )
    client = _AnthropicClient(invalid)
    provider = build_anthropic_provider("claude-test", client=client)
    with pytest.raises(InvalidProviderResponseError):
        await _collect(provider, _request(Message("user", (TextPart("hi"),))))


@pytest.mark.asyncio
async def test_anthropic_missing_stop_reason_and_invalid_native_types_are_rejected() -> None:
    missing_reason = _events()
    missing_reason[-2] = BetaRawMessageDeltaEvent(
        type="message_delta",
        delta={},
        usage={"input_tokens": 0, "output_tokens": 3},
    )
    client = _AnthropicClient(missing_reason)
    provider = build_anthropic_provider("claude-test", client=client)
    with pytest.raises(InvalidProviderResponseError):
        await _collect(provider, _request(Message("user", (TextPart("hi"),))))

    invalid_signature = _rich_events()
    invalid_signature[1] = invalid_signature[1].model_copy(
        update={
            "content_block": {
                "type": "thinking",
                "thinking": "",
                "signature": 7,
            }
        }
    )
    client = _AnthropicClient(invalid_signature)
    provider = build_anthropic_provider("claude-test", client=client)
    with pytest.raises(InvalidProviderResponseError):
        await _collect(provider, _request(Message("user", (TextPart("hi"),))))

    invalid_redacted = _rich_events()
    invalid_redacted[5] = invalid_redacted[5].model_copy(
        update={"content_block": {"type": "redacted_thinking", "data": 7}}
    )
    client = _AnthropicClient(invalid_redacted)
    provider = build_anthropic_provider("claude-test", client=client)
    with pytest.raises(InvalidProviderResponseError):
        await _collect(provider, _request(Message("user", (TextPart("hi"),))))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error_factory", "expected"),
    [
        (
            lambda request: httpx.HTTPStatusError(
                "not used",
                request=request,
                response=httpx.Response(401, request=request),
            ),
            NetworkError,
        ),
    ],
)
async def test_anthropic_generic_errors_are_safe(error_factory: object, expected: type[BaseException]) -> None:
    del error_factory, expected
    request = httpx.Request("GET", "https://mock.invalid")
    client = _AnthropicClient(_events())
    client.error = OSError("secret-sk-anthropic-error")
    provider = build_anthropic_provider("claude-test", client=client)
    with pytest.raises(NetworkError) as raised:
        await _collect(provider, _request(Message("user", (TextPart("hi"),))))
    assert "secret-sk-anthropic-error" not in str(raised.value)
    del request


@pytest.mark.asyncio
async def test_anthropic_official_errors_map_without_sdk_text() -> None:
    request = httpx.Request("GET", "https://mock.invalid")
    cases: list[tuple[BaseException, type[BaseException]]] = [
        (SDKAuthenticationError("secret-auth-text", response=httpx.Response(401, request=request), body={}), AuthenticationError),
        (SDKPermissionDeniedError("secret-permission-text", response=httpx.Response(403, request=request), body={}), AuthenticationError),
        (SDKRateLimitError("secret-rate-text", response=httpx.Response(429, request=request), body={}), RateLimitError),
        (SDKAPIConnectionError(request=request), NetworkError),
        (SDKAPITimeoutError(request), ProviderTimeoutError),
        (SDKAPIStatusError("secret-status-text", response=httpx.Response(500, request=request), body={}), ProviderError),
        (SDKAPIStatusError("secret-timeout-text", response=httpx.Response(408, request=request), body={}), ProviderTimeoutError),
        (SDKAPIStatusError("secret-request-text", response=httpx.Response(400, request=request), body={}), ProviderConfigurationError),
    ]
    for error, expected in cases:
        client = _AnthropicClient(_events())
        client.error = error
        provider = build_anthropic_provider("claude-test", client=client)
        with pytest.raises(expected) as raised:
            await _collect(provider, _request(Message("user", (TextPart("hi"),))))
        assert "secret-" not in str(raised.value)


@pytest.mark.asyncio
async def test_anthropic_explicit_and_task_cancellation_close_stream() -> None:
    client = _AnthropicClient(_events(), delay=0.05)
    provider = build_anthropic_provider("claude-test", client=client)
    token = CancellationToken()
    task = asyncio.create_task(
        _collect(provider, _request(Message("user", (TextPart("hi"),))), token)
    )
    await asyncio.sleep(0.01)
    token.cancel()
    with pytest.raises(GenerationCancelled):
        await task
    assert client.stream.closed is True

    client = _AnthropicClient(_events(), delay=0.05)
    provider = build_anthropic_provider("claude-test", client=client)
    task = asyncio.create_task(_collect(provider, _request(Message("user", (TextPart("hi"),)))))
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert client.stream.closed is True


def test_anthropic_builder_accepts_client_without_calling_create() -> None:
    client = _AnthropicClient([])
    provider = build_anthropic_provider("claude-test", client=client)
    assert provider.identity == ProviderIdentity("anthropic", "messages", "claude-test")
    assert client.calls == []


@pytest.mark.live
@pytest.mark.skipif(
    os.environ.get("UTHCODE_RUN_LIVE") != "1",
    reason="set UTHCODE_RUN_LIVE=1 to authorize live validation",
)
@pytest.mark.asyncio
async def test_anthropic_live_gate_is_not_run_by_w01() -> None:
    pytest.skip("W01 performs offline Provider validation only")
