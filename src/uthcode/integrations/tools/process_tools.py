"""Current-user, current-OS-shell process execution for the Bash tool."""

from __future__ import annotations

import asyncio
import ctypes
import os
import signal
import subprocess
import time
from collections.abc import Mapping
from ctypes import wintypes
from pathlib import Path
from typing import Any

from uthcode.core.provider import CancellationToken, JsonPayload, ToolDefinition
from uthcode.core.tool import ToolExecutionResult


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
    stdout = stdout_bytes.decode("utf-8", errors="replace").rstrip()
    stderr = stderr_bytes.decode("utf-8", errors="replace").rstrip()
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


__all__ = ["BashTool"]
