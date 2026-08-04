from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from typing import Any

import pytest
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
    ReasoningDelta,
    ReasoningOptions,
    ReasoningPart,
    RateLimitError,
    TextDelta,
    TextPart,
    ToolCallCompleted,
    ToolCallPart,
    ToolDefinition,
    ToolResultPart,
)
from uthcode.application import ProviderConfig, ProviderKind, create_application
from uthcode.integrations.providers.openai_compat import build_openai_compat_provider


class _AsyncStream:
    def __init__(self, chunks: list[Any], *, delay: float = 0) -> None:
        self._chunks = iter(chunks)
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
            return next(self._chunks)
        except StopIteration as exc:
            raise StopAsyncIteration from exc

    async def close(self) -> None:
        self.closed = True


class _OpenAICompatClient:
    def __init__(self, chunks: list[Any], *, delay: float = 0) -> None:
        self.base_url = "https://mock.invalid/v1"
        self.stream = _AsyncStream(chunks, delay=delay)
        self.calls: list[dict[str, Any]] = []
        self.error: BaseException | None = None
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    async def create(self, **kwargs: Any) -> _AsyncStream:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.stream


def _chunk(
    delta: Any,
    *,
    finish_reason: str | None = None,
    usage: CompletionUsage | None = None,
    chunk_id: str = "chunk-1",
) -> ChatCompletionChunk:
    return ChatCompletionChunk(
        id=chunk_id,
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


def _chunks(*, include_finish: bool = True) -> list[Any]:
    reasoning = ChoiceDelta.model_construct(
        role="assistant",
        content=None,
        tool_calls=None,
        reasoning_content="plan",
    )
    chunks: list[Any] = [
        _chunk(reasoning),
        _chunk(ChoiceDelta(role="assistant", content="answer")),
        _chunk(
            _tool_delta(
                0,
                call_id="call-1",
                name="search",
                arguments='{"q":',
            )
        ),
        _chunk(
            _tool_delta(
                1,
                call_id="call-2",
                name="lookup",
                arguments='{"q":',
            )
        ),
        _chunk(
            _tool_delta(0, call_id=None, name=None, arguments='"one"}'),
        ),
        _chunk(
            _tool_delta(1, call_id=None, name=None, arguments='"two"}'),
        ),
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
async def test_chat_actual_model_maps_reasoning_text_indexed_tools_and_usage() -> None:
    client = _OpenAICompatClient(_chunks())
    provider = build_openai_compat_provider(
        "deepseek-test",
        base_url="https://mock.invalid/v1",
        client=client,
    )
    request = _request(
        Message("user", (TextPart("hi"),)),
        tools=(
            ToolDefinition(
                "search",
                description="Search docs",
                parameters={"type": "object", "properties": {"q": {"type": "string"}}},
            ),
        ),
    )

    events = await _collect(provider, request)

    assert any(isinstance(event, TextDelta) and event.text == "answer" for event in events)
    completed = next(event for event in events if isinstance(event, GenerationCompleted))
    response = completed.response
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
        "reasoning_carrier",
        "assistant_text",
        "assistant_tool_call",
        "assistant_tool_call",
    ]
    assert [
        item.payload["index"]
        for item in response.native_items
        if item.kind == "assistant_tool_call"
    ] == [0, 1]
    assert sum(isinstance(event, NativeItemCompleted) for event in events) == 4
    assert client.stream.closed is True
    tool_schema = client.calls[0]["tools"]
    assert tool_schema == [
        {
            "type": "function",
            "function": {
                "name": "search",
                "description": "Search docs",
                "parameters": {
                    "type": "object",
                    "properties": {"q": {"type": "string"}},
                    "additionalProperties": False,
                },
            },
        }
    ]


@pytest.mark.asyncio
async def test_chat_history_replays_role_tool_and_never_emits_responses_items() -> None:
    client = _OpenAICompatClient(_chunks())
    provider = build_openai_compat_provider(
        "deepseek-test",
        base_url="https://mock.invalid/v1",
        client=client,
    )
    first = await _collect(provider, _request(Message("user", (TextPart("hi"),))))
    response = next(event.response for event in first if isinstance(event, GenerationCompleted))

    client.stream = _AsyncStream(_chunks())
    await _collect(
        provider,
        _request(
            Message("user", (TextPart("continue"),)),
            response.message,
            Message("tool", (ToolResultPart("call-1", "tool output"),)),
        ),
    )
    messages = client.calls[-1]["messages"]
    assistant = next(message for message in messages if message["role"] == "assistant")
    tool = next(message for message in messages if message["role"] == "tool")
    assert assistant["reasoning_content"] == "plan"
    assert assistant["tool_calls"] == [
        {
            "id": "call-1",
            "type": "function",
            "function": {"name": "search", "arguments": '{"q":"one"}'},
        },
        {
            "id": "call-2",
            "type": "function",
            "function": {"name": "lookup", "arguments": '{"q":"two"}'},
        },
    ]
    assert tool == {"role": "tool", "tool_call_id": "call-1", "content": "tool output"}
    serialized = repr(messages)
    assert "function_call_output" not in serialized
    assert "ResponseFunctionToolCall" not in serialized


@pytest.mark.asyncio
async def test_chat_missing_finish_reason_is_rejected() -> None:
    client = _OpenAICompatClient(_chunks(include_finish=False))
    provider = build_openai_compat_provider(
        "deepseek-test",
        base_url="https://mock.invalid/v1",
        client=client,
    )

    with pytest.raises(InvalidProviderResponseError):
        await _collect(provider, _request(Message("user", (TextPart("hi"),))))


class _AuthSDKError(Exception):
    status_code = 401


class _RateSDKError(Exception):
    status_code = 429


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error, expected",
    [(_AuthSDKError("auth"), AuthenticationError), (_RateSDKError("rate"), RateLimitError)],
)
async def test_chat_sdk_errors_are_mapped_without_leaking_error_text(
    error: BaseException, expected: type[BaseException]
) -> None:
    client = _OpenAICompatClient(_chunks())
    client.error = error
    provider = build_openai_compat_provider(
        "deepseek-test",
        base_url="https://mock.invalid/v1",
        client=client,
    )

    with pytest.raises(expected) as captured:
        await _collect(provider, _request(Message("user", (TextPart("hi"),))))
    assert "auth" not in str(captured.value)
    assert "rate" not in str(captured.value)


@pytest.mark.asyncio
async def test_chat_explicit_cancellation_closes_stream() -> None:
    client = _OpenAICompatClient(_chunks(), delay=0.05)
    provider = build_openai_compat_provider(
        "deepseek-test",
        base_url="https://mock.invalid/v1",
        client=client,
    )
    token = CancellationToken()
    task = asyncio.create_task(
        _collect(provider, _request(Message("user", (TextPart("hi"),))), token)
    )
    await asyncio.sleep(0.01)
    token.cancel()

    with pytest.raises(GenerationCancelled):
        await task
    assert client.stream.closed is True


_LIVE_ENABLED = (
    os.environ.get("UTHCODE_RUN_LIVE") == "1"
    and bool(os.environ.get("DEEPSEEK_API_KEY"))
)


@pytest.mark.live
@pytest.mark.skipif(
    not _LIVE_ENABLED,
    reason="set UTHCODE_RUN_LIVE=1 and DEEPSEEK_API_KEY for live validation",
)
@pytest.mark.asyncio
async def test_chat_deepseek_live_headless_text_reasoning_tools_and_continuation() -> None:
    application = create_application(
        ProviderConfig(
            kind=ProviderKind.OPENAI_COMPAT,
            model="deepseek-v4-flash",
            api_key_env="DEEPSEEK_API_KEY",
            base_url="https://api.deepseek.com",
            max_output_tokens=512,
        )
    )
    request = GenerationRequest(
        messages=(
            Message(
                "user",
                (
                    TextPart(
                        "Use the lookup tool exactly once for query 'uthcode'. "
                        "Think briefly before calling it and do not answer without the call."
                    ),
                ),
            ),
        ),
        tools=(
            ToolDefinition(
                "lookup",
                description="Look up one query.",
                parameters={
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            ),
        ),
        reasoning=ReasoningOptions(enabled=True, effort="medium"),
    )

    try:
        first = [event async for event in application.stream_generation(request)]
        first_terminal = next(event for event in first if isinstance(event, GenerationCompleted))
        calls = [event for event in first if isinstance(event, ToolCallCompleted)]
        assert any(isinstance(event, ReasoningDelta) for event in first)
        assert calls

        continuation = GenerationRequest(
            messages=(
                *request.messages,
                first_terminal.response.message,
                Message(
                    "tool",
                    tuple(
                        ToolResultPart(call.tool_call_id, "verified lookup result")
                        for call in calls
                    ),
                ),
            ),
            tools=request.tools,
            reasoning=request.reasoning,
        )
        second = [
            event
            async for event in application.stream_generation(continuation)
        ]
        second_terminal = next(event for event in second if isinstance(event, GenerationCompleted))
        assert any(isinstance(event, TextDelta) and event.text for event in first + second)
        assert second_terminal.response.finish_reason.value == "stop"
    finally:
        os.environ.pop("DEEPSEEK_API_KEY", None)
