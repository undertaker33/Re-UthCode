"""Workspace path and read-state safeguards for file and search tools."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path


class WorkspacePathError(ValueError):
    """Raised when a path cannot be safely resolved inside the workspace."""


_NOT_READ = "Error: file has not been read yet. Read it first before editing."
_CHANGED = "Error: file has been modified since last read. Read it again before editing."


class WorkspacePathResolver:
    """Resolve existing and new paths without allowing workspace escape."""

    def __init__(self, workdir: str | os.PathLike[str] | Path) -> None:
        raw_workdir = os.fspath(workdir)
        if "\x00" in raw_workdir:
            raise WorkspacePathError("Error: path contains null byte")
        self._root = Path(raw_workdir).expanduser().resolve(strict=False)

    @property
    def root(self) -> Path:
        return self._root

    def lexical_path(self, path: str | os.PathLike[str] | Path) -> Path:
        """Return a normalized path before following any symlink target."""

        raw_path = os.fspath(path)
        if "\x00" in raw_path:
            raise WorkspacePathError("Error: path contains null byte")
        candidate = Path(raw_path).expanduser()
        if not candidate.is_absolute():
            candidate = self._root / candidate
        # ``abspath`` normalizes ``..`` lexically but does not resolve links.
        return Path(os.path.normpath(os.path.abspath(os.fspath(candidate))))

    def resolve(self, path: str | os.PathLike[str] | Path) -> Path:
        """Resolve an existing path or safely construct a new path.

        Existing paths are resolved strictly.  For a new path, only the
        nearest existing parent is resolved strictly, so creating a new file
        does not require the whole parent chain to exist first.
        """

        candidate = self.lexical_path(path)
        self._require_within(candidate)

        try:
            if candidate.exists() or candidate.is_symlink():
                resolved = candidate.resolve(strict=True)
            else:
                resolved = self._resolve_new(candidate)
        except (OSError, RuntimeError) as exc:
            raise WorkspacePathError("Error: path cannot be resolved") from exc

        self._require_within(resolved)
        return resolved

    def display(self, path: str | os.PathLike[str] | Path) -> str:
        """Return a stable workspace-relative POSIX display path."""

        candidate = self.lexical_path(path)
        try:
            relative = candidate.relative_to(self._root)
        except ValueError:
            return str(candidate)
        return relative.as_posix() or "."

    def validate_candidate(self, path: str | os.PathLike[str] | Path) -> Path | None:
        """Return a safe candidate's physical path, otherwise ``None``.

        Search tools use this for every file returned by their walker.  A
        candidate must pass both the lexical and physical workspace checks.
        """

        try:
            lexical = self.lexical_path(path)
            self._require_within(lexical)
            resolved = Path(path).resolve(strict=True)
            self._require_within(resolved)
            return resolved
        except (OSError, RuntimeError, WorkspacePathError):
            return None

    def has_directory_symlink(self, path: str | os.PathLike[str] | Path) -> bool:
        """Return whether a path contains a directory symlink component."""

        lexical = self.lexical_path(path)
        self._require_within(lexical)
        current = self._root
        for part in lexical.relative_to(self._root).parts:
            current /= part
            try:
                if current.is_symlink() and current.is_dir():
                    return True
            except OSError:
                # An unreadable link is not safe to traverse.
                return True
        return False

    def _resolve_new(self, candidate: Path) -> Path:
        missing_parts = [candidate.name]
        parent = candidate.parent
        while not parent.exists() and not parent.is_symlink():
            if parent == parent.parent:
                raise WorkspacePathError("Error: path cannot be resolved")
            missing_parts.insert(0, parent.name)
            parent = parent.parent

        resolved_parent = parent.resolve(strict=True)
        return resolved_parent.joinpath(*missing_parts)

    def _require_within(self, path: Path) -> None:
        try:
            path.relative_to(self._root)
        except ValueError as exc:
            raise WorkspacePathError("Error: path is outside the workspace") from exc


@dataclass(frozen=True, slots=True)
class _FileState:
    path: Path
    text_digest: str
    raw_digest: str
    size: int
    mtime_ns: int
    identity: tuple[int, int] | None


class FileReadTracker:
    """Track the exact state observed by a successful file read."""

    def __init__(self) -> None:
        self._states: dict[Path, _FileState] = {}

    def record(self, path: str | os.PathLike[str] | Path, content: str, mtime_ns: int | None = None) -> None:
        """Record content and metadata for one normalized physical file."""

        if not isinstance(content, str):
            raise TypeError("content must be a string")
        resolved = Path(path).resolve(strict=True)
        stat = resolved.stat()
        self._states[resolved] = _FileState(
            path=resolved,
            text_digest=_digest_text(content),
            raw_digest=_digest_bytes(resolved.read_bytes()),
            size=stat.st_size,
            mtime_ns=stat.st_mtime_ns if mtime_ns is None else mtime_ns,
            identity=_stat_identity(stat),
        )

    def check(self, path: str | os.PathLike[str] | Path) -> tuple[bool, str]:
        """Check that a previously read file is unchanged and still present."""

        try:
            resolved = Path(path).resolve(strict=False)
        except (OSError, RuntimeError):
            return False, _CHANGED
        state = self._states.get(resolved)
        if state is None:
            return False, _NOT_READ

        try:
            stat = resolved.stat()
            if not resolved.is_file():
                return False, _CHANGED
            raw = resolved.read_bytes()
            content = resolved.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return False, _CHANGED

        if (
            _digest_text(content) != state.text_digest
            or _digest_bytes(raw) != state.raw_digest
            or stat.st_size != state.size
            or stat.st_mtime_ns != state.mtime_ns
            or _stat_changed(state.identity, _stat_identity(stat))
        ):
            return False, _CHANGED
        return True, ""

    def has_record(self, path: str | os.PathLike[str] | Path) -> bool:
        """Return whether a physical path was previously observed."""

        try:
            resolved = Path(path).resolve(strict=False)
        except (OSError, RuntimeError):
            return False
        return resolved in self._states

    def update(self, path: str | os.PathLike[str] | Path) -> None:
        """Refresh state after a successful write or edit."""

        try:
            resolved = Path(path).resolve(strict=True)
            content = resolved.read_text(encoding="utf-8")
            self.record(resolved, content)
        except (OSError, UnicodeDecodeError, RuntimeError):
            self.forget(path)

    def forget(self, path: str | os.PathLike[str] | Path) -> None:
        """Forget one physical file state."""

        try:
            resolved = Path(path).resolve(strict=False)
        except (OSError, RuntimeError):
            return
        self._states.pop(resolved, None)


def _digest_text(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _digest_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _stat_identity(stat: os.stat_result) -> tuple[int, int] | None:
    device = int(getattr(stat, "st_dev", 0))
    inode = int(getattr(stat, "st_ino", 0))
    if device == 0 and inode == 0:
        return None
    return device, inode


def _stat_changed(
    recorded: tuple[int, int] | None,
    current: tuple[int, int] | None,
) -> bool:
    return recorded is not None and current is not None and recorded != current


__all__ = [
    "FileReadTracker",
    "WorkspacePathError",
    "WorkspacePathResolver",
]
