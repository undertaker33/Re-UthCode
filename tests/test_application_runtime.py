from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from uthcode.application import (
    ApplicationMode,
    ApplicationSessionService,
    ApplicationRuntimeContext,
    ConfigSource,
    EffectiveConfig,
    ModelProfile,
    ProviderKind,
    ProviderProfile,
    SearchConfiguration,
    SessionOperationError,
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
    ReasoningDelta,
    ToolCallPart,
    ToolResultPart,
    TextDelta,
    TextPart,
    Usage,
)
from uthcode.core.permission import PermissionMode
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


@pytest.mark.asyncio
async def test_failed_turn_visible_content_and_stable_reason_survive_restart(
    tmp_path: Path,
) -> None:
    storage_root = tmp_path / "sessions"
    service = ApplicationSessionService(
        storage_root=storage_root,
        project_key="project",
        instruction_loader=None,
    )
    provider = FakeProvider(
        events=(ReasoningDelta("正在分析"), TextDelta("部分回答")),
        model_limits=TEST_LIMITS,
    )
    application = UthCodeApplication(provider, session_service=service)
    session = application.create_session("failed-session")

    result = await application.create_run().start_turn("触发失败").result()

    assert result.status.value == "failed"
    assert result.failure_reason is not None
    session_id = session.session_id
    application.close()

    restarted_service = ApplicationSessionService(
        storage_root=storage_root,
        project_key="project",
        instruction_loader=None,
    )
    recovery_provider = FakeProvider(
        events=(_completed("unused"),), model_limits=TEST_LIMITS
    )
    restarted = UthCodeApplication(
        recovery_provider,
        session_service=restarted_service,
    )
    resumed = restarted.resume_session(session_id)

    assert [(record.kind, record.text) for record in resumed.replay] == [
        ("user", "触发失败"),
        ("reasoning", "正在分析"),
        ("assistant", "部分回答"),
        ("failure", ""),
    ]
    failure = resumed.replay[-1]
    assert failure.termination_reason == "invalid_provider_response"
    assert failure.failure_reason == "invalid_provider_response"
    raw_history = (
        restarted_service.store.session_path(session_id) / "transcript.jsonl"
    ).read_text(encoding="utf-8")
    assert "Provider stream ended" not in raw_history
    await restarted.create_run().start_turn("继续").result()
    recovered_request = recovery_provider.recorded_requests[0]
    recovered_text = repr(
        tuple(message.to_dict() for message in recovered_request.messages)
    )
    assert "触发失败" in recovered_text
    assert "正在分析" not in recovered_text
    assert "部分回答" not in recovered_text
    restarted.close()


def test_runtime_context_and_model_status_are_stable_values(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
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
    try:
        environment = application._environment_sources(  # type: ignore[attr-defined]
            "one/ref",
            ProviderIdentity("local", "script", "remote-one"),
        )
        assert len(environment) == 1
        assert "[显示名](artifact:相对路径)" in environment[0].content
        assert "保留字符按界面协议 percent-encode" in environment[0].content
        assert "不扩大外部路径授权" in environment[0].content
    finally:
        application.close()


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


def test_streaming_context_delta_remains_an_estimate_without_provider_override(
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

    current = application.context_service.context_status
    assert current.measurement == "estimate"
    assert current.source == "live_delta"
    assert current.used_tokens == after.used_tokens
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


@pytest.mark.asyncio
async def test_general_application_isolated_tools_across_create_reload_and_recovery(
    tmp_path: Path,
) -> None:
    project = tmp_path / "coding-project"
    project.mkdir()
    (project / "AGENTS.md").write_text("coding-only instruction", encoding="utf-8")
    storage_root = tmp_path / "sessions"
    config = _config(tmp_path)
    context = ApplicationRuntimeContext.from_system(workdir=project)

    application = create_application(
        config,
        provider_builder=_builder,
        runtime_context=context,
        storage_root=storage_root,
        application_mode=ApplicationMode.GENERAL,
    )
    assert application.application_mode is ApplicationMode.GENERAL
    assert application.session_service is not None
    assert application.session_service.project_key == "uthcode:general"
    assert application.instruction_loader is not None
    assert application.instruction_loader.project_root is None
    assert [item.name for item in application.tool_definitions()] == [
        "WebFetch",
        "ToolResultRead",
    ]
    assert [item.name for item in application._agent_tool_definitions()] == [
        "WebFetch",
        "ToolResultRead",
    ]
    session = application.create_session("general-session")
    assert session.project_key == "uthcode:general"

    first_result = await application.create_run().start_turn("hello").result()
    assert first_result.final_text == "remote-one"
    first_request = application.provider.recorded_requests[-1]
    assert [item.name for item in first_request.tools] == [
        "WebFetch",
        "ToolResultRead",
    ]
    assert "日常文本交流" in first_request.system_prompt
    assert "coding-only instruction" not in first_request.system_prompt
    assert str(project) not in first_request.system_prompt

    application.reload_configuration(config)
    assert [item.name for item in application.tool_definitions()] == [
        "WebFetch",
        "ToolResultRead",
    ]
    second_result = await application.create_run().start_turn("again").result()
    assert second_result.final_text == "remote-one"
    assert [
        item.name for item in application.provider.recorded_requests[-1].tools
    ] == ["WebFetch", "ToolResultRead"]
    application.close()

    recovered = create_application(
        config,
        provider_builder=_builder,
        runtime_context=context,
        storage_root=storage_root,
        application_mode="general",
    )
    resumed = recovered.resume_session("general-session")
    assert resumed.project_key == "uthcode:general"
    assert [item.name for item in recovered.tool_definitions()] == [
        "WebFetch",
        "ToolResultRead",
    ]
    restart_result = await recovered.create_run().start_turn("after restart").result()
    assert restart_result.final_text == "remote-one"
    restart_request = recovered.provider.recorded_requests[-1]
    assert [item.name for item in restart_request.tools] == [
        "WebFetch",
        "ToolResultRead",
    ]
    assert "日常文本交流" in restart_request.system_prompt
    assert "coding-only instruction" not in restart_request.system_prompt
    recovered.close()

    coding = create_application(
        config,
        provider_builder=_builder,
        runtime_context=context,
        storage_root=storage_root,
    )
    assert coding.tool_definitions()
    assert coding.instruction_loader is not None
    assert coding.instruction_loader.project_root == project.resolve()
    with pytest.raises(SessionOperationError):
        coding.resume_session("general-session")
    coding.close()


@pytest.mark.asyncio
async def test_general_search_tools_follow_user_configuration_on_create_reload_and_restart(
    tmp_path: Path,
) -> None:
    project = tmp_path / "coding-project"
    project.mkdir()
    (project / "AGENTS.md").write_text("coding-only instruction", encoding="utf-8")
    runtime_context = ApplicationRuntimeContext.from_system(workdir=project)
    enabled_config = replace(
        _config(tmp_path),
        search=SearchConfiguration(enabled=True, api_key="isolated-search-key"),
    )
    disabled_config = replace(
        enabled_config,
        search=SearchConfiguration(enabled=True, api_key=None),
    )
    storage_root = tmp_path / "sessions"

    application = create_application(
        enabled_config,
        provider_builder=_builder,
        runtime_context=runtime_context,
        storage_root=storage_root,
        web_transport=object(),
        application_mode=ApplicationMode.GENERAL,
    )
    try:
        assert [item.name for item in application.tool_definitions()] == [
            "WebFetch",
            "WebSearch",
            "ToolResultRead",
        ]
        result = await application.create_run().start_turn("search the public web").result()
        assert result.final_text == "remote-one"
        request = application.provider.recorded_requests[-1]
        assert [item.name for item in request.tools] == [
            "WebFetch",
            "WebSearch",
            "ToolResultRead",
        ]
        assert "coding-only instruction" not in request.system_prompt
        assert str(project) not in request.system_prompt

        application.reload_configuration(disabled_config)
        assert [item.name for item in application.tool_definitions()] == [
            "WebFetch",
            "ToolResultRead",
        ]
        await application.create_run().start_turn("search is now disabled").result()
        assert [
            item.name for item in application.provider.recorded_requests[-1].tools
        ] == ["WebFetch", "ToolResultRead"]
    finally:
        application.close()

    recovered = create_application(
        enabled_config,
        provider_builder=_builder,
        runtime_context=runtime_context,
        storage_root=storage_root,
        web_transport=object(),
        application_mode=ApplicationMode.GENERAL,
    )
    try:
        assert [item.name for item in recovered.tool_definitions()] == [
            "WebFetch",
            "WebSearch",
            "ToolResultRead",
        ]
        await recovered.create_run().start_turn("search after restart").result()
        assert [
            item.name for item in recovered.provider.recorded_requests[-1].tools
        ] == ["WebFetch", "WebSearch", "ToolResultRead"]
    finally:
        recovered.close()


@pytest.mark.asyncio
async def test_general_executes_existing_search_through_local_http_fixture(
    tmp_path: Path,
) -> None:
    class _SearchProvider(FakeProvider):
        async def stream(self, request, *, cancellation):  # type: ignore[no-untyped-def]
            self.requests.append(request)
            cancellation.raise_if_cancelled()
            if len(self.requests) == 1:
                call = ToolCallPart(
                    "general-search-call",
                    "WebSearch",
                    {"query": "fixture query", "max_results": 1},
                )
                yield GenerationCompleted(
                    ProviderResponse(
                        message=Message("assistant", (call,)),
                        finish_reason=FinishReason.TOOL_CALLS,
                        usage=Usage(),
                    )
                )
                return
            assert any(
                isinstance(part, ToolResultPart)
                for message in request.messages
                for part in message.parts
            )
            yield _completed("GENERAL_SEARCH_FIXTURE_COMPLETED")

    search_provider = _SearchProvider(
        identity=ProviderIdentity("local", "fixture", "remote-one"),
        model_limits=TEST_LIMITS,
    )
    captured: list[dict[str, object]] = []

    def handle_search(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "answer": "not projected",
                "results": [
                    {
                        "title": "Fixture result",
                        "url": "https://example.com/public",
                        "content": "GENERAL_SEARCH_RESULT_MARKER",
                    }
                ],
                "usage": {"credits": 1},
            },
            request=request,
        )

    config = replace(
        _config(tmp_path),
        sources=(ConfigSource("user", tmp_path / ".uthcode" / "config.toml"),),
        search=SearchConfiguration(enabled=True, api_key="isolated-search-key"),
    )
    application = create_application(
        config,
        provider_builder=lambda _profile, _model: search_provider,
        runtime_context=ApplicationRuntimeContext.from_system(workdir=tmp_path),
        storage_root=tmp_path / "sessions",
        web_transport=httpx.MockTransport(handle_search),
        application_mode=ApplicationMode.GENERAL,
    )
    try:
        run = application.create_run()
        run.set_permission_mode(PermissionMode.FULL_ACCESS)
        result = await run.start_turn("Search the public web for the fixture query").result()
        assert result.final_text == "GENERAL_SEARCH_FIXTURE_COMPLETED"
        assert len(captured) == 1
        assert captured[0]["api_key"] == "isolated-search-key"
        assert captured[0]["search_depth"] == "basic"
        assert captured[0]["include_answer"] is False
        assert captured[0]["query"] == "fixture query"
        assert [tool.name for tool in search_provider.recorded_requests[0].tools] == [
            "WebFetch",
            "WebSearch",
            "ToolResultRead",
        ]
        tool_results = [
            part
            for message in search_provider.recorded_requests[-1].messages
            for part in message.parts
            if isinstance(part, ToolResultPart)
        ]
        assert tool_results
        assert "GENERAL_SEARCH_RESULT_MARKER" in repr(tool_results)
        assert "not projected" not in repr(tool_results)
        assert "isolated-search-key" not in repr(result)
        assert "isolated-search-key" not in repr(application.diagnostics())
    finally:
        application.close()


@pytest.mark.asyncio
async def test_general_webfetch_large_result_is_readable_and_recovers_from_session(
    tmp_path: Path,
) -> None:
    late_marker = "GENERAL_WEBFETCH_LATE_BODY_MARKER"

    class _FetchProvider(FakeProvider):
        async def stream(self, request, *, cancellation):  # type: ignore[no-untyped-def]
            self.requests.append(request)
            cancellation.raise_if_cancelled()
            assert [item.name for item in request.tools] == [
                "WebFetch",
                "ToolResultRead",
            ]
            if len(self.requests) == 1:
                call = ToolCallPart(
                    "general-webfetch-call",
                    "WebFetch",
                    {"url": "https://example.com/large", "max_bytes": 50_000},
                )
            elif len(self.requests) == 2:
                fetched = next(
                    part
                    for message in request.messages
                    for part in message.parts
                    if isinstance(part, ToolResultPart)
                    and part.tool_call_id == "general-webfetch-call"
                )
                assert fetched.metadata["persistence_status"] == "externalized"
                assert "Use ToolResultRead" in str(fetched.content)
                reference = fetched.metadata["ref"]
                call = ToolCallPart(
                    "general-webfetch-read-1",
                    "ToolResultRead",
                    {"ref": reference, "offset": 0, "limit": 2048},
                )
            elif len(self.requests) == 3:
                first_page_result = next(
                    part
                    for message in request.messages
                    for part in message.parts
                    if isinstance(part, ToolResultPart)
                    and part.tool_call_id == "general-webfetch-read-1"
                )
                first_page = json.loads(str(first_page_result.content))
                assert first_page["offset"] == 0
                assert late_marker not in first_page["content"]
                call = ToolCallPart(
                    "general-webfetch-read-2",
                    "ToolResultRead",
                    {
                        "ref": first_page["ref"],
                        "offset": first_page["next_offset"],
                        "limit": 2048,
                    },
                )
            elif len(self.requests) == 4:
                second_page_result = next(
                    part
                    for message in request.messages
                    for part in message.parts
                    if isinstance(part, ToolResultPart)
                    and part.tool_call_id == "general-webfetch-read-2"
                )
                second_page = json.loads(str(second_page_result.content))
                assert second_page["offset"] > 0
                assert late_marker in second_page["content"]
                yield _completed("GENERAL_WEBFETCH_FIXTURE_COMPLETED")
                return
            else:
                raise AssertionError("unexpected General WebFetch Provider request")
            yield GenerationCompleted(
                ProviderResponse(
                    message=Message("assistant", (call,)),
                    finish_reason=FinishReason.TOOL_CALLS,
                    usage=Usage(),
                )
            )

    body = "x" * 2400 + late_marker + "z" * 9000
    fetch_provider = _FetchProvider(
        identity=ProviderIdentity("local", "fixture", "remote-one"),
        model_limits=TEST_LIMITS,
    )

    def handle_fetch(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://example.com/large"
        return httpx.Response(
            200,
            content=body.encode("utf-8"),
            headers={"content-type": "text/plain; charset=utf-8"},
            request=request,
        )

    config = _config(tmp_path)
    runtime_context = ApplicationRuntimeContext.from_system(workdir=tmp_path)
    storage_root = tmp_path / "sessions"
    application = create_application(
        config,
        provider_builder=lambda _profile, _model: fetch_provider,
        runtime_context=runtime_context,
        storage_root=storage_root,
        web_transport=httpx.MockTransport(handle_fetch),
        application_mode=ApplicationMode.GENERAL,
    )
    session_id = "general-webfetch-session"
    try:
        application.create_session(session_id)
        run = application.create_run()
        run.set_permission_mode(PermissionMode.FULL_ACCESS)
        result = await run.start_turn("Read the full public fixture page").result()
        assert result.final_text == "GENERAL_WEBFETCH_FIXTURE_COMPLETED"
        assert len(fetch_provider.recorded_requests) == 4
        assert all(
            [item.name for item in request.tools] == ["WebFetch", "ToolResultRead"]
            for request in fetch_provider.recorded_requests
        )
        history = application.session_history_page(session_id)
        output_record = next(
            record
            for record in history.records
            if record.kind == "tool" and record.output_ref is not None
        )
        reference = output_record.output_ref
        assert reference is not None
        first_page = application.read_tool_result_page(
            session_id,
            reference,
            offset=0,
            limit=2048,
        )
        assert first_page.eof is False
        second_page = application.read_tool_result_page(
            session_id,
            reference,
            offset=first_page.next_offset,
            limit=2048,
        )
        assert late_marker in second_page.content
        assert second_page.ref == reference
    finally:
        application.close()

    recovered = create_application(
        config,
        provider_builder=_builder,
        runtime_context=runtime_context,
        storage_root=storage_root,
        web_transport=httpx.MockTransport(handle_fetch),
        application_mode=ApplicationMode.GENERAL,
    )
    try:
        recovered.resume_session(session_id)
        assert [item.name for item in recovered.tool_definitions()] == [
            "WebFetch",
            "ToolResultRead",
        ]
        recovered_page = recovered.read_tool_result_page(
            session_id,
            reference,
            offset=first_page.next_offset,
            limit=2048,
        )
        assert late_marker in recovered_page.content
        assert recovered_page.ref == reference
    finally:
        recovered.close()
