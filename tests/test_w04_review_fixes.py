from __future__ import annotations

import asyncio
import json
import sys
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
