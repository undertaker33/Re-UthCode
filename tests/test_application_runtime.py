from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from uthcode.application import (
    ConfigSource,
    EffectiveConfig,
    GenerationHandle,
    ModelProfile,
    ProviderKind,
    ProviderProfile,
    UthCodeApplication,
    create_application,
)
from uthcode.core.provider import (
    FinishReason,
    GenerationCancelled,
    GenerationCompleted,
    GenerationRequest,
    Message,
    ProviderIdentity,
    ProviderResponse,
    TextDelta,
    TextPart,
    Usage,
)
from uthcode.integrations.providers.fake import FakeProvider


def _request(text: str = "hello") -> GenerationRequest:
    return GenerationRequest(messages=(Message("user", (TextPart(text),)),))


def _completed(text: str = "done") -> GenerationCompleted:
    return GenerationCompleted(
        ProviderResponse(
            message=Message("assistant", (TextPart(text),)),
            usage=Usage(input_tokens=1, output_tokens=1),
            finish_reason=FinishReason.STOP,
        )
    )


async def _collect(handle: GenerationHandle) -> list[object]:
    return [event async for event in handle.events()]


@pytest.mark.asyncio
async def test_generation_handles_cancel_independently_and_record_requests() -> None:
    provider = FakeProvider(
        events=(TextDelta("done"), _completed()),
        delay=0.15,
    )
    application = UthCodeApplication(provider)
    first = application.start_generation(_request("first"))
    second = application.start_generation(_request("second"))

    first_task = asyncio.create_task(_collect(first))
    second_task = asyncio.create_task(_collect(second))
    await asyncio.sleep(0.02)
    assert first.cancel() is True
    assert first.cancel() is False
    assert first.cancelled is True
    assert second.cancelled is False

    with pytest.raises(GenerationCancelled):
        await first_task
    second_events = await second_task

    assert isinstance(second_events[-1], GenerationCompleted)
    assert second.cancelled is False
    assert len(provider.recorded_requests) == 2


@pytest.mark.asyncio
async def test_stream_generation_is_a_convenience_over_generation_handle() -> None:
    class RecordingApplication(UthCodeApplication):
        def __init__(self, provider: FakeProvider) -> None:
            super().__init__(provider)
            self.handles: list[GenerationHandle] = []

        def start_generation(self, request, *, cancellation=None):  # type: ignore[no-untyped-def]
            handle = super().start_generation(request, cancellation=cancellation)
            self.handles.append(handle)
            return handle

    application = RecordingApplication(
        FakeProvider(events=(TextDelta("ok"), _completed()))
    )
    events = [event async for event in application.stream_generation(_request())]

    assert len(application.handles) == 1
    assert isinstance(application.handles[0], GenerationHandle)
    assert isinstance(events[-1], GenerationCompleted)


def _runtime_config(tmp_path: Path) -> EffectiveConfig:
    return EffectiveConfig(
        model="one/ref",
        providers={
            "local": ProviderProfile("local", ProviderKind.FAKE),
        },
        models={
            "one/ref": ModelProfile("one/ref", "local", "remote-one", "One"),
            "two/ref": ModelProfile("two/ref", "local", "remote-two", "Two"),
        },
        sources=(ConfigSource("user", tmp_path / "config.toml"),),
    )


def _builder(provider: ProviderProfile, model: ModelProfile) -> FakeProvider:
    return FakeProvider(
        identity=ProviderIdentity(
            provider.provider_profile_id,
            "script",
            model.remote_model_id,
        ),
        events=(_completed(model.remote_model_id),),
    )


def test_model_catalog_and_status_are_safe_application_values(tmp_path: Path) -> None:
    config = _runtime_config(tmp_path)
    application = create_application(config, provider_builder=_builder)

    catalog = application.model_catalog()
    status = application.status()

    assert {model.model_ref for model in catalog} == {"one/ref", "two/ref"}
    assert status.current_model == "one/ref"
    assert status.provider_profile == "local"
    assert status.configuration_sources[0].path == (tmp_path / "config.toml")
    assert status.to_dict()["state"] == "ready"
    assert "DEEPSEEK" not in repr(status)
    assert not hasattr(application, "config")
    assert not hasattr(application, "models")
    assert not hasattr(status, "current_model_ref")
    assert not hasattr(status, "config_sources")


def test_candidate_provider_failure_does_not_change_runtime_or_file(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.toml"
    original = 'model = "one/ref"\n'
    config_path.write_text(original, encoding="utf-8")
    config = _runtime_config(tmp_path)
    calls: list[str] = []

    def builder(provider: ProviderProfile, model: ModelProfile) -> FakeProvider:
        calls.append(model.model_ref)
        if model.model_ref == "two/ref":
            raise RuntimeError("candidate construction failed")
        return _builder(provider, model)

    writes: list[str] = []
    application = create_application(
        config,
        provider_builder=builder,
        model_writer=writes.append,
    )
    old_provider = application.provider

    with pytest.raises(RuntimeError, match="candidate construction failed"):
        application.select_model("two/ref")

    assert calls == ["one/ref", "two/ref"]
    assert writes == []
    assert application.provider is old_provider
    assert application.current_model_ref == "one/ref"
    assert config_path.read_text(encoding="utf-8") == original


def test_user_model_write_failure_does_not_replace_candidate_or_current_model(
    tmp_path: Path,
) -> None:
    config = _runtime_config(tmp_path)
    old_provider = _builder(config.providers["local"], config.models["one/ref"])

    def fail_writer(_model_ref: str) -> None:
        raise OSError("write failed")

    application = UthCodeApplication(
        old_provider,
        configuration=config,
        provider_builder=_builder,
        model_writer=fail_writer,
    )

    with pytest.raises(OSError, match="write failed"):
        application.select_model("two/ref")

    assert application.provider is old_provider
    assert application.current_model_ref == "one/ref"


def test_successful_model_switch_updates_provider_and_only_user_selection() -> None:
    config = EffectiveConfig(
        model="one/ref",
        providers={"local": ProviderProfile("local", ProviderKind.FAKE)},
        models={
            "one/ref": ModelProfile("one/ref", "local", "remote-one"),
            "two/ref": ModelProfile("two/ref", "local", "remote-two"),
        },
    )
    writes: list[str] = []
    application = create_application(
        config,
        provider_builder=_builder,
        model_writer=writes.append,
    )
    old_provider = application.provider

    chosen = application.select_model("two/ref")

    assert chosen.remote_model_id == "remote-two"
    assert writes == ["two/ref"]
    assert application.provider is not old_provider
    assert application.provider.identity.model == "remote-two"
    assert application.current_model_ref == "two/ref"
    assert config.model == "one/ref"


def test_create_application_injection_receives_application_profiles() -> None:
    config = EffectiveConfig.single_model(
        "profile/ref",
        provider_profile_id="profile",
        provider_kind=ProviderKind.FAKE,
        remote_model_id="remote-id",
        max_output_tokens=321,
    )
    seen: list[tuple[ProviderProfile, ModelProfile]] = []

    def build(provider: ProviderProfile, model: ModelProfile) -> FakeProvider:
        seen.append((provider, model))
        return FakeProvider(
            identity=ProviderIdentity("fake", "script", "remote-id"),
            events=(_completed(),),
        )

    application = create_application(config, provider_builder=build)

    assert application.provider.identity.model == "remote-id"
    assert len(seen) == 1
    provider, model = seen[0]
    assert provider.provider_profile_id == "profile"
    assert model.model_ref == "profile/ref"
    assert model.remote_model_id == "remote-id"
    assert model.max_output_tokens == 321


def test_bootstrap_passes_max_output_tokens_to_integration_provider_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from uthcode.integrations.providers import factory as provider_factory

    config = EffectiveConfig.single_model(
        "profile/ref",
        provider_profile_id="profile",
        provider_kind=ProviderKind.FAKE,
        remote_model_id="remote-id",
        max_output_tokens=321,
    )
    seen: list[object] = []

    def observe(provider_config: object) -> FakeProvider:
        seen.append(provider_config)
        return FakeProvider(
            identity=ProviderIdentity("fake", "script", "remote-id"),
            events=(_completed(),),
        )

    monkeypatch.setattr(provider_factory, "create_provider", observe)
    application = create_application(config)

    assert application.provider.identity.model == "remote-id"
    assert len(seen) == 1
    provider_config = seen[0]
    assert provider_config.max_output_tokens == 321  # type: ignore[attr-defined]
    assert not hasattr(provider_config, "temperature")


def test_create_application_rejects_single_argument_provider_builder() -> None:
    config = EffectiveConfig.single_model("profile/ref")

    def build(_provider: ProviderProfile) -> FakeProvider:
        return FakeProvider(events=(_completed(),))

    with pytest.raises(TypeError):
        create_application(config, provider_builder=build)  # type: ignore[arg-type]
