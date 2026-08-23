from __future__ import annotations

from pathlib import Path

import pytest

from uthcode.application import (
    ApplicationRuntimeContext,
    ConfigSource,
    EffectiveConfig,
    ModelProfile,
    ProviderKind,
    ProviderProfile,
    UthCodeApplication,
    create_application,
)
from uthcode.core.provider import (
    FinishReason,
    GenerationCompleted,
    Message,
    ModelLimits,
    ProviderIdentity,
    ProviderResponse,
    TextPart,
    Usage,
)
from uthcode.integrations.providers.fake import FakeProvider


TEST_LIMITS = ModelLimits(max_input_tokens=1_000_000, source="test.fake")


def _completed(text: str) -> GenerationCompleted:
    return GenerationCompleted(
        ProviderResponse(
            message=Message("assistant", (TextPart(text),)),
            usage=Usage(input_tokens=1, output_tokens=1),
            finish_reason=FinishReason.STOP,
        )
    )


def _config(tmp_path: Path) -> EffectiveConfig:
    return EffectiveConfig(
        default_model="one/ref",
        providers={"local": ProviderProfile("local", ProviderKind.FAKE)},
        models={
            "one/ref": ModelProfile("one/ref", "local", "remote-one", "One"),
            "two/ref": ModelProfile("two/ref", "local", "remote-two", "Two"),
        },
        sources=(ConfigSource("user", tmp_path / "config.toml"),),
    )


def _builder(provider: ProviderProfile, model: ModelProfile) -> FakeProvider:
    return FakeProvider(
        identity=ProviderIdentity(provider.provider_profile_id, "script", model.remote_id),
        events=(_completed(model.remote_id),),
        model_limits=TEST_LIMITS,
    )


def test_runtime_context_and_model_status_are_stable_values(tmp_path: Path) -> None:
    context = ApplicationRuntimeContext.from_system(
        workdir=tmp_path / "nested" / ".." / "project",
        platform_name="TestOS",
        platform_release="release-1",
        current_date="2026-08-05",
    )
    application = create_application(
        _config(tmp_path),
        provider_builder=_builder,
        runtime_context=context,
        storage_root=tmp_path / "sessions",
    )

    status = application.status()
    assert context.workdir == (tmp_path / "project").resolve()
    assert context.current_date == "2026-08-05"
    assert {model.model_ref for model in application.model_catalog()} == {"one/ref", "two/ref"}
    assert status.current_model == "one/ref"
    assert status.configuration_sources[0].path == tmp_path / "config.toml"


def test_model_selection_is_atomic_at_the_application_boundary(tmp_path: Path) -> None:
    config = _config(tmp_path)
    writes: list[str] = []
    application = create_application(
        config,
        provider_builder=_builder,
        model_writer=writes.append,
        storage_root=tmp_path / "sessions",
    )
    old_provider = application.provider

    chosen = application.select_model("two/ref")

    assert chosen.remote_id == "remote-two"
    assert writes == ["two/ref"]
    assert application.provider is not old_provider
    assert application.current_model_ref == "two/ref"
    assert config.default_model == "one/ref"

    def fail_builder(_provider: ProviderProfile, model: ModelProfile) -> FakeProvider:
        if model.model_ref == "two/ref":
            raise RuntimeError("candidate construction failed")
        return _builder(_provider, model)

    failed = create_application(
        _config(tmp_path),
        provider_builder=fail_builder,
        model_writer=lambda _model_ref: None,
        storage_root=tmp_path / "failed-sessions",
    )
    before = failed.provider
    with pytest.raises(RuntimeError, match="candidate construction failed"):
        failed.select_model("two/ref")
    assert failed.provider is before
    assert failed.current_model_ref == "one/ref"


@pytest.mark.asyncio
async def test_active_turn_keeps_its_provider_and_model_snapshot(tmp_path: Path) -> None:
    config = _config(tmp_path)
    first = _builder(config.providers["local"], config.models["one/ref"])
    second = _builder(config.providers["local"], config.models["two/ref"])
    providers = {"one/ref": first, "two/ref": second}
    application = UthCodeApplication(
        first,
        configuration=config,
        provider_builder=lambda _provider, model: providers[model.model_ref],
        model_writer=lambda _model_ref: None,
    )
    run = application.create_run()

    active = run.start_turn("first")
    application.select_model("two/ref")
    assert (await active.result()).final_text == "remote-one"
    assert first.recorded_requests[-1].model == "remote-one"

    assert (await run.start_turn("second").result()).final_text == "remote-two"
    assert second.recorded_requests[-1].model == "remote-two"
