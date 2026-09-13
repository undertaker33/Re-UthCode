"""Bounded workspace matching with inherited ignore rules and continuation."""

from __future__ import annotations

import base64
import fnmatch
import hashlib
import json
import os
from collections.abc import Iterator, Mapping, Sequence
from functools import lru_cache
from pathlib import Path, PureWindowsPath

import pathspec
import regex

from uthcode.core.permission import Effect, PermissionAction, ResourceScope
from uthcode.core.provider import CancellationToken, JsonPayload, ToolDefinition
from uthcode.core.tool import (
    ToolExecutionResult,
    ToolFailure,
    ToolFailureKind,
    ToolPlanningAccess,
    ToolPreparation,
)
from uthcode.integrations.permissions import is_sensitive_resource

from .workspace import WorkspacePathError, WorkspacePathResolver


_SKIP_DIR_NAMES = frozenset(
    {".git", ".venv", "node_modules", "__pycache__", ".tox", ".mypy_cache", ".pytest_cache"}
)
_CANCELLED = "Error: tool call cancelled"
_PREPARED_FILES = "__uthcode_prepared_files"
_PREPARED_KEY = "__uthcode_search_key"
_DEFAULT_PAGE_SIZE = 100
_MAX_PAGE_SIZE = 500
_MAX_CANDIDATES = 20_000
_MAX_INPUT_BYTES = 2 * 1024 * 1024
_MAX_LINE_BYTES = 64 * 1024
_DEFAULT_OUTPUT_BYTES = 64 * 1024
_MAX_OUTPUT_BYTES = 256 * 1024
_CURSOR_PREFIX = "uthcode-search-v1."


class _IgnoreRules:
    """Read .gitignore/.ignore rules lazily for directory ancestry."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._cache: dict[Path, tuple[object, ...]] = {}

    def ignored(self, candidate: Path, *, is_dir: bool) -> bool:
        directory = candidate if is_dir else candidate.parent
        ancestors: list[Path] = []
        current = directory
        while True:
            ancestors.append(current)
            if current == self._root or current.parent == current:
                break
            try:
                current.relative_to(self._root)
            except ValueError:
                break
            current = current.parent
        ignored = False
        for base in reversed(ancestors):
            relative = _relative_to(candidate, base)
            for pattern in self._patterns(base):
                try:
                    matched = pattern.match_file(relative)
                except (OSError, ValueError):
                    matched = None
                if matched:
                    # GitWildMatchPattern.include is False for a negated rule.
                    ignored = bool(getattr(pattern, "include", True))
        return ignored

    def _patterns(self, directory: Path) -> tuple[object, ...]:
        cached = self._cache.get(directory)
        if cached is not None:
            return cached
        values: list[object] = []
        for name in (".gitignore", ".ignore"):
            path = directory / name
            try:
                lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
            except OSError:
                continue
            try:
                spec = pathspec.GitIgnoreSpec.from_lines(lines)
            except (TypeError, ValueError):
                continue
            values.extend(spec.patterns)
        result = tuple(values)
        self._cache[directory] = result
        return result


class GlobTool:
    """Find workspace files using bounded traversal and continuation cursors."""

    _definition = ToolDefinition(
        "Glob",
        "Find workspace files with a relative glob pattern; directory links are not followed.",
        {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "minLength": 1},
                "path": {"type": "string", "default": "."},
                "include_ignored": {"type": "boolean", "default": False},
                "include_hidden": {"type": "boolean", "default": True},
                "page_size": {"type": "integer", "minimum": 1, "maximum": _MAX_PAGE_SIZE},
                "cursor": {"type": ["string", "null"], "maxLength": 2048},
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
        options = _glob_options(arguments)
        base_lexical, base, scope = _resolve_base(self._resolver, options["path"])
        key = _query_key("glob", options)
        _cursor_offset(arguments.get("cursor"), key)
        rows = tuple(
            _safe_files(
                self._resolver,
                base_lexical,
                base,
                include_ignored=options["include_ignored"],
                include_hidden=options["include_hidden"],
            )
        )
        # Glob exposes paths rather than file contents, but a candidate list
        # can still disclose the existence of credential material.  Build the
        # sensitive resource from the exact physical candidates observed by
        # this preflight.  A later cursor request repeats this scan, so newly
        # created sensitive or linked candidates cannot inherit the first
        # page's decision.
        sensitive: list[str] = []
        for lexical, physical in rows:
            relative = lexical.relative_to(base_lexical).as_posix()
            if not _matches(relative, options["pattern"]):
                continue
            display = self._resolver.display(physical)
            if is_sensitive_resource(display):
                sensitive.append(display)
        resource = self._resolver.display(base)
        if sensitive:
            resource = _resource_with_sensitive_candidates(resource, sensitive)
        return ToolPreparation(
            action=PermissionAction(
                tool="Glob",
                action="glob",
                effect=Effect.READ,
                resource=resource,
                scope=scope,
            ),
            execution_arguments=_bind_search_files(arguments, base_lexical, rows, key),
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
            options = _glob_options(arguments)
            pattern = options["pattern"]
            key = _query_key("glob", options)
            offset = _cursor_offset(arguments.get("cursor"), key)
            prepared = _prepared_search_files(arguments, expected_key=key)
            if prepared is None:
                base_lexical, base, _ = _resolve_base(self._resolver, options["path"])
                candidates = (
                    (candidate.relative_to(base_lexical).as_posix(), physical)
                    for candidate, physical in _safe_files(
                        self._resolver,
                        base_lexical,
                        base,
                        include_ignored=options["include_ignored"],
                        include_hidden=options["include_hidden"],
                    )
                )
            else:
                candidates = ((relative, physical) for relative, physical in prepared)
        except (WorkspacePathError, TypeError, ValueError) as exc:
            return _error(str(exc))

        matches: list[str] = []
        seen_paths: set[str] = set()
        seen = 0
        has_more = False
        for relative, display_path in candidates:
            if cancellation.cancelled:
                return _cancelled()
            if not _matches(relative, pattern):
                continue
            if seen < offset:
                seen += 1
                continue
            seen += 1
            if len(matches) >= options["page_size"]:
                has_more = True
                break
            display = self._resolver.display(display_path)
            if display in seen_paths:
                continue
            seen_paths.add(display)
            matches.append(display)
        if not matches and offset == 0:
            return ToolExecutionResult("No files matched the pattern.")
        if not matches:
            return ToolExecutionResult("No more files matched the pattern.")
        cursor = _encode_cursor(key, offset + len(matches)) if has_more else None
        return ToolExecutionResult(
            "\n".join(sorted(matches)),
            next_cursor=cursor,
            details={"count": len(matches), "truncated": has_more},
        )


class GrepTool:
    """Search safe text files with regex timeouts and bounded result pages."""

    _definition = ToolDefinition(
        "Grep",
        "Search workspace text files with a Python-compatible regular expression.",
        {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "minLength": 1},
                "path": {"type": "string", "default": "."},
                "include": {"type": ["string", "null"], "default": None},
                "include_ignored": {"type": "boolean", "default": False},
                "include_hidden": {"type": "boolean", "default": True},
                "page_size": {"type": "integer", "minimum": 1, "maximum": _MAX_PAGE_SIZE},
                "max_bytes": {"type": "integer", "minimum": 1024, "maximum": _MAX_OUTPUT_BYTES},
                "timeout_ms": {"type": "integer", "minimum": 1, "maximum": 5000},
                "cursor": {"type": ["string", "null"], "maxLength": 2048},
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
        options = _grep_options(arguments)
        _compile_regex(options["pattern"])
        base_lexical, base, scope = _resolve_base(self._resolver, options["path"])
        key = _query_key("grep", options)
        _cursor_offset(arguments.get("cursor"), key)
        rows = tuple(
            _safe_files(
                self._resolver,
                base_lexical,
                base,
                include_ignored=options["include_ignored"],
                include_hidden=options["include_hidden"],
            )
        )
        sensitive: list[str] = []
        for lexical, physical in rows:
            relative = lexical.relative_to(base_lexical).as_posix()
            if options["include"] is not None and not _matches(relative, options["include"]):
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
            execution_arguments=_bind_search_files(arguments, base_lexical, rows, key),
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
            options = _grep_options(arguments)
            expression = _compile_regex(options["pattern"])
            key = _query_key("grep", options)
            offset = _cursor_offset(arguments.get("cursor"), key)
            prepared = _prepared_search_files(arguments, expected_key=key)
            if prepared is None:
                base_lexical, base, _ = _resolve_base(self._resolver, options["path"])
                candidates = (
                    (candidate.relative_to(base_lexical).as_posix(), physical)
                    for candidate, physical in _safe_files(
                        self._resolver,
                        base_lexical,
                        base,
                        include_ignored=options["include_ignored"],
                        include_hidden=options["include_hidden"],
                    )
                )
            else:
                candidates = ((relative, physical) for relative, physical in prepared)
        except (WorkspacePathError, TypeError, ValueError) as exc:
            return _error(str(exc))

        matches: list[str] = []
        seen_match_keys: set[tuple[str, int]] = set()
        match_index = 0
        output_bytes = 0
        has_more = False
        try:
            for relative, physical in candidates:
                if cancellation.cancelled:
                    return _cancelled()
                include = options["include"]
                if include is not None and not _matches(relative, include):
                    continue
                if _is_binary(physical):
                    continue
                display = self._resolver.display(physical)
                try:
                    # Stream one bounded text file at a time.  ``read_text``
                    # followed by ``splitlines`` retained an entire file in
                    # memory before the first regex check; the input and line
                    # budgets below keep the search bounded independently of
                    # the output page size.
                    with physical.open("r", encoding="utf-8", newline="") as handle:
                        input_bytes = 0
                        line_number = 0
                        while True:
                            raw_line = handle.readline(_MAX_LINE_BYTES + 1)
                            if not raw_line:
                                break
                            line_number += 1
                            if cancellation.cancelled:
                                return _cancelled()
                            input_bytes += len(raw_line.encode("utf-8", errors="ignore"))
                            if input_bytes > _MAX_INPUT_BYTES:
                                break
                            line_too_long = (
                                len(raw_line) > _MAX_LINE_BYTES
                                and not raw_line.endswith(("\r", "\n"))
                            )
                            if line_too_long:
                                # Keep regex work bounded while preserving a
                                # non-matching suffix for timeout-sensitive
                                # expressions; discard the rest in chunks.
                                line = (
                                    _bounded_utf8_prefix(raw_line, _MAX_LINE_BYTES)
                                    + "\n<line-truncated>"
                                )
                                while raw_line and not raw_line.endswith(("\r", "\n")):
                                    raw_line = handle.readline(_MAX_LINE_BYTES + 1)
                                    if raw_line:
                                        input_bytes += len(
                                            raw_line.encode("utf-8", errors="ignore")
                                        )
                                    if input_bytes > _MAX_INPUT_BYTES:
                                        break
                            else:
                                line = raw_line.rstrip("\r\n")
                            try:
                                matched = expression.search(
                                    line,
                                    timeout=options["timeout_ms"] / 1000,
                                )
                            except TimeoutError:
                                return ToolExecutionResult(
                                    "Error: regex search timed out",
                                    is_error=True,
                                    failure=ToolFailure(
                                        ToolFailureKind.TIMEOUT.value,
                                        retryable=True,
                                    ),
                                    details={"timeout_ms": options["timeout_ms"]},
                                )
                            if matched is None:
                                continue
                            if match_index < offset:
                                match_index += 1
                                continue
                            match_index += 1
                            if len(matches) >= options["page_size"]:
                                has_more = True
                                break
                            value = f"{display}:{line_number}:{line}"
                            encoded_size = len(value.encode("utf-8")) + (1 if matches else 0)
                            if output_bytes and output_bytes + encoded_size > options["max_bytes"]:
                                has_more = True
                                break
                            if not output_bytes and encoded_size > options["max_bytes"]:
                                value = _bounded_utf8_prefix(value, options["max_bytes"])
                                encoded_size = len(value.encode("utf-8"))
                            match_key = (display, line_number)
                            if match_key in seen_match_keys:
                                continue
                            seen_match_keys.add(match_key)
                            matches.append(value)
                            output_bytes += encoded_size
                except (OSError, UnicodeDecodeError):
                    continue
                if has_more:
                    break
        except (OSError, ValueError) as exc:
            return _error(str(exc))
        if not matches and offset == 0:
            return ToolExecutionResult("No matches found.")
        if not matches:
            return ToolExecutionResult("No more matches found.")
        cursor = _encode_cursor(key, offset + len(matches)) if has_more else None
        return ToolExecutionResult(
            "\n".join(sorted(matches)),
            next_cursor=cursor,
            details={"count": len(matches), "truncated": has_more},
        )


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
    *,
    include_ignored: bool = False,
    include_hidden: bool = False,
    max_candidates: int = _MAX_CANDIDATES,
) -> Iterator[tuple[Path, Path]]:
    """Yield at most a bounded candidate window; never materialize the tree."""

    if _contains_skipped_part(base_lexical, resolver.root):
        return
    matcher = _IgnoreRules(resolver.root)
    allow_outside = resolver.scope_of(base) is ResourceScope.OUTSIDE
    pending = [base_lexical]
    yielded = 0
    while pending and yielded < max_candidates:
        current = pending.pop()
        try:
            entries = os.scandir(current)
        except OSError:
            continue
        try:
            for entry in entries:
                if yielded >= max_candidates:
                    return
                if entry.name.casefold() in _SKIP_DIR_NAMES:
                    continue
                candidate = Path(entry.path)
                try:
                    relative_from_base = candidate.relative_to(base_lexical).parts
                except ValueError:
                    relative_from_base = candidate.parts
                if not include_hidden and any(part.startswith(".") for part in relative_from_base):
                    continue
                try:
                    directory = entry.is_dir(follow_symlinks=False)
                    if directory:
                        if not include_ignored and matcher.ignored(candidate, is_dir=True):
                            continue
                        pending.append(candidate)
                        continue
                    if not entry.is_file(follow_symlinks=True):
                        continue
                except (OSError, ValueError):
                    continue
                if not include_ignored and matcher.ignored(candidate, is_dir=False):
                    continue
                resolved = resolver.validate_candidate(candidate, allow_outside=allow_outside)
                if resolved is None:
                    continue
                if _contains_skipped_part(candidate, resolver.root) or _contains_skipped_part(resolved, resolver.root):
                    continue
                yield candidate, resolved
                yielded += 1
        finally:
            entries.close()


def _bind_search_files(
    arguments: JsonPayload,
    base_lexical: Path,
    rows: Sequence[tuple[Path, Path]],
    key: str,
) -> JsonPayload:
    values = dict(arguments)
    values[_PREPARED_KEY] = key
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
    *,
    expected_key: str,
) -> tuple[tuple[str, Path], ...] | None:
    if _PREPARED_FILES not in arguments:
        return None
    if arguments.get(_PREPARED_KEY) != expected_key:
        raise ValueError("Error: prepared search payload does not match this query")
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


def _glob_options(arguments: Mapping[str, object]) -> dict[str, object]:
    pattern = _relative_pattern(arguments.get("pattern"), "pattern")
    path = _text(arguments, "path", default=".")
    return {
        "pattern": pattern,
        "path": path,
        "include_ignored": _bool(arguments, "include_ignored", False),
        "include_hidden": _bool(arguments, "include_hidden", True),
        "page_size": _page_size(arguments.get("page_size", _DEFAULT_PAGE_SIZE)),
    }


def _grep_options(arguments: Mapping[str, object]) -> dict[str, object]:
    raw_include = arguments.get("include")
    include = _include_pattern(raw_include)
    return {
        "pattern": _text(arguments, "pattern"),
        "path": _text(arguments, "path", default="."),
        "include": include,
        "include_ignored": _bool(arguments, "include_ignored", False),
        "include_hidden": _bool(arguments, "include_hidden", True),
        "page_size": _page_size(arguments.get("page_size", _DEFAULT_PAGE_SIZE)),
        "max_bytes": _max_bytes(arguments.get("max_bytes", _DEFAULT_OUTPUT_BYTES)),
        "timeout_ms": _timeout_ms(arguments.get("timeout_ms", 250)),
    }


def _query_key(kind: str, options: Mapping[str, object]) -> str:
    payload = json.dumps({"kind": kind, **dict(options)}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _encode_cursor(key: str, offset: int) -> str:
    payload = json.dumps({"key": key, "offset": offset}, separators=(",", ":")).encode("ascii")
    return _CURSOR_PREFIX + base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _cursor_offset(value: object, key: str) -> int:
    if value in (None, ""):
        return 0
    if not isinstance(value, str) or not value.startswith(_CURSOR_PREFIX):
        raise ValueError("Error: invalid search cursor")
    encoded = value[len(_CURSOR_PREFIX) :]
    try:
        decoded = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        payload = json.loads(decoded.decode("ascii"))
    except (ValueError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Error: invalid search cursor") from exc
    if not isinstance(payload, Mapping) or payload.get("key") != key:
        raise ValueError("Error: search cursor does not match this query")
    offset = payload.get("offset")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ValueError("Error: invalid search cursor offset")
    return offset


def _contains_skipped_part(path: Path, root: Path) -> bool:
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        parts = path.parts
    return any(part.casefold() in _SKIP_DIR_NAMES for part in parts)


def _relative_to(path: Path, base: Path) -> str:
    try:
        return path.relative_to(base).as_posix()
    except ValueError:
        return path.name


def _relative_pattern(value: object, name: str) -> str:
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
    return bool(path) and fnmatch.fnmatchcase(path[0], pattern[0]) and _match_parts(path[1:], pattern[1:])


def _include_pattern(value: object) -> str | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise TypeError("include must be a string or null")
    include = _relative_pattern(value, "include")
    return include if "/" in include else f"**/{include}"


def _compile_regex(pattern: object) -> regex.Pattern:
    if not isinstance(pattern, str):
        raise TypeError("pattern must be a string")
    try:
        return regex.compile(pattern)
    except (regex.error, TypeError, ValueError) as exc:
        raise ValueError(f"Error: invalid regex: {exc}") from exc


def _is_binary(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return b"\x00" in handle.read(8192)
    except OSError:
        return True


def _bounded_utf8_prefix(value: str, limit_bytes: int) -> str:
    encoded = value.encode("utf-8")[:limit_bytes]
    while encoded:
        try:
            return encoded.decode("utf-8")
        except UnicodeDecodeError:
            encoded = encoded[:-1]
    return ""


def _text(arguments: Mapping[str, object], name: str, *, default: str | None = None) -> str:
    value = arguments.get(name, default)
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    return value


def _bool(arguments: Mapping[str, object], name: str, default: bool) -> bool:
    value = arguments.get(name, default)
    if not isinstance(value, bool):
        raise TypeError(f"{name} must be a boolean")
    return value


def _page_size(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= _MAX_PAGE_SIZE:
        raise ValueError(f"page_size must be between 1 and {_MAX_PAGE_SIZE}")
    return value


def _max_bytes(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1024 <= value <= _MAX_OUTPUT_BYTES:
        raise ValueError(f"max_bytes must be between 1024 and {_MAX_OUTPUT_BYTES}")
    return value


def _timeout_ms(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 5000:
        raise ValueError("timeout_ms must be between 1 and 5000")
    return value


def _resource_with_sensitive_candidates(base: str, candidates: list[str]) -> str:
    unique = sorted(set(candidates))
    summary = f"{base} [sensitive: {', '.join(unique)}]"
    return summary if len(summary) <= 512 else summary[:511] + "…"


def _error(message: str) -> ToolExecutionResult:
    return ToolExecutionResult(message, is_error=True)


def _cancelled() -> ToolExecutionResult:
    return _error(_CANCELLED)


__all__ = ["GlobTool", "GrepTool"]
