"""Immutable Core protocol values for pausing a Turn and asking a user.

The values in this module are deliberately independent of an interface or a
runtime coordinator.  They are small JSON-safe protocol objects that can be
passed between Core and an Application control plane while the active Turn
remains in memory.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any, ClassVar, TypeAlias

from .provider import JsonPayload, ToolDefinition


def _require_text(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _require_positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be a positive integer")
    if value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")
    return value


def _as_tuple(value: object, field_name: str) -> tuple[Any, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise TypeError(f"{field_name} must be a sequence")
    return tuple(value)


def _as_mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    return value


def _expect_keys(value: Mapping[str, object], expected: set[str]) -> None:
    actual = set(value)
    missing = expected - actual
    if missing:
        raise ValueError(f"payload is missing fields: {sorted(missing)!r}")
    extra = actual - expected
    if extra:
        raise ValueError(f"payload has unknown fields: {sorted(extra)!r}")


def _required(value: Mapping[str, object], field_name: str) -> object:
    try:
        return value[field_name]
    except KeyError as exc:
        raise ValueError(f"payload is missing field: {field_name}") from exc


def _coerce_enum(enum_type: type[Enum], value: object, field_name: str) -> Enum:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"unknown {field_name}: {value!r}") from exc


def _json_value(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (QuestionOption, UserQuestion, UserInputRequest, PauseRequest)):
        return value.to_dict()
    if isinstance(value, JsonPayload):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, Mapping):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_value(item) for item in value]
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    raise TypeError(f"interaction value of type {type(value).__name__} is not JSON-safe")


class _JsonModel:
    def to_dict(self) -> dict[str, object]:
        raise NotImplementedError

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)


def _json_object(value: str, field_name: str) -> Mapping[str, object]:
    parsed = json.loads(value)
    if not isinstance(parsed, Mapping):
        raise TypeError(f"{field_name} JSON must contain an object")
    return parsed


class PauseKind(str, Enum):
    USER_REQUESTED = "user_requested"
    USER_INPUT_REQUIRED = "user_input_required"
    PROVIDER_UNAVAILABLE = "provider_unavailable"


class PauseReason(str, Enum):
    USER_REQUESTED = "user_requested"
    USER_INPUT_REQUIRED = "user_input_required"
    NETWORK_ERROR = "network_error"
    RATE_LIMITED = "rate_limited"


class QuestionKind(str, Enum):
    TEXT = "text"
    SINGLE_SELECT = "single_select"
    MULTI_SELECT = "multi_select"


@dataclass(frozen=True, slots=True)
class QuestionOption(_JsonModel):
    label: str
    description: str

    def __post_init__(self) -> None:
        _require_text(self.label, "label")
        _require_text(self.description, "description")

    def to_dict(self) -> dict[str, object]:
        return {"label": self.label, "description": self.description}

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> QuestionOption:
        payload = _as_mapping(value, "option")
        _expect_keys(payload, {"label", "description"})
        return cls(
            label=_required(payload, "label"),  # type: ignore[arg-type]
            description=_required(payload, "description"),  # type: ignore[arg-type]
        )

    @classmethod
    def from_json(cls, value: str) -> QuestionOption:
        return cls.from_dict(_json_object(value, "QuestionOption"))


@dataclass(frozen=True, slots=True)
class UserQuestion(_JsonModel):
    question_id: str
    header: str
    question: str
    kind: QuestionKind
    options: tuple[QuestionOption, ...] = ()
    allow_other: bool = False

    def __post_init__(self) -> None:
        _require_text(self.question_id, "question_id")
        _require_text(self.header, "header")
        _require_text(self.question, "question")
        kind = _coerce_enum(QuestionKind, self.kind, "question kind")
        object.__setattr__(self, "kind", kind)
        options = _as_tuple(self.options, "options")
        if not all(isinstance(option, QuestionOption) for option in options):
            raise TypeError("options must contain QuestionOption values")
        object.__setattr__(self, "options", options)
        if not isinstance(self.allow_other, bool):
            raise TypeError("allow_other must be a boolean")

        if kind is QuestionKind.TEXT:
            if options:
                raise ValueError("text questions must not contain options")
            if self.allow_other:
                raise ValueError("text questions must not allow Other")
            return

        if not 2 <= len(options) <= 6:
            raise ValueError("select questions require between 2 and 6 options")
        labels = [option.label for option in options]
        if len(set(labels)) != len(labels):
            raise ValueError("select option labels must be unique")

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "question_id": self.question_id,
            "header": self.header,
            "question": self.question,
            "kind": self.kind.value,
        }
        if self.kind is not QuestionKind.TEXT:
            payload["options"] = [option.to_dict() for option in self.options]
            payload["allow_other"] = self.allow_other
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> UserQuestion:
        payload = _as_mapping(value, "question")
        kind = _coerce_enum(QuestionKind, _required(payload, "kind"), "question kind")
        base = {"question_id", "header", "question", "kind"}
        if kind is QuestionKind.TEXT:
            _expect_keys(payload, base)
            options: tuple[QuestionOption, ...] = ()
            allow_other = False
        else:
            if not base.issubset(payload):
                _expect_keys(payload, base | {"options"})
            allowed = base | {"options", "allow_other"}
            extra = set(payload) - allowed
            if extra:
                raise ValueError(f"payload has unknown fields: {sorted(extra)!r}")
            if "options" not in payload:
                raise ValueError("payload is missing fields: ['options']")
            options = tuple(
                QuestionOption.from_dict(item)  # type: ignore[arg-type]
                for item in _as_tuple(_required(payload, "options"), "options")
            )
            allow_other = payload.get("allow_other", False)  # type: ignore[assignment]
        return cls(
            question_id=_required(payload, "question_id"),  # type: ignore[arg-type]
            header=_required(payload, "header"),  # type: ignore[arg-type]
            question=_required(payload, "question"),  # type: ignore[arg-type]
            kind=kind,
            options=options,
            allow_other=allow_other,  # type: ignore[arg-type]
        )

    @classmethod
    def from_json(cls, value: str) -> UserQuestion:
        return cls.from_dict(_json_object(value, "UserQuestion"))


@dataclass(frozen=True, slots=True)
class UserInputRequest(_JsonModel):
    questions: tuple[UserQuestion, ...]

    def __post_init__(self) -> None:
        questions = _as_tuple(self.questions, "questions")
        if not 1 <= len(questions) <= 4:
            raise ValueError("UserInputRequest requires between 1 and 4 questions")
        if not all(isinstance(question, UserQuestion) for question in questions):
            raise TypeError("questions must contain UserQuestion values")
        ids = [question.question_id for question in questions]
        if len(set(ids)) != len(ids):
            raise ValueError("question IDs must be unique")
        object.__setattr__(self, "questions", questions)

    def to_dict(self) -> dict[str, object]:
        return {"questions": [question.to_dict() for question in self.questions]}

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> UserInputRequest:
        payload = _as_mapping(value, "user_input_request")
        _expect_keys(payload, {"questions"})
        questions = tuple(
            UserQuestion.from_dict(item)  # type: ignore[arg-type]
            for item in _as_tuple(_required(payload, "questions"), "questions")
        )
        return cls(questions)

    @classmethod
    def from_json(cls, value: str) -> UserInputRequest:
        return cls.from_dict(_json_object(value, "UserInputRequest"))

    def validate_answers(self, answers: Mapping[str, Sequence[str]] | JsonPayload) -> JsonPayload:
        normalized = _normalize_answers(answers)
        expected = {question.question_id for question in self.questions}
        actual = set(normalized)
        unknown = actual - expected
        missing = expected - actual
        if unknown:
            raise ValueError(f"answers contain unknown question IDs: {sorted(unknown)!r}")
        if missing:
            raise ValueError(f"answers are missing question IDs: {sorted(missing)!r}")

        questions = {question.question_id: question for question in self.questions}
        for question_id, question in questions.items():
            values = tuple(normalized[question_id])
            if question.kind is QuestionKind.TEXT and len(values) != 1:
                raise ValueError("text questions require exactly one answer")
            if question.kind is QuestionKind.SINGLE_SELECT and len(values) != 1:
                raise ValueError("single-select questions require exactly one answer")
            if question.kind is QuestionKind.MULTI_SELECT and not values:
                raise ValueError("multi-select questions require at least one answer")
            if question.kind is not QuestionKind.TEXT:
                allowed = {option.label for option in question.options}
                if not question.allow_other and any(value not in allowed for value in values):
                    raise ValueError(f"answers contain an invalid option for {question_id}")
        return normalized

    def answers_to_json(self, answers: Mapping[str, Sequence[str]] | JsonPayload) -> str:
        normalized = self.validate_answers(answers)
        return json.dumps(
            {"answers": {key: list(values) for key, values in normalized.items()}},
            ensure_ascii=False,
            sort_keys=True,
        )


def _normalize_answers(
    answers: Mapping[str, Sequence[str]] | JsonPayload,
) -> JsonPayload:
    payload = _as_mapping(answers, "answers")
    normalized: dict[str, list[str]] = {}
    for question_id, values in payload.items():
        _require_text(question_id, "question_id")
        if isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence):
            raise TypeError("each answer must be a sequence of strings")
        values_tuple = tuple(values)
        if not values_tuple:
            raise ValueError("each question must have at least one answer")
        if not all(isinstance(value, str) and value.strip() for value in values_tuple):
            raise ValueError("answers must be non-empty strings")
        if len(set(values_tuple)) != len(values_tuple):
            raise ValueError("answers must not contain duplicate values")
        normalized[question_id] = list(values_tuple)
    return JsonPayload(normalized)


@dataclass(frozen=True, slots=True)
class PauseRequest(_JsonModel):
    pause_id: str
    run_id: str
    turn_id: str
    kind: PauseKind
    reason: PauseReason
    iteration: int
    created_at: str
    tool_call_id: str | None = None
    user_input_request: UserInputRequest | None = None

    def __post_init__(self) -> None:
        for field_name in ("pause_id", "run_id", "turn_id", "created_at"):
            _require_text(getattr(self, field_name), field_name)
        kind = _coerce_enum(PauseKind, self.kind, "pause kind")
        reason = _coerce_enum(PauseReason, self.reason, "pause reason")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "reason", reason)
        _require_positive_int(self.iteration, "iteration")
        valid_reason = {
            PauseKind.USER_REQUESTED: {PauseReason.USER_REQUESTED},
            PauseKind.USER_INPUT_REQUIRED: {PauseReason.USER_INPUT_REQUIRED},
            PauseKind.PROVIDER_UNAVAILABLE: {
                PauseReason.NETWORK_ERROR,
                PauseReason.RATE_LIMITED,
            },
        }
        if reason not in valid_reason[kind]:
            raise ValueError(f"pause kind {kind.value} does not allow reason {reason.value}")

        if self.tool_call_id is not None:
            _require_text(self.tool_call_id, "tool_call_id")
        if self.user_input_request is not None and not isinstance(
            self.user_input_request, UserInputRequest
        ):
            raise TypeError("user_input_request must be UserInputRequest or None")
        if kind is PauseKind.USER_INPUT_REQUIRED:
            if self.tool_call_id is None or self.user_input_request is None:
                raise ValueError("user_input_required pause requires tool_call_id and questions")
        elif self.tool_call_id is not None or self.user_input_request is not None:
            raise ValueError("tool input fields are only valid for user_input_required")

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "pause_id": self.pause_id,
            "run_id": self.run_id,
            "turn_id": self.turn_id,
            "kind": self.kind.value,
            "reason": self.reason.value,
            "iteration": self.iteration,
            "created_at": self.created_at,
        }
        if self.kind is PauseKind.USER_INPUT_REQUIRED:
            payload["tool_call_id"] = self.tool_call_id
            payload["user_input_request"] = self.user_input_request.to_dict()  # type: ignore[union-attr]
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> PauseRequest:
        payload = _as_mapping(value, "pause_request")
        kind = _coerce_enum(PauseKind, _required(payload, "kind"), "pause kind")
        base = {"pause_id", "run_id", "turn_id", "kind", "reason", "iteration", "created_at"}
        if kind is PauseKind.USER_INPUT_REQUIRED:
            _expect_keys(payload, base | {"tool_call_id", "user_input_request"})
            tool_call_id = _required(payload, "tool_call_id")  # type: ignore[assignment]
            user_input_request = UserInputRequest.from_dict(
                _required(payload, "user_input_request")  # type: ignore[arg-type]
            )
        else:
            _expect_keys(payload, base)
            tool_call_id = None
            user_input_request = None
        return cls(
            pause_id=_required(payload, "pause_id"),  # type: ignore[arg-type]
            run_id=_required(payload, "run_id"),  # type: ignore[arg-type]
            turn_id=_required(payload, "turn_id"),  # type: ignore[arg-type]
            kind=kind,
            reason=_required(payload, "reason"),  # type: ignore[arg-type]
            iteration=_required(payload, "iteration"),  # type: ignore[arg-type]
            created_at=_required(payload, "created_at"),  # type: ignore[arg-type]
            tool_call_id=tool_call_id,  # type: ignore[arg-type]
            user_input_request=user_input_request,
        )

    @classmethod
    def from_json(cls, value: str) -> PauseRequest:
        return cls.from_dict(_json_object(value, "PauseRequest"))

    def validate_response(self, response: PauseResponse) -> None:
        if not isinstance(response, _PauseResponse):
            raise TypeError("response must be a PauseResponse")
        if response.pause_id != self.pause_id or response.run_id != self.run_id or response.turn_id != self.turn_id:
            raise ValueError("response does not match the pending pause IDs")
        if response.pause_kind is not self.kind:
            raise ValueError("response type does not match the pending pause kind")
        if isinstance(response, UserInputResponse):
            if response.tool_call_id != self.tool_call_id:
                raise ValueError("response does not match the pending tool call")
            assert self.user_input_request is not None
            self.user_input_request.validate_answers(response.answers)


@dataclass(frozen=True, slots=True)
class _PauseResponse(_JsonModel):
    response_type: ClassVar[str]
    pause_kind: ClassVar[PauseKind]

    pause_id: str
    run_id: str
    turn_id: str

    def __post_init__(self) -> None:
        _require_text(self.pause_id, "pause_id")
        _require_text(self.run_id, "run_id")
        _require_text(self.turn_id, "turn_id")

    @property
    def kind(self) -> PauseKind:
        return self.pause_kind

    def to_dict(self) -> dict[str, object]:
        return {
            "type": self.response_type,
            "pause_id": self.pause_id,
            "run_id": self.run_id,
            "turn_id": self.turn_id,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)


@dataclass(frozen=True, slots=True)
class ResumeTurnResponse(_PauseResponse):
    response_type: ClassVar[str] = "resume_turn"
    pause_kind: ClassVar[PauseKind] = PauseKind.USER_REQUESTED

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> ResumeTurnResponse:
        payload = _as_mapping(value, "resume response")
        _expect_keys(payload, {"type", "pause_id", "run_id", "turn_id"})
        if payload["type"] != cls.response_type:
            raise ValueError("response type is not resume_turn")
        return cls(
            _required(payload, "pause_id"),  # type: ignore[arg-type]
            _required(payload, "run_id"),  # type: ignore[arg-type]
            _required(payload, "turn_id"),  # type: ignore[arg-type]
        )

    @classmethod
    def from_json(cls, value: str) -> ResumeTurnResponse:
        return cls.from_dict(_json_object(value, "ResumeTurnResponse"))


@dataclass(frozen=True, slots=True)
class UserInputResponse(_PauseResponse):
    response_type: ClassVar[str] = "user_input"
    pause_kind: ClassVar[PauseKind] = PauseKind.USER_INPUT_REQUIRED

    tool_call_id: str
    answers: JsonPayload

    def __post_init__(self) -> None:
        _PauseResponse.__post_init__(self)
        _require_text(self.tool_call_id, "tool_call_id")
        object.__setattr__(self, "answers", _normalize_answers(self.answers))

    def to_dict(self) -> dict[str, object]:
        return {
            **_PauseResponse.to_dict(self),
            "tool_call_id": self.tool_call_id,
            "answers": {key: list(values) for key, values in self.answers.items()},
        }

    def answers_json(self, request: UserInputRequest) -> str:
        return request.answers_to_json(self.answers)

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> UserInputResponse:
        payload = _as_mapping(value, "user input response")
        _expect_keys(payload, {"type", "pause_id", "run_id", "turn_id", "tool_call_id", "answers"})
        if payload["type"] != cls.response_type:
            raise ValueError("response type is not user_input")
        return cls(
            _required(payload, "pause_id"),  # type: ignore[arg-type]
            _required(payload, "run_id"),  # type: ignore[arg-type]
            _required(payload, "turn_id"),  # type: ignore[arg-type]
            _required(payload, "tool_call_id"),  # type: ignore[arg-type]
            _required(payload, "answers"),  # type: ignore[arg-type]
        )

    @classmethod
    def from_json(cls, value: str) -> UserInputResponse:
        return cls.from_dict(_json_object(value, "UserInputResponse"))


@dataclass(frozen=True, slots=True)
class RetryProviderResponse(_PauseResponse):
    response_type: ClassVar[str] = "retry_provider"
    pause_kind: ClassVar[PauseKind] = PauseKind.PROVIDER_UNAVAILABLE

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> RetryProviderResponse:
        payload = _as_mapping(value, "retry response")
        _expect_keys(payload, {"type", "pause_id", "run_id", "turn_id"})
        if payload["type"] != cls.response_type:
            raise ValueError("response type is not retry_provider")
        return cls(
            _required(payload, "pause_id"),  # type: ignore[arg-type]
            _required(payload, "run_id"),  # type: ignore[arg-type]
            _required(payload, "turn_id"),  # type: ignore[arg-type]
        )

    @classmethod
    def from_json(cls, value: str) -> RetryProviderResponse:
        return cls.from_dict(_json_object(value, "RetryProviderResponse"))


PauseResponse: TypeAlias = ResumeTurnResponse | UserInputResponse | RetryProviderResponse


def pause_response_from_dict(value: Mapping[str, object]) -> PauseResponse:
    payload = _as_mapping(value, "pause response")
    response_type = payload.get("type")
    if response_type == ResumeTurnResponse.response_type:
        return ResumeTurnResponse.from_dict(payload)
    if response_type == UserInputResponse.response_type:
        return UserInputResponse.from_dict(payload)
    if response_type == RetryProviderResponse.response_type:
        return RetryProviderResponse.from_dict(payload)
    raise ValueError(f"unknown pause response type: {response_type!r}")


def pause_response_from_json(value: str) -> PauseResponse:
    parsed = json.loads(value)
    if not isinstance(parsed, Mapping):
        raise TypeError("PauseResponse JSON must contain an object")
    return pause_response_from_dict(parsed)


_OPTION_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "label": {"type": "string", "minLength": 1},
        "description": {"type": "string", "minLength": 1},
    },
    "required": ["label", "description"],
    "additionalProperties": False,
}

_SELECT_QUESTION_SCHEMA: dict[str, object] = {
    "type": "array",
    "minItems": 2,
    "maxItems": 6,
    "items": _OPTION_SCHEMA,
    "uniqueItems": True,
}

_QUESTION_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "question_id": {"type": "string", "minLength": 1},
        "header": {"type": "string", "minLength": 1},
        "question": {"type": "string", "minLength": 1},
        "kind": {"enum": [item.value for item in QuestionKind]},
        "options": _SELECT_QUESTION_SCHEMA,
        "allow_other": {"type": "boolean"},
    },
    "required": ["question_id", "header", "question", "kind"],
    "additionalProperties": False,
    "allOf": [
        {
            "if": {"properties": {"kind": {"const": QuestionKind.TEXT.value}}},
            "then": {
                "not": {
                    "anyOf": [
                        {"required": ["options"]},
                        {"required": ["allow_other"]},
                    ]
                }
            },
        },
        {
            "if": {
                "properties": {
                    "kind": {
                        "enum": [QuestionKind.SINGLE_SELECT.value, QuestionKind.MULTI_SELECT.value]
                    }
                }
            },
            "then": {"required": ["options"]},
        },
    ],
}


ASK_USER_TOOL_DEFINITION = ToolDefinition(
    name="AskUserQuestion",
    description=(
        "Ask for facts or choices that are required to continue. Use this only "
        "when the answer cannot be safely inferred; it must not replace Permission approval."
    ),
    parameters={
        "type": "object",
        "properties": {
            "questions": {
                "type": "array",
                "minItems": 1,
                "maxItems": 4,
                "items": _QUESTION_SCHEMA,
                "uniqueItems": True,
            }
        },
        "required": ["questions"],
        "additionalProperties": False,
    },
)


__all__ = [
    "ASK_USER_TOOL_DEFINITION",
    "PauseKind",
    "PauseReason",
    "PauseRequest",
    "PauseResponse",
    "QuestionKind",
    "QuestionOption",
    "RetryProviderResponse",
    "ResumeTurnResponse",
    "UserInputRequest",
    "UserInputResponse",
    "UserQuestion",
    "pause_response_from_dict",
    "pause_response_from_json",
]
