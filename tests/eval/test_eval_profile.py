from __future__ import annotations

import json
import inspect
import subprocess
import sys
from pathlib import Path

import uthcode.application.context as application_context
import uthcode.application.generation as application_generation

import eval.workloads as profile_workloads
from eval.metrics import compute_diagnostic_facts
from eval.profile import PROFILE_CANDIDATES, applied_profile
from eval.reporting import aggregate_experiment, compare_experiments
from uthcode.core.provider import ModelLimits


def _control_fingerprints() -> dict[str, str]:
    return {
        "code": "code-v1",
        "task": "long-context-constraint-v1",
        "model": "fake",
        "model_id": "eval-model",
        "provider": "fake",
        "prompt": "prompt-v1",
        "config": "config-v1",
        "permission": "permission-v1",
        "run_args": "run-v1",
        "platform": "windows-v1",
        "runtime": "runtime-v1",
        "uthcode_revision": "rev-v1",
    }


def _profile_attempt(profile: object, attempt_id: str) -> dict[str, object]:
    return {
        "attempt_id": attempt_id,
        "task_id": "long-context-constraint",
        "finish_category": "success",
        "fingerprints": _control_fingerprints(),
        "candidate_variant": profile.to_variant(),  # type: ignore[union-attr]
        "metric_details": {},
        "diagnostic_facts": {},
    }


def test_profile_candidates_are_distinct_and_include_full_parameters() -> None:
    assert len(PROFILE_CANDIDATES) >= 3
    assert len({profile.profile_id for profile in PROFILE_CANDIDATES}) == len(PROFILE_CANDIDATES)
    for profile in PROFILE_CANDIDATES:
        variant = profile.to_variant()
        assert variant["id"] == profile.profile_id
        parameters = variant["parameters"]
        assert isinstance(parameters, dict)
        assert parameters["effective_input_limit"] == 256_000
        assert parameters["working_headroom"] == profile.working_headroom
        assert parameters["count_allowance"] == profile.count_allowance


def test_applied_profile_reuses_and_restores_the_application_budget_seam() -> None:
    profile = next(item for item in PROFILE_CANDIDATES if item.profile_id == "balanced-208k")
    original_generation_resolver = application_generation.resolve_context_budget
    original_context_resolver = application_context.resolve_context_budget

    with applied_profile(profile):
        budget = application_generation.resolve_context_budget(
            configured_input_limit=None,
            provider_limits=ModelLimits(max_input_tokens=1_000_000, source="eval.test"),
            requested_output_reserve=4_096,
        )
        assert budget.effective_input_limit == 256_000
        assert budget.auto_gate_limit == 208_000
        assert budget.retained_target == 96_000
        assert budget.safety_allowance == 8_192
        assert application_context.resolve_context_budget is not original_context_resolver

    assert application_generation.resolve_context_budget is original_generation_resolver
    assert application_context.resolve_context_budget is original_context_resolver


def test_candidate_axis_is_reported_without_making_control_fingerprints_incompatible() -> None:
    baseline = aggregate_experiment(
        "production",
        [_profile_attempt(PROFILE_CANDIDATES[0], "production-1")],
    )
    candidate = aggregate_experiment(
        "balanced",
        [_profile_attempt(PROFILE_CANDIDATES[1], "balanced-1")],
    )

    result = compare_experiments(baseline, candidate)
    assert result["compatible"] is True
    assert result["incompatibilities"] == []
    assert result["delta"]["candidate_variants"]["baseline"][0]["id"] == "production-default"  # type: ignore[index]
    assert result["delta"]["candidate_variants"]["candidate"][0]["id"] == "balanced-208k"  # type: ignore[index]


def test_failure_correctness_compares_expected_and_observed_failure_reason() -> None:
    facts = compute_diagnostic_facts(
        verifier_result=None,
        turn_result={"status": "failed", "failure_reason": "context_unresolvable"},
        diagnostics={
            "finish_category": "agent_failure",
            "expected_failure_reason": "context_unresolvable",
        },
        events=[],
    )

    assert facts["failure_correctness"] == {
        "status": "available",
        "value": True,
        "evidence_refs": [
            "diagnostics.expected_failure_reason",
            "turn_result.failure_reason",
        ],
    }


def test_profile_workload_derives_observed_edit_and_has_no_standard_patch() -> None:
    source = inspect.getsource(profile_workloads)

    assert not hasattr(profile_workloads, "PROFILE_FINAL_IMPLEMENTATION")
    assert "def format_result(value: str, *, compact: bool = False)" not in source
    assert "_next_calls" not in source
    assert "_stage" not in source
    assert "WriteFile" not in source

    old_string, new_string = profile_workloads._derive_implementation_edit(
        '1\tdef format_result(value: str, *, compact: bool = False) -> str\n'
        '2\t    return value.strip() if compact else value.strip() + "!"\n'
    ) or ("", "")
    assert old_string.endswith('value.strip() + "!"')
    assert new_string.endswith('value.strip() + "."')


def test_profile_workload_route_seed_allows_multiple_valid_observation_orders() -> None:
    paths = tuple(profile_workloads.PROFILE_REQUIRED_EVIDENCE_PATHS)
    first = profile_workloads.ProfileWorkloadProvider(route_seed=0)._ordered_paths(paths)
    second = profile_workloads.ProfileWorkloadProvider(route_seed=1)._ordered_paths(paths)

    assert first != second
    assert set(first) == set(paths)
    assert set(second) == set(paths)


def test_profile_two_attempts_complete_distinct_read_edit_verify_routes(tmp_path: Path) -> None:
    eval_root = tmp_path / "eval-root"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "eval.runner",
            "profile",
            "--candidate",
            "balanced-208k",
            "--experiment",
            "route-evidence",
            "--eval-root",
            str(eval_root),
            "--attempts",
            "2",
        ],
        cwd=Path(__file__).parents[2],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    report = payload["report"]

    assert report["sample_count"] == 2
    assert report["task_sample_counts"] == {"long-context-constraint": 2}
    assert report["facts"]["workload_route"]["status"] == "available"
    route_values = report["facts"]["workload_route"]["values"]
    assert {value["route_seed"] for value in route_values} == {0, 1}
    attempts = report["attempts"]
    assert [item["attempt_id"] for item in attempts] == ["1", "2"]

    traces: list[tuple[tuple[object, ...], ...]] = []
    seeds: list[int] = []
    for attempt in attempts:
        assert attempt["finish_category"] == "success"
        assert attempt["verifier_result"]["success"] is True
        assert all(check["passed"] for check in attempt["verifier_result"]["checks"])

        route_fact = attempt["diagnostic_facts"]["workload_route"]
        assert route_fact["status"] == "available"
        route = route_fact["value"]
        assert route["complete"] is True
        assert route["read_failures"] == []
        assert set(route["read_paths"]) >= set(profile_workloads.PROFILE_REQUIRED_EVIDENCE_PATHS)
        assert route["profile_ref_available"] is True
        assert route["pages_finished"] is True
        assert route["edit_attempted"] is True
        assert route["edit_succeeded"] is True
        assert set(route["post_change_reads"]) == {
            "src/implementation.py",
            "tests/test_public_api.py",
        }
        assert {call["tool"] for call in route["trace"]} >= {
            "ReadFile",
            "ToolResultRead",
            "EditFile",
        }
        seeds.append(route["route_seed"])
        traces.append(
            tuple(
                tuple(call.get(key) for key in ("kind", "tool", "path", "offset", "limit"))
                for call in route["trace"]
            )
        )

    assert seeds == [0, 1]
    assert traces[0] != traces[1]


class _PrefixProbeApplication:
    current_model = None

    def tool_definitions(self) -> tuple[object, ...]:
        return ()


def test_profile_prefix_probe_uses_production_facts_for_reuse_and_invalidation(
    tmp_path,
) -> None:
    provider = profile_workloads.ProfileWorkloadProvider()
    provider.attach_application(_PrefixProbeApplication(), tmp_path)

    evidence = provider._application_prefix_probe()

    assert evidence["status"] == "available"
    growth = evidence["conversation_growth"]
    assert growth["stable_reuse"] is True
    assert growth["fingerprint_same"] is True
    assert growth["after"]["prefix_change_reason"] == "stable"

    invalidation = evidence["expected_invalidation"]
    assert invalidation["expected"] is True
    assert invalidation["fingerprint_changed"] is True
    assert invalidation["instruction_epoch_changed"] is True
    assert invalidation["change_reason"] == "instruction_source_added"
    assert invalidation["loader_change_reason"] == "instruction_source_added"
    assert invalidation["after"]["prefix_changed"] is True
    assert invalidation["after"]["request_metadata_reason"] == "instruction_source_added"
    assert invalidation["tool_schema_fingerprint_same"] is True

    compact = provider._prefix_reuse_pair(
        growth["before"],
        growth["after"],
        label="compact",
    )
    assert compact["stable_reuse"] is True

    projected = compute_diagnostic_facts(
        verifier_result=None,
        turn_result={"status": "completed"},
        diagnostics={
            "finish_category": "success",
            "context_diagnostics": "not_available",
            "eval_workload": {
                "prefix": evidence,
                "failure_correctness": {
                    "status": "not_applicable",
                    "reason": "successful workload; failure matrix is separate",
                },
            },
        },
        events=[],
    )
    assert projected["prefix_stability"]["status"] == "available"
    assert projected["prefix_stability"]["value"]["expected_invalidation"]["change_reason"] == (
        "instruction_source_added"
    )


def test_prefix_and_success_failure_facts_keep_unavailable_distinct() -> None:
    facts = compute_diagnostic_facts(
        verifier_result=None,
        turn_result={"status": "completed"},
        diagnostics={
            "finish_category": "success",
            "context_diagnostics": "not_available",
            "eval_workload": {
                "prefix": {
                    "status": "not_available",
                    "reason": "prefix probe unavailable",
                },
                "failure_correctness": {
                    "status": "not_applicable",
                    "reason": "successful workload; failure matrix is separate",
                },
            },
        },
        events=[],
    )

    assert facts["prefix_stability"]["status"] == "not_available"
    assert facts["prefix_stability"]["reason"] == "prefix probe unavailable"
    assert facts["failure_correctness"]["status"] == "not_available"
    assert facts["failure_correctness"]["source_status"] == "not_applicable"
    assert facts["failure_correctness"]["reason"] == (
        "successful workload; failure matrix is separate"
    )
