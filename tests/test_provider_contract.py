from __future__ import annotations

import asyncio
import dataclasses
import json

import pytest

from uthcode.core.provider import (
    CancellationToken,
    FinishReason,
    GenerationCompleted,
    GenerationRequest,
    JsonPayload,
    Message,
    NativeItem,
    NativeItemCompleted,
    ProviderIdentity,
    ProviderResponse,
    ReasoningDelta,
    ReasoningOptions,
    TextDelta,
    TextPart,
    ToolCallArgumentsDelta,
    ToolCallCompleted,
    ToolCallStarted,
    ToolDefinition,
    Usage,
    provider_event_from_json,
)


def test_contract_values_are_deeply_immutable_and_json_round_trip() -> None:
    nested = {"labels": ["one"], "settings": {"enabled": True}}
    request = GenerationRequest(
        messages=(Message(role="user", parts=(TextPart("hello"),)),),
        tools=(ToolDefinition("search", parameters={"type": "object"}),),
        reasoning=ReasoningOptions(enabled=True, details={"mode": "deliberate"}),
        metadata=nested,
    )

    nested["labels"].append("mutated")
    nested["settings"]["enabled"] = False

    assert request.metadata["labels"] == ["one"]
    assert request.metadata["settings"] == {"enabled": True}
    with pytest.raises(TypeError):
        request.metadata["labels"].append("blocked")
    with pytest.raises(TypeError):
        dict.__setitem__(request.metadata, "bypass", True)
    with pytest.raises(TypeError):
        list.__setitem__(request.metadata["labels"], 0, "bypass")
    with pytest.raises(TypeError):
        request.metadata._values["bypass"] = True  # type: ignore[index]
    with pytest.raises(dataclasses.FrozenInstanceError):
        request.messages = ()  # type: ignore[misc]

    restored = GenerationRequest.from_json(request.to_json())
    assert restored == request

    response = ProviderResponse(
        message=Message(role="assistant", parts=(TextPart("done"),)),
        usage=Usage(input_tokens=2, output_tokens=3),
        finish_reason=FinishReason.STOP,
    )
    assert ProviderResponse.from_dict(response.to_dict()) == response
    assert json.loads(TextDelta("chunk").to_json()) == {
        "type": "text_delta",
        "text": "chunk",
    }


@pytest.mark.parametrize("system_prompt", [None, "Use concise Chinese."])
def test_generation_request_system_prompt_round_trip(system_prompt: str | None) -> None:
    request = GenerationRequest(
        messages=(Message(role="user", parts=(TextPart("hello"),)),),
        system_prompt=system_prompt,
    )

    assert request.to_dict()["system_prompt"] == system_prompt
    assert GenerationRequest.from_dict(request.to_dict()) == request
    assert GenerationRequest.from_json(request.to_json()) == request


@pytest.mark.parametrize("system_prompt", ["", " \n\t", 123, False, []])
def test_generation_request_rejects_blank_or_invalid_system_prompt(system_prompt: object) -> None:
    with pytest.raises((TypeError, ValueError), match="system_prompt"):
        GenerationRequest(
            messages=(Message(role="user", parts=(TextPart("hello"),)),),
            system_prompt=system_prompt,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("role", ["system", "developer", "", "USER", None, 1])
def test_message_rejects_non_core_roles(role: object) -> None:
    with pytest.raises((TypeError, ValueError), match="role"):
        Message(role=role)  # type: ignore[arg-type]


@pytest.mark.parametrize("role", ["user", "assistant", "tool"])
def test_message_accepts_only_the_three_core_roles(role: str) -> None:
    assert Message(role=role).role == role


def test_all_provider_events_have_type_safe_json_round_trip() -> None:
    native = NativeItem(
        "fake",
        "script",
        "fake-model",
        kind="trace",
        payload={"nested": [1, {"ok": True}]},
    )
    response = ProviderResponse(
        message=Message(role="assistant", parts=(TextPart("done"),)),
        usage=Usage(input_tokens=2, output_tokens=3),
        finish_reason=FinishReason.STOP,
        native_items=(native,),
    )
    events = (
        TextDelta("text"),
        ReasoningDelta("thought"),
        ToolCallStarted("call-1", "search", 2),
        ToolCallArgumentsDelta("call-1", '{"q":', 2),
        ToolCallCompleted("call-1", "search", {"q": "uth"}, 2),
        NativeItemCompleted(native),
        GenerationCompleted(response),
    )

    for event in events:
        restored = provider_event_from_json(event.to_json())
        assert restored == event
        assert json.loads(event.to_json())["type"] == event.event_type

    with pytest.raises(ValueError, match="unknown provider event type"):
        provider_event_from_json('{"type":"future_event"}')


def test_json_payload_rejects_non_json_values() -> None:
    for value in [object(), {"bad": {1, 2}}, {"bad": b"bytes"}, {"bad": float("nan")}]:
        with pytest.raises((TypeError, ValueError)):
            JsonPayload(value if isinstance(value, dict) else {"value": value})


def test_native_items_are_ordered_and_provider_specific() -> None:
    anthropic = ProviderIdentity("anthropic", "messages", "model-a")
    responses = ProviderIdentity("openai", "responses", "model-b")
    items = (
        NativeItem(
            "anthropic",
            "messages",
            "model-a",
            sequence_index=0,
            kind="thinking",
            payload={"text": "x"},
        ),
        NativeItem(
            "openai",
            "responses",
            "model-b",
            sequence_index=1,
            kind="reasoning",
            payload={"summary": "y"},
        ),
    )
    message = Message(role="assistant", native_items=items)

    assert message.native_items_for(anthropic) == (items[0],)
    assert message.native_items_for(responses) == (items[1],)
    assert [item.sequence_index for item in message.native_items] == [0, 1]
    assert NativeItem.from_dict(items[0].to_dict()) == items[0]


@pytest.mark.asyncio
async def test_cancellation_is_idempotent_and_wakes_all_waiters() -> None:
    token = CancellationToken()
    waiters = [asyncio.create_task(token.wait()) for _ in range(3)]
    await asyncio.sleep(0)

    assert token.cancel() is True
    assert token.cancel() is False
    await asyncio.wait_for(asyncio.gather(*waiters), timeout=1)
    assert token.cancelled is True
    assert token.is_cancelled is True
