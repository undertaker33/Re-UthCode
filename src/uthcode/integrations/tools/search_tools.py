"""Workspace-safe file matching and Python regular-expression search."""

from __future__ import annotations

import fnmatch
import os
import re
from collections.abc import Iterator, Mapping, Sequence
from functools import lru_cache
from pathlib import Path, PureWindowsPath

from uthcode.core.permission import Effect, PermissionAction, ResourceScope
from uthcode.core.provider import CancellationToken, JsonPayload, ToolDefinition
from uthcode.core.tool import ToolExecutionResult, ToolPlanningAccess, ToolPreparation
from uthcode.integrations.permissions import is_sensitive_resource

from .workspace import WorkspacePathError, WorkspacePathResolver


_SKIP_DIR_NAMES = frozenset(
    {".git", ".venv", "node_modules", "__pycache__", ".tox", ".mypy_cache", ".pytest_cache"}
)
_CANCELLED = "Error: tool call cancelled"
_PREPARED_FILES = "__uthcode_prepared_files"


class GlobTool:
    """Find safe workspace files with deterministic relative paths."""

    _definition = ToolDefinition(
        "Glob",
        "Find workspace files with a relative glob pattern; directory links are not followed.",
        {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "minLength": 1},
                "path": {"type": "string", "default": "."},
            },
            "required": ["pattern"],
            "additionalProperties": False,
        },
    )

    def __init__(self, resolver: WorkspacePathResolver) -> None:
        self._resolver = resolver

    @property
    def definition(self) -> ToolDefinition:
        return self._definition

    @property
    def planning_access(self) -> ToolPlanningAccess:
        return ToolPlanningAccess.READ_ONLY

    def preflight(self, arguments: JsonPayload) -> ToolPreparation:
        _relative_pattern(_text(arguments, "pattern"), "pattern")
        base_lexical, base, scope = _resolve_base(
            self._resolver,
            _text(arguments, "path", default="."),
        )
        return ToolPreparation(
            action=PermissionAction(
                tool="Glob",
                action="glob",
                effect=Effect.READ,
                resource=self._resolver.display(base),
                scope=scope,
            ),
            execution_arguments=_bind_search_files(
                arguments,
                base_lexical,
                tuple(_safe_files(self._resolver, base_lexical, base)),
            ),
        )

    async def execute(
        self,
        arguments: JsonPayload,
        *,
        cancellation: CancellationToken,
    ) -> ToolExecutionResult:
        if cancellation.cancelled:
            return _cancelled()
        try:
            pattern = _relative_pattern(_text(arguments, "pattern"), "pattern")
            prepared_rows = _prepared_search_files(arguments)
            if prepared_rows is None:
                base_lexical, base, _ = _resolve_base(
                    self._resolver,
                    _text(arguments, "path", default="."),
                )
        except (WorkspacePathError, TypeError, ValueError) as exc:
            return _error(str(exc))

        matches: list[str] = []
        if prepared_rows is None:
            candidates = (
                (
                    candidate.relative_to(base_lexical).as_posix(),
                    candidate,
                )
                for candidate, _ in _safe_files(self._resolver, base_lexical, base)
            )
        else:
            candidates = ((relative, physical) for relative, physical in prepared_rows)
        for relative, display_path in candidates:
            if cancellation.cancelled:
                return _cancelled()
            if _matches(relative, pattern):
                matches.append(self._resolver.display(display_path))

        if not matches:
            return ToolExecutionResult("No files matched the pattern.")
        return ToolExecutionResult("\n".join(sorted(set(matches))))


class GrepTool:
    """Search safe workspace text files using Python regular expressions."""

    _definition = ToolDefinition(
        "Grep",
        "Search workspace text files with a Python regular expression.",
        {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "minLength": 1},
                "path": {"type": "string", "default": "."},
                "include": {"type": ["string", "null"], "default": None},
            },
            "required": ["pattern"],
            "additionalProperties": False,
        },
    )

    def __init__(self, resolver: WorkspacePathResolver) -> None:
        self._resolver = resolver

    @property
    def definition(self) -> ToolDefinition:
        return self._definition

    @property
    def planning_access(self) -> ToolPlanningAccess:
        return ToolPlanningAccess.READ_ONLY

    def preflight(self, arguments: JsonPayload) -> ToolPreparation:
        re.compile(_text(arguments, "pattern"))
        base_lexical, base, scope = _resolve_base(
            self._resolver,
            _text(arguments, "path", default="."),
        )
        raw_include = arguments.get("include")
        if raw_include not in (None, ""):
            if not isinstance(raw_include, str):
                raise TypeError("include must be a string or null")
            _relative_pattern(raw_include, "include")
        include = _include_pattern(raw_include)
        sensitive: list[str] = []
        prepared_rows = tuple(_safe_files(self._resolver, base_lexical, base))
        for lexical, physical in prepared_rows:
            relative = lexical.relative_to(base_lexical).as_posix()
            if include is not None and not _matches(relative, include):
                continue
            display = self._resolver.display(physical)
            if is_sensitive_resource(display):
                sensitive.append(display)
        resource = self._resolver.display(base)
        if sensitive:
            resource = _resource_with_sensitive_candidates(resource, sensitive)
        return ToolPreparation(
            action=PermissionAction(
                tool="Grep",
                action="grep",
                effect=Effect.READ,
                resource=resource,
                scope=scope,
            ),
            execution_arguments=_bind_search_files(
                arguments,
                base_lexical,
                prepared_rows,
            ),
        )

    async def execute(
        self,
        arguments: JsonPayload,
        *,
        cancellation: CancellationToken,
    ) -> ToolExecutionResult:
        if cancellation.cancelled:
            return _cancelled()
        try:
            regex = re.compile(_text(arguments, "pattern"))
        except (TypeError, ValueError):
            return _error("Error: invalid regex")
        except re.error as exc:
            return _error(f"Error: invalid regex: {exc}")

        try:
            prepared_rows = _prepared_search_files(arguments)
            base_lexical = base = None
            if prepared_rows is None:
                base_lexical, base, _ = _resolve_base(
                    self._resolver,
                    _text(arguments, "path", default="."),
                )
            raw_include = arguments.get("include")
            include = None
            if raw_include not in (None, ""):
                if not isinstance(raw_include, str):
                    raise TypeError("include must be a string or null")
                include = _relative_pattern(raw_include, "include")
                if "/" not in include:
                    include = f"**/{include}"
        except (WorkspacePathError, TypeError, ValueError) as exc:
            return _error(str(exc))

        matches: list[str] = []
        if prepared_rows is None:
            assert base_lexical is not None
            assert base is not None
            candidates = tuple(
                (candidate.relative_to(base_lexical).as_posix(), candidate, physical)
                for candidate, physical in _safe_files(self._resolver, base_lexical, base)
            )
        else:
            candidates = tuple((relative, physical, physical) for relative, physical in prepared_rows)
        for relative, candidate, physical in sorted(
            candidates,
            key=lambda item: self._resolver.display(item[2]),
        ):
            if cancellation.cancelled:
                return _cancelled()
            if include is not None and not _matches(relative, include):
                continue
            try:
                content = physical.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            display = self._resolver.display(physical)
            for line_number, line in enumerate(content.splitlines(), start=1):
                if regex.search(line):
                    matches.append(f"{display}:{line_number}:{line}")

        if not matches:
            return ToolExecutionResult("No matches found.")
        return ToolExecutionResult("\n".join(matches))


def _resolve_base(
    resolver: WorkspacePathResolver,
    raw_path: str,
) -> tuple[Path, Path, ResourceScope]:
    base_lexical = resolver.lexical_path(raw_path)
    base = resolver.resolve(raw_path)
    if not base.exists():
        raise WorkspacePathError(f"Error: path not found: {resolver.display(base)}")
    if not base.is_dir():
        raise WorkspacePathError(f"Error: path is not a directory: {resolver.display(base)}")
    scope = resolver.scope_of(base)
    if resolver.has_directory_symlink(raw_path) and scope is ResourceScope.INSIDE:
        raise WorkspacePathError("Error: directory symlinks are not followed")
    return base_lexical, base, scope


def _safe_files(
    resolver: WorkspacePathResolver,
    base_lexical: Path,
    base: Path,
) -> Iterator[tuple[Path, Path]]:
    if _contains_skipped_part(base_lexical, resolver.root):
        return
    pending = [base_lexical]
    while pending:
        current = pending.pop()
        try:
            entries = sorted(os.scandir(current), key=lambda entry: entry.name.casefold(), reverse=True)
        except OSError:
            continue
        for entry in entries:
            if entry.name.casefold() in _SKIP_DIR_NAMES:
                continue
            candidate = Path(entry.path)
            try:
                if entry.is_dir(follow_symlinks=False):
                    pending.append(candidate)
                    continue
                if not entry.is_file(follow_symlinks=True):
                    continue
            except OSError:
                continue
            resolved = resolver.validate_candidate(
                candidate,
                allow_outside=resolver.scope_of(base) is ResourceScope.OUTSIDE,
            )
            if resolved is None:
                continue
            if _contains_skipped_part(candidate, resolver.root) or _contains_skipped_part(
                resolved, resolver.root
            ):
                continue
            yield candidate, resolved


def _bind_search_files(
    arguments: JsonPayload,
    base_lexical: Path,
    rows: Sequence[tuple[Path, Path]],
) -> JsonPayload:
    values = dict(arguments)
    values[_PREPARED_FILES] = [
        {
            "relative": lexical.relative_to(base_lexical).as_posix(),
            "physical": str(physical),
        }
        for lexical, physical in rows
    ]
    return JsonPayload(values)


def _prepared_search_files(
    arguments: Mapping[str, object],
) -> tuple[tuple[str, Path], ...] | None:
    if _PREPARED_FILES not in arguments:
        return None
    raw_rows = arguments[_PREPARED_FILES]
    if isinstance(raw_rows, (str, bytes, bytearray)) or not isinstance(raw_rows, Sequence):
        raise ValueError("Error: invalid prepared search payload")
    rows: list[tuple[str, Path]] = []
    for raw_row in raw_rows:
        if not isinstance(raw_row, Mapping):
            raise ValueError("Error: invalid prepared search payload")
        relative = raw_row.get("relative")
        physical = raw_row.get("physical")
        if not isinstance(relative, str) or not isinstance(physical, str):
            raise ValueError("Error: invalid prepared search payload")
        rows.append((relative, Path(physical)))
    return tuple(rows)


def _contains_skipped_part(path: Path, root: Path) -> bool:
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        parts = path.parts
    return any(part.casefold() in _SKIP_DIR_NAMES for part in parts)


def _relative_pattern(value: str, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if "\x00" in value:
        raise WorkspacePathError(f"Error: {name} contains null byte")
    normalized = value.replace("\\", "/")
    if not normalized or PureWindowsPath(normalized).is_absolute() or normalized.startswith("/"):
        raise WorkspacePathError(f"Error: {name} must be relative")
    parts = [part for part in normalized.split("/") if part not in ("", ".")]
    if not parts or ".." in parts:
        raise WorkspacePathError(f"Error: {name} contains an unsafe path segment")
    return "/".join(parts)


def _matches(relative: str, pattern: str) -> bool:
    return _match_parts(tuple(relative.split("/")), tuple(pattern.split("/")))


@lru_cache(maxsize=None)
def _match_parts(path: tuple[str, ...], pattern: tuple[str, ...]) -> bool:
    if not pattern:
        return not path
    if pattern[0] == "**":
        return _match_parts(path, pattern[1:]) or bool(path) and _match_parts(path[1:], pattern)
    return bool(path) and fnmatch.fnmatchcase(path[0], pattern[0]) and _match_parts(
        path[1:], pattern[1:]
    )


def _text(arguments: Mapping[str, object], name: str, *, default: str | None = None) -> str:
    value = arguments.get(name, default)
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    return value


def _include_pattern(value: object) -> str | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise TypeError("include must be a string or null")
    include = _relative_pattern(value, "include")
    if "/" not in include:
        include = f"**/{include}"
    return include


def _resource_with_sensitive_candidates(base: str, candidates: list[str]) -> str:
    unique = sorted(set(candidates))
    summary = f"{base} [sensitive: {', '.join(unique)}]"
    if len(summary) <= 512:
        return summary
    return summary[:511] + "…"


def _error(message: str) -> ToolExecutionResult:
    return ToolExecutionResult(message, is_error=True)


def _cancelled() -> ToolExecutionResult:
    return _error(_CANCELLED)


__all__ = ["GlobTool", "GrepTool"]
