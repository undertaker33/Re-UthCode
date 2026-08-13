from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from eval.models import AttemptRecord
from eval.runner import _config
from uthcode.application import ProviderKind

REPO_ROOT = Path(__file__).parents[2]
TASK_IDS = (
    "single-file-control",
    "cross-file-evidence",
    "todo-long-task",
    "plan-only",
    "ask-user-resume",
    "permission-boundary",
    "long-context-constraint",
)


def _runner(*args: str, cwd: Path = REPO_ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "eval.runner", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _json_output(completed: subprocess.CompletedProcess[str]) -> dict[str, object]:
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert isinstance(payload, dict)
    return payload


def test_runner_help_is_offline_and_exposes_manual_commands() -> None:
    completed = _runner("--help")
    assert completed.returncode == 0
    assert "smoke" in completed.stdout
    assert "run" in completed.stdout
    assert "compare" in completed.stdout
    assert "clean" in completed.stdout
    assert "--model" in _runner("smoke", "--help").stdout
    assert "--model" in _runner("run", "--help").stdout


@pytest.mark.parametrize("task_id", TASK_IDS)
def test_runner_fake_smoke_uses_external_artifacts_and_application_chain(
    task_id: str, tmp_path: Path
) -> None:
    eval_root = tmp_path / "eval-root"
    completed = _runner(
        "smoke",
        "--task",
        task_id,
        "--experiment",
        f"smoke-{task_id}",
        "--eval-root",
        str(eval_root),
        "--attempts",
        "1",
    )
    payload = _json_output(completed)
    assert payload["mode"] == "fake"
    assert payload["task_ids"] == [task_id]
    assert Path(str(payload["report_path"])).is_file()
    assert Path(str(payload["report_path"])).is_relative_to(eval_root.resolve())
    assert payload["report"]["dimensions"]["correctness"]["status"] == "available"
    expected_category = {
        "plan-only": "success",
        "permission-boundary": "blocked_by_permission",
    }.get(task_id, "agent_failure")
    assert payload["report"]["finish_categories"] == {expected_category: 1}
    assert (eval_root / "workspaces").is_dir()
    assert not (REPO_ROOT / "artifacts").exists()
    artifact_root = Path(str(payload["report"]["attempts"][0]["paths"]["artifacts"]))
    restored = AttemptRecord.from_json((artifact_root / "record.json").read_text(encoding="utf-8"))
    assert restored.task_id == task_id


def test_runner_fake_suite_aggregates_all_tasks(tmp_path: Path) -> None:
    eval_root = tmp_path / "eval-root"
    completed = _runner(
        "run",
        "--suite",
        "all",
        "--experiment",
        "suite-fake",
        "--eval-root",
        str(eval_root),
        "--attempts",
        "1",
    )
    payload = _json_output(completed)
    assert payload["task_ids"] == list(TASK_IDS)
    assert payload["report"]["sample_count"] == len(TASK_IDS)
    assert set(payload["report"]["dimensions"]) == {
        "correctness", "context", "exploration", "efficiency", "stability", "safety"
    }
    assert payload["report"]["finish_categories"] == {
        "agent_failure": 5,
        "blocked_by_permission": 1,
        "success": 1,
    }
    assert payload["report"]["task_sample_counts"] == {task_id: 1 for task_id in TASK_IDS}
    assert "overall" not in payload["report"]


def test_runner_persists_explicit_model_identifier_in_fingerprint(tmp_path: Path) -> None:
    completed = _runner(
        "smoke",
        "--task",
        "plan-only",
        "--experiment",
        "model-fingerprint",
        "--eval-root",
        str(tmp_path / "eval-root"),
        "--model",
        "offline-model-v2",
        "--attempts",
        "1",
    )
    payload = _json_output(completed)
    assert payload["report"]["fingerprints"]["model_id"] == "offline-model-v2"
    record = payload["report"]["attempts"][0]
    assert record["fingerprints"]["model_id"] == "offline-model-v2"


def test_runner_builds_live_config_with_selected_remote_model() -> None:
    config = _config(ProviderKind.ANTHROPIC, "EVAL_TEST_KEY", "claude-sonnet-4-20250514")
    assert config.current_model.remote_model_id == "claude-sonnet-4-20250514"
    assert config.provider_for().kind is ProviderKind.ANTHROPIC


def test_runner_requires_model_for_authorized_live_run_before_attempt_creation(tmp_path: Path) -> None:
    eval_root = tmp_path / "eval-root"
    completed = _runner(
        "smoke",
        "--task",
        "single-file-control",
        "--experiment",
        "live-missing-model",
        "--eval-root",
        str(eval_root),
        "--provider-kind",
        "anthropic",
        "--api-key-env",
        "EVAL_TEST_KEY",
        "--live",
        "--live-authorized",
    )
    assert completed.returncode != 0
    assert "explicit --model" in (completed.stderr + completed.stdout)
    assert not eval_root.exists()


def test_runner_plan_only_fake_smoke_has_a_successful_read_only_path(tmp_path: Path) -> None:
    completed = _runner(
        "smoke",
        "--task",
        "plan-only",
        "--experiment",
        "plan-smoke",
        "--eval-root",
        str(tmp_path / "eval-root"),
        "--attempts",
        "1",
    )
    payload = _json_output(completed)
    assert payload["report"]["finish_categories"] == {"success": 1}
    assert payload["report"]["dimensions"]["correctness"]["median_score"] == 100


def test_runner_compare_writes_no_delta_for_incompatible_results(tmp_path: Path) -> None:
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first = _json_output(_runner(
        "smoke", "--task", "single-file-control", "--experiment", "first",
        "--eval-root", str(first_root), "--attempts", "1",
    ))
    second = _json_output(_runner(
        "smoke", "--task", "single-file-control", "--experiment", "second",
        "--eval-root", str(second_root), "--attempts", "1", "--prompt-salt", "different",
    ))
    completed = _runner(
        "compare",
        "--baseline",
        str(first["report_path"]),
        "--candidate",
        str(second["report_path"]),
    )
    result = _json_output(completed)
    assert result["compatible"] is False
    assert result["delta"] is None
    assert result["incompatibilities"]


def test_runner_rejects_live_provider_before_network_without_authorization(tmp_path: Path) -> None:
    completed = _runner(
        "smoke",
        "--task",
        "single-file-control",
        "--experiment",
        "live-refused",
        "--eval-root",
        str(tmp_path / "eval-root"),
        "--provider-kind",
        "anthropic",
        "--api-key-env",
        "EVAL_TEST_KEY",
        "--live",
    )
    assert completed.returncode != 0
    assert "authorization" in (completed.stderr + completed.stdout).lower()


def test_runner_clean_rejects_source_repository(tmp_path: Path) -> None:
    completed = _runner("clean", "--eval-root", str(REPO_ROOT))
    assert completed.returncode != 0
    assert "dedicated" in (completed.stderr + completed.stdout).lower()
