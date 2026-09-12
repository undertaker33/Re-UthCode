from __future__ import annotations

import asyncio
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from uthcode.application import (
    ApplicationRuntimeContext,
    ApplicationSessionService,
    PermissionApprovalChoice,
    UthCodeApplication,
)
from uthcode.application.tools import ApplicationToolService
from uthcode.core.permission import PermissionMode
from uthcode.core.provider import (
    CancellationToken,
    FinishReason,
    GenerationCompleted,
    Message,
    ModelLimits,
    ProviderIdentity,
    ProviderResponse,
    ProviderEvent,
    TextPart,
    ToolCallPart,
)
from uthcode.core.secrets import SecretValue
from uthcode.integrations.providers.fake import FakeProvider
from uthcode.integrations.tools.process_sessions import ProcessSessionManager
from uthcode.integrations.tools.process_tools import BashTool, ProcessTool
from uthcode.interfaces.desktop.bridge import DesktopBridge
from uthcode.interfaces.desktop.protocol import RequestEnvelope


def _python_command(source: str) -> str:
    if os.name == "nt":
        return subprocess.list2cmdline([sys.executable, "-c", source])
    return f"{shlex.quote(sys.executable)} -c {shlex.quote(source)}"


class _ScriptedProvider:
    identity = ProviderIdentity("test", "scripted", "test-model")

    def __init__(self, scripts: tuple[tuple[ProviderEvent, ...], ...]) -> None:
        self.scripts = scripts
        self.requests = []

    def resolve_model_limits(self, _model: str) -> ModelLimits:
        return ModelLimits(max_input_tokens=1_000_000, source="test.process")

    async def stream(self, request, *, cancellation: CancellationToken):
        self.requests.append(request)
        index = min(len(self.requests) - 1, len(self.scripts) - 1)
        for event in self.scripts[index]:
            cancellation.raise_if_cancelled()
            yield event


def _completed(*parts: object, finish_reason: FinishReason = FinishReason.STOP) -> GenerationCompleted:
    return GenerationCompleted(
        ProviderResponse(
            message=Message("assistant", tuple(parts)),
            finish_reason=finish_reason,
        )
    )


@pytest.mark.asyncio
async def test_application_process_events_survive_tool_turn_and_redact_split_secret(
    tmp_path: Path,
) -> None:
    secret = "cross-turn-secret"
    manager = ProcessSessionManager(max_output_bytes=32 * 1024)
    service = ApplicationSessionService(
        storage_root=tmp_path / "sessions",
        project_key=str(tmp_path),
        instruction_loader=None,
    )
    service.create_session("session-1")
    tool_service = ApplicationToolService(
        (),
        workdir=tmp_path,
        secret_values=(SecretValue(secret),),
        session_provider=lambda: service.active_session,
    )
    runtime = ApplicationRuntimeContext(
        workdir=tmp_path,
        platform_name="test",
        platform_release="1",
        current_date="2026-09-12",
        process_manager=manager,
    )
    application = UthCodeApplication(
        FakeProvider(),
        runtime_context=runtime,
        tool_service=tool_service,
        session_service=service,
    )
    events: list[dict[str, object]] = []
    application.subscribe_process_events(events.append)
    bash = BashTool(
        tmp_path,
        process_manager=manager,
        session_provider=lambda: service.active_session,
    )
    source = (
        f"secret_marker={secret!r};import sys,time;"
        "sys.stdout.write('cross-turn-');sys.stdout.flush();"
        "time.sleep(0.15);"
        "sys.stdout.write('secret\\n');sys.stdout.flush();"
        "time.sleep(0.15)"
    )
    cancellation = CancellationToken()
    cancellation.session_id = "session-1"
    cancellation.turn_id = "turn-1"
    result = await bash.execute(
        {"command": _python_command(source), "yield_time_ms": 20},
        cancellation=cancellation,
    )

    assert result.process_id
    # The Bash Tool has returned while the child remains owned by the Session.
    assert result.process_state == "running"
    await asyncio.sleep(0.5)

    output = "".join(
        str(item.get("text", ""))
        for item in events
        if item.get("type") == "process_output"
    )
    assert "cross-turn-secret" not in output
    assert "<redacted>" in output
    assert any(item.get("type") == "process_state" and item.get("state") == "exited" for item in events)
    assert any(item.get("process_id") == result.process_id for item in events)

    # Closing the Application clears the Session's remaining process state.
    await application.close_async()
    await manager.shutdown()


@pytest.mark.asyncio
async def test_application_routes_process_output_after_tool_call_and_turn_completion(
    tmp_path: Path,
) -> None:
    secret = "turn-secret-value"
    manager = ProcessSessionManager(max_output_bytes=32 * 1024)
    service = ApplicationSessionService(
        storage_root=tmp_path / "sessions",
        project_key=str(tmp_path),
        instruction_loader=None,
    )
    service.create_session("session-1")
    bash = BashTool(
        tmp_path,
        process_manager=manager,
        session_provider=lambda: service.active_session,
    )
    provider = _ScriptedProvider(
        (
            (_completed(
                ToolCallPart(
                    "process-call",
                    "Bash",
                    {
                        "command": _python_command(
                            "import sys,time;"
                            "sys.stdout.write('turn-');sys.stdout.flush();"
                            "time.sleep(0.15);"
                            "sys.stdout.write('secret-value\\n');sys.stdout.flush();"
                            "time.sleep(0.2)"
                        ),
                        "yield_time_ms": 20,
                    },
                ),
                finish_reason=FinishReason.TOOL_CALLS,
            ),),
            (_completed(TextPart("turn completed")),),
        )
    )
    tool_service = ApplicationToolService(
        (
            bash,
            ProcessTool(
                manager,
                session_provider=lambda: service.active_session,
            ),
        ),
        workdir=tmp_path,
        secret_values=(SecretValue(secret),),
        session_provider=lambda: service.active_session,
    )
    application = UthCodeApplication(
        provider,
        runtime_context=ApplicationRuntimeContext(
            workdir=tmp_path,
            platform_name="test",
            platform_release="1",
            current_date="2026-09-12",
            process_manager=manager,
        ),
        tool_service=tool_service,
        session_service=service,
    )
    bridge = DesktopBridge(application=application, workdir=tmp_path)
    try:
        bridge_run = bridge.run
        assert bridge_run is not None
        bridge_run.set_permission_mode(PermissionMode.FULL_ACCESS)
        started = await bridge.handle_request(
            RequestEnvelope("process-turn", "turn.start", {"prompt": "start a process"})
        )
        assert started.ok is True
        await bridge.wait_for_idle()

        # The Turn has finished; the Session-owned child continues and the
        # Application -> Desktop observer must deliver later events.
        await asyncio.sleep(0.5)
        process_events = [
            envelope.event
            for envelope in bridge.drain_outbox()
            if envelope.type == "agent_event"
            and envelope.event.get("type") in {"process_output", "process_state"}
        ]
        assert process_events, (len(provider.requests), application.list_processes())
        assert any(event.get("type") == "process_output" for event in process_events)
        assert any(event.get("type") == "process_state" and event.get("state") == "exited" for event in process_events)
        assert process_events[-1].get("type") == "process_state"
        assert all(secret not in repr(event) for event in process_events)
        assert any("<redacted>" in str(event.get("text", "")) for event in process_events)
        process_id = str(process_events[0]["process_id"])
        listed = await bridge.handle_request(
            RequestEnvelope("process-list", "process.list", {})
        )
        assert listed.ok is True and listed.result is not None
        assert any(item.get("process_id") == process_id for item in listed.result["processes"])
        assert secret not in repr(listed.result)
        read = await bridge.handle_request(
            RequestEnvelope("process-read", "process.read", {"process_id": process_id, "cursor": 0})
        )
        assert read.ok is True and read.result is not None
        assert read.result["state"] == "exited"
        assert secret not in repr(read.result)
        assert any("<redacted>" in str(item.get("text", "")) for item in read.result["entries"])
    finally:
        await bridge.shutdown()


@pytest.mark.asyncio
async def test_desktop_process_controls_use_application_permission_boundary(
    tmp_path: Path,
) -> None:
    manager = ProcessSessionManager()
    service = ApplicationSessionService(
        storage_root=tmp_path / "sessions",
        project_key=str(tmp_path),
        instruction_loader=None,
    )
    service.create_session("session-1")
    application = UthCodeApplication(
        FakeProvider(),
        runtime_context=ApplicationRuntimeContext(
            workdir=tmp_path,
            platform_name="test",
            platform_release="1",
            current_date="2026-09-12",
            process_manager=manager,
        ),
        tool_service=ApplicationToolService(
            (ProcessTool(manager, session_provider=lambda: service.active_session),),
            workdir=tmp_path,
            session_provider=lambda: service.active_session,
        ),
        session_service=service,
    )
    bridge = DesktopBridge(application=application, workdir=tmp_path)
    process = await manager.start(
        session_id="session-1",
        command=_python_command("import time; time.sleep(5)"),
        cwd=tmp_path,
    )
    process_id = process.process_id
    try:
        listed = await bridge.handle_request(
            RequestEnvelope("process-list-boundary", "process.list", {})
        )
        assert listed.ok is True and listed.result is not None
        assert any(item["process_id"] == process_id for item in listed.result["processes"])

        asked = await bridge.handle_request(
            RequestEnvelope(
                "process-stop-ask",
                "process.stop",
                {"process_id": process_id},
            )
        )
        assert asked.ok is True and asked.result is not None
        permission = asked.result["permission_required"]
        permission_id = permission["permission_id"]
        assert permission["action"] == "stop"

        released = await bridge.handle_request(
            RequestEnvelope(
                "process-stop-release",
                "process.permission.release",
                {
                    "process_id": process_id,
                    "permission_id": permission_id,
                },
            )
        )
        assert released.ok is True
        assert released.result == {"permission_id": permission_id, "released": True}
        assert bridge._pending_process_operations == {}
        assert manager.get(process_id, "session-1").state == "running"

        asked_again = await bridge.handle_request(
            RequestEnvelope(
                "process-stop-ask-again",
                "process.stop",
                {"process_id": process_id},
            )
        )
        assert asked_again.ok is True and asked_again.result is not None
        permission_id = asked_again.result["permission_required"]["permission_id"]
        rejected = await bridge.handle_request(
            RequestEnvelope(
                "process-stop-reject",
                "process.stop",
                {
                    "process_id": process_id,
                    "permission_id": permission_id,
                    "permission_choice": PermissionApprovalChoice.REJECT.value,
                },
            )
        )
        assert rejected.ok is False
        assert rejected.error is not None and rejected.error.kind == "permission_denied"
        assert manager.get(process_id, "session-1").state == "running"

        asked_again = await bridge.handle_request(
            RequestEnvelope(
                "process-stop-ask-once",
                "process.stop",
                {"process_id": process_id},
            )
        )
        assert asked_again.ok is True and asked_again.result is not None
        permission_id = asked_again.result["permission_required"]["permission_id"]
        approved = await bridge.handle_request(
            RequestEnvelope(
                "process-stop-once",
                "process.stop",
                {
                    "process_id": process_id,
                    "permission_id": permission_id,
                    "permission_choice": PermissionApprovalChoice.ONCE.value,
                },
            )
        )
        assert approved.ok is True and approved.result == {
            "process_id": process_id,
            "state": "exited",
            "exit_code": manager.get(process_id, "session-1").exit_code,
            "confirmed": True,
        }

        # Cancellation still terminates at the shared ToolExecutor boundary
        # before the Process Tool can invoke the manager.
        prepared = application.prepare_process_operation(
            {"action": "read", "process_id": process_id, "cursor": 0}
        )
        token = CancellationToken()
        token.cancel()
        cancelled = await application.execute_prepared_process_operation(
            prepared,  # type: ignore[arg-type]
            cancellation=token,
        )
        assert cancelled.is_error is True
        assert "cancelled" in cancelled.content
    finally:
        await bridge.shutdown()
