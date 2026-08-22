from __future__ import annotations

import asyncio
import gc
import inspect
from pathlib import Path
import warnings

import pytest

from uthcode.application import (
    ApplicationRuntimeContext,
    ConfigSource,
    EffectiveConfig,
    GenerationHandle,
    InstructionLoader,
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
    ModelLimits,
    ProviderIdentity,
    ProviderResponse,
    TextDelta,
    TextPart,
    Usage,
)
from uthcode.integrations.providers.fake import FakeProvider
from uthcode.integrations.instruction_files import InstructionFileReader


TEST_LIMITS = ModelLimits(max_input_tokens=1_000_000, source="test.fake")


def _request(text: str = "hello") -> GenerationRequest:
    return GenerationRequest(messages=(Message("user", (TextPart(text),)),))


def _request_text(request: GenerationRequest) -> str:
    return "\n".join(
        part.text
        for message in request.messages
        for part in message.parts
        if isinstance(part, TextPart)
    )


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


async def _await_handle(handle: GenerationHandle) -> GenerationHandle:
    return await handle


class _AsyncLimitsProvider(FakeProvider):
    def __init__(self, identity: ProviderIdentity, limits: ModelLimits) -> None:
        super().__init__(
            identity=identity,
            events=(_completed(identity.model),),
        )
        self._async_limits = limits
        self.resolved_models: list[str] = []

    async def resolve_model_limits(self, model: str) -> ModelLimits:
        self.resolved_models.append(model)
        await asyncio.sleep(0)
        return self._async_limits


class _BlockingAsyncLimitsProvider(_AsyncLimitsProvider):
    def __init__(self, identity: ProviderIdentity, limits: ModelLimits) -> None:
        super().__init__(identity, limits)
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.cancelled_count = 0

    async def resolve_model_limits(self, model: str) -> ModelLimits:
        self.resolved_models.append(model)
        self.started.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled_count += 1
            raise
        return self._async_limits


class _FailingAsyncLimitsProvider(_AsyncLimitsProvider):
    def __init__(
        self,
        identity: ProviderIdentity,
        limits: ModelLimits,
        failure: BaseException,
    ) -> None:
        super().__init__(identity, limits)
        self._failure = failure

    async def resolve_model_limits(self, model: str) -> ModelLimits:
        self.resolved_models.append(model)
        raise self._failure


def _async_limits_config() -> EffectiveConfig:
    return EffectiveConfig(
        default_model="one/ref",
        providers={
            "first": ProviderProfile("first", ProviderKind.FAKE),
            "second": ProviderProfile("second", ProviderKind.FAKE),
        },
        models={
            "one/ref": ModelProfile("one/ref", "first", "remote-one"),
            "two/ref": ModelProfile("two/ref", "second", "remote-two"),
        },
    )


@pytest.mark.asyncio
async def test_generation_handles_cancel_independently_and_record_requests() -> None:
    provider = FakeProvider(
        events=(TextDelta("done"), _completed()),
        delay=0.15,
        model_limits=TEST_LIMITS,
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
        FakeProvider(events=(TextDelta("ok"), _completed()), model_limits=TEST_LIMITS)
    )
    events = [event async for event in application.stream_generation(_request())]

    assert len(application.handles) == 1
    assert isinstance(application.handles[0], GenerationHandle)
    assert isinstance(events[-1], GenerationCompleted)


def _runtime_config(tmp_path: Path) -> EffectiveConfig:
    return EffectiveConfig(
        default_model="one/ref",
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
            model.remote_id,
        ),
        events=(_completed(model.remote_id),),
        model_limits=TEST_LIMITS,
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
    original = 'default_model = "one/ref"\n'
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
        default_model="one/ref",
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

    assert chosen.remote_id == "remote-two"
    assert writes == ["two/ref"]
    assert application.provider is not old_provider
    assert application.provider.identity.model == "remote-two"
    assert application.current_model_ref == "two/ref"
    assert config.default_model == "one/ref"


@pytest.mark.asyncio
async def test_model_switch_refreshes_prompt_model_protocol_and_remote_identity(
    tmp_path: Path,
) -> None:
    config = EffectiveConfig(
        default_model="one/ref",
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
                model.remote_id,
            ),
            events=(_completed(model.remote_id),),
            model_limits=TEST_LIMITS,
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
    assert first_prompt == second_prompt
    assert (
        providers["one/ref"].recorded_requests[0].metadata["stable_prefix_fingerprint"]
        == providers["two/ref"].recorded_requests[0].metadata["stable_prefix_fingerprint"]
    )
    assert "模型选择：one/ref" not in first_prompt
    assert "模型选择：two/ref" not in second_prompt
    assert "模型选择：one/ref" in _request_text(providers["one/ref"].recorded_requests[0])
    assert "Provider 协议：protocol-one/ref" in _request_text(providers["one/ref"].recorded_requests[0])
    assert "远端模型：remote-one" in _request_text(providers["one/ref"].recorded_requests[0])
    assert "模型选择：two/ref" in _request_text(providers["two/ref"].recorded_requests[0])
    assert "Provider 协议：protocol-two/ref" in _request_text(providers["two/ref"].recorded_requests[0])
    assert "远端模型：remote-two" in _request_text(providers["two/ref"].recorded_requests[0])


@pytest.mark.asyncio
async def test_generation_handle_binds_provider_snapshot_across_model_switch(
    tmp_path: Path,
) -> None:
    config = EffectiveConfig(
        default_model="one/ref",
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
                model.remote_id,
            ),
            events=(_completed(model.remote_id),),
            model_limits=TEST_LIMITS,
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
    assert "模型选择：one/ref" in _request_text(old_request)
    assert "Provider 协议：protocol-one/ref" in _request_text(old_request)
    assert "远端模型：remote-one" in _request_text(old_request)

    new_handle = application.start_generation(_request("new"))
    new_events = await _collect(new_handle)

    assert isinstance(new_events[-1], GenerationCompleted)
    assert len(providers["one/ref"].recorded_requests) == 1
    assert len(providers["two/ref"].recorded_requests) == 1
    new_request = providers["two/ref"].recorded_requests[0]
    assert new_request.system_prompt is not None
    assert "模型选择：two/ref" in _request_text(new_request)
    assert "Provider 协议：protocol-two/ref" in _request_text(new_request)
    assert "远端模型：remote-two" in _request_text(new_request)


@pytest.mark.asyncio
async def test_async_limits_handle_binds_model_snapshot_across_model_switch() -> None:
    config = _async_limits_config()
    providers: dict[str, _AsyncLimitsProvider] = {}

    def builder(provider: ProviderProfile, model: ModelProfile) -> _AsyncLimitsProvider:
        instance = _AsyncLimitsProvider(
            ProviderIdentity(
                provider.provider_profile_id,
                f"protocol-{model.model_ref}",
                model.remote_id,
            ),
            TEST_LIMITS,
        )
        providers[model.model_ref] = instance
        return instance

    application = create_application(
        config,
        provider_builder=builder,
        model_writer=lambda _model_ref: None,
    )

    old_handle = application.start_generation(_request("old"))
    application.select_model("two/ref")
    old_events = await _collect(old_handle)

    assert isinstance(old_events[-1], GenerationCompleted)
    old_provider = providers["one/ref"]
    assert old_provider.resolved_models == ["remote-one"]
    assert len(old_provider.recorded_requests) == 1
    old_request = old_provider.recorded_requests[0]
    assert old_request.model == "remote-one"
    assert "模型选择：one/ref" in _request_text(old_request)
    assert "远端模型：remote-one" in _request_text(old_request)
    assert providers["two/ref"].resolved_models == []
    assert providers["two/ref"].recorded_requests == ()


@pytest.mark.asyncio
async def test_async_limits_handle_binds_instruction_snapshot_across_adopt_session_state(
    tmp_path: Path,
) -> None:
    user_root = tmp_path / "home"
    project_root = tmp_path / "project"
    user_root.mkdir(exist_ok=True)
    project_root.mkdir(exist_ok=True)
    project_agents = project_root / "AGENTS.md"
    project_agents.write_text("old instruction epoch", encoding="utf-8")
    loader = InstructionLoader(
        user_root=user_root,
        project_root=project_root,
        reader=InstructionFileReader(),
    )
    loader.load_session(strict=True)

    provider = _AsyncLimitsProvider(
        ProviderIdentity("first", "protocol-old", "remote-old"),
        TEST_LIMITS,
    )
    application = UthCodeApplication(provider, instruction_loader=loader)
    old_epoch = loader.instruction_epoch
    old_fingerprint = loader.stable_prefix_fingerprint
    old_reason = loader.change_reason
    old_state = loader.instruction_state
    handle = application.start_generation(_request("old instruction"))

    project_agents.write_text("new instruction epoch", encoding="utf-8")
    new_loader = InstructionLoader(
        user_root=user_root,
        project_root=project_root,
        reader=InstructionFileReader(),
    )
    new_loader.rebuild_from_metadata(old_state, strict=True)
    assert new_loader.instruction_epoch != old_epoch
    loader.adopt_session_state(new_loader)
    assert loader.instruction_epoch == new_loader.instruction_epoch

    events = await _collect(handle)

    assert isinstance(events[-1], GenerationCompleted)
    assert provider.resolved_models == ["remote-old"]
    assert len(provider.recorded_requests) == 1
    request = provider.recorded_requests[0]
    assert request.model == "remote-old"
    assert request.system_prompt is not None
    assert "old instruction epoch" in request.system_prompt
    assert "new instruction epoch" not in request.system_prompt
    assert request.metadata["instruction_epoch"] == old_epoch
    assert request.metadata["stable_prefix_fingerprint"] == old_fingerprint
    assert request.metadata["prefix_change_reason"] == old_reason


def test_unconsumed_async_limits_handle_does_not_leak_coroutine() -> None:
    provider = _AsyncLimitsProvider(
        ProviderIdentity("first", "protocol", "remote-one"),
        TEST_LIMITS,
    )
    application = UthCodeApplication(provider)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", RuntimeWarning)
        handle = application.start_generation(_request("discard"))
        del handle
        gc.collect()

    assert provider.resolved_models == []
    assert not any("never awaited" in str(item.message) for item in caught)


@pytest.mark.asyncio
async def test_cancelled_async_limits_handle_does_not_resolve_or_stream() -> None:
    provider = _AsyncLimitsProvider(
        ProviderIdentity("first", "protocol", "remote-one"),
        TEST_LIMITS,
    )
    application = UthCodeApplication(provider)
    handle = application.start_generation(_request("cancel"))

    assert handle.cancel() is True
    with pytest.raises(GenerationCancelled):
        await _collect(handle)

    assert provider.resolved_models == []
    assert provider.recorded_requests == ()


@pytest.mark.asyncio
async def test_async_limits_handle_resolves_once_when_prepared_then_streamed() -> None:
    provider = _AsyncLimitsProvider(
        ProviderIdentity("first", "protocol", "remote-one"),
        TEST_LIMITS,
    )
    application = UthCodeApplication(provider)
    handle = application.start_generation(_request("once"))

    assert await asyncio.gather(handle, handle) == [handle, handle]
    events = await _collect(handle)

    assert isinstance(events[-1], GenerationCompleted)
    assert provider.resolved_models == ["remote-one"]
    assert len(provider.recorded_requests) == 1


@pytest.mark.asyncio
async def test_handle_cancel_cancels_owned_async_limits_preparation() -> None:
    provider = _BlockingAsyncLimitsProvider(
        ProviderIdentity("first", "protocol", "remote-one"),
        TEST_LIMITS,
    )
    application = UthCodeApplication(provider)
    handle = application.start_generation(_request("cancel-preparation"))
    consumer = asyncio.create_task(_collect(handle))

    await provider.started.wait()
    assert handle.cancel() is True

    with pytest.raises(GenerationCancelled):
        await asyncio.wait_for(consumer, timeout=1)

    assert provider.cancelled_count == 1
    assert provider.recorded_requests == ()
    assert handle._preparation_task is None  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_waiter_cancellation_does_not_cancel_shared_preparation_or_events() -> None:
    provider = _BlockingAsyncLimitsProvider(
        ProviderIdentity("first", "protocol", "remote-one"),
        TEST_LIMITS,
    )
    application = UthCodeApplication(provider)
    handle = application.start_generation(_request("waiter-cancel"))
    events_task = asyncio.create_task(_collect(handle))
    await provider.started.wait()

    waiter_task = asyncio.create_task(_await_handle(handle))
    await asyncio.sleep(0)
    assert not waiter_task.done()
    waiter_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter_task

    assert handle.cancelled is False
    provider.release.set()
    events = await events_task

    assert isinstance(events[-1], GenerationCompleted)
    assert provider.resolved_models == ["remote-one"]
    assert len(provider.recorded_requests) == 1
    assert handle.cancelled is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "expected"),
    [("provider", RuntimeError), ("cancelled", GenerationCancelled)],
)
async def test_async_limits_preparation_closes_resolver_failures(
    failure: str,
    expected: type[BaseException],
) -> None:
    error: BaseException = (
        RuntimeError("limits failed")
        if failure == "provider"
        else asyncio.CancelledError()
    )
    provider = _FailingAsyncLimitsProvider(
        ProviderIdentity("first", "protocol", "remote-one"),
        TEST_LIMITS,
        error,
    )
    application = UthCodeApplication(provider)
    handle = application.start_generation(_request("resolver-error"))

    with pytest.raises(expected):
        await _collect(handle)

    assert provider.resolved_models == ["remote-one"]
    assert provider.recorded_requests == ()
    assert handle._preparation_task is None  # type: ignore[attr-defined]


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
                model.remote_id,
            ),
            events=(_completed(model.remote_id),),
            model_limits=TEST_LIMITS,
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
    assert "模型选择：one/ref" in _request_text(old_provider.recorded_requests[0])
    assert "Provider 协议：protocol-one/ref" in _request_text(old_provider.recorded_requests[0])
    assert "远端模型：remote-one" in _request_text(old_provider.recorded_requests[0])


def test_create_application_injection_receives_application_profiles() -> None:
    config = EffectiveConfig.single_model(
        "profile/ref",
        provider_profile_id="profile",
        provider_kind=ProviderKind.FAKE,
        remote_id="remote-id",
        max_output_tokens=321,
    )
    seen: list[tuple[ProviderProfile, ModelProfile]] = []

    def build(provider: ProviderProfile, model: ModelProfile) -> FakeProvider:
        seen.append((provider, model))
        return FakeProvider(
            identity=ProviderIdentity("fake", "script", "remote-id"),
            events=(_completed(),),
            model_limits=TEST_LIMITS,
        )

    application = create_application(config, provider_builder=build)

    assert application.provider.identity.model == "remote-id"
    assert len(seen) == 1
    provider, model = seen[0]
    assert provider.provider_profile_id == "profile"
    assert model.model_ref == "profile/ref"
    assert model.remote_id == "remote-id"
    assert model.max_output_tokens == 321


def test_bootstrap_passes_max_output_tokens_to_integration_provider_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from uthcode.integrations.providers import factory as provider_factory

    config = EffectiveConfig.single_model(
        "profile/ref",
        provider_profile_id="profile",
        provider_kind=ProviderKind.FAKE,
        remote_id="remote-id",
        max_output_tokens=321,
    )
    seen: list[object] = []

    def observe(provider_config: object) -> FakeProvider:
        seen.append(provider_config)
        return FakeProvider(
            identity=ProviderIdentity("fake", "script", "remote-id"),
            events=(_completed(),),
            model_limits=TEST_LIMITS,
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
        return FakeProvider(events=(_completed(),), model_limits=TEST_LIMITS)

    with pytest.raises(TypeError):
        create_application(config, provider_builder=build)  # type: ignore[arg-type]
