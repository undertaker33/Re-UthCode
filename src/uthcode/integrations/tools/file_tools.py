"""Read, write, and exact-edit tools protected by workspace state."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from pathlib import Path

from uthcode.core.permission import Effect, PermissionAction, ResourceScope
from uthcode.core.provider import CancellationToken, JsonPayload, ToolDefinition
from uthcode.core.tool import ToolExecutionResult, ToolPlanningAccess, ToolPreparation

from .workspace import FileReadTracker, WorkspacePathError, WorkspacePathResolver


_CANCELLED = "Error: tool call cancelled"


class ReadFileTool:
    """Read UTF-8 text with stable one-based line numbers."""

    _definition = ToolDefinition(
        "ReadFile",
        "Read a UTF-8 text file from the workspace with one-based line numbers.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "offset": {"type": "integer", "minimum": 1, "default": 1},
                "limit": {"type": "integer", "minimum": 1, "maximum": 2000, "default": 2000},
            },
            "required": ["path"],
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
        return ToolPlanningAccess.READ_ONLY

    def preflight(self, arguments: JsonPayload) -> ToolPreparation:
        path, scope = self._resolver.resolve_with_scope(_text(arguments, "path"))
        return ToolPreparation(
            action=PermissionAction(
                tool="ReadFile",
                action="read",
                effect=Effect.READ,
                resource=self._resolver.display(path),
                scope=scope,
            ),
            execution_arguments=_bind_path(arguments, path),
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
            path = self._resolver.resolve(_text(arguments, "path"))
        except (WorkspacePathError, TypeError, ValueError) as exc:
            return _error(str(exc))

        _notify_path_access(self._on_path_access, path)

        if not path.exists():
            return _error(f"Error: file not found: {self._resolver.display(path)}")
        if not path.is_file():
            return _error(f"Error: path is not a file: {self._resolver.display(path)}")

        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            return _error(f"Error: failed to read file: {exc}")
        except OSError as exc:
            return _error(f"Error: failed to read file: {exc}")

        if cancellation.cancelled:
            return _cancelled()
        try:
            self._tracker.record(path, content)
        except (OSError, RuntimeError):
            return _error("Error: failed to record file state after reading")

        offset = int(arguments.get("offset", 1))
        limit = int(arguments.get("limit", 2000))
        lines = content.splitlines()
        selected = lines[offset - 1 : offset - 1 + limit]
        numbered = [
            f"{line_number}\t{line}"
            for line_number, line in enumerate(selected, start=offset)
        ]
        return ToolExecutionResult(
            "\n".join(numbered),
            details={
                "evidence": "read_content",
                "content_digest": _content_digest(content),
            },
        )


class WriteFileTool:
    """Write a new file or replace an already-read workspace file."""

    _definition = ToolDefinition(
        "WriteFile",
        "Write UTF-8 text to a workspace file; existing files must be read first.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
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
        path, scope = self._resolver.resolve_with_scope(_text(arguments, "path"))
        return ToolPreparation(
            action=PermissionAction(
                tool="WriteFile",
                action="write",
                effect=Effect.WRITE,
                resource=self._resolver.display(path),
                scope=scope,
            ),
            execution_arguments=_bind_path(arguments, path),
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
            path = self._resolver.resolve(_text(arguments, "path"))
        except (WorkspacePathError, TypeError, ValueError) as exc:
            return _error(str(exc))

        if path.exists() or self._tracker.has_record(path):
            if not path.is_file():
                if path.exists():
                    return _error(f"Error: path is not a file: {self._resolver.display(path)}")
            ok, message = self._tracker.check(path)
            if not ok:
                return _error(message)

        if cancellation.cancelled:
            return _cancelled()
        before_digest: str | None = None
        if path.is_file():
            try:
                before_digest = _bytes_digest(path.read_bytes())
            except OSError as exc:
                return _error(f"Error: failed to read file before writing: {exc}")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if cancellation.cancelled:
                return _cancelled()
            path.write_text(_text(arguments, "content"), encoding="utf-8")
        except OSError as exc:
            return _error(f"Error: failed to write file: {exc}")

        self._tracker.update(path)
        try:
            after_digest = _bytes_digest(path.read_bytes())
        except OSError as exc:
            return _error(f"Error: failed to confirm file write: {exc}")
        return ToolExecutionResult(
            f"Successfully wrote to {self._resolver.display(path)}",
            details={
                "evidence": "file_change",
                "changed": before_digest != after_digest,
                "content_digest": after_digest,
            },
        )


class EditFileTool:
    """Replace exactly one non-empty string in an already-read file."""

    _definition = ToolDefinition(
        "EditFile",
        "Replace one unique non-empty string in an already-read workspace file.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old_string": {"type": "string", "minLength": 1},
                "new_string": {"type": "string"},
            },
            "required": ["path", "old_string", "new_string"],
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
        path, scope = self._resolver.resolve_with_scope(_text(arguments, "path"))
        return ToolPreparation(
            action=PermissionAction(
                tool="EditFile",
                action="edit",
                effect=Effect.WRITE,
                resource=self._resolver.display(path),
                scope=scope,
            ),
            execution_arguments=_bind_path(arguments, path),
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
            path = self._resolver.resolve(_text(arguments, "path"))
        except (WorkspacePathError, TypeError, ValueError) as exc:
            return _error(str(exc))

        _notify_path_access(self._on_path_access, path)

        if not path.exists():
            return _error(f"Error: file not found: {self._resolver.display(path)}")
        if not path.is_file():
            return _error(f"Error: path is not a file: {self._resolver.display(path)}")

        ok, message = self._tracker.check(path)
        if not ok:
            return _error(message)
        old_string = _text(arguments, "old_string")
        if not old_string:
            return _error("Error: old_string must not be empty")

        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            return _error(f"Error: failed to read file: {exc}")
        except OSError as exc:
            return _error(f"Error: failed to read file: {exc}")

        count = content.count(old_string)
        if count == 0:
            return _error("Error: old_string not found in file")
        if count > 1:
            return _error(f"Error: old_string found {count} times, must be unique")

        ok, message = self._tracker.check(path)
        if not ok:
            return _error(message)
        if cancellation.cancelled:
            return _cancelled()
        try:
            new_string = _text(arguments, "new_string")
            path.write_text(content.replace(old_string, new_string, 1), encoding="utf-8")
        except OSError as exc:
            return _error(f"Error: failed to write file: {exc}")

        self._tracker.update(path)
        try:
            after_digest = _bytes_digest(path.read_bytes())
        except OSError as exc:
            return _error(f"Error: failed to confirm file edit: {exc}")
        return ToolExecutionResult(
            f"Successfully edited {self._resolver.display(path)}",
            details={
                "evidence": "file_change",
                "changed": _content_digest(content) != after_digest,
                "content_digest": after_digest,
            },
        )


def _bind_path(arguments: JsonPayload, path: Path) -> JsonPayload:
    values = dict(arguments)
    values["path"] = str(path)
    return JsonPayload(values)


def _text(arguments: Mapping[str, object], name: str) -> str:
    value = arguments[name]
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    return value


def _error(message: str) -> ToolExecutionResult:
    return ToolExecutionResult(message, is_error=True)


def _cancelled() -> ToolExecutionResult:
    return ToolExecutionResult(_CANCELLED, is_error=True)


def _content_digest(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _bytes_digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _notify_path_access(
    callback: Callable[[Path], object] | None,
    path: Path,
) -> object | None:
    if callback is None:
        return None
    # The callback runs before file I/O.  Its normal Loader failure mode is a
    # diagnostic result (strict=False); unexpected exceptions remain visible
    # to the ToolExecutor instead of being silently discarded.
    return callback(path)


__all__ = ["EditFileTool", "ReadFileTool", "WriteFileTool"]
