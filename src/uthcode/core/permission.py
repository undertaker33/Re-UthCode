"""Provider-independent permission facts and three-layer evaluation."""

from __future__ import annotations

import json
import ntpath
import posixpath
import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum


class PermissionMode(str, Enum):
    """The permission mode selected for the current AgentRun."""

    DEFAULT = "default"
    AUTO = "auto"
    FULL_ACCESS = "full_access"


class Effect(str, Enum):
    """The trusted side-effect class of one normalized ToolCall."""

    READ = "read"
    WRITE = "write"
    DESTRUCTIVE = "destructive"
    EXTERNAL = "external"
    UNKNOWN = "unknown"


class ResourceScope(str, Enum):
    """The physical resource scope known during Action preflight."""

    INSIDE = "inside"
    OUTSIDE = "outside"
    UNKNOWN = "unknown"


class Decision(str, Enum):
    """The only terminal outcomes of permission evaluation."""

    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


class RuleKind(str, Enum):
    """The two rule partitions evaluated by the permission domain."""

    GUARD = "guard"
    POLICY = "policy"


class DecisionReason(str, Enum):
    """Stable facts explaining which part of the evaluation produced a result."""

    GUARD_MATCH = "guard_match"
    POLICY_MATCH = "policy_match"
    SESSION_GRANT = "session_grant"
    MODE_FALLBACK = "mode_fallback"


def _enum_value(value: object, enum_type: type[Enum], name: str) -> Enum:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        allowed = ", ".join(str(item.value) for item in enum_type)
        raise ValueError(f"{name} must be one of: {allowed}") from exc


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"{name} must be a non-empty string")
    if "\x00" in value:
        raise ValueError(f"{name} must not contain a null byte")
    return value


def _optional_text(value: object, name: str) -> str | None:
    if value is None:
        return None
    return _text(value, name)


@dataclass(frozen=True, slots=True)
class PermissionAction:
    """A trusted, display-safe description of a normalized ToolCall."""

    tool: str
    action: str
    effect: Effect
    resource: str | None = None
    scope: ResourceScope = ResourceScope.UNKNOWN

    def __post_init__(self) -> None:
        object.__setattr__(self, "tool", _text(self.tool, "tool"))
        object.__setattr__(self, "action", _text(self.action, "action"))
        object.__setattr__(
            self,
            "effect",
            _enum_value(self.effect, Effect, "effect"),
        )
        object.__setattr__(
            self,
            "resource",
            _optional_text(self.resource, "resource"),
        )
        object.__setattr__(
            self,
            "scope",
            _enum_value(self.scope, ResourceScope, "scope"),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "tool": self.tool,
            "action": self.action,
            "effect": self.effect.value,
            "resource": self.resource,
            "scope": self.scope.value,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))


def _normalized_resource_path(resource: str) -> str:
    normalized = resource.replace("\\", "/")
    if re.match(r"^(?:[A-Za-z]:/|//)", normalized):
        return ntpath.normpath(normalized).replace("\\", "/")
    return posixpath.normpath(normalized)


def _is_path_like_resource(resource: str) -> bool:
    normalized = resource.replace("\\", "/")
    return normalized.startswith("/") or re.match(
        r"^(?:[A-Za-z]:/|//)", normalized
    ) is not None


def _resource_path_key(resource: str) -> str:
    """Normalize physical path-like resources without importing filesystem APIs."""

    normalized = _normalized_resource_path(resource)
    if re.match(r"^(?:[A-Za-z]:/|//)", normalized):
        return ntpath.normcase(ntpath.normpath(normalized)).replace("\\", "/")
    return posixpath.normpath(normalized)


def _is_filesystem_root_resource(resource: str) -> bool:
    normalized = _normalized_resource_path(resource)
    if normalized == "/":
        return True

    drive, tail = ntpath.splitdrive(normalized)
    drive = drive.replace("\\", "/")
    tail = tail.replace("\\", "/")
    if re.fullmatch(r"[A-Za-z]:", drive):
        return tail in {"", "/"}
    if drive.startswith("//"):
        share_parts = [part for part in drive[2:].split("/") if part]
        return len(share_parts) == 2 and tail in {"", "/"}
    return False


def _resources_equal(expected: str, actual: str) -> bool:
    if _is_path_like_resource(expected) and _is_path_like_resource(actual):
        return _resource_path_key(expected) == _resource_path_key(actual)
    return expected == actual


def _resource_prefix_matches(prefix: str, resource: str) -> bool:
    if _is_filesystem_root_resource(prefix):
        return False
    prefix_key = _resource_path_key(prefix).rstrip("/")
    resource_key = _resource_path_key(resource)
    if not prefix_key:
        return False
    return resource_key == prefix_key or resource_key.startswith(prefix_key + "/")


@dataclass(frozen=True, slots=True)
class Rule:
    """One immutable Guard or Policy matcher.

    ``priority`` represents the source precedence supplied by the Integration
    rule loader.  A larger value is more specific.  Rules with the same
    source and priority are resolved by ``DENY > ASK > ALLOW``.
    """

    kind: RuleKind
    decision: Decision
    source: str = "inline"
    priority: int = 0
    rule_id: str | None = None
    tool: str | None = None
    action: str | None = None
    effect: Effect | None = None
    resource: str | None = None
    scope: ResourceScope | None = None
    resource_prefix: bool = False
    resource_regex: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _enum_value(self.kind, RuleKind, "kind"))
        object.__setattr__(
            self,
            "decision",
            _enum_value(self.decision, Decision, "decision"),
        )
        object.__setattr__(self, "source", _text(self.source, "source"))
        if isinstance(self.priority, bool) or not isinstance(self.priority, int):
            raise TypeError("priority must be an integer")
        object.__setattr__(self, "rule_id", _optional_text(self.rule_id, "rule_id"))
        object.__setattr__(self, "tool", _optional_text(self.tool, "tool"))
        object.__setattr__(self, "action", _optional_text(self.action, "action"))
        if self.effect is not None:
            object.__setattr__(
                self,
                "effect",
                _enum_value(self.effect, Effect, "effect"),
            )
        if self.scope is not None:
            object.__setattr__(
                self,
                "scope",
                _enum_value(self.scope, ResourceScope, "scope"),
            )
        object.__setattr__(self, "resource", _optional_text(self.resource, "resource"))
        object.__setattr__(
            self,
            "resource_regex",
            _optional_text(self.resource_regex, "resource_regex"),
        )
        if not isinstance(self.resource_prefix, bool):
            raise TypeError("resource_prefix must be a boolean")
        if self.resource_prefix and self.resource is None:
            raise ValueError("resource_prefix requires a resource")
        if self.resource_regex is not None and self.resource is not None:
            raise ValueError("resource and resource_regex are mutually exclusive")
        if self.resource_regex is not None and self.resource_prefix:
            raise ValueError("resource_prefix cannot be used with resource_regex")

    def matches(self, action: PermissionAction) -> bool:
        if self.tool is not None and self.tool != action.tool:
            return False
        if self.action is not None and self.action != action.action:
            return False
        if self.effect is not None and self.effect is not action.effect:
            return False
        if self.scope is not None and self.scope is not action.scope:
            return False
        if self.resource_regex is not None:
            try:
                resource = (action.resource or "").replace("\\", "/")
                return re.search(self.resource_regex, resource) is not None
            except re.error:
                # Integration rule loading validates regexes before they reach
                # Core.  A programmatic malformed Rule is simply non-matching
                # rather than turning evaluation into an unsafe broad allow.
                return False
        if self.resource is None:
            return True
        if action.resource is None:
            return False
        if not self.resource_prefix:
            return _resources_equal(self.resource, action.resource)
        return _resource_prefix_matches(self.resource, action.resource)

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "decision": self.decision.value,
            "source": self.source,
            "priority": self.priority,
            "rule_id": self.rule_id,
            "tool": self.tool,
            "action": self.action,
            "effect": self.effect.value if self.effect is not None else None,
            "resource": self.resource,
            "scope": self.scope.value if self.scope is not None else None,
            "resource_prefix": self.resource_prefix,
            "resource_regex": self.resource_regex,
        }


@dataclass(frozen=True, slots=True)
class RuleSet:
    """The immutable Rule snapshot used by one evaluator/Run."""

    rules: tuple[Rule, ...] = ()

    def __post_init__(self) -> None:
        rules = tuple(self.rules)
        if not all(isinstance(rule, Rule) for rule in rules):
            raise TypeError("rules must contain Rule values")
        object.__setattr__(self, "rules", rules)

    @property
    def guard_rules(self) -> tuple[Rule, ...]:
        return tuple(rule for rule in self.rules if rule.kind is RuleKind.GUARD)

    @property
    def policy_rules(self) -> tuple[Rule, ...]:
        return tuple(rule for rule in self.rules if rule.kind is RuleKind.POLICY)

    def to_dict(self) -> dict[str, object]:
        return {"rules": tuple(rule.to_dict() for rule in self.rules)}


@dataclass(frozen=True, slots=True)
class SessionGrant:
    """A precise, Run-local replacement for one ordinary Strategy ASK."""

    tool: str
    action: str
    effect: Effect
    resource: str
    scope: ResourceScope | None = None
    resource_prefix: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "tool", _text(self.tool, "tool"))
        object.__setattr__(self, "action", _text(self.action, "action"))
        object.__setattr__(
            self,
            "effect",
            _enum_value(self.effect, Effect, "effect"),
        )
        object.__setattr__(self, "resource", _text(self.resource, "resource"))
        if self.scope is not None:
            object.__setattr__(
                self,
                "scope",
                _enum_value(self.scope, ResourceScope, "scope"),
            )
        if not isinstance(self.resource_prefix, bool):
            raise TypeError("resource_prefix must be a boolean")

    def matches(self, action: PermissionAction) -> bool:
        if (
            self.tool != action.tool
            or self.action != action.action
            or self.effect is not action.effect
            or (self.scope is not None and self.scope is not action.scope)
            or action.resource is None
        ):
            return False
        if not self.resource_prefix:
            return _resources_equal(self.resource, action.resource)
        return _resource_prefix_matches(self.resource, action.resource)

    def to_dict(self) -> dict[str, object]:
        return {
            "tool": self.tool,
            "action": self.action,
            "effect": self.effect.value,
            "resource": self.resource,
            "scope": self.scope.value if self.scope is not None else None,
            "resource_prefix": self.resource_prefix,
        }


@dataclass(frozen=True, slots=True)
class PermissionDecision:
    """The final immutable result of Action → Rules → Strategy."""

    decision: Decision
    reason: DecisionReason
    action: PermissionAction
    mode: PermissionMode
    matched_rule_id: str | None = None
    matched_source: str | None = None
    matched_rule_kind: RuleKind | None = None
    guard_allowed: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "decision",
            _enum_value(self.decision, Decision, "decision"),
        )
        object.__setattr__(
            self,
            "reason",
            _enum_value(self.reason, DecisionReason, "reason"),
        )
        if not isinstance(self.action, PermissionAction):
            raise TypeError("action must be a PermissionAction")
        object.__setattr__(
            self,
            "mode",
            _enum_value(self.mode, PermissionMode, "mode"),
        )
        object.__setattr__(
            self,
            "matched_rule_id",
            _optional_text(self.matched_rule_id, "matched_rule_id"),
        )
        object.__setattr__(
            self,
            "matched_source",
            _optional_text(self.matched_source, "matched_source"),
        )
        if self.matched_rule_kind is not None:
            object.__setattr__(
                self,
                "matched_rule_kind",
                _enum_value(self.matched_rule_kind, RuleKind, "matched_rule_kind"),
            )
        if not isinstance(self.guard_allowed, bool):
            raise TypeError("guard_allowed must be a boolean")

    @property
    def outcome(self) -> Decision:
        """Return the terminal decision using a descriptive read-only name."""

        return self.decision

    def to_dict(self) -> dict[str, object]:
        return {
            "decision": self.decision.value,
            "reason": self.reason.value,
            "action": self.action.to_dict(),
            "mode": self.mode.value,
            "matched_rule_id": self.matched_rule_id,
            "matched_source": self.matched_source,
            "matched_rule_kind": (
                self.matched_rule_kind.value
                if self.matched_rule_kind is not None
                else None
            ),
            "guard_allowed": self.guard_allowed,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))


class PermissionEvaluator:
    """Evaluate one trusted Action against a Rule snapshot and Run mode."""

    def __init__(self, rules: RuleSet | None = None) -> None:
        if rules is None:
            rules = RuleSet()
        if not isinstance(rules, RuleSet):
            raise TypeError("rules must be a RuleSet or None")
        self._rules = rules

    @property
    def rules(self) -> RuleSet:
        return self._rules

    def evaluate(
        self,
        action: PermissionAction,
        mode: PermissionMode = PermissionMode.DEFAULT,
        session_grants: Sequence[SessionGrant] = (),
    ) -> PermissionDecision:
        if not isinstance(action, PermissionAction):
            raise TypeError("action must be a PermissionAction")
        mode = _enum_value(mode, PermissionMode, "mode")  # type: ignore[assignment]
        grants = tuple(session_grants)
        if not all(isinstance(grant, SessionGrant) for grant in grants):
            raise TypeError("session_grants must contain SessionGrant values")

        guard = self._select(RuleKind.GUARD, action)
        if guard is not None:
            if guard.decision is Decision.DENY:
                return self._from_rule(
                    Decision.DENY,
                    DecisionReason.GUARD_MATCH,
                    action,
                    mode,
                    guard,
                    guard_allowed=False,
                )
            if guard.decision is Decision.ASK:
                return self._from_rule(
                    Decision.ASK,
                    DecisionReason.GUARD_MATCH,
                    action,
                    mode,
                    guard,
                    guard_allowed=False,
                )
            guard_allowed = True
        else:
            guard_allowed = False

        if mode is PermissionMode.FULL_ACCESS:
            if guard is not None:
                return self._from_rule(
                    Decision.ALLOW,
                    DecisionReason.GUARD_MATCH,
                    action,
                    mode,
                    guard,
                    guard_allowed=True,
                )
            return self._fallback(action, mode, Decision.ALLOW, guard_allowed=False)

        policy = self._select(RuleKind.POLICY, action)
        if policy is not None:
            return self._from_rule(
                policy.decision,
                DecisionReason.POLICY_MATCH,
                action,
                mode,
                policy,
                guard_allowed=guard_allowed,
            )

        strategy = self._strategy(action, mode)
        if strategy is Decision.ASK and any(grant.matches(action) for grant in grants):
            return PermissionDecision(
                decision=Decision.ALLOW,
                reason=DecisionReason.SESSION_GRANT,
                action=action,
                mode=mode,
                guard_allowed=guard_allowed,
            )
        return self._fallback(action, mode, strategy, guard_allowed=guard_allowed)

    def _select(self, kind: RuleKind, action: PermissionAction) -> Rule | None:
        matches = [rule for rule in self._rules.rules if rule.kind is kind and rule.matches(action)]
        if not matches:
            return None

        highest_priority = max(rule.priority for rule in matches)
        highest = [rule for rule in matches if rule.priority == highest_priority]
        # A source is the unit of precedence.  If malformed input gives two
        # source names the same priority, preserve RuleSet order instead of
        # turning a lower-level DENY into a global deny-wins rule.
        selected_source = highest[0].source
        same_source = [rule for rule in highest if rule.source == selected_source]
        return max(same_source, key=lambda rule: _decision_rank(rule.decision))

    @staticmethod
    def _strategy(action: PermissionAction, mode: PermissionMode) -> Decision:
        if action.scope is ResourceScope.INSIDE and action.effect is Effect.READ:
            return Decision.ALLOW
        if (
            mode is PermissionMode.AUTO
            and action.scope is ResourceScope.INSIDE
            and action.effect is Effect.WRITE
        ):
            return Decision.ALLOW
        return Decision.ASK

    @staticmethod
    def _from_rule(
        decision: Decision,
        reason: DecisionReason,
        action: PermissionAction,
        mode: PermissionMode,
        rule: Rule,
        *,
        guard_allowed: bool,
    ) -> PermissionDecision:
        return PermissionDecision(
            decision=decision,
            reason=reason,
            action=action,
            mode=mode,
            matched_rule_id=rule.rule_id,
            matched_source=rule.source,
            matched_rule_kind=rule.kind,
            guard_allowed=guard_allowed,
        )

    @staticmethod
    def _fallback(
        action: PermissionAction,
        mode: PermissionMode,
        decision: Decision,
        *,
        guard_allowed: bool,
    ) -> PermissionDecision:
        return PermissionDecision(
            decision=decision,
            reason=DecisionReason.MODE_FALLBACK,
            action=action,
            mode=mode,
            guard_allowed=guard_allowed,
        )


def _decision_rank(decision: Decision) -> int:
    return {
        Decision.ALLOW: 1,
        Decision.ASK: 2,
        Decision.DENY: 3,
    }[decision]


def evaluate_permission(
    action: PermissionAction,
    *,
    mode: PermissionMode = PermissionMode.DEFAULT,
    rules: RuleSet | None = None,
    session_grants: Sequence[SessionGrant] = (),
) -> PermissionDecision:
    """Evaluate one Action without exposing evaluator state to callers."""

    return PermissionEvaluator(rules).evaluate(action, mode, session_grants)


__all__ = [
    "Decision",
    "DecisionReason",
    "Effect",
    "PermissionAction",
    "PermissionDecision",
    "PermissionEvaluator",
    "PermissionMode",
    "ResourceScope",
    "Rule",
    "RuleKind",
    "RuleSet",
    "SessionGrant",
    "evaluate_permission",
]
