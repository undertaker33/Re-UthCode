"""Physical workspace isolation and manifest-backed cleanup for private Eval."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class WorkspaceSafetyError(ValueError):
    """Raised before an unsafe workspace write or deletion is attempted."""


_ROOT_MARKER = ".uthcode-eval-root.json"
_MANIFEST_NAME = "manifest.json"
_COMPONENTS = ("workspace", "home", "artifacts")


def _physical(path: Path) -> Path:
    try:
        return path.expanduser().resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise WorkspaceSafetyError("path could not be physically resolved") from exc


def _is_link(path: Path) -> bool:
    """Return true for symbolic links and Windows junctions."""

    try:
        if path.is_symlink():
            return True
        is_junction = getattr(path, "is_junction", None)
        return bool(is_junction()) if callable(is_junction) else False
    except OSError as exc:
        raise WorkspaceSafetyError("path type could not be inspected") from exc


def _absolute_input(path: Path) -> Path:
    candidate = path.expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    return candidate


def _reject_link_components(path: Path) -> None:
    """Reject a path whose existing components include a link or junction."""

    candidate = _absolute_input(path)
    current = Path(candidate.anchor)
    for part in candidate.parts[1:]:
        current /= part
        if current.exists() and _is_link(current):
            raise WorkspaceSafetyError("path must not contain a symbolic link or junction")


def _same_or_child(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _assert_external_root(repo: Path, candidate: Path, *, home: Path | None = None) -> None:
    user_home = _physical(home if home is not None else Path.home())
    anchor = _physical(Path(candidate.anchor))
    if candidate == repo or _same_or_child(candidate, repo):
        raise WorkspaceSafetyError("external root must be outside the source repository")
    if candidate == user_home:
        raise WorkspaceSafetyError("external root must not be the user home")
    if candidate == anchor or candidate.parent == candidate:
        raise WorkspaceSafetyError("external root must not be a filesystem root")


def _safe_identifier(value: str, field: str) -> str:
    if not isinstance(value, str) or not value or value in {".", ".."}:
        raise WorkspaceSafetyError(f"{field} must be a safe identifier")
    if any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-" for char in value):
        raise WorkspaceSafetyError(f"{field} must be a safe identifier")
    return value


def _ensure_directory(path: Path) -> Path:
    if path.exists() and (_is_link(path) or not path.is_dir()):
        raise WorkspaceSafetyError("directory target is not a directory")
    path.mkdir(parents=True, exist_ok=True)
    if _is_link(path):
        raise WorkspaceSafetyError("directory target must not be a symbolic link")
    return path


def _write_json(path: Path, payload: dict[str, object]) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _sha256_tree(path: Path) -> str:
    digest = hashlib.sha256()
    if path.is_file():
        digest.update(path.relative_to(path.parent).as_posix().encode())
        digest.update(path.read_bytes())
        return digest.hexdigest()
    for child in sorted(path.rglob("*"), key=lambda item: item.relative_to(path).as_posix()):
        relative = child.relative_to(path).as_posix()
        digest.update(relative.encode("utf-8"))
        if _is_link(child):
            raise WorkspaceSafetyError("fixture must not contain symbolic links")
        if child.is_file():
            digest.update(child.read_bytes())
    return digest.hexdigest()


def _validate_fixture(
    path: Path,
    repo_root: Path,
    eval_root: Path,
    destination_paths: tuple[Path, ...],
) -> Path:
    _reject_link_components(path)
    physical = _physical(path)
    if not physical.is_dir() or _is_link(path) or _is_link(physical):
        raise WorkspaceSafetyError("fixture must be a physical directory")
    if _same_or_child(physical, eval_root):
        raise WorkspaceSafetyError("fixture must be outside the Eval root")
    if physical == repo_root or not _same_or_child(physical, repo_root):
        raise WorkspaceSafetyError("fixture must be a physical child of the source repository")
    if any(
        _same_or_child(physical, destination)
        or _same_or_child(destination, physical)
        for destination in destination_paths
    ):
        raise WorkspaceSafetyError("fixture must be outside attempt destinations")
    for child in physical.rglob("*"):
        if _is_link(child):
            raise WorkspaceSafetyError("fixture must not contain symbolic links")
    return physical


@dataclass(frozen=True, slots=True)
class RepositorySnapshot:
    repo_root: Path
    entries: tuple[str, ...]


def _git_entries(repo_root: Path) -> tuple[str, ...]:
    try:
        completed = subprocess.run(
            ["git", "status", "--short", "--untracked-files=all"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise WorkspaceSafetyError("unable to read repository status") from exc
    return tuple(line for line in completed.stdout.splitlines() if line)


def capture_repository_snapshot(repo_root: Path) -> RepositorySnapshot:
    root = _physical(repo_root)
    if not (root / ".git").exists():
        raise WorkspaceSafetyError("repo_root must be a Git repository")
    return RepositorySnapshot(root, _git_entries(root))


def repository_status_delta(before: RepositorySnapshot, after: RepositorySnapshot) -> tuple[str, ...]:
    if before.repo_root != after.repo_root:
        raise WorkspaceSafetyError("repository snapshot roots do not match")
    return tuple(entry for entry in after.entries if entry not in before.entries)


def resolve_eval_root(repo_root: Path, external_root: Path, *, home: Path | None = None) -> Path:
    """Validate and initialize a dedicated root for all Eval runtime data."""

    repo = _physical(repo_root)
    if not repo.is_dir() or not (repo / ".git").exists():
        raise WorkspaceSafetyError("repo_root must be a Git repository directory")
    _reject_link_components(external_root)
    candidate = _physical(external_root)
    _assert_external_root(repo, candidate, home=home)
    existed = candidate.exists()
    if existed and (_is_link(candidate) or not candidate.is_dir()):
        raise WorkspaceSafetyError("external root must be a physical directory")
    marker = candidate / _ROOT_MARKER
    if existed and not marker.exists():
        raise WorkspaceSafetyError("external root is not a dedicated Eval directory")
    candidate.mkdir(parents=True, exist_ok=True)
    if _is_link(candidate):
        raise WorkspaceSafetyError("external root must not be a symbolic link")
    if marker.exists():
        if _is_link(marker) or not marker.is_file():
            raise WorkspaceSafetyError("Eval root marker is not a regular file")
        try:
            payload = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise WorkspaceSafetyError("Eval root marker is invalid") from exc
        if not isinstance(payload, dict) or payload.get("kind") != "uthcode-eval-root":
            raise WorkspaceSafetyError("path is not a dedicated Eval root")
        marker_repo = payload.get("repo_root")
        if not isinstance(marker_repo, str):
            raise WorkspaceSafetyError("Eval root marker has no source repository")
        if _physical(Path(marker_repo)) != repo:
            raise WorkspaceSafetyError("Eval root is already bound to another repository")
    else:
        _write_json(marker, {"kind": "uthcode-eval-root", "schema_version": 1, "repo_root": str(repo)})
    for name in ("workspaces", "homes", "artifacts", "cache", "reports"):
        _ensure_directory(candidate / name)
    return candidate


@dataclass(frozen=True, slots=True)
class AttemptPaths:
    repo_root: Path
    eval_root: Path
    experiment_id: str
    task_id: str
    attempt_id: str
    workspace: Path
    home: Path
    artifacts: Path
    manifest: Path
    fixture_sha256: str


def _attempt_component(root: Path, experiment_id: str, task_id: str, attempt_id: str, component: str) -> Path:
    return root / component / experiment_id / task_id / attempt_id


def _validate_attempt_paths(root: Path, experiment_id: str, task_id: str, attempt_id: str) -> dict[str, Path]:
    ids = {
        "experiment_id": _safe_identifier(experiment_id, "experiment_id"),
        "task_id": _safe_identifier(task_id, "task_id"),
        "attempt_id": _safe_identifier(attempt_id, "attempt_id"),
    }
    paths: dict[str, Path] = {}
    for component in _COMPONENTS:
        lexical = _attempt_component(root, ids["experiment_id"], ids["task_id"], ids["attempt_id"], component)
        if lexical.exists() and _is_link(lexical):
            raise WorkspaceSafetyError(f"{component} path must not be a symbolic link")
        path = _physical(lexical)
        if path != lexical:
            raise WorkspaceSafetyError(f"{component} path must not traverse a symbolic link")
        if not _same_or_child(path, root) or path == root:
            raise WorkspaceSafetyError(f"{component} path escapes Eval root")
        paths[component] = path
    return paths


def create_attempt(
    repo_root: Path,
    eval_root: Path,
    experiment_id: str,
    task_id: str,
    attempt_id: str,
    fixture: Path,
) -> AttemptPaths:
    repo = _physical(repo_root)
    _reject_link_components(eval_root)
    root = _physical(eval_root)
    _assert_external_root(repo, root)
    if not (root / _ROOT_MARKER).is_file() or _is_link(root / _ROOT_MARKER):
        raise WorkspaceSafetyError("eval_root is not a dedicated initialized root")
    try:
        marker = json.loads((root / _ROOT_MARKER).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise WorkspaceSafetyError("eval_root marker is invalid") from exc
    if (
        not isinstance(marker, dict)
        or marker.get("kind") != "uthcode-eval-root"
        or marker.get("schema_version") != 1
        or not isinstance(marker.get("repo_root"), str)
        or _physical(Path(marker["repo_root"])) != repo
    ):
        raise WorkspaceSafetyError("eval_root is bound to a different source repository")
    paths = _validate_attempt_paths(root, experiment_id, task_id, attempt_id)
    fixture_path = _validate_fixture(fixture, repo, root, tuple(paths.values()))
    if any(path.exists() for path in paths.values()):
        raise WorkspaceSafetyError("attempt already exists")
    manifest = paths["artifacts"] / _MANIFEST_NAME
    _ensure_directory(paths["artifacts"].parent)
    _ensure_directory(paths["artifacts"])
    initial = {
        "kind": "uthcode-eval-attempt",
        "schema_version": 1,
        "status": "creating",
        "repo_root": str(repo),
        "eval_root": str(root),
        "experiment_id": experiment_id,
        "task_id": task_id,
        "attempt_id": attempt_id,
        "workspace": str(paths["workspace"]),
        "home": str(paths["home"]),
        "artifacts": str(paths["artifacts"]),
        "components": {name: str(path) for name, path in paths.items()},
    }
    _write_json(manifest, initial)
    try:
        _ensure_directory(paths["workspace"].parent)
        _ensure_directory(paths["home"].parent)
        shutil.copytree(fixture_path, paths["workspace"])
        _ensure_directory(paths["home"])
        fixture_hash = _sha256_tree(fixture_path)
        _write_json(
            manifest,
            {
                **initial,
                "status": "ready",
                "fixture": str(fixture_path),
                "fixture_sha256": fixture_hash,
                "components": {name: str(path) for name, path in paths.items()},
            },
        )
    except BaseException as exc:
        _write_json(manifest, {**initial, "status": "creation_failed", "error_type": type(exc).__name__})
        raise
    return AttemptPaths(
        repo,
        root,
        experiment_id,
        task_id,
        attempt_id,
        paths["workspace"],
        paths["home"],
        paths["artifacts"],
        manifest,
        fixture_hash,
    )


def _validate_clean_target(
    root: Path,
    name: str,
    component: Path,
    manifest_payload: dict[str, Any],
) -> None:
    resolved = _physical(component)
    if resolved != component or not _same_or_child(resolved, root) or resolved == root:
        raise WorkspaceSafetyError("clean target is outside the dedicated Eval root")
    if _is_link(component):
        raise WorkspaceSafetyError("clean target must be a physical directory")
    if not component.exists():
        return
    if not component.is_dir():
        raise WorkspaceSafetyError("clean target must be a physical directory")
    for item in component.rglob("*"):
        if _is_link(item):
            raise WorkspaceSafetyError(f"clean target contains a link: {item.name}")
    components = manifest_payload.get("components")
    expected = components.get(name) if isinstance(components, dict) else None
    if not isinstance(expected, str) or _physical(Path(expected)) != component:
        raise WorkspaceSafetyError("manifest component does not match clean target")


def clean_attempt(
    eval_root: Path,
    experiment_id: str | None = None,
    task_id: str | None = None,
    attempt_id: str | None = None,
) -> tuple[Path, ...]:
    """Delete exactly one manifest-owned attempt after all safety checks pass."""

    _reject_link_components(eval_root)
    root = _physical(eval_root)
    marker = root / _ROOT_MARKER
    if not root.is_dir() or _is_link(root) or not marker.is_file() or _is_link(marker):
        raise WorkspaceSafetyError("clean requires a dedicated Eval root")
    if experiment_id is None or task_id is None or attempt_id is None:
        raise WorkspaceSafetyError("clean requires experiment, task and attempt identifiers")
    paths = _validate_attempt_paths(root, experiment_id, task_id, attempt_id)
    manifest = paths["artifacts"] / _MANIFEST_NAME
    if not manifest.is_file() or _is_link(manifest):
        raise WorkspaceSafetyError("clean requires a manifest-owned attempt")
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise WorkspaceSafetyError("attempt manifest is invalid") from exc
    if not isinstance(payload, dict) or payload.get("kind") != "uthcode-eval-attempt":
        raise WorkspaceSafetyError("attempt manifest is invalid")
    marker_repo = payload.get("repo_root")
    if not isinstance(marker_repo, str):
        raise WorkspaceSafetyError("attempt manifest has no source repository")
    source_repo = _physical(Path(marker_repo))
    if not source_repo.is_dir() or not (source_repo / ".git").exists():
        raise WorkspaceSafetyError("attempt manifest source repository is invalid")
    try:
        root_marker = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise WorkspaceSafetyError("Eval root marker is invalid") from exc
    if (
        not isinstance(root_marker, dict)
        or root_marker.get("kind") != "uthcode-eval-root"
        or root_marker.get("schema_version") != 1
        or root_marker.get("repo_root") != str(source_repo)
    ):
        raise WorkspaceSafetyError("Eval root marker does not match the attempt")
    _assert_external_root(source_repo, root)
    if (
        payload.get("eval_root") != str(root)
        or payload.get("experiment_id") != experiment_id
        or payload.get("task_id") != task_id
        or payload.get("attempt_id") != attempt_id
    ):
        raise WorkspaceSafetyError("attempt manifest identity mismatch")
    if payload.get("status") not in {"ready", "creation_failed"}:
        raise WorkspaceSafetyError("attempt manifest is not cleanable")
    expected = {
        "workspace": paths["workspace"],
        "home": paths["home"],
        "artifacts": paths["artifacts"],
    }
    for name, component in expected.items():
        manifest_path = payload.get(name)
        if not isinstance(manifest_path, str) or _physical(Path(manifest_path)) != component:
            raise WorkspaceSafetyError("attempt manifest target mismatch")
        _validate_clean_target(root, name, component, payload)
    for component in expected.values():
        if component.exists():
            shutil.rmtree(component)
    return tuple(expected.values())


repository_fingerprint = capture_repository_snapshot
