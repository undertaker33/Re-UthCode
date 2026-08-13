"""Strict, versioned data contracts for the private Eval tool.

The models in this module are deliberately independent from ``uthcode.core``.
They are the on-disk boundary for task definitions and attempt artifacts, not
another representation of the Agent runtime state.
"""

from __future__ import annotations

import json
import math
import re
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath
from types import MappingProxyType


class ContractError(ValueError):
    """Raised when an Eval payload violates its versioned contract."""


CURRENT_SCHEMA_VERSION = 1
SCHEMA_VERSION = CURRENT_SCHEMA_VERSION
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_DIMENSIONS = {
    "correctness",
    "context",
    "exploration",
    "efficiency",
    "stability",
    "safety",
}


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ContractError(f"{field}: expected an object")
    if any(not isinstance(key, str) for key in value):
        raise ContractError(f"{field}: object keys must be strings")
    return value  # type: ignore[return-value]


def _keys(
    value: Mapping[str, object],
    field: str,
    *,
    required: set[str],
    optional: set[str] = set(),
) -> None:
    missing = sorted(required - set(value))
    if missing:
        raise ContractError(f"{field}: missing fields")
    unknown = sorted(set(value) - required - optional)
    if unknown:
        raise ContractError(f"{field}: unknown fields")


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{field}: must be a non-empty string")
    if "\x00" in value:
        raise ContractError(f"{field}: must not contain null bytes")
    return value


def _identifier(value: object, field: str) -> str:
    value = _text(value, field)
    if _IDENTIFIER.fullmatch(value) is None or value in {".", ".."}:
        raise ContractError(f"{field}: must be a safe identifier")
    return value


def _relative_path(value: object, field: str) -> str:
    value = _text(value, field).replace("\\", "/")
    path = PurePosixPath(value)
    normalized = "/".join(path.parts)
    if (
        value.startswith("/")
        or value.startswith("//")
        or re.match(r"^[A-Za-z]:", value)
        or any(part in {"", ".", ".."} for part in path.parts)
        or ":" in value
        or normalized != value
    ):
        raise ContractError(f"{field}: must be a normalized relative path")
    return normalized


def _enum(value: object, enum_type: type[Enum], field: str) -> Enum:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise ContractError(f"{field}: unsupported value") from exc


def _sequence(value: object, field: str) -> tuple[object, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise ContractError(f"{field}: expected an array")
    return tuple(value)


def _positive_int(value: object, field: str, *, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ContractError(f"{field}: must be a positive integer")
    if maximum is not None and value > maximum:
        raise ContractError(f"{field}: exceeds the allowed bound")
    return value


def _non_negative_number(value: object, field: str, *, maximum: float | None = None) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractError(f"{field}: must be a number")
    if not math.isfinite(float(value)) or value < 0:
        raise ContractError(f"{field}: must be finite and non-negative")
    if maximum is not None and value > maximum:
        raise ContractError(f"{field}: exceeds the allowed bound")
    return value


def _json_value(value: object, field: str = "value") -> object:
    if value is None or isinstance(value, (str, bool, int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            raise ContractError(f"{field}: must be JSON-safe")
        return value
    if isinstance(value, Mapping):
        return {
            _text(key, f"{field} key"): _json_value(item, f"{field} value")
            for key, item in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_value(item, field) for item in value]
    raise ContractError(f"{field}: must be JSON-safe")


def _freeze_json(value: object, field: str = "value") -> object:
    """Copy JSON-safe data into immutable containers."""

    if value is None or isinstance(value, (str, bool, int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            raise ContractError(f"{field}: must be JSON-safe")
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, object] = {}
        for key, item in value.items():
            frozen[_text(key, f"{field} key")] = _freeze_json(item, f"{field} value")
        return MappingProxyType(frozen)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(_freeze_json(item, field) for item in value)
    raise ContractError(f"{field}: must be JSON-safe")


def _thaw_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _unique_ids(items: Sequence[object], field: str) -> None:
    ids = [item for item in items if isinstance(item, str)]
    if len(ids) != len(set(ids)):
        raise ContractError(f"{field}: duplicate identifiers")


def _parse_json_object(value: str, field: str) -> Mapping[str, object]:
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError) as exc:
        raise ContractError(f"{field}: invalid JSON") from exc
    return _mapping(parsed, field)


def _schema_version(value: object, field: str = "schema_version") -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ContractError(f"{field}: unsupported schema version")
    if value != CURRENT_SCHEMA_VERSION:
        raise ContractError(f"{field}: unsupported schema version")
    return value


class BehaviorMode(str, Enum):
    DEFAULT = "default"
    PLAN = "plan"


class InteractionKind(str, Enum):
    ASK_USER = "ask_user"
    PLAN_REVIEW = "plan_review"


class PermissionRuleKind(str, Enum):
    POLICY = "policy"


class PermissionDecision(str, Enum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


class PermissionEffect(str, Enum):
    READ = "read"
    WRITE = "write"
    DESTRUCTIVE = "destructive"
    EXTERNAL = "external"
    UNKNOWN = "unknown"


class PermissionScope(str, Enum):
    INSIDE = "inside"
    OUTSIDE = "outside"
    UNKNOWN = "unknown"


class CheckKind(str, Enum):
    HARD = "hard"
    PARTIAL = "partial"
    FORBIDDEN = "forbidden"


class MetricStatus(str, Enum):
    AVAILABLE = "available"
    NOT_AVAILABLE = "not_available"


class FinishCategory(str, Enum):
    SUCCESS = "success"
    AGENT_FAILURE = "agent_failure"
    BLOCKED_BY_PERMISSION = "blocked_by_permission"
    UNDECLARED_INTERACTION = "undeclared_interaction"
    TIMEOUT = "timeout"
    VERIFIER_ERROR = "verifier_error"
    RUNNER_ERROR = "runner_error"


@dataclass(frozen=True, slots=True)
class RequiredEvidence:
    id: str
    path: str
    fact: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _identifier(self.id, "required_evidence.id"))
        object.__setattr__(self, "path", _relative_path(self.path, "required_evidence.path"))
        object.__setattr__(self, "fact", _text(self.fact, "required_evidence.fact"))

    @classmethod
    def from_mapping(cls, value: object) -> RequiredEvidence:
        payload = _mapping(value, "required_evidence")
        _keys(payload, "required_evidence", required={"id", "path", "fact"})
        return cls(payload["id"], payload["path"], payload["fact"])  # type: ignore[arg-type]

    def to_dict(self) -> dict[str, object]:
        return {"id": self.id, "path": self.path, "fact": self.fact}


@dataclass(frozen=True, slots=True)
class InteractionSpec:
    id: str
    kind: InteractionKind
    response: dict[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _identifier(self.id, "interactions.id"))
        kind = _enum(self.kind, InteractionKind, "interactions.kind")
        object.__setattr__(self, "kind", kind)
        response = _mapping(self.response, "interactions.response")
        normalized = _freeze_json(response, "interactions.response")
        if not isinstance(normalized, Mapping):
            raise ContractError("interactions.response: expected an object")
        self._validate_response(kind, normalized)
        object.__setattr__(self, "response", normalized)

    @staticmethod
    def _validate_response(kind: InteractionKind, response: Mapping[str, object]) -> None:
        if kind is InteractionKind.ASK_USER:
            if set(response) != {"answers"}:
                raise ContractError("interactions.response: ask_user requires answers")
            answers = _mapping(response["answers"], "interactions.response.answers")
            for question_id, answer in answers.items():
                _identifier(question_id, "interactions.response.answers key")
                values = _sequence(answer, "interactions.response.answers")
                if not values or any(not isinstance(item, str) or not item.strip() for item in values):
                    raise ContractError("interactions.response.answers: invalid answer")
            return
        if set(response) - {"choice", "feedback"} or "choice" not in response:
            raise ContractError("interactions.response: invalid plan_review response")
        choice = response["choice"]
        if choice not in {"approve", "revise"}:
            raise ContractError("interactions.response.choice: unsupported value")
        if choice == "revise":
            if not isinstance(response.get("feedback"), str) or not response["feedback"].strip():
                raise ContractError("interactions.response.feedback: required for revision")
        elif "feedback" in response:
            raise ContractError("interactions.response: approve must not contain feedback")

    @classmethod
    def from_mapping(cls, value: object) -> InteractionSpec:
        payload = _mapping(value, "interactions")
        _keys(payload, "interactions", required={"id", "kind", "response"})
        return cls(
            payload["id"],
            _enum(payload["kind"], InteractionKind, "interactions.kind"),  # type: ignore[arg-type]
            dict(_mapping(payload["response"], "interactions.response")),
        )

    def to_dict(self) -> dict[str, object]:
        return {"id": self.id, "kind": self.kind.value, "response": _thaw_json(self.response)}


@dataclass(frozen=True, slots=True)
class PermissionRule:
    id: str
    kind: PermissionRuleKind
    decision: PermissionDecision
    tool: str
    action: str
    effect: PermissionEffect
    scope: PermissionScope
    resource: str
    resource_prefix: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _identifier(self.id, "permission_rules.id"))
        object.__setattr__(self, "kind", _enum(self.kind, PermissionRuleKind, "permission_rules.kind"))
        object.__setattr__(self, "decision", _enum(self.decision, PermissionDecision, "permission_rules.decision"))
        for field in ("tool", "action"):
            value = _text(getattr(self, field), f"permission_rules.{field}")
            if "*" in value or "?" in value:
                raise ContractError("permission rule: wildcard matchers are not allowed")
            object.__setattr__(self, field, value)
        resource = _text(self.resource, "permission_rules.resource")
        if "*" in resource or "?" in resource:
            raise ContractError("permission rule: wildcard matchers are not allowed")
        object.__setattr__(
            self,
            "resource",
            _relative_path(resource, "permission_rules.resource"),
        )
        object.__setattr__(self, "effect", _enum(self.effect, PermissionEffect, "permission_rules.effect"))
        object.__setattr__(self, "scope", _enum(self.scope, PermissionScope, "permission_rules.scope"))
        if not isinstance(self.resource_prefix, bool):
            raise ContractError("permission_rules.resource_prefix: must be boolean")
        if self.resource_prefix:
            raise ContractError("permission rule: broad resource prefixes are not allowed")
        if self.decision is PermissionDecision.ALLOW and (
            self.scope is not PermissionScope.INSIDE
            or self.effect not in {PermissionEffect.READ, PermissionEffect.WRITE}
        ):
            raise ContractError("permission rule: allow must be bounded to inside read/write")

    @classmethod
    def from_mapping(cls, value: object) -> PermissionRule:
        payload = _mapping(value, "permission_rules")
        _keys(
            payload,
            "permission_rules",
            required={"id", "kind", "decision", "tool", "action", "effect", "scope", "resource"},
            optional={"resource_prefix"},
        )
        return cls(
            payload["id"],
            payload["kind"],  # type: ignore[arg-type]
            payload["decision"],  # type: ignore[arg-type]
            payload["tool"],  # type: ignore[arg-type]
            payload["action"],  # type: ignore[arg-type]
            payload["effect"],  # type: ignore[arg-type]
            payload["scope"],  # type: ignore[arg-type]
            payload["resource"],  # type: ignore[arg-type]
            payload.get("resource_prefix", False),  # type: ignore[arg-type]
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "kind": self.kind.value,
            "decision": self.decision.value,
            "tool": self.tool,
            "action": self.action,
            "effect": self.effect.value,
            "scope": self.scope.value,
            "resource": self.resource,
            "resource_prefix": self.resource_prefix,
        }


@dataclass(frozen=True, slots=True)
class ScoringSpec:
    hard: int | float
    partial: int | float
    dimensions: tuple[str, ...]
    dimension_weights: tuple[tuple[str, int | float], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "hard", _non_negative_number(self.hard, "scoring.hard", maximum=100))
        object.__setattr__(self, "partial", _non_negative_number(self.partial, "scoring.partial", maximum=100))
        dimensions = tuple(_identifier(item, "scoring.dimensions") for item in self.dimensions)
        if not dimensions or len(set(dimensions)) != len(dimensions):
            raise ContractError("scoring.dimensions: must contain unique dimensions")
        if not set(dimensions) <= _DIMENSIONS:
            raise ContractError("scoring.dimensions: unsupported dimension")
        weights: list[tuple[str, int | float]] = []
        for key, value in self.dimension_weights:
            if key not in dimensions:
                raise ContractError("scoring.dimension_weights: unknown dimension")
            weights.append((key, _non_negative_number(value, "scoring.dimension_weights", maximum=100)))
        if len({key for key, _ in weights}) != len(weights):
            raise ContractError("scoring.dimension_weights: duplicate dimension")
        object.__setattr__(self, "dimensions", dimensions)
        object.__setattr__(self, "dimension_weights", tuple(weights))

    @classmethod
    def from_mapping(cls, value: object) -> ScoringSpec:
        payload = _mapping(value, "scoring")
        _keys(payload, "scoring", required={"hard", "partial", "dimensions"})
        dimensions_value = payload["dimensions"]
        weights: tuple[tuple[str, int | float], ...] = ()
        if isinstance(dimensions_value, Mapping):
            items = []
            for key, weight in dimensions_value.items():
                items.append((_identifier(key, "scoring.dimensions"), _non_negative_number(weight, "scoring.dimensions", maximum=100)))
            dimensions = tuple(key for key, _ in items)
            weights = tuple(items)
        else:
            dimensions = tuple(_identifier(item, "scoring.dimensions") for item in _sequence(dimensions_value, "scoring.dimensions"))
        return cls(payload["hard"], payload["partial"], dimensions, weights)  # type: ignore[arg-type]

    def to_dict(self) -> dict[str, object]:
        dimensions: object = list(self.dimensions)
        if self.dimension_weights:
            dimensions = {key: value for key, value in self.dimension_weights}
        return {"hard": self.hard, "partial": self.partial, "dimensions": dimensions}


@dataclass(frozen=True, slots=True)
class TaskDefinition:
    schema_version: int
    task_id: str
    task_version: str
    instruction_path: str
    fixture_path: str
    verifier_path: str
    behavior_mode: BehaviorMode
    timeout_seconds: int
    required_evidence: tuple[RequiredEvidence, ...]
    interactions: tuple[InteractionSpec, ...]
    permission_rules: tuple[PermissionRule, ...]
    scoring: ScoringSpec
    attempts: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "schema_version", _schema_version(self.schema_version))
        object.__setattr__(self, "task_id", _identifier(self.task_id, "task_id"))
        object.__setattr__(self, "task_version", _text(self.task_version, "task_version"))
        for field in ("instruction_path", "fixture_path", "verifier_path"):
            object.__setattr__(self, field, _relative_path(getattr(self, field), field))
        object.__setattr__(self, "behavior_mode", _enum(self.behavior_mode, BehaviorMode, "behavior_mode"))
        object.__setattr__(self, "timeout_seconds", _positive_int(self.timeout_seconds, "timeout_seconds", maximum=86400))
        object.__setattr__(self, "attempts", _positive_int(self.attempts, "attempts", maximum=1000))
        evidence = tuple(self.required_evidence)
        interactions = tuple(self.interactions)
        rules = tuple(self.permission_rules)
        if not all(isinstance(item, RequiredEvidence) for item in evidence):
            raise ContractError("required_evidence: invalid item")
        if not all(isinstance(item, InteractionSpec) for item in interactions):
            raise ContractError("interactions: invalid item")
        if not all(isinstance(item, PermissionRule) for item in rules):
            raise ContractError("permission_rules: invalid item")
        for items, field in ((evidence, "required_evidence"), (interactions, "interactions"), (rules, "permission_rules")):
            ids = [item.id for item in items]
            _unique_ids(ids, field)
        if not isinstance(self.scoring, ScoringSpec):
            raise ContractError("scoring: invalid value")
        object.__setattr__(self, "required_evidence", evidence)
        object.__setattr__(self, "interactions", interactions)
        object.__setattr__(self, "permission_rules", rules)

    @classmethod
    def from_mapping(cls, value: object) -> TaskDefinition:
        payload = _mapping(value, "task")
        _keys(
            payload,
            "task",
            required={
                "schema_version", "task_id", "task_version", "instruction_path",
                "fixture_path", "verifier_path", "behavior_mode", "timeout_seconds",
                "required_evidence", "interactions", "permission_rules", "scoring",
            },
            optional={"attempts"},
        )
        evidence = tuple(RequiredEvidence.from_mapping(item) for item in _sequence(payload["required_evidence"], "required_evidence"))
        interactions = tuple(InteractionSpec.from_mapping(item) for item in _sequence(payload["interactions"], "interactions"))
        rules = tuple(PermissionRule.from_mapping(item) for item in _sequence(payload["permission_rules"], "permission_rules"))
        return cls(
            payload["schema_version"],  # type: ignore[arg-type]
            payload["task_id"],  # type: ignore[arg-type]
            payload["task_version"],  # type: ignore[arg-type]
            payload["instruction_path"],  # type: ignore[arg-type]
            payload["fixture_path"],  # type: ignore[arg-type]
            payload["verifier_path"],  # type: ignore[arg-type]
            payload["behavior_mode"],  # type: ignore[arg-type]
            payload["timeout_seconds"],  # type: ignore[arg-type]
            evidence,
            interactions,
            rules,
            ScoringSpec.from_mapping(payload["scoring"]),
            payload.get("attempts", 1),  # type: ignore[arg-type]
        )

    from_dict = from_mapping

    @classmethod
    def from_json(cls, value: str) -> TaskDefinition:
        return cls.from_mapping(_parse_json_object(value, "TaskDefinition"))

    @classmethod
    def from_toml(cls, path: Path) -> TaskDefinition:
        try:
            with path.open("rb") as stream:
                payload = tomllib.load(stream)
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise ContractError("TaskDefinition TOML: unable to parse") from exc
        return cls.from_mapping(payload)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "task_id": self.task_id,
            "task_version": self.task_version,
            "instruction_path": self.instruction_path,
            "fixture_path": self.fixture_path,
            "verifier_path": self.verifier_path,
            "behavior_mode": self.behavior_mode.value,
            "timeout_seconds": self.timeout_seconds,
            "attempts": self.attempts,
            "required_evidence": [item.to_dict() for item in self.required_evidence],
            "interactions": [item.to_dict() for item in self.interactions],
            "permission_rules": [item.to_dict() for item in self.permission_rules],
            "scoring": self.scoring.to_dict(),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True, slots=True)
class VerifierCheck:
    check_id: str
    kind: CheckKind
    passed: bool
    points: int | float
    max_points: int | float
    message: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "check_id", _identifier(self.check_id, "checks.check_id"))
        object.__setattr__(self, "kind", _enum(self.kind, CheckKind, "checks.kind"))
        if not isinstance(self.passed, bool):
            raise ContractError("checks.passed: must be boolean")
        object.__setattr__(self, "max_points", _non_negative_number(self.max_points, "checks.max_points"))
        if self.max_points <= 0:
            raise ContractError("checks.max_points: must be positive")
        object.__setattr__(self, "points", _non_negative_number(self.points, "checks.points"))
        if self.points > self.max_points:
            raise ContractError("checks.points: must not exceed max_points")
        object.__setattr__(self, "message", _text(self.message, "checks.message"))

    @classmethod
    def from_mapping(cls, value: object) -> VerifierCheck:
        payload = _mapping(value, "checks")
        _keys(payload, "checks", required={"check_id", "kind", "passed", "points", "max_points", "message"})
        return cls(
            payload["check_id"], payload["kind"], payload["passed"], payload["points"], payload["max_points"], payload["message"]  # type: ignore[arg-type]
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "check_id": self.check_id,
            "kind": self.kind.value,
            "passed": self.passed,
            "points": self.points,
            "max_points": self.max_points,
            "message": self.message,
        }


@dataclass(frozen=True, slots=True)
class VerifierResult:
    schema_version: int
    checks: tuple[VerifierCheck, ...]
    correctness_score: int | float
    success: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "schema_version", _schema_version(self.schema_version))
        checks = tuple(self.checks)
        if not all(isinstance(item, VerifierCheck) for item in checks):
            raise ContractError("checks: invalid item")
        ids = [item.check_id for item in checks]
        if len(ids) != len(set(ids)):
            raise ContractError("checks: duplicate identifiers")
        object.__setattr__(self, "checks", checks)
        object.__setattr__(self, "correctness_score", _non_negative_number(self.correctness_score, "correctness_score", maximum=100))
        if not isinstance(self.success, bool):
            raise ContractError("success: must be boolean")
        expected = all(item.passed for item in checks if item.kind in {CheckKind.HARD, CheckKind.FORBIDDEN})
        if self.success != expected:
            raise ContractError("success: inconsistent with hard and forbidden checks")

    @classmethod
    def from_mapping(cls, value: object) -> VerifierResult:
        payload = _mapping(value, "VerifierResult")
        _keys(payload, "VerifierResult", required={"schema_version", "checks", "correctness_score", "success"})
        checks = tuple(VerifierCheck.from_mapping(item) for item in _sequence(payload["checks"], "checks"))
        return cls(payload["schema_version"], checks, payload["correctness_score"], payload["success"])  # type: ignore[arg-type]

    from_dict = from_mapping

    @classmethod
    def from_json(cls, value: str) -> VerifierResult:
        return cls.from_mapping(_parse_json_object(value, "VerifierResult"))

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "checks": [item.to_dict() for item in self.checks],
            "correctness_score": self.correctness_score,
            "success": self.success,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True, slots=True)
class MetricValue:
    status: MetricStatus
    value: int | float | None = None
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        status = _enum(self.status, MetricStatus, "metric.status")
        object.__setattr__(self, "status", status)
        if status is MetricStatus.NOT_AVAILABLE:
            if self.value is not None:
                raise ContractError("metric.value: not_available metrics must not have a value")
        else:
            if self.value is None:
                raise ContractError("metric.value: available metrics require a value")
            object.__setattr__(self, "value", _non_negative_number(self.value, "metric.value"))
        refs = tuple(
            _text(item, "metric.evidence_refs")
            for item in _sequence(self.evidence_refs, "metric.evidence_refs")
        )
        if len(refs) != len(set(refs)):
            raise ContractError("metric.evidence_refs: duplicate references")
        object.__setattr__(self, "evidence_refs", refs)

    @classmethod
    def from_mapping(cls, value: object) -> MetricValue:
        payload = _mapping(value, "metric")
        _keys(payload, "metric", required={"status", "value"}, optional={"evidence_refs"})
        return cls(payload["status"], payload["value"], tuple(payload.get("evidence_refs", ())))  # type: ignore[arg-type]

    @classmethod
    def from_json(cls, value: str) -> MetricValue:
        return cls.from_mapping(_parse_json_object(value, "MetricValue"))

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "value": self.value,
            "evidence_refs": list(self.evidence_refs),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True, slots=True)
class AttemptRecord:
    schema_version: int
    experiment_id: str
    task_id: str
    attempt_id: str
    fingerprints: dict[str, str]
    paths: dict[str, str]
    timestamps: dict[str, str]
    duration_seconds: int | float
    finish_category: FinishCategory
    turn_result: dict[str, object] | None
    verifier_result: VerifierResult | None
    metrics: dict[str, MetricValue]
    artifact_manifest: dict[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(self, "schema_version", _schema_version(self.schema_version))
        for field in ("experiment_id", "task_id", "attempt_id"):
            object.__setattr__(self, field, _identifier(getattr(self, field), field))
        object.__setattr__(self, "fingerprints", MappingProxyType(self._string_mapping(self.fingerprints, "fingerprints")))
        object.__setattr__(self, "paths", MappingProxyType(self._string_mapping(self.paths, "paths")))
        object.__setattr__(self, "timestamps", MappingProxyType(self._string_mapping(self.timestamps, "timestamps")))
        object.__setattr__(self, "duration_seconds", _non_negative_number(self.duration_seconds, "duration_seconds"))
        object.__setattr__(self, "finish_category", _enum(self.finish_category, FinishCategory, "finish_category"))
        if self.turn_result is not None:
            normalized = _freeze_json(self.turn_result, "turn_result")
            if not isinstance(normalized, Mapping):
                raise ContractError("turn_result: expected an object")
            object.__setattr__(self, "turn_result", normalized)
        if self.verifier_result is not None and not isinstance(self.verifier_result, VerifierResult):
            raise ContractError("verifier_result: invalid value")
        metrics = {}
        for key, value in _mapping(self.metrics, "metrics").items():
            metrics[_identifier(key, "metrics key")] = value if isinstance(value, MetricValue) else MetricValue.from_mapping(value)
        object.__setattr__(self, "metrics", MappingProxyType(metrics))
        manifest = _freeze_json(self.artifact_manifest, "artifact_manifest")
        if not isinstance(manifest, Mapping):
            raise ContractError("artifact_manifest: expected an object")
        object.__setattr__(self, "artifact_manifest", manifest)

    @staticmethod
    def _string_mapping(value: object, field: str) -> dict[str, str]:
        payload = _mapping(value, field)
        result: dict[str, str] = {}
        for key, item in payload.items():
            result[_text(key, f"{field} key")] = _text(item, f"{field} value")
        return result

    @classmethod
    def from_mapping(cls, value: object) -> AttemptRecord:
        payload = _mapping(value, "AttemptRecord")
        _keys(
            payload,
            "AttemptRecord",
            required={
                "schema_version", "experiment_id", "task_id", "attempt_id", "fingerprints",
                "paths", "timestamps", "duration_seconds", "finish_category", "turn_result",
                "verifier_result", "metrics", "artifact_manifest",
            },
        )
        verifier_value = payload["verifier_result"]
        verifier = None if verifier_value is None else VerifierResult.from_mapping(verifier_value)
        return cls(
            payload["schema_version"], payload["experiment_id"], payload["task_id"], payload["attempt_id"],
            dict(_mapping(payload["fingerprints"], "fingerprints")),
            dict(_mapping(payload["paths"], "paths")),
            dict(_mapping(payload["timestamps"], "timestamps")),
            payload["duration_seconds"], payload["finish_category"],
            None if payload["turn_result"] is None else dict(_mapping(payload["turn_result"], "turn_result")),
            verifier,
            {key: MetricValue.from_mapping(item) for key, item in _mapping(payload["metrics"], "metrics").items()},
            dict(_mapping(payload["artifact_manifest"], "artifact_manifest")),
        )  # type: ignore[arg-type]

    from_dict = from_mapping

    @classmethod
    def from_json(cls, value: str) -> AttemptRecord:
        return cls.from_mapping(_parse_json_object(value, "AttemptRecord"))

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "experiment_id": self.experiment_id,
            "task_id": self.task_id,
            "attempt_id": self.attempt_id,
            "fingerprints": _thaw_json(self.fingerprints),
            "paths": _thaw_json(self.paths),
            "timestamps": _thaw_json(self.timestamps),
            "duration_seconds": self.duration_seconds,
            "finish_category": self.finish_category.value,
            "turn_result": None if self.turn_result is None else _thaw_json(self.turn_result),
            "verifier_result": None if self.verifier_result is None else self.verifier_result.to_dict(),
            "metrics": {key: value.to_dict() for key, value in self.metrics.items()},
            "artifact_manifest": _thaw_json(self.artifact_manifest),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
