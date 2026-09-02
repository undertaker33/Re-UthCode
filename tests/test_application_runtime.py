from __future__ import annotations

from dataclasses import replace
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
from uthcode.integrations.session_files import SessionWriter


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


def test_session_models_are_independent_from_the_persisted_new_session_default(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    writes: list[str] = []
    application = create_application(
        config,
        provider_builder=_builder,
        model_writer=writes.append,
        runtime_context=ApplicationRuntimeContext.from_system(workdir=tmp_path),
        storage_root=tmp_path / "sessions",
    )

    session_a = application.new_session_for_command()
    assert session_a.model_ref == "one/ref"
    session_a_id = session_a.session_id
    session_b = application.new_session_for_command()
    assert session_b.model_ref == "one/ref"
    application.select_model("two/ref")
    assert session_b.model_ref == "two/ref"

    # Reopening A changes only the active provider.  B's preference remains
    # durable and the most recently selected model remains the new-session
    # default.
    assert application.session_service is not None
    assert application.session_service.read_session(session_a_id).metadata.model_ref == "one/ref"
    application.resume_session_for_command(session_a_id)
    assert application.current_model_ref == "one/ref"
    session_c = application.new_session_for_command()
    assert session_c.model_ref == "two/ref"
    assert writes[-1] == "two/ref"

    application.close()
    restarted_config = replace(config, default_model=writes[-1])
    restarted = create_application(
        restarted_config,
        provider_builder=_builder,
        model_writer=writes.append,
        runtime_context=ApplicationRuntimeContext.from_system(workdir=tmp_path),
        storage_root=tmp_path / "sessions",
    )
    session_d = restarted.new_session_for_command()
    assert session_d.model_ref == "two/ref"
    restarted.close()


def test_model_selection_rolls_back_session_and_context_when_commit_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writes: list[str] = []
    application = create_application(
        _config(tmp_path),
        provider_builder=_builder,
        model_writer=writes.append,
        runtime_context=ApplicationRuntimeContext.from_system(workdir=tmp_path),
        storage_root=tmp_path / "sessions",
    )
    session = application.new_session_for_command()
    assert application.session_service is not None
    original_refresh = application._refresh_context_for_session

    def fail_refresh(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("context commit failed")

    monkeypatch.setattr(application, "_refresh_context_for_session", fail_refresh)
    with pytest.raises(RuntimeError, match="context commit failed"):
        application.select_model("two/ref")
    monkeypatch.setattr(application, "_refresh_context_for_session", original_refresh)

    assert application.current_model_ref == "one/ref"
    assert application._default_model_ref == "one/ref"
    assert session.model_ref == "one/ref"
    assert application.session_service.read_session(session.session_id).metadata.model_ref == "one/ref"
    assert writes == ["two/ref", "one/ref"]
    application.close()


def test_model_selection_metadata_failure_does_not_publish_a_split_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writes: list[str] = []
    application = create_application(
        _config(tmp_path),
        provider_builder=_builder,
        model_writer=writes.append,
        runtime_context=ApplicationRuntimeContext.from_system(workdir=tmp_path),
        storage_root=tmp_path / "sessions",
    )
    session = application.new_session_for_command()
    original_update = SessionWriter.update_model_ref

    def fail_target(writer: SessionWriter, model_ref: str | None) -> object:
        if model_ref == "two/ref":
            raise OSError("metadata write failed")
        return original_update(writer, model_ref)

    monkeypatch.setattr(SessionWriter, "update_model_ref", fail_target)
    with pytest.raises(OSError, match="metadata write failed"):
        application.select_model("two/ref")

    assert application.current_model_ref == "one/ref"
    assert application._default_model_ref == "one/ref"
    assert session.model_ref == "one/ref"
    assert writes == ["two/ref", "one/ref"]
    application.close()


def test_streaming_context_delta_is_an_estimate_until_provider_usage_corrects_it(
    tmp_path: Path,
) -> None:
    application = create_application(
        _config(tmp_path),
        provider_builder=_builder,
        runtime_context=ApplicationRuntimeContext.from_system(workdir=tmp_path),
        storage_root=tmp_path / "sessions",
    )
    application.new_session_for_command()
    before = application.context_service.context_status
    application.record_live_context_delta("assistant 流式中文 delta", source="live_delta")
    after = application.context_service.context_status
    assert after.available is True
    assert after.measurement == "estimate"
    assert after.source == "live_delta"
    assert after.used_tokens > before.used_tokens

    application.context_service.record_exact_usage(after.used_tokens + 3)
    corrected = application.context_service.context_status
    assert corrected.measurement == "exact"
    assert corrected.used_tokens == after.used_tokens + 3
    application.close()


def _application_with_luna_current_and_sol_new_default(
    tmp_path: Path,
) -> tuple[UthCodeApplication, str, set[str]]:
    """Build the A/B state where a fresh Session must use Sol while A is Luna."""

    writes: list[str] = []
    application = create_application(
        _config(tmp_path),
        provider_builder=_builder,
        model_writer=writes.append,
        runtime_context=ApplicationRuntimeContext.from_system(workdir=tmp_path),
        storage_root=tmp_path / "sessions",
    )
    session_a = application.new_session_for_command()
    session_a_id = session_a.session_id
    session_a.close()
    session_b = application.new_session_for_command()
    application.select_model("two/ref")
    session_b.close()
    application.resume_session_for_command(session_a_id)
    application.close()
    assert application.session_service is not None
    existing = {entry.session_id for entry in application.session_catalog()}
    assert application.current_model_ref == "one/ref"
    assert application._default_model_ref == "two/ref"
    return application, session_a_id, existing


def test_new_session_model_preflight_rejects_provider_failure_before_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application, _session_a_id, existing = _application_with_luna_current_and_sol_new_default(tmp_path)
    assert application.session_service is not None

    def fail_builder(_provider: ProviderProfile, _model: ModelProfile) -> FakeProvider:
        raise RuntimeError("provider construction failed")

    monkeypatch.setattr(application, "_provider_builder", fail_builder)
    with pytest.raises(RuntimeError, match="provider construction failed"):
        application.new_session_for_command()

    assert application.session_service.active_session is None
    assert {entry.session_id for entry in application.session_catalog()} == existing
    assert application.current_model_ref == "one/ref"
    assert application._default_model_ref == "two/ref"
    application.close()


def test_new_session_context_preflight_rejects_failure_before_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application, _session_a_id, existing = _application_with_luna_current_and_sol_new_default(tmp_path)
    assert application.session_service is not None

    def fail_compile(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("context preflight failed")

    monkeypatch.setattr(application.context_service, "compile", fail_compile)
    with pytest.raises(RuntimeError, match="context preflight failed"):
        application.new_session_for_command()

    assert application.session_service.active_session is None
    assert {entry.session_id for entry in application.session_catalog()} == existing
    assert application.current_model_ref == "one/ref"
    assert application._default_model_ref == "two/ref"
    application.close()


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
