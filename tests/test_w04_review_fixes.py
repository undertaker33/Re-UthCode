from __future__ import annotations

import asyncio
import json
import sys
import tomllib
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest

from uthcode.application import (
    ApplicationRuntimeContext,
    EffectiveConfig,
    ModelProfile,
    PermissionApprovalChoice,
    PermissionApprovalResponse,
    PermissionMode,
    ProviderKind,
    ProviderProfile,
    SearchConfiguration,
    TextPart,
    create_application,
    load_effective_config,
    write_user_configuration,
)
from uthcode.core.agent_events import TurnPaused
from uthcode.core.permission import PermissionAction
from uthcode.core.provider import (
    CancellationToken,
    FinishReason,
    GenerationCompleted,
    GenerationRequest,
    Message,
    ModelLimits,
    ProviderEvent,
    ProviderIdentity,
    ProviderResponse,
    TextPart as ProviderTextPart,
    ToolCallPart,
    Usage,
)
from uthcode.integrations.tools.process_sessions import ProcessSessionManager
from uthcode.interfaces.desktop.bridge import DesktopBridge
from uthcode.interfaces.desktop.protocol import RequestEnvelope
import uthcode.interfaces.desktop.bridge as bridge_module


def _response(
    *parts: object,
    finish_reason: FinishReason = FinishReason.STOP,
) -> GenerationCompleted:
    return GenerationCompleted(
        ProviderResponse(
            message=Message("assistant", tuple(parts)),
            finish_reason=finish_reason,
            usage=Usage(),
        )
    )


class _ScriptedProvider:
    def __init__(self, scripts: Iterable[Iterable[ProviderEvent]]) -> None:
        self.identity = ProviderIdentity("fake", "w04-review", "fake-model")
        self.scripts = tuple(tuple(script) for script in scripts)
        self.requests: list[GenerationRequest] = []

    def resolve_model_limits(self, _model: str) -> ModelLimits:
        return ModelLimits(max_input_tokens=1_000_000, source="test.w04-review")

    async def stream(
        self,
        request: GenerationRequest,
        *,
        cancellation: CancellationToken,
    ) -> AsyncIterator[ProviderEvent]:
        self.requests.append(request)
        cancellation.raise_if_cancelled()
        index = min(len(self.requests) - 1, len(self.scripts) - 1)
        for event in self.scripts[index]:
            cancellation.raise_if_cancelled()
            yield event


def _config(*, search: SearchConfiguration | None = None) -> EffectiveConfig:
    return EffectiveConfig(
        default_model="local/ref",
        providers={"local": ProviderProfile("local", ProviderKind.FAKE)},
        models={
            "local/ref": ModelProfile("local/ref", "local", "fake-model"),
        },
        search=search,
    )


def _context(workdir: Path, manager: ProcessSessionManager | None = None) -> ApplicationRuntimeContext:
    return ApplicationRuntimeContext(
        workdir=workdir,
        platform_name="TestOS",
        platform_release="w04-review",
        current_date="2026-09-13",
        process_manager=manager,
    )


async def _collect(handle) -> list[object]:
    return [event async for event in handle.events()]


async def _wait_for_pause(handle):
    for _ in range(500):
        pending = handle.pending_pause
        if pending is not None:
            return pending
        await asyncio.sleep(0)
    raise AssertionError("Application did not publish the expected permission pause")


async def _wait_for_pause_clear(handle) -> None:
    for _ in range(500):
        if handle.pending_pause is None:
            return
        await asyncio.sleep(0)
    raise AssertionError("Application did not consume the permission response")


@pytest.mark.parametrize(
    ("key_expression", "environment_value"),
    [
        ("synthetic-search-key-for-test", None),
        ("env:UTHCODE_SYNTHETIC_SEARCH_KEY", "synthetic-search-key-for-test"),
    ],
    ids=("literal", "environment-reference"),
)
def test_settings_save_preserves_untouched_search_key_and_factory_registration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    key_expression: str,
    environment_value: str | None,
) -> None:
    home = tmp_path / "home"
    user_config = home / ".uthcode" / "config.toml"
    if environment_value is not None:
        monkeypatch.setenv("UTHCODE_SYNTHETIC_SEARCH_KEY", environment_value)

    write_user_configuration(
        {
            "default_model": "local/ref",
            "providers": {"local": {"kind": "fake"}},
            "models": {
                "local/ref": {
                    "provider_profile_id": "local",
                    "remote_id": "fake-model",
                }
            },
            "search": {
                "enabled": True,
                "provider": "tavily",
                "api_key": key_expression,
                "max_results": 5,
                "max_fetch_bytes": 4096,
                "timeout_seconds": 7.0,
            },
        },
        home=home,
    )

    # This is the production settings form shape: it carries ordinary Search
    # edits but deliberately omits the untouched secret field.
    write_user_configuration(
        {
            "search": {
                "enabled": True,
                "provider": "tavily",
                "max_results": 4,
                "max_fetch_bytes": 8192,
                "timeout_seconds": 8.0,
            }
        },
        home=home,
    )
    stored_search = tomllib.loads(user_config.read_text(encoding="utf-8")).get("search", {})
    assert stored_search.get("api_key") == key_expression
    effective = load_effective_config(cwd=tmp_path, home=home)
    assert effective.search is not None and effective.search.api_key is not None
    application = create_application(
        effective,
        runtime_context=_context(tmp_path),
        storage_root=tmp_path / "sessions",
    )
    try:
        assert "WebSearch" in {item.name for item in application.tool_definitions()}
    finally:
        application.close()

    # Disabling Search is independent from retaining its credential reference.
    write_user_configuration(
        {
            "search": {
                "enabled": False,
                "provider": "tavily",
                "max_results": 4,
                "max_fetch_bytes": 8192,
                "timeout_seconds": 8.0,
            }
        },
        home=home,
    )
    stored_search = tomllib.loads(user_config.read_text(encoding="utf-8")).get("search", {})
    assert stored_search.get("api_key") == key_expression
    disabled_application = create_application(
        load_effective_config(cwd=tmp_path, home=home),
        runtime_context=_context(tmp_path),
        storage_root=tmp_path / "disabled-sessions",
    )
    try:
        assert "WebSearch" not in {item.name for item in disabled_application.tool_definitions()}
    finally:
        disabled_application.close()

    # An explicitly blank value is the user's request to clear the key.
    write_user_configuration(
        {
            "search": {
                "enabled": True,
                "provider": "tavily",
                "api_key": "",
                "max_results": 4,
                "max_fetch_bytes": 8192,
                "timeout_seconds": 8.0,
            }
        },
        home=home,
    )
    cleared_search = tomllib.loads(user_config.read_text(encoding="utf-8")).get("search", {})
    assert "api_key" not in cleared_search
    cleared_application = create_application(
        load_effective_config(cwd=tmp_path, home=home),
        runtime_context=_context(tmp_path),
        storage_root=tmp_path / "cleared-sessions",
    )
    try:
        assert "WebSearch" not in {item.name for item in cleared_application.tool_definitions()}
    finally:
        cleared_application.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("reject_redirect", [False, True])
async def test_formal_application_redirect_approval_controls_each_http_hop(
    tmp_path: Path,
    reject_redirect: bool,
) -> None:
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        requested.append(url)
        if url.endswith("/start"):
            return httpx.Response(
                302,
                headers={"location": "https://example.com/final"},
                request=request,
            )
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text="<p>fixture final page</p>",
            request=request,
        )

    provider = _ScriptedProvider(
        (
            (
                _response(
                    ToolCallPart(
                        "fetch-call",
                        "WebFetch",
                        {"url": "https://example.com/start"},
                    ),
                    finish_reason=FinishReason.TOOL_CALLS,
                ),
            ),
            (_response(ProviderTextPart("turn complete")),),
        )
    )
    application = create_application(
        _config(),
        provider_builder=lambda _provider, _model: provider,
        runtime_context=_context(tmp_path),
        web_transport=httpx.MockTransport(handler),
    )
    run = application.create_run(run_id="redirect-application")
    handle = run.start_turn("fetch the fixture")
    events_task = asyncio.create_task(_collect(handle))

    approvals: list[PermissionAction] = []
    try:
        for index in range(2):
            pending = await _wait_for_pause(handle)
            assert isinstance(pending, object)
            assert pending.permission_request is not None
            request = pending.permission_request
            approvals.append(
                PermissionAction(
                    tool=request.tool,
                    action=request.action,
                    effect=request.effect,
                    resource=request.resource,
                    scope=request.scope,
                )
            )
            choice = (
                PermissionApprovalChoice.REJECT
                if reject_redirect and index == 1
                else PermissionApprovalChoice.ONCE
            )
            assert handle.resume(
                PermissionApprovalResponse(
                    pending.pause_id,
                    pending.run_id,
                    pending.turn_id,
                    request.permission_id,
                    choice,
                )
            )
            await _wait_for_pause_clear(handle)

        events = await asyncio.wait_for(events_task, timeout=2)
        result = await asyncio.wait_for(handle.result(), timeout=2)
    finally:
        await application.close_async()

    assert [action.action for action in approvals] == ["fetch", "redirect"]
    assert approvals[0].resource == "https://example.com/start"
    assert approvals[1].resource == "https://example.com/final"
    assert sum(isinstance(event, TurnPaused) for event in events) == 2
    assert result.final_text == "turn complete"
    assert requested == (
        ["https://example.com/start", "https://example.com/final"]
        if not reject_redirect
        else ["https://example.com/start"]
    )


@pytest.mark.asyncio
async def test_search_secret_is_redacted_from_application_event_history_and_artifact(
    tmp_path: Path,
) -> None:
    secret = "opaque-search-value-94"
    rows = [
        {
            "title": f"title {secret} {index}",
            "url": f"https://example.com/{index}",
            "content": f"reflected {secret} " + ("x" * 500),
        }
        for index in range(20)
    ]
    seen_payload: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_payload.update(json.loads(request.content))
        return httpx.Response(
            200,
            # The credential is reflected both as a value and as a JSON key;
            # the latter exercises the Application metadata projection path.
            json={"results": rows, "usage": {"note": secret, secret: secret}},
            request=request,
        )

    provider = _ScriptedProvider(
        (
            (
                _response(
                    ToolCallPart(
                        "search-call",
                        "WebSearch",
                        {"query": "fixture", "max_results": 20},
                    ),
                    finish_reason=FinishReason.TOOL_CALLS,
                ),
            ),
            (_response(ProviderTextPart("safe final")),),
        )
    )
    application = create_application(
        _config(
            search=SearchConfiguration(
                enabled=True,
                api_key=secret,
                max_results=20,
            )
        ),
        provider_builder=lambda _provider, _model: provider,
        runtime_context=_context(tmp_path),
        storage_root=tmp_path / "sessions",
        web_transport=httpx.MockTransport(handler),
    )
    application.ensure_session()
    run = application.create_run(run_id="search-secret-application")
    run.set_permission_mode(PermissionMode.FULL_ACCESS)
    handle = run.start_turn("search the fixture")
    try:
        events = await _collect(handle)
        result = await handle.result()
        session = application.session_service.active_session  # type: ignore[union-attr]
        assert session is not None
        history_text = json.dumps(session.snapshot.to_dict(), ensure_ascii=False)
        artifact_values: list[str] = []
        for path in (tmp_path / "sessions").rglob("*"):
            if not path.is_file():
                continue
            try:
                artifact_values.append(path.read_text(encoding="utf-8", errors="ignore"))
            except (OSError, PermissionError):
                continue
        artifact_text = "\n".join(artifact_values)
        tool_text = "\n".join(
            part.text
            for message in provider.requests[1].messages
            if message.role == "tool"
            for part in message.parts
            if isinstance(part, ProviderTextPart)
        )
        event_text = "\n".join(event.to_json() for event in events)
    finally:
        await application.close_async()

    assert seen_payload["search_depth"] == "basic"
    assert seen_payload["include_answer"] is False
    assert secret not in event_text
    assert secret not in result.to_json()
    assert secret not in tool_text
    assert secret not in history_text
    assert secret not in artifact_text
    assert "<redacted>" in (event_text + result.to_json() + history_text + artifact_text)
    assert application._tool_service.public_diagnostics()["externalization"]["externalized"] >= 1


@pytest.mark.asyncio
async def test_desktop_settings_save_reloads_search_for_next_turn_and_keeps_process_alive(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    user = home / ".uthcode" / "config.toml"
    user.parent.mkdir(parents=True)
    user.write_text(
        """default_model = \"local/ref\"\n\n[providers.local]\nkind = \"fake\"\n\n[models.\"local/ref\"]\nprovider = \"local\"\nremote_id = \"fake-model\"\n\n[search]\nenabled = false\n""",
        encoding="utf-8",
    )
    provider = _ScriptedProvider(((_response(ProviderTextPart("next turn")),),))
    manager = ProcessSessionManager()
    application = create_application(
        _config(),
        provider_builder=lambda _provider, _model: provider,
        runtime_context=_context(tmp_path, manager),
        storage_root=tmp_path / "sessions",
    )
    bridge = DesktopBridge(application=application, home=home, workdir=tmp_path)
    application.ensure_session()
    session = application.session_service.active_session  # type: ignore[union-attr]
    assert session is not None
    managed = await manager.start(
        session_id=session.session_id,
        command=f'"{sys.executable}" -c "import time; time.sleep(20)"',
        cwd=tmp_path,
    )
    process_id = managed.process_id
    manager_identity = id(manager)

    try:
        saved = await bridge.handle_request(
            RequestEnvelope(
                "settings-reload-search",
                "settings.save",
                {
                    "search": {
                        "enabled": True,
                        "provider": "tavily",
                        "api_key": "idle-save-secret",
                        "max_results": 3,
                        "max_fetch_bytes": 4096,
                        "timeout_seconds": 7.0,
                    },
                    "tool_limits": {
                        "timeout_seconds": 5.0,
                        "output_bytes": 4096,
                        "attachment_bytes": 8192,
                    },
                },
            )
        )
        assert saved.ok is True
        assert id(application.runtime_context.process_manager) == manager_identity
        assert manager.list(session.session_id)[0]["process_id"] == process_id
        assert manager.list(session.session_id)[0]["state"] == "running"
        assert application.configuration.search.enabled is True  # type: ignore[union-attr]
        assert application.configuration.search.max_results == 3  # type: ignore[union-attr]
        assert application.configuration.search.max_fetch_bytes == 4096  # type: ignore[union-attr]
        assert application.configuration.tool_limits.output_bytes == 4096  # type: ignore[union-attr]
        assert manager.max_output_bytes == 4096
        assert any(definition.name == "WebSearch" for definition in application.tool_definitions())

        handle = bridge.run.start_turn("verify the next turn tool view")  # type: ignore[union-attr]
        result = await handle.result()
        assert result.final_text == "next turn"
        assert any(definition.name == "WebSearch" for definition in provider.requests[-1].tools)
        assert id(application.runtime_context.process_manager) == manager_identity
        assert manager.list(session.session_id)[0]["state"] == "running"
    finally:
        await manager.stop(process_id, session.session_id)
        await bridge.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("reload_fails", [False, True], ids=("applied", "apply-failed"))
async def test_desktop_settings_save_keeps_active_turn_snapshot_then_applies_at_idle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reload_fails: bool,
) -> None:
    home = tmp_path / "home"
    user = home / ".uthcode" / "config.toml"
    user.parent.mkdir(parents=True)
    user.write_text(
        '''default_model = "local/ref"

[providers.local]
kind = "fake"

[models."local/ref"]
provider = "local"
remote_id = "fake-model"

[search]
enabled = false
''',
        encoding="utf-8",
    )
    started = asyncio.Event()
    release = asyncio.Event()

    class BlockingProvider(_ScriptedProvider):
        async def stream(self, request: GenerationRequest, *, cancellation: CancellationToken) -> AsyncIterator[ProviderEvent]:
            self.requests.append(request)
            cancellation.raise_if_cancelled()
            if len(self.requests) == 1:
                started.set()
                await release.wait()
            yield _response(ProviderTextPart(f"turn-{len(self.requests)}"))

    provider = BlockingProvider(())
    application = create_application(
        _config(),
        provider_builder=lambda _provider, _model: provider,
        runtime_context=_context(tmp_path),
        storage_root=tmp_path / "sessions",
    )
    if reload_fails:
        def fail_reload(_configuration: EffectiveConfig) -> None:
            raise RuntimeError("synthetic active-Turn application failure")

        monkeypatch.setattr(application, "reload_configuration", fail_reload)
    bridge = DesktopBridge(application=application, home=home, workdir=tmp_path)
    application.ensure_session()
    try:
        first = await bridge.handle_request(
            RequestEnvelope(
                "active-turn-start",
                "turn.start",
                {"prompt": "the current request keeps its original tools"},
            )
        )
        assert first.ok is True
        await asyncio.wait_for(started.wait(), timeout=2)
        assert not any(definition.name == "WebSearch" for definition in provider.requests[0].tools)

        saved = await bridge.handle_request(
            RequestEnvelope(
                "active-turn-settings-save",
                "settings.save",
                {"search": {"enabled": True, "provider": "tavily", "api_key": "turn-search-secret", "max_results": 2}},
            )
        )
        assert saved.ok is True and saved.result is not None
        assert saved.result["durable"] == "saved"
        assert saved.result["applications"] == {"applied": 0, "pending": 1, "failed": 0}
        assert application.configuration.search is None or application.configuration.search.enabled is False  # type: ignore[union-attr]

        release.set()
        await bridge.wait_for_idle()
        assert provider.requests[0].model == "fake-model"
        assert application.configuration.search.enabled is (not reload_fails)  # type: ignore[union-attr]
        events = [item.event for item in bridge.drain_outbox() if hasattr(item, "event")]
        turn_index = next(index for index, event in enumerate(events) if event.get("type") == "turn_completed")
        application_index = next(index for index, event in enumerate(events) if event.get("type") == "settings_applications")
        assert turn_index < application_index
        assert events[application_index] == {
            "type": "settings_applications",
            "applied": 0 if reload_fails else 1,
            "pending": 0,
            "failed": 1 if reload_fails else 0,
        }

        second = await bridge.handle_request(
            RequestEnvelope(
                "idle-turn-start",
                "turn.start",
                {"prompt": "the next request sees the applied tools"},
            )
        )
        assert second.ok is True
        await bridge.wait_for_idle()
        assert len(provider.requests) == 2
        assert any(definition.name == "WebSearch" for definition in provider.requests[-1].tools) is (not reload_fails)
    finally:
        release.set()
        await bridge.shutdown()


@pytest.mark.asyncio
async def test_settings_retry_apply_does_not_repeat_durable_writer_side_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    user = home / ".uthcode" / "config.toml"
    user.parent.mkdir(parents=True)
    user.write_text(
        '''default_model = "local/ref"

[providers.local]
kind = "fake"

[models."local/ref"]
provider = "local"
remote_id = "fake-model"
''',
        encoding="utf-8",
    )
    application = create_application(
        _config(),
        provider_builder=lambda _provider, _model: _ScriptedProvider(((_response(ProviderTextPart("unused")),),)),
        runtime_context=_context(tmp_path),
        storage_root=tmp_path / "sessions",
    )
    real_writer = bridge_module.write_user_configuration
    writes = 0

    def counted_writer(request: object, *, home: Path | None = None) -> object:
        nonlocal writes
        writes += 1
        return real_writer(request, home=home)  # type: ignore[arg-type]

    def fail_reload(_configuration: EffectiveConfig) -> None:
        raise RuntimeError("synthetic application reload failure")

    monkeypatch.setattr(bridge_module, "write_user_configuration", counted_writer)
    monkeypatch.setattr(application, "reload_configuration", fail_reload)
    bridge = DesktopBridge(application=application, home=home, workdir=tmp_path)
    try:
        saved = await bridge.handle_request(
            RequestEnvelope("failed-apply-save", "settings.save", {"default_permission_mode": "auto"})
        )
        assert saved.ok is True and saved.result is not None
        assert saved.result["durable"] == "saved"
        assert saved.result["applications"] == {"applied": 0, "pending": 0, "failed": 1}
        durable_text = user.read_text(encoding="utf-8")
        assert "default_permission_mode = \"auto\"" in durable_text
        assert writes == 1

        retried = await bridge.handle_request(RequestEnvelope("retry-apply-only", "settings.retry_apply", {}))
        assert retried.ok is True and retried.result is not None
        assert retried.result["applications"] == {"applied": 0, "pending": 0, "failed": 1}
        assert writes == 1, "retry_apply retries Application application only"
        assert user.read_text(encoding="utf-8") == durable_text
    finally:
        await bridge.shutdown()


@pytest.mark.asyncio
async def test_desktop_settings_save_reloads_idle_background_runtime_before_resume(
    tmp_path: Path,
) -> None:
    """A retained background Session must not resume an obsolete config."""

    home = tmp_path / "home"
    user = home / ".uthcode" / "config.toml"
    user.parent.mkdir(parents=True)
    user.write_text(
        """default_model = \"local/ref\"\ndefault_permission_mode = \"default\"\n\n[providers.local]\nkind = \"fake\"\n\n[models.\"local/ref\"]\nprovider = \"local\"\nremote_id = \"fake-model\"\n\n[search]\nenabled = false\n""",
        encoding="utf-8",
    )
    provider = _ScriptedProvider(((_response(ProviderTextPart("background next turn")),),))
    manager = ProcessSessionManager()
    application = create_application(
        _config(),
        provider_builder=lambda _provider, _model: provider,
        runtime_context=_context(tmp_path, manager),
        storage_root=tmp_path / "sessions",
    )
    bridge = DesktopBridge(application=application, home=home, workdir=tmp_path)
    application.ensure_session()
    first = application.session_service.active_session  # type: ignore[union-attr]
    assert first is not None
    managed = await manager.start(
        session_id=first.session_id,
        command=f'"{sys.executable}" -c "import time; time.sleep(20)"',
        cwd=tmp_path,
    )
    manager_identity = id(manager)
    first_application = application
    try:
        created = await bridge.handle_request(
            RequestEnvelope("background-new", "session.new", {})
        )
        assert created.ok is True
        second_id = created.result["session_id"]  # type: ignore[index]
        assert isinstance(second_id, str)
        assert bridge.application is not first_application
        assert first.session_id in bridge._background_runtimes
        retained = bridge._background_runtimes[first.session_id]
        assert retained["application"] is first_application

        saved = await bridge.handle_request(
            RequestEnvelope(
                "background-save",
                "settings.save",
                {
                    "default_permission_mode": "auto",
                    "search": {
                        "enabled": True,
                        "provider": "tavily",
                        "api_key": "background-save-secret",
                        "max_results": 2,
                        "max_fetch_bytes": 4096,
                        "timeout_seconds": 7.0,
                    },
                },
            )
        )
        assert saved.ok is True
        assert id(first_application.runtime_context.process_manager) == manager_identity
        assert first_application.configuration.search.enabled is True  # type: ignore[union-attr]
        assert first_application.configuration.search.max_results == 2  # type: ignore[union-attr]
        assert any(
            definition.name == "WebSearch"
            for definition in first_application.tool_definitions()
        )

        resumed = await bridge.handle_request(
            RequestEnvelope(
                "background-resume",
                "session.resume",
                {"session_id": first.session_id},
            )
        )
        assert resumed.ok is True
        assert bridge.application is first_application
        assert bridge.run.permission_mode.value == "auto"  # type: ignore[union-attr]
        assert manager.list(first.session_id)[0]["process_id"] == managed.process_id
        assert manager.list(first.session_id)[0]["state"] == "running"

        handle = bridge.run.start_turn("verify retained background runtime")  # type: ignore[union-attr]
        result = await handle.result()
        assert result.final_text == "background next turn"
        assert any(
            definition.name == "WebSearch"
            for definition in provider.requests[-1].tools
        )
    finally:
        if manager.list(first.session_id):
            await manager.stop(managed.process_id, first.session_id)
        await bridge.shutdown()


@pytest.mark.asyncio
async def test_process_projection_keeps_old_secret_until_child_retires(
    tmp_path: Path,
) -> None:
    """Reloading a shared manager cannot expose a live child's old secret."""

    old_secret = "old-process-secret-61"
    new_secret = "new-process-secret-72"
    manager = ProcessSessionManager()
    provider = _ScriptedProvider(((_response(ProviderTextPart("done")),),))
    application = create_application(
        _config(
            search=SearchConfiguration(
                enabled=True,
                api_key=old_secret,
                max_results=4,
            )
        ),
        provider_builder=lambda _provider, _model: provider,
        runtime_context=_context(tmp_path, manager),
        storage_root=tmp_path / "sessions",
    )
    application.ensure_session()
    session = application.session_service.active_session  # type: ignore[union-attr]
    assert session is not None
    observations: list[dict[str, object]] = []
    unsubscribe = application.subscribe_process_events(
        lambda value: observations.append(dict(value))
    )
    command = (
        f'"{sys.executable}" -c "import time; time.sleep(.15); '
        f"print('{old_secret}', flush=True); time.sleep(1)\""
    )
    managed = await manager.start(session_id=session.session_id, command=command, cwd=tmp_path)
    try:
        application.reload_configuration(
            _config(
                search=SearchConfiguration(
                    enabled=True,
                    api_key=new_secret,
                    max_results=2,
                )
            )
        )
        await manager.wait_for_output(managed, 2.0)
        read = manager.read(managed.process_id, session.session_id)
        listing = manager.list(session.session_id)
        event_text = json.dumps(observations, ensure_ascii=False)
        read_text = json.dumps([entry.text for entry in read.entries], ensure_ascii=False)
        command_text = json.dumps(listing, ensure_ascii=False)
        assert old_secret not in event_text
        assert old_secret not in read_text
        assert old_secret not in command_text
        assert "<redacted>" in (event_text + read_text + command_text)
        await manager.stop(managed.process_id, session.session_id)
        assert managed.output_projector is None
        assert managed.command_projector is None
        assert managed.projected_command is not None
    finally:
        unsubscribe()
        await application.close_async()


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["success", "failure", "cancelled"])
async def test_turn_terminal_without_configuration_patch_preserves_provider_and_full_access(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    outcome: str,
) -> None:
    home = tmp_path / "home"
    write_user_configuration(
        {
            "default_model": "local/ref",
            "default_permission_mode": "default",
            "providers": {"local": {"kind": "fake"}},
            "models": {"local/ref": {"provider_profile_id": "local", "remote_id": "fake-model"}},
        },
        home=home,
    )
    started = asyncio.Event()
    release = asyncio.Event()

    class FailingProvider(_ScriptedProvider):
        async def stream(self, request: GenerationRequest, *, cancellation: CancellationToken) -> AsyncIterator[ProviderEvent]:
            self.requests.append(request)
            raise RuntimeError("synthetic provider failure")
            if False:  # pragma: no cover - makes this an async generator
                yield _response(ProviderTextPart("unreachable"))

    class BlockingProvider(_ScriptedProvider):
        async def stream(self, request: GenerationRequest, *, cancellation: CancellationToken) -> AsyncIterator[ProviderEvent]:
            self.requests.append(request)
            started.set()
            while not release.is_set() and not cancellation.cancelled:
                await asyncio.sleep(0.005)
            cancellation.raise_if_cancelled()
            yield _response(ProviderTextPart("cancelled fixture"))

    provider: _ScriptedProvider
    if outcome == "failure":
        provider = FailingProvider(())
    elif outcome == "cancelled":
        provider = BlockingProvider(())
    else:
        provider = _ScriptedProvider(((_response(ProviderTextPart("completed fixture")),),))
    application = create_application(
        _config(),
        provider_builder=lambda _provider, _model: provider,
        runtime_context=_context(tmp_path),
        storage_root=tmp_path / "sessions",
    )
    reloads = 0
    real_reload = application.reload_configuration

    def counted_reload(configuration: EffectiveConfig) -> None:
        nonlocal reloads
        reloads += 1
        real_reload(configuration)

    monkeypatch.setattr(application, "reload_configuration", counted_reload)
    bridge = DesktopBridge(application=application, home=home, workdir=tmp_path)
    run = bridge.run
    assert run is not None
    run.set_permission_mode(PermissionMode.FULL_ACCESS)

    # A user-file change by another process is not an authorized Settings
    # write.  An empty safe-boundary drain must not reload it or reset Run mode.
    write_user_configuration(
        {
            "default_model": "disk/ref",
            "providers": {"local": None, "disk": {"kind": "fake"}},
            "models": {
                "local/ref": None,
                "disk/ref": {"provider_profile_id": "disk", "remote_id": "disk-model"},
            },
        },
        home=home,
    )

    try:
        started_reply = await bridge.handle_request(
            RequestEnvelope(f"no-patch-{outcome}", "turn.start", {"prompt": "exercise an idle drain"})
        )
        assert started_reply.ok is True
        if outcome == "cancelled":
            await asyncio.wait_for(started.wait(), timeout=2)
            cancelled = await bridge.handle_request(RequestEnvelope("no-patch-cancel", "turn.cancel", {}))
            assert cancelled.ok is True
        await bridge.wait_for_idle()

        assert reloads == 0
        assert application.configuration.default_model == "local/ref"  # type: ignore[union-attr]
        assert set(application.configuration.providers) == {"local"}  # type: ignore[union-attr]
        assert run.permission_mode is PermissionMode.FULL_ACCESS
        events = [item.event.get("type") for item in bridge.drain_outbox() if hasattr(item, "event")]
        assert "settings_applications" not in events
        if outcome == "success":
            assert "turn_completed" in events
        elif outcome == "failure":
            assert "turn_failed" in events
        else:
            assert "turn_cancelled" in events
    finally:
        release.set()
        await bridge.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("first_terminal", ["turn", "compact"], ids=("turn-first", "compact-first"))
async def test_owner_terminal_drains_without_save_do_not_create_cross_owner_pending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    first_terminal: str,
) -> None:
    home = tmp_path / "home"
    project_a = tmp_path / "project-a"
    project_b = tmp_path / "project-b"
    project_a.mkdir()
    project_b.mkdir()
    write_user_configuration(
        {
            "default_model": "local/ref",
            "default_permission_mode": "default",
            "providers": {"local": {"kind": "fake"}},
            "models": {"local/ref": {"provider_profile_id": "local", "remote_id": "fake-model"}},
        },
        home=home,
    )
    turn_started = asyncio.Event()
    release_turn = asyncio.Event()
    compact_started = asyncio.Event()
    release_compact = asyncio.Event()

    class BlockingProvider(_ScriptedProvider):
        async def stream(
            self,
            request: GenerationRequest,
            *,
            cancellation: CancellationToken,
        ) -> AsyncIterator[ProviderEvent]:
            self.requests.append(request)
            turn_started.set()
            await release_turn.wait()
            cancellation.raise_if_cancelled()
            yield _response(ProviderTextPart("background turn completed"))

    turn_provider = BlockingProvider(())

    def make_application(path: Path) -> object:
        selected_provider = turn_provider if path.resolve() == project_a.resolve() else _ScriptedProvider(())
        return create_application(
            load_effective_config(cwd=path, home=home),
            provider_builder=lambda _provider, _model: selected_provider,
            runtime_context=_context(path),
            storage_root=tmp_path / "sessions" / path.name,
        )

    application_a = make_application(project_a)
    application_a.ensure_session()
    session_a = application_a.session_service.active_session  # type: ignore[union-attr]
    assert session_a is not None
    bridge = DesktopBridge(
        application=application_a,
        application_factory=make_application,
        home=home,
        workdir=project_a,
    )
    run_a = bridge.run
    assert run_a is not None
    run_a.set_permission_mode(PermissionMode.FULL_ACCESS)
    reload_counts = {"a": 0, "b": 0}

    def count_reloads(application: object, key: str) -> None:
        original_reload = application.reload_configuration

        def counted_reload(configuration: EffectiveConfig) -> None:
            reload_counts[key] += 1
            original_reload(configuration)

        monkeypatch.setattr(application, "reload_configuration", counted_reload)

    count_reloads(application_a, "a")
    try:
        started_reply = await bridge.handle_request(
            RequestEnvelope("multi-owner-turn-start", "turn.start", {"prompt": "hold owner A active"})
        )
        assert started_reply.ok is True
        await asyncio.wait_for(turn_started.wait(), timeout=2)

        opened = await bridge.handle_request(
            RequestEnvelope("multi-owner-project-open", "project.open", {"path": str(project_b)})
        )
        assert opened.ok is True
        background_a = bridge._background_runtimes[session_a.session_id]
        assert background_a["application"] is application_a
        turn_task = background_a["task"]
        assert isinstance(turn_task, asyncio.Task)

        new_session = await bridge.handle_request(RequestEnvelope("multi-owner-session-new", "session.new", {}))
        assert new_session.ok is True
        application_b = bridge.application
        run_b = bridge.run
        assert application_b is not None and application_b is not application_a
        assert run_b is not None
        run_b.set_permission_mode(PermissionMode.FULL_ACCESS)
        count_reloads(application_b, "b")
        original_compact = application_b.compact_session

        async def gated_compact(*, cancellation: CancellationToken | None = None) -> object:
            compact_started.set()
            await release_compact.wait()
            return await original_compact(cancellation=cancellation)

        monkeypatch.setattr(application_b, "compact_session", gated_compact)
        compact_reply = await bridge.handle_request(
            RequestEnvelope("multi-owner-compact-start", "command.execute", {"text": "/compact"})
        )
        assert compact_reply.ok is True
        assert compact_reply.result is not None
        compact_session_id = compact_reply.result["params"]["session_id"]
        await asyncio.wait_for(compact_started.wait(), timeout=2)
        compact_operation = bridge._compaction_operations[compact_session_id]
        compact_task = compact_operation["task"]
        assert isinstance(compact_task, asyncio.Task)

        original_config_a = application_a.configuration
        original_config_b = application_b.configuration
        assert original_config_a is not None and original_config_b is not None
        write_user_configuration(
            {
                "default_model": "disk/ref",
                "providers": {
                    "local": None,
                    "disk": {"kind": "fake"},
                },
                "models": {
                    "local/ref": None,
                    "disk/ref": {"provider_profile_id": "disk", "remote_id": "disk-model"},
                },
            },
            home=home,
        )
        assert bridge._configuration_application_states == {}

        def assert_no_unrequested_apply() -> None:
            assert bridge._configuration_application_states == {}
            assert reload_counts == {"a": 0, "b": 0}
            assert application_a.configuration is original_config_a
            assert application_b.configuration is original_config_b
            assert set(application_a.configuration.providers) == {"local"}
            assert set(application_b.configuration.providers) == {"local"}
            assert run_a.permission_mode is PermissionMode.FULL_ACCESS
            assert run_b.permission_mode is PermissionMode.FULL_ACCESS
            events = [item.event for item in bridge.drain_outbox() if hasattr(item, "event")]
            assert not any(event.get("type") == "settings_applications" for event in events)

        if first_terminal == "turn":
            release_turn.set()
            await asyncio.wait_for(asyncio.shield(turn_task), timeout=2)
            assert_no_unrequested_apply()
            release_compact.set()
            await asyncio.wait_for(asyncio.shield(compact_task), timeout=2)
        else:
            release_compact.set()
            await asyncio.wait_for(asyncio.shield(compact_task), timeout=2)
            assert_no_unrequested_apply()
            release_turn.set()
            await asyncio.wait_for(asyncio.shield(turn_task), timeout=2)
        assert_no_unrequested_apply()
    finally:
        release_turn.set()
        release_compact.set()
        await bridge.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("reload_fails", [False, True], ids=("applied", "failed"))
async def test_cross_project_background_turn_publishes_drained_configuration_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reload_fails: bool,
) -> None:
    home = tmp_path / "home"
    project_a = tmp_path / "project-a"
    project_b = tmp_path / "project-b"
    project_a.mkdir()
    project_b.mkdir()
    write_user_configuration(
        {
            "default_model": "local/ref",
            "default_permission_mode": "default",
            "providers": {"local": {"kind": "fake"}},
            "models": {"local/ref": {"provider_profile_id": "local", "remote_id": "fake-model"}},
        },
        home=home,
    )
    started = asyncio.Event()
    release = asyncio.Event()

    class BackgroundProvider(_ScriptedProvider):
        async def stream(self, request: GenerationRequest, *, cancellation: CancellationToken) -> AsyncIterator[ProviderEvent]:
            self.requests.append(request)
            started.set()
            await release.wait()
            cancellation.raise_if_cancelled()
            if reload_fails:
                yield _response(ProviderTextPart("turn still completes after apply failure"))
            else:
                yield _response(ProviderTextPart("turn completed"))

    provider = BackgroundProvider(())

    def make_application(path: Path, selected_provider: _ScriptedProvider) -> object:
        return create_application(
            load_effective_config(cwd=path, home=home),
            provider_builder=lambda _provider, _model: selected_provider,
            runtime_context=_context(path),
            storage_root=tmp_path / "sessions" / path.name,
        )

    application_a = make_application(project_a, provider)
    application_a.ensure_session()
    session = application_a.session_service.active_session  # type: ignore[union-attr]
    assert session is not None
    bridge = DesktopBridge(
        application=application_a,
        application_factory=lambda path: make_application(path, _ScriptedProvider(())),
        home=home,
        workdir=project_a,
    )
    if reload_fails:
        def fail_reload(_configuration: EffectiveConfig) -> None:
            raise RuntimeError("synthetic application-apply failure")

        monkeypatch.setattr(application_a, "reload_configuration", fail_reload)

    try:
        started_reply = await bridge.handle_request(
            RequestEnvelope("cross-project-turn-start", "turn.start", {"prompt": "finish in the background"})
        )
        assert started_reply.ok is True
        await asyncio.wait_for(started.wait(), timeout=2)

        opened = await bridge.handle_request(
            RequestEnvelope("cross-project-open", "project.open", {"path": str(project_b)})
        )
        assert opened.ok is True
        background = bridge._background_runtimes[session.session_id]
        assert background["application"] is application_a
        assert background["handle"] is not None
        assert background["task"] is not None

        saved = await bridge.handle_request(
            RequestEnvelope("cross-project-settings", "settings.save", {"default_permission_mode": "auto"})
        )
        assert saved.ok is True
        assert saved.result is not None
        assert saved.result["applications"] == {"applied": 1, "pending": 1, "failed": 0}

        release.set()
        task = background["task"]
        assert isinstance(task, asyncio.Task)
        await asyncio.wait_for(asyncio.shield(task), timeout=2)
        events = [
            item.event
            for item in bridge.drain_outbox()
            if hasattr(item, "event")
        ]
        turn_index = next(index for index, event in enumerate(events) if event.get("type") == "turn_completed")
        application_index = next(index for index, event in enumerate(events) if event.get("type") == "settings_applications")
        assert events[turn_index]["project_key"] == str(project_a.resolve())
        assert turn_index < application_index
        assert events[application_index] == {
            "type": "settings_applications",
            "applied": 1 if reload_fails else 2,
            "pending": 0,
            "failed": 1 if reload_fails else 0,
        }
        assert "api_key" not in events[application_index]
    finally:
        release.set()
        await bridge.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("compact_fails", [False, True], ids=("completed-no-change", "operation-failed"))
@pytest.mark.parametrize("reload_fails", [False, True], ids=("application-applied", "application-failed"))
async def test_compaction_terminal_publishes_drained_configuration_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    compact_fails: bool,
    reload_fails: bool,
) -> None:
    home = tmp_path / "home"
    project_a = tmp_path / "project-a"
    project_b = tmp_path / "project-b"
    project_a.mkdir()
    project_b.mkdir()
    write_user_configuration(
        {
            "default_model": "local/ref",
            "default_permission_mode": "default",
            "providers": {"local": {"kind": "fake"}},
            "models": {"local/ref": {"provider_profile_id": "local", "remote_id": "fake-model"}},
        },
        home=home,
    )
    def make_application(path: Path) -> object:
        return create_application(
            load_effective_config(cwd=path, home=home),
            provider_builder=lambda _provider, _model: _ScriptedProvider(()),
            runtime_context=_context(path),
            storage_root=tmp_path / "sessions" / path.name,
        )

    application_a = make_application(project_a)
    application_a.ensure_session()
    session = application_a.session_service.active_session  # type: ignore[union-attr]
    assert session is not None
    if reload_fails:
        def fail_reload(_configuration: EffectiveConfig) -> None:
            raise RuntimeError("synthetic Compact-boundary application failure")

        monkeypatch.setattr(application_a, "reload_configuration", fail_reload)
    original_compact = application_a.compact_session
    started = asyncio.Event()
    release = asyncio.Event()

    async def gated_compact(*, cancellation: CancellationToken | None = None) -> object:
        started.set()
        await release.wait()
        if compact_fails:
            raise RuntimeError("synthetic compaction failure")
        return await original_compact(cancellation=cancellation)

    monkeypatch.setattr(application_a, "compact_session", gated_compact)
    bridge = DesktopBridge(
        application=application_a,
        application_factory=make_application,
        home=home,
        workdir=project_a,
    )
    try:
        compact = await bridge.handle_request(
            RequestEnvelope("compact-settings-start", "command.execute", {"text": "/compact"})
        )
        assert compact.ok is True
        assert compact.result is not None
        operation_id = compact.result["params"]["operation_id"]
        await asyncio.wait_for(started.wait(), timeout=2)

        opened = await bridge.handle_request(
            RequestEnvelope("compact-background-open", "project.open", {"path": str(project_b)})
        )
        assert opened.ok is True
        background = bridge._background_runtimes[session.session_id]
        assert background["application"] is application_a
        assert bridge._compaction_operations[session.session_id]["state"] == "running"

        saved = await bridge.handle_request(
            RequestEnvelope("compact-settings-save", "settings.save", {"default_permission_mode": "auto"})
        )
        assert saved.ok is True
        assert saved.result is not None
        assert saved.result["applications"] == {"applied": 1, "pending": 1, "failed": 0}

        release.set()
        operation = bridge._compaction_operations[session.session_id]
        task = operation["task"]
        assert isinstance(task, asyncio.Task)
        await asyncio.wait_for(asyncio.shield(task), timeout=2)
        events = [
            item.event
            for item in bridge.drain_outbox()
            if hasattr(item, "event")
        ]
        terminal_index = next(
            index for index, event in enumerate(events)
            if event.get("type") == "compaction_operation" and event.get("operation_id") == operation_id
            and event.get("state") == ("failed" if compact_fails else "no_change")
        )
        application_index = next(index for index, event in enumerate(events) if event.get("type") == "settings_applications")
        assert terminal_index < application_index
        assert events[application_index] == {
            "type": "settings_applications",
            "applied": 1 if reload_fails else 2,
            "pending": 0,
            "failed": 1 if reload_fails else 0,
        }
    finally:
        release.set()
        await bridge.shutdown()
