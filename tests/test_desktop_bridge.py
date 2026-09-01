from __future__ import annotations

import asyncio
import io
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import uthcode.interfaces.desktop.bridge as bridge_module

from uthcode.application import (
    AgentEvent,
    ApplicationStatus,
    ApplicationRuntimeContext,
    ApplicationSessionService,
    BehaviorMode,
    ConfigSource,
    EffectiveConfig,
    GenerationCompleted,
    Message,
    ModelProfile,
    PermissionApprovalChoice,
    PermissionApprovalRequest,
    PermissionApprovalResponse,
    PauseKind,
    PauseReason,
    PauseRequest,
    PlanReviewChoice,
    PlanReviewRequest,
    PlanReviewResponse,
    PermissionMode,
    ProviderResponse,
    ProviderIdentity,
    QuestionKind,
    RetryProviderResponse,
    ResumeTurnResponse,
    RunSnapshot,
    RunStatus,
    SessionReplayRecord,
    FailureReason,
    TerminationReason,
    TextDelta,
    TextPart,
    UserInputRequest,
    UserInputResponse,
    UserQuestion,
    Usage,
    UthCodeApplication,
)
from uthcode.core.agent_events import (
    ToolFinished,
    TurnFailed,
    agent_event_from_dict as core_agent_event_from_dict,
)
from uthcode.core.permission import Effect, ResourceScope, RuleSet
from uthcode.application import ToolResultPart
from uthcode.integrations.providers.fake import FakeProvider
from uthcode.interfaces.desktop.bridge import DesktopBridge
from uthcode.interfaces.desktop.protocol import RequestEnvelope, encode_envelope


def _completed(text: str = "done") -> GenerationCompleted:
    return GenerationCompleted(
        ProviderResponse(
            message=Message("assistant", (TextPart(text),)),
            usage=Usage(),
        )
    )


def _application(*events: object) -> UthCodeApplication:
    return UthCodeApplication(
        FakeProvider(events=events or (_completed(),)),  # type: ignore[arg-type]
        runtime_context=ApplicationRuntimeContext.from_system(
            workdir=Path("C:/desktop-bridge-test"),
            platform_name="TestOS",
            platform_release="1",
            current_date="2026-08-29",
        ),
    )


class _FakeHandle:
    def __init__(self, pause: PauseRequest | None = None) -> None:
        self.pending_pause = pause
        self.paused = pause is not None
        self.resume_calls: list[object] = []
        self.cancel_calls = 0
        self.pause_calls = 0
        self.steer_calls: list[str] = []

    def resume(self, response: object) -> bool:
        self.resume_calls.append(response)
        if self.pending_pause is None:
            return False
        self.pending_pause = None
        self.paused = False
        return True

    def cancel(self) -> bool:
        self.cancel_calls += 1
        self.pending_pause = None
        self.paused = False
        return True

    def pause(self) -> bool:
        self.pause_calls += 1
        return True

    def steer(self, text: str) -> bool:
        self.steer_calls.append(text)
        return True

    async def result(self) -> object:
        return SimpleNamespace(run_id="run", turn_id="turn", status="cancelled")


class _FakeRun:
    behavior_mode = BehaviorMode.DEFAULT
    permission_mode = PermissionMode.DEFAULT

    def __init__(self) -> None:
        self.started: list[str] = []
        self.handle = _FakeHandle()

    def start_turn(self, prompt: str) -> _FakeHandle:
        self.started.append(prompt)
        return self.handle

    def set_behavior_mode(self, mode: BehaviorMode) -> BehaviorMode:
        self.behavior_mode = mode
        return mode

    def set_permission_mode(self, mode: PermissionMode) -> PermissionMode:
        self.permission_mode = mode
        return mode


class _FakeApplication:
    def __init__(self) -> None:
        self.runs: list[_FakeRun] = []
        self.ensure_calls = 0
        self.close_calls = 0
        self.current_model_ref = "fake/ref"
        self.runtime_context = SimpleNamespace(workdir=Path("C:/fake"))

    def create_run(self) -> _FakeRun:
        run = _FakeRun()
        self.runs.append(run)
        return run

    def ensure_session(self) -> None:
        self.ensure_calls += 1

    def close(self) -> None:
        self.close_calls += 1

    def model_catalog(self) -> tuple[ModelProfile, ...]:
        return (ModelProfile("fake/ref", "provider", "remote"),)

    def session_catalog(self) -> tuple[object, ...]:
        return ()


class _BlockingHandle(_FakeHandle):
    """A handle whose stream stays live until the bridge cancels it."""

    def __init__(self) -> None:
        super().__init__()
        self._closed = asyncio.Event()

    async def events(self):
        await self._closed.wait()
        if False:
            yield None

    def cancel(self) -> bool:
        accepted = super().cancel()
        self._closed.set()
        return accepted


class _EventHandle:
    def __init__(self, *events: object, error: Exception | None = None) -> None:
        self._events = events
        self._error = error

    async def events(self):
        if self._error is not None:
            raise self._error
        for event in self._events:
            yield event

    async def result(self) -> object:
        return SimpleNamespace(run_id="run-1", turn_id="turn-1", status="failed")


class _SessionApplication(_FakeApplication):
    def __init__(self, session_id: str = "session-1") -> None:
        super().__init__()
        self.session_id = session_id
        self.new_session_calls = 0
        self.resume_session_calls: list[str] = []

    def new_session_for_command(self) -> SimpleNamespace:
        self.new_session_calls += 1
        self.session_id = f"session-new-{self.new_session_calls}"
        return SimpleNamespace(session_id=self.session_id, replay=())

    def resume_session_for_command(self, session_id: str) -> SimpleNamespace:
        self.resume_session_calls.append(session_id)
        self.session_id = session_id
        replay = (
            SessionReplayRecord(
                session_id,
                1,
                "turn-1",
                "user",
                text="hello",
            ),
        )
        return SimpleNamespace(session_id=session_id, replay=replay)


class _FailingFreshRunApplication(_SessionApplication):
    def __init__(self, session_id: str = "session-1") -> None:
        super().__init__(session_id)
        self.fail_create_run = False

    def create_run(self) -> _FakeRun:
        if self.fail_create_run:
            raise RuntimeError("permission-rules-secret")
        return super().create_run()


def _user_input_pause() -> PauseRequest:
    question = UserQuestion(
        "question-1",
        "Q1",
        "What should be done?",
        QuestionKind.TEXT,
    )
    return PauseRequest(
        "pause-input",
        "run-1",
        "turn-1",
        PauseKind.USER_INPUT_REQUIRED,
        PauseReason.USER_INPUT_REQUIRED,
        1,
        "now",
        tool_call_id="call-1",
        user_input_request=UserInputRequest((question,)),
    )


def _permission_pause() -> PauseRequest:
    request = PermissionApprovalRequest(
        permission_id="permission-1",
        run_id="run-1",
        turn_id="turn-1",
        tool_call_id="call-1",
        tool="Bash",
        action="execute",
        effect=Effect.READ,
        resource="C:/project/file.txt",
        scope=ResourceScope.INSIDE,
        reason="mode_fallback",
        mode=PermissionMode.DEFAULT,
        choices=(
            PermissionApprovalChoice.ONCE,
            PermissionApprovalChoice.SESSION,
            PermissionApprovalChoice.REJECT,
        ),
        guard=False,
    )
    return PauseRequest(
        "pause-permission",
        "run-1",
        "turn-1",
        PauseKind.PERMISSION_REQUIRED,
        PauseReason.PERMISSION_REQUIRED,
        1,
        "now",
        tool_call_id="call-1",
        permission_request=request,
    )


def _guard_permission_pause() -> PauseRequest:
    request = PermissionApprovalRequest(
        permission_id="permission-guard",
        run_id="run-1",
        turn_id="turn-1",
        tool_call_id="call-1",
        tool="Bash",
        action="execute",
        effect=Effect.DESTRUCTIVE,
        resource="C:/project/file.txt",
        scope=ResourceScope.INSIDE,
        reason="guard_match",
        mode=PermissionMode.DEFAULT,
        choices=(PermissionApprovalChoice.ONCE, PermissionApprovalChoice.REJECT),
        guard=True,
    )
    return PauseRequest(
        "pause-guard",
        "run-1",
        "turn-1",
        PauseKind.PERMISSION_REQUIRED,
        PauseReason.PERMISSION_REQUIRED,
        1,
        "now",
        tool_call_id="call-1",
        permission_request=request,
    )


def _plan_pause() -> PauseRequest:
    return PauseRequest(
        "pause-plan",
        "run-1",
        "turn-1",
        PauseKind.PLAN_REVIEW_REQUIRED,
        PauseReason.PLAN_REVIEW_REQUIRED,
        1,
        "now",
        plan_review_request=PlanReviewRequest(1, "step one"),
    )


@pytest.mark.asyncio
async def test_bridge_emits_ready_turn_events_in_application_order_and_rejects_second_start() -> None:
    application = _application(TextDelta("delta"), _completed("answer"))
    bridge = DesktopBridge(application=application)
    try:
        first = await bridge.handle_request(
            RequestEnvelope("start-1", "turn.start", {"prompt": "hello"})
        )
        assert first.ok is True
        second = await bridge.handle_request(
            RequestEnvelope("start-2", "turn.start", {"prompt": "again"})
        )
        assert second.ok is False
        assert second.error is not None and second.error.kind == "turn_active"

        await bridge.wait_for_idle()
        events = [
            envelope.event
            for envelope in bridge.drain_outbox()
            if envelope.type == "agent_event"
        ]
        assert [event["type"] for event in events][-1] == "turn_completed"
        assert [event["turn_id"] for event in events]
        assert len({event["turn_id"] for event in events}) == 1
    finally:
        await bridge.shutdown()


@pytest.mark.asyncio
async def test_pending_pause_accepts_only_matching_typed_resume_and_duplicate_is_stale() -> None:
    application = _FakeApplication()
    bridge = DesktopBridge(application=application)
    pause = PauseRequest(
        "pause-1",
        "run-1",
        "turn-1",
        PauseKind.USER_REQUESTED,
        PauseReason.USER_REQUESTED,
        1,
        "now",
    )
    handle = _FakeHandle(pause)
    bridge._active_handle = handle

    stale = await bridge.handle_request(
        RequestEnvelope(
            "resume-stale",
            "turn.resume",
            {"response": ResumeTurnResponse("other", "run-1", "turn-1").to_dict()},
        )
    )
    assert stale.ok is False and stale.error is not None
    assert stale.error.kind == "stale_response"
    assert handle.resume_calls == []

    accepted = await bridge.handle_request(
        RequestEnvelope(
            "resume-ok",
            "turn.resume",
            {"response": ResumeTurnResponse("pause-1", "run-1", "turn-1").to_dict()},
        )
    )
    assert accepted.ok is True
    assert len(handle.resume_calls) == 1

    duplicate = await bridge.handle_request(
        RequestEnvelope(
            "resume-duplicate",
            "turn.resume",
            {"response": ResumeTurnResponse("pause-1", "run-1", "turn-1").to_dict()},
        )
    )
    assert duplicate.ok is False and duplicate.error is not None
    assert duplicate.error.kind in {"stale_response", "duplicate_response"}
    assert len(handle.resume_calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("pause", "response", "response_type"),
    [
        (
            _user_input_pause(),
            UserInputResponse(
                "pause-input",
                "run-1",
                "turn-1",
                "call-1",
                {"question-1": ["answer"]},
            ),
            UserInputResponse,
        ),
        (
            _permission_pause(),
            PermissionApprovalResponse(
                "pause-permission",
                "run-1",
                "turn-1",
                "permission-1",
                PermissionApprovalChoice.ONCE,
            ),
            PermissionApprovalResponse,
        ),
        (
            _plan_pause(),
            PlanReviewResponse(
                "pause-plan",
                "run-1",
                "turn-1",
                1,
                PlanReviewChoice.APPROVE,
            ),
            PlanReviewResponse,
        ),
        (
            PauseRequest(
                "pause-retry",
                "run-1",
                "turn-1",
                PauseKind.PROVIDER_UNAVAILABLE,
                PauseReason.RATE_LIMITED,
                1,
                "now",
            ),
            RetryProviderResponse("pause-retry", "run-1", "turn-1"),
            RetryProviderResponse,
        ),
    ],
)
async def test_turn_resume_maps_each_public_typed_response(
    pause: PauseRequest,
    response: object,
    response_type: type[object],
) -> None:
    application = _FakeApplication()
    bridge = DesktopBridge(application=application)
    handle = _FakeHandle(pause)
    bridge._active_handle = handle

    result = await bridge.handle_request(
        RequestEnvelope("typed-resume", "turn.resume", {"response": response.to_dict()})  # type: ignore[attr-defined]
    )

    assert result.ok is True
    assert len(handle.resume_calls) == 1
    assert isinstance(handle.resume_calls[0], response_type)


@pytest.mark.asyncio
async def test_plan_revise_requires_non_empty_feedback_and_preserves_pending_pause() -> None:
    application = _FakeApplication()
    bridge = DesktopBridge(application=application)
    pause = _plan_pause()
    handle = _FakeHandle(pause)
    bridge._active_handle = handle
    payload = {
        "type": "plan_review",
        "pause_id": "pause-plan",
        "run_id": "run-1",
        "turn_id": "turn-1",
        "revision": 1,
        "choice": "revise",
        "feedback": "",
    }

    result = await bridge.handle_request(
        RequestEnvelope("plan-empty-feedback", "turn.resume", {"response": payload})
    )

    assert result.ok is False
    assert result.error is not None and result.error.kind == "invalid_response"
    assert bridge._pending_pause() is pause
    assert handle.resume_calls == []


@pytest.mark.asyncio
async def test_permission_resume_uses_request_choices_without_fabricating_session_grant() -> None:
    application = _FakeApplication()
    bridge = DesktopBridge(application=application)
    pause = _guard_permission_pause()
    assert pause.permission_request is not None
    assert PermissionApprovalChoice.SESSION not in pause.permission_request.choices
    handle = _FakeHandle(pause)
    bridge._active_handle = handle

    result = await bridge.handle_request(
        RequestEnvelope(
            "guard-permission",
            "turn.resume",
            {
                "response": PermissionApprovalResponse(
                    "pause-guard",
                    "run-1",
                    "turn-1",
                    "permission-guard",
                    PermissionApprovalChoice.ONCE,
                ).to_dict()
            },
        )
    )

    assert result.ok is True
    assert isinstance(handle.resume_calls[0], PermissionApprovalResponse)


@pytest.mark.asyncio
async def test_active_command_gate_happens_before_dispatch_and_pending_input_cannot_steer() -> None:
    application = _FakeApplication()
    bridge = DesktopBridge(application=application)
    handle = _FakeHandle()
    bridge._active_handle = handle
    called = False

    async def forbidden_dispatch(*_args: object, **_kwargs: object) -> object:
        nonlocal called
        called = True
        raise AssertionError("forbidden command reached Dispatcher")

    bridge._dispatcher.dispatch_async = forbidden_dispatch  # type: ignore[method-assign]
    for index, name in enumerate(("model", "new", "resume", "compact", "plan", "do", "build")):
        result = await bridge.handle_request(
            RequestEnvelope(f"command-{index}", "command.execute", {"text": f"/{name}"})
        )
        assert result.ok is False
        assert result.error is not None and result.error.kind == "turn_active"
    assert called is False

    pending = PauseRequest(
        "pause-2",
        "run-1",
        "turn-1",
        PauseKind.USER_REQUESTED,
        PauseReason.USER_REQUESTED,
        1,
        "now",
    )
    handle.pending_pause = pending
    steer = await bridge.handle_request(
        RequestEnvelope("steer-pending", "turn.steer", {"text": "do this too"})
    )
    command = await bridge.handle_request(
        RequestEnvelope("command-pending", "command.execute", {"text": "/clear"})
    )
    completion = await bridge.handle_request(
        RequestEnvelope("completion-pending", "command.complete", {"prefix": "/"})
    )
    assert steer.ok is False and steer.error is not None
    assert steer.error.kind == "interaction_pending"
    assert command.ok is False and command.error is not None
    assert command.error.kind == "interaction_pending"
    assert completion.ok is True
    assert completion.result is not None
    assert completion.result["blocked"] == "interaction_pending"
    assert handle.steer_calls == []


@pytest.mark.asyncio
async def test_unknown_and_duplicate_requests_do_not_enter_application() -> None:
    application = _FakeApplication()
    status_calls = 0

    def status() -> object:
        nonlocal status_calls
        status_calls += 1
        return {"status": "safe"}

    application.status = status  # type: ignore[attr-defined]
    bridge = DesktopBridge(application=application)

    unknown = await bridge.handle_request(
        RequestEnvelope("unknown", "runtime.nope", {})
    )
    assert unknown.ok is False
    assert unknown.error is not None and unknown.error.kind == "unknown_method"
    assert status_calls == 0

    first = await bridge.handle_request(RequestEnvelope("same", "status.get", {}))
    duplicate = await bridge.handle_request(RequestEnvelope("same", "status.get", {}))
    assert first.ok is True
    assert duplicate.ok is False
    assert duplicate.error is not None and duplicate.error.kind == "duplicate_request_id"
    assert status_calls == 1
    await bridge.shutdown()


@pytest.mark.asyncio
async def test_active_turn_controls_share_one_handle_and_terminal_releases_slot() -> None:
    application = _FakeApplication()
    bridge = DesktopBridge(application=application)
    handle = _BlockingHandle()
    assert isinstance(bridge.run, _FakeRun)
    bridge.run.handle = handle

    started = await bridge.handle_request(
        RequestEnvelope("control-start", "turn.start", {"prompt": "hello"})
    )
    assert started.ok is True
    assert bridge.active_handle is handle

    steered = await bridge.handle_request(
        RequestEnvelope("control-steer", "turn.steer", {"text": "and this"})
    )
    paused = await bridge.handle_request(
        RequestEnvelope("control-pause", "turn.pause", {})
    )
    cancelled = await bridge.handle_request(
        RequestEnvelope("control-cancel", "turn.cancel", {})
    )
    assert steered.ok is True and paused.ok is True and cancelled.ok is True
    assert handle.steer_calls == ["and this"]
    assert handle.pause_calls == 1
    assert handle.cancel_calls == 1

    await bridge.wait_for_idle()
    assert bridge.active_handle is None
    assert bridge._turn_task is None
    await bridge.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("pause_factory", [_plan_pause, lambda: PauseRequest(
    "pause-retry-cancel",
    "run-1",
    "turn-1",
    PauseKind.PROVIDER_UNAVAILABLE,
    PauseReason.TIMEOUT,
    1,
    "now",
), _user_input_pause, lambda: PauseRequest(
    "pause-user-cancel",
    "run-1",
    "turn-1",
    PauseKind.USER_REQUESTED,
    PauseReason.USER_REQUESTED,
    1,
    "now",
)])
async def test_turn_cancel_is_the_common_cancel_path_for_pending_interactions(
    pause_factory,
) -> None:
    application = _FakeApplication()
    bridge = DesktopBridge(application=application)
    handle = _FakeHandle(pause_factory())
    bridge._active_handle = handle

    result = await bridge.handle_request(RequestEnvelope(
        "cancel-pending",
        "turn.cancel",
        {},
    ))

    assert result.ok is True
    assert handle.cancel_calls == 1
    assert bridge._pending_pause() is None


@pytest.mark.asyncio
async def test_command_completion_exposes_registry_arguments_without_function_objects() -> None:
    application = _FakeApplication()
    bridge = DesktopBridge(application=application)
    result = await bridge.handle_request(
        RequestEnvelope("complete-1", "command.complete", {"prefix": "/model "})
    )
    assert result.ok is True
    assert result.result is not None
    assert result.result["argument_candidates"] == ["fake/ref"]
    assert all("handler" not in json.dumps(item) for item in result.result["candidates"])

    partial = await bridge.handle_request(
        RequestEnvelope("complete-partial", "command.complete", {"prefix": "/model f"})
    )
    assert partial.ok is True
    assert partial.result is not None
    assert partial.result["argument_candidates"] == ["fake/ref"]


@pytest.mark.asyncio
async def test_bridge_shutdown_cancels_active_handle_and_closes_application() -> None:
    application = _FakeApplication()
    bridge = DesktopBridge(application=application)
    handle = _FakeHandle()
    bridge._active_handle = handle
    result = await bridge.handle_request(RequestEnvelope("shutdown-1", "runtime.shutdown", {}))
    assert result.ok is True
    assert handle.cancel_calls == 1
    assert application.close_calls == 1
    assert bridge.state == "stopped"


@pytest.mark.asyncio
async def test_shutdown_close_failure_is_runtime_boundary_error() -> None:
    class FailingCloseApplication(_FakeApplication):
        def close(self) -> None:
            self.close_calls += 1
            raise RuntimeError("raw-native-secret")

    application = FailingCloseApplication()
    bridge = DesktopBridge(application=application)
    result = await bridge.handle_request(
        RequestEnvelope("shutdown-failed", "runtime.shutdown", {})
    )

    assert result.ok is False
    assert result.error is not None and result.error.kind == "application_close_failed"
    assert bridge.state == "failed"
    assert "raw-native-secret" not in json.dumps(result.to_dict())
    assert all(
        "raw-native-secret" not in json.dumps(item.to_dict())
        for item in bridge.drain_outbox()
    )
    await bridge.shutdown()


@pytest.mark.asyncio
async def test_session_new_and_resume_use_fresh_runs_and_safe_replay() -> None:
    application = _SessionApplication()
    bridge = DesktopBridge(application=application)
    first_run = bridge.run
    invalid = await bridge.handle_request(
        RequestEnvelope("session-id-injected", "session.new", {"session_id": "arbitrary"})
    )
    assert invalid.ok is False
    assert invalid.error is not None and invalid.error.kind == "invalid_request"
    assert application.new_session_calls == 0
    active_handle = _FakeHandle()
    bridge._active_handle = active_handle

    created = await bridge.handle_request(
        RequestEnvelope("session-new", "session.new", {})
    )
    assert created.ok is True
    assert application.new_session_calls == 1
    assert bridge.run is not first_run
    assert active_handle.cancel_calls == 1
    assert created.result is not None and created.result["replay"] == []

    resumed = await bridge.handle_request(
        RequestEnvelope(
            "session-resume",
            "session.resume",
            {"session_id": "session-restored"},
        )
    )
    assert resumed.ok is True
    assert application.resume_session_calls == ["session-restored"]
    assert bridge.run is not first_run
    assert resumed.result is not None
    assert resumed.result["replay"] == [
        {
            "session_id": "session-restored",
            "sequence": 1,
            "turn_id": "turn-1",
            "kind": "user",
            "text": "hello",
            "is_error": False,
        }
    ]
    await bridge.shutdown()


@pytest.mark.asyncio
async def test_session_operation_failure_keeps_application_and_run() -> None:
    from uthcode.application import SessionOperationError

    class FailingSessionApplication(_SessionApplication):
        def resume_session_for_command(self, session_id: str) -> SimpleNamespace:
            self.resume_session_calls.append(session_id)
            raise SessionOperationError("corrupt", session_id=session_id)

    application = FailingSessionApplication()
    bridge = DesktopBridge(application=application)
    original_run = bridge.run
    failed = await bridge.handle_request(
        RequestEnvelope("session-corrupt", "session.resume", {"session_id": "bad"})
    )

    assert failed.ok is False
    assert failed.error is not None and failed.error.kind == "session_corrupt"
    assert bridge.application is application
    assert bridge.run is original_run
    await bridge.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure_kind", "wire_kind"),
    [
        ("busy", "session_busy"),
        ("corrupt", "session_corrupt"),
        ("unknown", "session_unknown"),
    ],
)
async def test_session_busy_corrupt_and_unknown_failures_are_atomic(
    failure_kind: str,
    wire_kind: str,
) -> None:
    from uthcode.application import SessionOperationError

    class FailingSessionApplication(_SessionApplication):
        def resume_session_for_command(self, session_id: str) -> SimpleNamespace:
            self.resume_session_calls.append(session_id)
            raise SessionOperationError(failure_kind, session_id=session_id)

    application = FailingSessionApplication()
    bridge = DesktopBridge(application=application)
    original_run = bridge.run
    failed = await bridge.handle_request(
        RequestEnvelope(
            f"session-{failure_kind}",
            "session.resume",
            {"session_id": "bad"},
        )
    )

    assert failed.ok is False
    assert failed.error is not None and failed.error.kind == wire_kind
    assert bridge.application is application
    assert bridge.run is original_run
    assert application.session_id == "session-1"
    await bridge.shutdown()


@pytest.mark.asyncio
async def test_session_new_preflights_real_permission_rules_before_mutation(
    tmp_path: Path,
) -> None:
    loader_calls = 0

    def permission_rules_loader() -> RuleSet:
        nonlocal loader_calls
        loader_calls += 1
        if loader_calls > 1:
            raise RuntimeError("permission-rules-secret")
        return RuleSet()

    service = ApplicationSessionService(
        storage_root=tmp_path / "sessions",
        project_key=str((tmp_path / "project").resolve()),
        instruction_loader=None,
    )
    application = UthCodeApplication(
        FakeProvider(events=(_completed(),)),
        runtime_context=ApplicationRuntimeContext.from_system(
            workdir=tmp_path,
            platform_name="TestOS",
            platform_release="1",
            current_date="2026-08-29",
        ),
        permission_rules_loader=permission_rules_loader,
        session_service=service,
    )
    bridge = DesktopBridge(application=application)
    original_run = bridge.run

    failed = await bridge.handle_request(
        RequestEnvelope("session-new-permission-failure", "session.new", {})
    )

    assert failed.ok is False
    assert failed.error is not None and failed.error.kind == "session_error"
    assert bridge.application is application
    assert bridge.run is original_run
    assert service.active_session is None
    assert loader_calls == 2
    await bridge.shutdown()


@pytest.mark.asyncio
async def test_session_resume_preflights_real_permission_rules_before_mutation(
    tmp_path: Path,
) -> None:
    service = ApplicationSessionService(
        storage_root=tmp_path / "sessions",
        project_key=str((tmp_path / "project").resolve()),
        instruction_loader=None,
    )
    seeded = service.create_session("target")
    seeded.close()
    loader_calls = 0

    def permission_rules_loader() -> RuleSet:
        nonlocal loader_calls
        loader_calls += 1
        if loader_calls > 1:
            raise RuntimeError("permission-rules-secret")
        return RuleSet()

    application = UthCodeApplication(
        FakeProvider(events=(_completed(),)),
        runtime_context=ApplicationRuntimeContext.from_system(
            workdir=tmp_path,
            platform_name="TestOS",
            platform_release="1",
            current_date="2026-08-29",
        ),
        permission_rules_loader=permission_rules_loader,
        session_service=service,
    )
    bridge = DesktopBridge(application=application)
    original_run = bridge.run

    failed = await bridge.handle_request(
        RequestEnvelope(
            "session-resume-permission-failure",
            "session.resume",
            {"session_id": "target"},
        )
    )

    assert failed.ok is False
    assert failed.error is not None and failed.error.kind == "session_error"
    assert bridge.application is application
    assert bridge.run is original_run
    assert service.active_session is None
    assert loader_calls == 2
    await bridge.shutdown()


@pytest.mark.asyncio
async def test_slash_session_change_preflights_run_before_dispatch_mutates_session() -> None:
    application = _FailingFreshRunApplication()
    bridge = DesktopBridge(application=application)
    original_run = bridge.run
    application.fail_create_run = True
    dispatch_calls = 0

    async def dispatch(*_args: object, **_kwargs: object) -> object:
        nonlocal dispatch_calls
        dispatch_calls += 1
        raise AssertionError("session-changing command must be preflighted")

    bridge._dispatcher.dispatch_async = dispatch  # type: ignore[method-assign]
    failed = await bridge.handle_request(
        RequestEnvelope("slash-new-run-failure", "command.execute", {"text": "/new"})
    )

    assert failed.ok is False
    assert failed.error is not None and failed.error.kind == "session_error"
    assert dispatch_calls == 0
    assert application.new_session_calls == 0
    assert application.session_id == "session-1"
    assert bridge.run is original_run
    await bridge.shutdown()


@pytest.mark.asyncio
async def test_session_resume_preflights_run_before_session_mutation() -> None:
    application = _FailingFreshRunApplication()
    bridge = DesktopBridge(application=application)
    original_run = bridge.run
    application.fail_create_run = True

    failed = await bridge.handle_request(
        RequestEnvelope(
            "session-resume-run-failure",
            "session.resume",
            {"session_id": "target"},
        )
    )

    assert failed.ok is False
    assert failed.error is not None and failed.error.kind == "session_error"
    assert application.resume_session_calls == []
    assert application.session_id == "session-1"
    assert bridge.application is application
    assert bridge.run is original_run
    await bridge.shutdown()


@pytest.mark.asyncio
async def test_session_projection_failure_keeps_previous_run_and_application() -> None:
    class ProjectionFailureApplication(_SessionApplication):
        def resume_session_for_command(self, session_id: str) -> SimpleNamespace:
            self.resume_session_calls.append(session_id)
            raise ValueError("projection-native-secret")

    application = ProjectionFailureApplication()
    bridge = DesktopBridge(application=application)
    original_run = bridge.run

    failed = await bridge.handle_request(
        RequestEnvelope(
            "session-projection-failure",
            "session.resume",
            {"session_id": "target"},
        )
    )

    assert failed.ok is False
    assert failed.error is not None and failed.error.kind == "session_error"
    assert application.resume_session_calls == ["target"]
    assert application.session_id == "session-1"
    assert bridge.application is application
    assert bridge.run is original_run
    assert "projection-native-secret" not in json.dumps(failed.to_dict())
    await bridge.shutdown()


@pytest.mark.asyncio
async def test_runtime_initialize_uses_one_application_and_can_recover_configuration_state(
    tmp_path: Path,
) -> None:
    application = _FakeApplication()
    factory_calls: list[Path] = []

    def factory(path: Path) -> _FakeApplication:
        factory_calls.append(path)
        return application

    bridge = DesktopBridge(application_factory=factory)
    initialized = await bridge.handle_request(
        RequestEnvelope(
            "initialize-1",
            "runtime.initialize",
            {"cwd": str(tmp_path)},
        )
    )

    assert initialized.ok is True
    assert factory_calls == [tmp_path.resolve()]
    assert bridge.application is application
    assert len(application.runs) == 1

    repeated = await bridge.handle_request(
        RequestEnvelope("initialize-2", "runtime.initialize", {})
    )
    assert repeated.ok is True
    assert factory_calls == [tmp_path.resolve()]
    assert len(application.runs) == 1
    await bridge.shutdown()


@pytest.mark.asyncio
async def test_runtime_initialization_failure_has_stable_lifecycle_error_without_exception_text(
    tmp_path: Path,
) -> None:
    def factory(_path: Path) -> object:
        raise RuntimeError("native-api-key-secret")

    bridge = DesktopBridge(application_factory=factory)
    result = await bridge.handle_request(
        RequestEnvelope(
            "initialize-failed",
            "runtime.initialize",
            {"workdir": str(tmp_path)},
        )
    )

    assert result.ok is False
    assert result.error is not None and result.error.kind == "application_error"
    assert bridge.state == "failed"
    lifecycle = bridge.drain_outbox()
    assert [item.type for item in lifecycle] == ["runtime_state"]
    assert "native-api-key-secret" not in json.dumps([item.to_dict() for item in lifecycle])
    await bridge.shutdown()


@pytest.mark.asyncio
async def test_configuration_required_keeps_bridge_alive_for_settings_retry(tmp_path: Path) -> None:
    application = _FakeApplication()
    calls = 0

    def factory(_path: Path) -> _FakeApplication:
        nonlocal calls
        calls += 1
        if calls == 1:
            from uthcode.application import ConfigurationInitializationRequired

            raise ConfigurationInitializationRequired(tmp_path / "config.toml")
        return application

    bridge = DesktopBridge(application_factory=factory)
    first = await bridge.handle_request(
        RequestEnvelope("config-required", "runtime.initialize", {})
    )
    assert first.ok is False
    assert first.error is not None and first.error.kind == "configuration_required"
    assert bridge.state == "configuration_required"

    second = await bridge.handle_request(
        RequestEnvelope("config-retry", "runtime.initialize", {})
    )
    assert second.ok is True
    assert bridge.state == "ready"
    assert calls == 2
    await bridge.shutdown()


@pytest.mark.asyncio
async def test_project_switch_candidate_failure_keeps_previous_application_and_run(
    tmp_path: Path,
) -> None:
    current = _FakeApplication()
    bad_path = tmp_path / "bad"
    bad_path.mkdir()
    calls: list[Path] = []

    def factory(path: Path) -> _FakeApplication:
        calls.append(path)
        if path.name == "bad":
            raise RuntimeError("native payload must not cross the bridge")
        return _FakeApplication()

    bridge = DesktopBridge(application=current, application_factory=factory)
    previous_run = bridge.run
    failed = await bridge.handle_request(
        RequestEnvelope("project-bad", "project.open", {"path": str(bad_path)})
    )

    assert failed.ok is False
    assert failed.error is not None and failed.error.kind == "project_open_failed"
    assert bridge.application is current
    assert bridge.run is previous_run
    await bridge.shutdown()


@pytest.mark.asyncio
async def test_project_switch_closes_old_application_and_binds_fresh_run(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    current = _FakeApplication()
    candidate = _FakeApplication()
    factory_calls: list[Path] = []

    def factory(path: Path) -> _FakeApplication:
        factory_calls.append(path)
        return candidate

    bridge = DesktopBridge(application=current, application_factory=factory)
    previous_run = bridge.run
    handle = _FakeHandle()
    bridge._active_handle = handle
    switched = await bridge.handle_request(
        RequestEnvelope("project-switch", "project.open", {"path": str(target)})
    )

    assert switched.ok is True
    assert factory_calls == [target.resolve()]
    assert handle.cancel_calls == 1
    assert current.close_calls == 1
    assert bridge.application is candidate
    assert bridge.run is candidate.runs[0]
    assert bridge.run is not previous_run
    await bridge.shutdown()


@pytest.mark.asyncio
async def test_project_switch_run_creation_failure_keeps_previous_owner(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    current = _FakeApplication()

    class NoRunApplication(_FakeApplication):
        def create_run(self) -> object:
            raise RuntimeError("native-api-key-secret")

    candidate = NoRunApplication()
    bridge = DesktopBridge(
        application=current,
        application_factory=lambda _path: candidate,
    )
    previous_run = bridge.run
    failed = await bridge.handle_request(
        RequestEnvelope("project-no-run", "project.open", {"path": str(target)})
    )

    assert failed.ok is False
    assert failed.error is not None and failed.error.kind == "project_open_failed"
    assert bridge.application is current
    assert bridge.run is previous_run
    assert current.close_calls == 0
    assert candidate.close_calls == 1
    assert "native-api-key-secret" not in json.dumps(failed.to_dict())
    await bridge.shutdown()


@pytest.mark.asyncio
async def test_project_switch_catalog_projection_failure_keeps_previous_owner(
    tmp_path: Path,
) -> None:
    target = tmp_path / "target"
    target.mkdir()
    current = _FakeApplication()

    class FailingCatalogApplication(_FakeApplication):
        def session_catalog(self) -> tuple[object, ...]:
            raise RuntimeError("catalog-native-secret")

    candidate = FailingCatalogApplication()
    bridge = DesktopBridge(
        application=current,
        application_factory=lambda _path: candidate,
    )
    previous_run = bridge.run
    active_handle = _FakeHandle()
    bridge._active_handle = active_handle

    failed = await bridge.handle_request(
        RequestEnvelope("project-catalog-failure", "project.open", {"path": str(target)})
    )

    assert failed.ok is False
    assert failed.error is not None and failed.error.kind == "project_open_failed"
    assert bridge.application is current
    assert bridge.run is previous_run
    assert current.close_calls == 0
    assert candidate.close_calls == 1
    assert active_handle.cancel_calls == 0
    assert "catalog-native-secret" not in json.dumps(failed.to_dict())
    await bridge.shutdown()


@pytest.mark.asyncio
async def test_project_switch_run_projection_failure_keeps_previous_owner(
    tmp_path: Path,
) -> None:
    target = tmp_path / "target"
    target.mkdir()
    current = _FakeApplication()

    class FailingSnapshotRun(_FakeRun):
        def snapshot(self) -> object:
            raise RuntimeError("snapshot-native-secret")

    class FailingSnapshotApplication(_FakeApplication):
        def create_run(self) -> FailingSnapshotRun:
            run = FailingSnapshotRun()
            self.runs.append(run)
            return run

    candidate = FailingSnapshotApplication()
    bridge = DesktopBridge(
        application=current,
        application_factory=lambda _path: candidate,
    )
    previous_run = bridge.run

    failed = await bridge.handle_request(
        RequestEnvelope("project-snapshot-failure", "project.open", {"path": str(target)})
    )

    assert failed.ok is False
    assert failed.error is not None and failed.error.kind == "project_open_failed"
    assert bridge.application is current
    assert bridge.run is previous_run
    assert current.close_calls == 0
    assert candidate.close_calls == 1
    assert "snapshot-native-secret" not in json.dumps(failed.to_dict())
    await bridge.shutdown()


@pytest.mark.asyncio
async def test_status_projection_drops_native_exception_and_secret_values() -> None:
    application = _FakeApplication()

    class UnsafeStatus:
        def to_dict(self) -> dict[str, object]:
            return {
                "diagnostics": {
                    "native": object(),
                    "exception": RuntimeError("bridge-secret-value"),
                }
            }

    application.status = lambda: UnsafeStatus()  # type: ignore[attr-defined]
    bridge = DesktopBridge(application=application)
    result = await bridge.handle_request(RequestEnvelope("status-safe", "status.get", {}))

    assert result.ok is True
    encoded = json.dumps(result.to_dict(), ensure_ascii=False)
    assert "bridge-secret-value" not in encoded
    assert "RuntimeError" not in encoded
    await bridge.shutdown()


@pytest.mark.asyncio
async def test_secret_sentinel_stays_out_of_all_non_reveal_bridge_projections(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinels = {
        name: f"w04-{name}-sentinel"
        for name in (
            "api_key",
            "diagnostics",
            "session_path",
            "provider_response",
            "sdk_response",
            "config_source",
            "raw_provider_payload",
            "arguments_delta",
            "private_body",
            "native_payload",
            "exception",
        )
    }
    sentinel = sentinels["api_key"]
    home = tmp_path / "home"
    user = home / ".uthcode" / "config.toml"
    user.parent.mkdir(parents=True)
    user.write_text(
        f'''default_model = "remote/ref"

[providers.remote]
kind = "openai_responses"
api_key = "{sentinel}"

[models."remote/ref"]
provider = "remote"
remote_id = "remote"
''',
        encoding="utf-8",
    )

    class UnsafeSnapshotRun(_FakeRun):
        def snapshot(self) -> dict[str, object]:
            return {
                "run_id": "run-safe",
                "api_key": sentinel,
                "diagnostics": sentinels["diagnostics"],
                "session_path": home / "sessions.sqlite",
                "provider_response": {"raw": sentinels["provider_response"]},
                "sdk_response": sentinels["sdk_response"],
                "config_source": home / "private-config.toml",
                "raw_provider_payload": sentinels["raw_provider_payload"],
                "arguments_delta": sentinels["arguments_delta"],
                "private_body": sentinels["private_body"],
                "native_payload": object(),
                "exception": RuntimeError(sentinels["exception"]),
            }

    class UnsafeProjectionApplication(_FakeApplication):
        def create_run(self) -> UnsafeSnapshotRun:
            run = UnsafeSnapshotRun()
            self.runs.append(run)
            return run

    application = UnsafeProjectionApplication()
    application.status = lambda: ApplicationStatus(  # type: ignore[attr-defined]
        current_model="remote/ref",
        provider_profile="remote",
        provider_identity=ProviderIdentity("remote", "openai_responses", "remote"),
        configuration_sources=(ConfigSource("project", home / "private-config.toml"),),
        diagnostics={
            "api_key": sentinel,
            "diagnostics": sentinels["diagnostics"],
            "session_path": home / "sessions.sqlite",
            "provider_response": {"raw": sentinels["provider_response"]},
            "sdk_response": sentinels["sdk_response"],
            "config_source": home / "private-config.toml",
            "raw_provider_payload": sentinels["raw_provider_payload"],
            "arguments_delta": sentinels["arguments_delta"],
            "private_body": sentinels["private_body"],
            "native_payload": object(),
            "exception": RuntimeError(sentinels["exception"]),
            "safe": "retained",
        },
    )
    bridge = DesktopBridge(application=application, home=home)

    settings = await bridge.handle_request(RequestEnvelope("sentinel-settings", "settings.get", {}))
    status = await bridge.handle_request(RequestEnvelope("sentinel-status", "status.get", {}))
    assert settings.ok is True and status.ok is True
    settings_wire = json.dumps(settings.to_dict(), ensure_ascii=False)
    status_wire = json.dumps(status.to_dict(), ensure_ascii=False)
    assert all(value not in settings_wire for value in sentinels.values())
    assert all(value not in status_wire for value in sentinels.values())
    assert status.result is not None
    application_status = status.result["application"]  # type: ignore[index]
    assert "diagnostics" not in application_status  # type: ignore[operator]
    assert "configuration_sources" not in application_status  # type: ignore[operator]
    assert status.result["runtime"]["run"] is None  # type: ignore[index]

    class UnsafeEvent(AgentEvent):
        event_type = "turn_completed"

        def to_dict(self) -> dict[str, object]:
            return {
                "type": self.event_type,
                "run_id": self.run_id,
                "turn_id": self.turn_id,
                "final_text": "safe-looking event",
                "diagnostics": sentinels["diagnostics"],
                "session_path": home / "sessions.sqlite",
                "provider_response": sentinels["provider_response"],
                "sdk_response": sentinels["sdk_response"],
                "config_source": home / "private-config.toml",
                "raw_provider_payload": sentinels["raw_provider_payload"],
                "arguments_delta": sentinels["arguments_delta"],
                "private_body": sentinels["private_body"],
                "native_payload": object(),
                "exception": RuntimeError(sentinels["exception"]),
            }

    event_handle = _EventHandle(UnsafeEvent("run-safe", "turn-safe"))
    bridge._active_handle = event_handle
    bridge._turn_task = asyncio.create_task(bridge._consume_turn(event_handle))
    await bridge.wait_for_idle()
    events = bridge.drain_outbox()
    event_wire = json.dumps([item.to_dict() for item in events], ensure_ascii=False)
    assert all(value not in event_wire for value in sentinels.values())
    assert [item.type for item in events] == ["runtime_state"]
    assert events[0].state == "failed"  # type: ignore[union-attr]

    def fail_settings(*_args: object, **_kwargs: object) -> object:
        raise bridge_module.ConfigurationError(sentinel)

    monkeypatch.setattr(bridge_module, "read_user_configuration", fail_settings)
    failed = await bridge.handle_request(RequestEnvelope("sentinel-error", "settings.get", {}))
    assert failed.ok is False
    assert failed.error is not None and failed.error.kind == "configuration_error"
    assert sentinel not in json.dumps(failed.to_dict(), ensure_ascii=False)
    await bridge.shutdown()


@pytest.mark.asyncio
async def test_run_permission_mode_is_added_to_safe_runtime_and_command_projections() -> None:
    class ProjectedRun(_FakeRun):
        def snapshot(self) -> RunSnapshot:
            return RunSnapshot(
                run_id="run-safe",
                turn_id="turn-safe",
                iteration_count=0,
                tool_call_count=0,
                consecutive_unknown_tools=0,
                usage=Usage(),
                behavior_mode=BehaviorMode.DEFAULT,
                status=RunStatus.RUNNING,
                termination_reason=None,
            )

    class PermissionApplication(_FakeApplication):
        def create_run(self) -> ProjectedRun:
            run = ProjectedRun()
            self.runs.append(run)
            return run

        def set_default_permission_mode(self, mode: PermissionMode) -> PermissionMode:
            return mode

    application = PermissionApplication()
    bridge = DesktopBridge(application=application)

    application.runs[0].set_permission_mode(PermissionMode.AUTO)
    status = await bridge.handle_request(RequestEnvelope("permission-status", "status.get", {}))
    assert status.ok is True
    assert status.result is not None
    assert status.result["runtime"]["run"]["permission_mode"] == "auto"  # type: ignore[index]

    selected = await bridge.handle_request(
        RequestEnvelope("permission-command", "command.execute", {"text": "/permission full_access"})
    )
    assert selected.ok is True
    assert selected.result is not None
    assert selected.result["run"]["permission_mode"] == "full_access"  # type: ignore[index]
    assert application.runs[0].permission_mode is PermissionMode.FULL_ACCESS
    await bridge.shutdown()


@pytest.mark.asyncio
async def test_status_projection_drops_real_tool_result_part_content() -> None:
    application = _FakeApplication()
    content = "RAW-TOOL-RESULT-MUST-NOT-CROSS-DESKTOP"
    application.status = lambda: {  # type: ignore[attr-defined]
        "raw_tool_result": ToolResultPart("call-1", content, is_error=True),
    }
    bridge = DesktopBridge(application=application)

    result = await bridge.handle_request(RequestEnvelope("tool-result-safe", "status.get", {}))

    assert result.ok is True
    encoded = encode_envelope(result)
    assert content not in encoded
    assert '"type": "tool_result"' not in encoded
    await bridge.shutdown()


def test_event_projection_delegates_round_trip_validation_to_core_parser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event = ToolFinished(
        "run-parser",
        "turn-parser",
        1,
        "batch-parser",
        "call-parser",
        "Bash",
        "echo safe",
        "succeeded",
        False,
    )
    seen: list[object] = []

    def parse(payload: object) -> object:
        seen.append(payload)
        return core_agent_event_from_dict(payload)  # type: ignore[arg-type]

    monkeypatch.setattr(bridge_module, "agent_event_from_dict", parse)

    projected = bridge_module._event(event)

    assert projected == event.to_dict()
    assert seen == [event.to_dict()]


@pytest.mark.asyncio
async def test_session_changed_wire_projection_has_one_replay_location() -> None:
    application = _SessionApplication()
    bridge = DesktopBridge(application=application)

    result = await bridge.handle_request(
        RequestEnvelope("slash-new", "command.execute", {"text": "/new"})
    )

    assert result.ok is True
    assert result.result is not None
    assert result.result["replay"] == []
    assert result.result["ui_action"] == {
        "type": "session_changed",
        "session_id": application.session_id,
        "restored": False,
    }
    assert "replay" not in result.result["ui_action"]
    await bridge.shutdown()


@pytest.mark.asyncio
async def test_status_wire_projection_has_one_run_location() -> None:
    application = _FakeApplication()
    bridge = DesktopBridge(application=application)

    result = await bridge.handle_request(RequestEnvelope("status-one-run", "status.get", {}))

    assert result.ok is True
    assert result.result is not None
    assert "run" not in result.result
    assert "run" in result.result["runtime"]
    await bridge.shutdown()


@pytest.mark.asyncio
async def test_agent_failure_stays_agent_event_and_runtime_stream_errors_are_separate() -> None:
    application = _FakeApplication()
    bridge = DesktopBridge(application=application)
    failure = TurnFailed(
        "run-1",
        "turn-1",
        TerminationReason.PROVIDER_ERROR,
        FailureReason.PROVIDER_REQUEST,
    )
    tool_finished = ToolFinished(
        "run-1",
        "turn-1",
        1,
        "batch-1",
        "call-1",
        "Bash",
        "echo safe",
        "succeeded",
        False,
    )
    event_handle = _EventHandle(tool_finished, failure)
    bridge._active_handle = event_handle
    bridge._turn_task = asyncio.create_task(bridge._consume_turn(event_handle))
    await bridge.wait_for_idle()
    envelopes = bridge.drain_outbox()
    assert [item.type for item in envelopes] == ["agent_event", "agent_event"]
    assert envelopes[0].event["type"] == "tool_finished"  # type: ignore[union-attr]
    assert "tool_result" not in envelopes[0].event  # type: ignore[union-attr]
    assert envelopes[1].event["type"] == "turn_failed"  # type: ignore[union-attr]

    broken = _EventHandle(error=RuntimeError("raw-native-secret"))
    bridge._active_handle = broken
    bridge._turn_task = asyncio.create_task(bridge._consume_turn(broken))
    await bridge.wait_for_idle()
    failed = bridge.drain_outbox()
    assert [item.type for item in failed] == ["runtime_state"]
    assert failed[0].state == "failed"  # type: ignore[union-attr]
    assert "raw-native-secret" not in json.dumps([item.to_dict() for item in failed])
    await bridge.shutdown()


@pytest.mark.asyncio
async def test_settings_save_redacts_transient_api_key_from_request_and_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[object] = []

    def writer(request: object, *, home: object = None) -> dict[str, object]:
        del home
        captured.append(request)
        return {"default_model": "provider/model"}

    monkeypatch.setattr(bridge_module, "write_user_configuration", writer)
    bridge = DesktopBridge(application=_FakeApplication())
    result = await bridge.handle_request(
        RequestEnvelope(
            "settings-save",
            "settings.save",
            {
                "providers": {
                    "provider": {
                        "kind": "fake",
                        "api_key": "raw-native-secret",
                    }
                },
                "default_model": "provider/model",
            },
        )
    )

    assert result.ok is True
    assert captured
    request = captured[0]
    assert "raw-native-secret" not in repr(request)
    assert "raw-native-secret" not in json.dumps(result.to_dict())
    await bridge.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("expression", "environment_name", "environment_value"),
    [
        ("bridge-literal-configured-key", None, None),
        ("env:W04_BRIDGE_CONFIGURED_KEY", "W04_BRIDGE_CONFIGURED_KEY", "bridge-resolved-secret"),
    ],
)
async def test_settings_reveal_api_key_is_the_only_secret_bearing_bridge_response(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    expression: str,
    environment_name: str | None,
    environment_value: str | None,
) -> None:
    home = tmp_path / "home"
    user = home / ".uthcode" / "config.toml"
    user.parent.mkdir(parents=True)
    if environment_name is None:
        monkeypatch.delenv("W04_BRIDGE_CONFIGURED_KEY", raising=False)
    else:
        monkeypatch.setenv(environment_name, environment_value or "")
    user.write_text(
        f'''default_model = "remote/ref"

[providers.remote]
kind = "openai_responses"
api_key = "{expression}"

[models."remote/ref"]
provider = "remote"
remote_id = "remote"
''',
        encoding="utf-8",
    )
    bridge = DesktopBridge(application=_FakeApplication(), home=home)

    settings = await bridge.handle_request(RequestEnvelope("settings-safe", "settings.get", {}))
    revealed = await bridge.handle_request(
        RequestEnvelope(
            "settings-reveal",
            "settings.reveal_api_key",
            {"provider_profile_id": "remote"},
        )
    )

    encoded_settings = json.dumps(settings.to_dict(), ensure_ascii=False)
    assert expression not in encoded_settings
    if environment_value is not None:
        assert environment_value not in encoded_settings
    assert revealed.ok is True
    assert revealed.result == {"api_key": expression}
    if environment_value is not None:
        assert environment_value not in json.dumps(revealed.to_dict(), ensure_ascii=False)
    await bridge.shutdown()


@pytest.mark.asyncio
async def test_settings_reveal_api_key_maps_unknown_and_read_failures_without_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge = DesktopBridge(application=_FakeApplication())

    unknown = await bridge.handle_request(
        RequestEnvelope(
            "settings-reveal-unknown",
            "settings.reveal_api_key",
            {"provider_profile_id": "missing"},
        )
    )
    assert unknown.ok is False
    assert unknown.error is not None and unknown.error.kind == "configuration_error"
    assert "missing" not in unknown.error.message

    def fail(*_args: object, **_kwargs: object) -> str:
        raise bridge_module.ConfigurationError("raw-secret-read-failure")

    monkeypatch.setattr(bridge_module, "read_user_api_key", fail)
    failed = await bridge.handle_request(
        RequestEnvelope(
            "settings-reveal-failure",
            "settings.reveal_api_key",
            {"provider_profile_id": "remote"},
        )
    )
    assert failed.ok is False
    assert failed.error is not None and failed.error.kind == "configuration_error"
    assert "raw-secret-read-failure" not in json.dumps(failed.to_dict())
    await bridge.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("key_expression", "environment_name", "environment_value", "replacement"),
    [
        ("literal-gui-provider-key", None, None, None),
        ("env:W06_GUI_PROVIDER_KEY", "W06_GUI_PROVIDER_KEY", "env-gui-secret", None),
        ("literal-gui-provider-key", None, None, "replacement-gui-provider-key"),
    ],
)
async def test_settings_save_gui_request_renames_provider_through_application_writer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    key_expression: str,
    environment_name: str | None,
    environment_value: str | None,
    replacement: str | None,
) -> None:
    home = tmp_path / "home"
    user = home / ".uthcode" / "config.toml"
    user.parent.mkdir(parents=True)
    if environment_name is None:
        monkeypatch.delenv("W06_GUI_PROVIDER_KEY", raising=False)
    elif environment_value is None:
        monkeypatch.delenv(environment_name, raising=False)
    else:
        monkeypatch.setenv(environment_name, environment_value)
    user.write_text(
        f'''default_model = "remote/ref"

[providers.remote]
kind = "openai_responses"
api_key = "{key_expression}"

[models."remote/ref"]
provider = "remote"
remote_id = "remote"
''',
        encoding="utf-8",
    )
    profile: dict[str, object] = {"kind": "openai_responses"}
    if replacement is not None:
        profile["api_key"] = replacement
    bridge = DesktopBridge(application=_FakeApplication(), home=home)
    result = await bridge.handle_request(
        RequestEnvelope(
            "settings-gui-rename",
            "settings.save",
            {
                "request": {
                    "default_model": "remote/ref",
                    "provider_renames": {"remote": "renamed"},
                    "providers": {"renamed": profile},
                    "models": {
                        "remote/ref": {
                            "provider_profile_id": "renamed",
                            "remote_id": "remote",
                        }
                    },
                }
            },
        )
    )

    assert result.ok is True
    rendered = user.read_text(encoding="utf-8")
    assert "[providers.remote]" not in rendered
    assert "[providers.renamed]" in rendered
    assert 'provider = "renamed"' in rendered
    if replacement is None:
        assert f'api_key = "{key_expression}"' in rendered
    else:
        assert f'api_key = "{replacement}"' in rendered
        assert key_expression not in rendered
    assert key_expression not in json.dumps(result.to_dict())
    assert replacement is None or replacement not in json.dumps(result.to_dict())
    await bridge.shutdown()


@pytest.mark.asyncio
async def test_settings_save_gui_request_rejects_provider_rename_conflict_without_mutation(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    user = home / ".uthcode" / "config.toml"
    user.parent.mkdir(parents=True)
    user.write_text(
        '''default_model = "remote/ref"

[providers.remote]
kind = "fake"

[providers.existing]
kind = "fake"

[models."remote/ref"]
provider = "remote"
remote_id = "remote"
''',
        encoding="utf-8",
    )
    original = user.read_bytes()
    bridge = DesktopBridge(application=_FakeApplication(), home=home)
    conflict = await bridge.handle_request(
        RequestEnvelope(
            "settings-gui-conflict",
            "settings.save",
            {"request": {"provider_renames": {"remote": "existing"}}},
        )
    )
    invalid = await bridge.handle_request(
        RequestEnvelope(
            "settings-gui-invalid",
            "settings.save",
            {"request": {"provider_renames": {"missing": "renamed"}}},
        )
    )

    assert conflict.ok is False
    assert invalid.ok is False
    assert user.read_bytes() == original
    await bridge.shutdown()


@pytest.mark.asyncio
async def test_settings_save_gui_request_allows_batch_rename_into_released_source(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    user = home / ".uthcode" / "config.toml"
    user.parent.mkdir(parents=True)
    user.write_text(
        '''default_model = "a/ref"

[providers.a]
kind = "fake"

[providers.b]
kind = "fake"

[models."a/ref"]
provider = "a"
remote_id = "a"

[models."b/ref"]
provider = "b"
remote_id = "b"
''',
        encoding="utf-8",
    )
    bridge = DesktopBridge(application=_FakeApplication(), home=home)
    result = await bridge.handle_request(
        RequestEnvelope(
            "settings-gui-batch-rename",
            "settings.save",
            {
                "request": {
                    "default_model": "a/ref",
                    "provider_renames": {"a": "x", "b": "a"},
                    "providers": {"x": {"kind": "fake"}, "a": {"kind": "fake"}},
                    "models": {
                        "a/ref": {"provider_profile_id": "x", "remote_id": "a"},
                        "b/ref": {"provider_profile_id": "a", "remote_id": "b"},
                    },
                }
            },
        )
    )

    assert result.ok is True
    rendered = user.read_text(encoding="utf-8")
    assert "[providers.b]" not in rendered
    assert "[providers.x]" in rendered
    assert 'provider = "x"' in rendered
    assert 'provider = "a"' in rendered
    await bridge.shutdown()


@pytest.mark.asyncio
async def test_serve_forever_flushes_lifecycle_jsonl_and_closes_application() -> None:
    application = _FakeApplication()
    bridge = DesktopBridge(application=application)
    stdin = io.StringIO(
        '{"type":"request","id":"shutdown","method":"runtime.shutdown","params":{}}\n'
    )
    stdout = io.StringIO()
    stderr = io.StringIO()

    await bridge.serve_forever(stdin=stdin, stdout=stdout, stderr=stderr)

    lines = [json.loads(line) for line in stdout.getvalue().splitlines() if line]
    assert [line["type"] for line in lines] == [
        "runtime_state",
        "runtime_state",
        "runtime_state",
        "response",
    ]
    assert all(isinstance(line, dict) for line in lines)
    assert application.close_calls == 1
    assert "raw-native-secret" not in stdout.getvalue()
    assert "raw-native-secret" not in stderr.getvalue()


def test_desktop_module_stdout_is_jsonl_protocol_only() -> None:
    environment = os.environ.copy()
    source_root = str(Path(__file__).parents[1] / "src")
    environment["PYTHONPATH"] = source_root + os.pathsep + environment.get("PYTHONPATH", "")
    process = subprocess.Popen(
        [sys.executable, "-m", "uthcode.interfaces.desktop"],
        cwd=Path(__file__).parents[1],
        env=environment,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert process.stdin is not None
    assert process.stdout is not None
    process.stdin.write('{"type":"request","id":"status","method":"status.get","params":{}}\n')
    process.stdin.write('{"type":"request","id":"shutdown","method":"runtime.shutdown","params":{}}\n')
    process.stdin.close()
    stdout, stderr = process.communicate(timeout=10)
    assert process.returncode == 0
    lines = [line for line in stdout.splitlines() if line]
    assert lines
    payloads = [json.loads(line) for line in lines]
    assert all(isinstance(payload, dict) for payload in payloads)
    assert any(payload.get("type") == "response" and payload.get("id") == "status" for payload in payloads)
    assert any(payload.get("type") == "response" and payload.get("id") == "shutdown" for payload in payloads)
    assert all("Traceback" not in line for line in lines)
    assert "Traceback" not in stderr


def test_desktop_module_jsonl_transport_is_utf8_in_both_directions() -> None:
    environment = os.environ.copy()
    source_root = str(Path(__file__).parents[1] / "src")
    environment["PYTHONPATH"] = source_root + os.pathsep + environment.get("PYTHONPATH", "")
    environment["PYTHONIOENCODING"] = "cp936"
    environment["PYTHONUTF8"] = "0"
    process = subprocess.Popen(
        [sys.executable, "-m", "uthcode.interfaces.desktop"],
        cwd=Path(__file__).parents[1],
        env=environment,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    success = '{"type":"request","id":"status-中文","method":"status.get","params":{}}\n'
    request = '{"type":"request","id":"bad-中文","method":"不存在的方法","params":{"文本":"你好"}}\n'
    shutdown = '{"type":"request","id":"shutdown-中文","method":"runtime.shutdown","params":{}}\n'
    stdout, stderr = process.communicate((success + request + shutdown).encode("utf-8"), timeout=10)
    assert process.returncode == 0
    decoded = stdout.decode("utf-8", errors="strict")
    payloads = [json.loads(line) for line in decoded.splitlines() if line]
    assert any(payload.get("id") == "status-中文" and payload.get("ok") is True for payload in payloads)
    error = next(payload for payload in payloads if payload.get("id") == "bad-中文")
    assert error["ok"] is False
    assert error["error"]["message"] == "unknown Desktop method"
    assert stderr.decode("utf-8", errors="strict") == ""


def test_desktop_stdio_override_emits_utf8_agent_event_under_cp936_environment() -> None:
    environment = os.environ.copy()
    source_root = str(Path(__file__).parents[1] / "src")
    environment["PYTHONPATH"] = source_root + os.pathsep + environment.get("PYTHONPATH", "")
    environment["PYTHONIOENCODING"] = "cp936"
    environment["PYTHONUTF8"] = "0"
    script = (
        "import json,sys;"
        "from uthcode.interfaces.desktop.__main__ import _configure_utf8_stdio;"
        "_configure_utf8_stdio();"
        "sys.stdout.write(json.dumps({'type':'agent_event','event':{'type':'reasoning_delta','text':'中文推理'}},ensure_ascii=False)+'\\n');"
        "sys.stdout.flush()"
    )
    result = subprocess.run([sys.executable, "-c", script], cwd=Path(__file__).parents[1], env=environment, capture_output=True, timeout=10)
    assert result.returncode == 0
    payload = json.loads(result.stdout.decode("utf-8", errors="strict"))
    assert payload["event"]["text"] == "中文推理"
    assert result.stderr == b""


def test_desktop_module_rejects_invalid_utf8_without_business_dispatch() -> None:
    environment = os.environ.copy()
    source_root = str(Path(__file__).parents[1] / "src")
    environment["PYTHONPATH"] = source_root + os.pathsep + environment.get("PYTHONPATH", "")
    environment["PYTHONIOENCODING"] = "cp936"
    environment["PYTHONUTF8"] = "0"
    result = subprocess.run(
        [sys.executable, "-m", "uthcode.interfaces.desktop"],
        cwd=Path(__file__).parents[1], env=environment,
        input=b'{"type":"request","id":"bad","method":"status.get","params":{"text":"\x81"}}\n',
        capture_output=True, timeout=10,
    )
    assert result.returncode == 0
    assert b'"id":"bad"' not in result.stdout
    decoded = result.stdout.decode("utf-8", errors="strict")
    assert '"kind":"transport_error"' in decoded
    assert result.stderr.decode("utf-8", errors="strict") == ""
