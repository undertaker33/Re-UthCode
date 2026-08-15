"""Physical file access for the Application-owned instruction loader.

This module deliberately knows about paths, links, encodings, and file
identity only.  It does not decide which instruction scopes are active or how
an instruction epoch changes.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path


class InstructionFileError(RuntimeError):
    """A physical instruction source could not be safely read."""


class InstructionFilePathError(InstructionFileError):
    """A path escaped its trusted root or traversed a link component."""


class InstructionFileReadError(InstructionFileError):
    """A source was not a regular UTF-8 file."""


@dataclass(frozen=True, slots=True)
class InstructionFile:
    """The physical evidence returned to the Application layer."""

    path: Path
    identity: str
    content: str
    content_fingerprint: str

    def __post_init__(self) -> None:
        if not isinstance(self.path, Path):
            object.__setattr__(self, "path", Path(self.path))
        if not isinstance(self.identity, str) or not self.identity:
            raise ValueError("identity must be a non-empty string")
        if not isinstance(self.content, str):
            raise TypeError("content must be a string")
        if not isinstance(self.content_fingerprint, str) or not self.content_fingerprint:
            raise ValueError("content_fingerprint must be a non-empty string")


class InstructionFileReader:
    """Read UTF-8 instruction files and expose stable physical identities."""

    def canonical_path(
        self,
        path: str | os.PathLike[str] | Path,
        *,
        trusted_root: str | os.PathLike[str] | Path | None = None,
        base_dir: str | os.PathLike[str] | Path | None = None,
        relative_only: bool = False,
    ) -> Path:
        raw = os.fspath(path)
        if "\x00" in raw:
            raise InstructionFilePathError("instruction path contains a null byte")
        value = Path(raw)
        if relative_only and value.is_absolute():
            raise InstructionFilePathError("instruction include must be relative")
        if ".." in value.parts:
            raise InstructionFilePathError("instruction path contains a parent component")
        if base_dir is not None and not value.is_absolute():
            value = Path(base_dir) / value
        elif trusted_root is not None and not value.is_absolute():
            value = Path(trusted_root) / value
        candidate = Path(os.path.normpath(os.fspath(value.expanduser())))
        if trusted_root is not None:
            root = Path(trusted_root).expanduser().resolve(strict=False)
            try:
                candidate.relative_to(root)
            except ValueError as exc:
                raise InstructionFilePathError(
                    f"instruction path is outside trusted root: {candidate}"
                ) from exc
            # Inspect the lexical path before resolving it; resolving first
            # would erase the evidence that a symlink/junction was traversed.
            self._reject_link_components(candidate, root)
        normalized = candidate.resolve(strict=False)
        if trusted_root is not None:
            try:
                normalized.relative_to(root)
            except ValueError as exc:
                raise InstructionFilePathError(
                    f"instruction path resolves outside trusted root: {normalized}"
                ) from exc
        return normalized

    def identity(self, path: str | os.PathLike[str] | Path) -> str:
        normalized = Path(path).resolve(strict=False)
        try:
            stat = normalized.stat()
        except OSError:
            stat = None
        if stat is not None:
            device = int(getattr(stat, "st_dev", 0))
            inode = int(getattr(stat, "st_ino", 0))
            if device or inode:
                return f"stat:{device}:{inode}"
        # casefold is intentional even on a non-Windows test host: the
        # persisted identity must be portable to Windows.
        lexical = os.path.normpath(os.fspath(normalized)).casefold()
        return f"path:{lexical}"

    def read(
        self,
        path: str | os.PathLike[str] | Path,
        *,
        trusted_root: str | os.PathLike[str] | Path | None = None,
    ) -> InstructionFile:
        normalized = self.canonical_path(path, trusted_root=trusted_root)
        if not normalized.exists():
            raise InstructionFileReadError(f"instruction source does not exist: {normalized}")
        if not normalized.is_file():
            raise InstructionFileReadError(f"instruction source is not a regular file: {normalized}")
        try:
            content = normalized.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise InstructionFileReadError(
                f"instruction source could not be read: {normalized}: {exc}"
            ) from exc
        fingerprint = hashlib.sha256(content.encode("utf-8")).hexdigest()
        return InstructionFile(
            path=normalized,
            identity=self.identity(normalized),
            content=content,
            content_fingerprint=fingerprint,
        )

    def exists(
        self,
        path: str | os.PathLike[str] | Path,
        *,
        trusted_root: str | os.PathLike[str] | Path | None = None,
    ) -> bool:
        normalized = self.canonical_path(path, trusted_root=trusted_root)
        return normalized.is_file()

    @staticmethod
    def _reject_link_components(path: Path, root: Path) -> None:
        try:
            relative = path.relative_to(root)
        except ValueError as exc:  # pragma: no cover - canonical_path guards this.
            raise InstructionFilePathError(str(path)) from exc
        current = root
        for part in relative.parts:
            current = current / part
            try:
                is_junction = bool(getattr(current, "is_junction", lambda: False)())
                if current.is_symlink() or is_junction:
                    raise InstructionFilePathError(
                        f"instruction path traverses a link component: {path}"
                    )
            except OSError as exc:
                raise InstructionFilePathError(
                    f"instruction path component cannot be inspected: {path}"
                ) from exc


def discover_project_root(
    workdir: str | os.PathLike[str] | Path,
) -> Path:
    """Return the nearest Git root, or the normalized workdir if none exists."""

    current = Path(workdir).expanduser().resolve(strict=False)
    if current.is_file():
        current = current.parent
    for directory in (current, *current.parents):
        marker = directory / ".git"
        if marker.is_dir() or marker.is_file():
            return directory
    return current


__all__ = [
    "InstructionFile",
    "InstructionFileError",
    "InstructionFilePathError",
    "InstructionFileReadError",
    "InstructionFileReader",
    "discover_project_root",
]
