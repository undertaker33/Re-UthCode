from __future__ import annotations

import pytest

from uthcode.application import EffectiveConfig, UthCodeApplication
from uthcode.core.context import (
    ContextBudget,
    ContextBudgetError,
    ContextRequestSafetyError,
    ContextSourceBundle,
    ContextCompiler,
    ContextCountEstimate,
    account_generation_request,
    evaluate_gates,
    preflight_safety_count,
    safety_allowance_for,
)
from uthcode.core.provider import (
    CancellationToken,
    FinishReason,
    GenerationCancelled,
    GenerationCompleted,
    GenerationRequest,
    Message,
    ModelLimits,
    NetworkError,
    ProviderIdentity,
    ProviderResponse,
    TextPart,
    ToolDefinition,
    ToolCallPart,
    ToolResultPart,
    Usage,
)
from uthcode.integrations.providers.fake import FakeProvider


def _request(text: str = "hello") -> GenerationRequest:
    return GenerationRequest(
        system_prompt="system instruction",
        messages=(Message("user", (TextPart(text),)),),
        tools=(ToolDefinition("read", "read a file", {"type": "object"}),),
        max_output_tokens=256,
    )


def _application_request(text: str = "hello") -> GenerationRequest:
    return GenerationRequest(
        messages=(Message("user", (TextPart(text),)),),
        max_output_tokens=256,
    )


def _request_without_output_reserve(text: str = "hello") -> GenerationRequest:
    return GenerationRequest(messages=(Message("user", (TextPart(text),)),))


def _completed() -> GenerationCompleted:
    return GenerationCompleted(
        ProviderResponse(
            message=Message("assistant", (TextPart("done"),)),
            usage=Usage(),
            finish_reason=FinishReason.STOP,
        )
    )


async def _consume(handle) -> list[object]:  # type: ignore[no-untyped-def]
    return [event async for event in handle.events()]


class _NoCountProvider:
    identity = ProviderIdentity("fake", "no-count", "fake-model")

    def resolve_model_limits(self, _model: str) -> ModelLimits:
        return ModelLimits(max_input_tokens=20_000, source="test.runtime")


class _CancelledCountProvider:
    identity = ProviderIdentity("fake", "cancel-count", "fake-model")

    def __init__(self) -> None:
        self.counted: list[GenerationRequest] = []
        self.requests: list[GenerationRequest] = []

    async def resolve_model_limits(self, _model: str) -> ModelLimits:
        return ModelLimits(max_input_tokens=20_000, source="test.runtime")

    async def count_input_tokens(self, request: GenerationRequest) -> None:
        self.counted.append(request)
        raise GenerationCancelled()

    async def stream(
        self,
        request: GenerationRequest,
        *,
        cancellation: CancellationToken,
    ):
        self.requests.append(request)
        cancellation.raise_if_cancelled()
        yield _completed()


class _AsyncLimitsProvider:
    identity = ProviderIdentity("fake", "async-limits", "fake-model")

    def __init__(self, limits: ModelLimits) -> None:
        self._limits = limits
        self.resolved_models: list[str] = []
        self.requests: list[GenerationRequest] = []

    async def resolve_model_limits(self, model: str) -> ModelLimits:
        self.resolved_models.append(model)
        return self._limits

    async def stream(
        self,
        request: GenerationRequest,
        *,
        cancellation: CancellationToken,
    ):
        self.requests.append(request)
        cancellation.raise_if_cancelled()
        yield _completed()


def test_adaptive_headroom_is_small_window_aware_and_large_window_capped() -> None:
    small = ContextBudget.from_limits(
        configured_input_limit=25_000,
        provider_limits=ModelLimits(max_input_tokens=30_000),
    )
    large = ContextBudget.from_limits(
        configured_input_limit=1_000_000,
        provider_limits=ModelLimits(max_input_tokens=2_000_000),
    )

    assert small.effective_input_limit == 25_000
    assert small.working_headroom < large.working_headroom
    assert large.working_headroom <= 48_000
    assert large.retained_hard_cap < large.effective_input_limit


def test_context_budget_rejects_effective_limit_without_an_authority_source() -> None:
    with pytest.raises(ContextBudgetError, match="configured|reliable Provider"):
        ContextBudget(effective_input_limit=10_000)


def test_final_accounting_includes_instruction_messages_tools_and_framing() -> None:
    accounting = account_generation_request(_request())

    assert accounting.instruction_tokens > 0
    assert accounting.messages_tokens > 0
    assert accounting.tools_tokens > 0
    assert accounting.framing_tokens > 0
    assert accounting.input_tokens == sum(
        (
            accounting.instruction_tokens,
            accounting.messages_tokens,
            accounting.tools_tokens,
            accounting.framing_tokens,
        )
    )


def test_auto_pressure_can_be_true_while_hard_gate_is_safe() -> None:
    budget = ContextBudget.from_limits(
        configured_input_limit=25_000,
        provider_limits=ModelLimits(max_input_tokens=25_000),
        requested_output_reserve=256,
    )
    count = ContextCountEstimate(
        input_tokens=budget.auto_gate_limit + 1,
        source="test.pressure",
        kind="preflight_local_estimate",
    )

    decision = evaluate_gates(budget, count)

    assert decision.auto_pressure is True
    assert decision.hard_safe is True
    assert decision.input_safe is True
    assert decision.output_safe is True
    assert decision.combined_safe is True


def test_output_and_combined_limits_are_hard_checked_independently() -> None:
    request = _request()
    budget = ContextBudget.from_limits(
        configured_input_limit=100_000,
        provider_limits=ModelLimits(
            max_input_tokens=100_000,
            max_output_tokens=128,
            max_combined_tokens=200,
        ),
        requested_output_reserve=256,
    )
    count = preflight_safety_count(request, budget)
    decision = evaluate_gates(budget, count)

    assert decision.input_safe is True
    assert decision.output_safe is False
    assert decision.combined_safe is False
    assert decision.hard_safe is False


@pytest.mark.asyncio
async def test_missing_limits_fail_closed_before_provider_call() -> None:
    count_calls: list[GenerationRequest] = []

    def count(request: GenerationRequest) -> int:
        count_calls.append(request)
        return account_generation_request(request).input_tokens

    provider = FakeProvider(model_limits=None, input_token_counter=count)
    application = UthCodeApplication(provider)

    with pytest.raises(ContextBudgetError, match="limit"):
        await _consume(application.start_generation(
            GenerationRequest(messages=(Message("user", (TextPart("hello"),)),))
        ))

    assert provider.recorded_requests == ()
    assert count_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider_limits",
    (
        ModelLimits(
            max_input_tokens=100_000,
            max_output_tokens=1_024,
            source="test.output-limit",
        ),
        ModelLimits(
            max_input_tokens=100_000,
            max_combined_tokens=8_000,
            source="test.combined-limit",
        ),
    ),
)
async def test_unconfigured_output_reserve_is_hard_gated_before_direct_provider_call(
    provider_limits: ModelLimits,
) -> None:
    provider = FakeProvider(events=(_completed(),), model_limits=provider_limits)
    application = UthCodeApplication(
        provider,
        configuration=EffectiveConfig.single_model(
            "fake/ref",
            remote_id="fake-model",
            context_window=100_000,
        ),
    )

    with pytest.raises(ContextRequestSafetyError, match="output|combined"):
        await _consume(application.start_generation(_request_without_output_reserve()))

    assert provider.recorded_requests == ()


@pytest.mark.asyncio
async def test_unconfigured_output_reserve_is_hard_gated_before_formal_turn_provider_call() -> None:
    provider = FakeProvider(
        events=(_completed(),),
        model_limits=ModelLimits(
            max_input_tokens=100_000,
            max_output_tokens=1_024,
            source="test.output-limit",
        ),
    )
    application = UthCodeApplication(
        provider,
        configuration=EffectiveConfig.single_model(
            "fake/ref",
            remote_id="fake-model",
            context_window=100_000,
        ),
    )

    result = await application.create_run().start_turn("hello").result()

    assert result.status.value == "failed"
    assert provider.recorded_requests == ()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider_limits",
    (
        ModelLimits(
            max_input_tokens=100_000,
            max_output_tokens=1_024,
            source="test.async-output-limit",
        ),
        ModelLimits(
            max_input_tokens=100_000,
            max_combined_tokens=8_000,
            source="test.async-combined-limit",
        ),
    ),
)
async def test_async_limits_output_or_combined_gate_blocks_before_stream(
    provider_limits: ModelLimits,
) -> None:
    provider = _AsyncLimitsProvider(provider_limits)
    application = UthCodeApplication(
        provider,
        configuration=EffectiveConfig.single_model(
            "fake/ref",
            remote_id="fake-model",
            context_window=100_000,
        ),
    )

    with pytest.raises(ContextRequestSafetyError, match="output|combined"):
        await _consume(application.start_generation(_request_without_output_reserve()))

    assert provider.resolved_models == ["fake-model"]
    assert provider.requests == []


@pytest.mark.asyncio
async def test_required_current_fact_overflow_has_zero_provider_calls() -> None:
    provider = FakeProvider(
        model_limits=ModelLimits(max_input_tokens=64),
    )
    config = EffectiveConfig.single_model("fake/ref", context_window=64)
    application = UthCodeApplication(provider, configuration=config)
    request = GenerationRequest(
        messages=(Message("user", (TextPart("x" * 10_000),)),),
    )

    try:
        await _consume(application.start_generation(request))
    except ContextRequestSafetyError:
        pass
    else:  # pragma: no cover - the assertion is the safety contract
        raise AssertionError("required current facts must fail closed")

    assert provider.recorded_requests == ()


def test_compiler_without_resolved_limit_does_not_invent_a_window() -> None:
    snapshot = ContextCompiler().compile(ContextSourceBundle(current_turn=("hello",)))

    assert snapshot.budget_tokens is None
    assert snapshot.over_budget is False


@pytest.mark.asyncio
async def test_provider_count_targets_budget_aware_l3_request_and_final_send() -> None:
    counted: list[GenerationRequest] = []

    def count(request: GenerationRequest) -> ContextCountEstimate:
        counted.append(request)
        if len(request.messages) > 12:
            return ContextCountEstimate(
                46_408,
                "test.unbounded-count",
                "preflight_provider_count",
            )
        return ContextCountEstimate(
            account_generation_request(request).input_tokens,
            "test.final-count",
            "preflight_provider_count",
        )

    messages = tuple(
        Message("user", (TextPart(f"old-{index}-" + "x" * 2_000),))
        for index in range(20)
    ) + (Message("user", (TextPart("current"),)),)
    provider = FakeProvider(
        events=(_completed(),),
        model_limits=ModelLimits(max_input_tokens=10_000, source="test.limit"),
        input_token_counter=count,
    )
    application = UthCodeApplication(
        provider,
        configuration=EffectiveConfig.single_model(
            "fake/ref",
            remote_id="fake-model",
            context_window=10_000,
        ),
    )
    unbounded, _ = application.context_service.compose_generation_request(
        messages,
        run_id="unbounded",
    )

    events = await _consume(
        application.start_generation(GenerationRequest(messages=messages))
    )
    sent = provider.recorded_requests[-1]

    assert isinstance(events[-1], GenerationCompleted)
    assert len(counted) >= 2
    assert counted[0] != unbounded
    assert all(len(request.messages) <= 12 for request in counted)
    assert counted[-1] == sent
    assert counted[-1] is sent
    assert sent.metadata["context_gate"]["hard_safe"] is True
    assert sent.metadata["context_gate"]["input_tokens"] == sent.metadata[
        "request_accounting"
    ]["input_tokens"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("level", "tool_result", "inactive_text"),
    (
        ("L1", "x" * 12_000, "inactive"),
        ("L2", "x" * 1_000, "y" * 10_000),
    ),
)
async def test_l1_l2_recount_rebuild_and_regate_the_changed_request(
    level: str,
    tool_result: str,
    inactive_text: str,
) -> None:
    counted: list[GenerationRequest] = []

    def count(request: GenerationRequest) -> ContextCountEstimate:
        counted.append(request)
        reduction_needed = any(
            isinstance(part, ToolResultPart) and len(part.content) > 8_192
            or isinstance(part, TextPart) and len(part.text) > 2_048
            for message in request.messages[:-1]
            for part in message.parts
        )
        value = (
            20_000
            if reduction_needed
            else account_generation_request(request).input_tokens
        )
        return ContextCountEstimate(value, "test.count", "preflight_provider_count")

    messages = (
        Message(
            "assistant",
            (ToolCallPart("call-1", "read", {}), TextPart(inactive_text)),
        ),
        Message("tool", (ToolResultPart("call-1", tool_result),)),
        Message("user", (TextPart("current fact"),)),
    )
    provider = FakeProvider(
        events=(_completed(),),
        model_limits=ModelLimits(max_input_tokens=20_000, source="test.limit"),
        input_token_counter=count,
    )
    application = UthCodeApplication(
        provider,
        configuration=EffectiveConfig.single_model(
            "fake/ref",
            remote_id="fake-model",
            context_window=20_000,
        ),
    )

    await _consume(application.start_generation(GenerationRequest(messages=messages)))
    sent = provider.recorded_requests[-1]
    sent_parts = tuple(part for message in sent.messages for part in message.parts)
    call_ids = {part.tool_call_id for part in sent_parts if isinstance(part, ToolCallPart)}
    result_ids = {
        part.tool_call_id for part in sent_parts if isinstance(part, ToolResultPart)
    }

    assert level in sent.metadata["context_reduction_levels"]
    assert len(counted) >= 2
    assert counted[-1] == sent
    assert counted[-1] is sent
    assert call_ids == result_ids == {"call-1"}
    assert any(
        isinstance(part, TextPart) and "current fact" in part.text
        for part in sent_parts
    )
    assert sent.metadata["context_gate"]["hard_safe"] is True
    assert sent.metadata["context_count_source"] == "test.count"
    assert sent.metadata["request_accounting"] == account_generation_request(
        sent
    ).to_dict()


@pytest.mark.asyncio
async def test_provider_count_capability_missing_uses_local_conservative_preflight() -> None:
    application = UthCodeApplication(
        _NoCountProvider(),
        configuration=EffectiveConfig.single_model(
            "fake/ref",
            remote_id="fake-model",
            context_window=20_000,
        ),
    )

    handle = application.start_generation(_application_request())
    assert await handle is handle
    request = handle._request
    assert request is not None
    gate = request.metadata["context_gate"]

    assert request.metadata["context_count_source"] == "local.preflight_estimate"
    assert request.metadata["context_count_fallback"] == "capability_missing"
    assert gate["safety_allowance"] == safety_allowance_for(
        20_000,
        kind="preflight_local_estimate",
    )


@pytest.mark.asyncio
async def test_controlled_provider_count_failure_falls_back_and_streams_normally() -> None:
    def fail(_request: GenerationRequest) -> None:
        raise NetworkError("count endpoint unavailable")

    provider = FakeProvider(
        events=(_completed(),),
        model_limits=ModelLimits(max_input_tokens=20_000, source="test.limit"),
        input_token_counter=fail,
    )
    application = UthCodeApplication(
        provider,
        configuration=EffectiveConfig.single_model(
            "fake/ref",
            remote_id="fake-model",
            context_window=20_000,
        ),
    )

    events = await _consume(application.start_generation(_application_request()))
    sent = provider.recorded_requests[-1]

    assert isinstance(events[-1], GenerationCompleted)
    assert sent.metadata["context_count_source"] == "local.preflight_estimate"
    assert sent.metadata["context_count_fallback"] == "provider_count_failure"
    assert sent.metadata["context_gate"]["safety_allowance"] == safety_allowance_for(
        20_000,
        kind="preflight_local_estimate",
    )


@pytest.mark.asyncio
async def test_provider_count_cancellation_does_not_enter_local_fallback() -> None:
    provider = _CancelledCountProvider()
    application = UthCodeApplication(
        provider,
        configuration=EffectiveConfig.single_model(
            "fake/ref",
            remote_id="fake-model",
            context_window=20_000,
        ),
    )

    result = await application.create_run().start_turn("cancel").result()

    assert result.status.value == "cancelled"
    assert provider.counted
    assert provider.requests == []
    assert application.diagnostics()["context"].get("count_fallback") is None


@pytest.mark.asyncio
async def test_provider_configuration_count_error_is_not_treated_as_count_outage() -> None:
    from uthcode.core.provider import ProviderConfigurationError

    def fail(_request: GenerationRequest) -> None:
        raise ProviderConfigurationError("invalid count configuration")

    provider = FakeProvider(
        model_limits=ModelLimits(max_input_tokens=20_000, source="test.limit"),
        input_token_counter=fail,
    )
    application = UthCodeApplication(
        provider,
        configuration=EffectiveConfig.single_model(
            "fake/ref",
            remote_id="fake-model",
            context_window=20_000,
        ),
    )

    with pytest.raises(ProviderConfigurationError):
        await _consume(application.start_generation(_application_request()))
