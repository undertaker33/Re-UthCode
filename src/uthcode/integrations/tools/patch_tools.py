"""Codex-style text patch tool with preflight and per-file commits."""

from __future__ import annotations

import os
import re
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from uthcode.core.permission import Effect, PermissionAction, ResourceScope
from uthcode.core.provider import CancellationToken, JsonPayload, ToolDefinition
from uthcode.core.tool import (
    ToolExecutionResult,
    ToolFailure,
    ToolFailureKind,
    ToolPlanningAccess,
    ToolPreparation,
    ToolSideEffect,
)

from .workspace import FileReadTracker, WorkspacePathError, WorkspacePathResolver


_PATCH_BEGIN = "*** Begin Patch"
_PATCH_END = "*** End Patch"
_END_OF_FILE = "*** End of File"
_HEADER_RE = re.compile(r"^\*\*\*\s+(Add|Delete|Update)\s+File:\s*(.+?)\s*$")
_MOVE_RE = re.compile(r"^\*\*\*\s+Move\s+to:\s*(.+?)\s*$")
_HUNK_RE = re.compile(r"^@@(?:\s+.*)?$")


@dataclass(frozen=True, slots=True)
class PatchHunk:
    lines: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PatchOperation:
    kind: str
    source: str
    hunks: tuple[PatchHunk, ...] = ()
    destination: str | None = None
    content: str | None = None

    @property
    def targets(self) -> tuple[str, ...]:
        if self.destination is None:
            return (self.source,)
        return self.source, self.destination


@dataclass(frozen=True, slots=True)
class PatchPlan:
    operations: tuple[PatchOperation, ...]


class PatchSyntaxError(ValueError):
    """The input is not the supported textual Patch dialect."""


class _PatchCommitError(ValueError):
    """A target commit failed after one or more paths were changed."""

    def __init__(self, message: str, *, applied: Sequence[str] = ()) -> None:
        super().__init__(message)
        self.applied = tuple(applied)


def parse_patch(text: object) -> PatchPlan:
    if not isinstance(text, str):
        raise PatchSyntaxError("Error: patch must be a string")
    if "\x00" in text:
        raise PatchSyntaxError("Error: patch contains a null byte")
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    if not lines or lines[0] != _PATCH_BEGIN or lines[-1] != _PATCH_END:
        raise PatchSyntaxError(
            "Error: patch must start with `*** Begin Patch` and end with `*** End Patch`"
        )
    operations: list[PatchOperation] = []
    index = 1
    while index < len(lines) - 1:
        match = _HEADER_RE.match(lines[index])
        if match is None:
            raise PatchSyntaxError(f"Error: expected patch file header at line {index + 1}")
        kind = match.group(1).lower()
        source = _patch_path(match.group(2), "source")
        index += 1
        destination: str | None = None
        if index < len(lines) - 1:
            move = _MOVE_RE.match(lines[index])
            if move is not None:
                if kind != "update":
                    raise PatchSyntaxError("Error: Move to is only valid after Update File")
                destination = _patch_path(move.group(1), "destination")
                index += 1
        body: list[str] = []
        while index < len(lines) - 1 and _HEADER_RE.match(lines[index]) is None:
            if lines[index] == _END_OF_FILE:
                index += 1
                continue
            if _MOVE_RE.match(lines[index]) is not None:
                raise PatchSyntaxError("Error: Move to must immediately follow Update File")
            body.append(lines[index])
            index += 1
        if kind == "add":
            if any(line and not line.startswith("+") for line in body):
                raise PatchSyntaxError("Error: Add File content must use + lines")
            content = "\n".join(line[1:] for line in body)
            operations.append(PatchOperation(kind, source, content=content))
        elif kind == "delete":
            if body and any(line.strip() for line in body):
                raise PatchSyntaxError("Error: Delete File cannot contain content")
            operations.append(PatchOperation(kind, source))
        else:
            hunks = _parse_hunks(body)
            if not hunks:
                raise PatchSyntaxError("Error: Update File requires at least one hunk")
            operations.append(PatchOperation(kind, source, tuple(hunks), destination=destination))
    if not operations:
        raise PatchSyntaxError("Error: patch contains no file operations")
    return PatchPlan(tuple(operations))


def _parse_hunks(body: Sequence[str]) -> list[PatchHunk]:
    groups: list[list[str]] = []
    current: list[str] | None = None
    for line in body:
        if _HUNK_RE.match(line):
            if current is not None:
                groups.append(current)
            current = []
            continue
        if current is None:
            # The Codex dialect allows a compact update without @@ only when
            # every line is an ordinary hunk line.
            current = []
        if line and line[0] not in {" ", "+", "-"}:
            raise PatchSyntaxError("Error: patch hunk lines must begin with space, +, or -")
        current.append(line)
    if current is not None:
        groups.append(current)
    hunks: list[PatchHunk] = []
    for group in groups:
        if not group or not any(line.startswith((" ", "-")) for line in group):
            raise PatchSyntaxError("Error: each patch hunk must contain context or removed lines")
        hunks.append(PatchHunk(tuple(group)))
    return hunks


def _patch_path(value: str, name: str) -> str:
    normalized = value.strip().replace("\\", "/")
    if not normalized or normalized.startswith("/") or re.match(r"^[A-Za-z]:/", normalized):
        raise PatchSyntaxError(f"Error: {name} must be a relative workspace path")
    parts = [part for part in normalized.split("/") if part not in {"", "."}]
    if not parts or any(part == ".." for part in parts):
        raise PatchSyntaxError(f"Error: {name} contains an unsafe path segment")
    return "/".join(parts)


class ApplyPatchTool:
    """Apply one complete textual Patch after a zero-change preflight."""

    _definition = ToolDefinition(
        "ApplyPatch",
        "Apply a strict Codex-style text patch after reading and authorizing every target. "
        "The patch must start with `*** Begin Patch` and end with `*** End Patch`; "
        "use `*** Add File: path`, `*** Update File: path`, `*** Delete File: path`, "
        "optional `*** Move to: path`, and context hunks beginning with `@@`. "
        "Example: `*** Begin Patch\\n*** Update File: notes.txt\\n@@\\n-old\\n+new\\n*** End Patch`.",
        {
            "type": "object",
            "properties": {"patch": {"type": "string", "minLength": 1}},
            "required": ["patch"],
            "additionalProperties": False,
        },
    )

    def __init__(
        self,
        resolver: WorkspacePathResolver,
        tracker: FileReadTracker,
        *,
        on_path_access: Callable[[Path], object] | None = None,
    ) -> None:
        self._resolver = resolver
        self._tracker = tracker
        self._on_path_access = on_path_access

    @property
    def definition(self) -> ToolDefinition:
        return self._definition

    @property
    def planning_access(self) -> ToolPlanningAccess:
        return ToolPlanningAccess.HIDDEN

    def preflight(self, arguments: JsonPayload) -> ToolPreparation:
        plan = parse_patch(arguments.get("patch"))
        self._preflight_plan(plan)
        paths = [self._resolver.display(self._resolver.resolve(path)) for op in plan.operations for path in op.targets]
        scope = ResourceScope.INSIDE
        for op in plan.operations:
            for raw_path in op.targets:
                if self._resolver.scope_of(raw_path) is ResourceScope.OUTSIDE:
                    scope = ResourceScope.OUTSIDE
        resource = "patch:" + ",".join(paths)
        return ToolPreparation(
            action=PermissionAction(
                tool=self._definition.name,
                action="apply",
                effect=Effect.WRITE,
                resource=resource,
                scope=scope,
            ),
            # ToolPreparation payloads cross the Application/Core boundary and
            # therefore must remain JSON-shaped.  The immutable plan is a
            # preflight fact, not an executable object; execute reparses the
            # original text and performs the full preflight again immediately
            # before each commit.
            execution_arguments=JsonPayload({"patch": arguments.get("patch")}),
        )

    def _preflight_plan(self, plan: PatchPlan) -> None:
        seen: dict[str, str] = {}
        for operation in plan.operations:
            source = self._resolver.resolve(operation.source)
            source_key = _physical_path_key(source)
            if source_key in seen:
                raise ValueError(f"Error: patch target conflict: {operation.source}")
            seen[source_key] = operation.source
            destination: Path | None = None
            if operation.destination is not None:
                destination = self._resolver.resolve(operation.destination)
                destination_key = _physical_path_key(destination)
                if destination_key in seen:
                    raise ValueError(f"Error: patch target conflict: {operation.destination}")
                seen[destination_key] = operation.destination
            source_exists = source.exists()
            if operation.kind == "add":
                if source_exists:
                    raise ValueError(f"Error: Add File target already exists: {operation.source}")
                continue
            if not source_exists or not source.is_file():
                raise ValueError(f"Error: patch source not found: {operation.source}")
            ok, message = self._tracker.check(source)
            if not ok:
                raise ValueError(message)
            original = source.read_text(encoding="utf-8")
            if operation.kind == "update":
                _apply_hunks(original, operation.hunks)
                if operation.destination is not None:
                    assert destination is not None
                    if destination.exists():
                        raise ValueError(f"Error: Move target already exists: {operation.destination}")
            else:
                if operation.destination is not None:
                    raise ValueError("Error: Delete File cannot move to another path")

    async def execute(
        self,
        arguments: JsonPayload,
        *,
        cancellation: CancellationToken,
    ) -> ToolExecutionResult:
        if cancellation.cancelled:
            return _cancelled()
        try:
            plan = parse_patch(arguments.get("patch"))
            self._preflight_plan(plan)
        except (PatchSyntaxError, WorkspacePathError, UnicodeDecodeError, OSError, ValueError) as exc:
            return _error(str(exc), ToolFailureKind.CONFLICT if "modified" in str(exc) else ToolFailureKind.INVALID_INPUT)
        applied: list[str] = []
        failed: str | None = None
        not_applied: list[str] = []
        for index, operation in enumerate(plan.operations):
            if cancellation.cancelled:
                not_applied.extend(op.source for op in plan.operations[index:])
                return _partial(applied, failed="cancelled", not_applied=not_applied, cancelled=True)
            try:
                self._preflight_plan(PatchPlan((operation,)))
                for raw_path in operation.targets:
                    _notify(self._on_path_access, self._resolver.resolve(raw_path))
                applied.extend(self._commit(operation))
            except _PatchCommitError as exc:
                applied.extend(exc.applied)
                failed = f"{operation.source}: {exc}"
                not_applied.extend(op.source for op in plan.operations[index + 1 :])
                return _partial(applied, failed=failed, not_applied=not_applied)
            except (PatchSyntaxError, WorkspacePathError, UnicodeDecodeError, OSError, ValueError) as exc:
                failed = f"{operation.source}: {exc}"
                not_applied.extend(op.source for op in plan.operations[index + 1 :])
                return _partial(applied, failed=failed, not_applied=not_applied)
        return ToolExecutionResult(
            "Applied patch to " + ", ".join(applied),
            side_effect=ToolSideEffect.APPLIED if applied else ToolSideEffect.NONE,
            details={"applied": applied, "failed": [], "not_applied": []},
        )

    def _commit(self, operation: PatchOperation) -> tuple[str, ...]:
        source = self._resolver.resolve(operation.source)
        if operation.kind == "add":
            assert operation.content is not None
            _atomic_write(source, operation.content)
            self._tracker.update(source)
            return (operation.source,)
        original = source.read_text(encoding="utf-8")
        if operation.kind == "delete":
            source.unlink()
            self._tracker.forget(source)
            return (operation.source,)
        updated = _apply_hunks(original, operation.hunks)
        if operation.destination is None:
            _atomic_write(source, updated, newline=_newline_for(original))
            self._tracker.update(source)
            return (operation.source,)
        destination = self._resolver.resolve(operation.destination)
        _atomic_write(destination, updated, newline=_newline_for(original))
        try:
            source.unlink()
        except OSError as exc:
            # The destination is already the committed new inode.  Preserve
            # that fact in the partial result instead of claiming a rollback.
            self._tracker.update(destination)
            raise _PatchCommitError(
                "move destination was written but source removal failed",
                applied=(operation.destination,),
            ) from exc
        self._tracker.forget(source)
        self._tracker.update(destination)
        return operation.source, operation.destination


def _apply_hunks(original: str, hunks: Sequence[PatchHunk]) -> str:
    newline = _newline_for(original)
    normalized = original.replace("\r\n", "\n").replace("\r", "\n")
    trailing = normalized.endswith("\n")
    lines = normalized.split("\n")
    if trailing:
        lines.pop()
    cursor = 0
    for hunk in hunks:
        old = [line[1:] for line in hunk.lines if line.startswith((" ", "-"))]
        new = [line[1:] for line in hunk.lines if line.startswith((" ", "+"))]
        if not old:
            raise ValueError("Error: patch hunk has no context")
        locations = [
            index
            for index in range(cursor, len(lines) - len(old) + 1)
            if lines[index : index + len(old)] == old
        ]
        if len(locations) != 1:
            if not locations:
                raise ValueError("Error: patch hunk context was not found")
            raise ValueError("Error: patch hunk is ambiguous or repeated")
        location = locations[0]
        lines[location : location + len(old)] = new
        cursor = location + len(new)
    rendered = "\n".join(lines)
    if trailing:
        rendered += "\n"
    return rendered.replace("\n", newline)


def _newline_for(value: str) -> str:
    return "\r\n" if "\r\n" in value else "\n"


def _physical_path_key(path: Path) -> str:
    """Return the resolver's physical identity with Windows case folding."""

    normalized = os.path.normpath(os.fspath(path))
    if os.name == "nt":
        return os.path.normcase(normalized)
    return normalized


def _atomic_write(path: Path, content: str, *, newline: str = "\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    encoded = content.replace("\r\n", "\n").replace("\n", newline).encode("utf-8")
    try:
        with temporary.open("xb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _partial(
    applied: Sequence[str],
    *,
    failed: str,
    not_applied: Sequence[str],
    cancelled: bool = False,
) -> ToolExecutionResult:
    details = {
        "applied": list(applied),
        "failed": [failed],
        "not_applied": list(not_applied),
    }
    return ToolExecutionResult(
        json_text(details),
        is_error=True,
        failure=ToolFailure(
            ToolFailureKind.CANCELLED.value if cancelled else ToolFailureKind.CONFLICT.value,
            retryable=cancelled,
        ),
        side_effect=ToolSideEffect.PARTIAL if applied else ToolSideEffect.NONE,
        details=details,
    )


def json_text(value: Mapping[str, object]) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _error(message: str, kind: ToolFailureKind | str) -> ToolExecutionResult:
    return ToolExecutionResult(
        message,
        is_error=True,
        failure=ToolFailure(str(getattr(kind, "value", kind))),
        details={"applied": [], "failed": [message], "not_applied": []},
    )


def _cancelled() -> ToolExecutionResult:
    return _error("Error: tool call cancelled", ToolFailureKind.CANCELLED)


def _notify(callback: Callable[[Path], object] | None, path: Path) -> None:
    if callback is not None:
        callback(path)


__all__ = [
    "ApplyPatchTool",
    "PatchHunk",
    "PatchOperation",
    "PatchPlan",
    "PatchSyntaxError",
    "parse_patch",
]
