"""Interface-local pause menus and structured question drafts.

The Application owns the real pending pause.  This module only owns the
temporary focus, selection and answer draft needed to turn visible input into
one public ``TurnHandle.resume`` call.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from uthcode.application import (
    PauseKind,
    PauseRequest,
    PlanReviewChoice,
    PlanReviewResponse,
    PermissionApprovalChoice,
    PermissionApprovalResponse,
    RetryProviderResponse,
    ResumeTurnResponse,
    UserInputResponse,
    UserQuestion,
    pause_message,
)


class InteractionMode(str, Enum):
    CLOSED = "closed"
    PAUSE_ACTION = "pause_action"
    PERMISSION = "permission"
    QUESTIONS = "questions"
    REVIEW = "review"
    PLAN_REVIEW = "plan_review"
    PLAN_REVISION = "plan_revision"


class PauseAction(str, Enum):
    RESUME = "resume"
    RETRY = "retry"
    CANCEL = "cancel"


class PlanReviewAction(str, Enum):
    APPROVE = "approve"
    REVISE = "revise"
    CANCEL = "cancel"


@dataclass(slots=True)
class TuiInteractionState:
    """Short-lived input state for one visible pause request."""

    mode: InteractionMode = InteractionMode.CLOSED
    pause: PauseRequest | None = None
    question_index: int = 0
    action_index: int = 0
    option_index: int = 0
    selected_options: set[int] = field(default_factory=set)
    answers: dict[str, list[str]] = field(default_factory=dict)
    draft: str = ""
    free_text_mode: bool = False

    @property
    def open(self) -> bool:
        return self.mode is not InteractionMode.CLOSED

    @property
    def current_question(self) -> UserQuestion | None:
        request = self.pause.user_input_request if self.pause is not None else None
        if request is None or self.question_index >= len(request.questions):
            return None
        return request.questions[self.question_index]

    @property
    def current_options(self) -> tuple[str, ...]:
        question = self.current_question
        if question is None:
            return ()
        return tuple(option.label for option in question.options)

    @property
    def actions(self) -> tuple[PauseAction, ...]:
        if self.pause is None:
            return ()
        if self.pause.kind is PauseKind.PROVIDER_UNAVAILABLE:
            return (PauseAction.RETRY, PauseAction.CANCEL)
        if self.pause.kind is PauseKind.USER_REQUESTED:
            return (PauseAction.RESUME, PauseAction.CANCEL)
        return ()

    @property
    def plan_review_actions(self) -> tuple[PlanReviewAction, ...]:
        if self.pause is None or self.pause.kind is not PauseKind.PLAN_REVIEW_REQUIRED:
            return ()
        return (
            PlanReviewAction.APPROVE,
            PlanReviewAction.REVISE,
            PlanReviewAction.CANCEL,
        )

    @property
    def selected_plan_review_action(self) -> PlanReviewAction | None:
        actions = self.plan_review_actions
        if not actions:
            return None
        return actions[self.action_index % len(actions)]

    @property
    def permission_choices(self) -> tuple[PermissionApprovalChoice, ...]:
        request = self.pause.permission_request if self.pause is not None else None
        return request.choices if request is not None else ()

    @property
    def selected_permission_choice(self) -> PermissionApprovalChoice | None:
        choices = self.permission_choices
        if not choices:
            return None
        return choices[self.action_index % len(choices)]

    @property
    def selected_action(self) -> PauseAction | None:
        actions = self.actions
        if not actions:
            return None
        return actions[self.action_index % len(actions)]

    @property
    def selected_option(self) -> str | None:
        question = self.current_question
        if question is None:
            return None
        if self.option_index >= len(question.options):
            return "自行输入"
        return question.options[self.option_index].label

    @property
    def is_select(self) -> bool:
        question = self.current_question
        return question is not None and question.kind.value != "text"

    @property
    def is_review(self) -> bool:
        return self.mode is InteractionMode.REVIEW

    @property
    def is_permission(self) -> bool:
        return self.mode is InteractionMode.PERMISSION

    def open_pause(self, pause: PauseRequest) -> None:
        self._reset(pause)
        self.mode = (
            InteractionMode.PLAN_REVIEW
            if pause.kind is PauseKind.PLAN_REVIEW_REQUIRED
            else (
                InteractionMode.QUESTIONS
                if pause.kind is PauseKind.USER_INPUT_REQUIRED
                else (
                    InteractionMode.PERMISSION
                    if pause.kind is PauseKind.PERMISSION_REQUIRED
                    else InteractionMode.PAUSE_ACTION
                )
            )
        )

    def close(self) -> None:
        self._reset(None)

    def move(self, delta: int) -> None:
        if self.mode is InteractionMode.PLAN_REVIEW:
            actions = self.plan_review_actions
            if actions:
                self.action_index = (self.action_index + delta) % len(actions)
            return
        if self.mode is InteractionMode.PAUSE_ACTION:
            actions = self.actions
            if actions:
                self.action_index = (self.action_index + delta) % len(actions)
            return
        if self.mode is InteractionMode.PERMISSION:
            choices = self.permission_choices
            if choices:
                self.action_index = (self.action_index + delta) % len(choices)
            return
        if self.mode is not InteractionMode.QUESTIONS or not self.is_select:
            return
        question = self.current_question
        if question is not None:
            count = len(question.options) + 1
            if count:
                self.option_index = (self.option_index + delta) % count

    def toggle_option(self) -> bool:
        if self.mode is not InteractionMode.QUESTIONS or not self.is_select:
            return False
        question = self.current_question
        if question is None or self.free_text_mode:
            return False
        if self.option_index >= len(question.options):
            return self.choose_free_text()
        if question.kind.value == "single_select":
            self.selected_options = {self.option_index}
        elif self.option_index in self.selected_options:
            self.selected_options.remove(self.option_index)
        else:
            self.selected_options.add(self.option_index)
        return True

    def choose_free_text(self) -> bool:
        question = self.current_question
        if question is None or not self.is_select:
            return False
        self.free_text_mode = True
        self.draft = ""
        return True

    def exit_free_text(self) -> bool:
        """Leave free-text input and restore an option focus."""

        if not self.free_text_mode:
            return False
        question = self.current_question
        self.free_text_mode = False
        self.draft = ""
        if question is None:
            self.selected_options.clear()
            self.option_index = 0
            return True

        valid_selected = {
            index
            for index in self.selected_options
            if 0 <= index < len(question.options)
        }
        if question.kind.value == "single_select" and valid_selected:
            valid_selected = {min(valid_selected)}
        self.selected_options = valid_selected
        self.option_index = min(valid_selected, default=0)
        return True

    def set_draft(self, value: str) -> None:
        self.draft = value

    def submit_current(self) -> bool:
        """Commit the current question and advance to review or the next one."""

        if self.mode is not InteractionMode.QUESTIONS:
            return False
        question = self.current_question
        if question is None:
            return False
        values = self._current_answer_values()
        if not values:
            return False
        self.answers[question.question_id] = values
        if self.question_index + 1 >= len(self.pause.user_input_request.questions):  # type: ignore[union-attr]
            self.mode = InteractionMode.REVIEW
        else:
            self.question_index += 1
            self._reset_question_draft()
        return True

    def previous_question(self) -> bool:
        if self.mode is InteractionMode.REVIEW:
            request = self.pause.user_input_request if self.pause is not None else None
            if request is None:
                return False
            self.question_index = len(request.questions) - 1
            self.mode = InteractionMode.QUESTIONS
            self._load_answer_draft()
            return True
        if self.mode is not InteractionMode.QUESTIONS or self.question_index <= 0:
            return False
        self.question_index -= 1
        self._load_answer_draft()
        return True

    def confirm_action(self) -> PauseAction | None:
        if self.mode is not InteractionMode.PAUSE_ACTION:
            return None
        return self.selected_action

    def permission_response(self) -> PermissionApprovalResponse | None:
        choice = self.selected_permission_choice
        pause = self.pause
        request = pause.permission_request if pause is not None else None
        if pause is None or request is None or choice is None:
            return None
        return PermissionApprovalResponse(
            pause_id=pause.pause_id,
            run_id=pause.run_id,
            turn_id=pause.turn_id,
            permission_id=request.permission_id,
            choice=choice,
        )

    def begin_plan_revision(self) -> bool:
        if (
            self.mode is not InteractionMode.PLAN_REVIEW
            or self.selected_plan_review_action is not PlanReviewAction.REVISE
        ):
            return False
        self.mode = InteractionMode.PLAN_REVISION
        self.draft = ""
        return True

    def plan_review_response(self) -> PlanReviewResponse | None:
        pause = self.pause
        request = pause.plan_review_request if pause is not None else None
        if pause is None or request is None:
            return None
        if self.mode is InteractionMode.PLAN_REVIEW:
            if self.selected_plan_review_action is not PlanReviewAction.APPROVE:
                return None
            return PlanReviewResponse(
                pause.pause_id,
                pause.run_id,
                pause.turn_id,
                request.revision,
                PlanReviewChoice.APPROVE,
            )
        if self.mode is InteractionMode.PLAN_REVISION:
            feedback = self.draft.strip()
            if not feedback:
                return None
            return PlanReviewResponse(
                pause.pause_id,
                pause.run_id,
                pause.turn_id,
                request.revision,
                PlanReviewChoice.REVISE,
                feedback,
            )
        return None

    def response_for_action(self):  # type: ignore[no-untyped-def]
        action = self.confirm_action()
        pause = self.pause
        if action is None or pause is None or action is PauseAction.CANCEL:
            return None
        if action is PauseAction.RETRY:
            return RetryProviderResponse(pause.pause_id, pause.run_id, pause.turn_id)
        return ResumeTurnResponse(pause.pause_id, pause.run_id, pause.turn_id)

    def user_input_response(self) -> UserInputResponse | None:
        pause = self.pause
        request = pause.user_input_request if pause is not None else None
        if pause is None or request is None or self.mode is not InteractionMode.REVIEW:
            return None
        return UserInputResponse(
            pause.pause_id,
            pause.run_id,
            pause.turn_id,
            pause.tool_call_id or "",
            {question_id: tuple(values) for question_id, values in self.answers.items()},
        )

    def render_lines(self) -> tuple[tuple[str, str], ...]:
        pause = self.pause
        if not self.open or pause is None:
            return ()
        if self.mode is InteractionMode.PLAN_REVIEW:
            request = pause.plan_review_request
            if request is None:
                return ()
            lines: list[tuple[str, str]] = [
                ("class:interaction.plan.title", f"Review Plan v{request.revision}\n"),
                (
                    "class:interaction.hint",
                    "↑/↓ 选择 · Enter 确认 · Esc 暂时关闭\n",
                ),
            ]
            labels = {
                PlanReviewAction.APPROVE: "Approve and execute",
                PlanReviewAction.REVISE: "Revise plan",
                PlanReviewAction.CANCEL: "Cancel",
            }
            for index, action in enumerate(self.plan_review_actions):
                marker = "›" if index == self.action_index else " "
                lines.append(
                    (
                        "class:interaction.option",
                        f"{marker} {labels[action]}\n",
                    )
                )
            return tuple(lines)
        if self.mode is InteractionMode.PLAN_REVISION:
            request = pause.plan_review_request
            if request is None:
                return ()
            return (
                (
                    "class:interaction.plan.title",
                    f"Revise Plan v{request.revision}\n",
                ),
                (
                    "class:interaction.hint",
                    "输入修改点后按 Enter · Esc 返回 Review\n",
                ),
            )
        if self.mode is InteractionMode.PAUSE_ACTION:
            lines: list[tuple[str, str]] = [
                ("class:interaction.title", "已暂停：选择下一步\n"),
                (
                    "class:interaction.question",
                    f"{pause_message(pause.reason)}\n",
                ),
                ("class:interaction.hint", "↑/↓ 选择 · Enter 确认 · Esc 返回\n"),
            ]
            for index, action in enumerate(self.actions):
                marker = "›" if index == self.action_index else " "
                lines.append(("class:interaction.option", f"{marker} {action.value}\n"))
            return tuple(lines)
        if self.mode is InteractionMode.PERMISSION:
            request = pause.permission_request
            if request is None:
                return ()
            lines = [
                ("class:interaction.title", "需要权限确认\n"),
                (
                    "class:interaction.question",
                    f"{request.tool} · {request.action} · {request.effect.value}\n",
                ),
                (
                    "class:interaction.question",
                    f"resource: {request.resource or '<unknown>'}\n",
                ),
                (
                    "class:interaction.question",
                    f"reason: {request.reason} · mode: {request.mode.value}"
                    + (" · Guard" if request.guard else " · ordinary")
                    + "\n",
                ),
                ("class:interaction.hint", "↑/↓ 选择 · Enter 确认 · Esc 返回\n"),
            ]
            labels = {
                PermissionApprovalChoice.ONCE: "Allow once",
                PermissionApprovalChoice.SESSION: "Allow for session",
                PermissionApprovalChoice.REJECT: "Reject",
            }
            for index, choice in enumerate(request.choices):
                marker = "›" if index == self.action_index else " "
                lines.append(
                    (
                        "class:interaction.option",
                        f"{marker} {labels[choice]}\n",
                    )
                )
            return tuple(lines)
        if self.mode is InteractionMode.REVIEW:
            lines = [
                ("class:interaction.title", "请确认回答\n"),
                ("class:interaction.hint", "Enter 提交 · Esc 返回修改\n"),
            ]
            request = pause.user_input_request
            assert request is not None
            for question in request.questions:
                answer = " / ".join(self.answers.get(question.question_id, ()))
                lines.append(("class:interaction.option", f"{question.header}: {answer}\n"))
            return tuple(lines)

        question = self.current_question
        if question is None:
            return ()
        lines = [
            ("class:interaction.title", f"{question.header} · {self.question_index + 1}\n"),
            ("class:interaction.question", f"{question.question}\n"),
        ]
        if question.kind.value == "text":
            lines.append(("class:interaction.hint", "输入答案后按 Enter · Esc 返回\n"))
        else:
            lines.append(("class:interaction.hint", "↑/↓ 选择 · Space 勾选 · Enter 下一题\n"))
            for index, option in enumerate(question.options):
                selected = index in self.selected_options
                marker = "✓" if selected else ("›" if index == self.option_index else " ")
                lines.append(("class:interaction.option", f"{marker} {option.label} — {option.description}\n"))
            marker = "›" if self.free_text_mode or self.option_index >= len(question.options) else " "
            lines.append(("class:interaction.option", f"{marker} 自行输入\n"))
            if self.free_text_mode:
                lines.append(("class:interaction.hint", "输入答案后按 Enter · Esc 返回选项\n"))
        return tuple(lines)

    def _reset(self, pause: PauseRequest | None) -> None:
        self.mode = InteractionMode.CLOSED
        self.pause = pause
        self.question_index = 0
        self.action_index = 0
        self.option_index = 0
        self.selected_options.clear()
        self.answers.clear()
        self.draft = ""
        self.free_text_mode = False

    def _reset_question_draft(self) -> None:
        self.option_index = 0
        self.selected_options.clear()
        self.draft = ""
        self.free_text_mode = False

    def _load_answer_draft(self) -> None:
        question = self.current_question
        if question is None:
            self._reset_question_draft()
            return
        values = self.answers.get(question.question_id, [])
        self.selected_options = {
            index for index, option in enumerate(question.options) if option.label in values
        }
        option_labels = {option.label for option in question.options}
        free_values = [value for value in values if value not in option_labels]
        self.free_text_mode = bool(free_values)
        self.draft = values[0] if question.kind.value == "text" else (free_values[0] if free_values else "")
        if self.free_text_mode:
            self.option_index = len(question.options)
        elif self.selected_options:
            self.option_index = min(self.selected_options)
        else:
            self.option_index = 0

    def _current_answer_values(self) -> list[str]:
        question = self.current_question
        if question is None:
            return []
        if question.kind.value == "text":
            value = self.draft.strip()
            return [value] if value else []
        values = [
            option.label
            for index, option in enumerate(question.options)
            if index in self.selected_options
        ]
        if question.kind.value == "single_select":
            if self.free_text_mode:
                value = self.draft.strip()
                return [value] if value else []
            if values:
                return values[:1]
            if self.option_index < len(question.options):
                return [question.options[self.option_index].label]
            return []
        value = self.draft.strip() if self.free_text_mode else ""
        if value and value not in values:
            values.append(value)
        return values


__all__ = [
    "InteractionMode",
    "PauseAction",
    "PlanReviewAction",
    "TuiInteractionState",
]
