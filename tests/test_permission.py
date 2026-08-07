from __future__ import annotations

import json
from dataclasses import FrozenInstanceError

import pytest

from uthcode.core.permission import (
    Decision,
    DecisionReason,
    Effect,
    PermissionAction,
    PermissionEvaluator,
    PermissionMode,
    ResourceScope,
    Rule,
    RuleKind,
    RuleSet,
    SessionGrant,
)


def _action(
    *,
    effect: Effect = Effect.READ,
    scope: ResourceScope = ResourceScope.INSIDE,
    resource: str = "project/note.txt",
    tool: str = "ReadFile",
    action: str = "read",
) -> PermissionAction:
    return PermissionAction(
        tool=tool,
        action=action,
        effect=effect,
        resource=resource,
        scope=scope,
    )


def _rule(
    *,
    kind: RuleKind,
    decision: Decision,
    source: str = "user",
    priority: int = 10,
    rule_id: str = "rule-1",
    **matches: object,
) -> Rule:
    return Rule(
        kind=kind,
        decision=decision,
        source=source,
        priority=priority,
        rule_id=rule_id,
        **matches,
    )


@pytest.mark.parametrize(
    ("effect", "scope", "mode", "expected"),
    [
        (Effect.READ, ResourceScope.INSIDE, PermissionMode.DEFAULT, Decision.ALLOW),
        (Effect.READ, ResourceScope.INSIDE, PermissionMode.AUTO, Decision.ALLOW),
        (Effect.READ, ResourceScope.INSIDE, PermissionMode.FULL_ACCESS, Decision.ALLOW),
        (Effect.WRITE, ResourceScope.INSIDE, PermissionMode.DEFAULT, Decision.ASK),
        (Effect.WRITE, ResourceScope.INSIDE, PermissionMode.AUTO, Decision.ALLOW),
        (Effect.WRITE, ResourceScope.INSIDE, PermissionMode.FULL_ACCESS, Decision.ALLOW),
        (Effect.READ, ResourceScope.OUTSIDE, PermissionMode.DEFAULT, Decision.ASK),
        (Effect.READ, ResourceScope.OUTSIDE, PermissionMode.AUTO, Decision.ASK),
        (Effect.READ, ResourceScope.OUTSIDE, PermissionMode.FULL_ACCESS, Decision.ALLOW),
        (Effect.WRITE, ResourceScope.OUTSIDE, PermissionMode.DEFAULT, Decision.ASK),
        (Effect.WRITE, ResourceScope.OUTSIDE, PermissionMode.AUTO, Decision.ASK),
        (Effect.WRITE, ResourceScope.OUTSIDE, PermissionMode.FULL_ACCESS, Decision.ALLOW),
        (Effect.DESTRUCTIVE, ResourceScope.INSIDE, PermissionMode.DEFAULT, Decision.ASK),
        (Effect.DESTRUCTIVE, ResourceScope.INSIDE, PermissionMode.AUTO, Decision.ASK),
        (Effect.DESTRUCTIVE, ResourceScope.INSIDE, PermissionMode.FULL_ACCESS, Decision.ALLOW),
        (Effect.EXTERNAL, ResourceScope.INSIDE, PermissionMode.DEFAULT, Decision.ASK),
        (Effect.EXTERNAL, ResourceScope.INSIDE, PermissionMode.AUTO, Decision.ASK),
        (Effect.EXTERNAL, ResourceScope.INSIDE, PermissionMode.FULL_ACCESS, Decision.ALLOW),
        (Effect.UNKNOWN, ResourceScope.INSIDE, PermissionMode.DEFAULT, Decision.ASK),
        (Effect.UNKNOWN, ResourceScope.INSIDE, PermissionMode.AUTO, Decision.ASK),
        (Effect.UNKNOWN, ResourceScope.INSIDE, PermissionMode.FULL_ACCESS, Decision.ALLOW),
    ],
)
def test_strategy_matrix(
    effect: Effect,
    scope: ResourceScope,
    mode: PermissionMode,
    expected: Decision,
) -> None:
    result = PermissionEvaluator().evaluate(_action(effect=effect, scope=scope), mode=mode)

    assert result.decision is expected
    assert result.reason is DecisionReason.MODE_FALLBACK
    assert result.matched_rule_id is None


def test_guard_decisions_apply_in_all_modes_and_guard_allow_continues() -> None:
    action = _action(effect=Effect.WRITE)
    guard_deny = PermissionEvaluator(
        RuleSet((_rule(kind=RuleKind.GUARD, decision=Decision.DENY),))
    )
    guard_ask = PermissionEvaluator(
        RuleSet((_rule(kind=RuleKind.GUARD, decision=Decision.ASK),))
    )
    guard_allow_policy_deny = PermissionEvaluator(
        RuleSet(
            (
                _rule(kind=RuleKind.GUARD, decision=Decision.ALLOW, rule_id="guard"),
                _rule(
                    kind=RuleKind.POLICY,
                    decision=Decision.DENY,
                    rule_id="policy",
                ),
            )
        )
    )

    for mode in PermissionMode:
        assert guard_deny.evaluate(action, mode=mode).decision is Decision.DENY
        assert guard_ask.evaluate(action, mode=mode).decision is Decision.ASK

    ordinary = guard_allow_policy_deny.evaluate(action, mode=PermissionMode.DEFAULT)
    full_access = guard_allow_policy_deny.evaluate(
        action,
        mode=PermissionMode.FULL_ACCESS,
    )
    assert ordinary.decision is Decision.DENY
    assert ordinary.reason is DecisionReason.POLICY_MATCH
    assert full_access.decision is Decision.ALLOW
    assert full_access.reason is DecisionReason.GUARD_MATCH


def test_source_precedence_is_separate_from_same_source_strictness() -> None:
    action = _action(effect=Effect.WRITE)
    evaluator = PermissionEvaluator(
        RuleSet(
            (
                _rule(
                    kind=RuleKind.POLICY,
                    decision=Decision.DENY,
                    source="parent",
                    priority=10,
                    rule_id="parent-deny",
                ),
                _rule(
                    kind=RuleKind.POLICY,
                    decision=Decision.ALLOW,
                    source="nearest",
                    priority=20,
                    rule_id="nearest-allow",
                ),
            )
        )
    )
    nearest = evaluator.evaluate(action, mode=PermissionMode.DEFAULT)
    assert nearest.decision is Decision.ALLOW
    assert nearest.matched_rule_id == "nearest-allow"

    same_source = PermissionEvaluator(
        RuleSet(
            (
                _rule(
                    kind=RuleKind.POLICY,
                    decision=Decision.ALLOW,
                    rule_id="allow",
                ),
                _rule(
                    kind=RuleKind.POLICY,
                    decision=Decision.ASK,
                    rule_id="ask",
                ),
                _rule(
                    kind=RuleKind.POLICY,
                    decision=Decision.DENY,
                    rule_id="deny",
                ),
            )
        )
    )
    strictest = same_source.evaluate(action, mode=PermissionMode.AUTO)
    assert strictest.decision is Decision.DENY
    assert strictest.matched_rule_id == "deny"


def test_policy_allow_ask_and_deny_are_terminal_outcomes_except_full_access() -> None:
    action = _action(effect=Effect.READ)
    for decision in (Decision.ALLOW, Decision.ASK, Decision.DENY):
        result = PermissionEvaluator(
            RuleSet((_rule(kind=RuleKind.POLICY, decision=decision),))
        ).evaluate(action, mode=PermissionMode.DEFAULT)
        assert result.decision is decision
        assert result.reason is DecisionReason.POLICY_MATCH

    ignored = PermissionEvaluator(
        RuleSet((_rule(kind=RuleKind.POLICY, decision=Decision.DENY),))
    ).evaluate(action, mode=PermissionMode.FULL_ACCESS)
    assert ignored.decision is Decision.ALLOW
    assert ignored.reason is DecisionReason.MODE_FALLBACK


def test_session_grant_only_replaces_strategy_ask_and_is_exactly_bounded() -> None:
    action = _action(
        effect=Effect.WRITE,
        tool="WriteFile",
        action="write",
    )
    grant = SessionGrant(
        tool="WriteFile",
        action="write",
        effect=Effect.WRITE,
        resource="project/note.txt",
        scope=ResourceScope.INSIDE,
    )
    evaluator = PermissionEvaluator()

    allowed = evaluator.evaluate(
        action,
        mode=PermissionMode.DEFAULT,
        session_grants=(grant,),
    )
    assert allowed.decision is Decision.ALLOW
    assert allowed.reason is DecisionReason.SESSION_GRANT

    different_resource = evaluator.evaluate(
        _action(effect=Effect.WRITE, tool="WriteFile", action="write", resource="project/other.txt"),
        mode=PermissionMode.DEFAULT,
        session_grants=(grant,),
    )
    assert different_resource.decision is Decision.ASK

    policy_deny = PermissionEvaluator(
        RuleSet(
            (
                _rule(
                    kind=RuleKind.POLICY,
                    decision=Decision.DENY,
                    tool="WriteFile",
                    action="write",
                    effect=Effect.WRITE,
                ),
            )
        )
    ).evaluate(action, mode=PermissionMode.DEFAULT, session_grants=(grant,))
    assert policy_deny.decision is Decision.DENY


def test_permission_values_are_immutable_and_json_safe() -> None:
    action = _action()
    rule = _rule(kind=RuleKind.POLICY, decision=Decision.ALLOW)
    decision = PermissionEvaluator(RuleSet((rule,))).evaluate(action)

    with pytest.raises(FrozenInstanceError):
        action.resource = "secret"  # type: ignore[misc]

    payload = {
        "action": action.to_dict(),
        "rule": rule.to_dict(),
        "decision": decision.to_dict(),
    }
    encoded = json.dumps(payload, sort_keys=True)
    assert "Path" not in encoded
    assert "ToolDefinition" not in encoded
    assert "project/note.txt" in encoded
