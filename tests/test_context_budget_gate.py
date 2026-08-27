from __future__ import annotations

import pytest

from uthcode.application import (
    ApplicationContextService,
    ApplicationSessionService,
    EffectiveConfig,
    UthCodeApplication,
)
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


def _completed() -> GenerationCompleted:
    return GenerationCompleted(
        ProviderResponse(
            message=Message("assistant", (TextPart("done"),)),
            usage=Usage(),
            finish_reason=FinishReason.STOP,
        )
    )


class _NoCountProvider:
    identity = ProviderIdentity("fake", "no-count", "fake-model")

    def __init__(self) -> None:
        self.requests: list[GenerationRequest] = []

    def resolve_model_limits(self, _model: str) -> ModelLimits:
        return ModelLimits(max_input_tokens=20_000, source="test.runtime")

    async def stream(
        self,
        request: GenerationRequest,
        *,
        cancellation: CancellationToken,
    ):
        self.requests.append(request)
        cancellation.raise_if_cancelled()
        yield _completed()


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
    assert large.retained_target < large.effective_input_limit


def test_default_256k_budget_uses_the_selected_balanced_profile() -> None:
    budget = ContextBudget.from_limits(
        configured_input_limit=None,
        provider_limits=None,
    )

    assert budget.to_dict() == {
        "configured_input_limit": None,
        "provider_max_input": None,
        "default_input_limit": 256_000,
        "effective_input_limit": 256_000,
        "observed_input_sources": [],
        "effective_input_source": "default",
        "tightened_input_sources": [],
        "provider_max_output": None,
        "provider_combined_limit": None,
        "requested_output_reserve": 0,
        "safety_allowance": 8_192,
        "working_headroom": 48_000,
        "auto_gate_limit": 208_000,
        "fine_timeline_budget": 16_000,
        "retained_target": 96_000,
        "compaction_input_budget": 64_000,
        "compaction_output_reserve": 4_096,
    }


@pytest.mark.parametrize("effective_limit", (20_000, 64_000, 128_000))
def test_non_default_effective_limits_keep_derived_profile_values_legal(
    effective_limit: int,
) -> None:
    budget = ContextBudget.from_limits(
        configured_input_limit=effective_limit,
        provider_limits=ModelLimits(
            max_input_tokens=effective_limit,
            source="test.constrained-window",
        ),
    )

    assert 0 < budget.retained_target < budget.auto_gate_limit < budget.effective_input_limit
    assert budget.working_headroom == budget.effective_input_limit - budget.auto_gate_limit
    assert 0 < budget.compaction_output_reserve < budget.compaction_input_budget <= budget.effective_input_limit
    assert budget.safety_allowance == 0


def test_context_budget_rejects_retained_target_equal_to_auto_gate() -> None:
    with pytest.raises(ValueError, match="strictly smaller than auto_gate_limit"):
        ContextBudget(
            configured_input_limit=10_000,
            auto_gate_limit=8_000,
            retained_target=8_000,
        )


@pytest.mark.parametrize(
    ("configured", "provider"),
    (
        (3, None),
        (512, None),
        (513, None),
        (514, None),
        (600, None),
        (None, 3),
        (None, 512),
        (None, 513),
        (None, 514),
        (None, 600),
    ),
)
def test_small_effective_limits_derive_distinct_high_and_low_water(
    configured: int | None,
    provider: int | None,
) -> None:
    budget = ContextBudget.from_limits(
        configured_input_limit=configured,
        provider_limits=(
            None
            if provider is None
            else ModelLimits(max_input_tokens=provider, source="test.small-window")
        ),
    )

    assert 0 < budget.retained_target < budget.auto_gate_limit
    assert budget.auto_gate_limit < budget.effective_input_limit


@pytest.mark.parametrize("provider_limit", (512, 513, 514, 600))
def test_provider_small_ceiling_is_not_expanded_by_default(provider_limit: int) -> None:
    budget = ContextBudget.from_limits(
        configured_input_limit=None,
        provider_limits=ModelLimits(
            max_input_tokens=provider_limit,
            source="test.small-provider-window",
        ),
    )

    assert budget.effective_input_limit == provider_limit
    assert budget.effective_input_source == "provider"
    assert budget.tightened_input_sources == ("provider",)


def test_provider_ceiling_above_default_keeps_default_operating_window() -> None:
    budget = ContextBudget.from_limits(
        configured_input_limit=None,
        provider_limits=ModelLimits(
            max_input_tokens=512_000,
            source="test.large-provider-window",
        ),
    )

    assert budget.effective_input_limit == 256_000
    assert budget.effective_input_source == "default"
    assert budget.tightened_input_sources == ("default",)


@pytest.mark.parametrize(
    ("configured", "provider"),
    ((2, None), (None, 2)),
)
def test_effective_two_has_explicit_minimum_window_domain_error(
    configured: int | None,
    provider: int | None,
) -> None:
    with pytest.raises(
        ContextBudgetError,
        match="effective input limit must be at least 3 to separate High and Low Water",
    ):
        ContextBudget.from_limits(
            configured_input_limit=configured,
            provider_limits=(
                None
                if provider is None
                else ModelLimits(max_input_tokens=provider, source="test.minimum-window")
            ),
        )


def test_context_budget_rejects_an_unexplained_effective_limit() -> None:
    with pytest.raises(ContextBudgetError, match="effective|resolved"):
        ContextBudget(effective_input_limit=10_000)


@pytest.mark.parametrize(
    (
        "configured",
        "provider",
        "expected_effective",
        "expected_source",
        "expected_observed",
        "expected_tightened",
    ),
    (
        (None, None, 256_000, "default", (), ()),
        (None, 128_000, 128_000, "provider", ("provider",), ("provider",)),
        (None, 512_000, 256_000, "default", ("provider",), ("default",)),
        (300_000, None, 300_000, "configured", ("configured",), ()),
        (300_000, 400_000, 300_000, "configured", ("configured", "provider"), ()),
        (300_000, 200_000, 200_000, "provider", ("configured", "provider"), ("provider",)),
    ),
)
def test_context_limit_resolver_truth_table_and_provenance(
    configured: int | None,
    provider: int | None,
    expected_effective: int,
    expected_source: str,
    expected_observed: tuple[str, ...],
    expected_tightened: tuple[str, ...],
) -> None:
    budget = ContextBudget.from_limits(
        configured_input_limit=configured,
        provider_limits=(
            None
            if provider is None
            else ModelLimits(max_input_tokens=provider, source="test.runtime")
        ),
    )

    assert budget.default_input_limit == 256_000
    assert budget.effective_input_limit == expected_effective
    assert budget.effective_input_source == expected_source
    assert budget.observed_input_sources == expected_observed
    assert budget.tightened_input_sources == expected_tightened
    assert budget.to_dict()["default_input_limit"] == 256_000
    assert budget.to_dict()["effective_input_source"] == expected_source
    assert budget.to_dict()["observed_input_sources"] == list(expected_observed)
    assert budget.to_dict()["tightened_input_sources"] == list(expected_tightened)


def test_context_service_individual_limits_fallback_uses_shared_resolver() -> None:
    request, _snapshot = ApplicationContextService().compose_generation_request(
        (Message("user", (TextPart("hello"),)),),
        run_id="individual-limits",
        provider_limits=ModelLimits(max_input_tokens=512_000, source="test.runtime"),
    )

    assert request.metadata["context_budget"]["effective_input_limit"] == 256_000
    assert request.metadata["context_budget"]["effective_input_source"] == "default"
    assert request.metadata["context_budget"]["tightened_input_sources"] == ["default"]

    default_request, _snapshot = ApplicationContextService().compose_generation_request(
        (Message("user", (TextPart("hello"),)),),
        run_id="default-individual-limits",
    )
    assert default_request.metadata["context_budget"]["effective_input_limit"] == 256_000
    assert default_request.metadata["context_budget"]["effective_input_source"] == "default"


@pytest.mark.asyncio
async def test_idle_manual_compact_uses_default_resolver(tmp_path) -> None:
    session_service = ApplicationSessionService(
        storage_root=tmp_path,
        project_key="manual-default-limit",
        instruction_loader=None,
    )
    application = UthCodeApplication(
        FakeProvider(model_limits=None),
        session_service=session_service,
    )
    application.create_session("manual-default-limit")

    result = await application.compact_session()

    assert result.changed is False
    assert result.failure is None


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
async def test_missing_limits_use_default_operating_window_before_provider_call() -> None:
    count_calls: list[GenerationRequest] = []

    def count(request: GenerationRequest) -> int:
        count_calls.append(request)
        return account_generation_request(request).input_tokens

    provider = FakeProvider(
        events=(_completed(),),
        model_limits=None,
        input_token_counter=count,
    )
    application = UthCodeApplication(provider)

    result = await application.create_run().start_turn("hello").result()

    assert result.status.value == "completed"
    assert len(provider.recorded_requests) == 1
    assert count_calls
    diagnostics = application.diagnostics()["context_budget"]
    expected_profile = {
        "effective_input_limit": 256_000,
        "effective_input_source": "default",
        "tightened_input_sources": [],
        "safety_allowance": 8_192,
        "working_headroom": 48_000,
        "auto_gate_limit": 208_000,
        "fine_timeline_budget": 16_000,
        "retained_target": 96_000,
        "compaction_input_budget": 64_000,
        "compaction_output_reserve": 4_096,
    }
    assert {key: diagnostics[key] for key in expected_profile} == expected_profile
    request_budget = provider.recorded_requests[0].metadata["context_budget"]
    assert {key: request_budget[key] for key in expected_profile} == expected_profile


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

    result = await application.create_run().start_turn("hello").result()

    assert result.status.value == "failed"
    assert provider.resolved_models == ["fake-model"]
    assert provider.requests == []


@pytest.mark.asyncio
async def test_required_current_fact_overflow_has_zero_provider_calls() -> None:
    provider = FakeProvider(
        model_limits=ModelLimits(max_input_tokens=64),
    )
    config = EffectiveConfig.single_model("fake/ref", context_window=64)
    application = UthCodeApplication(provider, configuration=config)
    result = await application.create_run().start_turn("x" * 10_000).result()

    assert result.status.value == "failed"
    assert provider.recorded_requests == ()


def test_compiler_without_resolved_limit_does_not_invent_a_window() -> None:
    snapshot = ContextCompiler().compile(ContextSourceBundle(current_turn=("hello",)))

    assert snapshot.budget_tokens is None
    assert snapshot.over_budget is False


@pytest.mark.asyncio
async def test_provider_count_capability_missing_uses_local_conservative_preflight() -> None:
    provider = _NoCountProvider()
    application = UthCodeApplication(
        provider,
        configuration=EffectiveConfig.single_model(
            "fake/ref",
            remote_id="fake-model",
            context_window=20_000,
        ),
    )

    result = await application.create_run().start_turn("hello").result()
    request = provider.requests[-1]
    gate = request.metadata["context_gate"]

    assert result.final_text == "done"
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

    result = await application.create_run().start_turn("hello").result()
    sent = provider.recorded_requests[-1]

    assert result.final_text == "done"
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

    result = await application.create_run().start_turn("hello").result()

    assert result.status.value == "failed"
    assert provider.recorded_requests == ()
