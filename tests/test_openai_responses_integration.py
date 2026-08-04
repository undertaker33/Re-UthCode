from __future__ import annotations

import asyncio
import copy
import os
from types import SimpleNamespace
from typing import Any

import pytest
from openai.types import responses

from uthcode.core.provider import (
    CancellationToken,
    FinishReason,
    GenerationCancelled,
    GenerationCompleted,
    GenerationRequest,
    InvalidProviderResponseError,
    Message,
    NativeItemCompleted,
    ProviderIdentity,
    ReasoningDelta,
    ReasoningOptions,
    ReasoningPart,
    TextDelta,
    TextPart,
    ToolCallCompleted,
    ToolCallPart,
    ToolDefinition,
    ToolResultPart,
)
from uthcode.application import ProviderConfig, ProviderKind, create_application
from uthcode.integrations.providers.openai_responses import (
    OpenAIResponsesCodec,
    build_openai_responses_provider,
)


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


class _OpenAIClient:
    def __init__(self, events: list[Any], *, delay: float = 0) -> None:
        self.base_url = "https://mock.invalid/v1"
        self.stream = _AsyncStream(events, delay=delay)
        self.calls: list[dict[str, Any]] = []
        self.error: BaseException | None = None
        self.responses = SimpleNamespace(create=self.create)

    async def create(self, **kwargs: Any) -> _AsyncStream:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.stream


def _response(
    *,
    status: str,
    output: list[Any],
    usage: dict[str, Any] | None = None,
    response_id: str = "resp-1",
) -> responses.Response:
    data: dict[str, Any] = {
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


def _completed_response(output: list[Any]) -> responses.Response:
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


def _item_events(*, terminal: str = "completed", include_terminal: bool = True) -> list[Any]:
    reasoning_added = responses.ResponseReasoningItem(
        id="rs-1",
        summary=[],
        type="reasoning",
        encrypted_content=None,
        status="in_progress",
    )
    call_one_added = responses.ResponseFunctionToolCall(
        id="fc-1",
        call_id="call-1",
        name="search",
        arguments="",
        type="function_call",
        status="in_progress",
    )
    call_two_added = responses.ResponseFunctionToolCall(
        id="fc-2",
        call_id="call-2",
        name="lookup",
        arguments="",
        type="function_call",
        status="in_progress",
    )
    message_added = responses.ResponseOutputMessage(
        id="msg-1",
        content=[],
        role="assistant",
        status="in_progress",
        type="message",
    )
    call_one_done = responses.ResponseFunctionToolCall(
        id="fc-1",
        call_id="call-1",
        name="search",
        arguments='{"q":"one"}',
        type="function_call",
        status="completed",
    )
    call_two_done = responses.ResponseFunctionToolCall(
        id="fc-2",
        call_id="call-2",
        name="lookup",
        arguments='{"q":"two"}',
        type="function_call",
        status="completed",
    )
    reasoning_done = responses.ResponseReasoningItem(
        id="rs-1",
        summary=[{"type": "summary_text", "text": "plan"}],
        type="reasoning",
        encrypted_content="reasoning-signature",
        status="completed",
    )
    message_done = responses.ResponseOutputMessage(
        id="msg-1",
        content=[{"type": "output_text", "text": "answer", "annotations": []}],
        role="assistant",
        status="completed",
        type="message",
    )
    output = [reasoning_done, call_one_done, call_two_done, message_done]
    events: list[Any] = [
        responses.ResponseCreatedEvent(
            response=_response(status="in_progress", output=[]),
            sequence_number=0,
            type="response.created",
        ),
        responses.ResponseOutputItemAddedEvent(
            item=reasoning_added,
            output_index=0,
            sequence_number=1,
            type="response.output_item.added",
        ),
        responses.ResponseReasoningSummaryTextDeltaEvent(
            item_id="rs-1",
            output_index=0,
            sequence_number=2,
            summary_index=0,
            delta="plan",
            type="response.reasoning_summary_text.delta",
        ),
        responses.ResponseOutputItemAddedEvent(
            item=call_one_added,
            output_index=1,
            sequence_number=3,
            type="response.output_item.added",
        ),
        responses.ResponseOutputItemAddedEvent(
            item=call_two_added,
            output_index=2,
            sequence_number=4,
            type="response.output_item.added",
        ),
        responses.ResponseFunctionCallArgumentsDeltaEvent(
            item_id="fc-1",
            output_index=1,
            sequence_number=5,
            delta='{"q":"one"}',
            type="response.function_call_arguments.delta",
        ),
        responses.ResponseFunctionCallArgumentsDeltaEvent(
            item_id="fc-2",
            output_index=2,
            sequence_number=6,
            delta='{"q":"two"}',
            type="response.function_call_arguments.delta",
        ),
        responses.ResponseFunctionCallArgumentsDoneEvent(
            item_id="fc-1",
            output_index=1,
            sequence_number=7,
            arguments='{"q":"one"}',
            name="search",
            type="response.function_call_arguments.done",
        ),
        responses.ResponseFunctionCallArgumentsDoneEvent(
            item_id="fc-2",
            output_index=2,
            sequence_number=8,
            arguments='{"q":"two"}',
            name="lookup",
            type="response.function_call_arguments.done",
        ),
        responses.ResponseOutputItemDoneEvent(
            item=reasoning_done,
            output_index=0,
            sequence_number=9,
            type="response.output_item.done",
        ),
        responses.ResponseOutputItemDoneEvent(
            item=call_one_done,
            output_index=1,
            sequence_number=10,
            type="response.output_item.done",
        ),
        responses.ResponseOutputItemDoneEvent(
            item=call_two_done,
            output_index=2,
            sequence_number=11,
            type="response.output_item.done",
        ),
        responses.ResponseOutputItemAddedEvent(
            item=message_added,
            output_index=3,
            sequence_number=12,
            type="response.output_item.added",
        ),
        responses.ResponseTextDeltaEvent(
            item_id="msg-1",
            output_index=3,
            content_index=0,
            sequence_number=13,
            delta="answer",
            logprobs=[],
            type="response.output_text.delta",
        ),
        responses.ResponseTextDoneEvent(
            item_id="msg-1",
            output_index=3,
            content_index=0,
            sequence_number=14,
            text="answer",
            logprobs=[],
            type="response.output_text.done",
        ),
        responses.ResponseOutputItemDoneEvent(
            item=message_done,
            output_index=3,
            sequence_number=15,
            type="response.output_item.done",
        ),
    ]
    if include_terminal:
        terminal_response = _completed_response(output)
        if terminal == "completed":
            events.append(
                responses.ResponseCompletedEvent(
                    response=terminal_response,
                    sequence_number=16,
                    type="response.completed",
                )
            )
        elif terminal == "incomplete":
            events.append(
                responses.ResponseIncompleteEvent(
                    response=_response(status="incomplete", output=output),
                    sequence_number=16,
                    type="response.incomplete",
                )
            )
        else:
            events.append(
                responses.ResponseFailedEvent(
                    response=_response(status="failed", output=output),
                    sequence_number=16,
                    type="response.failed",
                )
            )
    return events


def _request(*messages: Message) -> GenerationRequest:
    return GenerationRequest(messages=messages)


async def _collect(provider: Any, request: GenerationRequest, token: CancellationToken | None = None) -> list[Any]:
    return [
        event
        async for event in provider.stream(
            request,
            cancellation=token or CancellationToken(),
        )
    ]


@pytest.mark.asyncio
async def test_responses_actual_model_preserves_items_indices_and_usage() -> None:
    client = _OpenAIClient(_item_events())
    provider = build_openai_responses_provider("gpt-test", client=client)

    events = await _collect(provider, _request(Message("user", (TextPart("hi"),))))

    assert any(isinstance(event, TextDelta) and event.text == "answer" for event in events)
    completed = next(event for event in events if isinstance(event, GenerationCompleted))
    response = completed.response
    assert response.message.parts == (
        ReasoningPart("plan"),
        ToolCallPart("call-1", "search", {"q": "one"}),
        ToolCallPart("call-2", "lookup", {"q": "two"}),
        TextPart("answer"),
    )
    assert [(item.kind, item.sequence_index) for item in response.native_items] == [
        ("reasoning", 0),
        ("function_call", 1),
        ("function_call", 2),
        ("message", 3),
    ]
    assert response.native_items[0].payload["encrypted_content"] == "reasoning-signature"
    assert response.usage.input_tokens == 13
    assert response.usage.output_tokens == 9
    assert response.usage.cache_read_tokens == 4
    assert response.finish_reason is FinishReason.STOP
    assert sum(isinstance(event, NativeItemCompleted) for event in events) == 4
    assert client.stream.closed is True


def test_responses_nullable_cache_usage_is_normalized_to_zero() -> None:
    class _Usage:
        def model_dump(self, *, mode: str) -> dict[str, Any]:
            del mode
            return {
                "input_tokens": 1,
                "output_tokens": 2,
                "total_tokens": 3,
                "input_tokens_details": {
                    "cached_tokens": None,
                    "cache_write_tokens": None,
                },
            }

    terminal = type(
        "ResponseCompletedEvent",
        (),
        {"response": SimpleNamespace(usage=_Usage())},
    )()
    codec = OpenAIResponsesCodec()
    codec._recorder = SimpleNamespace(events=[terminal])  # type: ignore[attr-defined]

    usage = codec.usage_from_model_response(None)

    assert usage is not None
    assert usage.cache_read_tokens == 0
    assert usage.cache_write_tokens == 0


@pytest.mark.asyncio
async def test_responses_duplicate_delta_done_and_terminal_frames_are_deduplicated() -> None:
    events = _item_events()
    terminal = events.pop()
    events.extend([copy.deepcopy(events[5]), copy.deepcopy(events[9]), terminal, copy.deepcopy(terminal)])
    client = _OpenAIClient(events)
    provider = build_openai_responses_provider("gpt-test", client=client)

    observed = await _collect(provider, _request(Message("user", (TextPart("hi"),))))

    completed = next(event for event in observed if isinstance(event, GenerationCompleted))
    assert completed.response.message.parts[1] == ToolCallPart("call-1", "search", {"q": "one"})
    assert sum(isinstance(event, GenerationCompleted) for event in observed) == 1


@pytest.mark.asyncio
async def test_responses_conflicting_duplicate_frame_is_rejected() -> None:
    events = _item_events()
    terminal = events.pop()
    conflict = events[5].model_copy(update={"delta": '{"q":"different"}'})
    events.extend([conflict, terminal])
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
async def test_responses_missing_terminal_and_unfinished_call_are_rejected() -> None:
    missing_terminal = _OpenAIClient(_item_events(include_terminal=False))
    provider = build_openai_responses_provider("gpt-test", client=missing_terminal)
    with pytest.raises(InvalidProviderResponseError):
        await _collect(provider, _request(Message("user", (TextPart("hi"),))))

    events = _item_events()
    terminal = events.pop()
    events = [
        event
        for event in events
        if not (
            type(event).__name__ == "ResponseOutputItemDoneEvent"
            and getattr(getattr(event, "item", None), "id", None) == "fc-1"
        )
    ]
    events.append(terminal)
    unfinished = _OpenAIClient(events)
    provider = build_openai_responses_provider("gpt-test", client=unfinished)
    with pytest.raises(InvalidProviderResponseError):
        await _collect(provider, _request(Message("user", (TextPart("hi"),))))


@pytest.mark.asyncio
async def test_responses_history_replays_reasoning_calls_and_function_call_output() -> None:
    client = _OpenAIClient(_item_events())
    provider = build_openai_responses_provider("gpt-test", client=client)
    first = await _collect(provider, _request(Message("user", (TextPart("hi"),))))
    response = next(event.response for event in first if isinstance(event, GenerationCompleted))

    client.stream = _AsyncStream(_item_events())
    await _collect(
        provider,
        _request(
            Message("user", (TextPart("continue"),)),
            response.message,
            Message("tool", (ToolResultPart("call-1", "tool output"),)),
        ),
    )
    inputs = client.calls[-1]["input"]
    assert any(item.get("type") == "reasoning" for item in inputs)
    assert any(item.get("type") == "function_call" and item.get("call_id") == "call-1" for item in inputs)
    assert any(
        item.get("type") == "function_call_output"
        and item.get("call_id") == "call-1"
        and item.get("output") == "tool output"
        for item in inputs
    )
    assert any(item.get("encrypted_content") == "reasoning-signature" for item in inputs)


@pytest.mark.asyncio
async def test_responses_native_items_are_filtered_for_another_identity() -> None:
    client = _OpenAIClient(_item_events())
    provider = build_openai_responses_provider("gpt-test", client=client)
    first = await _collect(provider, _request(Message("user", (TextPart("hi"),))))
    response = next(event.response for event in first if isinstance(event, GenerationCompleted))

    other = ProviderIdentity("openai", "chat_completions", "other-model")
    encoded = OpenAIResponsesCodec().encode_message(response.message, other)
    assert response.message.native_items_for(other) == ()
    assert getattr(encoded.parts[0], "signature", None) is None
    assert not any(getattr(part, "id", None) == "rs-1" for part in encoded.parts)


@pytest.mark.asyncio
async def test_responses_explicit_cancellation_closes_stream() -> None:
    client = _OpenAIClient(_item_events(), delay=0.05)
    provider = build_openai_responses_provider("gpt-test", client=client)
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
async def test_responses_deepseek_live_headless_text_reasoning_tools_and_continuation() -> None:
    application = create_application(
        ProviderConfig(
            kind=ProviderKind.OPENAI_RESPONSES,
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
        reasoning_observed = (
            any(isinstance(event, ReasoningDelta) for event in first)
            or any(
                isinstance(part, ReasoningPart)
                for part in first_terminal.response.message.parts
            )
            or any(item.kind == "reasoning" for item in first_terminal.response.native_items)
        )
        assert reasoning_observed
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
