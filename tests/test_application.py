from __future__ import annotations

import asyncio
import socket

import pytest

from uthcode.application import (
    ApplicationContextService,
    ApplicationRuntimeContext,
    EffectiveConfig,
    ProviderKind,
    UthCodeApplication,
    create_application,
)
from uthcode.core.provider import (
    FinishReason,
    GenerationCancelled,
    GenerationCompleted,
    GenerationRequest,
    InvalidProviderResponseError,
    Message,
    ModelLimits,
    ProviderIdentity,
    ProviderResponse,
    TextDelta,
    TextPart,
    ToolCallArgumentsDelta,
    ToolCallCompleted,
    ToolCallStarted,
    Usage,
)
from uthcode.integrations.providers.fake import FakeProvider


TEST_LIMITS = ModelLimits(max_input_tokens=1_000_000, source="test.fake")


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


async def _collect(application: UthCodeApplication) -> list[object]:
    return [
        event
        async for event in application.stream_generation(_request())
    ]


def test_offline_guard_blocks_network_construction() -> None:
    with pytest.raises(AssertionError, match="real network access is forbidden"):
        socket.create_connection(("example.invalid", 443))


@pytest.mark.asyncio
async def test_headless_application_streams_text_usage_and_one_terminal_event() -> None:
    provider = FakeProvider(
        events=(TextDelta("hel"), TextDelta("lo"), _completed()),
        model_limits=TEST_LIMITS,
    )
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
async def test_application_injects_authoritative_prompt_without_mutating_request(
    tmp_path,
) -> None:
    context = ApplicationRuntimeContext.from_system(
        workdir=tmp_path / "project",
        platform_name="TestOS",
        platform_release="1.0",
        current_date="2026-08-05",
    )
    provider = FakeProvider(
        identity=ProviderIdentity("fake", "test-protocol", "remote-model"),
        events=(_completed(),),
        model_limits=TEST_LIMITS,
    )
    application = UthCodeApplication(provider, runtime_context=context)
    request = _request()
    original = request.to_dict()

    events = [event async for event in application.stream_generation(request)]

    assert isinstance(events[-1], GenerationCompleted)
    assert len(provider.recorded_requests) == 1
    prepared = provider.recorded_requests[0]
    assert prepared is not request
    assert prepared.system_prompt is not None
    assert "工作目录：" not in prepared.system_prompt
    environment_text = "\n".join(
        part.text
        for message in prepared.messages
        for part in message.parts
        if isinstance(part, TextPart)
    )
    assert f"工作目录：{context.workdir}" in environment_text
    assert "平台：TestOS / 1.0" in environment_text
    assert "当前日期：2026-08-05" in environment_text
    assert "模型选择：remote-model" in environment_text
    assert "Provider 协议：test-protocol" in environment_text
    assert "远端模型：remote-model" in environment_text
    assert request.to_dict() == original
    assert request.system_prompt is None


@pytest.mark.asyncio
async def test_formal_bootstrap_builds_a_fake_headless_application() -> None:
    application = create_application(
        EffectiveConfig.single_model(
            "bootstrap/ref",
            provider_profile_id="bootstrap",
            provider_kind=ProviderKind.FAKE,
            remote_id="bootstrap-fake",
            context_window=1_000_000,
        )
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
                ),
                model_limits=TEST_LIMITS,
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
    provider = FakeProvider(
        events=script,
        model_limits=TEST_LIMITS,
    )  # type: ignore[arg-type]
    observed: list[object] = []

    with pytest.raises(InvalidProviderResponseError):
        async for event in UthCodeApplication(provider).stream_generation(_request()):
            observed.append(event)

    assert not any(isinstance(event, GenerationCompleted) for event in observed)


@pytest.mark.asyncio
async def test_explicit_cancellation_is_distinct_from_task_cancellation() -> None:
    application = UthCodeApplication(
        FakeProvider(events=(_completed(),), delay=10, model_limits=TEST_LIMITS)
    )
    handle = application.start_generation(_request())

    async def collect_handle() -> list[object]:
        return [event async for event in handle.events()]

    task = asyncio.create_task(collect_handle())
    await asyncio.sleep(0.05)
    handle.cancel()

    with pytest.raises(GenerationCancelled):
        await task

    task_cancelled = asyncio.create_task(
        _collect(
            UthCodeApplication(
                FakeProvider(events=(_completed(),), delay=10, model_limits=TEST_LIMITS)
            )
        )
    )
    await asyncio.sleep(0.05)
    task_cancelled.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task_cancelled


def test_application_rejects_caller_system_prompt_before_provider_call() -> None:
    provider = FakeProvider()
    application = UthCodeApplication(provider)
    request = GenerationRequest(
        system_prompt="caller-owned prompt",
        messages=(Message("user", (TextPart("hello"),)),),
    )

    with pytest.raises(ValueError, match="system_prompt"):
        application.start_generation(request)

    assert provider.recorded_requests == ()


def test_application_rejects_caller_model_before_provider_call() -> None:
    provider = FakeProvider()
    application = UthCodeApplication(provider)
    request = GenerationRequest(
        model="caller-selected-model",
        messages=(Message("user", (TextPart("hello"),)),),
    )

    with pytest.raises(ValueError, match="model"):
        application.start_generation(request)

    assert provider.recorded_requests == ()


def test_prompt_build_failure_rejects_request_before_provider_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = FakeProvider(model_limits=TEST_LIMITS)
    application = UthCodeApplication(provider)

    def fail(*_args: object, **_kwargs: object):
        raise RuntimeError("prompt build failed")

    monkeypatch.setattr(ApplicationContextService, "compose_generation_request", fail)

    with pytest.raises(RuntimeError, match="prompt build failed"):
        application.start_generation(_request())

    assert provider.recorded_requests == ()
