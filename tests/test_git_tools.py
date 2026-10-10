from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from uthcode.core import CancellationToken
from uthcode.integrations.tools.git_tools import (
    GitQueryCancelled,
    GitUnavailableError,
    GitWorkspace,
    GitWorkspaceTool,
)


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
        workspace.diff(path="nested/../tracked.txt")
    with pytest.raises(ValueError):
        workspace.diff(path="C:\\outside.txt")
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


def test_workspace_review_separates_staged_unstaged_and_untracked_state(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    tracked = root / "tracked.txt"
    tracked.write_text("staged version\n", encoding="utf-8")
    _git(root, "add", "tracked.txt")
    tracked.write_text("unstaged version\n", encoding="utf-8")
    (root / "new file.txt").write_text("untracked body\n", encoding="utf-8")

    result = GitWorkspace(root).review()

    status = result["status"]
    assert isinstance(status, dict)
    entries = status["entries"]
    assert {entry["path"]: entry["xy"] for entry in entries} == {
        "tracked.txt": "MM",
        "new file.txt": "??",
    }
    staged = result["staged_diff"]
    unstaged = result["unstaged_diff"]
    assert isinstance(staged, dict) and isinstance(unstaged, dict)
    assert "-before" in staged["text"] and "+staged version" in staged["text"]
    assert "-staged version" in unstaged["text"] and "+unstaged version" in unstaged["text"]
    assert "untracked body" not in staged["text"] + unstaged["text"]
    assert result["truncated"] is False


def test_workspace_review_reports_rename_and_selected_file_paths(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    _git(root, "mv", "tracked.txt", "renamed.txt")

    all_changes = GitWorkspace(root).review()
    status = all_changes["status"]
    assert isinstance(status, dict)
    renamed = next(entry for entry in status["entries"] if entry["path"] == "renamed.txt")
    assert "R" in renamed["xy"]
    assert renamed["original_path"] == "tracked.txt"

    selected = GitWorkspace(root).review(path="renamed.txt")
    staged = selected["staged_diff"]
    assert isinstance(staged, dict)
    assert "a/tracked.txt" in staged["text"]
    assert "b/renamed.txt" in staged["text"]
    with pytest.raises(ValueError):
        GitWorkspace(root).review(path="../outside.txt")


def test_workspace_review_reports_deletion_binary_and_bounded_partial_diff(
    tmp_path: Path,
) -> None:
    root = _repo(tmp_path)
    (root / "tracked.txt").unlink()
    binary = root / "binary.bin"
    binary.write_bytes(b"\x00\x01original")
    _git(root, "add", "binary.bin")
    _git(root, "commit", "-m", "binary")
    binary.write_bytes(b"\x00\x02changed")

    result = GitWorkspace(root).review()
    status = result["status"]
    assert isinstance(status, dict)
    by_path = {entry["path"]: entry["xy"] for entry in status["entries"]}
    assert by_path["tracked.txt"] == " D"
    assert by_path["binary.bin"] == " M"
    unstaged = result["unstaged_diff"]
    assert isinstance(unstaged, dict)
    assert "-before" in unstaged["text"]
    assert "Binary files a/binary.bin and b/binary.bin differ" in unstaged["text"]

    (root / "large.txt").write_text("line\n" * 20_000, encoding="utf-8")
    _git(root, "add", "large.txt")
    bounded = GitWorkspace(root, max_output_bytes=1024).review()
    large_diff = bounded["staged_diff"]
    assert isinstance(large_diff, dict)
    assert large_diff["truncated"] is True
    assert large_diff["size_bytes"] <= 1024
    assert bounded["truncated"] is True


def test_workspace_review_preserves_non_git_and_cancellation_outcomes(
    tmp_path: Path,
) -> None:
    with pytest.raises(GitUnavailableError):
        GitWorkspace(tmp_path).review()
    repository = tmp_path / "repo"
    repository.mkdir()
    root = _repo(repository)
    token = CancellationToken()
    token.cancel()
    with pytest.raises(GitQueryCancelled):
        GitWorkspace(root).review(cancellation=token)
