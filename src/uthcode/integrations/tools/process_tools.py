"""Current-user, current-OS-shell process execution for the Bash tool."""

from __future__ import annotations

import asyncio
import ctypes
import locale
import os
import re
import shlex
import signal
import subprocess
import time
from collections.abc import Mapping
from ctypes import wintypes
from pathlib import Path
from typing import Any

from uthcode.core.permission import (
    CircuitBreaker,
    Effect,
    PermissionAction,
    ResourceScope,
)
from uthcode.core.provider import CancellationToken, JsonPayload, ToolDefinition
from uthcode.core.tool import ToolExecutionResult, ToolPlanningAccess, ToolPreparation
from uthcode.core.command_security import safe_bash_command_summary
from uthcode.integrations.permissions import (
    BASH_ACTION_FACT_MARKER,
    BASH_GUARD_FACT_MARKER,
    BASH_SENSITIVE_TARGET_MARKER,
    is_sensitive_resource,
)


_CANCELLED = "Error: command cancelled"
_REAP_TIMEOUT_SECONDS = 5.0
_TERMINATION_GRACE_SECONDS = 0.25


class _ProcessTreeControl:
    async def terminate(self, process: asyncio.subprocess.Process) -> bool:
        raise NotImplementedError

    def close(self) -> None:
        return None


class _StartedProcess:
    def __init__(
        self,
        process: asyncio.subprocess.Process,
        control: _ProcessTreeControl,
    ) -> None:
        self.process = process
        self.control = control


class _PosixProcessGroupControl(_ProcessTreeControl):
    def __init__(self, process_group_id: int) -> None:
        self._process_group_id = process_group_id

    async def terminate(self, process: asyncio.subprocess.Process) -> bool:
        term_result = _signal_posix_process_group(
            self._process_group_id,
            signal.SIGTERM,
        )
        if term_result is None:
            return False

        direct_reaped = await _await_process(
            process,
            _TERMINATION_GRACE_SECONDS,
        )
        group_empty = await _await_posix_process_group_exit(
            self._process_group_id,
            _TERMINATION_GRACE_SECONDS,
        )
        if direct_reaped and group_empty:
            return True

        kill_result = _signal_posix_process_group(
            self._process_group_id,
            signal.SIGKILL,
        )
        if kill_result is None:
            return False
        direct_reaped = direct_reaped or await _await_process(
            process,
            _REAP_TIMEOUT_SECONDS,
        )
        group_empty = await _await_posix_process_group_exit(
            self._process_group_id,
            _REAP_TIMEOUT_SECONDS,
        )
        return direct_reaped and group_empty


if os.name == "nt":

    class _WindowsThreadEntry32(ctypes.Structure):
        _fields_ = (
            ("dwSize", ctypes.c_uint32),
            ("cntUsage", ctypes.c_uint32),
            ("th32ThreadID", ctypes.c_uint32),
            ("th32OwnerProcessID", ctypes.c_uint32),
            ("tpBasePri", ctypes.c_int32),
            ("tpDeltaPri", ctypes.c_int32),
            ("dwFlags", ctypes.c_uint32),
        )

    class _WindowsJobAccountingInfo(ctypes.Structure):
        _fields_ = (
            ("total_user_time", ctypes.c_int64),
            ("total_kernel_time", ctypes.c_int64),
            ("this_period_total_user_time", ctypes.c_int64),
            ("this_period_total_kernel_time", ctypes.c_int64),
            ("total_page_fault_count", ctypes.c_uint32),
            ("total_processes", ctypes.c_uint32),
            ("active_processes", ctypes.c_uint32),
            ("total_terminated_processes", ctypes.c_uint32),
        )

    class _WindowsKernelApi:
        _THREAD_SUSPEND_RESUME = 0x0002
        _TH32CS_SNAPTHREAD = 0x00000004
        _INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
        _WAIT_FAILED = 0xFFFFFFFF

        def __init__(self) -> None:
            self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            handle = ctypes.c_void_p

            self._kernel32.CreateJobObjectW.argtypes = [
                wintypes.LPVOID,
                wintypes.LPCWSTR,
            ]
            self._kernel32.CreateJobObjectW.restype = handle
            self._kernel32.AssignProcessToJobObject.argtypes = [handle, handle]
            self._kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
            self._kernel32.TerminateJobObject.argtypes = [handle, wintypes.UINT]
            self._kernel32.TerminateJobObject.restype = wintypes.BOOL
            self._kernel32.QueryInformationJobObject.argtypes = [
                handle,
                wintypes.INT,
                wintypes.LPVOID,
                wintypes.DWORD,
                ctypes.POINTER(wintypes.DWORD),
            ]
            self._kernel32.QueryInformationJobObject.restype = wintypes.BOOL
            self._kernel32.CloseHandle.argtypes = [handle]
            self._kernel32.CloseHandle.restype = wintypes.BOOL
            self._kernel32.CreateToolhelp32Snapshot.argtypes = [
                wintypes.DWORD,
                wintypes.DWORD,
            ]
            self._kernel32.CreateToolhelp32Snapshot.restype = handle
            self._kernel32.Thread32First.argtypes = [
                handle,
                ctypes.POINTER(_WindowsThreadEntry32),
            ]
            self._kernel32.Thread32First.restype = wintypes.BOOL
            self._kernel32.Thread32Next.argtypes = [
                handle,
                ctypes.POINTER(_WindowsThreadEntry32),
            ]
            self._kernel32.Thread32Next.restype = wintypes.BOOL
            self._kernel32.OpenThread.argtypes = [
                wintypes.DWORD,
                wintypes.BOOL,
                wintypes.DWORD,
            ]
            self._kernel32.OpenThread.restype = handle
            self._kernel32.ResumeThread.argtypes = [handle]
            self._kernel32.ResumeThread.restype = wintypes.DWORD

        @staticmethod
        def _handle_value(value: object) -> int:
            if isinstance(value, ctypes.c_void_p):
                return int(value.value or 0)
            return int(value or 0)

        @staticmethod
        def _winerror(message: str) -> OSError:
            error_code = ctypes.get_last_error()
            return OSError(error_code, f"{message}: {error_code}")

        def create_job(self) -> int:
            handle = self._handle_value(
                self._kernel32.CreateJobObjectW(None, None)
            )
            if not handle:
                raise self._winerror("CreateJobObjectW failed")
            return handle

        def close_handle(self, handle: int) -> None:
            if not self._kernel32.CloseHandle(ctypes.c_void_p(handle)):
                raise self._winerror("CloseHandle failed")

        def assign_process(self, job: int, process: int) -> None:
            if not self._kernel32.AssignProcessToJobObject(
                ctypes.c_void_p(job),
                ctypes.c_void_p(process),
            ):
                raise self._winerror("AssignProcessToJobObject failed")

        def terminate_job(self, job: int) -> None:
            if not self._kernel32.TerminateJobObject(
                ctypes.c_void_p(job),
                1,
            ):
                raise self._winerror("TerminateJobObject failed")

        def active_processes(self, job: int) -> int:
            info = _WindowsJobAccountingInfo()
            returned = ctypes.c_uint32()
            if not self._kernel32.QueryInformationJobObject(
                ctypes.c_void_p(job),
                1,
                ctypes.byref(info),
                ctypes.sizeof(info),
                ctypes.byref(returned),
            ):
                raise self._winerror("QueryInformationJobObject failed")
            return int(info.active_processes)

        def resume_primary_thread(self, process_id: int) -> None:
            snapshot = self._handle_value(
                self._kernel32.CreateToolhelp32Snapshot(
                    self._TH32CS_SNAPTHREAD,
                    0,
                )
            )
            if not snapshot or snapshot == self._INVALID_HANDLE_VALUE:
                raise self._winerror("CreateToolhelp32Snapshot failed")

            entry = _WindowsThreadEntry32()
            entry.dwSize = ctypes.sizeof(entry)
            try:
                found = bool(
                    self._kernel32.Thread32First(
                        ctypes.c_void_p(snapshot),
                        ctypes.byref(entry),
                    )
                )
                while found:
                    if entry.th32OwnerProcessID == process_id:
                        thread = self._handle_value(
                            self._kernel32.OpenThread(
                                self._THREAD_SUSPEND_RESUME,
                                False,
                                entry.th32ThreadID,
                            )
                        )
                        if not thread:
                            raise self._winerror("OpenThread failed")
                        try:
                            if self._kernel32.ResumeThread(
                                ctypes.c_void_p(thread)
                            ) == self._WAIT_FAILED:
                                raise self._winerror("ResumeThread failed")
                        finally:
                            self.close_handle(thread)
                        return
                    found = bool(
                        self._kernel32.Thread32Next(
                            ctypes.c_void_p(snapshot),
                            ctypes.byref(entry),
                        )
                    )
            finally:
                self.close_handle(snapshot)
            raise RuntimeError(
                f"could not find the suspended primary thread for PID {process_id}"
            )


    class _WindowsJobControl(_ProcessTreeControl):
        def __init__(self) -> None:
            self._api = _WindowsKernelApi()
            self._job = self._api.create_job()
            self._assigned = False
            self._termination_requested = False
            self._confirmed_empty = False

        def attach_and_resume(self, process: asyncio.subprocess.Process) -> None:
            process_handle = _windows_process_handle(process)
            self._api.assign_process(self._job, process_handle)
            self._assigned = True
            self._api.resume_primary_thread(process.pid)

        async def terminate(self, process: asyncio.subprocess.Process) -> bool:
            self._termination_requested = True
            if self._assigned:
                try:
                    self._api.terminate_job(self._job)
                except OSError:
                    return False
            else:
                try:
                    process.kill()
                except (OSError, ProcessLookupError):
                    pass

            direct_reaped = await _await_process(
                process,
                _REAP_TIMEOUT_SECONDS,
            )
            job_empty = await self._await_empty()
            self._confirmed_empty = direct_reaped and job_empty
            return self._confirmed_empty

        async def _await_empty(self) -> bool:
            deadline = time.monotonic() + _REAP_TIMEOUT_SECONDS
            while True:
                try:
                    if self._api.active_processes(self._job) == 0:
                        return True
                except OSError:
                    return False
                if time.monotonic() >= deadline:
                    return False
                await asyncio.sleep(0.01)

        def close(self) -> None:
            if not getattr(self, "_job", 0):
                return
            if self._termination_requested and not self._confirmed_empty:
                try:
                    self._api.terminate_job(self._job)
                except OSError:
                    pass
            try:
                self._api.close_handle(self._job)
            finally:
                self._job = 0


else:

    class _WindowsJobControl(_ProcessTreeControl):  # pragma: no cover
        def __init__(self) -> None:
            raise RuntimeError("Windows job control is unavailable")


def _windows_process_handle(process: asyncio.subprocess.Process) -> int:
    transport = getattr(process, "_transport", None)
    if transport is None:
        raise RuntimeError("asyncio process transport is unavailable")
    popen = transport.get_extra_info("subprocess")
    process_handle = getattr(popen, "_handle", None)
    if process_handle is None:
        raise RuntimeError("Windows process handle is unavailable")
    return int(process_handle)


_READ_COMMANDS = frozenset(
    {
        "cat",
        "dir",
        "echo",
        "file",
        "find",
        "findstr",
        "format-list",
        "get-acl",
        "get-childitem",
        "get-itemproperty",
        "head",
        "less",
        "ls",
        "more",
        "pwd",
        "rg",
        "sed",
        "select-string",
        "stat",
        "tail",
        "type",
        "uname",
        "wc",
        "where",
        "which",
        "whoami",
        "grep",
        "egrep",
        "fgrep",
        "get-content",
        "get-filehash",
        "get-item",
        "resolve-path",
        "test-path",
    }
)
_WRITE_COMMANDS = frozenset(
    {
        "cp",
        "copy",
        "make",
        "md",
        "mkdir",
        "mktemp",
        "move",
        "mv",
        "npm install",
        "pip install",
        "ren",
        "rename",
        "add-content",
        "copy-item",
        "move-item",
        "out-file",
        "sed -i",
        "set-content",
        "tee",
        "touch",
    }
)
_DESTRUCTIVE_COMMANDS = frozenset(
    {
        "chmod",
        "chown",
        "del",
        "diskpart",
        "erase",
        "format",
        "kill",
        "mkfs",
        "rd",
        "remove-item",
        "rm",
        "rmdir",
        "shutdown",
    }
)
_EXTERNAL_COMMANDS = frozenset(
    {
        "curl",
        "docker",
        "ftp",
        "invoke-restmethod",
        "invoke-webrequest",
        "kubectl",
        "nc",
        "net",
        "npm publish",
        "podman",
        "scp",
        "sftp",
        "ssh",
        "wget",
    }
)
_SIMPLE_COMMAND_PREFIXES = (
    (("npm", "publish"), Effect.EXTERNAL),
    (("npm", "install"), Effect.WRITE),
    (("pip", "install"), Effect.WRITE),
    (("sed", "-i"), Effect.WRITE),
)
_GIT_READ_SUBCOMMANDS = frozenset(
    {"status", "diff", "log", "show", "rev-parse", "ls-files"}
)
_GIT_WRITE_SUBCOMMANDS = frozenset(
    {
        "add",
        "am",
        "apply",
        "cherry-pick",
        "commit",
        "init",
        "merge",
        "mv",
        "rebase",
        "revert",
        "stash",
    }
)
_GIT_EXTERNAL_SUBCOMMANDS = frozenset({"clone", "fetch", "pull", "push"})
_GIT_BRANCH_DELETE_OPTIONS = frozenset({"-d", "--delete"})
_GIT_BRANCH_MOVE_OPTIONS = frozenset(
    {"-m", "--move", "-c", "--copy", "-f", "--force", "--edit-description"}
)
_GIT_BRANCH_READ_OPTIONS = frozenset(
    {
        "-a",
        "-l",
        "-r",
        "-v",
        "-vv",
        "--all",
        "--contains",
        "--list",
        "--merged",
        "--no-merged",
        "--no-contains",
        "--points-at",
        "--remotes",
        "--show-current",
        "--verbose",
    }
)
_GIT_TAG_READ_OPTIONS = frozenset(
    {
        "-l",
        "--contains",
        "--list",
        "--merged",
        "--no-merged",
        "--no-contains",
        "--points-at",
    }
)
_GIT_TAG_CREATE_OPTIONS = frozenset(
    {
        "-a",
        "-f",
        "-m",
        "-s",
        "--annotate",
        "--cleanup",
        "--create-reflog",
        "--force",
        "--local-user",
        "--message",
        "--sign",
    }
)
_GIT_RESET_WRITE_OPTIONS = frozenset(
    {
        "-n",
        "--intent-to-add",
        "--mixed",
        "--pathspec-file-nul",
        "--pathspec-from-file",
        "--soft",
    }
)
_EFFECT_RANK = {
    Effect.READ: 1,
    Effect.UNKNOWN: 2,
    Effect.WRITE: 3,
    Effect.DESTRUCTIVE: 4,
    Effect.EXTERNAL: 5,
}
_BASH_CONTENT_READ_COMMANDS = frozenset(
    {
        "cat",
        "get-content",
        "head",
        "less",
        "more",
        "sed",
        "tail",
        "type",
        "wc",
        "get-filehash",
    }
)
_BASH_CONTENT_SEARCH_COMMANDS = frozenset(
    {
        "egrep",
        "fgrep",
        "findstr",
        "grep",
        "rg",
        "select-string",
    }
)
_BASH_METADATA_COMMANDS = frozenset(
    {
        "dir",
        "file",
        "find",
        "format-list",
        "get-acl",
        "get-childitem",
        "get-item",
        "get-itemproperty",
        "ls",
        "resolve-path",
        "stat",
        "test-path",
    }
)
_BASH_DATA_COMMANDS = frozenset(
    {
        "echo",
        "format-list",
        "format-table",
        "foreach-object",
        "out-string",
        "printf",
        "print",
        "write-host",
        "write-output",
    }
)
_BASH_OPAQUE_NESTED_EXECUTION = re.compile(
    r"(?ix)(?:"
    r"(?<![A-Za-z0-9_-])-exec(?:dir)?(?![A-Za-z0-9_-])"
    r"|(?<![A-Za-z0-9_-])xargs(?![A-Za-z0-9_-])"
    r"|(?<![A-Za-z0-9_-])(?:sh|bash|zsh|pwsh|powershell)(?:\.exe)?"
    r"\s+-(?:c|command)\b"
    r"|(?<![A-Za-z0-9_-])cmd(?:\.exe)?\s+/c\b"
    r")"
)
def _scan_bash_command(
    command: str,
) -> tuple[tuple[tuple[str, str | None], ...], bool]:
    """Scan executable shell segments and flag opaque nested execution."""

    normalized = command.strip()
    if not normalized:
        return (), False

    segments: list[tuple[str, str | None]] = []
    start = 0
    connector_before: str | None = None
    quote: str | None = None
    escaped = False
    arithmetic_depth = 0
    arithmetic_escaped = False
    group_depth = 0
    nested_execution = False
    index = 0
    while index < len(normalized):
        character = normalized[index]
        if arithmetic_depth:
            if arithmetic_escaped:
                arithmetic_escaped = False
            elif character == "\\":
                arithmetic_escaped = True
            elif normalized.startswith("$((", index):
                arithmetic_depth += 2
                index += 3
                continue
            elif normalized.startswith("$(", index):
                nested_execution = True
                arithmetic_depth += 1
                index += 2
                continue
            elif character == "`":
                nested_execution = True
            elif character == "(":
                arithmetic_depth += 1
            elif character == ")":
                arithmetic_depth -= 1
            index += 1
            continue
        if quote is not None:
            if escaped:
                escaped = False
            elif character == "\\" and quote != "'":
                escaped = True
            elif quote == '"' and normalized.startswith("$((", index):
                arithmetic_depth = 2
                index += 3
                continue
            elif quote == '"' and (
                normalized.startswith("$(", index) or character == "`"
            ):
                nested_execution = True
            elif character == quote:
                quote = None
            index += 1
            continue

        if escaped:
            escaped = False
            index += 1
            continue
        if character == "\\":
            escaped = True
            index += 1
            continue
        if character in {"'", '"'}:
            quote = character
            index += 1
            continue
        if normalized.startswith("$((", index):
            arithmetic_depth = 2
            index += 3
            continue
        if normalized.startswith("$(", index) or character == "`":
            nested_execution = True
            index += 1
            continue
        if character == "(":
            group_depth += 1
            index += 1
            continue
        if character == ")" and group_depth:
            group_depth -= 1
            index += 1
            continue
        if character == "{" and (
            (
                index == 0
                or normalized[index - 1].isspace()
                or normalized[index - 1] in ";|&)"
            )
            and (index + 1 == len(normalized) or normalized[index + 1].isspace())
        ):
            nested_execution = True

        connector: str | None = None
        width = 0
        if normalized.startswith("&&", index):
            connector = "&&"
            width = 2
        elif normalized.startswith("||", index):
            connector = "||"
            width = 2
        elif character in {";", "|", "\n", "\r"} or (
            character == "&"
            and (
                index == 0
                or normalized[index - 1] not in "<>"
            )
            and (index + 1 == len(normalized) or normalized[index + 1] != ">")
        ):
            connector = character
            width = 1
            if character == "\r" and normalized.startswith("\r\n", index):
                connector = "\n"
                width = 2
        if connector is not None and group_depth == 0:
            segment = normalized[start:index].strip()
            if segment:
                segments.append((segment, connector_before))
            connector_before = connector
            index += width
            start = index
            continue
        index += 1

    segment = normalized[start:].strip()
    if segment:
        segments.append((segment, connector_before))
    return tuple(segments), nested_execution


def _split_bash_segments(command: str) -> tuple[tuple[str, str | None], ...]:
    return _scan_bash_command(command)[0]


def _segment_tokens(segment: str) -> list[str]:
    segment = _unwrap_command_group(segment)
    try:
        return shlex.split(segment, posix=os.name != "nt")
    except ValueError:
        return []


def _segment_program(segment: str) -> tuple[str, list[str]]:
    tokens = _segment_tokens(segment)
    while tokens and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", tokens[0]):
        tokens.pop(0)
    if not tokens:
        return "", []
    program = tokens[0].strip('"\'').replace("\\", "/").rsplit("/", 1)[-1].lower()
    return program, tokens[1:]


def _unwrap_command_group(segment: str) -> str:
    """Remove balanced CMD grouping parentheses around a visible segment."""

    value = segment.strip()
    while value.startswith("("):
        depth = 0
        quote: str | None = None
        escaped = False
        closing: int | None = None
        for index, character in enumerate(value):
            if quote is not None:
                if escaped:
                    escaped = False
                elif character == "\\" and quote != "'":
                    escaped = True
                elif character == quote:
                    quote = None
                continue
            if character in {"'", '"'}:
                quote = character
            elif character == "(":
                depth += 1
            elif character == ")":
                depth -= 1
                if depth == 0:
                    closing = index
                    break
        if closing is None:
            break
        remainder = value[closing + 1 :].strip()
        if remainder:
            value = f"{value[1:closing].strip()} {remainder}"
        else:
            value = value[1:closing].strip()
    return value.rstrip(")").strip()


def _outer_command_group(segment: str) -> str | None:
    """Return the content when one balanced group encloses the whole segment."""

    value = segment.strip()
    if not value.startswith("("):
        return None
    depth = 0
    quote: str | None = None
    escaped = False
    for index, character in enumerate(value):
        if quote is not None:
            if escaped:
                escaped = False
            elif character == "\\" and quote != "'":
                escaped = True
            elif character == quote:
                quote = None
            continue
        if character in {"'", '"'}:
            quote = character
        elif character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth == 0:
                return value[1:index] if not value[index + 1 :].strip() else None
    return None


def _redirection_targets(segment: str) -> tuple[tuple[str, str], ...]:
    """Return shell input/output redirection targets from one segment."""

    tokens = _segment_tokens(segment)
    targets: list[tuple[str, str]] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token in {"<", ">", ">>"}:
            if index + 1 < len(tokens):
                direction = "input" if token == "<" else "output"
                targets.append((direction, tokens[index + 1]))
                index += 2
                continue
        standalone = re.match(r"^(?P<operator>\d*(?:>>?|<|&>|>&))$", token)
        if standalone is not None and index + 1 < len(tokens):
            operator = standalone.group("operator")
            direction = "input" if operator.endswith("<") else "output"
            targets.append((direction, tokens[index + 1]))
            index += 2
            continue
        descriptor_copy = re.match(r"^\d*>&(?P<target>\d+)$", token)
        if descriptor_copy is not None:
            targets.append(("output", f"&{descriptor_copy.group('target')}"))
            index += 1
            continue
        match = re.match(r"^(?P<operator>\d*(?:>>?|<|&>|>&))(?P<target>.+)$", token)
        if match is not None:
            operator = match.group("operator")
            if operator.startswith("<"):
                index += 1
                continue
            targets.append(("output", match.group("target")))
        index += 1
    return tuple(targets)


def _redirection_effect(segment: str) -> Effect | None:
    """Return the effect added by shell redirections in one segment."""

    redirections = _redirection_targets(segment)
    if not redirections:
        tokens = _segment_tokens(segment)
        malformed = any(
            re.fullmatch(r"\d*(?:>>?|<|&>|>&)", token) is not None
            for token in tokens
        )
        return Effect.UNKNOWN if malformed else None
    for direction, target in redirections:
        if direction != "output":
            continue
        normalized = target.strip("\"'").replace("\\", "/").lower()
        if re.fullmatch(r"&\d+", normalized):
            continue
        if normalized in {"nul", "nul:", "/dev/null"}:
            continue
        return Effect.WRITE
    return None


def _sensitive_arguments(arguments: list[str]) -> bool:
    return any(
        is_sensitive_resource(argument)
        or is_sensitive_resource(argument.strip("\"'{}\\;|&"))
        for argument in arguments
    )


def _segment_sensitive_target(
    segment: str,
    program: str,
    arguments: list[str],
    effect: Effect,
) -> bool:
    """Associate sensitive paths only with the segment that can open them."""

    redirections = _redirection_targets(segment)
    if any(
        direction == "input" and is_sensitive_resource(target)
        for direction, target in redirections
    ):
        return True
    if any(
        direction == "output" and is_sensitive_resource(target)
        for direction, target in redirections
    ):
        return True

    if program in _BASH_CONTENT_READ_COMMANDS:
        return _sensitive_arguments(arguments)
    if program in _BASH_CONTENT_SEARCH_COMMANDS:
        return _sensitive_arguments(arguments)
    if program in _BASH_METADATA_COMMANDS or program in _BASH_DATA_COMMANDS:
        return False
    if effect in {Effect.WRITE, Effect.DESTRUCTIVE, Effect.UNKNOWN}:
        return _sensitive_arguments(arguments)
    return False


def _nested_sensitive_content_target(command: str) -> bool:
    """Find sensitive operands attached to nested content readers."""

    names = sorted(
        _BASH_CONTENT_READ_COMMANDS | _BASH_CONTENT_SEARCH_COMMANDS,
        key=len,
        reverse=True,
    )
    pattern = re.compile(
        r"(?i)(?<![A-Za-z0-9_-])(?:"
        + "|".join(re.escape(name) for name in names)
        + r")(?![A-Za-z0-9_-])"
    )
    for match in pattern.finditer(command):
        tail = re.split(r"[|;&\n\r]", command[match.end() :], maxsplit=1)[0]
        if _sensitive_arguments(_segment_tokens(tail)):
            return True
        prefix = command[: match.start()]
        if (
            re.search(r"(?i)(?:-exec(?:dir)?|xargs|foreach-object)", prefix)
            and re.search(r"(?:\$_|\{\})", tail)
            and is_sensitive_resource(prefix)
        ):
            return True
    return False


def _effective_program(program: str, arguments: list[str]) -> str:
    if program in {"sudo", "doas"} and arguments:
        return arguments[0].strip('"\'').replace("\\", "/").rsplit("/", 1)[-1].lower()
    return program


def _has_unquoted_device_redirection(segment: str) -> bool:
    quote: str | None = None
    escaped = False
    index = 0
    while index < len(segment):
        character = segment[index]
        if quote is not None:
            if escaped:
                escaped = False
            elif character == "\\" and quote != "'":
                escaped = True
            elif character == quote:
                quote = None
            index += 1
            continue
        if escaped:
            escaped = False
            index += 1
            continue
        if character == "\\":
            escaped = True
            index += 1
            continue
        if character in {"'", '"'}:
            quote = character
            index += 1
            continue
        if character == ">" and not segment.startswith(">=", index):
            index += 1
            if index < len(segment) and segment[index] == ">":
                index += 1
            while index < len(segment) and segment[index].isspace():
                index += 1
            target_start = index
            while index < len(segment) and not segment[index].isspace():
                index += 1
            target = segment[target_start:index].strip('"\'')
            if target.replace("\\", "/").lower().startswith("/dev/"):
                return True
            continue
        index += 1
    return False


def _has_critical_process_target(program: str, arguments: list[str]) -> bool:
    if program not in {"kill", "pkill", "taskkill"}:
        return False
    for index, argument in enumerate(arguments):
        normalized = argument.strip('"\'').lower()
        if normalized in {"-1", "1"}:
            return True
        if normalized in {"/pid", "-p", "--pid"} and index + 1 < len(arguments):
            if arguments[index + 1].strip('"\'').lower() == "1":
                return True
    return False


def _bash_guard_facts(command: str) -> tuple[str, ...]:
    """Return high-confidence Guard facts from the classifier's segments."""

    normalized = " ".join(command.strip().split())
    segments, nested_execution = _scan_bash_command(command)
    facts: list[str] = []

    def add(fact: str) -> None:
        if fact not in facts:
            facts.append(fact)

    if nested_execution:
        add("nested-execution")

    if re.match(r"(?i)^\s*:\s*\(\s*\)\s*\{", normalized) and re.search(
        r"\|\s*:\s*&\s*\}\s*;\s*:", normalized
    ):
        add("fork-bomb")

    parsed: list[tuple[str, list[str], str | None]] = []
    for segment, connector in segments:
        program, arguments = _segment_program(segment)
        parsed.append((program, arguments, connector))
        effective = _effective_program(program, arguments)
        effective_arguments = arguments[1:] if program in {"sudo", "doas"} and arguments else arguments

        if program in {"sudo", "doas", "su", "runas"}:
            add("privilege-escalation")

        if program in {"rm", "rmdir", "rd", "del", "erase", "remove-item"} or (
            program in {"sudo", "doas"} and effective in {"rm", "rmdir", "rd", "del", "erase", "remove-item"}
        ):
            delete_arguments = effective_arguments if program in {"sudo", "doas"} else arguments
            target: str | None = None
            after_separator = False
            for argument in delete_arguments:
                normalized_argument = argument.strip('"\'')
                if after_separator:
                    target = normalized_argument
                    break
                if normalized_argument == "--":
                    after_separator = True
                    continue
                if normalized_argument.startswith("-") or (
                    len(normalized_argument) > 1
                    and re.fullmatch(r"/[A-Za-z]+", normalized_argument)
                ):
                    continue
                target = normalized_argument
                break
            if target is not None:
                target = target.replace("\\", "/")
                if (
                    target in {"/", "~", ".", "*", "./*"}
                    or target.startswith("~/")
                    or target.startswith("./*/")
                ):
                    add("root-delete")

        if program in {"remove-item", "rd", "rmdir", "del", "erase"}:
            for argument in arguments:
                candidate = argument.strip('"\'').replace("/", "\\")
                if re.fullmatch(
                    r"[A-Za-z]:\\(?:Users|Windows|Program Files)(?:\\[^\\]+)?\\*",
                    candidate,
                    flags=re.IGNORECASE,
                ):
                    add("windows-system-delete")
                    break

        if effective.startswith("mkfs") or effective in {"wipefs", "fdisk", "parted", "format"}:
            add("disk-format")
        if effective == "diskpart" and any(
            argument.strip('"\'').lower() == "clean" for argument in effective_arguments
        ):
            add("windows-disk-operation")
        if effective in {"clear-disk", "format-volume"}:
            add("windows-disk-operation")

        if effective == "dd" and any(
            re.match(r"(?i)^of\s*=\s*[\"']?/dev/", argument.strip('"\''))
            for argument in effective_arguments
        ):
            add("raw-device-write")
        if _has_unquoted_device_redirection(segment):
            add("device-redirection")

        if effective in {"chmod", "chown"}:
            recursive = any(
                argument.strip('"\'').lower() == "--recursive"
                or re.fullmatch(r"-[^-]*r[^-]*", argument.strip('"\''), flags=re.IGNORECASE)
                for argument in effective_arguments
            )
            extreme = any(
                argument.strip('"\'') == "777"
                or argument.strip('"\'').replace("\\", "/").startswith(("/", "~"))
                for argument in effective_arguments
            )
            if recursive and extreme:
                add("recursive-extreme-permissions")

        if _has_critical_process_target(effective, effective_arguments):
            add("critical-process-kill")

    for index in range(1, len(parsed)):
        previous_program, previous_arguments, _ = parsed[index - 1]
        current_program, current_arguments, connector = parsed[index]
        if connector != "|":
            continue
        previous_effective = _effective_program(previous_program, previous_arguments)
        current_effective = _effective_program(current_program, current_arguments)
        if previous_effective in {"curl", "wget"} and current_effective in {"sh", "bash", "dash"}:
            add("remote-script-pipe")

    return tuple(facts)


def _nested_command_payloads(command: str) -> tuple[str, ...]:
    """Extract executable payloads from the supported opaque wrappers."""

    payloads: list[str] = []
    for segment, _ in _scan_bash_command(command)[0]:
        program, arguments = _segment_program(segment)
        options = {
            "sh": {"-c"},
            "bash": {"-c"},
            "zsh": {"-c"},
            "cmd": {"/c"},
            "cmd.exe": {"/c"},
            "pwsh": {"-c", "-command"},
            "pwsh.exe": {"-c", "-command"},
            "powershell": {"-c", "-command"},
            "powershell.exe": {"-c", "-command"},
        }.get(program)
        if options:
            for index, argument in enumerate(arguments):
                if argument.strip('"\'').lower() in options and index + 1 < len(arguments):
                    payload = _remove_matching_outer_quotes(
                        " ".join(arguments[index + 1 :]).strip()
                    )
                    if payload:
                        payloads.append(payload)
                    break

    index = 0
    quote: str | None = None
    escaped = False
    while index < len(command):
        character = command[index]
        if escaped:
            escaped = False
            index += 1
            continue
        if character == "\\" and quote != "'":
            escaped = True
            index += 1
            continue
        if character == "'":
            quote = None if quote == "'" else ("'" if quote is None else quote)
            index += 1
            continue
        if character == '"':
            quote = None if quote == '"' else ('"' if quote is None else quote)
            index += 1
            continue
        if quote == "'":
            index += 1
            continue
        if command.startswith("$(", index) and not command.startswith("$((", index):
            depth = 1
            cursor = index + 2
            inner_quote: str | None = None
            inner_escaped = False
            while cursor < len(command) and depth:
                inner_character = command[cursor]
                if inner_quote is not None:
                    if inner_escaped:
                        inner_escaped = False
                    elif inner_character == "\\" and inner_quote != "'":
                        inner_escaped = True
                    elif inner_character == inner_quote:
                        inner_quote = None
                elif inner_character in {"'", '"'}:
                    inner_quote = inner_character
                elif command.startswith("$(", cursor):
                    depth += 1
                    cursor += 1
                elif inner_character == ")":
                    depth -= 1
                    if depth == 0:
                        payloads.append(command[index + 2 : cursor])
                        index = cursor
                        break
                cursor += 1
        elif character == "`":
            closing = command.find("`", index + 1)
            if closing != -1:
                payloads.append(command[index + 1 : closing])
                index = closing
        index += 1
    return tuple(payloads)


def _remove_matching_outer_quotes(value: str) -> str:
    """Remove one matching quote pair without consuming nested quote tails."""

    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        quote = value[0]
        return value[1:-1].replace(f"\\{quote}", quote)
    return value


def _normalized_delete_target(value: str) -> str:
    return value.strip('"\'').replace("\\", "/").rstrip("/") or "/"


def _bash_circuit_breakers(
    command: str,
    *,
    _depth: int = 0,
) -> tuple[CircuitBreaker, ...]:
    """Return only catastrophic, structurally parsed Bash execution facts."""

    breakers: list[CircuitBreaker] = []

    def add(value: CircuitBreaker) -> None:
        if value not in breakers:
            breakers.append(value)

    if _depth > 4:
        return ()
    home_candidates = {
        str(Path.home()).replace("\\", "/").rstrip("/").lower(),
        "~",
        "$home",
        "${home}",
        "%userprofile%",
        "$env:userprofile",
    }
    parsed: list[tuple[str, list[str], str | None, str]] = []
    for segment, connector in _scan_bash_command(command)[0]:
        program, arguments = _segment_program(segment)
        parsed.append((program, arguments, connector, segment))
        effective = _effective_program(program, arguments)
        effective_arguments = (
            arguments[1:] if program in {"sudo", "doas"} and arguments else arguments
        )

        if effective in {"rm", "rmdir", "rd", "remove-item"}:
            recursive = any(
                value.strip('"\'').lower() in {"-r", "-rf", "-fr", "--recursive", "/s"}
                or re.fullmatch(r"-[^-]*r[^-]*", value.strip('"\''), re.IGNORECASE)
                for value in effective_arguments
            )
            targets = [
                _normalized_delete_target(value)
                for value in effective_arguments
                if not value.strip('"\'').startswith("-")
                and value.strip('"\'').lower() not in {"/s", "/q"}
            ]
            if recursive:
                for target in targets:
                    lowered = target.lower()
                    if target == "/" or re.fullmatch(r"[A-Za-z]:", target) or re.fullmatch(
                        r"//[^/]+/[^/]+", target
                    ):
                        add(CircuitBreaker.FILESYSTEM_ROOT_DELETE)
                    if lowered in home_candidates:
                        add(CircuitBreaker.HOME_DELETE)

        if effective.startswith("mkfs") or effective in {
            "wipefs",
            "fdisk",
            "parted",
            "format",
            "clear-disk",
            "format-volume",
        }:
            add(CircuitBreaker.DISK_OR_VOLUME_DAMAGE)
        if effective == "diskpart" and any(
            value.strip('"\'').lower() in {"clean", "clean all"}
            for value in effective_arguments
        ):
            add(CircuitBreaker.DISK_OR_VOLUME_DAMAGE)
        if effective == "dd" and any(
            re.match(r"(?i)^of\s*=\s*[\"']?/dev/", value.strip('"\''))
            for value in effective_arguments
        ):
            add(CircuitBreaker.RAW_DEVICE_WRITE)
        if _has_unquoted_device_redirection(segment):
            add(CircuitBreaker.RAW_DEVICE_WRITE)

    for index, (program, arguments, connector, _) in enumerate(parsed):
        if program != "diskpart" or connector != "|" or index == 0:
            continue
        previous_program, previous_arguments, _, _ = parsed[index - 1]
        if previous_program in {"echo", "write-output", "printf"} and any(
            value.strip('"\'').lower() in {"clean", "clean all"}
            for value in previous_arguments
        ):
            add(CircuitBreaker.DISK_OR_VOLUME_DAMAGE)

    for payload in _nested_command_payloads(command):
        for breaker in _bash_circuit_breakers(payload, _depth=_depth + 1):
            add(breaker)
    return tuple(breakers)


def classify_bash_command(command: str) -> Effect:
    """Classify obvious shell effects without claiming complete parsing.

    The classifier deliberately returns UNKNOWN for constructs it cannot
    inspect reliably.  Known effects in a composite command are preserved so
    a harmless-looking prefix cannot hide a later write, destructive action,
    or external interaction.
    """

    if not isinstance(command, str) or not command.strip():
        return Effect.UNKNOWN
    segments = _split_bash_segments(command)
    effects = [_classify_bash_segment(segment) for segment, _ in segments if segment.strip()]
    if not effects:
        return Effect.UNKNOWN
    return max(effects, key=lambda effect: _EFFECT_RANK[effect])


def _classify_bash_segment(segment: str) -> Effect:
    outer_group = _outer_command_group(segment)
    if outer_group is not None:
        return classify_bash_command(outer_group)
    segment = _unwrap_command_group(segment)
    redirection_effect = _redirection_effect(segment)
    if redirection_effect is not None:
        return redirection_effect
    if any(marker in segment for marker in ("$(`", "$(", "`", "\n")):
        return Effect.UNKNOWN
    try:
        tokens = shlex.split(segment, posix=os.name != "nt")
    except ValueError:
        return Effect.UNKNOWN
    if not tokens:
        return Effect.READ

    while tokens and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", tokens[0]):
        tokens.pop(0)
    if not tokens:
        return Effect.UNKNOWN

    program = tokens[0].replace("\\", "/").rsplit("/", 1)[-1].lower()
    arguments = tokens[1:]

    if program in {"cd", "chdir", "set-location"}:
        return (
            Effect.READ
            if _static_navigation_target(program, arguments) is not None
            else Effect.UNKNOWN
        )

    if program in {"git", "git.exe"}:
        return _classify_git_command(arguments)

    for command_set, effect in (
        (_EXTERNAL_COMMANDS, Effect.EXTERNAL),
        (_DESTRUCTIVE_COMMANDS, Effect.DESTRUCTIVE),
        (_WRITE_COMMANDS, Effect.WRITE),
        (_READ_COMMANDS, Effect.READ),
    ):
        if program in command_set:
            return effect

    command_tokens = (program, *(token.lower() for token in arguments))
    for prefix, effect in _SIMPLE_COMMAND_PREFIXES:
        if command_tokens[: len(prefix)] == prefix:
            return effect

    if program in {"clear", "cls", "true", "false", "exit", "sleep"}:
        return Effect.READ
    if program in {"sudo", "su", "runas"}:
        return Effect.DESTRUCTIVE
    return Effect.UNKNOWN


def _static_navigation_target(program: str, arguments: list[str]) -> str | None:
    values = [argument.strip('"\'') for argument in arguments]
    if program in {"cd", "chdir"} and values and values[0].lower() == "/d":
        values = values[1:]
    if program == "set-location" and len(values) == 2 and values[0].lower() in {
        "-path",
        "-literalpath",
    }:
        values = values[1:]
    if len(values) != 1:
        return None
    target = values[0]
    if not target or target == "-" or target.startswith("~"):
        return None
    if any(marker in target for marker in ("$", "%", "`", "*", "?", "[", "]", "{", "}")):
        return None
    return target


def _bash_resource_scope(command: str, workdir: Path, effect: Effect) -> ResourceScope:
    if effect is not Effect.READ:
        return ResourceScope.UNKNOWN
    current = workdir
    for segment, connector_before in _split_bash_segments(command):
        program, arguments = _segment_program(segment)
        if program not in {"cd", "chdir", "set-location"}:
            continue
        if connector_before not in {None, "&&"}:
            return ResourceScope.UNKNOWN
        target = _static_navigation_target(program, arguments)
        if target is None:
            return ResourceScope.UNKNOWN
        candidate = Path(target)
        if not candidate.is_absolute():
            candidate = current / candidate
        candidate = candidate.resolve(strict=False)
        try:
            candidate.relative_to(workdir)
        except ValueError:
            return ResourceScope.OUTSIDE
        current = candidate
    return ResourceScope.INSIDE


def _classify_git_command(arguments: list[str]) -> Effect:
    """Classify Git by subcommand and safety-critical options.

    Git subcommands have materially different effects even when their first
    token is the same.  This parser intentionally handles only high-confidence
    cases and returns UNKNOWN for unsupported forms.
    """

    if not arguments:
        return Effect.UNKNOWN

    subcommand = arguments[0].lower()
    subarguments = [argument.lower() for argument in arguments[1:]]

    if subcommand in _GIT_EXTERNAL_SUBCOMMANDS:
        return Effect.EXTERNAL
    if subcommand in _GIT_READ_SUBCOMMANDS:
        if _has_git_output_option(subarguments):
            return Effect.WRITE
        return Effect.READ
    if subcommand in _GIT_WRITE_SUBCOMMANDS:
        return Effect.WRITE
    if subcommand == "branch":
        return _classify_git_branch(subarguments)
    if subcommand == "remote":
        return _classify_git_remote(subarguments)
    if subcommand == "checkout":
        return _classify_git_checkout(subarguments)
    if subcommand == "switch":
        return _classify_git_switch(subarguments)
    if subcommand == "restore":
        return _classify_git_restore(subarguments)
    if subcommand == "rm":
        return Effect.DESTRUCTIVE
    if subcommand == "clean":
        return Effect.DESTRUCTIVE
    if subcommand == "reset":
        return _classify_git_reset(subarguments)
    if subcommand == "tag":
        return _classify_git_tag(subarguments)
    return Effect.UNKNOWN


def _classify_git_branch(arguments: list[str]) -> Effect:
    if not arguments:
        return Effect.READ
    if any(argument in _GIT_BRANCH_DELETE_OPTIONS for argument in arguments):
        return Effect.DESTRUCTIVE
    if any(argument in _GIT_BRANCH_MOVE_OPTIONS for argument in arguments):
        return Effect.WRITE

    has_read_query = False
    for argument in arguments:
        if argument in _GIT_BRANCH_READ_OPTIONS or _has_option_value(
            argument, ("--format", "--sort", "--column")
        ):
            has_read_query = True
            continue
        if argument.startswith("-"):
            return Effect.UNKNOWN
        if has_read_query:
            continue
        return Effect.WRITE
    return Effect.READ if has_read_query else Effect.UNKNOWN


def _classify_git_remote(arguments: list[str]) -> Effect:
    if not arguments:
        return Effect.READ
    subcommand = arguments[0]
    if subcommand in {"-v", "--verbose"}:
        return Effect.READ if len(arguments) == 1 else Effect.UNKNOWN
    if subcommand == "get-url":
        return _classify_git_remote_get_url(arguments[1:])
    if subcommand == "show":
        return _classify_git_remote_show(arguments[1:])
    if subcommand in {"add", "set-url", "remove", "rm", "rename"}:
        return Effect.WRITE
    if subcommand in {"prune", "update"}:
        return Effect.EXTERNAL
    return Effect.UNKNOWN


def _classify_git_remote_get_url(arguments: list[str]) -> Effect:
    for argument in arguments:
        if argument == "--":
            continue
        if argument.startswith("-") and argument not in {"--all", "--push"}:
            return Effect.UNKNOWN
    return Effect.READ


def _classify_git_remote_show(arguments: list[str]) -> Effect:
    no_query = False
    after_separator = False
    for argument in arguments:
        if after_separator:
            continue
        if argument == "--":
            after_separator = True
            continue
        if argument in {"-n", "--no-query"}:
            no_query = True
            continue
        if argument.startswith("-"):
            return Effect.UNKNOWN
    return Effect.READ if no_query else Effect.EXTERNAL


def _classify_git_checkout(arguments: list[str]) -> Effect:
    if not arguments:
        return Effect.UNKNOWN
    if "--" in arguments or any(argument in {"-f", "--force", "-b"} for argument in arguments):
        return Effect.DESTRUCTIVE if "--" in arguments or any(
            argument in {"-f", "--force"} for argument in arguments
        ) else Effect.WRITE
    return Effect.WRITE


def _classify_git_switch(arguments: list[str]) -> Effect:
    if not arguments:
        return Effect.UNKNOWN
    if any(argument in {"-f", "--force", "--discard-changes"} for argument in arguments):
        return Effect.DESTRUCTIVE
    return Effect.WRITE


def _classify_git_restore(arguments: list[str]) -> Effect:
    if not arguments:
        return Effect.UNKNOWN
    staged_only = "--staged" in arguments or "-s" in arguments
    restores_worktree = "--worktree" in arguments or "-w" in arguments or not staged_only
    if restores_worktree:
        return Effect.DESTRUCTIVE
    return Effect.WRITE


def _classify_git_reset(arguments: list[str]) -> Effect:
    if any(
        argument == option or argument.startswith(option + "=")
        for argument in arguments
        for option in ("--hard", "--merge", "--keep")
    ):
        return Effect.DESTRUCTIVE
    if any(argument.startswith("-") and argument not in _GIT_RESET_WRITE_OPTIONS for argument in arguments):
        return Effect.UNKNOWN
    return Effect.WRITE


def _classify_git_tag(arguments: list[str]) -> Effect:
    if not arguments:
        return Effect.READ
    if any(argument in {"-d", "--delete"} for argument in arguments):
        return Effect.DESTRUCTIVE

    has_read_query = False
    for argument in arguments:
        if argument in _GIT_TAG_READ_OPTIONS or _has_option_value(
            argument, ("--format", "--sort", "--column")
        ):
            has_read_query = True
            continue
        if argument in _GIT_TAG_CREATE_OPTIONS or _has_option_value(
            argument, ("--cleanup", "--local-user", "--message")
        ):
            return Effect.WRITE
        if argument.startswith("-"):
            return Effect.UNKNOWN
        if has_read_query:
            continue
        return Effect.WRITE
    return Effect.READ if has_read_query else Effect.WRITE


def _has_git_output_option(arguments: list[str]) -> bool:
    return any(argument in {"-o", "--output"} or argument.startswith("--output=") for argument in arguments)


def _has_option_value(argument: str, options: tuple[str, ...]) -> bool:
    return any(argument == option or argument.startswith(option + "=") for option in options)


def _nested_content_read(command: str) -> bool:
    nested_execution = _scan_bash_command(command)[1] or (
        _BASH_OPAQUE_NESTED_EXECUTION.search(command) is not None
    )
    if not nested_execution:
        return False
    names = sorted(_BASH_CONTENT_READ_COMMANDS | _BASH_CONTENT_SEARCH_COMMANDS, key=len, reverse=True)
    pattern = r"(?i)(?<![A-Za-z0-9_-])(?:" + "|".join(re.escape(name) for name in names) + r")(?![A-Za-z0-9_-])"
    return re.search(pattern, command) is not None


def _bash_operation_kind(command: str) -> str:
    """Classify trusted Bash facts for sensitive-resource Guard matching."""

    segments, nested_execution = _scan_bash_command(command)
    nested_execution = nested_execution or (
        _BASH_OPAQUE_NESTED_EXECUTION.search(command) is not None
    )
    content_read = False
    content_search = False
    writes = False
    unknown = False
    metadata = False
    for segment, _connector in segments:
        program, _arguments = _segment_program(segment)
        if program in _BASH_CONTENT_SEARCH_COMMANDS:
            content_search = True
        elif program in _BASH_CONTENT_READ_COMMANDS:
            content_read = True
        elif program in _BASH_METADATA_COMMANDS:
            metadata = True

        effect = _classify_bash_segment(segment)
        if effect in {Effect.WRITE, Effect.DESTRUCTIVE}:
            writes = True
        elif effect is Effect.UNKNOWN:
            unknown = True

    if nested_execution:
        if _nested_content_read(command):
            content_read = True
        else:
            unknown = True

    if content_read or content_search:
        if writes:
            return "mixed"
        if content_search and not content_read:
            return "content-search"
        return "content-read"
    if writes:
        return "write"
    if unknown:
        return "unknown"
    if metadata:
        return "metadata"
    return "other"


def _bash_sensitive_operation_target(command: str) -> bool:
    """Return a sensitive-target fact associated with an executable segment."""

    segments, nested_execution = _scan_bash_command(command)
    for segment, _connector in segments:
        program, arguments = _segment_program(segment)
        if _segment_sensitive_target(
            segment,
            program,
            arguments,
            _classify_bash_segment(segment),
        ):
            return True

    if nested_execution or _BASH_OPAQUE_NESTED_EXECUTION.search(command) is not None:
        return _nested_sensitive_content_target(command)
    return False


def _bash_action_summary(command: str) -> str:
    operation_kind = _bash_operation_kind(command)
    target_fact = (
        f" [{BASH_SENSITIVE_TARGET_MARKER}]"
        if _bash_sensitive_operation_target(command)
        else ""
    )
    return (
        f"Bash [{BASH_ACTION_FACT_MARKER}:{operation_kind}]"
        f"{target_fact} {safe_bash_command_summary(command)}"
    )


class BashTool:
    """Run a command with the current OS shell and current user privileges.

    This is unsandboxed process execution.  It does not provide an operating
    system sandbox, command allow-list, or privilege elevation.
    """

    _definition = ToolDefinition(
        "Bash",
        "Execute a command with the current operating-system shell and current user privileges; this is unsandboxed process execution.",
        {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "timeout_seconds": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 600,
                    "default": 120,
                },
            },
            "required": ["command"],
            "additionalProperties": False,
        },
    )

    def __init__(self, workdir: str | os.PathLike[str] | Path) -> None:
        self._workdir = Path(workdir).expanduser().resolve(strict=False)

    @property
    def definition(self) -> ToolDefinition:
        return self._definition

    @property
    def planning_access(self) -> ToolPlanningAccess:
        return ToolPlanningAccess.READ_ONLY

    def preflight(self, arguments: JsonPayload) -> ToolPreparation:
        command = _text(arguments, "command")
        effect = classify_bash_command(command)
        scope = _bash_resource_scope(command, self._workdir, effect)
        summary = _bash_action_summary(command)
        facts = _bash_guard_facts(command)
        if facts:
            summary = f"{summary} [{BASH_GUARD_FACT_MARKER}:{','.join(facts)}]"
        return ToolPreparation(
            action=PermissionAction(
                tool="Bash",
                action="execute",
                effect=effect,
                resource=summary,
                scope=scope,
                circuit_breakers=_bash_circuit_breakers(command),
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
            return _error(_CANCELLED)
        try:
            command = _text(arguments, "command")
            timeout_seconds = _timeout(arguments.get("timeout_seconds", 120))
        except (TypeError, ValueError) as exc:
            return _error(f"Error: invalid arguments for Bash: {exc}")

        started: _StartedProcess | None = None
        try:
            started = await _start_process(command, self._workdir)
        except (OSError, RuntimeError, ValueError) as exc:
            return _error(f"Error: failed to start command: {exc}")
        process = started.process

        communication = asyncio.create_task(process.communicate())
        cancellation_wait = asyncio.create_task(cancellation.wait())
        try:
            done, _ = await asyncio.wait(
                (communication, cancellation_wait),
                timeout=float(timeout_seconds),
                return_when=asyncio.FIRST_COMPLETED,
            )

            if communication in done:
                try:
                    stdout, stderr = communication.result()
                except (OSError, asyncio.CancelledError) as exc:
                    return _error(f"Error: failed to collect command output: {exc}")
                return _completed_result(process.returncode, stdout, stderr)

            timed_out = not cancellation_wait in done
            stopped = await _terminate_process_tree(started)
            reaped = await _await_communication(communication)
            if not stopped or not reaped:
                return _error(
                    "Error: command ended without confirmed process and pipe reaping"
                )
            if timed_out:
                return _error(
                    f"Error: command timed out after {timeout_seconds}s"
                )
            return _error(_CANCELLED)
        except asyncio.CancelledError as cancellation_error:
            # A task cancellation is distinct from the Core cancellation token,
            # but the child must still be terminated before the task exits.
            stopped = await _terminate_process_tree(started)
            reaped = await _await_communication(communication)
            if not stopped or not reaped:
                raise RuntimeError(
                    "Error: cancelled command ended without confirmed process "
                    "and pipe reaping"
                ) from cancellation_error
            raise
        finally:
            if not cancellation_wait.done():
                cancellation_wait.cancel()
            await asyncio.gather(cancellation_wait, return_exceptions=True)
            started.control.close()


async def _start_process(command: str, workdir: Path) -> _StartedProcess:
    kwargs: dict[str, Any] = {}
    control: _ProcessTreeControl | None = None
    if os.name == "nt":
        # Keep the shell suspended until it is assigned to a Job Object.  This
        # closes the race where a shell can create a child and exit before a
        # parent-PID based tree walk or taskkill can see it.
        control = _WindowsJobControl()
        kwargs["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP
            | 0x00000004  # CREATE_SUSPENDED
        )
    else:
        kwargs["start_new_session"] = True

    process: asyncio.subprocess.Process | None = None
    try:
        process = await asyncio.create_subprocess_shell(
            command,
            cwd=str(workdir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            **kwargs,
        )
        if os.name == "nt":
            assert isinstance(control, _WindowsJobControl)
            control.attach_and_resume(process)
        else:
            control = _PosixProcessGroupControl(process.pid)
        assert control is not None
        return _StartedProcess(process, control)
    except BaseException:
        if process is not None:
            if control is None:
                control = _PosixProcessGroupControl(process.pid)
            cleanup = asyncio.create_task(control.terminate(process))
            try:
                await asyncio.shield(cleanup)
            except BaseException:
                try:
                    await asyncio.shield(cleanup)
                except BaseException:
                    pass
            try:
                if process.returncode is None:
                    process.kill()
                await asyncio.shield(process.wait())
            except BaseException:
                pass
        if control is not None:
            control.close()
        raise


async def _terminate_process_tree(started: _StartedProcess) -> bool:
    """Terminate and confirm the complete platform process lifetime."""

    try:
        return await started.control.terminate(started.process)
    except (OSError, ProcessLookupError, RuntimeError, asyncio.TimeoutError):
        return False


def _signal_posix_process_group(process_group_id: int, signum: int) -> bool | None:
    try:
        os.killpg(process_group_id, signum)
    except ProcessLookupError:
        return False
    except OSError:
        return None
    return True


def _posix_process_group_exists(process_group_id: int) -> bool | None:
    try:
        os.killpg(process_group_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return None
    return True


async def _await_posix_process_group_exit(
    process_group_id: int,
    timeout: float,
) -> bool:
    deadline = time.monotonic() + timeout
    while True:
        exists = _posix_process_group_exists(process_group_id)
        if exists is False:
            return True
        if exists is None or time.monotonic() >= deadline:
            return False
        await asyncio.sleep(0.01)


async def _await_process(
    process: asyncio.subprocess.Process,
    timeout: float,
) -> bool:
    try:
        await asyncio.wait_for(asyncio.shield(process.wait()), timeout)
    except (OSError, ProcessLookupError, asyncio.TimeoutError):
        return False
    return True


async def _await_communication(task: asyncio.Task[tuple[bytes, bytes]]) -> bool:
    try:
        await asyncio.wait_for(asyncio.shield(task), _REAP_TIMEOUT_SECONDS)
    except (Exception, asyncio.CancelledError):
        return False
    return True


def _completed_result(
    returncode: int | None,
    stdout_bytes: bytes,
    stderr_bytes: bytes,
) -> ToolExecutionResult:
    stdout = _decode_process_output(stdout_bytes).rstrip()
    stderr = _decode_process_output(stderr_bytes).rstrip()
    sections: list[str] = []
    if stdout:
        sections.append(f"STDOUT:\n{stdout}")
    if stderr:
        sections.append(f"STDERR:\n{stderr}")
    if not sections:
        sections.append("(no output)")
    if returncode is None:
        return _error("Error: process exit status was not available")
    if returncode not in (None, 0):
        sections.append(f"Exit code: {returncode}")
    return ToolExecutionResult(
        "\n\n".join(sections),
        is_error=returncode not in (None, 0),
    )


def _decode_process_output(data: bytes) -> str:
    """Decode captured process bytes using the current shell's known encodings."""

    encodings = ["utf-8"]
    if os.name == "nt":
        encodings.extend(_windows_output_encodings())

    seen: set[str] = set()
    for encoding in encodings:
        normalized = encoding.casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        try:
            return data.decode(encoding, errors="strict")
        except (LookupError, UnicodeDecodeError):
            continue

    return data.decode("utf-8", errors="replace")


def _windows_output_encodings() -> tuple[str, ...]:
    """Return finite ANSI/OEM encodings reported by this Windows shell."""

    encodings: list[str] = []
    try:
        kernel32 = ctypes.windll.kernel32
        for function_name in ("GetConsoleOutputCP", "GetOEMCP", "GetACP"):
            function = getattr(kernel32, function_name, None)
            if function is None:
                continue
            function.restype = wintypes.UINT
            code_page = int(function())
            if code_page > 0:
                encodings.append(f"cp{code_page}")
    except (AttributeError, OSError, TypeError, ValueError):
        pass

    try:
        system_encoding = locale.getencoding()
    except (AttributeError, LookupError):
        system_encoding = ""
    if system_encoding:
        encodings.append(system_encoding)
    return tuple(encodings)


def _text(arguments: Mapping[str, object], name: str) -> str:
    value = arguments[name]
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    return value


def _timeout(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("timeout_seconds must be an integer")
    if not 1 <= value <= 600:
        raise ValueError("timeout_seconds must be between 1 and 600")
    return value


def _error(message: str) -> ToolExecutionResult:
    return ToolExecutionResult(message, is_error=True)


__all__ = ["BashTool", "classify_bash_command", "safe_bash_command_summary"]
