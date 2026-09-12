"""Application-owned process sessions used by Bash and Process tools.

The manager deliberately owns OS handles and bounded output only.  Core sees
stable process facts through ``ToolExecutionResult``; it never receives a
``Popen``/PTY object.  A process belongs to exactly one durable Session key,
so a stale or cross-Session process id cannot be used as a control capability.
"""

from __future__ import annotations

import asyncio
import os
import signal
import shlex
import subprocess
import sys
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from collections.abc import Callable, Mapping
from typing import Any

@dataclass(frozen=True, slots=True)
class ProcessOutput:
    sequence: int
    stream: str
    text: str


@dataclass(frozen=True, slots=True)
class ProcessRead:
    process_id: str
    entries: tuple[ProcessOutput, ...]
    next_cursor: int
    earliest_cursor: int
    cursor_expired: bool
    state: str
    exit_code: int | None
    expired: bool = False
    expiration_reason: str | None = None


@dataclass(slots=True)
class _ManagedProcess:
    process_id: str
    session_id: str
    command: str
    cwd: Path
    process: asyncio.subprocess.Process | None
    control: Any
    pty: Any | None = None
    pty_task: asyncio.Task[None] | None = None
    stdout_task: asyncio.Task[None] | None = None
    stderr_task: asyncio.Task[None] | None = None
    watcher_task: asyncio.Task[None] | None = None
    timeout_task: asyncio.Task[None] | None = None
    ring: deque[ProcessOutput] = field(default_factory=deque)
    ring_bytes: int = 0
    next_sequence: int = 0
    state: str = "running"
    exit_code: int | None = None
    writer_closed: bool = False
    turn_id: str | None = None
    timeout_seconds: float | None = None
    timed_out: bool = False
    pty_write_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    output_signal: asyncio.Event = field(default_factory=asyncio.Event)
    last_stream: str = "terminal"

    def append(self, stream: str, text: str, *, max_bytes: int) -> None:
        if not text:
            return
        # Keep chunks modest so one noisy child cannot create a huge Python
        # string before the byte cap is applied.
        for start in range(0, len(text), 4096):
            chunk = text[start : start + 4096]
            item = ProcessOutput(self.next_sequence, stream, chunk)
            self.next_sequence += len(chunk.encode("utf-8"))
            self.ring.append(item)
            self.ring_bytes += len(chunk.encode("utf-8"))
            while self.ring and self.ring_bytes > max_bytes:
                removed = self.ring.popleft()
                self.ring_bytes -= len(removed.text.encode("utf-8"))


class ProcessSessionError(RuntimeError):
    def __init__(self, message: str, *, kind: str = "process_failed", unknown: bool = False) -> None:
        self.kind = kind
        self.unknown = unknown
        super().__init__(message)


class ProcessSessionManager:
    """Own bounded process sessions for one Application composition."""

    def __init__(
        self,
        *,
        max_output_bytes: int = 2 * 1024 * 1024,
        max_processes_per_session: int = 64,
        max_finished_per_session: int = 32,
        max_expired_per_session: int = 128,
    ) -> None:
        if isinstance(max_output_bytes, bool) or not isinstance(max_output_bytes, int) or max_output_bytes <= 0:
            raise ValueError("max_output_bytes must be positive")
        for name, value in (
            ("max_processes_per_session", max_processes_per_session),
            ("max_finished_per_session", max_finished_per_session),
            ("max_expired_per_session", max_expired_per_session),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be positive")
        self.max_output_bytes = max_output_bytes
        self.max_processes_per_session = max_processes_per_session
        self.max_finished_per_session = max_finished_per_session
        self.max_expired_per_session = max_expired_per_session
        self._processes: dict[str, _ManagedProcess] = {}
        self._expired: dict[str, dict[str, dict[str, object]]] = {}
        self._closed_sessions: set[str] = set()
        self._lock = asyncio.Lock()
        self._observers: list[Callable[[Mapping[str, object]], None]] = []
        self._output_projector: Callable[[Mapping[str, object]], Mapping[str, object]] | None = None
        self._command_projector: Callable[[str], str] | None = None

    def set_output_projector(
        self,
        projector: Callable[[Mapping[str, object]], Mapping[str, object]] | None,
    ) -> None:
        """Install the Application's one redacted process stream projection."""

        if projector is not None and not callable(projector):
            raise TypeError("projector must be callable or None")
        self._output_projector = projector

    def set_command_projector(self, projector: Callable[[str], str] | None) -> None:
        """Install the Application's command projection for Process.list."""

        if projector is not None and not callable(projector):
            raise TypeError("projector must be callable or None")
        self._command_projector = projector

    def subscribe(self, observer: Callable[[Mapping[str, object]], None]) -> Callable[[], None]:
        """Subscribe to bounded output and state observations."""

        if not callable(observer):
            raise TypeError("observer must be callable")
        if observer not in self._observers:
            self._observers.append(observer)

        def unsubscribe() -> None:
            try:
                self._observers.remove(observer)
            except ValueError:
                pass

        return unsubscribe

    def _emit(
        self,
        managed: _ManagedProcess,
        *,
        event: str,
        sequence: int | None = None,
        stream: str | None = None,
        text: str = "",
        projected: bool = False,
    ) -> None:
        payload: dict[str, object] = {
            "type": event,
            "session_id": managed.session_id,
            "process_id": managed.process_id,
            "sequence": managed.next_sequence if sequence is None else sequence,
            "next_cursor": managed.next_sequence,
            "state": managed.state,
            "exit_code": managed.exit_code,
            "timed_out": managed.timed_out,
            "pty": managed.pty is not None,
        }
        if managed.turn_id is not None:
            payload["turn_id"] = managed.turn_id
        if stream is not None:
            payload["stream"] = stream
        if text:
            payload["text"] = text
        if projected:
            # This is an internal composition marker.  Desktop's allowlist
            # never forwards it; Application uses it to avoid a second
            # stateful redaction pass after the ring was projected.
            payload["_projected"] = True
        for observer in tuple(self._observers):
            try:
                observer(payload)
            except Exception:
                continue

    def _project_output(
        self,
        managed: _ManagedProcess,
        *,
        event: str,
        stream: str,
        text: str,
    ) -> str:
        projector = self._output_projector
        if projector is None:
            return text
        observation: dict[str, object] = {
            "type": event,
            "session_id": managed.session_id,
            "process_id": managed.process_id,
            "sequence": managed.next_sequence,
            "next_cursor": managed.next_sequence,
            "state": managed.state,
            "exit_code": managed.exit_code,
            "timed_out": managed.timed_out,
            "pty": managed.pty is not None,
            "stream": stream,
            "text": text,
        }
        if managed.turn_id is not None:
            observation["turn_id"] = managed.turn_id
        try:
            projected = projector(observation)
        except Exception:
            # A projection failure must fail closed.  The raw chunk is never
            # allowed to enter either the ring or the observer stream.
            return ""
        value = projected.get("text") if isinstance(projected, Mapping) else ""
        return value if isinstance(value, str) else ""

    def _append_output(
        self,
        managed: _ManagedProcess,
        stream: str,
        text: str,
        *,
        already_projected: bool = False,
    ) -> None:
        if not text:
            return
        safe_text = text if already_projected else self._project_output(
            managed,
            event="process_output",
            stream=stream,
            text=text,
        )
        if not safe_text:
            return
        start = managed.next_sequence
        managed.last_stream = stream
        managed.append(stream, safe_text, max_bytes=self.max_output_bytes)
        managed.output_signal.set()
        self._emit(
            managed,
            event="process_output",
            sequence=start,
            stream=stream,
            text=safe_text,
            projected=self._output_projector is not None,
        )

    def _flush_output_projection(self, managed: _ManagedProcess) -> None:
        if self._output_projector is None:
            return
        safe_text = self._project_output(
            managed,
            event="process_state",
            stream=managed.last_stream or "status",
            text="",
        )
        self._append_output(
            managed,
            managed.last_stream or "status",
            safe_text,
            already_projected=True,
        )

    def _finish_state(self, managed: _ManagedProcess) -> None:
        self._flush_output_projection(managed)
        self._emit(
            managed,
            event="process_state",
            projected=self._output_projector is not None,
        )
        self._evict_finished(managed.session_id, protected={managed.process_id})

    async def start(
        self,
        *,
        session_id: str,
        command: str,
        cwd: Path,
        pty: bool = False,
        rows: int = 24,
        cols: int = 80,
        turn_id: str | None = None,
        timeout_seconds: float | None = None,
    ) -> _ManagedProcess:
        if not isinstance(session_id, str) or not session_id:
            session_id = "default"
        if timeout_seconds is not None and timeout_seconds <= 0:
            raise ProcessSessionError("Error: process timeout is invalid", kind="invalid_input")
        if session_id in self._closed_sessions:
            raise ProcessSessionError("Error: Session process runtime is closed", kind="unavailable")
        self._evict_finished(session_id)
        active_count = sum(
            1 for item in self._processes.values() if item.session_id == session_id
        )
        if active_count >= self.max_processes_per_session:
            raise ProcessSessionError(
                "Error: Session process quota is full",
                kind="resource_limit",
            )
        if pty:
            managed = await self._start_pty(session_id, command, cwd, rows, cols, turn_id)
        else:
            managed = await self._start_pipe(session_id, command, cwd, turn_id)
        async with self._lock:
            self._processes[managed.process_id] = managed
        if timeout_seconds is not None:
            managed.timeout_seconds = float(timeout_seconds)
            managed.timeout_task = asyncio.create_task(self._enforce_timeout(managed, float(timeout_seconds)))
        return managed

    async def _enforce_timeout(self, managed: _ManagedProcess, timeout_seconds: float) -> None:
        try:
            await asyncio.sleep(timeout_seconds)
            if managed.state != "running":
                return
            managed.timed_out = True
            await self._terminate_managed(managed)
        except asyncio.CancelledError:
            return

    async def _start_pipe(
        self,
        session_id: str,
        command: str,
        cwd: Path,
        turn_id: str | None,
    ) -> _ManagedProcess:
        # Imported lazily to reuse the existing Job Object/process-group
        # implementation without creating a second Bash launch path.
        from .process_tools import _start_process

        started = await _start_process(command, cwd)
        managed = _ManagedProcess(
            process_id=uuid.uuid4().hex,
            session_id=session_id,
            command=command,
            cwd=cwd,
            process=started.process,
            control=started.control,
            turn_id=turn_id,
        )
        process = started.process
        if process.stdout is None or process.stderr is None:
            await self._terminate_managed(managed, unknown=True)
            raise ProcessSessionError("Error: process pipes are unavailable", unknown=True)
        managed.stdout_task = asyncio.create_task(self._pump_reader(managed, process.stdout, "stdout"))
        managed.stderr_task = asyncio.create_task(self._pump_reader(managed, process.stderr, "stderr"))
        managed.watcher_task = asyncio.create_task(self._watch_pipe(managed))
        return managed

    async def _start_pty(
        self,
        session_id: str,
        command: str,
        cwd: Path,
        rows: int,
        cols: int,
        turn_id: str | None,
    ) -> _ManagedProcess:
        if rows <= 0 or cols <= 0 or rows > 4096 or cols > 4096:
            raise ProcessSessionError("Error: PTY size is invalid", kind="invalid_input")
        if os.name == "nt":
            try:
                from winpty import PtyProcess
            except ImportError as exc:
                raise ProcessSessionError("Error: Windows PTY dependency is unavailable", kind="unavailable") from exc
        else:
            try:
                from ptyprocess import PtyProcess
            except ImportError as exc:
                raise ProcessSessionError("Error: POSIX PTY dependency is unavailable", kind="unavailable") from exc
        try:
            if os.name == "nt":
                try:
                    argv = ["cmd.exe", "/d", "/c", *_windows_pty_tokens(command)]
                except ValueError:
                    argv = ["cmd.exe", "/d", "/c", command]
            else:
                argv = ["/bin/sh", "-lc", command]
            pty = PtyProcess.spawn(argv, cwd=str(cwd), dimensions=(rows, cols))
        except TypeError:
            # Older pywinpty releases use ``dimensions`` only after spawn.
            pty = PtyProcess.spawn(argv, cwd=str(cwd))
            try:
                pty.set_size(rows, cols)
            except Exception:
                pass
        except Exception as exc:
            raise ProcessSessionError("Error: PTY process could not be started", kind="process_failed") from exc
        managed = _ManagedProcess(
            process_id=uuid.uuid4().hex,
            session_id=session_id,
            command=command,
            cwd=cwd,
            process=None,
            control=_PtyControl(pty),
            pty=pty,
            turn_id=turn_id,
        )
        managed.pty_task = asyncio.create_task(self._pump_pty(managed))
        managed.watcher_task = asyncio.create_task(self._watch_pty(managed))
        return managed

    async def _pump_reader(self, managed: _ManagedProcess, reader: asyncio.StreamReader, stream: str) -> None:
        try:
            while True:
                data = await reader.read(8192)
                if not data:
                    return
                text = _decode(data)
                self._append_output(managed, stream, text)
        except (asyncio.CancelledError, ConnectionError, OSError):
            return

    async def _pump_pty(self, managed: _ManagedProcess) -> None:
        pty = managed.pty
        if pty is None:
            return
        try:
            while True:
                try:
                    data = await asyncio.to_thread(pty.read, 4096)
                except EOFError:
                    return
                except (OSError, ValueError):
                    return
                if not data:
                    return
                if isinstance(data, bytes):
                    text = _decode(data)
                else:
                    text = str(data)
                self._append_output(managed, "terminal", text)
        except asyncio.CancelledError:
            return

    async def _watch_pipe(self, managed: _ManagedProcess) -> None:
        process = managed.process
        if process is None:
            return
        try:
            managed.exit_code = await process.wait()
            tasks = [task for task in (managed.stdout_task, managed.stderr_task) if task is not None]
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            managed.state = "exited"
            self._cancel_timeout_task(managed)
            self._finish_state(managed)
        except asyncio.CancelledError:
            return

    async def _watch_pty(self, managed: _ManagedProcess) -> None:
        pty = managed.pty
        if pty is None:
            return
        try:
            while True:
                alive = await asyncio.to_thread(pty.isalive)
                if not alive:
                    if managed.pty_task is not None:
                        try:
                            await asyncio.wait_for(asyncio.shield(managed.pty_task), 5.0)
                        except Exception:
                            pass
                    status = getattr(pty, "exitstatus", None)
                    managed.exit_code = status if isinstance(status, int) else None
                    managed.state = "exited"
                    self._cancel_timeout_task(managed)
                    self._finish_state(managed)
                    return
                await asyncio.sleep(0.02)
        except asyncio.CancelledError:
            return
        except Exception:
            managed.state = "unknown"
            self._finish_state(managed)

    async def wait_for_output(self, managed: _ManagedProcess, wait_seconds: float) -> None:
        if wait_seconds <= 0 or managed.state != "running":
            return
        tasks = [task for task in (managed.watcher_task,) if task is not None]
        # The watcher exits only once the process exits.  A short polling
        # loop also notices first output without imposing a process lifetime.
        deadline = asyncio.get_running_loop().time() + wait_seconds
        initial = managed.next_sequence
        while managed.state == "running" and asyncio.get_running_loop().time() < deadline:
            if managed.next_sequence != initial:
                return
            await asyncio.sleep(0.01)

    def get(self, process_id: str, session_id: str) -> _ManagedProcess:
        managed = self._processes.get(process_id)
        if managed is None:
            raise ProcessSessionError("Error: process is no longer available", kind="not_found")
        if managed.session_id != session_id:
            raise ProcessSessionError("Error: process does not belong to this Session", kind="permission_denied")
        return managed

    def list(self, session_id: str) -> tuple[dict[str, object], ...]:
        return tuple(
            self._describe_with_projection(item)
            for item in self._processes.values()
            if item.session_id == session_id
        )

    def _describe_with_projection(self, managed: _ManagedProcess) -> dict[str, object]:
        result = self.describe(managed)
        projector = self._command_projector
        command = result.get("command")
        if projector is not None and isinstance(command, str):
            try:
                projected = projector(command)
            except Exception:
                projected = "<command unavailable>"
            result["command"] = projected if isinstance(projected, str) else "<command unavailable>"
        return result

    @staticmethod
    def describe(managed: _ManagedProcess) -> dict[str, object]:
        return {
            "process_id": managed.process_id,
            "state": managed.state,
            "exit_code": managed.exit_code,
            "pty": managed.pty is not None,
            "session_id": managed.session_id,
            "command": managed.command[:512],
            "next_cursor": managed.next_sequence,
        }

    def read(self, process_id: str, session_id: str, cursor: int = 0) -> ProcessRead:
        if isinstance(cursor, bool) or not isinstance(cursor, int) or cursor < 0:
            raise ProcessSessionError("Error: cursor must be a non-negative integer", kind="invalid_input")
        managed = self._processes.get(process_id)
        if managed is None:
            expired = self._expired.get(session_id, {}).get(process_id)
            if expired is not None:
                earliest = int(expired.get("earliest_cursor", 0))
                next_cursor = int(expired.get("next_cursor", earliest))
                return ProcessRead(
                    process_id,
                    (),
                    next_cursor,
                    earliest,
                    True,
                    "expired",
                    expired.get("exit_code") if isinstance(expired.get("exit_code"), int) else None,
                    True,
                    str(expired.get("reason", "session_terminal_quota")),
                )
            for owner, records in self._expired.items():
                if owner != session_id and process_id in records:
                    raise ProcessSessionError("Error: process does not belong to this Session", kind="permission_denied")
            raise ProcessSessionError("Error: process is no longer available", kind="not_found")
        if managed.session_id != session_id:
            raise ProcessSessionError("Error: process does not belong to this Session", kind="permission_denied")
        earliest = managed.ring[0].sequence if managed.ring else managed.next_sequence
        expired = cursor < earliest
        start = earliest if expired else cursor
        entries = tuple(item for item in managed.ring if item.sequence >= start)
        return ProcessRead(
            process_id,
            entries,
            managed.next_sequence,
            earliest,
            expired,
            managed.state,
            managed.exit_code,
        )

    async def write(
        self,
        process_id: str,
        session_id: str,
        data: str,
        *,
        eof: bool = False,
    ) -> _ManagedProcess:
        managed = self.get(process_id, session_id)
        if managed.state != "running":
            raise ProcessSessionError("Error: process is not running", kind="conflict")
        if not isinstance(data, str):
            raise ProcessSessionError("Error: process input must be text", kind="invalid_input")
        try:
            if managed.pty is not None:
                async with managed.pty_write_lock:
                    before = managed.next_sequence
                    if data:
                        await asyncio.to_thread(managed.pty.write, data)
                        await self._wait_for_pty_flush(managed, before, 0.75)
                    if eof:
                        await self._close_pty_input(managed)
            else:
                writer = managed.process.stdin if managed.process is not None else None
                if writer is None:
                    raise ProcessSessionError("Error: process stdin is unavailable", kind="unsupported")
                if data:
                    writer.write(data.encode("utf-8"))
                    await writer.drain()
                if eof:
                    writer.close()
                    managed.writer_closed = True
        except ProcessSessionError:
            raise
        except (BrokenPipeError, ConnectionError, OSError) as exc:
            raise ProcessSessionError("Error: process stdin is unavailable", kind="process_failed") from exc
        return managed

    async def _wait_for_pty_flush(
        self,
        managed: _ManagedProcess,
        before: int,
        wait_seconds: float,
    ) -> None:
        """Let the native PTY read pump observe input before EOF is sent."""

        deadline = asyncio.get_running_loop().time() + max(0.0, wait_seconds)
        while managed.state == "running" and managed.next_sequence == before:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                return
            managed.output_signal.clear()
            try:
                await asyncio.wait_for(managed.output_signal.wait(), min(remaining, 0.1))
            except asyncio.TimeoutError:
                continue

    async def _close_pty_input(self, managed: _ManagedProcess) -> None:
        pty = managed.pty
        if pty is None:
            return
        try:
            if os.name == "nt":
                # Ctrl-Z followed by Enter is the closest portable EOF for a
                # Windows console.  A caller can still stop a process if the
                # command ignores it.
                await asyncio.to_thread(pty.write, "\x1a\r\n")
            else:
                await asyncio.to_thread(pty.write, "\x04")
            managed.writer_closed = True
        except (OSError, EOFError) as exc:
            raise ProcessSessionError("Error: PTY EOF could not be delivered", kind="process_failed") from exc

    async def resize(self, process_id: str, session_id: str, rows: int, cols: int) -> _ManagedProcess:
        managed = self.get(process_id, session_id)
        if managed.pty is None:
            raise ProcessSessionError("Error: resize is supported only for PTY processes", kind="unsupported")
        if isinstance(rows, bool) or not isinstance(rows, int) or isinstance(cols, bool) or not isinstance(cols, int) or not (1 <= rows <= 4096 and 1 <= cols <= 4096):
            raise ProcessSessionError("Error: PTY size is invalid", kind="invalid_input")
        try:
            resize = getattr(managed.pty, "set_size", None)
            if not callable(resize):
                resize = getattr(managed.pty, "setwinsize", None)
            if not callable(resize):
                raise ProcessSessionError("Error: PTY resize is unavailable", kind="unsupported")
            await asyncio.to_thread(resize, rows, cols)
        except ProcessSessionError:
            raise
        except Exception as exc:
            raise ProcessSessionError("Error: PTY resize failed", kind="process_failed") from exc
        return managed

    async def stop(self, process_id: str, session_id: str) -> bool:
        managed = self.get(process_id, session_id)
        confirmed = await self._terminate_managed(managed)
        if confirmed:
            managed.state = "exited"
        else:
            managed.state = "unknown"
        return confirmed

    async def _terminate_managed(self, managed: _ManagedProcess, *, unknown: bool = False) -> bool:
        if managed.state != "running":
            return managed.state == "exited"
        try:
            if managed.pty is not None:
                terminate = getattr(managed.pty, "terminate", None)
                if callable(terminate):
                    await asyncio.to_thread(terminate)
                if managed.watcher_task is not None:
                    try:
                        await asyncio.wait_for(asyncio.shield(managed.watcher_task), 5.0)
                    except Exception:
                        pass
                managed.state = "exited" if not unknown else "unknown"
                self._finish_state(managed)
                self._cancel_timeout_task(managed)
                return managed.state == "exited"
            if managed.process is None:
                managed.state = "unknown"
                self._finish_state(managed)
                return False
            confirmed = await managed.control.terminate(managed.process)
            if managed.stdout_task or managed.stderr_task:
                await asyncio.gather(*(task for task in (managed.stdout_task, managed.stderr_task) if task is not None), return_exceptions=True)
            managed.state = "exited" if confirmed and not unknown else "unknown"
            managed.exit_code = managed.process.returncode
            self._finish_state(managed)
            self._cancel_timeout_task(managed)
            return managed.state == "exited"
        except Exception:
            managed.state = "unknown"
            self._finish_state(managed)
            self._cancel_timeout_task(managed)
            return False

    @staticmethod
    def _cancel_timeout_task(managed: _ManagedProcess) -> None:
        task = managed.timeout_task
        current = asyncio.current_task()
        if task is not None and task is not current and not task.done():
            task.cancel()

    async def shutdown_session(self, session_id: str) -> None:
        self._closed_sessions.add(session_id)
        for managed in tuple(self._processes.values()):
            if managed.session_id == session_id and managed.state == "running":
                await self._terminate_managed(managed)
        self._close_finished(session_id)

    async def shutdown_turn(self, session_id: str, turn_id: str) -> None:
        """Stop only processes started by one cancelled/failed Turn."""

        for managed in tuple(self._processes.values()):
            if (
                managed.session_id == session_id
                and managed.turn_id == turn_id
                and managed.state == "running"
            ):
                await self._terminate_managed(managed)

    async def shutdown(self) -> None:
        for session_id in {item.session_id for item in self._processes.values()}:
            await self.shutdown_session(session_id)
        self._closed_sessions.update(item.session_id for item in self._processes.values())
        self._close_finished()

    def _close_finished(self, session_id: str | None = None) -> None:
        for process_id, managed in tuple(self._processes.items()):
            if session_id is not None and managed.session_id != session_id:
                continue
            if managed.state != "running":
                for task in (
                    managed.stdout_task,
                    managed.stderr_task,
                    managed.pty_task,
                    managed.watcher_task,
                    managed.timeout_task,
                ):
                    if task is not None and not task.done():
                        task.cancel()
                try:
                    managed.control.close()
                except Exception:
                    pass
                self._processes.pop(process_id, None)

    def _evict_finished(
        self,
        session_id: str,
        *,
        protected: set[str] | None = None,
    ) -> None:
        protected = protected or set()
        finished = [
            item
            for item in self._processes.values()
            if item.session_id == session_id and item.state != "running"
        ]
        while len(finished) > self.max_finished_per_session:
            candidate = next((item for item in finished if item.process_id not in protected), None)
            if candidate is None:
                return
            finished.remove(candidate)
            self._expire_process(candidate, reason="session_terminal_quota")

    def _expire_process(self, managed: _ManagedProcess, *, reason: str) -> None:
        records = self._expired.setdefault(managed.session_id, {})
        earliest = managed.ring[0].sequence if managed.ring else managed.next_sequence
        records[managed.process_id] = {
            "process_id": managed.process_id,
            "state": "expired",
            "exit_code": managed.exit_code,
            "earliest_cursor": earliest,
            "next_cursor": managed.next_sequence,
            "reason": reason,
        }
        while len(records) > self.max_expired_per_session:
            records.pop(next(iter(records)))
        self._processes.pop(managed.process_id, None)
        self._discard_managed(managed)

    @staticmethod
    def _discard_managed(managed: _ManagedProcess) -> None:
        for task in (
            managed.stdout_task,
            managed.stderr_task,
            managed.pty_task,
            managed.watcher_task,
            managed.timeout_task,
        ):
            if task is not None and not task.done():
                task.cancel()
        try:
            managed.control.close()
        except Exception:
            pass


class _PtyControl:
    def __init__(self, pty: Any) -> None:
        self.pty = pty

    async def terminate(self, _process: object) -> bool:
        terminate = getattr(self.pty, "terminate", None)
        if not callable(terminate):
            return False
        try:
            await asyncio.to_thread(terminate)
        except Exception:
            return False
        return True

    def close(self) -> None:
        close = getattr(self.pty, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass


def _windows_pty_tokens(command: str) -> list[str]:
    """Parse one Windows shell command without POSIX backslash loss.

    ``shlex.split(..., posix=True)`` turns an unquoted ``C:\\...`` executable
    into a different path.  The Windows mode preserves backslashes and the
    resulting tokens are handed to pywinpty, which applies the native
    ``list2cmdline`` quoting before ``cmd.exe`` receives them.
    """

    tokens = shlex.split(command, posix=False)
    result: list[str] = []
    for token in tokens:
        if len(token) >= 2 and token[0] == token[-1] == '"':
            token = token[1:-1]
        result.append(token)
    if not result:
        raise ValueError("command must not be empty")
    return result


def _decode(value: bytes) -> str:
    try:
        return value.decode("utf-8")
    except UnicodeDecodeError:
        return value.decode("utf-8", errors="replace")


__all__ = ["ProcessOutput", "ProcessRead", "ProcessSessionError", "ProcessSessionManager"]
