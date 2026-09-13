"""Read-only Git workspace queries with bounded, argv-only subprocesses."""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from collections.abc import Mapping, Sequence
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
)

from .workspace import WorkspacePathError, WorkspacePathResolver


_OPERATIONS = frozenset({"status", "diff", "log", "show", "branch"})
_DEFAULT_LIMIT = 20
_MAX_LIMIT = 100
_DEFAULT_OUTPUT_BYTES = 256 * 1024
_MAX_OUTPUT_BYTES = 2 * 1024 * 1024


class GitUnavailableError(RuntimeError):
    """Git is unavailable or the workspace is not a repository."""


class GitQueryError(RuntimeError):
    """A bounded Git query returned an invalid or failed result."""


class GitQueryCancelled(GitQueryError):
    """The caller cancelled a running Git query before it completed."""


@dataclass(frozen=True, slots=True)
class GitCommandResult:
    returncode: int
    stdout: bytes
    stderr: bytes
    truncated: bool = False


class GitWorkspace:
    """Execute only the five frozen read-only Git operations."""

    def __init__(
        self,
        root: str | os.PathLike[str] | Path,
        *,
        timeout_seconds: float = 10.0,
        max_output_bytes: int = _DEFAULT_OUTPUT_BYTES,
        executable: str = "git",
    ) -> None:
        self.root = Path(root).expanduser().resolve(strict=False)
        if not self.root.is_dir():
            raise ValueError("Git workspace root must be a directory")
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)):
            raise TypeError("timeout_seconds must be a number")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if isinstance(max_output_bytes, bool) or not isinstance(max_output_bytes, int):
            raise TypeError("max_output_bytes must be an integer")
        if max_output_bytes <= 0:
            raise ValueError("max_output_bytes must be positive")
        if not isinstance(executable, str) or not executable or "\x00" in executable:
            raise ValueError("Git executable must be a non-empty string")
        self.timeout_seconds = min(float(timeout_seconds), 120.0)
        self.max_output_bytes = min(max_output_bytes, _MAX_OUTPUT_BYTES)
        self.executable = executable

    def status(self, *, cancellation: CancellationToken | None = None) -> dict[str, object]:
        result = self._run(
            "status",
            "--porcelain=v1",
            "-z",
            "--branch",
            "--untracked-files=all",
            "--no-renames",
            cancellation=cancellation,
        )
        records = result.stdout.split(b"\x00")
        branch: str | None = None
        entries: list[dict[str, object]] = []
        index = 0
        while index < len(records):
            raw = records[index]
            index += 1
            if not raw:
                continue
            text = _decode_path(raw)
            if text.startswith("## "):
                branch = text[3:]
                continue
            if len(raw) < 3:
                continue
            status = _decode_path(raw[:2])
            path = _decode_path(raw[3:])
            entry: dict[str, object] = {"xy": status, "path": path}
            if status and status[0] in {"R", "C"} and index < len(records):
                entry["original_path"] = _decode_path(records[index])
                index += 1
            entries.append(entry)
        return {
            "branch": branch,
            "entries": entries,
            "unborn": branch is not None and (
                "no commits yet" in branch.casefold()
                or "initial commit" in branch.casefold()
                or branch.endswith("(initial)")
            ),
            "truncated": result.truncated,
        }

    def diff(
        self,
        *,
        path: str | None = None,
        ref: str | None = None,
        cached: bool = False,
        cancellation: CancellationToken | None = None,
    ) -> dict[str, object]:
        args: list[str] = [
            "diff",
            "--no-ext-diff",
            "--no-textconv",
            "--no-color",
            "--no-renames",
        ]
        if cached:
            args.append("--cached")
        if ref is not None:
            args.append(_ref(ref))
        args.append("--")
        if path is not None:
            args.append(_pathspec(path))
        result = self._run(*args, cancellation=cancellation)
        return _text_payload(result)

    def log(
        self,
        *,
        limit: int = _DEFAULT_LIMIT,
        path: str | None = None,
        ref: str | None = None,
        cancellation: CancellationToken | None = None,
    ) -> dict[str, object]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= _MAX_LIMIT:
            raise ValueError(f"limit must be between 1 and {_MAX_LIMIT}")
        args = [
            "log",
            "--no-color",
            "--date=iso-strict",
            f"-n{limit}",
            "--format=%H%x00%an%x00%aI%x00%s%x00",
        ]
        if ref is not None:
            args.append(_ref(ref))
        args.append("--")
        if path is not None:
            args.append(_pathspec(path))
        result = self._run(*args, cancellation=cancellation)
        records = result.stdout.split(b"\x00")
        commits: list[dict[str, str]] = []
        index = 0
        while index + 3 < len(records):
            commit, author, date, subject = records[index : index + 4]
            index += 4
            if not commit:
                continue
            commits.append(
                {
                    "commit": _decode_path(commit),
                    "author": _decode_path(author),
                    "date": _decode_path(date),
                    "subject": _decode_path(subject),
                }
            )
        return {"commits": commits, "truncated": result.truncated}

    def show(
        self,
        *,
        ref: str,
        path: str | None = None,
        cancellation: CancellationToken | None = None,
    ) -> dict[str, object]:
        args = [
            "show",
            "--no-ext-diff",
            "--no-textconv",
            "--no-color",
            "--no-renames",
            _ref(ref),
            "--",
        ]
        if path is not None:
            args.append(_pathspec(path))
        return _text_payload(self._run(*args, cancellation=cancellation))

    def branch(self, *, cancellation: CancellationToken | None = None) -> dict[str, object]:
        result = self._run(
            "for-each-ref",
            "--format=%(HEAD)%00%(refname:short)%00%(objectname)%00",
            "refs/heads",
            "refs/remotes",
            cancellation=cancellation,
        )
        records = result.stdout.split(b"\x00")
        branches: list[dict[str, object]] = []
        index = 0
        while index + 2 < len(records):
            head, name, commit = records[index : index + 3]
            index += 3
            if not name:
                continue
            branches.append(
                {
                    "current": _decode_path(head) == "*",
                    "name": _decode_path(name),
                    "commit": _decode_path(commit),
                }
            )
        try:
            current = _decode_path(
                self._run(
                    "symbolic-ref",
                    "--short",
                    "-q",
                    "HEAD",
                    allow_failure=True,
                    cancellation=cancellation,
                ).stdout
            ).strip()
        except GitQueryError:
            current = None
        detached = current in {None, ""}
        if detached:
            current = None
        head = self._run(
            "rev-parse",
            "--verify",
            "HEAD",
            allow_failure=True,
            cancellation=cancellation,
        )
        return {
            "current": current,
            "detached": detached,
            "unborn": head.returncode != 0,
            "branches": branches,
            "truncated": result.truncated,
        }

    def query(self, operation: str, **kwargs: object) -> dict[str, object]:
        if operation not in _OPERATIONS:
            raise ValueError(f"unsupported Git operation: {operation}")
        method = getattr(self, operation)
        return method(**kwargs)

    def _run(
        self,
        *args: str,
        allow_failure: bool = False,
        cancellation: CancellationToken | None = None,
    ) -> GitCommandResult:
        if any(not isinstance(arg, str) or "\x00" in arg for arg in args):
            raise ValueError("Git arguments must be NUL-free strings")
        env = os.environ.copy()
        env.update(
            {
                "GIT_OPTIONAL_LOCKS": "0",
                "GIT_PAGER": "cat",
                "GIT_TERMINAL_PROMPT": "0",
                "GIT_EXTERNAL_DIFF": "",
                "GIT_DIFF_OPTS": "",
            }
        )
        argv = [self.executable, "--no-pager", "--no-optional-locks", "-C", str(self.root), *args]
        try:
            process = subprocess.Popen(
                argv,
                cwd=self.root,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise GitUnavailableError("Git executable is unavailable") from exc
        except OSError as exc:
            raise GitUnavailableError("Git query could not be started") from exc

        # Drain both pipes concurrently.  Git can block while writing either
        # stream; using ``run(..., PIPE)`` and slicing after exit both risks a
        # deadlock and retains unbounded command output in the parent.
        stdout = bytearray()
        stderr = bytearray()
        truncated = threading.Event()

        def drain(stream: object, target: bytearray) -> None:
            reader = getattr(stream, "read", None)
            if not callable(reader):
                return
            while True:
                chunk = reader(8192)
                if not chunk:
                    return
                if not isinstance(chunk, bytes):
                    chunk = bytes(chunk)
                remaining = self.max_output_bytes - len(target)
                if remaining > 0:
                    target.extend(chunk[:remaining])
                if len(chunk) > max(remaining, 0):
                    # Continue draining and discard the bounded overflow so
                    # the child cannot block on a full pipe.  The caller gets
                    # an explicit truncation fact rather than a false full
                    # transcript.
                    truncated.set()

        stdout_thread = threading.Thread(
            target=drain,
            args=(process.stdout, stdout),
            name="uthcode-git-stdout",
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=drain,
            args=(process.stderr, stderr),
            name="uthcode-git-stderr",
            daemon=True,
        )
        stdout_thread.start()
        stderr_thread.start()

        deadline = time.monotonic() + self.timeout_seconds
        try:
            while process.poll() is None:
                if cancellation is not None and cancellation.cancelled:
                    _stop_process(process)
                    raise GitQueryCancelled("Git query cancelled")
                if time.monotonic() >= deadline:
                    _stop_process(process)
                    raise GitQueryError("Git query timed out")
                time.sleep(0.01)
            returncode = process.returncode
        finally:
            # The process is already complete on the normal path.  On timeout
            # or cancellation _stop_process has reaped it.  Joining only the
            # bounded drainers ensures no background pipe reader survives the
            # Tool call.
            stdout_thread.join(timeout=1.0)
            stderr_thread.join(timeout=1.0)
            for stream in (process.stdout, process.stderr):
                close = getattr(stream, "close", None)
                if callable(close):
                    try:
                        close()
                    except OSError:
                        pass

        if returncode != 0 and not allow_failure:
            message = _decode_path(bytes(stderr)).strip() or "Git query failed"
            if "not a git repository" in message.casefold():
                raise GitUnavailableError("workspace is not a Git repository")
            if "does not exist" in message.casefold() or "unknown revision" in message.casefold():
                raise GitQueryError(message)
            raise GitQueryError(message)
        return GitCommandResult(returncode, bytes(stdout), bytes(stderr), truncated.is_set())


class GitWorkspaceTool:
    """Application Tool wrapper around :class:`GitWorkspace`."""

    _definition = ToolDefinition(
        "GitWorkspace",
        "Read bounded Git status, diff, log, show, or branch information.",
        {
            "type": "object",
            "properties": {
                "operation": {"type": "string", "enum": sorted(_OPERATIONS)},
                "path": {"type": ["string", "null"]},
                "ref": {"type": ["string", "null"]},
                "cached": {"type": "boolean", "default": False},
                "limit": {"type": "integer", "minimum": 1, "maximum": _MAX_LIMIT},
            },
            "required": ["operation"],
            "additionalProperties": False,
        },
    )

    def __init__(self, root: str | os.PathLike[str] | Path, *, workspace: GitWorkspace | None = None) -> None:
        self._workspace = workspace or GitWorkspace(root)

    @property
    def definition(self) -> ToolDefinition:
        return self._definition

    @property
    def planning_access(self) -> ToolPlanningAccess:
        return ToolPlanningAccess.READ_ONLY

    def preflight(self, arguments: JsonPayload) -> ToolPreparation:
        operation = _operation(arguments.get("operation"))
        self._validate_arguments(operation, arguments)
        return ToolPreparation(
            action=PermissionAction(
                tool=self._definition.name,
                action=operation,
                effect=Effect.READ,
                resource=self._workspace.root.as_posix(),
                scope=ResourceScope.INSIDE,
            ),
            execution_arguments=arguments,
        )

    async def execute(
        self,
        arguments: JsonPayload,
        *,
        cancellation: CancellationToken,
    ) -> ToolExecutionResult:
        if cancellation.cancelled:
            return ToolExecutionResult(
                "Error: tool call cancelled",
                is_error=True,
                failure=ToolFailure(ToolFailureKind.CANCELLED.value, retryable=True),
            )
        try:
            operation = _operation(arguments.get("operation"))
            values = self._validate_arguments(operation, arguments)
            result = self._workspace.query(operation, cancellation=cancellation, **values)
        except GitQueryCancelled as exc:
            return _failure(str(exc), ToolFailureKind.CANCELLED, retryable=True)
        except GitUnavailableError as exc:
            return _failure(str(exc), ToolFailureKind.UNAVAILABLE)
        except GitQueryError as exc:
            return _failure(str(exc), ToolFailureKind.CONFLICT)
        except (TypeError, ValueError, WorkspacePathError) as exc:
            return _failure(f"Error: invalid GitWorkspace arguments: {exc}", ToolFailureKind.INVALID_INPUT)
        if cancellation.cancelled:
            return ToolExecutionResult(
                "Error: tool call cancelled",
                is_error=True,
                failure=ToolFailure(ToolFailureKind.CANCELLED.value, retryable=True),
            )
        payload = {"operation": operation, **result}
        return ToolExecutionResult(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            details={"operation": operation, **result},
        )

    def _validate_arguments(self, operation: str, arguments: Mapping[str, object]) -> dict[str, object]:
        path = arguments.get("path")
        if path is not None:
            path = _pathspec(path)
        ref = arguments.get("ref")
        if ref is not None:
            ref = _ref(ref)
        values: dict[str, object] = {}
        if operation == "diff":
            values.update(path=path, ref=ref, cached=bool(arguments.get("cached", False)))
        elif operation == "log":
            values.update(limit=arguments.get("limit", _DEFAULT_LIMIT), path=path, ref=ref)
        elif operation == "show":
            if ref is None:
                raise ValueError("show requires ref")
            values.update(ref=ref, path=path)
        elif operation in {"status", "branch"}:
            if path is not None or ref is not None:
                raise ValueError(f"{operation} does not accept path or ref")
        return values


def _operation(value: object) -> str:
    if not isinstance(value, str) or value not in _OPERATIONS:
        raise ValueError("operation must be one of status, diff, log, show, branch")
    return value


def _pathspec(value: object) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValueError("path must be a non-empty NUL-free string")
    normalized = value.replace("\\", "/")
    if normalized.startswith("/") or normalized.startswith("../") or normalized == ".." or "/../" in normalized:
        raise ValueError("path must stay within the workspace")
    return normalized


def _ref(value: object) -> str:
    if not isinstance(value, str) or not value or "\x00" in value or value.startswith("-"):
        raise ValueError("ref must be a non-empty safe revision")
    return value


def _decode_path(value: bytes) -> str:
    return value.decode("utf-8", errors="surrogateescape")


def _text_payload(result: GitCommandResult) -> dict[str, object]:
    return {
        "text": _decode_path(result.stdout),
        "truncated": result.truncated,
        "size_bytes": len(result.stdout),
    }


def _stop_process(process: subprocess.Popen[bytes]) -> None:
    """Terminate and reap a Git child without collecting its pipes."""

    if process.poll() is not None:
        return
    try:
        process.terminate()
    except OSError:
        pass
    try:
        process.wait(timeout=0.5)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
        except OSError:
            pass
        try:
            process.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            # The bounded drain threads will still close their handles in the
            # caller's finally block; never fall back to communicate().
            pass


def _failure(
    message: str,
    kind: ToolFailureKind,
    *,
    retryable: bool = False,
) -> ToolExecutionResult:
    return ToolExecutionResult(
        f"Error: {message}",
        is_error=True,
        failure=ToolFailure(kind.value, retryable=retryable),
    )


GitWorkspaceQueryTool = GitWorkspaceTool


__all__ = [
    "GitCommandResult",
    "GitQueryError",
    "GitUnavailableError",
    "GitWorkspace",
    "GitWorkspaceQueryTool",
    "GitWorkspaceTool",
]
