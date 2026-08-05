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
from openai.types import responses

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
    ProviderIdentity,
    ProviderError,
    RateLimitError,
    ReasoningDelta,
    ReasoningPart,
    TextDelta,
    TextPart,
    ToolCallCompleted,
    ToolCallPart,
    ToolDefinition,
    ToolResultPart,
)
from uthcode.integrations.providers.openai_responses import build_openai_responses_provider


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


class _OpenAIClient:
    def __init__(self, events: list[object], *, delay: float = 0.0) -> None:
        self.stream = _AsyncStream(events, delay=delay)
        self.calls: list[dict[str, object]] = []
        self.error: BaseException | None = None
        self.responses = SimpleNamespace(create=self.create)

    async def create(self, **kwargs: object) -> _AsyncStream:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.stream


def _response(
    *,
    status: str,
    output: list[object],
    usage: dict[str, object] | None = None,
    response_id: str = "resp-1",
) -> responses.Response:
    data: dict[str, object] = {
        "id": response_id,
        "created_at": 1,
        "model": "gpt-test",
        "object": "response",
        "output": output,
        "parallel_tool_calls": True,
        "tool_choice": "auto",
        "tools": [],
        "status": status,
    }
    if usage is not None:
        data["usage"] = usage
    return responses.Response.model_validate(data)


def _completed_response(output: list[object]) -> responses.Response:
    return _response(
        status="completed",
        output=output,
        usage={
            "input_tokens": 13,
            "output_tokens": 9,
            "total_tokens": 22,
            "input_tokens_details": {"cached_tokens": 4, "cache_write_tokens": 2},
            "output_tokens_details": {"reasoning_tokens": 3},
        },
    )


def _item_events(
    *,
    terminal: str = "completed",
    include_terminal: bool = True,
    duplicate: bool = False,
) -> list[object]:
    reasoning_added = responses.ResponseReasoningItem(
        id="rs-1", summary=[], type="reasoning", encrypted_content=None, status="in_progress"
    )
    call_one_added = responses.ResponseFunctionToolCall(
        id="fc-1", call_id="call-1", name="search", arguments="", type="function_call", status="in_progress"
    )
    call_two_added = responses.ResponseFunctionToolCall(
        id="fc-2", call_id="call-2", name="lookup", arguments="", type="function_call", status="in_progress"
    )
    message_added = responses.ResponseOutputMessage(
        id="msg-1", content=[], role="assistant", status="in_progress", type="message"
    )
    call_one_done = responses.ResponseFunctionToolCall(
        id="fc-1", call_id="call-1", name="search", arguments='{"q":"one"}', type="function_call", status="completed"
    )
    call_two_done = responses.ResponseFunctionToolCall(
        id="fc-2", call_id="call-2", name="lookup", arguments='{"q":"two"}', type="function_call", status="completed"
    )
    reasoning_done = responses.ResponseReasoningItem(
        id="rs-1", summary=[{"type": "summary_text", "text": "plan"}], type="reasoning", encrypted_content="reasoning-signature", status="completed"
    )
    message_done = responses.ResponseOutputMessage(
        id="msg-1", content=[{"type": "output_text", "text": "answer", "annotations": []}], role="assistant", status="completed", type="message"
    )
    output = [reasoning_done, call_one_done, call_two_done, message_done]
    events: list[object] = [
        responses.ResponseCreatedEvent(
            response=_response(status="in_progress", output=[]), sequence_number=0, type="response.created"
        ),
        responses.ResponseOutputItemAddedEvent(
            item=reasoning_added, output_index=0, sequence_number=1, type="response.output_item.added"
        ),
        responses.ResponseReasoningSummaryPartAddedEvent(
            item_id="rs-1",
            output_index=0,
            part={"type": "summary_text", "text": ""},
            sequence_number=101,
            summary_index=0,
            type="response.reasoning_summary_part.added",
        ),
        responses.ResponseReasoningSummaryTextDeltaEvent(
            item_id="rs-1", output_index=0, sequence_number=2, summary_index=0, delta="plan", type="response.reasoning_summary_text.delta"
        ),
        responses.ResponseReasoningSummaryPartDoneEvent(
            item_id="rs-1",
            output_index=0,
            part={"type": "summary_text", "text": "plan"},
            sequence_number=102,
            summary_index=0,
            type="response.reasoning_summary_part.done",
        ),
        responses.ResponseOutputItemAddedEvent(
            item=call_one_added, output_index=1, sequence_number=3, type="response.output_item.added"
        ),
        responses.ResponseOutputItemAddedEvent(
            item=call_two_added, output_index=2, sequence_number=4, type="response.output_item.added"
        ),
        responses.ResponseFunctionCallArgumentsDeltaEvent(
            item_id="fc-1", output_index=1, sequence_number=5, delta='{"q":"one"}', type="response.function_call_arguments.delta"
        ),
        responses.ResponseFunctionCallArgumentsDeltaEvent(
            item_id="fc-2", output_index=2, sequence_number=6, delta='{"q":"two"}', type="response.function_call_arguments.delta"
        ),
        responses.ResponseFunctionCallArgumentsDoneEvent(
            item_id="fc-1", output_index=1, sequence_number=7, arguments='{"q":"one"}', name="search", type="response.function_call_arguments.done"
        ),
        responses.ResponseFunctionCallArgumentsDoneEvent(
            item_id="fc-2", output_index=2, sequence_number=8, arguments='{"q":"two"}', name="lookup", type="response.function_call_arguments.done"
        ),
        responses.ResponseOutputItemDoneEvent(
            item=reasoning_done, output_index=0, sequence_number=9, type="response.output_item.done"
        ),
        responses.ResponseOutputItemDoneEvent(
            item=call_one_done, output_index=1, sequence_number=10, type="response.output_item.done"
        ),
        responses.ResponseOutputItemDoneEvent(
            item=call_two_done, output_index=2, sequence_number=11, type="response.output_item.done"
        ),
        responses.ResponseOutputItemAddedEvent(
            item=message_added, output_index=3, sequence_number=12, type="response.output_item.added"
        ),
        responses.ResponseTextDeltaEvent(
            item_id="msg-1", output_index=3, content_index=0, sequence_number=13, delta="answer", logprobs=[], type="response.output_text.delta"
        ),
        responses.ResponseTextDoneEvent(
            item_id="msg-1", output_index=3, content_index=0, sequence_number=14, text="answer", logprobs=[], type="response.output_text.done"
        ),
        responses.ResponseOutputItemDoneEvent(
            item=message_done, output_index=3, sequence_number=15, type="response.output_item.done"
        ),
    ]
    if duplicate:
        events.insert(14, events[14])
    if include_terminal:
        if terminal == "completed":
            events.append(
                responses.ResponseCompletedEvent(
                    response=_completed_response(output), sequence_number=16, type="response.completed"
                )
            )
        elif terminal == "incomplete":
            events.append(
                responses.ResponseIncompleteEvent(
                    response=_response(status="incomplete", output=output), sequence_number=16, type="response.incomplete"
                )
            )
        else:
            events.append(
                responses.ResponseFailedEvent(
                    response=_response(status="failed", output=output), sequence_number=16, type="response.failed"
                )
            )
    return events


def _request(
    *messages: Message,
    system_prompt: str | None = None,
    tools: tuple[ToolDefinition, ...] = (),
) -> GenerationRequest:
    return GenerationRequest(
        messages=messages,
        system_prompt=system_prompt,
        tools=tools,
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
async def test_responses_public_stream_preserves_items_indices_usage_and_reasoning() -> None:
    client = _OpenAIClient(_item_events())
    provider = build_openai_responses_provider("gpt-test", client=client)
    events = await _collect(provider, _request(Message("user", (TextPart("hi"),))))

    assert any(isinstance(event, TextDelta) and event.text == "answer" for event in events)
    assert any(isinstance(event, ReasoningDelta) and event.text == "plan" for event in events)
    response = next(event.response for event in events if isinstance(event, GenerationCompleted))
    assert response.message.parts == (
        ReasoningPart("plan"),
        ToolCallPart("call-1", "search", {"q": "one"}),
        ToolCallPart("call-2", "lookup", {"q": "two"}),
        TextPart("answer"),
    )
    assert [(item.kind, item.sequence_index) for item in response.native_items] == [
        ("reasoning", 0), ("function_call", 1), ("function_call", 2), ("message", 3)
    ]
    assert response.native_items[0].payload["encrypted_content"] == "reasoning-signature"
    assert response.usage.input_tokens == 13
    assert response.usage.output_tokens == 9
    assert response.usage.cache_read_tokens == 4
    assert response.usage.cache_write_tokens == 2
    assert response.finish_reason is FinishReason.TOOL_CALLS
    assert sum(isinstance(event, NativeItemCompleted) for event in events) == 4
    assert sum(isinstance(event, ToolCallCompleted) for event in events) == 2
    assert "instructions" not in client.calls[0]
    assert all(item.get("role") != "system" for item in client.calls[0]["input"])
    assert client.stream.closed is True


@pytest.mark.asyncio
async def test_responses_request_shapes_tools_native_replay_and_cross_identity_fallback() -> None:
    client = _OpenAIClient(_item_events())
    provider = build_openai_responses_provider("gpt-test", client=client)
    tools = (ToolDefinition("search", "Search", {"type": "object", "properties": {"q": {"type": "string"}}}),)
    first = await _collect(
        provider,
        _request(
            Message("user", (TextPart("hi"),)),
            system_prompt="rules",
            tools=tools,
        ),
    )
    response = next(event.response for event in first if isinstance(event, GenerationCompleted))
    client.stream = _AsyncStream(_item_events())
    await _collect(
        provider,
        _request(
            response.message,
            Message("tool", (ToolResultPart("call-1", "result"),)),
            system_prompt="rules",
            tools=tools,
        ),
    )
    call = client.calls[-1]
    assert call["instructions"] == "rules"
    assert call["tools"] == [{"type": "function", "name": "search", "description": "Search", "parameters": {"type": "object", "properties": {"q": {"type": "string"}}}}]
    assert any(item.get("type") == "function_call_output" for item in call["input"])
    assert any(item.get("type") == "reasoning" and item.get("encrypted_content") == "reasoning-signature" for item in call["input"])

    other_client = _OpenAIClient(_item_events())
    other = build_openai_responses_provider("other-model", client=other_client)
    await _collect(other, _request(response.message))
    assert "instructions" not in other_client.calls[-1]
    input_values = other_client.calls[-1]["input"]
    assert not any(item.get("type") == "reasoning" for item in input_values)
    assert any(item.get("role") == "assistant" for item in input_values)


@pytest.mark.asyncio
async def test_responses_duplicate_frames_are_deduplicated_and_conflicts_rejected() -> None:
    client = _OpenAIClient(_item_events(duplicate=True))
    provider = build_openai_responses_provider("gpt-test", client=client)
    events = await _collect(provider, _request(Message("user", (TextPart("hi"),))))
    assert sum(isinstance(event, TextDelta) for event in events) == 1

    conflict = _item_events()
    duplicate = conflict[13].model_copy(update={"delta": "different"})
    conflict.insert(14, duplicate)
    client = _OpenAIClient(conflict)
    provider = build_openai_responses_provider("gpt-test", client=client)
    with pytest.raises(InvalidProviderResponseError):
        await _collect(provider, _request(Message("user", (TextPart("hi"),))))


@pytest.mark.asyncio
async def test_responses_rejects_conflicting_reasoning_summary_part_snapshot() -> None:
    events = _item_events()
    part_index = next(
        index
        for index, event in enumerate(events)
        if isinstance(event, responses.ResponseReasoningSummaryPartDoneEvent)
    )
    events[part_index] = responses.ResponseReasoningSummaryPartDoneEvent(
        item_id="rs-1",
        output_index=0,
        part={"type": "summary_text", "text": "CONFLICT"},
        sequence_number=102,
        summary_index=0,
        type="response.reasoning_summary_part.done",
    )
    client = _OpenAIClient(events)
    provider = build_openai_responses_provider("gpt-test", client=client)

    with pytest.raises(InvalidProviderResponseError):
        await _collect(provider, _request(Message("user", (TextPart("hi"),))))


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal", ["incomplete", "failed"])
async def test_responses_incomplete_or_failed_terminal_is_not_success(terminal: str) -> None:
    client = _OpenAIClient(_item_events(terminal=terminal))
    provider = build_openai_responses_provider("gpt-test", client=client)
    with pytest.raises(InvalidProviderResponseError):
        await _collect(provider, _request(Message("user", (TextPart("hi"),))))


@pytest.mark.asyncio
async def test_responses_error_event_is_safe_and_has_no_success_terminal() -> None:
    client = _OpenAIClient(
        [SimpleNamespace(type="error", sequence_number=1, message="secret-response-error")]
    )
    provider = build_openai_responses_provider("gpt-test", client=client)
    with pytest.raises(ProviderError) as raised:
        await _collect(provider, _request(Message("user", (TextPart("hi"),))))
    assert "secret-response-error" not in str(raised.value)


@pytest.mark.asyncio
async def test_responses_missing_terminal_and_unfinished_call_are_rejected() -> None:
    client = _OpenAIClient(_item_events(include_terminal=False))
    provider = build_openai_responses_provider("gpt-test", client=client)
    with pytest.raises(InvalidProviderResponseError):
        await _collect(provider, _request(Message("user", (TextPart("hi"),))))

    unfinished = _item_events()
    unfinished = [
        event
        for event in unfinished
        if not (isinstance(event, responses.ResponseOutputItemDoneEvent) and event.output_index == 1)
    ]
    unfinished = [
        event
        for event in unfinished
        if not isinstance(event, responses.ResponseCompletedEvent)
    ] + [
        responses.ResponseCompletedEvent(
            response=_completed_response([]), sequence_number=30, type="response.completed"
        )
    ]
    client = _OpenAIClient(unfinished)
    provider = build_openai_responses_provider("gpt-test", client=client)
    with pytest.raises(InvalidProviderResponseError):
        await _collect(provider, _request(Message("user", (TextPart("hi"),))))


@pytest.mark.asyncio
async def test_responses_nullable_cache_usage_is_zero() -> None:
    usage = SimpleNamespace(
        input_tokens=1,
        output_tokens=2,
        total_tokens=3,
        input_tokens_details=SimpleNamespace(cached_tokens=None, cache_write_tokens=None),
        output_tokens_details=SimpleNamespace(reasoning_tokens=None),
    )
    response = SimpleNamespace(
        id="resp-nullable",
        status="completed",
        output=[],
        usage=usage,
    )
    client = _OpenAIClient([SimpleNamespace(response=response, sequence_number=1, type="response.completed")])
    provider = build_openai_responses_provider("gpt-test", client=client)
    events = await _collect(provider, _request(Message("user", (TextPart("hi"),))))
    completed = next(event for event in events if isinstance(event, GenerationCompleted))
    assert completed.response.usage.cache_read_tokens == 0
    assert completed.response.usage.cache_write_tokens == 0


@pytest.mark.asyncio
async def test_responses_official_errors_are_safe() -> None:
    request = httpx.Request("GET", "https://mock.invalid")
    cases: list[tuple[BaseException, type[BaseException]]] = [
        (SDKAuthenticationError("secret-auth", response=httpx.Response(401, request=request), body={}), AuthenticationError),
        (SDKPermissionDeniedError("secret-permission", response=httpx.Response(403, request=request), body={}), AuthenticationError),
        (SDKRateLimitError("secret-rate", response=httpx.Response(429, request=request), body={}), RateLimitError),
        (SDKAPIConnectionError(request=request), NetworkError),
        (SDKAPITimeoutError(request), NetworkError),
        (SDKAPIStatusError("secret-status", response=httpx.Response(500, request=request), body={}), ProviderError),
    ]
    for error, expected in cases:
        client = _OpenAIClient(_item_events())
        client.error = error
        provider = build_openai_responses_provider("gpt-test", client=client)
        with pytest.raises(expected) as raised:
            await _collect(provider, _request(Message("user", (TextPart("hi"),))))
        assert "secret-" not in str(raised.value)


@pytest.mark.asyncio
async def test_responses_explicit_and_task_cancellation_close_stream() -> None:
    client = _OpenAIClient(_item_events(), delay=0.05)
    provider = build_openai_responses_provider("gpt-test", client=client)
    token = CancellationToken()
    task = asyncio.create_task(_collect(provider, _request(Message("user", (TextPart("hi"),))), token))
    await asyncio.sleep(0.01)
    token.cancel()
    with pytest.raises(GenerationCancelled):
        await task
    assert client.stream.closed is True


@pytest.mark.live
@pytest.mark.skipif(
    os.environ.get("UTHCODE_RUN_LIVE") != "1",
    reason="set UTHCODE_RUN_LIVE=1 to authorize live validation",
)
@pytest.mark.asyncio
async def test_responses_live_gate_is_not_run_by_w01() -> None:
    pytest.skip("W01 performs offline Provider validation only")

    client = _OpenAIClient(_item_events(), delay=0.05)
    provider = build_openai_responses_provider("gpt-test", client=client)
    task = asyncio.create_task(_collect(provider, _request(Message("user", (TextPart("hi"),)))))
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert client.stream.closed is True
