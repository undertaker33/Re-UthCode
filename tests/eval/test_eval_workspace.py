from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from eval.workspace import (
    WorkspaceSafetyError,
    capture_repository_snapshot,
    clean_attempt,
    create_attempt,
    repository_status_delta,
    resolve_eval_root,
)


def _git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(
        ["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True
    )
    return repo


def _fixture(repo: Path) -> Path:
    fixture = repo / "fixture"
    (fixture / "src").mkdir(parents=True)
    (fixture / "src" / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    (fixture / "instruction.md").write_text("inspect\n", encoding="utf-8")
    return fixture


def test_external_root_is_physical_and_rejects_repo_home_and_filesystem_roots(
    tmp_path: Path,
) -> None:
    repo = _git_repo(tmp_path)
    home = tmp_path / "user-home"
    home.mkdir()

    accepted = resolve_eval_root(repo, tmp_path / "external-eval", home=home)
    assert accepted.is_dir()
    assert (accepted / ".uthcode-eval-root.json").is_file()

    for unsafe in (repo, repo / "nested", home, Path(home.anchor)):
        with pytest.raises(WorkspaceSafetyError):
            resolve_eval_root(repo, unsafe, home=home)

    link = tmp_path / "repo-link"
    try:
        link.symlink_to(repo, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symbolic links are unavailable")
    with pytest.raises(WorkspaceSafetyError):
        resolve_eval_root(repo, link, home=home)


def test_external_root_under_home_is_allowed_but_home_root_is_rejected(
    tmp_path: Path,
) -> None:
    repo = _git_repo(tmp_path)
    home = tmp_path / "user-home"
    home.mkdir()

    accepted = resolve_eval_root(repo, home / "uthcode-eval", home=home)
    assert accepted == home / "uthcode-eval"

    with pytest.raises(WorkspaceSafetyError, match="user home"):
        resolve_eval_root(repo, home, home=home)


def test_existing_unmarked_directory_is_not_claimed_as_eval_root(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    candidate = tmp_path / "existing"
    candidate.mkdir()
    (candidate / "keep.txt").write_text("do not claim\n", encoding="utf-8")

    with pytest.raises(WorkspaceSafetyError, match="dedicated"):
        resolve_eval_root(repo, candidate)
    assert not (candidate / ".uthcode-eval-root.json").exists()


def test_same_repository_can_reopen_its_marked_eval_root(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    candidate = resolve_eval_root(repo, tmp_path / "external-eval")

    assert resolve_eval_root(repo, candidate) == candidate


def test_attempt_copies_fixture_and_preserves_dirty_repository_state(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    existing = repo / "existing-user-change.txt"
    existing.write_text("keep me\n", encoding="utf-8")
    fixture = _fixture(repo)
    before = capture_repository_snapshot(repo)
    fixture_before = (fixture / "src" / "module.py").read_bytes()
    root = resolve_eval_root(repo, tmp_path / "external-eval")

    attempt = create_attempt(repo, root, "exp-1", "single-file-control", "a-1", fixture)

    assert attempt.workspace.is_relative_to(root)
    assert attempt.home.is_relative_to(root)
    assert attempt.artifacts.is_relative_to(root)
    assert (attempt.workspace / "src" / "module.py").read_bytes() == fixture_before
    assert (fixture / "src" / "module.py").read_bytes() == fixture_before
    assert attempt.manifest.is_file()
    manifest = json.loads(attempt.manifest.read_text(encoding="utf-8"))
    assert manifest["status"] == "ready"
    assert manifest["fixture_sha256"] == attempt.fixture_sha256

    after = capture_repository_snapshot(repo)
    assert repository_status_delta(before, after) == ()
    assert any("existing-user-change.txt" in item for item in before.entries)

    with pytest.raises(WorkspaceSafetyError, match="already exists"):
        create_attempt(repo, root, "exp-1", "single-file-control", "a-1", fixture)


def test_attempt_rejects_fixture_outside_repo_and_eval_root_without_residue(
    tmp_path: Path,
) -> None:
    repo = _git_repo(tmp_path)
    fixture = _fixture(repo)
    root = resolve_eval_root(repo, tmp_path / "external-eval")
    outside = tmp_path / "outside-fixture"
    outside.mkdir()

    with pytest.raises(WorkspaceSafetyError, match="physical child"):
        create_attempt(repo, root, "exp-1", "task", "outside", outside)
    with pytest.raises(WorkspaceSafetyError, match="physical child"):
        create_attempt(repo, root, "exp-1", "task", "repo-root", repo)
    with pytest.raises(WorkspaceSafetyError, match="outside the Eval root"):
        create_attempt(repo, root, "exp-1", "task", "eval-root", root)

    for attempt_id in ("outside", "repo-root", "eval-root"):
        assert not (root / "artifacts" / "exp-1" / "task" / attempt_id).exists()


def test_partial_attempt_creation_keeps_manifest_and_does_not_touch_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _git_repo(tmp_path)
    fixture = _fixture(repo)
    root = resolve_eval_root(repo, tmp_path / "external-eval")
    before = capture_repository_snapshot(repo)

    def fail_copy(*_args: object, **_kwargs: object) -> None:
        raise OSError("copy failed")

    monkeypatch.setattr("eval.workspace.shutil.copytree", fail_copy)
    with pytest.raises(OSError, match="copy failed"):
        create_attempt(repo, root, "exp-1", "task", "a-1", fixture)

    manifest = root / "artifacts" / "exp-1" / "task" / "a-1" / "manifest.json"
    assert manifest.is_file()
    assert json.loads(manifest.read_text(encoding="utf-8"))["status"] == "creation_failed"
    assert repository_status_delta(before, capture_repository_snapshot(repo)) == ()


def test_clean_requires_exact_manifest_and_deletes_only_one_attempt(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    fixture = _fixture(repo)
    root = resolve_eval_root(repo, tmp_path / "external-eval")
    first = create_attempt(repo, root, "exp-1", "task", "a-1", fixture)
    second = create_attempt(repo, root, "exp-1", "task", "a-2", fixture)

    cleaned = clean_attempt(root, "exp-1", "task", "a-1")
    assert set(cleaned) == {first.workspace, first.home, first.artifacts}
    assert not first.workspace.exists()
    assert not first.home.exists()
    assert not first.artifacts.exists()
    assert second.workspace.is_dir()
    assert second.home.is_dir()
    assert second.artifacts.is_dir()
    assert root.is_dir()
    assert (root / ".uthcode-eval-root.json").is_file()

    with pytest.raises(WorkspaceSafetyError):
        clean_attempt(root, "exp-1", "task", "a-1")
    with pytest.raises(WorkspaceSafetyError):
        clean_attempt(repo)
    with pytest.raises(WorkspaceSafetyError):
        clean_attempt(root)


def test_clean_stops_before_deleting_an_attempt_containing_a_link(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    fixture = _fixture(repo)
    root = resolve_eval_root(repo, tmp_path / "external-eval")
    attempt = create_attempt(repo, root, "exp-1", "task", "a-1", fixture)
    link = attempt.workspace / "link"
    try:
        link.symlink_to(repo / "fixture", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symbolic links are unavailable")

    with pytest.raises(WorkspaceSafetyError, match="link"):
        clean_attempt(root, "exp-1", "task", "a-1")
    assert attempt.workspace.is_dir()
    assert attempt.home.is_dir()
    assert attempt.artifacts.is_dir()
