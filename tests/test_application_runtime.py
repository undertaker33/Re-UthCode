from __future__ import annotations

import asyncio
import inspect
from pathlib import Path

import pytest

from uthcode.application import (
    ApplicationRuntimeContext,
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


def test_runtime_context_normalizes_workdir_and_freezes_system_values(
    tmp_path: Path,
) -> None:
    context = ApplicationRuntimeContext.from_system(
        workdir=tmp_path / "nested" / ".." / "project",
        platform_name="TestOS",
        platform_release="release-1",
        current_date="2026-08-05",
    )

    assert context.workdir == (tmp_path / "project").resolve()
    assert context.workdir.is_absolute()
    assert context.platform_name == "TestOS"
    assert context.platform_release == "release-1"
    assert context.current_date == "2026-08-05"
    with pytest.raises(AttributeError):
        context.current_date = "2026-08-06"  # type: ignore[misc]


def test_generation_handles_do_not_accept_shared_external_tokens() -> None:
    assert "cancellation" not in inspect.signature(
        UthCodeApplication.start_generation
    ).parameters
    assert "cancellation" not in inspect.signature(
        UthCodeApplication.stream_generation
    ).parameters


@pytest.mark.asyncio
async def test_stream_generation_is_a_convenience_over_generation_handle() -> None:
    class RecordingApplication(UthCodeApplication):
        def __init__(self, provider: FakeProvider) -> None:
            super().__init__(provider)
            self.handles: list[GenerationHandle] = []

        def start_generation(self, request):  # type: ignore[no-untyped-def]
            handle = super().start_generation(request)
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


@pytest.mark.asyncio
async def test_model_switch_refreshes_prompt_model_protocol_and_remote_identity(
    tmp_path: Path,
) -> None:
    config = EffectiveConfig(
        model="one/ref",
        providers={
            "first": ProviderProfile("first", ProviderKind.FAKE),
            "second": ProviderProfile("second", ProviderKind.FAKE),
        },
        models={
            "one/ref": ModelProfile("one/ref", "first", "remote-one"),
            "two/ref": ModelProfile("two/ref", "second", "remote-two"),
        },
    )
    context = ApplicationRuntimeContext.from_system(
        workdir=tmp_path,
        platform_name="TestOS",
        platform_release="1.0",
        current_date="2026-08-05",
    )
    providers: dict[str, FakeProvider] = {}

    def builder(provider: ProviderProfile, model: ModelProfile) -> FakeProvider:
        instance = FakeProvider(
            identity=ProviderIdentity(
                provider.provider_profile_id,
                f"protocol-{model.model_ref}",
                model.remote_model_id,
            ),
            events=(_completed(model.remote_model_id),),
        )
        providers[model.model_ref] = instance
        return instance

    application = create_application(
        config,
        runtime_context=context,
        provider_builder=builder,
        model_writer=lambda _model_ref: None,
    )

    await _collect(application.start_generation(_request()))
    application.select_model("two/ref")
    await _collect(application.start_generation(_request()))

    first_prompt = providers["one/ref"].recorded_requests[0].system_prompt
    second_prompt = providers["two/ref"].recorded_requests[0].system_prompt
    assert first_prompt is not None
    assert second_prompt is not None
    assert "模型选择：one/ref" in first_prompt
    assert "Provider 协议：protocol-one/ref" in first_prompt
    assert "远端模型：remote-one" in first_prompt
    assert "模型选择：two/ref" in second_prompt
    assert "Provider 协议：protocol-two/ref" in second_prompt
    assert "远端模型：remote-two" in second_prompt


@pytest.mark.asyncio
async def test_generation_handle_binds_provider_snapshot_across_model_switch(
    tmp_path: Path,
) -> None:
    config = EffectiveConfig(
        model="one/ref",
        providers={
            "first": ProviderProfile("first", ProviderKind.FAKE),
            "second": ProviderProfile("second", ProviderKind.FAKE),
        },
        models={
            "one/ref": ModelProfile("one/ref", "first", "remote-one"),
            "two/ref": ModelProfile("two/ref", "second", "remote-two"),
        },
    )
    context = ApplicationRuntimeContext.from_system(
        workdir=tmp_path,
        platform_name="TestOS",
        platform_release="1.0",
        current_date="2026-08-05",
    )
    providers: dict[str, FakeProvider] = {}

    def builder(provider: ProviderProfile, model: ModelProfile) -> FakeProvider:
        instance = FakeProvider(
            identity=ProviderIdentity(
                provider.provider_profile_id,
                f"protocol-{model.model_ref}",
                model.remote_model_id,
            ),
            events=(_completed(model.remote_model_id),),
        )
        providers[model.model_ref] = instance
        return instance

    application = create_application(
        config,
        runtime_context=context,
        provider_builder=builder,
        model_writer=lambda _model_ref: None,
    )

    old_handle = application.start_generation(_request("old"))
    application.select_model("two/ref")

    old_events = await _collect(old_handle)

    assert isinstance(old_events[-1], GenerationCompleted)
    assert len(providers["one/ref"].recorded_requests) == 1
    assert len(providers["two/ref"].recorded_requests) == 0
    old_request = providers["one/ref"].recorded_requests[0]
    assert old_request.system_prompt is not None
    assert "模型选择：one/ref" in old_request.system_prompt
    assert "Provider 协议：protocol-one/ref" in old_request.system_prompt
    assert "远端模型：remote-one" in old_request.system_prompt

    new_handle = application.start_generation(_request("new"))
    new_events = await _collect(new_handle)

    assert isinstance(new_events[-1], GenerationCompleted)
    assert len(providers["one/ref"].recorded_requests) == 1
    assert len(providers["two/ref"].recorded_requests) == 1
    new_request = providers["two/ref"].recorded_requests[0]
    assert new_request.system_prompt is not None
    assert "模型选择：two/ref" in new_request.system_prompt
    assert "Provider 协议：protocol-two/ref" in new_request.system_prompt
    assert "远端模型：remote-two" in new_request.system_prompt


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["provider", "writer"])
async def test_failed_model_switch_keeps_old_prompt_identity(
    tmp_path: Path,
    failure: str,
) -> None:
    config = _runtime_config(tmp_path)

    def builder(provider: ProviderProfile, model: ModelProfile) -> FakeProvider:
        if failure == "provider" and model.model_ref == "two/ref":
            raise RuntimeError("candidate construction failed")
        return FakeProvider(
            identity=ProviderIdentity(
                provider.provider_profile_id,
                f"protocol-{model.model_ref}",
                model.remote_model_id,
            ),
            events=(_completed(model.remote_model_id),),
        )

    def writer(_model_ref: str) -> None:
        if failure == "writer":
            raise OSError("write failed")

    application = create_application(
        config,
        runtime_context=ApplicationRuntimeContext.from_system(
            workdir=tmp_path,
            platform_name="TestOS",
            platform_release="1.0",
            current_date="2026-08-05",
        ),
        provider_builder=builder,
        model_writer=writer,
    )
    old_provider = application.provider

    with pytest.raises((RuntimeError, OSError)):
        application.select_model("two/ref")
    await _collect(application.start_generation(_request()))

    prompt = old_provider.recorded_requests[0].system_prompt
    assert prompt is not None
    assert "模型选择：one/ref" in prompt
    assert "Provider 协议：protocol-one/ref" in prompt
    assert "远端模型：remote-one" in prompt


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
