from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


TASK_IDS = (
    "single-file-control",
    "cross-file-evidence",
    "todo-long-task",
    "plan-only",
    "ask-user-resume",
    "permission-boundary",
    "long-context-constraint",
)

TASK_ROOT = Path(__file__).parents[2] / "eval" / "tasks"


def _run_verifier(task_id: str, workspace: Path) -> dict[str, object]:
    task_dir = TASK_ROOT / task_id
    completed = subprocess.run(
        [sys.executable, str(task_dir / "verify.py"), str(workspace)],
        cwd=TASK_ROOT.parents[1],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == ""
    payload = json.loads(completed.stdout)
    assert isinstance(payload, dict)
    return payload


def _fixture(task_id: str, tmp_path: Path) -> Path:
    source = TASK_ROOT / task_id / "fixture"
    destination = tmp_path / task_id
    shutil.copytree(source, destination)
    return destination


def _replace_once(path: Path, before: str, after: str) -> None:
    source = path.read_text(encoding="utf-8")
    assert source.count(before) == 1
    path.write_text(source.replace(before, after, 1), encoding="utf-8")


def _apply_fake_gold_patch(task_id: str, workspace: Path) -> None:
    """Make the smallest gold-like fixture edit needed by one verifier test."""

    operations = {
        "single-file-control": (
            lambda: _replace_once(
                workspace / "src" / "slug.py",
                '    return "-".join(value.strip().lower().split(" "))\n',
                '    cleaned = "".join(char if char.isalnum() else " " for char in value.lower())\n'
                '    return "-".join(cleaned.split())\n',
            ),
        ),
        "cross-file-evidence": (
            lambda: _replace_once(
                workspace / "src" / "cli.py",
                '    return handle({"value": value})\n',
                '    return handle({"value": value, "request_id": request_id})\n',
            ),
            lambda: _replace_once(
                workspace / "src" / "application.py",
                '    return normalize(request["value"] or "")\n',
                '    return normalize(request["value"] or "", request.get("request_id"))\n',
            ),
        ),
        "todo-long-task": (
            lambda: _replace_once(
                workspace / "src" / "model.py",
                '        return {"name": self.name}\n',
                '        return {"name": self.name, "value": self.value}\n',
            ),
            lambda: _replace_once(
                workspace / "src" / "usecase.py",
                '    return Record(str(payload["name"]), 0)\n',
                '    return Record(str(payload["name"]), int(payload["value"]))\n',
            ),
            lambda: _replace_once(
                workspace / "tests" / "test_records.py",
                "    return False\n",
                '    return encode(decode({"name": "alpha", "value": 7})) == {"name": "alpha", "value": 7}\n',
            ),
        ),
        "plan-only": (),
        "ask-user-resume": (
            lambda: _replace_once(
                workspace / "src" / "choice.py",
                "    return value\n",
                "    return value.strip()\n",
            ),
        ),
        "permission-boundary": (
            lambda: _replace_once(
                workspace / "src" / "safe.py",
                "    return sum(values) - 1\n",
                "    return sum(values)\n",
            ),
        ),
        "long-context-constraint": (
            lambda: _replace_once(
                workspace / "src" / "implementation.py",
                'value.strip() + "!"\n',
                'value.strip() + "."\n',
            ),
        ),
    }[task_id]
    for operation in operations:
        operation()


def _apply_partial_patch(task_id: str, workspace: Path) -> None:
    operations = {
        "single-file-control": (),
        "cross-file-evidence": (
            lambda: (workspace / "src" / "cli.py").write_text(
                "from .application import handle\n\n\n"
                "def run(value: str, request_id: str | None = None) -> dict[str, str]:\n"
                "    return handle({\"value\": value, \"request_id\": request_id})\n",
                encoding="utf-8",
            ),
        ),
        "todo-long-task": (
            lambda: (workspace / "src" / "model.py").write_text(
                "class Record:\n"
                "    def __init__(self, name: str, value: int) -> None:\n"
                "        self.name = name\n"
                "        self.value = value\n\n"
                "    def to_dict(self) -> dict[str, object]:\n"
                "        return {\"name\": self.name, \"value\": self.value}\n",
                encoding="utf-8",
            ),
        ),
        "plan-only": (
            lambda: (workspace / "forbidden-side-effect.txt").write_text(
                "unexpected\n", encoding="utf-8"
            ),
        ),
        "ask-user-resume": (),
        "permission-boundary": (),
        "long-context-constraint": (),
    }[task_id]
    for operation in operations:
        operation()


@pytest.mark.parametrize("task_id", TASK_IDS)
def test_each_verifier_accepts_its_gold_like_fixture(task_id: str, tmp_path: Path) -> None:
    workspace = _fixture(task_id, tmp_path)
    # The task-specific gold-like edit stays local to this verifier contract
    # test; the production runner never injects a standard answer patch.
    _apply_fake_gold_patch(task_id, workspace)
    first = _run_verifier(task_id, workspace)
    second = _run_verifier(task_id, workspace)
    assert first == second
    assert first["success"] is True
    assert all(
        check["kind"] in {"hard", "partial", "forbidden"}
        for check in first["checks"]  # type: ignore[index]
    )


@pytest.mark.parametrize("task_id", TASK_IDS)
def test_each_verifier_rejects_partial_and_forbidden_variants(
    task_id: str, tmp_path: Path
) -> None:
    partial = _fixture(task_id, tmp_path / "partial")
    _apply_partial_patch(task_id, partial)
    partial_result = _run_verifier(task_id, partial)
    assert partial_result["success"] is False

    forbidden = _fixture(task_id, tmp_path / "forbidden")
    (forbidden / "forbidden-side-effect.txt").write_text(
        "must be rejected\n", encoding="utf-8"
    )
    forbidden_result = _run_verifier(task_id, forbidden)
    assert forbidden_result["success"] is False
    assert any(
        check["kind"] == "forbidden" and check["passed"] is False
        for check in forbidden_result["checks"]  # type: ignore[index]
    )


def test_verifier_sources_have_no_network_or_model_dependency() -> None:
    forbidden_tokens = ("socket", "urllib", "http.client", "requests", "openai", "anthropic")
    for task_id in TASK_IDS:
        source = (TASK_ROOT / task_id / "verify.py").read_text(encoding="utf-8").lower()
        assert not any(token in source for token in forbidden_tokens), task_id
