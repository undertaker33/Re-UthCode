from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from uthcode.core import CancellationToken
from uthcode.integrations.tools.git_tools import GitUnavailableError, GitWorkspace, GitWorkspaceTool


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=root, text=True, capture_output=True, check=True)


def _repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "--initial-branch=main")
    _git(tmp_path, "config", "user.email", "test@example.invalid")
    _git(tmp_path, "config", "user.name", "UthCode Test")
    (tmp_path / "tracked.txt").write_text("before\n", encoding="utf-8")
    _git(tmp_path, "add", "tracked.txt")
    _git(tmp_path, "commit", "-m", "initial")
    return tmp_path


def test_git_workspace_read_queries_and_special_paths(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    (root / "tracked.txt").write_text("after\n", encoding="utf-8")
    (root / "space name.txt").write_text("untracked\n", encoding="utf-8")
    workspace = GitWorkspace(root)

    status = workspace.status()
    assert status["entries"] == [
        {"xy": " M", "path": "tracked.txt"},
        {"xy": "??", "path": "space name.txt"},
    ]
    assert workspace.diff()["text"].find("-before") >= 0
    assert workspace.log(limit=1)["commits"][0]["subject"] == "initial"
    assert "before" in workspace.show(ref="HEAD", path="tracked.txt")["text"]
    branches = workspace.branch()
    assert branches["detached"] is False
    assert any(item["current"] and item["name"] == "main" for item in branches["branches"])
    assert branches["unborn"] is False


def test_git_workspace_reports_unborn_and_detached_states(tmp_path: Path) -> None:
    _git(tmp_path, "init", "--initial-branch=main")
    workspace = GitWorkspace(tmp_path)
    assert workspace.status()["unborn"] is True
    assert workspace.branch()["unborn"] is True
    (tmp_path / "file.txt").write_text("one\n", encoding="utf-8")
    _git(tmp_path, "config", "user.email", "test@example.invalid")
    _git(tmp_path, "config", "user.name", "UthCode Test")
    _git(tmp_path, "add", "file.txt")
    _git(tmp_path, "commit", "-m", "initial")
    _git(tmp_path, "checkout", "--detach", "HEAD")
    detached = workspace.branch()
    assert detached["detached"] is True
    assert detached["current"] is None


@pytest.mark.asyncio
async def test_git_workspace_tool_is_read_only_and_reports_non_git(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    tool = GitWorkspaceTool(root)
    prepared = tool.preflight({"operation": "status"})
    assert prepared.action.effect.value == "read"
    result = await tool.execute(prepared.execution_arguments, cancellation=CancellationToken())
    assert result.is_error is False
    assert json.loads(str(result.content))["operation"] == "status"

    non_repo_path = tmp_path.parent / f"{tmp_path.name}-non-repo"
    non_repo_path.mkdir()
    non_repo = GitWorkspaceTool(non_repo_path)
    unavailable = await non_repo.execute({"operation": "status"}, cancellation=CancellationToken())  # type: ignore[arg-type]
    assert unavailable.is_error is True
    assert unavailable.failure is not None
    assert unavailable.failure.kind == "unavailable"


def test_git_workspace_rejects_unsafe_inputs_and_missing_git(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    workspace = GitWorkspace(root)
    with pytest.raises(ValueError):
        workspace.diff(path="../outside")
    with pytest.raises(ValueError):
        workspace.show(ref="-c", path=None)
    with pytest.raises(GitUnavailableError):
        GitWorkspace(root, executable="git-command-that-does-not-exist").status()


def test_git_diff_disables_external_diff_and_optional_index_locks(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    (root / "tracked.txt").write_text("after\n", encoding="utf-8")
    marker = tmp_path / "external-diff-called.txt"
    external = tmp_path / "external-diff.cmd"
    external.write_text(
        f'@echo off\r\n>"{marker}" echo called\r\n',
        encoding="utf-8",
        newline="",
    )
    _git(root, "config", "diff.external", str(external))

    result = GitWorkspace(root).diff()

    assert "-before" in result["text"]
    assert marker.exists() is False
    assert (root / ".git" / "index.lock").exists() is False


def test_git_large_output_is_drained_with_a_bounded_result(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    (root / "tracked.txt").write_text("x\n" * 400_000, encoding="utf-8")

    result = GitWorkspace(root, max_output_bytes=1024).diff()

    assert result["truncated"] is True
    assert result["size_bytes"] <= 1024
