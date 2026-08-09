from __future__ import annotations

import json
from dataclasses import FrozenInstanceError

import pytest
from jsonschema import Draft202012Validator

from uthcode.core.agent_events import (
    TurnPaused,
    TurnPausing,
    TurnResumed,
    UserInputRequested,
    agent_event_from_dict,
    agent_event_from_json,
)
from uthcode.core.interaction import (
    ASK_USER_TOOL_DEFINITION,
    PauseKind,
    PauseReason,
    PauseRequest,
    PlanReviewChoice,
    PlanReviewRequest,
    PlanReviewResponse,
    PermissionApprovalChoice,
    PermissionApprovalRequest,
    PermissionApprovalResponse,
    QuestionKind,
    QuestionOption,
    RetryProviderResponse,
    ResumeTurnResponse,
    SteeringRequest,
    UserInputRequest,
    UserInputResponse,
    UserQuestion,
    pause_response_from_json,
)
from uthcode.core.permission import (
    Effect,
    PermissionAction,
    PermissionEvaluator,
    ResourceScope,
    Rule,
    RuleKind,
    RuleSet,
    Decision,
)


def _select_question(
    question_id: str = "choice",
    *,
    kind: QuestionKind = QuestionKind.SINGLE_SELECT,
    allow_other: bool = False,
) -> UserQuestion:
    return UserQuestion(
        question_id=question_id,
        header="Choice",
        question="Which option should be used?",
        kind=kind,
        options=(
            QuestionOption("one", "Use the first option"),
            QuestionOption("two", "Use the second option"),
        ),
        allow_other=allow_other,
    )


def _request() -> UserInputRequest:
    return UserInputRequest(
        questions=(
            UserQuestion("name", "Name", "What is your name?", QuestionKind.TEXT),
            _select_question(),
            _select_question("many", kind=QuestionKind.MULTI_SELECT, allow_other=True),
        )
    )


def _pause(
    *,
    kind: PauseKind = PauseKind.USER_INPUT_REQUIRED,
    reason: PauseReason = PauseReason.USER_INPUT_REQUIRED,
) -> PauseRequest:
    return PauseRequest(
        pause_id="pause-1",
        run_id="run-1",
        turn_id="turn-1",
        kind=kind,
        reason=reason,
        iteration=2,
        created_at="2026-08-07T12:00:00+08:00",
        tool_call_id="call-1" if kind is PauseKind.USER_INPUT_REQUIRED else None,
        user_input_request=_request() if kind is PauseKind.USER_INPUT_REQUIRED else None,
    )


def test_enums_and_pause_combinations_are_fixed() -> None:
    assert [item.value for item in PauseKind] == [
        "user_requested",
        "user_input_required",
        "provider_unavailable",
        "permission_required",
        "plan_review_required",
    ]
    assert [item.value for item in PauseReason] == [
        "user_requested",
        "user_input_required",
        "network_error",
        "rate_limited",
        "permission_required",
        "plan_review_required",
    ]

    PauseRequest(
        "pause-user",
        "run-1",
        "turn-1",
        PauseKind.USER_REQUESTED,
        PauseReason.USER_REQUESTED,
        1,
        "now",
    )
    PauseRequest(
        "pause-network",
        "run-1",
        "turn-1",
        PauseKind.PROVIDER_UNAVAILABLE,
        PauseReason.NETWORK_ERROR,
        1,
        "now",
    )
    PauseRequest(
        "pause-rate",
        "run-1",
        "turn-1",
        PauseKind.PROVIDER_UNAVAILABLE,
        PauseReason.RATE_LIMITED,
        1,
        "now",
    )

    with pytest.raises(ValueError):
        PauseRequest(
            "pause-invalid",
            "run-1",
            "turn-1",
            PauseKind.USER_REQUESTED,
            PauseReason.NETWORK_ERROR,
            1,
            "now",
        )
    with pytest.raises(ValueError):
        PauseRequest(
            "pause-invalid",
            "run-1",
            "turn-1",
            PauseKind.USER_INPUT_REQUIRED,
            PauseReason.USER_INPUT_REQUIRED,
            1,
            "now",
        )


def test_question_shapes_and_json_are_immutable_and_stable() -> None:
    request = _request()
    encoded = request.to_json()
    assert UserInputRequest.from_json(encoded) == request
    assert json.loads(encoded) == request.to_dict()

    with pytest.raises(FrozenInstanceError):
        request.questions = ()  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        request.questions[0].question = "changed"  # type: ignore[misc]

    with pytest.raises(ValueError):
        UserInputRequest(())
    with pytest.raises(ValueError):
        UserInputRequest(tuple(UserQuestion(str(i), "h", "q", QuestionKind.TEXT) for i in range(5)))
    with pytest.raises(ValueError):
        UserInputRequest((UserQuestion("same", "h", "q", QuestionKind.TEXT), UserQuestion("same", "h", "q", QuestionKind.TEXT)))
    with pytest.raises(ValueError):
        UserQuestion("q", "h", "q", QuestionKind.TEXT, options=(QuestionOption("x", "x"),))
    with pytest.raises(ValueError):
        UserQuestion("q", "h", "q", QuestionKind.TEXT, allow_other=True)
    with pytest.raises(ValueError):
        UserQuestion(
            "q",
            "h",
            "q",
            QuestionKind.SINGLE_SELECT,
            options=(QuestionOption("only", "x"),),
        )
    with pytest.raises(ValueError):
        UserQuestion(
            "q",
            "h",
            "q",
            QuestionKind.SINGLE_SELECT,
            options=(QuestionOption("same", "x"), QuestionOption("same", "y")),
        )


def test_answers_validate_by_question_kind_and_have_stable_json() -> None:
    request = _request()
    valid = UserInputResponse(
        "pause-1",
        "run-1",
        "turn-1",
        "call-1",
        {"name": ["Ada"], "choice": ["one"], "many": ["one", "custom"]},
    )
    normalized = request.validate_answers(valid.answers)
    assert normalized == valid.answers
    assert json.loads(valid.answers_json(request)) == {
        "answers": {"choice": ["one"], "many": ["one", "custom"], "name": ["Ada"]}
    }

    with pytest.raises(ValueError):
        request.validate_answers({"name": ["Ada"], "choice": ["one"], "many": []})
    with pytest.raises(ValueError):
        request.validate_answers({"name": ["Ada", "extra"], "choice": ["one"], "many": ["one"]})
    with pytest.raises(ValueError):
        request.validate_answers({"name": ["Ada"], "choice": ["unknown"], "many": ["one"]})
    with pytest.raises(ValueError):
        request.validate_answers({"name": ["Ada"], "choice": ["one"], "many": ["one", "one"]})
    with pytest.raises(ValueError):
        request.validate_answers({"name": ["Ada"], "choice": ["one"], "many": ["one"], "extra": ["x"]})


def test_other_and_response_type_matching() -> None:
    request = UserInputRequest((_select_question(allow_other=True),))
    assert request.validate_answers({"choice": ["a custom answer"]})["choice"] == ["a custom answer"]

    pause = _pause()
    assert pause.validate_response(UserInputResponse("pause-1", "run-1", "turn-1", "call-1", {"name": ["Ada"], "choice": ["one"], "many": ["one"]})) is None
    with pytest.raises(ValueError):
        pause.validate_response(ResumeTurnResponse("pause-1", "run-1", "turn-1"))
    with pytest.raises(ValueError):
        pause.validate_response(UserInputResponse("stale", "run-1", "turn-1", "call-1", {"name": ["Ada"], "choice": ["one"], "many": ["one"]}))

    for response, response_type in (
        (ResumeTurnResponse("pause", "run", "turn"), "resume_turn"),
        (RetryProviderResponse("pause", "run", "turn"), "retry_provider"),
        (UserInputResponse("pause", "run", "turn", "call", {"q": ["a"]}), "user_input"),
        (
            PlanReviewResponse(
                "pause",
                "run",
                "turn",
                1,
                PlanReviewChoice.APPROVE,
            ),
            "plan_review",
        ),
    ):
        assert json.loads(response.to_json())["type"] == response_type
        assert pause_response_from_json(response.to_json()) == response


def test_plan_review_request_response_and_revision_validation_are_strict() -> None:
    request = PlanReviewRequest(2, "Complete replacement plan")
    pause = PauseRequest(
        "pause-plan",
        "run-1",
        "turn-1",
        PauseKind.PLAN_REVIEW_REQUIRED,
        PauseReason.PLAN_REVIEW_REQUIRED,
        3,
        "now",
        plan_review_request=request,
    )
    approve = PlanReviewResponse(
        "pause-plan",
        "run-1",
        "turn-1",
        2,
        PlanReviewChoice.APPROVE,
    )
    revise = PlanReviewResponse(
        "pause-plan",
        "run-1",
        "turn-1",
        2,
        PlanReviewChoice.REVISE,
        "Keep the public API unchanged.",
    )

    assert pause.validate_response(approve) is None
    assert pause.validate_response(revise) is None
    assert PauseRequest.from_json(pause.to_json()) == pause
    assert PlanReviewRequest.from_json(request.to_json()) == request
    assert PlanReviewResponse.from_dict(approve.to_dict()) == approve
    assert PlanReviewResponse.from_json(revise.to_json()) == revise
    assert pause_response_from_json(approve.to_json()) == approve
    assert pause_response_from_json(revise.to_json()) == revise
    assert approve.to_dict() == {
        "type": "plan_review",
        "pause_id": "pause-plan",
        "run_id": "run-1",
        "turn_id": "turn-1",
        "revision": 2,
        "choice": "approve",
    }
    assert revise.to_dict() == {
        "type": "plan_review",
        "pause_id": "pause-plan",
        "run_id": "run-1",
        "turn_id": "turn-1",
        "revision": 2,
        "choice": "revise",
        "feedback": "Keep the public API unchanged.",
    }
    assert pause.to_dict()["plan_review_request"] == request.to_dict()

    for response in (
        PlanReviewResponse("wrong", "run-1", "turn-1", 2, PlanReviewChoice.APPROVE),
        PlanReviewResponse("pause-plan", "wrong", "turn-1", 2, PlanReviewChoice.APPROVE),
        PlanReviewResponse("pause-plan", "run-1", "wrong", 2, PlanReviewChoice.APPROVE),
        PlanReviewResponse("pause-plan", "run-1", "turn-1", 1, PlanReviewChoice.APPROVE),
    ):
        with pytest.raises(ValueError):
            pause.validate_response(response)

    with pytest.raises(ValueError):
        PlanReviewResponse(
            "pause-plan",
            "run-1",
            "turn-1",
            2,
            PlanReviewChoice.REVISE,
            " ",
        )
    with pytest.raises(ValueError):
        PlanReviewResponse(
            "pause-plan",
            "run-1",
            "turn-1",
            2,
            PlanReviewChoice.APPROVE,
            "unexpected feedback",
        )


@pytest.mark.parametrize("feedback", (None, "unexpected feedback"))
def test_plan_review_approve_json_rejects_any_feedback_field(
    feedback: object,
) -> None:
    payload = {
        "type": "plan_review",
        "pause_id": "pause-plan",
        "run_id": "run-1",
        "turn_id": "turn-1",
        "revision": 2,
        "choice": "approve",
        "feedback": feedback,
    }

    with pytest.raises(ValueError):
        PlanReviewResponse.from_dict(payload)
    with pytest.raises(ValueError):
        pause_response_from_json(json.dumps(payload))


@pytest.mark.parametrize(
    "payload",
    (
        {
            "type": "plan_review",
            "pause_id": "pause-plan",
            "run_id": "run-1",
            "turn_id": "turn-1",
            "revision": 2,
            "choice": "revise",
        },
        {
            "type": "plan_review",
            "pause_id": "pause-plan",
            "run_id": "run-1",
            "turn_id": "turn-1",
            "revision": 2,
            "choice": "revise",
            "feedback": None,
        },
        {
            "type": "plan_review",
            "pause_id": "pause-plan",
            "run_id": "run-1",
            "turn_id": "turn-1",
            "revision": 2,
            "choice": "revise",
            "feedback": " ",
        },
    ),
)
def test_plan_review_revise_json_requires_nonempty_feedback(
    payload: dict[str, object],
) -> None:
    with pytest.raises((TypeError, ValueError)):
        PlanReviewResponse.from_dict(payload)
    with pytest.raises((TypeError, ValueError)):
        pause_response_from_json(json.dumps(payload))


def test_steering_request_is_immutable_json_safe_and_not_a_pause() -> None:
    request = SteeringRequest(
        steering_id="steer-1",
        run_id="run-1",
        turn_id="turn-1",
        text="Also update the tests.",
    )

    assert SteeringRequest.from_json(request.to_json()) == request
    assert request.to_dict() == {
        "steering_id": "steer-1",
        "run_id": "run-1",
        "turn_id": "turn-1",
        "text": "Also update the tests.",
    }
    assert not isinstance(request, PauseRequest)
    assert "steer" not in {item.value for item in PauseKind}
    with pytest.raises(FrozenInstanceError):
        request.text = "changed"  # type: ignore[misc]
    with pytest.raises((TypeError, ValueError)):
        SteeringRequest("steer-1", "run-1", "turn-1", " ")
    with pytest.raises((TypeError, ValueError, KeyError)):
        SteeringRequest.from_dict({**request.to_dict(), "unexpected": True})


def test_permission_approval_protocol_is_strict_and_redacted() -> None:
    action = PermissionAction(
        "WriteFile",
        "write",
        Effect.WRITE,
        "C:/workspace/note.txt",
        ResourceScope.INSIDE,
    )
    decision = PermissionEvaluator().evaluate(action)
    request = PermissionApprovalRequest.from_decision(
        decision,
        permission_id="permission-1",
        run_id="run-1",
        turn_id="turn-1",
        tool_call_id="call-1",
    )
    assert request.choices == (
        PermissionApprovalChoice.ONCE,
        PermissionApprovalChoice.SESSION,
        PermissionApprovalChoice.REJECT,
    )
    payload = request.to_dict()
    assert PermissionApprovalRequest.from_json(request.to_json()) == request
    assert "secret-value" not in json.dumps(payload)

    pause = PauseRequest(
        "pause-1",
        "run-1",
        "turn-1",
        PauseKind.PERMISSION_REQUIRED,
        PauseReason.PERMISSION_REQUIRED,
        1,
        "now",
        tool_call_id="call-1",
        permission_request=request,
    )
    response = PermissionApprovalResponse(
        pause.pause_id,
        pause.run_id,
        pause.turn_id,
        request.permission_id,
        PermissionApprovalChoice.ONCE,
    )
    assert pause.validate_response(response) is None
    assert pause_response_from_json(response.to_json()) == response
    with pytest.raises(ValueError):
        pause.validate_response(
            PermissionApprovalResponse(
                pause.pause_id,
                pause.run_id,
                pause.turn_id,
                "stale-permission",
                PermissionApprovalChoice.ONCE,
            )
        )

    guard_decision = PermissionEvaluator(
        RuleSet(
            (
                Rule(
                    kind=RuleKind.GUARD,
                    decision=Decision.ASK,
                    tool="WriteFile",
                    source="guard",
                ),
            )
        )
    ).evaluate(action)
    guard_request = PermissionApprovalRequest.from_decision(
        guard_decision,
        permission_id="permission-guard",
        run_id="run-1",
        turn_id="turn-1",
        tool_call_id="call-1",
    )
    assert guard_request.choices == (
        PermissionApprovalChoice.ONCE,
        PermissionApprovalChoice.REJECT,
    )


def test_permission_pause_and_response_decoders_reject_missing_and_extra_fields() -> None:
    action = PermissionAction(
        "WriteFile",
        "write",
        Effect.WRITE,
        "note.txt",
        ResourceScope.INSIDE,
    )
    request = PermissionApprovalRequest.from_decision(
        PermissionEvaluator().evaluate(action),
        permission_id="permission-1",
        run_id="run-1",
        turn_id="turn-1",
        tool_call_id="call-1",
    )
    pause = PauseRequest(
        "pause-1",
        "run-1",
        "turn-1",
        PauseKind.PERMISSION_REQUIRED,
        PauseReason.PERMISSION_REQUIRED,
        1,
        "now",
        tool_call_id="call-1",
        permission_request=request,
    ).to_dict()
    response = PermissionApprovalResponse(
        "pause-1",
        "run-1",
        "turn-1",
        "permission-1",
        PermissionApprovalChoice.REJECT,
    ).to_dict()
    for decoder, payload, required in (
        (PauseRequest.from_dict, pause, "permission_request"),
        (PermissionApprovalResponse.from_dict, response, "choice"),
    ):
        missing = dict(payload)
        del missing[required]
        with pytest.raises((TypeError, ValueError, KeyError)):
            decoder(missing)
        with pytest.raises((TypeError, ValueError, KeyError)):
            decoder({**payload, "unexpected": True})


def test_ask_user_definition_is_strict_and_json_schema_valid() -> None:
    definition = ASK_USER_TOOL_DEFINITION
    assert definition.name == "AskUserQuestion"
    assert "Permission" in (definition.description or "")
    schema = definition.parameters
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["questions"]
    question_schema = schema["properties"]["questions"]["items"]
    option_schema = question_schema["properties"]["options"]["items"]
    assert question_schema["additionalProperties"] is False
    assert option_schema["additionalProperties"] is False
    assert question_schema["properties"]["options"]["minItems"] == 2
    assert question_schema["properties"]["options"]["maxItems"] == 6
    schema_data = definition.to_dict()["parameters"]
    Draft202012Validator.check_schema(schema_data)
    validator = Draft202012Validator(schema_data)
    assert validator.is_valid({"questions": [UserQuestion("q", "h", "q", QuestionKind.TEXT).to_dict()]})
    assert not validator.is_valid({"questions": [{"question_id": "q", "header": "h", "question": "q", "kind": "text", "unexpected": True}]})


def test_interaction_events_round_trip_without_answer_content() -> None:
    pause = _pause()
    events = (
        TurnPausing("run-1", "turn-1", "pause-1", PauseKind.USER_REQUESTED, PauseReason.USER_REQUESTED, 2),
        UserInputRequested("run-1", "turn-1", "pause-1", "call-1", _request()),
        TurnPaused("run-1", "turn-1", pause),
        TurnResumed("run-1", "turn-1", "pause-1", PauseKind.USER_INPUT_REQUIRED),
    )
    for event in events:
        restored = agent_event_from_json(event.to_json())
        assert restored == event
        payload = event.to_json()
        assert "Ada" not in payload
        assert "answers" not in payload
        assert "asyncio" not in payload


@pytest.mark.parametrize(
    "factory",
    (
        lambda: QuestionOption("", "description"),
        lambda: QuestionOption(" ", "description"),
        lambda: QuestionOption("label", ""),
        lambda: QuestionOption("label", "\t"),
        lambda: UserQuestion("", "Header", "Question", QuestionKind.TEXT),
        lambda: UserQuestion("id", "", "Question", QuestionKind.TEXT),
        lambda: UserQuestion("id", "Header", "", QuestionKind.TEXT),
        lambda: PauseRequest("", "run", "turn", PauseKind.USER_REQUESTED, PauseReason.USER_REQUESTED, 1, "now"),
        lambda: PauseRequest("pause", "", "turn", PauseKind.USER_REQUESTED, PauseReason.USER_REQUESTED, 1, "now"),
        lambda: PauseRequest("pause", "run", "", PauseKind.USER_REQUESTED, PauseReason.USER_REQUESTED, 1, "now"),
        lambda: PauseRequest("pause", "run", "turn", PauseKind.USER_REQUESTED, PauseReason.USER_REQUESTED, 1, ""),
        lambda: ResumeTurnResponse("", "run", "turn"),
        lambda: ResumeTurnResponse("pause", "", "turn"),
        lambda: RetryProviderResponse("pause", "run", " "),
        lambda: UserInputResponse("pause", "run", "turn", "", {"answer": ["ok"]}),
    ),
)
def test_protocol_rejects_empty_or_whitespace_text(factory) -> None:
    with pytest.raises((TypeError, ValueError)):
        factory()


@pytest.mark.parametrize(
    "factory",
    (
        lambda: QuestionOption(1, "description"),
        lambda: UserQuestion("id", 1, "Question", QuestionKind.TEXT),
        lambda: UserQuestion("id", "Header", "Question", 1),
        lambda: UserQuestion("id", "Header", "Question", QuestionKind.TEXT, options=1),
        lambda: UserQuestion("id", "Header", "Question", QuestionKind.TEXT, allow_other=1),
        lambda: UserInputRequest(1),
        lambda: PauseRequest("pause", "run", "turn", PauseKind.USER_REQUESTED, PauseReason.USER_REQUESTED, True, "now"),
        lambda: PauseRequest("pause", "run", "turn", PauseKind.USER_REQUESTED, PauseReason.USER_REQUESTED, "1", "now"),
        lambda: PauseRequest("pause", "run", "turn", PauseKind.USER_REQUESTED, PauseReason.USER_REQUESTED, 1, 1),
        lambda: UserInputResponse("pause", "run", "turn", "call", {"answer": 1}),
        lambda: UserInputResponse("pause", "run", "turn", "call", {"answer": "ok"}),
    ),
)
def test_protocol_rejects_wrong_scalar_and_collection_types(factory) -> None:
    with pytest.raises((TypeError, ValueError)):
        factory()


def test_select_and_question_count_boundaries_are_exact() -> None:
    def select_with_options(count: int) -> UserQuestion:
        return UserQuestion(
            "choice",
            "Choice",
            "Choose",
            QuestionKind.SINGLE_SELECT,
            options=tuple(QuestionOption(str(index), "description") for index in range(count)),
        )

    select_with_options(2)
    select_with_options(6)
    with pytest.raises(ValueError):
        select_with_options(1)
    with pytest.raises(ValueError):
        select_with_options(7)
    with pytest.raises(ValueError):
        UserQuestion(
            "choice",
            "Choice",
            "Choose",
            QuestionKind.SINGLE_SELECT,
            options=(QuestionOption("same", "one"), QuestionOption("same", "two")),
        )

    for count in (1, 4):
        UserInputRequest(
            tuple(
                UserQuestion(str(index), "Header", "Question", QuestionKind.TEXT)
                for index in range(count)
            )
        )
    with pytest.raises(ValueError):
        UserInputRequest(())
    with pytest.raises(ValueError):
        UserInputRequest(
            tuple(
                UserQuestion(str(index), "Header", "Question", QuestionKind.TEXT)
                for index in range(5)
            )
        )


def test_text_questions_reject_options_and_allow_other() -> None:
    option = QuestionOption("one", "One")
    with pytest.raises(ValueError):
        UserQuestion("text", "Text", "Enter", QuestionKind.TEXT, options=(option,))
    with pytest.raises(ValueError):
        UserQuestion("text", "Text", "Enter", QuestionKind.TEXT, allow_other=True)


def _assert_strict_dict_and_json_decoders(
    from_dict,
    from_json,
    payload: dict[str, object],
    required_field: str,
) -> None:
    missing = dict(payload)
    del missing[required_field]
    for decoder in (from_dict, lambda value: from_json(json.dumps(value))):
        with pytest.raises((TypeError, ValueError, KeyError)):
            decoder(missing)
    extra = {**payload, "unexpected": True}
    for decoder in (from_dict, lambda value: from_json(json.dumps(value))):
        with pytest.raises((TypeError, ValueError, KeyError)):
            decoder(extra)


def test_all_protocol_decoders_reject_missing_and_extra_fields() -> None:
    option = QuestionOption("one", "One").to_dict()
    text_question = UserQuestion("text", "Text", "Enter", QuestionKind.TEXT).to_dict()
    select_question = _select_question().to_dict()
    request = _request().to_dict()
    user_pause = _pause(kind=PauseKind.USER_REQUESTED, reason=PauseReason.USER_REQUESTED).to_dict()
    input_pause = _pause().to_dict()
    resume = ResumeTurnResponse("pause", "run", "turn").to_dict()
    retry = RetryProviderResponse("pause", "run", "turn").to_dict()
    answer = UserInputResponse(
        "pause",
        "run",
        "turn",
        "call-1",
        {"name": ["Ada"], "choice": ["one"], "many": ["one"]},
    ).to_dict()

    _assert_strict_dict_and_json_decoders(QuestionOption.from_dict, QuestionOption.from_json, option, "label")
    _assert_strict_dict_and_json_decoders(UserQuestion.from_dict, UserQuestion.from_json, text_question, "question")
    _assert_strict_dict_and_json_decoders(UserQuestion.from_dict, UserQuestion.from_json, select_question, "options")
    _assert_strict_dict_and_json_decoders(UserInputRequest.from_dict, UserInputRequest.from_json, request, "questions")
    _assert_strict_dict_and_json_decoders(PauseRequest.from_dict, PauseRequest.from_json, user_pause, "reason")
    _assert_strict_dict_and_json_decoders(PauseRequest.from_dict, PauseRequest.from_json, input_pause, "tool_call_id")
    _assert_strict_dict_and_json_decoders(ResumeTurnResponse.from_dict, ResumeTurnResponse.from_json, resume, "pause_id")
    _assert_strict_dict_and_json_decoders(RetryProviderResponse.from_dict, RetryProviderResponse.from_json, retry, "turn_id")
    _assert_strict_dict_and_json_decoders(UserInputResponse.from_dict, UserInputResponse.from_json, answer, "answers")

    for payload in (resume, retry, answer):
        missing = dict(payload)
        del missing["type"]
        with pytest.raises((TypeError, ValueError, KeyError)):
            pause_response_from_json(json.dumps(missing))
        with pytest.raises((TypeError, ValueError, KeyError)):
            pause_response_from_json(json.dumps({**payload, "unexpected": True}))


def test_invalid_pause_reason_kind_and_response_combinations_are_rejected() -> None:
    invalid_pairs = (
        (PauseKind.USER_REQUESTED, PauseReason.USER_INPUT_REQUIRED),
        (PauseKind.USER_REQUESTED, PauseReason.NETWORK_ERROR),
        (PauseKind.USER_INPUT_REQUIRED, PauseReason.USER_REQUESTED),
        (PauseKind.USER_INPUT_REQUIRED, PauseReason.RATE_LIMITED),
        (PauseKind.PROVIDER_UNAVAILABLE, PauseReason.USER_REQUESTED),
        (PauseKind.PROVIDER_UNAVAILABLE, PauseReason.USER_INPUT_REQUIRED),
    )
    for kind, reason in invalid_pairs:
        with pytest.raises(ValueError):
            PauseRequest("pause", "run", "turn", kind, reason, 1, "now")

    with pytest.raises(ValueError):
        pause_response_from_json(
            json.dumps({"type": "unknown", "pause_id": "p", "run_id": "r", "turn_id": "t"})
        )
    with pytest.raises(ValueError):
        ResumeTurnResponse.from_dict(
            {"type": "retry_provider", "pause_id": "p", "run_id": "r", "turn_id": "t"}
        )
    with pytest.raises(ValueError):
        RetryProviderResponse.from_dict(
            {"type": "resume_turn", "pause_id": "p", "run_id": "r", "turn_id": "t"}
        )


def test_all_pause_and_tool_ids_must_match_the_pending_request() -> None:
    pause = _pause()
    valid = {"name": ["Ada"], "choice": ["one"], "many": ["one"]}
    for field_name in ("pause_id", "run_id", "turn_id", "tool_call_id"):
        values = {
            "pause_id": "pause-1",
            "run_id": "run-1",
            "turn_id": "turn-1",
            "tool_call_id": "call-1",
        }
        values[field_name] = "wrong"
        response = UserInputResponse(
            values["pause_id"],
            values["run_id"],
            values["turn_id"],
            values["tool_call_id"],
            valid,
        )
        with pytest.raises(ValueError):
            pause.validate_response(response)


@pytest.mark.parametrize(
    "question_request, answers",
    (
        (UserInputRequest((UserQuestion("text", "Text", "Enter", QuestionKind.TEXT),)), {}),
            (UserInputRequest((_select_question(),)), {}),
        (UserInputRequest((_select_question(kind=QuestionKind.MULTI_SELECT),)), {}),
        (UserInputRequest((UserQuestion("text", "Text", "Enter", QuestionKind.TEXT),)), {"wrong": ["answer"]}),
            (UserInputRequest((_select_question(),)), {"wrong": ["one"]}),
        (UserInputRequest((_select_question(kind=QuestionKind.MULTI_SELECT),)), {"wrong": ["one"]}),
    ),
)
def test_text_single_multi_answers_require_the_expected_question_ids(question_request, answers) -> None:
    with pytest.raises(ValueError):
        question_request.validate_answers(answers)


@pytest.mark.parametrize(
    "answers",
    (
        {"text": [""]},
        {"text": ["   "]},
        {"text": ["answer", "answer"]},
    ),
)
def test_answers_reject_empty_whitespace_and_duplicate_values(answers) -> None:
    request = UserInputRequest((UserQuestion("text", "Text", "Enter", QuestionKind.TEXT),))
    with pytest.raises((TypeError, ValueError)):
        request.validate_answers(answers)


def test_answer_schema_has_additional_properties_false_at_every_object_layer() -> None:
    schema = ASK_USER_TOOL_DEFINITION.parameters
    question_schema = schema["properties"]["questions"]["items"]
    option_schema = question_schema["properties"]["options"]["items"]
    assert schema["additionalProperties"] is False
    assert question_schema["additionalProperties"] is False
    assert option_schema["additionalProperties"] is False
    validator = Draft202012Validator(schema)
    assert not validator.is_valid({"questions": [], "extra": True})
    assert not validator.is_valid(
        {"questions": [{"question_id": "q", "header": "h", "question": "q", "kind": "text", "extra": True}]}
    )
    assert not validator.is_valid(
        {
            "questions": [
                {
                    "question_id": "q",
                    "header": "h",
                    "question": "q",
                    "kind": "single_select",
                    "options": [
                        {"label": "one", "description": "One", "extra": True},
                        {"label": "two", "description": "Two"},
                    ],
                }
            ]
        }
    )


def test_new_agent_events_reject_missing_extra_and_nested_id_fields() -> None:
    pause = _pause()
    events = (
        TurnPausing("run-1", "turn-1", "pause-1", PauseKind.USER_REQUESTED, PauseReason.USER_REQUESTED, 2),
        UserInputRequested("run-1", "turn-1", "pause-1", "call-1", _request()),
        TurnPaused("run-1", "turn-1", pause),
        TurnResumed("run-1", "turn-1", "pause-1", PauseKind.USER_INPUT_REQUIRED),
    )
    for event in events:
        payload = event.to_dict()
        for field_name in tuple(payload):
            missing = dict(payload)
            del missing[field_name]
            with pytest.raises((TypeError, ValueError, KeyError)):
                agent_event_from_dict(missing)
            with pytest.raises((TypeError, ValueError, KeyError)):
                agent_event_from_json(json.dumps(missing))
        with pytest.raises((TypeError, ValueError, KeyError)):
            agent_event_from_dict({**payload, "unexpected": True})
        with pytest.raises((TypeError, ValueError, KeyError)):
            agent_event_from_json(json.dumps({**payload, "unexpected": True}))

    nested = pause.to_dict()
    nested["run_id"] = "wrong-run"
    with pytest.raises(ValueError):
        agent_event_from_dict(
            {"type": "turn_paused", "run_id": "run-1", "turn_id": "turn-1", "pause": nested}
        )
    with pytest.raises(ValueError):
        TurnPausing(
            "run-1",
            "turn-1",
            "pause-1",
            PauseKind.USER_REQUESTED,
            PauseReason.NETWORK_ERROR,
            2,
        )
