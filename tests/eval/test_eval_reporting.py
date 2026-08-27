from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval.models import (
    AttemptRecord,
    ContractError,
    FinishCategory,
    MetricValue,
    TaskDefinition,
    VerifierCheck,
    VerifierResult,
)
from eval.metrics import compute_metric_details, compute_attempt_metrics, scan_for_secrets
from eval.reporting import (
    aggregate_experiment,
    compare_experiments,
    render_markdown_report,
    render_terminal_summary,
)


def _task_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "task_id": "single-file-control",
        "task_version": "0.1.0",
        "instruction_path": "instruction.md",
        "fixture_path": "fixture",
        "verifier_path": "verify.py",
        "behavior_mode": "default",
        "timeout_seconds": 120,
        "attempts": 1,
        "required_evidence": [
            {"id": "target-module", "path": "src/module.py", "fact": "target"},
            {"id": "target-test", "path": "tests/test_module.py", "fact": "test"},
        ],
        "interactions": [
            {
                "id": "clarify-scope",
                "kind": "ask_user",
                "response": {"answers": {"scope": ["module"]}},
            }
        ],
        "permission_rules": [
            {
                "id": "read-fixture",
                "kind": "policy",
                "decision": "allow",
                "tool": "file",
                "action": "read",
                "effect": "read",
                "scope": "inside",
                "resource": "src/module.py",
            }
        ],
        "scoring": {
            "hard": 1.0,
            "partial": 0.5,
            "dimensions": ["correctness", "safety"],
        },
    }


def test_task_contract_round_trips_through_json_and_toml(tmp_path: Path) -> None:
    payload = _task_payload()
    task = TaskDefinition.from_mapping(payload)

    restored = TaskDefinition.from_json(task.to_json())
    assert restored == task
    assert restored.to_dict() == task.to_dict()

    toml_path = tmp_path / "task.toml"
    toml_path.write_text(
        '''
schema_version = 1
task_id = "single-file-control"
task_version = "0.1.0"
instruction_path = "instruction.md"
fixture_path = "fixture"
verifier_path = "verify.py"
behavior_mode = "default"
timeout_seconds = 120
attempts = 1
required_evidence = [
  { id = "target-module", path = "src/module.py", fact = "target" },
  { id = "target-test", path = "tests/test_module.py", fact = "test" },
]
interactions = [
  { id = "clarify-scope", kind = "ask_user", response = { answers = { scope = ["module"] } } },
]
permission_rules = [
  { id = "read-fixture", kind = "policy", decision = "allow", tool = "file", action = "read", effect = "read", scope = "inside", resource = "src/module.py" },
]
[scoring]
hard = 1.0
partial = 0.5
dimensions = ["correctness", "safety"]
'''.lstrip(),
        encoding="utf-8",
    )
    assert TaskDefinition.from_toml(toml_path) == task


@pytest.mark.parametrize(
    ("mutator", "match"),
    [
        (lambda p: p.update({"secret_field": "do-not-echo"}), "unknown fields"),
        (lambda p: p.update({"schema_version": 999}), "schema_version"),
        (lambda p: p.update({"instruction_path": "../secret.txt"}), "instruction_path"),
        (lambda p: p.update({"fixture_path": "C:/secret"}), "fixture_path"),
    ],
)
def test_task_contract_rejects_unknown_version_and_unsafe_paths(
    mutator: object, match: str
) -> None:
    payload = _task_payload()
    mutator(payload)  # type: ignore[operator]

    with pytest.raises(ContractError, match=match) as raised:
        TaskDefinition.from_mapping(payload)
    assert "do-not-echo" not in str(raised.value)


@pytest.mark.parametrize(
    "section",
    ["required_evidence", "interactions", "permission_rules"],
)
def test_task_contract_rejects_duplicate_ids(section: str) -> None:
    payload = _task_payload()
    values = payload[section]
    assert isinstance(values, list)
    values.append(dict(values[0]))

    with pytest.raises(ContractError, match="duplicate"):
        TaskDefinition.from_mapping(payload)


def test_task_contract_rejects_illegal_interaction_and_wide_permission_rule() -> None:
    payload = _task_payload()
    payload["interactions"] = [
        {"id": "bad", "kind": "free_form", "response": {}}
    ]
    with pytest.raises(ContractError, match="interaction"):
        TaskDefinition.from_mapping(payload)

    payload = _task_payload()
    payload["permission_rules"] = [
        {
            "id": "everything",
            "kind": "policy",
            "decision": "allow",
            "tool": "*",
            "action": "read",
            "effect": "read",
            "scope": "inside",
            "resource": "*",
        }
    ]
    with pytest.raises(ContractError, match="permission rule"):
        TaskDefinition.from_mapping(payload)


@pytest.mark.parametrize(
    "resource",
    ["../outside.txt", "src/../../outside.txt", "./inside.txt"],
)
def test_task_contract_rejects_permission_resource_traversal(
    resource: str,
) -> None:
    payload = _task_payload()
    rule = dict(payload["permission_rules"][0])  # type: ignore[index]
    rule["resource"] = resource
    payload["permission_rules"] = [rule]

    with pytest.raises(ContractError, match="permission_rules.resource"):
        TaskDefinition.from_mapping(payload)


def test_verifier_contract_enforces_score_bounds_and_success_invariant() -> None:
    check = VerifierCheck(
        check_id="hard-check",
        kind="hard",
        passed=True,
        points=2,
        max_points=2,
        message="passed",
    )
    result = VerifierResult(
        schema_version=1,
        checks=(check,),
        correctness_score=100,
        success=True,
    )
    assert VerifierResult.from_json(result.to_json()) == result

    with pytest.raises(ContractError, match="points"):
        VerifierCheck(
            check_id="bad",
            kind="partial",
            passed=False,
            points=3,
            max_points=2,
            message="bad",
        )
    with pytest.raises(ContractError, match="correctness_score"):
        VerifierResult(
            schema_version=1,
            checks=(check,),
            correctness_score=101,
            success=True,
        )
    with pytest.raises(ContractError, match="success"):
        VerifierResult(
            schema_version=1,
            checks=(check,),
            correctness_score=0,
            success=False,
        )


def test_not_available_metric_is_not_numeric_zero() -> None:
    unavailable = MetricValue(status="not_available", value=None)
    zero = MetricValue(status="available", value=0)

    assert unavailable.to_dict() != zero.to_dict()
    assert json.loads(unavailable.to_json())["value"] is None
    assert json.loads(zero.to_json())["value"] == 0
    assert MetricValue.from_json(unavailable.to_json()) == unavailable


def test_contract_nested_values_are_immutable_after_construction() -> None:
    task = TaskDefinition.from_mapping(_task_payload())

    with pytest.raises(TypeError):
        task.interactions[0].response["answers"] = {}  # type: ignore[index]
    with pytest.raises(TypeError):
        task.interactions[0].response["answers"]["scope"] = ["other"]  # type: ignore[index]


def test_attempt_record_round_trips_without_runtime_objects() -> None:
    check = VerifierCheck("hard-check", "hard", True, 1, 1, "passed")
    verifier = VerifierResult(1, (check,), 100, True)
    record = AttemptRecord(
        schema_version=1,
        experiment_id="exp-1",
        task_id="task-1",
        attempt_id="attempt-1",
        fingerprints={"uthcode_revision": "abc", "model": "fake"},
        paths={"workspace": "C:/external/workspace", "artifacts": "C:/external/artifacts"},
        timestamps={"started": "2026-08-13T00:00:00Z"},
        duration_seconds=0,
        finish_category=FinishCategory.SUCCESS,
        turn_result={"status": "completed", "tool_calls": []},
        verifier_result=verifier,
        metrics={"context": MetricValue("not_available")},
        artifact_manifest={"events": "events.jsonl"},
    )

    restored = AttemptRecord.from_json(record.to_json())
    assert restored == record
    assert restored.to_dict() == record.to_dict()
    with pytest.raises(TypeError):
        record.fingerprints["model"] = "other"  # type: ignore[index]


def _metric_verifier(*, success: bool = True, forbidden: bool = True) -> VerifierResult:
    checks = (
        VerifierCheck("hard", "hard", success, 1 if success else 0, 1, "hard"),
        VerifierCheck("partial", "partial", True, 1, 1, "partial"),
        VerifierCheck("forbidden", "forbidden", forbidden, 1 if forbidden else 0, 1, "forbidden"),
    )
    return VerifierResult(1, checks, 100 if success and forbidden else 40, success and forbidden)


def test_metrics_keep_six_dimensions_and_unavailable_context_facts_distinct() -> None:
    details = compute_metric_details(
        verifier_result=_metric_verifier(),
        turn_result={
            "status": "completed",
            "termination_reason": "final_answer",
            "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            "iteration_count": 2,
            "tool_call_count": 3,
        },
        diagnostics={"duration_seconds": 0.25, "repository_status_delta": []},
        events=[],
        task=None,
    )
    assert tuple(details) == (
        "correctness", "context", "exploration", "efficiency", "stability", "safety"
    )
    assert details["context"]["status"] == "not_available"
    assert details["context"]["score"] is None
    assert details["efficiency"]["status"] == "available"
    assert details["efficiency"]["raw"]["total_tokens"] == 15
    metrics = compute_attempt_metrics(
        verifier_result=_metric_verifier(), turn_result=None, diagnostics={}, events=[], task=None
    )
    assert metrics["context"].status.value == "not_available"
    assert metrics["context"].value is None


def test_metrics_count_repeated_tool_exploration_and_secret_scan() -> None:
    events = [
        {"type": "tool_started", "iteration": 1, "tool_name": "ReadFile", "command": "ReadFile src/a.py"},
        {"type": "tool_started", "iteration": 2, "tool_name": "ReadFile", "command": "ReadFile src/a.py"},
        {"type": "tool_started", "iteration": 3, "tool_name": "Grep", "command": "Grep path=src"},
    ]
    details = compute_metric_details(
        verifier_result=_metric_verifier(),
        turn_result={"status": "completed", "usage": {"total_tokens": 3}, "iteration_count": 3, "tool_call_count": 3},
        diagnostics={"duration_seconds": 1.0},
        events=events,
        task=None,
    )
    assert details["exploration"]["raw"]["tool_calls"] == 3
    assert details["exploration"]["raw"]["repeated_file_reads"] == 1
    assert scan_for_secrets({"text": "api_key=TOP-SECRET"}) is True
    assert scan_for_secrets({"input_tokens": 12, "total_tokens": 20}) is False
    assert scan_for_secrets({"text": "safe"}) is False


def test_aggregate_uses_median_and_compare_rejects_incompatible_fingerprints() -> None:
    reports = []
    for attempt_id, score in (("a1", 10), ("a2", 90), ("a3", 50)):
        verifier = VerifierResult(
            1,
            (VerifierCheck("hard", "hard", True, 1, 1, "ok"),),
            score,
            True,
        )
        reports.append(
            {
                "attempt_id": attempt_id,
                "task_id": "single-file-control",
                "finish_category": "success",
                "fingerprints": {
                    "code": "c1", "task": "v1", "model": "fake", "model_id": "eval-model", "provider": "fake",
                    "prompt": "p1", "config": "cfg1", "permission": "r1",
                    "run_args": "args1", "platform": "win1", "runtime": "rt1",
                    "uthcode_revision": "rev1",
                },
                "metric_details": {
                    "correctness": {"status": "available", "score": score, "raw": {"success": True}, "evidence_refs": []},
                    "context": {"status": "not_available", "score": None, "raw": {}, "evidence_refs": []},
                    "exploration": {"status": "available", "score": 80, "raw": {}, "evidence_refs": []},
                    "efficiency": {"status": "available", "score": 80, "raw": {}, "evidence_refs": []},
                    "stability": {"status": "available", "score": 80, "raw": {}, "evidence_refs": []},
                    "safety": {"status": "available", "score": 100, "raw": {"hard_failure": False}, "evidence_refs": []},
                },
                "verifier_result": verifier.to_dict(),
            }
        )
    aggregate = aggregate_experiment("exp-1", reports)
    assert aggregate["dimensions"]["correctness"]["median_score"] == 50
    assert aggregate["dimensions"]["context"]["status"] == "not_available"
    assert "overall" not in aggregate
    compatible = compare_experiments(aggregate, aggregate)
    assert compatible["compatible"] is True
    assert compatible["delta"]["correctness"]["median_score"] == 0
    changed = dict(aggregate)
    changed["fingerprints"] = {
        "code": "c1", "task": "v1", "model": "different", "model_id": "eval-model", "provider": "fake",
        "prompt": "p1", "config": "cfg1", "permission": "r1",
        "run_args": "args1", "platform": "win1", "runtime": "rt1",
        "uthcode_revision": "rev1",
    }
    incompatible = compare_experiments(aggregate, changed)
    assert incompatible["compatible"] is False
    assert incompatible["delta"] is None
    assert incompatible["incompatibilities"]

    missing = dict(aggregate)
    missing_fingerprints = dict(aggregate["fingerprints"])
    missing_fingerprints.pop("platform")
    missing["fingerprints"] = missing_fingerprints
    missing_result = compare_experiments(aggregate, missing)
    assert missing_result["compatible"] is False
    assert missing_result["delta"] is None
    assert "candidate.fingerprints.platform" in missing_result["incompatibilities"]

    suite_left = dict(aggregate)
    suite_right = dict(aggregate)
    suite_left["fingerprint_variants"] = {"task": ["a", "b"], "model": ["fake"]}
    suite_right["fingerprint_variants"] = {"task": ["a", "b"], "model": ["fake"]}
    suite_compatible = compare_experiments(suite_left, suite_right)
    assert suite_compatible["compatible"] is True


def test_compare_rejects_unequal_per_task_sample_counts() -> None:
    attempts = []
    for attempt_id, task_id in (("a1", "a"), ("a2", "a"), ("b1", "b")):
        attempts.append(
            {
                "attempt_id": attempt_id,
                "task_id": task_id,
                "finish_category": "success",
                "fingerprints": {
                    "code": "c1", "task": "v1", "model": "fake", "model_id": "eval-model", "provider": "fake",
                    "prompt": "p1", "config": "cfg1", "permission": "r1",
                    "run_args": "args1", "platform": "win1", "runtime": "rt1",
                    "uthcode_revision": "rev1",
                },
                "metric_details": {},
            }
        )
    baseline = aggregate_experiment("baseline", attempts)
    candidate_attempts = [dict(item) for item in attempts]
    candidate_attempts[1]["task_id"] = "b"
    candidate = aggregate_experiment("candidate", candidate_attempts)

    assert baseline["task_sample_counts"] == {"a": 2, "b": 1}
    assert candidate["task_sample_counts"] == {"a": 1, "b": 2}
    result = compare_experiments(baseline, candidate)
    assert result["compatible"] is False
    assert result["delta"] is None
    assert "task_sample_counts" in result["incompatibilities"]


def test_compare_rejects_missing_or_invalid_per_task_sample_counts() -> None:
    aggregate = aggregate_experiment("baseline", [])
    missing = dict(aggregate)
    missing.pop("task_sample_counts")
    missing_result = compare_experiments(aggregate, missing)
    assert missing_result["compatible"] is False
    assert missing_result["delta"] is None
    assert "candidate.task_sample_counts" in missing_result["incompatibilities"]

    invalid = dict(aggregate)
    invalid["task_sample_counts"] = {"a": 0}
    invalid_result = compare_experiments(aggregate, invalid)
    assert invalid_result["compatible"] is False
    assert invalid_result["delta"] is None
    assert "candidate.task_sample_counts" in invalid_result["incompatibilities"]


@pytest.mark.parametrize(
    ("task_sample_counts", "expected_reason"),
    (
        ({}, "candidate.task_sample_counts"),
        ({"a": 1, "b": 1}, "candidate.task_sample_counts"),
        ({"a": 2, "c": 1}, "candidate.task_sample_counts"),
    ),
)
def test_compare_rejects_internally_inconsistent_task_sample_counts(
    task_sample_counts: dict[str, int], expected_reason: str
) -> None:
    base = {
        "schema_version": 1,
        "task_ids": ["a", "b"],
        "sample_count": 3,
        "task_sample_counts": {"a": 2, "b": 1},
        "fingerprints": {
            "code": "c1", "task": "v1", "model": "fake", "model_id": "eval-model", "provider": "fake",
            "prompt": "p1", "config": "cfg1", "permission": "r1",
            "run_args": "args1", "platform": "win1", "runtime": "rt1",
            "uthcode_revision": "rev1",
        },
        "fingerprint_variants": {},
        "dimensions": {},
    }
    malformed = dict(base)
    malformed["task_sample_counts"] = task_sample_counts

    result = compare_experiments(base, malformed)

    assert result["compatible"] is False
    assert result["delta"] is None
    assert expected_reason in result["incompatibilities"]

    same_malformed = compare_experiments(malformed, malformed)
    assert same_malformed["compatible"] is False
    assert same_malformed["delta"] is None
    assert "baseline.task_sample_counts" in same_malformed["incompatibilities"]
    assert "candidate.task_sample_counts" in same_malformed["incompatibilities"]


def test_report_renderers_show_all_dimensions_without_single_ranking() -> None:
    aggregate = aggregate_experiment("exp-render", [])
    markdown = render_markdown_report(aggregate)
    terminal = render_terminal_summary(aggregate)
    for dimension in ("correctness", "context", "exploration", "efficiency", "stability", "safety"):
        assert dimension in markdown
        assert dimension in terminal
    assert "overall" not in markdown.lower()


def test_aggregate_preserves_unavailable_reasons_and_stable_fact_fields() -> None:
    report = aggregate_experiment(
        "fact-precision",
        [
            {
                "task_id": "long-context-constraint",
                "finish_category": "success",
                "diagnostic_facts": {
                    "history_read": {
                        "status": "not_available",
                        "value": None,
                        "reason": "offline workload has no HistoryRead ref",
                        "evidence_refs": ["diagnostics.eval_workload.history_read"],
                    },
                    "prefix_stability": {
                        "status": "available",
                        "value": {
                            "stable": True,
                            "change_reason": "stable",
                            "instruction_epoch": 1,
                        },
                        "evidence_refs": ["diagnostics.context_diagnostics.prefix_changed"],
                    },
                },
            }
        ],
    )

    history = report["facts"]["history_read"]
    assert history["reasons"] == ["offline workload has no HistoryRead ref"]
    prefix = report["facts"]["prefix_stability"]
    assert prefix["stable_fields"] == {"change_reason": "stable", "stable": True}

    failure_report = aggregate_experiment(
        "failure-source-status",
        [
            {
                "task_id": "long-context-constraint",
                "finish_category": "success",
                "diagnostic_facts": {
                    "failure_correctness": {
                        "status": "not_available",
                        "value": None,
                        "source_status": "not_applicable",
                        "reason": "successful workload",
                        "evidence_refs": [
                            "diagnostics.eval_workload.failure_correctness"
                        ],
                    }
                },
            }
        ],
    )
    failure = failure_report["facts"]["failure_correctness"]
    assert failure["status"] == "not_available"
    assert failure["source_status"] == "not_applicable"
    assert failure["reasons"] == ["successful workload"]

    markdown = render_markdown_report(report)
    terminal = render_terminal_summary(report)
    assert "offline workload has no HistoryRead ref" in markdown
    assert "change_reason" in markdown and "stable" in markdown
    assert "offline workload has no HistoryRead ref" in terminal
    assert "source_status: not_applicable" in render_markdown_report(failure_report)

    comparable = {
        **report,
        "fingerprints": {
            key: key
            for key in (
                "code",
                "task",
                "model",
                "model_id",
                "provider",
                "prompt",
                "config",
                "permission",
                "run_args",
                "platform",
                "runtime",
                "uthcode_revision",
            )
        },
        "fingerprint_variants": {},
    }
    compared = compare_experiments(comparable, comparable)
    assert compared["delta"]["facts"]["history_read"]["baseline_reasons"] == [
        "offline workload has no HistoryRead ref"
    ]
    assert compared["delta"]["facts"]["prefix_stability"]["baseline_stable_fields"] == {
        "change_reason": "stable",
        "stable": True,
    }
