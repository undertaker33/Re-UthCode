from __future__ import annotations

import asyncio

import pytest

from uthcode.application import UthCodeApplication
from uthcode.core.provider import (
    FinishReason,
    GenerationCompleted,
    Message,
    ModelLimits,
    ProviderError,
    ProviderResponse,
    TextDelta,
    TextPart,
    Usage,
)
from uthcode.integrations.providers.fake import FakeProvider


TEST_LIMITS = ModelLimits(max_input_tokens=1_000_000, source="test.fake")


def _completed(text: str = "done") -> GenerationCompleted:
    return GenerationCompleted(
        ProviderResponse(
            message=Message("assistant", (TextPart(text),)),
            usage=Usage(input_tokens=1, output_tokens=1),
            finish_reason=FinishReason.STOP,
        )
    )


@pytest.mark.asyncio
async def test_headless_application_runs_one_formal_turn() -> None:
    provider = FakeProvider(
        events=(TextDelta("working"), _completed("answer")),
        model_limits=TEST_LIMITS,
    )
    application = UthCodeApplication(provider)

    result = await application.create_run().start_turn("hello").result()

    assert result.status.value == "completed"
    assert result.final_text == "answer"
    assert len(provider.recorded_requests) == 1
    assert provider.recorded_requests[0].system_prompt is not None


@pytest.mark.asyncio
async def test_formal_turn_preserves_cancel_and_provider_failure_boundaries() -> None:
    delayed = UthCodeApplication(
        FakeProvider(
            events=(_completed(),),
            delay=0.05,
            model_limits=TEST_LIMITS,
        )
    )
    handle = delayed.create_run().start_turn("cancel")
    await asyncio.sleep(0.01)
    assert handle.cancel() is True
    assert handle.cancel() is False
    assert (await handle.result()).status.value == "cancelled"

    failed = UthCodeApplication(
        FakeProvider(
            error=ProviderError("synthetic provider failure"),
            model_limits=TEST_LIMITS,
        )
    )
    result = await failed.create_run().start_turn("fail").result()
    assert result.status.value == "failed"
