from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace

import httpx
import pytest
from openai import (
    APIConnectionError as SDKAPIConnectionError,
    APIStatusError as SDKAPIStatusError,
    APITimeoutError as SDKAPITimeoutError,
    AuthenticationError as SDKAuthenticationError,
    PermissionDeniedError as SDKPermissionDeniedError,
    RateLimitError as SDKRateLimitError,
)
from openai.types import CompletionUsage
from openai.types.chat import ChatCompletionChunk
from openai.types.chat.chat_completion_chunk import ChoiceDelta

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
    ReasoningDelta,
    ReasoningPart,
    TextDelta,
    TextPart,
    ToolCallArgumentsDelta,
    ToolCallCompleted,
    ToolCallPart,
    ToolCallStarted,
    ToolDefinition,
    ToolResultPart,
)
from uthcode.integrations.providers.openai_compat import build_openai_compat_provider


class _AsyncStream:
    def __init__(self, chunks: list[object], *, delay: float = 0.0) -> None:
        self._chunks = iter(chunks)
        self.delay = delay
        self.closed = False

    def __aiter__(self) -> _AsyncStream:
        return self

    async def __anext__(self) -> object:
        if self.delay:
            await asyncio.sleep(self.delay)
        try:
            return next(self._chunks)
        except StopIteration as exc:
            raise StopAsyncIteration from exc

    async def close(self) -> None:
        self.closed = True


class _OpenAICompatClient:
    def __init__(self, chunks: list[object], *, delay: float = 0.0) -> None:
        self.stream = _AsyncStream(chunks, delay=delay)
        self.calls: list[dict[str, object]] = []
        self.error: BaseException | None = None
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    async def create(self, **kwargs: object) -> _AsyncStream:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.stream


def _chunk(
    delta: object,
    *,
    finish_reason: str | None = None,
    usage: CompletionUsage | None = None,
) -> ChatCompletionChunk:
    return ChatCompletionChunk(
        id="chunk-1",
        choices=[{"index": 0, "delta": delta, "finish_reason": finish_reason}],
        created=1,
        model="deepseek-test",
        object="chat.completion.chunk",
        usage=usage,
    )


def _tool_delta(index: int, *, call_id: str | None, name: str | None, arguments: str) -> ChoiceDelta:
    return ChoiceDelta(
        role="assistant",
        tool_calls=[
            {
                "index": index,
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": arguments},
            }
        ],
    )


def _chunks(*, include_finish: bool = True) -> list[object]:
    reasoning = ChoiceDelta.model_construct(
        role="assistant", content=None, tool_calls=None, reasoning_content="plan"
    )
    chunks: list[object] = [
        _chunk(reasoning),
        _chunk(ChoiceDelta(role="assistant", content="answer")),
        _chunk(_tool_delta(0, call_id="call-1", name="search", arguments='{"q":')),
        _chunk(_tool_delta(1, call_id="call-2", name="lookup", arguments='{"q":')),
        _chunk(_tool_delta(0, call_id=None, name=None, arguments='"one"}')),
        _chunk(_tool_delta(1, call_id=None, name=None, arguments='"two"}')),
    ]
    if include_finish:
        chunks.append(
            _chunk(
                ChoiceDelta(role="assistant"),
                finish_reason="tool_calls",
                usage=CompletionUsage(
                    prompt_tokens=12,
                    completion_tokens=8,
                    total_tokens=20,
                    prompt_tokens_details={"cached_tokens": 3, "cache_write_tokens": 1},
                    completion_tokens_details={"reasoning_tokens": 2},
                ),
            )
        )
    return chunks


def _delayed_identity_chunks() -> list[object]:
    return [
        _chunk(_tool_delta(0, call_id=None, name=None, arguments='{"q":')),
        _chunk(_tool_delta(1, call_id=None, name=None, arguments='{"q":')),
        _chunk(_tool_delta(0, call_id="call-1", name=None, arguments='"one"}')),
        _chunk(_tool_delta(1, call_id="call-2", name=None, arguments='"two"}')),
        _chunk(_tool_delta(0, call_id=None, name="search", arguments="")),
        _chunk(_tool_delta(1, call_id=None, name="lookup", arguments="")),
        _chunk(
            ChoiceDelta(role="assistant"),
            finish_reason="tool_calls",
            usage=CompletionUsage(
                prompt_tokens=12,
                completion_tokens=8,
                total_tokens=20,
            ),
        ),
    ]


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
async def test_chat_public_stream_maps_reasoning_text_indexed_tools_usage_and_order() -> None:
    client = _OpenAICompatClient(_chunks())
    provider = build_openai_compat_provider(
        "deepseek-test", base_url="https://mock.invalid/v1", client=client
    )
    tools = (ToolDefinition("search", "Search docs", {"type": "object", "properties": {"q": {"type": "string"}}}),)
    events = await _collect(provider, _request(Message("user", (TextPart("hi"),)), tools=tools))
    assert any(isinstance(event, TextDelta) and event.text == "answer" for event in events)
    assert any(isinstance(event, ReasoningDelta) and event.text == "plan" for event in events)
    response = next(event.response for event in events if isinstance(event, GenerationCompleted))
    assert response.message.parts == (
        ReasoningPart("plan"),
        TextPart("answer"),
        ToolCallPart("call-1", "search", {"q": "one"}),
        ToolCallPart("call-2", "lookup", {"q": "two"}),
    )
    assert response.usage.cache_read_tokens == 3
    assert response.usage.cache_write_tokens == 1
    assert response.finish_reason is FinishReason.TOOL_CALLS
    assert [item.kind for item in response.native_items] == [
        "reasoning_carrier", "assistant_text", "assistant_tool_call", "assistant_tool_call"
    ]
    assert [
        item.payload["index"]
        for item in response.native_items
        if item.kind == "assistant_tool_call"
    ] == [0, 1]
    assert sum(isinstance(event, NativeItemCompleted) for event in events) == 4
    assert client.stream.closed is True
    assert client.calls[0]["stream_options"] == {"include_usage": True}
    assert not any(message["role"] == "system" for message in client.calls[0]["messages"])
    assert client.calls[0]["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "search",
                "description": "Search docs",
                "parameters": {"type": "object", "properties": {"q": {"type": "string"}},
                },
            },
        }
    ]


@pytest.mark.asyncio
async def test_chat_public_stream_preserves_interleaved_reasoning_and_text_segments() -> None:
    chunks = [
        _chunk(
            ChoiceDelta.model_construct(
                role="assistant", content="first", reasoning_content="plan"
            )
        ),
        _chunk(
            ChoiceDelta.model_construct(
                role="assistant", content=None, reasoning_content="more"
            )
        ),
        _chunk(ChoiceDelta(role="assistant", content="second")),
        _chunk(ChoiceDelta(role="assistant"), finish_reason="stop"),
    ]
    client = _OpenAICompatClient(chunks)
    provider = build_openai_compat_provider(
        "deepseek-test", base_url="https://mock.invalid/v1", client=client
    )

    events = await _collect(provider, _request(Message("user", (TextPart("hi"),))))

    assert [
        type(event)
        for event in events
        if isinstance(event, (ReasoningDelta, TextDelta))
    ] == [ReasoningDelta, TextDelta, ReasoningDelta, TextDelta]
    response = next(event.response for event in events if isinstance(event, GenerationCompleted))
    assert response.message.parts == (
        ReasoningPart("plan"),
        TextPart("first"),
        ReasoningPart("more"),
        TextPart("second"),
    )


@pytest.mark.asyncio
async def test_chat_request_keeps_context_steering_duplicates_and_current_user_separate() -> None:
    client = _OpenAICompatClient(_chunks())
    provider = build_openai_compat_provider(
        "deepseek-test", base_url="https://mock.invalid/v1", client=client
    )

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
    assert [message["content"] for message in sent] == [
        "[Context] runtime",
        "steering",
        "duplicate",
        "duplicate",
        "？",
    ]
    assert sent[-1] == {"role": "user", "content": "？"}


@pytest.mark.asyncio
async def test_chat_compat_does_not_send_responses_or_anthropic_cache_fields() -> None:
    client = _OpenAICompatClient(_chunks())
    provider = build_openai_compat_provider(
        "deepseek-test", base_url="https://mock.invalid/v1", client=client
    )
    request = _request(
        Message("user", (TextPart("hi"),)),
        system_prompt="rules",
        tools=(
            ToolDefinition(
                "search",
                "Search docs",
                {"type": "object", "properties": {"q": {"type": "string"}}},
            ),
        ),
        metadata={
            "stable_prefix_fingerprint": "prefix-v1",
            "tool_schema_fingerprint": "tools-v1",
        },
    )

    await _collect(provider, request)
    call = client.calls[0]
    assert {
        "prompt_cache_key",
        "prompt_cache_options",
        "prompt_cache_retention",
        "cache_control",
    }.isdisjoint(call)
    assert "cache_control" not in repr(call)


@pytest.mark.asyncio
async def test_chat_delayed_tool_identity_replays_cached_deltas_with_real_ids() -> None:
    client = _OpenAICompatClient(_delayed_identity_chunks())
    provider = build_openai_compat_provider(
        "deepseek-test", base_url="https://mock.invalid/v1", client=client
    )

    events = await _collect(provider, _request(Message("user", (TextPart("hi"),))))

    for call_id, name, expected_arguments in (
        ("call-1", "search", ('{"q":', '"one"}')),
        ("call-2", "lookup", ('{"q":', '"two"}')),
    ):
        call_events = [
            event
            for event in events
            if isinstance(
                event,
                (ToolCallStarted, ToolCallArgumentsDelta, ToolCallCompleted),
            )
            and event.tool_call_id == call_id
        ]
        assert [type(event) for event in call_events] == [
            ToolCallStarted,
            ToolCallArgumentsDelta,
            ToolCallArgumentsDelta,
            ToolCallCompleted,
        ]
        assert isinstance(call_events[0], ToolCallStarted)
        assert call_events[0].name == name
        assert [event.arguments_delta for event in call_events[1:3]] == list(expected_arguments)
        assert isinstance(call_events[3], ToolCallCompleted)
        assert call_events[3].name == name
        assert call_events[3].arguments == {"q": expected_arguments[1][1:-2]}

    tool_events = [
        event
        for event in events
        if isinstance(event, (ToolCallStarted, ToolCallArgumentsDelta, ToolCallCompleted))
    ]
    assert [(type(event), event.tool_call_id) for event in tool_events] == [
        (ToolCallStarted, "call-1"),
        (ToolCallArgumentsDelta, "call-1"),
        (ToolCallArgumentsDelta, "call-1"),
        (ToolCallCompleted, "call-1"),
        (ToolCallStarted, "call-2"),
        (ToolCallArgumentsDelta, "call-2"),
        (ToolCallArgumentsDelta, "call-2"),
        (ToolCallCompleted, "call-2"),
    ]
    assert all(not event.tool_call_id.startswith("index-") for event in tool_events)


@pytest.mark.asyncio
async def test_chat_nullable_usage_is_normalized_and_history_uses_chat_shapes() -> None:
    client = _OpenAICompatClient(
        [
            _chunk(ChoiceDelta(role="assistant", content="answer")),
            _chunk(
                ChoiceDelta(role="assistant"),
                finish_reason="stop",
                usage=CompletionUsage(
                    prompt_tokens=3,
                    completion_tokens=1,
                    total_tokens=4,
                    prompt_tokens_details=None,
                    completion_tokens_details=None,
                ),
            ),
        ]
    )
    provider = build_openai_compat_provider(
        "deepseek-test", base_url="https://mock.invalid/v1", client=client
    )
    first = await _collect(provider, _request(Message("user", (TextPart("hi"),))))
    response = next(event.response for event in first if isinstance(event, GenerationCompleted))
    assert response.usage.cache_read_tokens == 0
    assert response.usage.details["reasoning_tokens"] == 0

    history_client = _OpenAICompatClient(_chunks())
    history_provider = build_openai_compat_provider(
        "deepseek-test", base_url="https://mock.invalid/v1", client=history_client
    )
    history_first = await _collect(
        history_provider, _request(Message("user", (TextPart("hi"),)))
    )
    history_response = next(
        event.response for event in history_first if isinstance(event, GenerationCompleted)
    )
    history_client.stream = _AsyncStream(_chunks())
    await _collect(
        history_provider,
        _request(
            Message("user", (TextPart("continue"),)),
            history_response.message,
            Message("tool", (ToolResultPart("call-1", "tool output"),)),
            system_prompt="rules",
        ),
    )
    messages = history_client.calls[-1]["messages"]
    assistant = next(message for message in messages if message["role"] == "assistant")
    assert assistant["reasoning_content"] == "plan"
    assert assistant["tool_calls"] == [
        {"id": "call-1", "type": "function", "function": {"name": "search", "arguments": '{"q":"one"}'}},
        {"id": "call-2", "type": "function", "function": {"name": "lookup", "arguments": '{"q":"two"}'}},
    ]
    assert messages[0] == {"role": "system", "content": "rules"}
    assert messages[1] == {"role": "user", "content": "continue"}
    assert sum(message["role"] == "system" for message in messages) == 1
    assert any(message == {"role": "tool", "tool_call_id": "call-1", "content": "tool output"} for message in messages)
    assert "function_call_output" not in repr(messages)


@pytest.mark.asyncio
async def test_chat_plan_revision_maps_tool_message_before_user_feedback() -> None:
    client = _OpenAICompatClient(_chunks())
    provider = build_openai_compat_provider(
        "deepseek-test", base_url="https://mock.invalid/v1", client=client
    )

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
    tool_index = next(
        index
        for index, message in enumerate(messages)
        if message.get("role") == "tool" and message.get("tool_call_id") == "plan-1"
    )
    feedback_index = next(
        index
        for index, message in enumerate(messages)
        if message == {"role": "user", "content": "include verification"}
    )
    assert tool_index < feedback_index


@pytest.mark.asyncio
async def test_chat_cross_identity_native_items_are_ignored_and_standard_parts_remain() -> None:
    client = _OpenAICompatClient(_chunks())
    provider = build_openai_compat_provider(
        "deepseek-test", base_url="https://mock.invalid/v1", client=client
    )
    first = await _collect(provider, _request(Message("user", (TextPart("hi"),))))
    response = next(event.response for event in first if isinstance(event, GenerationCompleted))
    other_client = _OpenAICompatClient(_chunks())
    other = build_openai_compat_provider(
        "other-model", base_url="https://mock.invalid/v1", client=other_client
    )
    await _collect(other, _request(response.message))
    assistant = other_client.calls[-1]["messages"][0]
    assert "reasoning_content" not in assistant
    assert assistant["content"] == "answer"
    assert assistant["tool_calls"][0]["id"] == "call-1"


@pytest.mark.asyncio
async def test_chat_missing_finish_or_invalid_tool_arguments_is_rejected() -> None:
    client = _OpenAICompatClient(_chunks(include_finish=False))
    provider = build_openai_compat_provider(
        "deepseek-test", base_url="https://mock.invalid/v1", client=client
    )
    with pytest.raises(InvalidProviderResponseError):
        await _collect(provider, _request(Message("user", (TextPart("hi"),))))

    bad = _chunks()
    bad[-2] = _chunk(_tool_delta(0, call_id=None, name=None, arguments="not-json"))
    client = _OpenAICompatClient(bad)
    provider = build_openai_compat_provider(
        "deepseek-test", base_url="https://mock.invalid/v1", client=client
    )
    with pytest.raises(InvalidProviderResponseError):
        await _collect(provider, _request(Message("user", (TextPart("hi"),))))


@pytest.mark.asyncio
async def test_chat_conflicting_index_identity_is_rejected() -> None:
    chunks = _chunks()
    chunks.insert(4, _chunk(_tool_delta(0, call_id="different", name=None, arguments="")))
    client = _OpenAICompatClient(chunks)
    provider = build_openai_compat_provider(
        "deepseek-test", base_url="https://mock.invalid/v1", client=client
    )
    with pytest.raises(InvalidProviderResponseError):
        await _collect(provider, _request(Message("user", (TextPart("hi"),))))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("call_id", "name"),
    [(None, "search"), ("call-1", None)],
)
async def test_chat_tool_call_requires_id_and_name(call_id: str | None, name: str | None) -> None:
    chunks = [
        _chunk(_tool_delta(0, call_id=call_id, name=name, arguments="{}")),
        _chunk(ChoiceDelta(role="assistant"), finish_reason="tool_calls"),
    ]
    client = _OpenAICompatClient(chunks)
    provider = build_openai_compat_provider(
        "deepseek-test", base_url="https://mock.invalid/v1", client=client
    )
    with pytest.raises(InvalidProviderResponseError):
        await _collect(provider, _request(Message("user", (TextPart("hi"),))))


@pytest.mark.asyncio
async def test_chat_official_errors_are_safe() -> None:
    request = httpx.Request("GET", "https://mock.invalid")
    cases: list[tuple[BaseException, type[BaseException]]] = [
        (SDKAuthenticationError("secret-auth", response=httpx.Response(401, request=request), body={}), AuthenticationError),
        (SDKPermissionDeniedError("secret-permission", response=httpx.Response(403, request=request), body={}), AuthenticationError),
        (SDKRateLimitError("secret-rate", response=httpx.Response(429, request=request), body={}), RateLimitError),
        (SDKAPIConnectionError(request=request), NetworkError),
        (SDKAPITimeoutError(request), ProviderTimeoutError),
        (SDKAPIStatusError("secret-status", response=httpx.Response(500, request=request), body={}), ProviderError),
        (SDKAPIStatusError("secret-timeout", response=httpx.Response(408, request=request), body={}), ProviderTimeoutError),
        (SDKAPIStatusError("secret-request", response=httpx.Response(400, request=request), body={}), ProviderConfigurationError),
    ]
    for error, expected in cases:
        client = _OpenAICompatClient(_chunks())
        client.error = error
        provider = build_openai_compat_provider(
            "deepseek-test", base_url="https://mock.invalid/v1", client=client
        )
        with pytest.raises(expected) as raised:
            await _collect(provider, _request(Message("user", (TextPart("hi"),))))
        assert "secret-" not in str(raised.value)


@pytest.mark.asyncio
async def test_chat_explicit_and_task_cancellation_close_stream() -> None:
    client = _OpenAICompatClient(_chunks(), delay=0.05)
    provider = build_openai_compat_provider(
        "deepseek-test", base_url="https://mock.invalid/v1", client=client
    )
    token = CancellationToken()
    task = asyncio.create_task(_collect(provider, _request(Message("user", (TextPart("hi"),))), token))
    await asyncio.sleep(0.01)
    token.cancel()
    with pytest.raises(GenerationCancelled):
        await task
    assert client.stream.closed is True

    client = _OpenAICompatClient(_chunks(), delay=0.05)
    provider = build_openai_compat_provider(
        "deepseek-test", base_url="https://mock.invalid/v1", client=client
    )
    task = asyncio.create_task(_collect(provider, _request(Message("user", (TextPart("hi"),)))))
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert client.stream.closed is True


def test_chat_builder_accepts_client_without_calling_create() -> None:
    client = _OpenAICompatClient([])
    provider = build_openai_compat_provider(
        "deepseek-test", base_url="https://mock.invalid/v1", client=client
    )
    assert provider.identity == ProviderIdentity("openai", "chat_completions", "deepseek-test")
    assert client.calls == []


@pytest.mark.live
@pytest.mark.skipif(
    os.environ.get("UTHCODE_RUN_LIVE") != "1",
    reason="set UTHCODE_RUN_LIVE=1 to authorize live validation",
)
@pytest.mark.asyncio
async def test_chat_live_gate_is_not_run_by_w01() -> None:
    pytest.skip("W01 performs offline Provider validation only")
