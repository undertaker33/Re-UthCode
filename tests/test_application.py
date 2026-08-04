from __future__ import annotations

import asyncio
import socket

import pytest

from uthcode.application import (
    ProviderConfig,
    ProviderKind,
    UthCodeApplication,
    create_application,
)
from uthcode.core.provider import (
    CancellationToken,
    FinishReason,
    GenerationCancelled,
    GenerationCompleted,
    GenerationRequest,
    InvalidProviderResponseError,
    Message,
    ProviderResponse,
    TextDelta,
    TextPart,
    ToolCallArgumentsDelta,
    ToolCallCompleted,
    ToolCallStarted,
    Usage,
)
from uthcode.integrations.providers.fake import FakeProvider


def _request() -> GenerationRequest:
    return GenerationRequest(messages=(Message("user", (TextPart("hello"),)),))


def _completed() -> GenerationCompleted:
    return GenerationCompleted(
        ProviderResponse(
            message=Message("assistant", (TextPart("done"),)),
            usage=Usage(input_tokens=4, output_tokens=2),
            finish_reason=FinishReason.STOP,
        )
    )


async def _collect(application: UthCodeApplication, token: CancellationToken | None = None) -> list[object]:
    return [
        event
        async for event in application.stream_generation(_request(), cancellation=token)
    ]


def test_offline_guard_blocks_network_construction() -> None:
    with pytest.raises(AssertionError, match="real network access is forbidden"):
        socket.create_connection(("example.invalid", 443))


@pytest.mark.asyncio
async def test_headless_application_streams_text_usage_and_one_terminal_event() -> None:
    provider = FakeProvider(events=(TextDelta("hel"), TextDelta("lo"), _completed()))
    application = UthCodeApplication(provider)

    events = await _collect(application)

    assert [type(event) for event in events] == [
        TextDelta,
        TextDelta,
        GenerationCompleted,
    ]
    assert events[-1].response.usage.total_tokens == 6  # type: ignore[union-attr]
    assert sum(isinstance(event, GenerationCompleted) for event in events) == 1
    assert len(provider.recorded_requests) == 1


@pytest.mark.asyncio
async def test_formal_bootstrap_builds_a_fake_headless_application() -> None:
    application = create_application(
        ProviderConfig(kind=ProviderKind.FAKE, model="bootstrap-fake")
    )

    events = await _collect(application)

    assert isinstance(application, UthCodeApplication)
    assert application.provider.identity.model == "bootstrap-fake"
    assert isinstance(events[-1], GenerationCompleted)
    assert sum(isinstance(event, GenerationCompleted) for event in events) == 1


@pytest.mark.asyncio
async def test_tool_call_events_keep_script_order() -> None:
    events = await _collect(
        UthCodeApplication(
            FakeProvider(
                events=(
                    ToolCallStarted("call-1", "search"),
                    ToolCallArgumentsDelta("call-1", '{"q":'),
                    ToolCallArgumentsDelta("call-1", '"uth"}'),
                    ToolCallCompleted("call-1", "search", {"q": "uth"}),
                    _completed(),
                )
            )
        )
    )

    assert [type(event) for event in events] == [
        ToolCallStarted,
        ToolCallArgumentsDelta,
        ToolCallArgumentsDelta,
        ToolCallCompleted,
        GenerationCompleted,
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "script",
    [
        (TextDelta("missing-terminal"),),
        (_completed(), _completed()),
        (_completed(), TextDelta("after-terminal")),
    ],
)
async def test_invalid_terminal_shapes_are_rejected(script: tuple[object, ...]) -> None:
    provider = FakeProvider(events=script)  # type: ignore[arg-type]
    observed: list[object] = []

    with pytest.raises(InvalidProviderResponseError):
        async for event in UthCodeApplication(provider).stream_generation(_request()):
            observed.append(event)

    assert not any(isinstance(event, GenerationCompleted) for event in observed)


@pytest.mark.asyncio
async def test_explicit_cancellation_is_distinct_from_task_cancellation() -> None:
    token = CancellationToken()
    application = UthCodeApplication(FakeProvider(events=(_completed(),), delay=10))
    task = asyncio.create_task(_collect(application, token))
    await asyncio.sleep(0.05)
    token.cancel()

    with pytest.raises(GenerationCancelled):
        await task

    task_cancelled = asyncio.create_task(
        _collect(UthCodeApplication(FakeProvider(events=(_completed(),), delay=10)))
    )
    await asyncio.sleep(0.05)
    task_cancelled.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task_cancelled
