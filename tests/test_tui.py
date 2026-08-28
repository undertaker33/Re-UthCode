from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from collections.abc import AsyncIterator, Iterable
from pathlib import Path

import pytest
from prompt_toolkit.input.defaults import create_pipe_input
from prompt_toolkit.document import Document
from prompt_toolkit.layout import VSplit
from prompt_toolkit.output import DummyOutput
from rich.text import Text

from uthcode.application import (
    AgentRun,
    ApplicationRuntimeContext,
    BehaviorMode,
    BehaviorModeChanged,
    BehaviorModeSelected,
    CompletionBlocked,
    EffectiveConfig,
    FailureReason,
    GenerationCompleted,
    GenerationRequest,
    Message,
    ModelProfile,
    PauseKind,
    PauseReason,
    PauseRequest,
    PlanProposed,
    PlanReviewChoice,
    PlanReviewRequest,
    PlanReviewResponse,
    PermissionApprovalChoice,
    PermissionApprovalRequest,
    ProviderResponse,
    PermissionMode,
    QuestionOption,
    QuestionKind,
    RetryProviderResponse,
    RunStatus,
    SessionChanged,
    SessionReplayRecord,
    TextDelta,
    TextPart,
    TaskItem,
    TaskState,
    TaskStateChanged,
    TaskStatus,
    TurnHandle,
    ToolCallPart,
    ToolResultPart,
    Usage,
    UthCodeApplication,
    create_application,
    UserSteeringApplied,
    UserSteeringRequested,
    UserInputRequest,
    UserQuestion,
    CommandOutcome,
    OutcomeStatus,
    failure_message,
    pause_message,
)
from uthcode.core.provider import (
    CancellationToken,
    FinishReason,
    ModelLimits,
    NetworkError,
    ReasoningDelta as ProviderReasoningDelta,
    ProviderEvent,
    RateLimitError,
)
from uthcode.core.agent import TerminationReason
from uthcode.core.agent_events import (
    AssistantMessageCompleted,
    AssistantMessageDelta,
    AssistantMessageKind,
    ReasoningDelta as AgentReasoningDelta,
    ReasoningFinished,
    ReasoningStarted,
    ToolFinished,
    ToolStarted,
    TurnFailed,
)
from uthcode.core.permission import Effect, ResourceScope
from uthcode.integrations.providers.fake import FakeProvider
from uthcode.integrations.session_files import SessionFileStore
from uthcode.interfaces.tui.app import (
    UthCodeTUI,
    _StreamProjection,
    _tail_for_preview,
    _window_start,
)
from uthcode.interfaces.tui.interaction import (
    InteractionMode,
    PlanReviewAction,
    TuiInteractionState,
)
from uthcode.interfaces.tui.rendering import (
    AgentEventRenderer,
    MarkdownStream,
    PlanUpdate,
    RenderBatch,
    RenderOperation,
    TextUpdate,
    TaskStateUpdate,
    ToolUpdate,
)
from uthcode.interfaces.tui.state import EscArmState, previous_grapheme_length
from uthcode.interfaces.tui.terminal import (
    CLEAR_VIEWPORT,
    KITTY_KEYBOARD_OFF,
    KITTY_KEYBOARD_ON,
    PALETTE,
    RichTerminalRenderer,
    SYNCHRONIZED_OUTPUT_OFF,
    SYNCHRONIZED_OUTPUT_ON,
    _protect_nested_markdown_fences,
)
from uthcode.interfaces.tui.windows_input import create_windows_unicode_input


TEST_LIMITS = ModelLimits(max_input_tokens=1_000_000, source="test.fake")


class RecordingOutput(DummyOutput):
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    def write(self, data: str) -> None:
        self.events.append(("write", data))

    def write_raw(self, data: str) -> None:
        self.events.append(("raw", data))

    def erase_down(self) -> None:
        self.events.append(("erase_down", ""))

    def cursor_goto(self, row: int = 0, column: int = 0) -> None:
        self.events.append(("cursor_goto", f"{row},{column}"))

    def getvalue(self) -> str:
        return "".join(
            value
            for operation, value in self.events
            if operation in {"write", "raw"}
        )


class _ScriptedProvider(FakeProvider):
    def __init__(
        self,
        scripts: Iterable[Iterable[ProviderEvent]],
        *,
        delay: float = 0.0,
        delays: tuple[float, ...] | None = None,
    ) -> None:
        super().__init__(delay=delay, model_limits=TEST_LIMITS)
        self._scripts = tuple(tuple(script) for script in scripts)
        self._delays = delays

    async def stream(
        self,
        request: GenerationRequest,
        *,
        cancellation: CancellationToken,
    ) -> AsyncIterator[ProviderEvent]:
        self.requests.append(request)
        cancellation.raise_if_cancelled()
        index = min(len(self.requests) - 1, len(self._scripts) - 1)
        for event in self._scripts[index]:
            delay = self._delays[index] if self._delays is not None else self._delay
            if delay:
                try:
                    await asyncio.wait_for(cancellation.wait(), timeout=delay)
                except asyncio.TimeoutError:
                    pass
                else:
                    cancellation.raise_if_cancelled()
            cancellation.raise_if_cancelled()
            yield event


class _ProviderFailureThenSuccess(_ScriptedProvider):
    def __init__(
        self,
        error: NetworkError | RateLimitError,
        success: Iterable[ProviderEvent],
    ) -> None:
        super().__init__((tuple(success),))
        self._error = error

    async def stream(
        self,
        request: GenerationRequest,
        *,
        cancellation: CancellationToken,
    ) -> AsyncIterator[ProviderEvent]:
        if not self.requests:
            self.requests.append(request)
            cancellation.raise_if_cancelled()
            raise self._error
        async for event in super().stream(request, cancellation=cancellation):
            yield event


class _FakeModeRun:
    def __init__(self, mode: BehaviorMode = BehaviorMode.DEFAULT) -> None:
        self.behavior_mode = mode
        self.permission_mode = PermissionMode.DEFAULT
        self.selected: list[BehaviorMode] = []

    def set_behavior_mode(self, mode: BehaviorMode) -> None:
        self.selected.append(mode)
        self.behavior_mode = mode


class _FakeRunProxy:
    """Test-local W02 run contract without mutating production classes."""

    def __init__(self, run: AgentRun) -> None:
        self._run = run
        self.behavior_mode = BehaviorMode.DEFAULT

    @property
    def permission_mode(self) -> PermissionMode:
        return self._run.permission_mode

    def set_permission_mode(self, mode: PermissionMode) -> None:
        self._run.set_permission_mode(mode)

    def set_behavior_mode(self, mode: BehaviorMode) -> None:
        self.behavior_mode = mode

    def start_turn(self, prompt: str) -> TurnHandle:
        return self._run.start_turn(prompt)

    def __getattr__(self, name: str) -> object:
        return getattr(self._run, name)


class _FakeSteeringHandle:
    def __init__(self, *, accepted: bool = True, pending_pause: object | None = None) -> None:
        self.accepted = accepted
        self.pending_pause = pending_pause
        self.paused = pending_pause is not None
        self.steer_calls: list[str] = []
        self.resume_calls: list[object] = []
        self.cancel_calls = 0

    def steer(self, text: str) -> bool:
        self.steer_calls.append(text)
        return self.accepted

    def resume(self, response: object) -> bool:
        self.resume_calls.append(response)
        return True

    def cancel(self) -> bool:
        self.cancel_calls += 1
        return True


def _plan_review_pause(revision: int = 1) -> PauseRequest:
    return PauseRequest(
        pause_id="plan-pause",
        run_id="run",
        turn_id="turn",
        kind=PauseKind.PLAN_REVIEW_REQUIRED,
        reason=PauseReason.PLAN_REVIEW_REQUIRED,
        iteration=2,
        created_at="now",
        plan_review_request=PlanReviewRequest(revision, f"Plan {revision}"),
    )


def _ask_user_pause() -> PauseRequest:
    return PauseRequest(
        pause_id="ask-pause",
        run_id="run",
        turn_id="turn",
        kind=PauseKind.USER_INPUT_REQUIRED,
        reason=PauseReason.USER_INPUT_REQUIRED,
        iteration=2,
        created_at="now",
        tool_call_id="ask-call",
        user_input_request=UserInputRequest(
            (
                UserQuestion(
                    "goal",
                    "Goal",
                    "What should change?",
                    QuestionKind.TEXT,
                ),
            )
        ),
    )


def _permission_pause() -> PauseRequest:
    request = PermissionApprovalRequest(
        permission_id="permission-1",
        run_id="run",
        turn_id="turn",
        tool_call_id="write-call",
        tool="WriteFile",
        action="write",
        effect=Effect.WRITE,
        resource="safe.txt",
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
        pause_id="permission-pause",
        run_id="run",
        turn_id="turn",
        kind=PauseKind.PERMISSION_REQUIRED,
        reason=PauseReason.PERMISSION_REQUIRED,
        iteration=2,
        created_at="now",
        tool_call_id="write-call",
        permission_request=request,
    )


def _retry_pause() -> PauseRequest:
    return PauseRequest(
        pause_id="retry-pause",
        run_id="run",
        turn_id="turn",
        kind=PauseKind.PROVIDER_UNAVAILABLE,
        reason=PauseReason.NETWORK_ERROR,
        iteration=2,
        created_at="now",
    )


def _completed(
    text: str = "done",
    *parts: object,
    finish_reason: FinishReason = FinishReason.STOP,
) -> GenerationCompleted:
    return GenerationCompleted(
        ProviderResponse(
            message=Message("assistant", (TextPart(text), *parts)),
            usage=Usage(),
            finish_reason=finish_reason,
        )
    )


def _latest_tool_message(request: GenerationRequest) -> Message:
    for message in reversed(request.messages):
        if message.role == "tool":
            return message
    raise AssertionError("request has no tool message")


def _application(*events: object, delay: float = 0.0) -> UthCodeApplication:
    provider_events = events or (_completed("fake response"),)
    return UthCodeApplication(
        FakeProvider(
            events=provider_events, delay=delay, model_limits=TEST_LIMITS
        ),  # type: ignore[arg-type]
        runtime_context=ApplicationRuntimeContext.from_system(
            workdir=Path("C:/workspace"),
            platform_name="TestOS",
            platform_release="1.0",
            current_date="2026-08-06",
        ),
    )


async def _wait_until(predicate, attempts: int = 80) -> None:  # type: ignore[no-untyped-def]
    for _ in range(attempts):
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition did not become true")


async def _start_tui(
    application: UthCodeApplication | None = None,
) -> tuple[UthCodeTUI, object, asyncio.Task[int], RecordingOutput]:
    pipe_context = create_pipe_input()
    pipe = pipe_context.__enter__()
    output = RecordingOutput()
    tui = UthCodeTUI(
        application or _application(),
        input_device=pipe,
        terminal_output=output,
    )
    tui._run = _FakeRunProxy(tui._run)  # type: ignore[assignment]
    task = asyncio.create_task(tui.run_async())
    await _wait_until(lambda: tui.ui.is_running)
    return tui, (pipe_context, pipe), task, output


async def _stop_tui(
    tui: UthCodeTUI,
    pipe_state: object,
    task: asyncio.Task[int],
) -> None:
    pipe_context, pipe = pipe_state  # type: ignore[misc]
    if tui.ui.is_running:
        pipe.send_text("\x03")
    await asyncio.wait_for(task, timeout=2)
    pipe_context.__exit__(None, None, None)


async def _assert_tui_shutdown_cleanup(
    tui: UthCodeTUI,
    run: AgentRun,
    handle: TurnHandle,
) -> None:
    driver = handle._driver
    assert driver._result_future is not None
    assert driver._result_future.done()
    result = await handle.result()
    assert result.status is RunStatus.CANCELLED
    assert run._active_turn is None
    assert handle.pending_pause is None
    assert tui._generation_task is None
    assert tui._active_handle is None
    assert not tui._background_tasks
    assert driver._task is None
    assert driver._response_waiter is None
    assert driver._segment_signal is None


async def _assert_consumer_failure_cleanup(
    tui: UthCodeTUI,
    run: AgentRun,
    handle: TurnHandle,
    task: asyncio.Task[None],
) -> None:
    assert task.done()
    assert not task.cancelled()
    assert task.exception() is None
    driver = handle._driver
    assert driver._result_future is not None
    assert driver._result_future.done()
    result = await handle.result()
    assert result.status is RunStatus.CANCELLED
    assert run._active_turn is None
    assert handle.pending_pause is None
    assert driver._task is None
    assert driver._response_waiter is None
    assert driver._segment_signal is None
    assert tui._active_handle is None
    assert tui._generation_task is None
    assert not tui._background_tasks


def test_grapheme_backspace_lengths_cover_chinese_combining_and_emoji() -> None:
    assert previous_grapheme_length("你好") == 1
    assert previous_grapheme_length("e\u0301") == 2
    assert previous_grapheme_length("👨‍👩‍👧‍👦") == len("👨‍👩‍👧‍👦")
    assert previous_grapheme_length("") == 0


def test_double_escape_state_is_time_bound() -> None:
    esc = EscArmState()
    esc.arm(10.0)
    assert esc.consume(10.5) is True
    esc.arm(10.0)
    assert esc.consume(11.1) is False


def test_tui_interaction_state_handles_select_multi_other_and_review() -> None:
    request = UserInputRequest(
        (
            UserQuestion(
                "single",
                "Mode",
                "Choose a mode",
                QuestionKind.SINGLE_SELECT,
                (
                    QuestionOption("fast", "Fast mode"),
                    QuestionOption("safe", "Safe mode"),
                ),
            ),
            UserQuestion(
                "multi",
                "Targets",
                "Choose targets",
                QuestionKind.MULTI_SELECT,
                (
                    QuestionOption("api", "API"),
                    QuestionOption("ui", "UI"),
                ),
            ),
            UserQuestion(
                "other",
                "Owner",
                "Who owns it?",
                QuestionKind.SINGLE_SELECT,
                (
                    QuestionOption("team", "The team"),
                    QuestionOption("me", "The user"),
                ),
                allow_other=True,
            ),
        )
    )
    pause = PauseRequest(
        "pause",
        "run",
        "turn",
        PauseKind.USER_INPUT_REQUIRED,
        PauseReason.USER_INPUT_REQUIRED,
        1,
        "now",
        "call",
        request,
    )
    state = TuiInteractionState()
    state.open_pause(pause)
    assert state.mode is InteractionMode.QUESTIONS

    assert state.submit_current() is True
    assert state.answers["single"] == ["fast"]
    state.move(1)
    assert state.toggle_option() is True
    state.move(1)
    assert state.toggle_option() is True
    assert state.submit_current() is True
    assert state.answers["multi"] == ["api", "ui"]
    state.choose_other()
    state.set_draft("a partner")
    assert state.submit_current() is True
    assert state.mode is InteractionMode.REVIEW
    response = state.user_input_response()
    assert response is not None
    assert response.answers["other"] == ["a partner"]


def test_tui_interaction_state_renders_permission_choices_without_secret_payload() -> None:
    request = PermissionApprovalRequest(
        permission_id="permission-1",
        run_id="run",
        turn_id="turn",
        tool_call_id="call",
        tool="WriteFile",
        action="write",
        effect=Effect.WRITE,
        resource="safe.txt",
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
    pause = PauseRequest(
        pause_id="pause",
        run_id="run",
        turn_id="turn",
        kind=PauseKind.PERMISSION_REQUIRED,
        reason=PauseReason.PERMISSION_REQUIRED,
        iteration=1,
        created_at="now",
        tool_call_id="call",
        permission_request=request,
    )
    state = TuiInteractionState()
    state.open_pause(pause)
    assert state.mode is InteractionMode.PERMISSION
    assert state.permission_choices == request.choices
    assert "Allow for session" in "".join(text for _style, text in state.render_lines())
    assert "secret" not in "".join(text for _style, text in state.render_lines())
    state.move(1)
    response = state.permission_response()
    assert response is not None
    assert response.choice is PermissionApprovalChoice.SESSION


def test_tui_plan_review_state_approves_or_collects_revision_without_owning_plan_state() -> None:
    pause = _plan_review_pause(3)
    state = TuiInteractionState()
    state.open_pause(pause)

    assert state.mode is InteractionMode.PLAN_REVIEW
    assert state.plan_review_actions == (
        PlanReviewAction.APPROVE,
        PlanReviewAction.REVISE,
        PlanReviewAction.CANCEL,
    )
    assert state.selected_plan_review_action is PlanReviewAction.APPROVE
    rendered = "".join(text for _style, text in state.render_lines())
    assert "Plan v3" in rendered
    assert "Approve and execute" in rendered
    approve = state.plan_review_response()
    assert approve == PlanReviewResponse(
        "plan-pause",
        "run",
        "turn",
        3,
        PlanReviewChoice.APPROVE,
    )

    state.open_pause(pause)
    state.move(1)
    assert state.selected_plan_review_action is PlanReviewAction.REVISE
    assert state.begin_plan_revision() is True
    assert state.mode is InteractionMode.PLAN_REVISION
    state.set_draft("保留 public API")
    revise = state.plan_review_response()
    assert revise == PlanReviewResponse(
        "plan-pause",
        "run",
        "turn",
        3,
        PlanReviewChoice.REVISE,
        "保留 public API",
    )
    assert not hasattr(state, "plan_state")


def test_tui_interaction_exit_other_restores_legal_single_select_focus() -> None:
    question = UserQuestion(
        "mode",
        "Mode",
        "Choose a mode",
        QuestionKind.SINGLE_SELECT,
        (
            QuestionOption("fast", "Fast mode"),
            QuestionOption("safe", "Safe mode"),
        ),
        allow_other=True,
    )
    pause = PauseRequest(
        "pause",
        "run",
        "turn",
        PauseKind.USER_INPUT_REQUIRED,
        PauseReason.USER_INPUT_REQUIRED,
        1,
        "now",
        "call",
        UserInputRequest((question,)),
    )
    state = TuiInteractionState()
    state.open_pause(pause)

    state.move(1)
    assert state.toggle_option() is True
    state.move(1)
    assert state.option_index == len(question.options)
    assert state.choose_other() is True
    state.set_draft("custom")

    assert state.exit_other() is True
    assert state.other_mode is False
    assert state.draft == ""
    assert state.option_index == 1
    assert state.selected_options == {1}
    assert 0 <= state.option_index < len(question.options)

    state.open_pause(pause)
    state.move(len(question.options))
    assert state.choose_other() is True
    state.set_draft("custom")
    assert state.exit_other() is True
    assert state.other_mode is False
    assert state.draft == ""
    assert state.option_index == 0
    assert state.selected_options == set()
    assert 0 <= state.option_index < len(question.options)


def test_markdown_stream_waits_for_real_fence_closure() -> None:
    stream = MarkdownStream()
    assert stream.append("```text\ninside\n```not-a-close\n") == ()
    assert stream.committed == ""
    assert stream.append("```\n") == (
        "```text\ninside\n```not-a-close\n```\n",
    )


def test_markdown_stream_commits_paragraphs_and_force_flushes_tail() -> None:
    stream = MarkdownStream()
    assert stream.append("第一段\n\n") == ("第一段\n\n",)
    assert stream.append("- one\n- two") == ()
    assert stream.force() == "- one\n- two"


def test_renderer_keeps_interleaved_reasoning_and_assistant_blocks_in_event_order() -> None:
    now = [10.0]
    renderer = AgentEventRenderer(interval_seconds=0.5, clock=lambda: now[0])
    events = (
        ReasoningStarted("run", "turn", "m1", 1, 1),
        AgentReasoningDelta("run", "turn", "m1", 1, "R1"),
        ReasoningFinished("run", "turn", "m1", 1, 1),
        # A completed assistant message must be committed as one authority
        # update, while a later reasoning segment remains a new block.
        AssistantMessageDelta("run", "turn", "m1", 1, "A1"),
        AssistantMessageCompleted(
            "run", "turn", "m1", 1,
            AssistantMessageKind.PROGRESS,
            Message("assistant", (TextPart("A1"),)),
        ),
        ReasoningStarted("run", "turn", "m1", 1, 2),
        AgentReasoningDelta("run", "turn", "m1", 1, "R2"),
        ReasoningFinished("run", "turn", "m1", 1, 2),
        AssistantMessageDelta("run", "turn", "m1", 1, "A2"),
        AssistantMessageCompleted(
            "run", "turn", "m1", 1,
            AssistantMessageKind.FINAL,
            Message("assistant", (TextPart("A2"),)),
        ),
    )

    batches = []
    for index, event in enumerate(events):
        if index in {1, 3, 6, 8}:
            now[0] += 1.0
        batches.append(renderer.push(event))
    batches.append(renderer.flush())
    operations = [
        operation
        for batch in batches
        if batch is not None
        for operation in batch.operations
    ]

    assert [operation.kind for operation in operations] == [
        "text", "text", "text", "text", "text", "text"
    ]
    updates = [
        operation.value
        for operation in operations
        if operation.kind == "text"
    ]
    assert [(update.kind, update.text) for update in updates] == [
        ("reasoning", "R1"),
        ("assistant", "A1"),
        ("assistant", "A1"),
        ("reasoning", "R2"),
        ("assistant", "A2"),
        ("assistant", "A2"),
    ]
    assert [update.authoritative for update in updates] == [
        False, False, True, False, False, True
    ]


def test_renderer_exposes_reasoning_and_formal_semantic_bar_colours() -> None:
    renderer = RichTerminalRenderer(width=80)
    reasoning = renderer.reasoning_message("思考")
    formal = renderer.agent_message("回答")

    assert PALETTE.reasoning_accent != PALETTE.success
    assert f"38;2;{int(PALETTE.reasoning_accent[1:3], 16)};" in reasoning
    assert f"38;2;{int(PALETTE.success[1:3], 16)};" in formal


def test_reasoning_preview_uses_declared_prompt_toolkit_style() -> None:
    tui = UthCodeTUI(_application(), terminal_output=RecordingOutput())
    tui._streams.append(
        _StreamProjection(
            MarkdownStream(pending="思考中"),
            "reasoning",
            block_id="reasoning-preview",
        )
    )

    fragments = tui._preview_fragments()
    style = tui._style()
    reasoning_role = style.get_attrs_for_style_str("class:preview.reasoning.role")
    formal_role = style.get_attrs_for_style_str("class:preview.role")
    reasoning_body = style.get_attrs_for_style_str("class:preview.reasoning")

    assert fragments[0] == (
        "class:preview.reasoning.role",
        "┃ UthCode · reasoning:\n",
    )
    assert fragments[1] == ("class:preview.reasoning", "思考中")
    assert reasoning_role.color == PALETTE.reasoning_accent.lstrip("#")
    assert formal_role.color == PALETTE.success.lstrip("#")
    assert reasoning_role != formal_role
    assert reasoning_body.color == PALETTE.text.lstrip("#")


@pytest.mark.asyncio
async def test_assistant_delta_is_preview_only_until_authoritative_completion() -> None:
    output = RecordingOutput()
    tui = UthCodeTUI(_application(), terminal_output=output)

    await tui._apply_batch(
        RenderBatch(
            text=(TextUpdate("m:assistant", "assistant", "preview"),),
        )
    )
    assert tui._pending_text() == "preview"
    assert "preview" not in output.getvalue()

    await tui._apply_batch(
        RenderBatch(
            text=(
                TextUpdate(
                    "m:assistant",
                    "assistant",
                    "authoritative",
                    mode="replace",
                    authoritative=True,
                ),
            ),
        )
    )
    rendered = output.getvalue()
    assert tui._pending_text() == ""
    assert rendered.count("UthCode:") == 1
    assert "preview" not in rendered
    assert "authoritative" in rendered


@pytest.mark.asyncio
async def test_reasoning_tail_is_forced_before_formal_authority() -> None:
    output = RecordingOutput()
    tui = UthCodeTUI(_application(), terminal_output=output)

    await tui._apply_batch(
        RenderBatch(
            text=(TextUpdate("m:reasoning:1", "reasoning", "reasoning tail"),)
        )
    )
    await tui._apply_batch(
        RenderBatch(
            text=(
                TextUpdate(
                    "m:assistant:1",
                    "assistant",
                    "formal answer",
                    mode="replace",
                    authoritative=True,
                ),
            )
        )
    )
    plain = Text.from_ansi(output.getvalue()).plain
    assert plain.index("reasoning tail") < plain.index("formal answer")


@pytest.mark.asyncio
async def test_tool_boundary_forces_reasoning_but_keeps_assistant_preview() -> None:
    output = RecordingOutput()
    tui = UthCodeTUI(_application(), terminal_output=output)

    await tui._apply_batch(
        RenderBatch(
            text=(
                TextUpdate("m:reasoning", "reasoning", "reasoning tail"),
                TextUpdate("m:assistant", "assistant", "assistant preview"),
            )
        )
    )
    await tui._apply_batch(
        RenderBatch(
            tools=(ToolUpdate("call-1", "Bash", "dir", "finished"),),
        )
    )

    plain = Text.from_ansi(output.getvalue()).plain
    assert "reasoning tail" in plain
    assert "finished" in plain and "Bash" in plain
    assert "assistant preview" not in plain
    assert tui._pending_text() == "assistant preview"


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal", ["failed", "cancelled"])
async def test_failed_or_cancelled_terminal_discards_assistant_preview(
    terminal: str,
) -> None:
    output = RecordingOutput()
    tui = UthCodeTUI(_application(), terminal_output=output)

    await tui._apply_batch(
        RenderBatch(
            text=(
                TextUpdate("m:reasoning", "reasoning", "reasoning tail"),
                TextUpdate("m:assistant", "assistant", "assistant preview"),
            )
        )
    )
    await tui._apply_batch(
        RenderBatch(
            terminal=terminal,
            terminal_message="provider failed" if terminal == "failed" else None,
        )
    )

    plain = Text.from_ansi(output.getvalue()).plain
    assert "reasoning tail" in plain
    assert "assistant preview" not in plain
    assert tui._pending_text() == ""
    assert "UthCode:" not in plain


@pytest.mark.asyncio
async def test_completed_terminal_commits_final_once_after_tool_boundary() -> None:
    output = RecordingOutput()
    tui = UthCodeTUI(_application(), terminal_output=output)

    await tui._apply_batch(
        RenderBatch(
            text=(TextUpdate("m:assistant", "assistant", "preview"),),
            tools=(ToolUpdate("call-1", "Bash", "dir", "finished"),),
        )
    )
    await tui._apply_batch(
        RenderBatch(
            terminal="completed",
            final_text="authoritative final",
        )
    )

    plain = Text.from_ansi(output.getvalue()).plain
    assert "preview" not in plain
    assert plain.count("UthCode:") == 1
    assert plain.count("authoritative final") == 1


@pytest.mark.asyncio
async def test_real_stream_keeps_reasoning_before_one_formal_permanent_block() -> None:
    provider = _ScriptedProvider(
        ((
            ProviderReasoningDelta("先思考"),
            TextDelta("正式回复"),
            _completed("正式回复"),
        ),),
        delay=0.21,
    )
    application = UthCodeApplication(
        provider,
        runtime_context=ApplicationRuntimeContext.from_system(
            workdir=Path("C:/workspace"),
            platform_name="TestOS",
            platform_release="1.0",
            current_date="2026-08-06",
        ),
    )
    output = RecordingOutput()
    tui = UthCodeTUI(application, terminal_output=output)
    tui._start_turn("hello")
    task = tui._generation_task
    assert task is not None
    await task

    plain = Text.from_ansi(output.getvalue()).plain
    assert plain.index("先思考") < plain.index("正式回复")
    assert plain.count("UthCode · reasoning") == 1
    assert plain.count("UthCode:") == 1


@pytest.mark.asyncio
async def test_real_consumer_keeps_delayed_assistant_delta_in_preview_until_final() -> None:
    provider = _ScriptedProvider(
        ((TextDelta("draft"), _completed("final")),),
        delay=0.21,
    )
    application = UthCodeApplication(
        provider,
        runtime_context=ApplicationRuntimeContext.from_system(
            workdir=Path("C:/workspace"),
            platform_name="TestOS",
            platform_release="1.0",
            current_date="2026-08-06",
        ),
    )
    output = RecordingOutput()
    tui = UthCodeTUI(application, terminal_output=output)
    tui._start_turn("hello")
    task = tui._generation_task
    assert task is not None

    await _wait_until(lambda: tui._pending_text() == "draft", attempts=200)
    assert "draft" not in output.getvalue()
    await task

    plain = Text.from_ansi(output.getvalue()).plain
    assert "draft" not in plain
    assert plain.count("UthCode:") == 1
    assert plain.count("final") == 1


@pytest.mark.asyncio
async def test_real_consumer_cancellation_discards_assistant_draft() -> None:
    provider = _ScriptedProvider(
        ((TextDelta("cancel draft"), _completed("never shown")),),
        delay=0.21,
    )
    application = UthCodeApplication(
        provider,
        runtime_context=ApplicationRuntimeContext.from_system(
            workdir=Path("C:/workspace"),
            platform_name="TestOS",
            platform_release="1.0",
            current_date="2026-08-06",
        ),
    )
    output = RecordingOutput()
    tui = UthCodeTUI(application, terminal_output=output)
    tui._start_turn("hello")
    task = tui._generation_task
    assert task is not None

    await _wait_until(lambda: tui._pending_text() == "cancel draft", attempts=200)
    task.cancel()
    await task

    plain = Text.from_ansi(output.getvalue()).plain
    assert "cancel draft" not in plain
    assert "never shown" not in plain
    assert tui._pending_text() == ""


@pytest.mark.asyncio
async def test_real_consumer_failure_discards_assistant_draft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _ScriptedProvider(
        ((TextDelta("failed draft"), _completed("never shown")),),
        delay=0.21,
    )
    original_push = AgentEventRenderer.push

    def fail_on_authority(
        renderer: AgentEventRenderer,
        event: AgentEvent,
    ) -> RenderBatch | None:
        if event.event_type == "assistant_message_completed":
            raise RuntimeError("consumer projection failed")
        return original_push(renderer, event)

    monkeypatch.setattr(AgentEventRenderer, "push", fail_on_authority)
    application = UthCodeApplication(
        provider,
        runtime_context=ApplicationRuntimeContext.from_system(
            workdir=Path("C:/workspace"),
            platform_name="TestOS",
            platform_release="1.0",
            current_date="2026-08-06",
        ),
    )
    output = RecordingOutput()
    tui = UthCodeTUI(application, terminal_output=output)
    tui._start_turn("hello")
    task = tui._generation_task
    assert task is not None
    await task

    plain = Text.from_ansi(output.getvalue()).plain
    assert "failed draft" not in plain
    assert tui._pending_text() == ""
    assert tui.activity == "error"


@pytest.mark.asyncio
async def test_resume_hydrate_is_ordered_bounded_and_does_not_enter_live_stream() -> None:
    output = RecordingOutput()
    tui = UthCodeTUI(_application(), terminal_output=output)
    records = tuple(
        SessionReplayRecord(
            "resume-1", index, "turn-1", kind, text=text,
            tool_name="Bash" if kind == "tool" else None,
            tool_call_id=f"call-{index}" if kind == "tool" else None,
            status="finished" if kind == "tool" else None,
        )
        for index, (kind, text) in enumerate(
            (("user", "你好"), ("reasoning", "先想"),
             ("assistant", "回答"), ("tool", "dir")),
            start=1,
        )
    )
    emits: list[str] = []
    yields = 0

    async def capture(value: str) -> None:
        emits.append(value)

    async def record_yield() -> None:
        nonlocal yields
        yields += 1

    tui._emit = capture  # type: ignore[method-assign]
    tui._yield_replay = record_yield  # type: ignore[method-assign]
    await tui._apply_command_outcome(
        "/resume resume-1",
        CommandOutcome(
            OutcomeStatus.SUCCESS,
            ui_action=SessionChanged("resume-1", restored=True, replay=records),
        ),
    )

    plain = Text.from_ansi("".join(emits)).plain
    assert plain.index("你好") < plain.index("先想") < plain.index("回答") < plain.index("Bash")
    assert plain.count("你好") == 1
    assert plain.count("先想") == 1
    assert plain.count("回答") == 1
    assert plain.count("dir") == 1
    assert not tui._streams
    assert yields == 0  # one batch is not required to yield


@pytest.mark.asyncio
async def test_resume_hydrate_yields_between_bounded_batches() -> None:
    tui = UthCodeTUI(_application(), terminal_output=RecordingOutput())
    records = tuple(
        SessionReplayRecord("resume-2", index, "turn-1", "user", f"line-{index}")
        for index in range(1, 66)
    )
    emits: list[str] = []
    yields = 0

    async def capture(value: str) -> None:
        emits.append(value)

    async def record_yield() -> None:
        nonlocal yields
        yields += 1

    tui._emit = capture  # type: ignore[method-assign]
    tui._yield_replay = record_yield  # type: ignore[method-assign]
    await tui._hydrate_replay(records)

    assert len(emits) == 3
    assert yields == 2
    assert "line-1" in emits[0]
    assert "line-33" in emits[1]
    assert "line-65" in emits[2]


@pytest.mark.asyncio
async def test_tui_startup_is_lazy_and_first_input_ensures_session() -> None:
    application = _application()
    calls: list[str] = []
    original_ensure = application.ensure_session

    def record_ensure():  # type: ignore[no-untyped-def]
        calls.append("ensure")
        return original_ensure()

    application.ensure_session = record_ensure  # type: ignore[method-assign]
    tui = UthCodeTUI(application, terminal_output=RecordingOutput())
    assert calls == []
    await tui._show_startup()
    assert calls == []
    tui._start_turn("first input")
    assert calls == ["ensure"]
    await tui.shutdown()


@pytest.mark.asyncio
async def test_tui_cold_start_help_status_picker_and_exit_do_not_create_session(
    tmp_path: Path,
) -> None:
    store = SessionFileStore(tmp_path / "sessions")
    provider = FakeProvider(events=(_completed("unused"),), model_limits=TEST_LIMITS)
    application = create_application(
        EffectiveConfig.single_model("fake/model", context_window=1_000_000),
        provider_builder=lambda _profile, _model: provider,
        runtime_context=ApplicationRuntimeContext.from_system(workdir=tmp_path),
        session_store=store,
    )
    tui, pipe_state, task, _output = await _start_tui(application)
    try:
        assert application.list_sessions() == ()
        await tui._handle_submission("/help")
        await tui._handle_submission("/status")
        await tui._handle_submission("/resume")
        assert application.list_sessions() == ()
    finally:
        await _stop_tui(tui, pipe_state, task)
    assert application.list_sessions() == ()


def test_t08_events_project_plan_task_mode_steering_and_completion_control() -> None:
    renderer = AgentEventRenderer(clock=lambda: 10.0)
    plan = renderer.push(
        PlanProposed("run", "turn", 1, 2, "# 完整 Plan v2")
    )
    assert plan is not None
    assert plan.plans == (PlanUpdate(2, "# 完整 Plan v2"),)

    task_state = TaskState(
        (
            TaskItem("探索", TaskStatus.COMPLETED),
            TaskItem("实现", TaskStatus.IN_PROGRESS),
            TaskItem("验证", TaskStatus.PENDING),
        )
    )
    tasks = renderer.push(TaskStateChanged("run", "turn", 2, task_state))
    assert tasks is not None
    assert tasks.task_states == (
        TaskStateUpdate(
            (
                ("completed", "探索"),
                ("in_progress", "实现"),
                ("pending", "验证"),
            )
        ),
    )

    requested = renderer.push(UserSteeringRequested("run", "turn", "steer-1"))
    applied = renderer.push(UserSteeringApplied("run", "turn", "steer-1"))
    blocked = renderer.push(CompletionBlocked("run", "turn", 3, 2))
    mode = renderer.push(
        BehaviorModeChanged(
            "run",
            "turn",
            BehaviorMode.PLAN,
            BehaviorMode.DEFAULT,
        )
    )

    assert requested is not None and requested.activity == "steering…"
    assert applied is not None and applied.activity == "updating task…"
    assert requested.users == () and applied.users == ()
    assert blocked is not None
    assert blocked.activity == "continuing · 2 unfinished tasks"
    assert blocked.text == () and blocked.final_text is None
    assert mode is not None and mode.activity == "mode: default"


@pytest.mark.asyncio
async def test_tui_consumes_application_failure_projection_without_native_details() -> None:
    renderer = AgentEventRenderer(clock=lambda: 10.0)
    event = TurnFailed(
        "run",
        "turn",
        TerminationReason.PROVIDER_ERROR,
        FailureReason.AUTHENTICATION,
    )
    batch = renderer.push(event)

    assert batch is not None
    assert batch.terminal == "failed"
    assert batch.terminal_message == failure_message(FailureReason.AUTHENTICATION)

    output = RecordingOutput()
    tui = UthCodeTUI(_application(), terminal_output=output)
    await tui._apply_batch(batch)
    rendered = output.getvalue()
    assert failure_message(FailureReason.AUTHENTICATION) in rendered
    assert "AuthenticationError" not in rendered
    assert "traceback" not in rendered


def test_tui_pause_projection_uses_the_application_owner() -> None:
    assert pause_message(PauseReason.TIMEOUT) == "provider request timed out; retry available"


@pytest.mark.asyncio
async def test_plan_revisions_and_task_state_append_as_distinct_permanent_blocks() -> None:
    output = RecordingOutput()
    tui = UthCodeTUI(_application(), terminal_output=output)

    await tui._apply_batch(
        RenderBatch(
            plans=(
                PlanUpdate(1, "# 方案一"),
                PlanUpdate(2, "# 完整替代方案二"),
            ),
            task_states=(
                TaskStateUpdate(
                    (
                        ("completed", "探索"),
                        ("in_progress", "实现"),
                        ("pending", "验证"),
                    )
                ),
            ),
        )
    )

    rendered = output.getvalue()
    plain = Text.from_ansi(rendered).plain
    assert rendered.count("UthCode · Plan v1") == 1
    assert rendered.count("UthCode · Plan v2") == 1
    assert "方案一" in rendered and "完整替代方案二" in rendered
    assert "✓ 探索" in plain
    assert "› 实现" in plain
    assert "○ 验证" in plain
    assert PALETTE.plan_background != PALETTE.user_background
    assert PALETTE.plan_accent != PALETTE.muted
    plan_rgb = tuple(
        int(PALETTE.plan_background[index : index + 2], 16)
        for index in (1, 3, 5)
    )
    assert f"48;2;{plan_rgb[0]};{plan_rgb[1]};{plan_rgb[2]}m" in rendered


def test_renderer_restores_roles_surfaces_markdown_and_code_colours() -> None:
    renderer = RichTerminalRenderer(width=80)
    user = renderer.user_message("你好")
    agent = renderer.agent_message(
        "# 标题\n\n- 一\n- 二\n\n`inline`\n\n"
        "```python\nprovider = self._provider\nprint(provider)\n```"
    )
    assert "you" in user
    assert "UthCode:" in agent
    assert "┃" in user and "┃" in agent
    assert "48;2;36;47;56m" in user
    assert "48;2;30;30;30m" not in agent
    assert "48;2;18;18;18m" in agent
    assert "38;2;224;224;224m" in agent
    assert "38;2;254;166;43" in agent
    assert "38;2;0;0;0" not in agent


def test_renderer_keeps_truecolor_when_no_color_is_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    renderer = RichTerminalRenderer(width=80)
    user = renderer.user_message("你好")
    agent = renderer.agent_message(
        "回答\n\n```python\nprint('ok')\n```",
    )
    tool = renderer.tool(status="finished", name="Bash", command="dir")

    assert "48;2;36;47;56m" in user
    assert "38;2;224;224;224m" in agent
    assert "48;2;18;18;18m" in agent
    assert "38;2;78;191;113m" in tool
    assert "\x1b[38;2;154;154;154m┃" in tool


def test_tool_rows_keep_status_text_and_semantic_colour() -> None:
    renderer = RichTerminalRenderer(width=80)
    success = renderer.tool(status="finished", name="Bash", command="dir")
    failure = renderer.tool(status="denied", name="Bash", command="del")
    assert "finished" in success and "38;2;78;191;113m" in success
    assert "denied" in failure and "38;2;185;60;91m" in failure
    assert "\x1b[38;2;154;154;154m┃" in success
    assert "\x1b[38;2;154;154;154m┃" in failure
    assert success.endswith("\n\n") and failure.endswith("\n\n")


@pytest.mark.parametrize(
    ("tool_name", "command", "status"),
    [
        ("AskUserQuestion", "<user input required>", "finished"),
        ("TodoWrite", "<task state update>", "finished"),
        ("ProposePlan", "<plan review required>", "finished"),
        ("Reveal", "<tool summary unavailable>", "denied"),
    ],
)
def test_tui_consumes_real_tool_events_without_repeating_tool_name(
    tool_name: str,
    command: str,
    status: str,
) -> None:
    renderer = AgentEventRenderer(clock=lambda: 10.0)
    events = (
        ToolStarted("run", "turn", 1, "batch", "call", tool_name, command),
        ToolFinished("run", "turn", 1, "batch", "call", tool_name, command, status, status == "denied"),
    )

    batches = [renderer.push(event) for event in events]
    updates = [batch.tools[0] for batch in batches if batch is not None]

    assert [(update.tool_name, update.command, update.status) for update in updates] == [
        (tool_name, command, "running"),
        (tool_name, command, status),
    ]
    rendered = RichTerminalRenderer(width=80).tool(
        status=updates[-1].status,
        name=updates[-1].tool_name,
        command=updates[-1].command,
    )
    assert Text.from_ansi(rendered).plain.count(tool_name) == 1


@pytest.mark.skipif(sys.platform != "win32", reason="Windows console event")
def test_windows_native_shift_enter_maps_to_newline() -> None:
    from prompt_toolkit.keys import Keys
    from prompt_toolkit.win32_types import KEY_EVENT_RECORD

    input_device = create_windows_unicode_input()
    reader = input_device.console_input_reader  # type: ignore[attr-defined]
    event = KEY_EVENT_RECORD()
    event.KeyDown = 1
    event.RepeatCount = 1
    event.VirtualKeyCode = 13
    event.VirtualScanCode = 28
    event.uChar.UnicodeChar = "\r"
    event.ControlKeyState = reader.SHIFT_PRESSED
    keys = reader._event_to_key_presses(event)
    assert [key.key for key in keys] == [Keys.ControlJ]


def test_composer_prompt_is_separate_from_ime_buffer_cursor() -> None:
    tui = UthCodeTUI(_application(), terminal_output=RecordingOutput())
    composer = tui._composer
    assert isinstance(composer, VSplit)
    assert len(composer.children) == 2
    assert composer.children[1].content is tui._buffer_control


@pytest.mark.asyncio
async def test_tui_permission_picker_uses_run_session_and_warns_on_full_access() -> None:
    output = RecordingOutput()
    tui = UthCodeTUI(_application(), terminal_output=output)
    tui.application._permission_writer = lambda _mode: None
    outcome = await tui.dispatcher.dispatch_text_async("/permission")
    assert outcome is not None
    await tui._apply_command_outcome("/permission", outcome)
    assert tui.permission_picker.open is True
    assert tui._run.permission_mode is PermissionMode.DEFAULT

    tui.permission_picker.move(1)
    tui._select_permission_mode()
    await _wait_until(lambda: tui._run.permission_mode is PermissionMode.AUTO)
    assert tui._run.permission_mode is PermissionMode.AUTO
    assert tui.application.create_run().permission_mode is PermissionMode.AUTO

    outcome = await tui.dispatcher.dispatch_text_async("/permission")
    assert outcome is not None
    await tui._apply_command_outcome("/permission", outcome)
    tui.permission_picker.move(1)
    assert tui.permission_picker.selected is PermissionMode.FULL_ACCESS
    tui._select_permission_mode()
    await _wait_until(lambda: tui._run.permission_mode is PermissionMode.FULL_ACCESS)
    assert tui._run.permission_mode is PermissionMode.FULL_ACCESS
    assert "高风险提示" in output.getvalue()


def test_tui_status_warns_only_on_full_access_permission_fragment() -> None:
    tui = UthCodeTUI(_application(), terminal_output=RecordingOutput())

    default_fragments = tui._status_fragments()
    assert all(style == "class:status" for style, _text in default_fragments)

    tui._run.set_permission_mode(PermissionMode.FULL_ACCESS)
    fragments = tui._status_fragments()
    warning = [(style, text) for style, text in fragments if "permission:" in text]
    assert warning == [("class:status.warning", "permission: full_access")]
    assert all(
        style == "class:status"
        for style, text in fragments
        if "permission:" not in text
    )
    assert tui._style().get_attrs_for_style_str("class:status.warning").color == PALETTE.error.removeprefix("#")


@pytest.mark.asyncio
async def test_behavior_mode_action_updates_idle_run_separator_and_status_dimensions() -> None:
    output = RecordingOutput()
    tui = UthCodeTUI(_application(), terminal_output=output)
    run = _FakeModeRun()
    tui._run = run  # type: ignore[assignment]

    plan = await tui.dispatcher.dispatch_text_async("/plan")
    assert plan is not None and plan.ui_action == BehaviorModeSelected(BehaviorMode.PLAN)
    await tui._apply_command_outcome("/plan", plan)

    assert run.selected == [BehaviorMode.PLAN]
    assert tui._separator_fragments()[0][0] == "class:separator.plan"
    status = "".join(text for _style, text in tui._status_fragments())
    assert "mode: plan" in status
    assert "permission: default" in status

    execute = await tui.dispatcher.dispatch_text_async("/do")
    assert execute is not None
    await tui._apply_command_outcome("/do", execute)
    assert run.selected == [BehaviorMode.PLAN, BehaviorMode.DEFAULT]
    assert tui._separator_fragments()[0][0] == "class:separator"


@pytest.mark.asyncio
async def test_behavior_mode_action_does_not_switch_an_active_turn() -> None:
    output = RecordingOutput()
    tui = UthCodeTUI(_application(), terminal_output=output)
    run = _FakeModeRun()
    tui._run = run  # type: ignore[assignment]
    tui._active_handle = _FakeSteeringHandle()  # type: ignore[assignment]

    plan = await tui.dispatcher.dispatch_text_async("/plan")
    assert plan is not None
    await tui._apply_command_outcome("/plan", plan)

    assert run.selected == []
    assert run.behavior_mode is BehaviorMode.DEFAULT
    assert "生成进行中不能切换行为模式" in output.getvalue()


@pytest.mark.asyncio
async def test_active_turn_text_steers_and_appends_user_message_exactly_once() -> None:
    output = RecordingOutput()
    tui = UthCodeTUI(_application(), terminal_output=output)
    handle = _FakeSteeringHandle()
    tui._active_handle = handle  # type: ignore[assignment]

    await tui._handle_submission("和 2")
    requested = AgentEventRenderer(clock=lambda: 10.0).push(
        UserSteeringRequested("run", "turn", "steer-1")
    )
    applied = AgentEventRenderer(clock=lambda: 10.0).push(
        UserSteeringApplied("run", "turn", "steer-1")
    )
    assert requested is not None and applied is not None
    await tui._apply_batch(requested)
    await tui._apply_batch(applied)

    assert handle.steer_calls == ["和 2"]
    assert output.getvalue().count("和 2") == 1
    assert tui.activity == "updating task…"


@pytest.mark.asyncio
async def test_pending_typed_interaction_prevents_plain_text_steering() -> None:
    tui = UthCodeTUI(_application(), terminal_output=RecordingOutput())
    pause = _ask_user_pause()
    handle = _FakeSteeringHandle(pending_pause=pause)
    tui._active_handle = handle  # type: ignore[assignment]

    await tui._handle_submission("不能旁路")

    assert handle.steer_calls == []
    assert tui.interaction.pause is pause
    assert tui.interaction.mode is InteractionMode.QUESTIONS


@pytest.mark.parametrize(
    ("pause", "slash", "expected_mode"),
    (
        (_plan_review_pause(), "/plan", InteractionMode.PLAN_REVIEW),
        (_ask_user_pause(), "/clear", InteractionMode.QUESTIONS),
        (_permission_pause(), "/permission auto", InteractionMode.PERMISSION),
        (_retry_pause(), "/quit", InteractionMode.PAUSE_ACTION),
    ),
)
@pytest.mark.asyncio
async def test_closed_pending_typed_pause_reopens_before_any_slash_dispatch(
    pause: PauseRequest,
    slash: str,
    expected_mode: InteractionMode,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tui = UthCodeTUI(_application(), terminal_output=RecordingOutput())
    handle = _FakeSteeringHandle(pending_pause=pause)
    tui._active_handle = handle  # type: ignore[assignment]
    tui.interaction.open_pause(pause)
    tui._handle_interaction_escape()
    assert tui.interaction.mode is InteractionMode.CLOSED

    dispatch_calls: list[object] = []

    async def record_dispatch(invocation: object) -> None:
        dispatch_calls.append(invocation)

    monkeypatch.setattr(tui.dispatcher, "dispatch_async", record_dispatch)

    await tui._handle_submission(slash)

    assert dispatch_calls == []
    assert tui.interaction.pause is pause
    assert tui.interaction.mode is expected_mode
    assert handle.steer_calls == []
    assert handle.resume_calls == []
    assert handle.cancel_calls == 0
    assert tui._closing is False


@pytest.mark.parametrize(
    "mode",
    (
        InteractionMode.PAUSE_ACTION,
        InteractionMode.PERMISSION,
        InteractionMode.QUESTIONS,
        InteractionMode.PLAN_REVIEW,
    ),
)
@pytest.mark.asyncio
async def test_open_typed_interaction_consumes_submit_before_steering(
    mode: InteractionMode,
) -> None:
    tui = UthCodeTUI(_application(), terminal_output=RecordingOutput())
    handle = _FakeSteeringHandle(pending_pause=object())
    tui._active_handle = handle  # type: ignore[assignment]
    tui.interaction.mode = mode

    await tui._handle_submission("typed input")

    assert handle.steer_calls == []


def test_loading_w03_tui_tests_does_not_mutate_production_run_class_attributes() -> None:
    test_path = Path(__file__).resolve()
    repo_root = test_path.parents[1]
    src_path = repo_root / "src"
    script = f"""
import runpy
from uthcode.application import AgentRun, TurnHandle

before = (frozenset(vars(AgentRun)), frozenset(vars(TurnHandle)))
runpy.run_path({str(test_path)!r}, run_name="w03_tui_test_contract_probe")
after = (frozenset(vars(AgentRun)), frozenset(vars(TurnHandle)))
if before != after:
    raise AssertionError(
        "production class attributes changed while loading W03 tests: "
        f"AgentRun added={{sorted(after[0] - before[0])}}, "
        f"TurnHandle added={{sorted(after[1] - before[1])}}"
    )
"""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        value
        for value in (str(src_path), environment.get("PYTHONPATH", ""))
        if value
    )

    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=repo_root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_plan_approve_mode_change_restores_default_separator_immediately() -> None:
    tui = UthCodeTUI(_application(), terminal_output=RecordingOutput())
    run = _FakeModeRun(BehaviorMode.PLAN)
    tui._run = run  # type: ignore[assignment]
    assert tui._separator_fragments()[0][0] == "class:separator.plan"

    run.behavior_mode = BehaviorMode.DEFAULT
    batch = AgentEventRenderer(clock=lambda: 10.0).push(
        BehaviorModeChanged(
            "run",
            "turn",
            BehaviorMode.PLAN,
            BehaviorMode.DEFAULT,
        )
    )
    assert batch is not None

    assert tui._separator_fragments()[0][0] == "class:separator"


def test_tui_submits_plan_approve_and_revision_through_existing_resume_api() -> None:
    tui = UthCodeTUI(_application(), terminal_output=RecordingOutput())
    handle = _FakeSteeringHandle(pending_pause=_plan_review_pause(4))
    tui._active_handle = handle  # type: ignore[assignment]
    tui.interaction.open_pause(handle.pending_pause)  # type: ignore[arg-type]

    tui._submit_interaction()

    assert handle.resume_calls == [
        PlanReviewResponse(
            "plan-pause",
            "run",
            "turn",
            4,
            PlanReviewChoice.APPROVE,
        )
    ]
    assert tui.interaction.mode is InteractionMode.CLOSED

    handle.pending_pause = _plan_review_pause(5)
    tui.interaction.open_pause(handle.pending_pause)
    tui.interaction.move(1)
    tui._submit_interaction()
    assert tui.interaction.mode is InteractionMode.PLAN_REVISION
    tui.buffer.set_document(Document("缩小范围", len("缩小范围")), bypass_readonly=True)
    tui._submit_interaction()
    assert handle.resume_calls[-1] == PlanReviewResponse(
        "plan-pause",
        "run",
        "turn",
        5,
        PlanReviewChoice.REVISE,
        "缩小范围",
    )


@pytest.mark.asyncio
async def test_hardware_cursor_tracks_persistent_buffer_window_at_bottom() -> None:
    tui, pipe_state, task, _output = await _start_tui()
    _context, pipe = pipe_state  # type: ignore[misc]
    try:
        pipe.send_text("hi")
        await _wait_until(lambda: tui.buffer.text == "hi")
        await asyncio.sleep(0.05)
        screen = tui.ui.renderer.last_rendered_screen
        point = screen.get_cursor_position(tui.ui.layout.current_window)
        assert point.x == 6  # two letters after the four-column prompt
        assert point.y == tui.ui.output.get_size().rows - 4
        assert tui.ui.layout.current_window in screen.cursor_positions
    finally:
        await _stop_tui(tui, pipe_state, task)


def test_composer_is_three_lines_then_expands_with_content() -> None:
    tui = UthCodeTUI(_application(), terminal_output=RecordingOutput())
    tui._terminal_size = lambda: (40, 20)  # type: ignore[method-assign]
    assert tui._composer_height() == 3
    tui.buffer.set_document(Document("一\n二\n三\n四", 7), bypass_readonly=True)
    assert tui._composer_height() == 4


def test_stream_preview_tracks_latest_rows_instead_of_freezing_at_top() -> None:
    assert _tail_for_preview(
        "第一行\n第二行\n第三行\n第四行",
        width=20,
        height=2,
    ) == "第三行\n第四行"
    assert _tail_for_preview(
        "123456789",
        width=3,
        height=2,
    ) == "456\n789"


def test_nested_markdown_code_fence_uses_a_longer_outer_fence() -> None:
    source = (
        "```markdown\n"
        "# 文档\n\n"
        "```python\n"
        "print('嵌套代码块')\n"
        "```\n"
        "```\n"
    )
    protected = _protect_nested_markdown_fences(source)
    assert protected.startswith("````markdown\n")
    assert protected.endswith("````\n")
    assert "```python\nprint('嵌套代码块')\n```\n" in protected


def test_welcome_contains_logo_model_cwd_and_no_global_background() -> None:
    value = RichTerminalRenderer(width=100).welcome(
        "deepseek/chat", "C:\\workspace"
    )
    assert "UthCode" in value
    assert "deepseek/chat" in value
    assert "C:\\workspace" in value
    assert "Shift+Enter" in value


@pytest.mark.asyncio
async def test_startup_clears_viewport_without_clearing_scrollback_or_alt_screen() -> None:
    tui, pipe_state, task, output = await _start_tui()
    try:
        rendered = output.getvalue()
        raw_writes = [
            value
            for operation, value in output.events
            if operation == "raw"
        ]
        assert raw_writes[0] == SYNCHRONIZED_OUTPUT_ON
        assert raw_writes[1].startswith(CLEAR_VIEWPORT)
        assert raw_writes[2] == SYNCHRONIZED_OUTPUT_OFF
        assert SYNCHRONIZED_OUTPUT_OFF in rendered
        assert KITTY_KEYBOARD_ON in rendered
        assert "\x1b[3J" not in rendered
        assert "\x1b[?1049" not in rendered
        assert "\x1b[?1000" not in rendered
        assert tui.ui.full_screen is False
    finally:
        await _stop_tui(tui, pipe_state, task)
    assert KITTY_KEYBOARD_OFF in output.getvalue()


@pytest.mark.asyncio
async def test_permanent_commit_wraps_erase_content_and_redraw_on_one_output() -> None:
    tui, pipe_state, task, output = await _start_tui()
    try:
        output.events.clear()
        await tui._emit("PERMANENT")
        on = output.events.index(("raw", SYNCHRONIZED_OUTPUT_ON))
        content = output.events.index(("raw", "PERMANENT"))
        off = output.events.index(("raw", SYNCHRONIZED_OUTPUT_OFF))
        assert on < content < off
        assert any(
            operation == "erase_down"
            for operation, _value in output.events[on + 1 : content]
        )
        assert any(
            operation in {"write", "cursor_goto"}
            for operation, _value in output.events[content + 1 : off]
        )
    finally:
        await _stop_tui(tui, pipe_state, task)


@pytest.mark.asyncio
async def test_one_event_batch_uses_one_permanent_terminal_commit() -> None:
    tui = UthCodeTUI(_application(), terminal_output=RecordingOutput())
    writes: list[str] = []

    async def capture(value: str) -> None:
        writes.append(value)

    tui._emit = capture  # type: ignore[method-assign]
    await tui._apply_batch(
        RenderBatch(
            users=(("user", "问题"),),
            text=(
                TextUpdate(
                    "assistant",
                    "assistant",
                    "第一段。\n\n第二段。",
                    mode="replace",
                    authoritative=True,
                ),
            ),
            tools=(ToolUpdate("tool", "Bash", "dir", "finished"),),
        )
    )
    assert len(writes) == 1
    assert "问题" in writes[0]
    assert "第一段" in writes[0] and "第二段" in writes[0]
    assert "finished" in writes[0]


@pytest.mark.asyncio
async def test_permanent_render_uses_current_terminal_width() -> None:
    tui = UthCodeTUI(_application(), terminal_output=RecordingOutput())
    tui._terminal_size = lambda: (52, 20)  # type: ignore[method-assign]
    await tui._apply_batch(RenderBatch(users=(("user", "问题"),)))
    assert tui._renderer.width == 52


@pytest.mark.asyncio
async def test_unicode_input_and_grapheme_backspace_do_not_exit() -> None:
    tui, pipe_state, task, _output = await _start_tui()
    pipe_context, pipe = pipe_state  # type: ignore[misc]
    del pipe_context
    try:
        pipe.send_text("你好")
        await _wait_until(lambda: tui.buffer.text == "你好")
        pipe.send_text("\x7f")
        await _wait_until(lambda: tui.buffer.text == "你")
        pipe.send_text("\x7f\x7f")
        await _wait_until(lambda: tui.buffer.text == "")
        assert tui.ui.is_running
        pipe.send_text("e\u0301")
        await _wait_until(lambda: tui.buffer.text == "e\u0301")
        pipe.send_text("\x7f")
        await _wait_until(lambda: tui.buffer.text == "")
        assert tui.ui.is_running
    finally:
        await _stop_tui(tui, pipe_state, task)


@pytest.mark.asyncio
async def test_slash_menu_keeps_accepting_text_and_backspace() -> None:
    tui, pipe_state, task, _output = await _start_tui()
    _context, pipe = pipe_state  # type: ignore[misc]
    try:
        pipe.send_text("/")
        await _wait_until(lambda: tui.completion.open)
        pipe.send_text("status")
        await _wait_until(lambda: tui.buffer.text == "/status")
        assert tui.completion.open
        pipe.send_text("\x7f")
        await _wait_until(lambda: tui.buffer.text == "/statu")
        assert tui.ui.is_running
    finally:
        await _stop_tui(tui, pipe_state, task)


@pytest.mark.asyncio
async def test_shift_enter_ctrl_j_and_multiline_paste_preserve_newlines() -> None:
    tui, pipe_state, task, _output = await _start_tui()
    _context, pipe = pipe_state  # type: ignore[misc]
    try:
        pipe.send_text("甲\x1b[13;2u乙")
        await _wait_until(lambda: tui.buffer.text == "甲\n乙")
        pipe.send_text("\n丙")
        await _wait_until(lambda: tui.buffer.text == "甲\n乙\n丙")
        pipe.send_text("丁\n戊")
        await _wait_until(lambda: tui.buffer.text.endswith("丁\n戊"))
        assert tui._generation_task is None
    finally:
        await _stop_tui(tui, pipe_state, task)


@pytest.mark.asyncio
async def test_enter_submits_exact_chinese_to_provider_and_finishes() -> None:
    application = _application(_completed("回答"))
    provider = application.provider
    tui, pipe_state, task, output = await _start_tui(application)
    _context, pipe = pipe_state  # type: ignore[misc]
    try:
        pipe.send_text("你好\r")
        await _wait_until(lambda: tui._generation_task is None and bool(provider.requests))
        request = provider.requests[0]
        assert any(
            getattr(part, "text", None) == "你好"
            for message in request.messages
            for part in message.parts
        )
        rendered = output.getvalue()
        assert "you" in rendered and "你好" in rendered
        assert "UthCode:" in rendered and "回答" in rendered
    finally:
        await _stop_tui(tui, pipe_state, task)


@pytest.mark.asyncio
async def test_model_picker_escape_restores_draft_and_never_exits() -> None:
    tui, pipe_state, task, _output = await _start_tui()
    _context, pipe = pipe_state  # type: ignore[misc]
    try:
        tui._picker_draft = Document("/model", len("/model"))
        tui.picker.replace(
            (ModelProfile("fake/model", "fake", "model", "Fake"),),
            "fake/model",
        )
        assert tui.picker.open
        pipe.send_text("\x1b")
        await _wait_until(lambda: not tui.picker.open)
        assert tui.buffer.text == "/model"
        assert tui.ui.is_running
    finally:
        await _stop_tui(tui, pipe_state, task)


def test_candidate_window_tracks_selected_visible_item() -> None:
    assert _window_start(0, 15, 8) == 0
    assert _window_start(8, 15, 8) <= 8 < _window_start(8, 15, 8) + 8
    assert _window_start(14, 15, 8) == 7


@pytest.mark.asyncio
async def test_tui_double_escape_pauses_and_resume_keeps_the_turn_alive() -> None:
    provider = _ScriptedProvider(
        ((_completed("回答"),), (_completed("回答"),)),
        delays=(5.0, 0.0),
    )
    application = UthCodeApplication(
        provider,
        runtime_context=ApplicationRuntimeContext.from_system(
            workdir=Path("C:/workspace"),
            platform_name="TestOS",
            platform_release="1.0",
            current_date="2026-08-06",
        ),
    )
    tui, pipe_state, task, _output = await _start_tui(application)
    _context, pipe = pipe_state  # type: ignore[misc]
    try:
        pipe.send_text("hello\r")
        await _wait_until(lambda: tui._active_handle is not None and bool(provider.requests))
        pipe.send_text("\x1b\x1b")
        await _wait_until(
            lambda: tui._active_handle is not None
            and tui._active_handle.pending_pause is not None,
            attempts=500,
        )
        await _wait_until(lambda: tui.activity == "paused")
        assert tui._active_handle is not None
        assert not tui._active_handle.cancelled()
        pipe.send_text("\r")
        await _wait_until(lambda: tui._generation_task is None, attempts=500)
        assert tui._active_handle is None
        assert provider.requests
    finally:
        await _stop_tui(tui, pipe_state, task)


@pytest.mark.asyncio
async def test_tui_pause_resume_and_ask_user_pilot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call = ToolCallPart(
        "ask-1",
        "AskUserQuestion",
        {
            "questions": [
                {
                    "question_id": "q1",
                    "header": "Value",
                    "question": "What value should be used?",
                    "kind": "text",
                }
            ]
        },
    )
    provider = _ScriptedProvider(
        (
            (_completed("discarded before pause"),),
            (_completed("need input", call, finish_reason=FinishReason.TOOL_CALLS),),
            (_completed("已完成"),),
        ),
        delays=(5.0, 0.0, 0.0),
    )
    application = UthCodeApplication(
        provider,
        runtime_context=ApplicationRuntimeContext.from_system(
            workdir=Path("C:/workspace"),
            platform_name="TestOS",
            platform_release="1.0",
            current_date="2026-08-06",
        ),
    )
    started_handles: list[TurnHandle] = []
    original_start_turn = AgentRun.start_turn

    def record_start(run: AgentRun, prompt: str) -> TurnHandle:
        handle = original_start_turn(run, prompt)
        started_handles.append(handle)
        return handle

    monkeypatch.setattr(AgentRun, "start_turn", record_start)
    tui, pipe_state, task, output = await _start_tui(application)
    _context, pipe = pipe_state  # type: ignore[misc]
    try:
        pipe.send_text("hello\r")
        await _wait_until(lambda: tui._active_handle is not None and len(provider.requests) == 1)
        pipe.send_text("\x1b\x1b")
        await _wait_until(
            lambda: tui._active_handle is not None
            and tui._active_handle.pending_pause is not None
            and tui.activity == "paused",
            attempts=500,
        )
        handle = tui._active_handle
        assert handle is not None
        assert len(started_handles) == 1
        assert not handle.cancelled()

        # Resume the same Turn through the public TUI action menu.  The retry
        # reaches a second pause for AskUserQuestion without starting a new Turn.
        pipe.send_text("\r")
        await _wait_until(
            lambda: tui._active_handle is handle
            and tui.interaction.mode is InteractionMode.QUESTIONS
            and handle.pending_pause is not None
            and len(provider.requests) == 2,
            attempts=500,
        )
        pipe.send_text("答案\r")
        await _wait_until(lambda: tui.interaction.mode is InteractionMode.REVIEW)
        pipe.send_text("\r")
        await _wait_until(
            lambda: tui._generation_task is None
            and tui._active_handle is None
            and tui.interaction.mode is InteractionMode.CLOSED,
            attempts=500,
        )

        assert len(started_handles) == 1
        assert len(provider.requests) == 3
        assert "已完成" in output.getvalue()
        assert _latest_tool_message(provider.requests[2]).parts == (
            ToolResultPart("ask-1", '{"answers": {"q1": ["答案"]}}'),
        )
        assert not tui._background_tasks
    finally:
        await _stop_tui(tui, pipe_state, task)


@pytest.mark.asyncio
async def test_tui_pause_cancel_cleans_turn_without_saved_state() -> None:
    provider = _ScriptedProvider(
        ((_completed("不会完成"),), (_completed("不会完成"),)),
        delays=(5.0, 0.0),
    )
    application = UthCodeApplication(
        provider,
        runtime_context=ApplicationRuntimeContext.from_system(
            workdir=Path("C:/workspace"),
            platform_name="TestOS",
            platform_release="1.0",
            current_date="2026-08-06",
        ),
    )
    tui, pipe_state, task, output = await _start_tui(application)
    _context, pipe = pipe_state  # type: ignore[misc]
    try:
        pipe.send_text("hello\r")
        await _wait_until(lambda: tui._active_handle is not None and bool(provider.requests))
        pipe.send_text("\x1b\x1b")
        await _wait_until(
            lambda: tui._active_handle is not None
            and tui._active_handle.pending_pause is not None,
            attempts=500,
        )
        await _wait_until(lambda: tui.activity == "paused")
        tui.interaction.move(1)
        pipe.send_text("\r")
        await _wait_until(lambda: tui._generation_task is None, attempts=500)
        assert tui._active_handle is None
        assert len(provider.requests) == 1
        assert "保存" not in output.getvalue()
        assert not tui._background_tasks
    finally:
        await _stop_tui(tui, pipe_state, task)


@pytest.mark.asyncio
async def test_tui_shutdown_waits_for_active_turn_terminal_and_releases_run() -> None:
    provider = _ScriptedProvider(
        (
            (_completed("cancelled response"),),
            (_completed("after shutdown"),),
        ),
        delays=(5.0, 0.0),
    )
    application = UthCodeApplication(
        provider,
        runtime_context=ApplicationRuntimeContext.from_system(
            workdir=Path("C:/workspace"),
            platform_name="TestOS",
            platform_release="1.0",
            current_date="2026-08-06",
        ),
    )
    tui, pipe_state, task, _output = await _start_tui(application)
    _context, pipe = pipe_state  # type: ignore[misc]
    try:
        pipe.send_text("hello\r")
        await _wait_until(
            lambda: tui._active_handle is not None and bool(provider.requests),
            attempts=500,
        )
        handle = tui._active_handle
        assert handle is not None
        run = tui._run

        await tui.shutdown()

        await _assert_tui_shutdown_cleanup(tui, run, handle)
        next_handle = run.start_turn("after shutdown")
        assert (await next_handle.result()).status is RunStatus.COMPLETED
        await tui.shutdown()
    finally:
        await _stop_tui(tui, pipe_state, task)


@pytest.mark.asyncio
@pytest.mark.parametrize("pause_case", ("user_requested", "ask_user"))
async def test_tui_shutdown_cleans_paused_or_ask_user_turn_and_is_idempotent(
    pause_case: str,
) -> None:
    ask_call = ToolCallPart(
        "ask-shutdown",
        "AskUserQuestion",
        {
            "questions": [
                {
                    "question_id": "q1",
                    "header": "Value",
                    "question": "What value should be used?",
                    "kind": "text",
                }
            ]
        },
    )
    if pause_case == "user_requested":
        provider = _ScriptedProvider(
            ((_completed("paused response"),),),
            delays=(5.0,),
        )
    else:
        provider = _ScriptedProvider(
            ((_completed("need input", ask_call, finish_reason=FinishReason.TOOL_CALLS),),)
        )
    application = UthCodeApplication(
        provider,
        runtime_context=ApplicationRuntimeContext.from_system(
            workdir=Path("C:/workspace"),
            platform_name="TestOS",
            platform_release="1.0",
            current_date="2026-08-06",
        ),
    )
    tui, pipe_state, task, _output = await _start_tui(application)
    _context, pipe = pipe_state  # type: ignore[misc]
    try:
        pipe.send_text("hello\r")
        if pause_case == "user_requested":
            await _wait_until(
                lambda: tui._active_handle is not None and bool(provider.requests),
                attempts=500,
            )
            pipe.send_text("\x1b\x1b")
            await _wait_until(
                lambda: tui._active_handle is not None
                and tui._active_handle.pending_pause is not None
                and tui.activity == "paused",
                attempts=500,
            )
        else:
            await _wait_until(
                lambda: tui.interaction.mode is InteractionMode.QUESTIONS,
                attempts=500,
            )
        handle = tui._active_handle
        assert handle is not None
        assert handle.pending_pause is not None
        run = tui._run

        await tui.shutdown()

        await _assert_tui_shutdown_cleanup(tui, run, handle)
        await tui.shutdown()
    finally:
        await _stop_tui(tui, pipe_state, task)


@pytest.mark.asyncio
async def test_tui_renderer_failure_closes_application_turn_before_dropping_handle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _ScriptedProvider(
        (
            (_completed("cancelled response"),),
            (_completed("next turn"),),
        ),
        delays=(5.0, 0.0),
    )
    application = UthCodeApplication(
        provider,
        runtime_context=ApplicationRuntimeContext.from_system(
            workdir=Path("C:/workspace"),
            platform_name="TestOS",
            platform_release="1.0",
            current_date="2026-08-06",
        ),
    )

    def fail_projection(
        self: AgentEventRenderer,
        event: object,
    ) -> RenderBatch | None:
        del self, event
        raise RuntimeError("projection failed")

    monkeypatch.setattr(AgentEventRenderer, "push", fail_projection)
    tui = UthCodeTUI(application, terminal_output=RecordingOutput())
    tui._start_turn("hello")
    handle = tui._active_handle
    task = tui._generation_task
    assert handle is not None
    assert task is not None
    run = tui._run

    await task

    await _assert_consumer_failure_cleanup(tui, run, handle, task)
    next_handle = run.start_turn("after failure")
    assert (await next_handle.result()).status is RunStatus.COMPLETED
    await tui.shutdown()


@pytest.mark.asyncio
async def test_tui_periodic_flush_failure_closes_stalled_application_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _ScriptedProvider(
        ((_completed("cancelled response"),),),
        delays=(5.0,),
    )
    application = UthCodeApplication(
        provider,
        runtime_context=ApplicationRuntimeContext.from_system(
            workdir=Path("C:/workspace"),
            platform_name="TestOS",
            platform_release="1.0",
            current_date="2026-08-06",
        ),
    )

    def fail_flush(self: AgentEventRenderer) -> RenderBatch:
        del self
        raise RuntimeError("periodic flush failed")

    monkeypatch.setattr(AgentEventRenderer, "flush", fail_flush)
    tui = UthCodeTUI(application, terminal_output=RecordingOutput())
    tui._start_turn("hello")
    handle = tui._active_handle
    task = tui._generation_task
    assert handle is not None
    assert task is not None
    run = tui._run

    await task

    await _assert_consumer_failure_cleanup(tui, run, handle, task)
    await tui.shutdown()


@pytest.mark.asyncio
async def test_tui_secondary_error_display_failure_still_closes_application_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _ScriptedProvider(
        ((_completed("cancelled response"),),),
        delays=(5.0,),
    )
    application = UthCodeApplication(
        provider,
        runtime_context=ApplicationRuntimeContext.from_system(
            workdir=Path("C:/workspace"),
            platform_name="TestOS",
            platform_release="1.0",
            current_date="2026-08-06",
        ),
    )

    def fail_projection(
        self: AgentEventRenderer,
        event: object,
    ) -> RenderBatch | None:
        del self, event
        raise RuntimeError("projection failed")

    async def fail_error_display(text: str) -> None:
        del text
        raise RuntimeError("error display failed")

    monkeypatch.setattr(AgentEventRenderer, "push", fail_projection)
    tui = UthCodeTUI(application, terminal_output=RecordingOutput())
    monkeypatch.setattr(tui, "_show_error", fail_error_display)
    tui._start_turn("hello")
    handle = tui._active_handle
    task = tui._generation_task
    assert handle is not None
    assert task is not None
    run = tui._run

    await task

    await _assert_consumer_failure_cleanup(tui, run, handle, task)
    await tui.shutdown()
    await tui.shutdown()


@pytest.mark.asyncio
async def test_tui_ask_user_projection_failure_clears_pending_waiter_and_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ask_call = ToolCallPart(
        "ask-consumer-failure",
        "AskUserQuestion",
        {
            "questions": [
                {
                    "question_id": "q1",
                    "header": "Value",
                    "question": "What value should be used?",
                    "kind": "text",
                }
            ]
        },
    )
    provider = _ScriptedProvider(
        ((_completed("need input", ask_call, finish_reason=FinishReason.TOOL_CALLS),),)
    )
    application = UthCodeApplication(
        provider,
        runtime_context=ApplicationRuntimeContext.from_system(
            workdir=Path("C:/workspace"),
            platform_name="TestOS",
            platform_release="1.0",
            current_date="2026-08-06",
        ),
    )

    def fail_open_pause(
        self: TuiInteractionState,
        pause: PauseRequest,
    ) -> None:
        del self, pause
        raise RuntimeError("interaction projection failed")

    monkeypatch.setattr(TuiInteractionState, "open_pause", fail_open_pause)
    tui = UthCodeTUI(application, terminal_output=RecordingOutput())
    tui._start_turn("hello")
    handle = tui._active_handle
    task = tui._generation_task
    assert handle is not None
    assert task is not None
    run = tui._run

    await task

    await _assert_consumer_failure_cleanup(tui, run, handle, task)
    await tui.shutdown()


@pytest.mark.asyncio
async def test_tui_pause_question_panel_submits_through_application_turn() -> None:
    call = ToolCallPart(
        "ask-1",
        "AskUserQuestion",
        {
            "questions": [
                {
                    "question_id": "q1",
                    "header": "Value",
                    "question": "What value should be used?",
                    "kind": "text",
                }
            ]
        },
    )
    provider = _ScriptedProvider(
        (
            (_completed("need input", call, finish_reason=FinishReason.TOOL_CALLS),),
            (_completed("已完成"),),
        )
    )
    application = UthCodeApplication(
        provider,
        runtime_context=ApplicationRuntimeContext.from_system(
            workdir=Path("C:/workspace"),
            platform_name="TestOS",
            platform_release="1.0",
            current_date="2026-08-06",
        ),
    )
    tui, pipe_state, task, output = await _start_tui(application)
    _context, pipe = pipe_state  # type: ignore[misc]
    try:
        pipe.send_text("hello\r")
        await _wait_until(
            lambda: tui._active_handle is not None
            and tui._active_handle.pending_pause is not None
        )
        await _wait_until(lambda: tui.activity == "paused")
        pipe.send_text("答案\r")
        await _wait_until(lambda: tui.interaction.is_review)
        pipe.send_text("\r")
        await _wait_until(lambda: tui._generation_task is None)
        assert "已完成" in output.getvalue()
        assert len(provider.requests) == 2
        assert any(
            "答案" in getattr(part, "content", "")
            for part in _latest_tool_message(provider.requests[1]).parts
        )
    finally:
        await _stop_tui(tui, pipe_state, task)


@pytest.mark.asyncio
async def test_real_tui_single_other_escape_enter_returns_to_ordinary_option(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call = ToolCallPart(
        "ask-other",
        "AskUserQuestion",
        {
            "questions": [
                {
                    "question_id": "mode",
                    "header": "Mode",
                    "question": "Choose a mode.",
                    "kind": "single_select",
                    "options": [
                        {"label": "fast", "description": "Fast"},
                        {"label": "safe", "description": "Safe"},
                    ],
                    "allow_other": True,
                }
            ]
        },
    )
    provider = _ScriptedProvider(
        (
            (_completed("need mode", call, finish_reason=FinishReason.TOOL_CALLS),),
            (_completed("done"),),
        )
    )
    application = UthCodeApplication(
        provider,
        runtime_context=ApplicationRuntimeContext.from_system(
            workdir=Path("C:/workspace"),
            platform_name="TestOS",
            platform_release="1.0",
            current_date="2026-08-06",
        ),
    )
    started_handles: list[TurnHandle] = []
    resume_calls: list[object] = []
    original_start_turn = AgentRun.start_turn
    original_resume = TurnHandle.resume

    def record_start(run: AgentRun, prompt: str) -> TurnHandle:
        handle = original_start_turn(run, prompt)
        started_handles.append(handle)
        return handle

    def record_resume(handle: TurnHandle, response: object) -> bool:
        resume_calls.append(response)
        return original_resume(handle, response)  # type: ignore[arg-type]

    monkeypatch.setattr(AgentRun, "start_turn", record_start)
    monkeypatch.setattr(TurnHandle, "resume", record_resume)
    tui, pipe_state, task, _output = await _start_tui(application)
    _context, pipe = pipe_state  # type: ignore[misc]
    try:
        pipe.send_text("hello\r")
        await _wait_until(
            lambda: tui.interaction.mode is InteractionMode.QUESTIONS,
            attempts=500,
        )
        question = tui.interaction.current_question
        assert question is not None
        tui.interaction.move(len(question.options))
        assert tui.interaction.option_index == len(question.options)
        assert tui.interaction.toggle_option() is True
        assert tui.interaction.other_mode is True
        pipe.send_text("custom-owner")
        await _wait_until(lambda: tui.buffer.text == "custom-owner")

        pipe.send_text("\x1b[27u")
        await _wait_until(
            lambda: not tui.interaction.other_mode
            and tui.buffer.text == ""
            and 0 <= tui.interaction.option_index < len(question.options),
            attempts=500,
        )
        assert tui.interaction.draft == ""
        assert tui.interaction.selected_options == set()
        assert resume_calls == []

        pipe.send_text("\r")
        await _wait_until(lambda: tui.interaction.mode is InteractionMode.REVIEW)
        assert tui.interaction.answers["mode"] == ["fast"]
        assert resume_calls == []

        pipe.send_text("\r")
        await _wait_until(
            lambda: tui._generation_task is None
            and tui._active_handle is None
            and tui.interaction.mode is InteractionMode.CLOSED
            and not tui._background_tasks,
            attempts=500,
        )
        assert len(started_handles) == 1
        assert len(provider.requests) == 2
        assert len(resume_calls) == 1
        response = resume_calls[0]
        assert type(response).__name__ == "UserInputResponse"
        assert response.answers["mode"] == ["fast"]  # type: ignore[union-attr]
        assert _latest_tool_message(provider.requests[1]).parts == (
            ToolResultPart("ask-other", '{"answers": {"mode": ["fast"]}}'),
        )
        assert "custom-owner" not in _latest_tool_message(provider.requests[1]).parts[0].content
    finally:
        await _stop_tui(tui, pipe_state, task)


@pytest.mark.asyncio
async def test_real_tui_question_back_restores_buffer_and_draft_without_resuming(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call = ToolCallPart(
        "ask-text",
        "AskUserQuestion",
        {
            "questions": [
                {
                    "question_id": "q1",
                    "header": "First",
                    "question": "First answer?",
                    "kind": "text",
                },
                {
                    "question_id": "q2",
                    "header": "Second",
                    "question": "Second answer?",
                    "kind": "text",
                },
            ]
        },
    )
    provider = _ScriptedProvider(
        (
            (_completed("need answers", call, finish_reason=FinishReason.TOOL_CALLS),),
            (_completed("answers accepted"),),
        )
    )
    application = UthCodeApplication(
        provider,
        runtime_context=ApplicationRuntimeContext.from_system(
            workdir=Path("C:/workspace"),
            platform_name="TestOS",
            platform_release="1.0",
            current_date="2026-08-06",
        ),
    )
    resume_calls: list[object] = []
    original_resume = TurnHandle.resume

    def record_resume(handle: TurnHandle, response: object) -> bool:
        resume_calls.append(response)
        return original_resume(handle, response)  # type: ignore[arg-type]

    monkeypatch.setattr(TurnHandle, "resume", record_resume)
    tui, pipe_state, task, _output = await _start_tui(application)
    _context, pipe = pipe_state  # type: ignore[misc]
    try:
        pipe.send_text("hello\r")
        await _wait_until(lambda: tui.interaction.mode is InteractionMode.QUESTIONS)
        pipe.send_text("answer-one\r")
        await _wait_until(lambda: tui.interaction.question_index == 1)
        pipe.send_text("answer-two\r")
        await _wait_until(lambda: tui.interaction.is_review)
        assert provider.requests and len(provider.requests) == 1

        await asyncio.sleep(0.05)
        pipe.send_text("\x1b[27u")
        await _wait_until(
            lambda: tui.interaction.mode is InteractionMode.QUESTIONS
            and tui.interaction.current_question is not None
            and tui.interaction.current_question.question_id == "q2"
            and tui.buffer.text == "answer-two"
        )
        assert tui.buffer.cursor_position == len("answer-two")
        assert tui.interaction.draft == "answer-two"
        assert tui.interaction.answers["q2"] == ["answer-two"]
        assert resume_calls == []

        pipe.send_text("\r")
        await _wait_until(lambda: tui.interaction.is_review)
        assert tui.interaction.answers["q2"] == ["answer-two"]
        assert len(provider.requests) == 1
        assert resume_calls == []

        await asyncio.sleep(0.05)
        pipe.send_text("\x1b[27u")
        await _wait_until(lambda: tui.buffer.text == "answer-two")
        tui.buffer.set_document(
            Document("answer-new", len("answer-new")),
            bypass_readonly=True,
        )
        pipe.send_text("\r")
        await _wait_until(lambda: tui.interaction.is_review)
        assert tui.interaction.answers["q2"] == ["answer-new"]
        assert len(provider.requests) == 1
        assert resume_calls == []

        pipe.send_text("\r")
        await _wait_until(
            lambda: tui._generation_task is None
            and tui._active_handle is None
            and not tui._background_tasks
        )
        assert len(provider.requests) == 2
        assert len(resume_calls) == 1
        assert type(resume_calls[0]).__name__ == "UserInputResponse"
    finally:
        await _stop_tui(tui, pipe_state, task)


@pytest.mark.asyncio
async def test_real_tui_question_back_restores_other_and_selection_state() -> None:
    call = ToolCallPart(
        "ask-options",
        "AskUserQuestion",
        {
            "questions": [
                {
                    "question_id": "text",
                    "header": "Text",
                    "question": "Describe it.",
                    "kind": "text",
                },
                {
                    "question_id": "single",
                    "header": "Mode",
                    "question": "Choose one.",
                    "kind": "single_select",
                    "options": [
                        {"label": "fast", "description": "Fast"},
                        {"label": "safe", "description": "Safe"},
                    ],
                },
                {
                    "question_id": "multi",
                    "header": "Targets",
                    "question": "Choose many.",
                    "kind": "multi_select",
                    "options": [
                        {"label": "api", "description": "API"},
                        {"label": "ui", "description": "UI"},
                    ],
                },
                {
                    "question_id": "other",
                    "header": "Owner",
                    "question": "Who owns it?",
                    "kind": "single_select",
                    "options": [
                        {"label": "team", "description": "The team"},
                        {"label": "me", "description": "The user"},
                    ],
                    "allow_other": True,
                },
            ]
        },
    )
    provider = _ScriptedProvider(
        ((_completed("need options", call, finish_reason=FinishReason.TOOL_CALLS),),)
    )
    application = UthCodeApplication(
        provider,
        runtime_context=ApplicationRuntimeContext.from_system(
            workdir=Path("C:/workspace"),
            platform_name="TestOS",
            platform_release="1.0",
            current_date="2026-08-06",
        ),
    )
    tui, pipe_state, task, _output = await _start_tui(application)
    _context, pipe = pipe_state  # type: ignore[misc]
    try:
        pipe.send_text("hello\r")
        await _wait_until(lambda: tui.interaction.mode is InteractionMode.QUESTIONS)
        pipe.send_text("description\r")
        await _wait_until(
            lambda: tui.interaction.current_question is not None
            and tui.interaction.current_question.question_id == "single"
        )

        tui.interaction.move(1)
        tui.interaction.toggle_option()
        pipe.send_text("\r")
        await _wait_until(
            lambda: tui.interaction.current_question is not None
            and tui.interaction.current_question.question_id == "multi"
        )
        tui.interaction.toggle_option()
        tui.interaction.move(1)
        tui.interaction.toggle_option()
        pipe.send_text("\r")
        await _wait_until(
            lambda: tui.interaction.current_question is not None
            and tui.interaction.current_question.question_id == "other"
        )

        tui.interaction.move(2)
        tui.interaction.toggle_option()
        pipe.send_text("custom-owner\r")
        await _wait_until(lambda: tui.interaction.is_review)

        await asyncio.sleep(0.05)
        pipe.send_text("\x1b[27u")
        await _wait_until(
            lambda: tui.interaction.current_question is not None
            and tui.interaction.current_question.question_id == "other"
            and tui.interaction.other_mode
            and tui.buffer.text == "custom-owner"
        )
        assert tui.buffer.cursor_position == len("custom-owner")

        pipe.send_text("\x1b[D")
        await _wait_until(
            lambda: tui.interaction.current_question is not None
            and tui.interaction.current_question.question_id == "multi"
        )
        assert tui.interaction.selected_options == {0, 1}
        assert tui.buffer.text == ""

        pipe.send_text("\x1b[D")
        await _wait_until(
            lambda: tui.interaction.current_question is not None
            and tui.interaction.current_question.question_id == "single"
        )
        assert tui.interaction.selected_options == {1}
        assert tui.buffer.text == ""
        assert len(provider.requests) == 1
    finally:
        await _stop_tui(tui, pipe_state, task)


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [NetworkError("network"), RateLimitError("rate")])
async def test_tui_provider_retry_pilot_uses_one_turn_and_cleans_up(
    error: NetworkError | RateLimitError,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _ProviderFailureThenSuccess(error, (_completed("retry succeeded"),))
    application = UthCodeApplication(
        provider,
        runtime_context=ApplicationRuntimeContext.from_system(
            workdir=Path("C:/workspace"),
            platform_name="TestOS",
            platform_release="1.0",
            current_date="2026-08-06",
        ),
    )
    started_prompts: list[str] = []
    original_start_turn = AgentRun.start_turn
    resume_calls: list[object] = []

    def record_start(run: AgentRun, prompt: str):  # type: ignore[no-untyped-def]
        started_prompts.append(prompt)
        return original_start_turn(run, prompt)

    original_resume = TurnHandle.resume

    def record_resume(handle: TurnHandle, response: object) -> bool:
        resume_calls.append(response)
        return original_resume(handle, response)  # type: ignore[arg-type]

    monkeypatch.setattr(AgentRun, "start_turn", record_start)
    monkeypatch.setattr(TurnHandle, "resume", record_resume)
    tui, pipe_state, task, output = await _start_tui(application)
    _context, pipe = pipe_state  # type: ignore[misc]
    try:
        pipe.send_text("hello\r")
        await _wait_until(
            lambda: tui.interaction.mode is InteractionMode.PAUSE_ACTION
            and len(provider.requests) == 1
        )
        pipe.send_text("\r")
        await _wait_until(
            lambda: tui._generation_task is None
            and tui._active_handle is None
            and tui.interaction.mode is InteractionMode.CLOSED
            and not tui._background_tasks
        )
        assert len(started_prompts) == 1
        assert len(provider.requests) == 2
        assert len(resume_calls) == 1
        assert isinstance(resume_calls[0], RetryProviderResponse)
        assert "retry succeeded" in output.getvalue()
    finally:
        await _stop_tui(tui, pipe_state, task)


@pytest.mark.asyncio
async def test_tui_provider_cancel_pilot_stops_retry_and_cleans_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _ProviderFailureThenSuccess(
        NetworkError("network"),
        (_completed("must not run"),),
    )
    application = UthCodeApplication(
        provider,
        runtime_context=ApplicationRuntimeContext.from_system(
            workdir=Path("C:/workspace"),
            platform_name="TestOS",
            platform_release="1.0",
            current_date="2026-08-06",
        ),
    )
    started_prompts: list[str] = []
    original_start_turn = AgentRun.start_turn
    resume_calls: list[object] = []
    cancel_calls = 0

    def record_start(run: AgentRun, prompt: str):  # type: ignore[no-untyped-def]
        started_prompts.append(prompt)
        return original_start_turn(run, prompt)

    original_resume = TurnHandle.resume
    original_cancel = TurnHandle.cancel

    def record_resume(handle: TurnHandle, response: object) -> bool:
        resume_calls.append(response)
        return original_resume(handle, response)  # type: ignore[arg-type]

    def record_cancel(handle: TurnHandle) -> bool:
        nonlocal cancel_calls
        cancel_calls += 1
        return original_cancel(handle)

    monkeypatch.setattr(AgentRun, "start_turn", record_start)
    monkeypatch.setattr(TurnHandle, "resume", record_resume)
    monkeypatch.setattr(TurnHandle, "cancel", record_cancel)
    tui, pipe_state, task, output = await _start_tui(application)
    _context, pipe = pipe_state  # type: ignore[misc]
    try:
        pipe.send_text("hello\r")
        await _wait_until(
            lambda: tui.interaction.mode is InteractionMode.PAUSE_ACTION
            and len(provider.requests) == 1
        )
        tui.interaction.move(1)
        pipe.send_text("\r")
        await _wait_until(
            lambda: tui._generation_task is None
            and tui._active_handle is None
            and tui.interaction.mode is InteractionMode.CLOSED
            and not tui._background_tasks
        )
        assert len(started_prompts) == 1
        assert len(provider.requests) == 1
        assert resume_calls == []
        assert cancel_calls == 1
        assert "保存" not in output.getvalue()
        assert "retry succeeded" not in output.getvalue()
    finally:
        await _stop_tui(tui, pipe_state, task)


def test_transient_height_budget_fits_small_terminal() -> None:
    tui = UthCodeTUI(_application(), terminal_output=RecordingOutput())
    tui._terminal_size = lambda: (40, 5)  # type: ignore[method-assign]
    tui.picker.replace(
        (ModelProfile("fake/model", "fake", "model", "Fake"),),
        "fake/model",
    )
    assert (
        tui._candidate_height()
        + tui._composer_height()
        + tui._preview_height()
        + 1
        <= 5
    )
    tui._streams.append(_StreamProjection(
        MarkdownStream(pending="still generating"),
        "assistant",
        block_id="pending",
    ))
    tui._terminal_size = lambda: (40, 3)  # type: ignore[method-assign]
    assert tui._preview_height() == 0
    assert not tui._has_preview()


@pytest.mark.asyncio
async def test_stalled_stream_delta_reaches_temporary_preview(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _ScriptedProvider(
        ((_completed("done"),),),
        delays=(0.2,),
    )
    application = UthCodeApplication(
        provider,
        runtime_context=ApplicationRuntimeContext.from_system(
            workdir=Path("C:/workspace"),
            platform_name="TestOS",
            platform_release="1.0",
            current_date="2026-08-06",
        ),
    )
    original_flush = AgentEventRenderer.flush
    sent = False

    def flush_with_partial(renderer: AgentEventRenderer) -> RenderBatch:
        nonlocal sent
        if not sent:
            sent = True
            return RenderBatch(
                text=(TextUpdate("assistant", "assistant", "partial"),)
            )
        return original_flush(renderer)

    monkeypatch.setattr(AgentEventRenderer, "flush", flush_with_partial)
    tui = UthCodeTUI(application, terminal_output=RecordingOutput())
    tui._start_turn("hello")
    task = tui._generation_task
    assert task is not None

    await _wait_until(lambda: tui._pending_text() == "partial")
    await tui.shutdown()
    await task


@pytest.mark.asyncio
async def test_interaction_error_is_visible_and_input_can_continue() -> None:
    output = RecordingOutput()
    tui = UthCodeTUI(_application(), terminal_output=output)

    async def fail() -> None:
        raise ValueError("bad input")

    tui._spawn(fail())
    await _wait_until(lambda: not tui._background_tasks)
    assert "界面操作失败；可以继续输入" in output.getvalue()
    assert not tui._closing


@pytest.mark.asyncio
async def test_clear_keeps_scrollback_and_run_but_resets_projection() -> None:
    output = RecordingOutput()
    tui = UthCodeTUI(_application(), terminal_output=output)
    run = tui._run
    tui._streams.append(_StreamProjection(
        MarkdownStream(pending="preview"),
        "assistant",
        block_id="x",
    ))
    await tui._clear_viewport()
    assert tui._run is run
    assert not tui._streams
    assert CLEAR_VIEWPORT in output.getvalue()
    assert "\x1b[3J" not in output.getvalue()
    assert "上方终端历史仍保留" in output.getvalue()


@pytest.mark.asyncio
async def test_each_turn_discards_previous_transient_stream_projection() -> None:
    tui = UthCodeTUI(_application(), terminal_output=RecordingOutput())
    tui._streams.append(_StreamProjection(
        MarkdownStream(pending="stale preview"),
        "assistant",
        block_id="old-turn",
        started=True,
        open=True,
    ))

    tui._start_turn("new turn")
    assert all(projection.block_id != "old-turn" for projection in tui._streams)
    assert tui._generation_task is not None
    await tui._generation_task


@pytest.mark.asyncio
async def test_authoritative_correction_appends_without_rewriting() -> None:
    output = RecordingOutput()
    tui = UthCodeTUI(_application(), terminal_output=output)
    await tui._apply_batch(
        RenderBatch(
            text=(TextUpdate("m:assistant", "assistant", "partial\n\n"),),
        )
    )
    await tui._flush_streams()
    await tui._apply_batch(
        RenderBatch(
            text=(
                TextUpdate(
                    "m:assistant",
                    "assistant",
                    "authoritative",
                    mode="replace",
                ),
            ),
        )
    )
    rendered = output.getvalue()
    assert "partial" in rendered
    assert "响应已修正" in rendered
    assert "authoritative" in rendered


@pytest.mark.asyncio
async def test_final_answer_renders_once_instead_of_one_role_block_per_paragraph() -> None:
    output = RecordingOutput()
    tui = UthCodeTUI(_application(), terminal_output=output)
    await tui._apply_batch(
        RenderBatch(
            text=(
                TextUpdate(
                    "m:assistant",
                    "assistant",
                    "第一段。\n\n第二段。\n\n- 项目一\n- 项目二\n",
                ),
            )
        )
    )
    partial = output.getvalue()
    assert partial.count("UthCode:") == 0
    assert "第一段" not in partial
    await tui._apply_batch(
        RenderBatch(
            terminal="completed",
            final_text="第一段。\n\n第二段。\n\n- 项目一\n- 项目二\n",
        )
    )
    rendered = output.getvalue()
    assert rendered.count("UthCode:") == 1
    assert "第一段" in rendered and "第二段" in rendered and "项目二" in rendered


@pytest.mark.asyncio
async def test_running_tool_is_transient_and_terminal_tool_commits_once() -> None:
    output = RecordingOutput()
    tui = UthCodeTUI(_application(), terminal_output=output)
    running = RenderBatch(
        tools=(ToolUpdate("t", "Bash", "dir", "running"),),
    )
    await tui._apply_batch(running)
    assert tui.activity == "running Bash: dir"
    assert "running Bash" not in output.getvalue()
    finished = RenderBatch(
        tools=(ToolUpdate("t", "Bash", "dir", "finished"),),
    )
    await tui._apply_batch(finished)
    assert output.getvalue().count("finished") == 1


def test_source_and_dependencies_have_no_textual_blessed_or_removed_assets() -> None:
    root = Path(__file__).parents[1]
    tui_root = root / "src/uthcode/interfaces/tui"
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in tui_root.glob("*.py")
    )
    assert "textual" not in source.casefold()
    assert "blessed" not in source.casefold()
    assert not (tui_root / "tui.tcss").exists()
    assert not (tui_root / "widgets.py").exists()
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    assert "textual" not in pyproject.casefold()
    assert "blessed" not in pyproject.casefold()
    assert "prompt_toolkit>=3.0.52,<4" in pyproject
