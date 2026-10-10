from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from uthcode.core.provider import CancellationToken
import uthcode.integrations.tools.process_sessions as process_sessions
from uthcode.integrations.tools.process_sessions import (
    ProcessSessionError,
    ProcessSessionManager,
    _ManagedProcess,
    _PtyControl,
    _terminate_windows_pty_tree,
)
from uthcode.integrations.tools.process_tools import BashTool, ProcessTool


def _python(command: str) -> str:
    return subprocess.list2cmdline([sys.executable, "-c", command])


def test_unreadable_pty_liveness_does_not_confirm_tree_termination() -> None:
    class UnreadablePty:
        def isalive(self) -> bool:
            raise OSError("process status unavailable")

    assert _terminate_windows_pty_tree(UnreadablePty()) is False


@pytest.mark.asyncio
async def test_posix_completed_pty_stop_preserves_exited_state(monkeypatch: pytest.MonkeyPatch) -> None:
    # Exercise POSIX state semantics even when this focused suite runs on Windows.
    monkeypatch.setattr(process_sessions, "os", SimpleNamespace(name="posix"))
    manager = ProcessSessionManager()
    control = SimpleNamespace(stop_confirmed=False)
    completed = _ManagedProcess(
        process_id="completed-pty",
        session_id="s1",
        command="fake",
        cwd=Path.cwd(),
        process=None,
        control=control,
        pty=object(),
        state="exited",
    )
    manager._processes[completed.process_id] = completed

    assert await manager.stop(completed.process_id, "s1") is True
    assert completed.state == "exited"

    class ExitDuringFinalizeLock:
        async def __aenter__(self) -> ExitDuringFinalizeLock:
            racing.state = "exited"
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

    racing = _ManagedProcess(
        process_id="racing-completed-pty",
        session_id="s1",
        command="fake",
        cwd=Path.cwd(),
        process=None,
        control=SimpleNamespace(stop_confirmed=False),
        pty=object(),
    )
    racing.pty_finalize_lock = ExitDuringFinalizeLock()  # type: ignore[assignment]
    manager._processes[racing.process_id] = racing

    assert await manager.stop(racing.process_id, "s1") is True
    assert racing.state == "exited"


@pytest.mark.asyncio
async def test_bash_short_wait_cross_turn_read_and_cursor_expiry(tmp_path: Path) -> None:
    manager = ProcessSessionManager(max_output_bytes=32)
    tool = BashTool(tmp_path, process_manager=manager, session_provider=lambda: type("S", (), {"session_id": "s1"})())
    result = await tool.execute(
        {"command": _python("import time,sys; print('a'*100, flush=True); time.sleep(.2); print('done', flush=True)"), "yield_time_ms": 50},
        cancellation=CancellationToken(),
    )
    assert result.process_id and result.process_state == "running"
    process_id = result.process_id
    await asyncio.sleep(.35)
    read = manager.read(process_id, "s1", 0)
    assert read.state == "exited" and read.exit_code == 0
    assert read.earliest_cursor > 0 and read.cursor_expired
    assert any("done" in entry.text for entry in read.entries)
    with pytest.raises(ProcessSessionError, match="does not belong"):
        manager.read(process_id, "s2", 0)
    await manager.shutdown()


@pytest.mark.asyncio
async def test_terminal_processes_are_evicted_with_explicit_expired_facts(tmp_path: Path) -> None:
    manager = ProcessSessionManager(
        max_finished_per_session=1,
        max_expired_per_session=4,
    )
    first = await manager.start(
        session_id="s1",
        command=_python("print('first', flush=True)"),
        cwd=tmp_path,
    )
    await asyncio.sleep(0.25)
    assert manager.read(first.process_id, "s1", 0).state == "exited"

    second = await manager.start(
        session_id="s1",
        command=_python("print('second', flush=True)"),
        cwd=tmp_path,
    )
    await asyncio.sleep(0.25)

    listed = manager.list("s1")
    assert [item["process_id"] for item in listed] == [second.process_id]
    expired = manager.read(first.process_id, "s1", 0)
    assert expired.state == "expired"
    assert expired.expired is True
    assert expired.cursor_expired is True
    assert expired.expiration_reason == "session_terminal_quota"
    assert expired.next_cursor >= expired.earliest_cursor
    await manager.shutdown()


@pytest.mark.asyncio
async def test_windows_pty_isatty_stdin_eof_and_resize(tmp_path: Path) -> None:
    if os.name != "nt":
        pytest.skip("native Windows PTY contract")
    manager = ProcessSessionManager()
    process = await manager.start(
        session_id="s1",
        command=_python("import os,sys; print(os.isatty(0), os.isatty(1), flush=True); print(sys.stdin.read(), flush=True)"),
        cwd=tmp_path,
        pty=True,
        rows=24,
        cols=80,
    )
    await asyncio.sleep(0.2)
    before = manager.read(process.process_id, "s1", 0)
    assert any("True True" in entry.text for entry in before.entries)
    await manager.resize(process.process_id, "s1", 40, 100)
    await manager.write(process.process_id, "s1", "hello\r\n", eof=True)
    await asyncio.sleep(0.6)
    after = manager.read(process.process_id, "s1", before.next_cursor)
    assert after.state == "exited" and after.exit_code == 0
    output = "".join(entry.text for entry in after.entries)
    assert "hello" in output
    assert process.pty.read_blocking is False
    assert not hasattr(process.pty, "_thread")
    await manager.shutdown()


@pytest.mark.asyncio
async def test_windows_pty_empty_idle_reads_do_not_end_output_pump(tmp_path: Path) -> None:
    if os.name != "nt":
        pytest.skip("native Windows PTY contract")
    manager = ProcessSessionManager()
    process = await manager.start(
        session_id="s1",
        command=_python(
            "import time; print('READY', flush=True); time.sleep(.25); "
            "print('AFTER-IDLE', flush=True); time.sleep(.25)"
        ),
        cwd=tmp_path,
        pty=True,
    )
    try:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + 3.0
        while loop.time() < deadline:
            read = manager.read(process.process_id, "s1", 0)
            output = "".join(entry.text for entry in read.entries)
            if "READY" in output:
                break
            await asyncio.sleep(0.01)
        assert "READY" in output
        await asyncio.sleep(0.12)
        assert process.state == "running"
        assert process.pty_task is not None and not process.pty_task.done()

        deadline = loop.time() + 3.0
        while loop.time() < deadline:
            read = manager.read(process.process_id, "s1", 0)
            output = "".join(entry.text for entry in read.entries)
            if "AFTER-IDLE" in output:
                break
            await asyncio.sleep(0.01)
        assert "AFTER-IDLE" in output
        deadline = loop.time() + 3.0
        while read.state == "running" and loop.time() < deadline:
            await asyncio.sleep(0.01)
            read = manager.read(process.process_id, "s1", 0)
        assert read.state == "exited" and read.exit_code == 0
        assert process.pty_eof is True
        assert not hasattr(process.pty, "_thread")
    finally:
        await manager.shutdown_session("s1")


@pytest.mark.asyncio
async def test_posix_pty_isatty_input_eof_resize_and_no_replay(tmp_path: Path) -> None:
    if os.name == "nt":
        pytest.skip("native POSIX PTY contract")
    manager = ProcessSessionManager()
    command = _python(
        "import os,sys; sys.stdin.reconfigure(encoding='utf-8'); "
        "size=os.get_terminal_size(1); "
        "print(f'TTY:{os.isatty(0)}:{os.isatty(1)} SIZE:{size.lines}x{size.columns}', flush=True); "
        "print('READY', flush=True); "
        "line=sys.stdin.readline(); print('RECEIVED:'+line.strip(), flush=True); "
        "size=os.get_terminal_size(1); print(f'RESIZE:{size.lines}x{size.columns}', flush=True); "
        "tail=sys.stdin.read(); print('TAIL:'+repr(tail), flush=True); "
        "print('PTY_STDERR', file=sys.stderr, flush=True)"
    )
    process = await manager.start(
        session_id="s1",
        command=command,
        cwd=tmp_path,
        pty=True,
        rows=24,
        cols=80,
    )
    try:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + 3.0
        output = ""
        while "READY" not in output and loop.time() < deadline:
            read = manager.read(process.process_id, "s1", 0)
            output = "".join(entry.text for entry in read.entries)
            await asyncio.sleep(0.01)
        assert "READY" in output
        assert "TTY:True:True SIZE:24x80" in output
        assert all(entry.stream == "terminal" for entry in read.entries)

        await manager.resize(process.process_id, "s1", 40, 100)
        await manager.write(process.process_id, "s1", "T11-PTY-一次\n")
        deadline = loop.time() + 3.0
        while "RECEIVED:T11-PTY-一次" not in output and loop.time() < deadline:
            read = manager.read(process.process_id, "s1", 0)
            output = "".join(entry.text for entry in read.entries)
            await asyncio.sleep(0.01)
        assert "RECEIVED:T11-PTY-一次" in output
        assert "RESIZE:40x100" in output

        await manager.write(process.process_id, "s1", "", eof=True)
        deadline = loop.time() + 3.0
        while process.state == "running" and loop.time() < deadline:
            await asyncio.sleep(0.01)
        read = manager.read(process.process_id, "s1", 0)
        output = "".join(entry.text for entry in read.entries)
        assert process.state == "exited"
        assert "TAIL:''" in output
        assert "PTY_STDERR" in output
        assert all(entry.stream == "terminal" for entry in read.entries)
    finally:
        await manager.shutdown_session("s1")


@pytest.mark.asyncio
async def test_pty_turn_cancellation_unblocks_reader_and_reaps_child(tmp_path: Path) -> None:
    manager = ProcessSessionManager()
    child_pid_file = tmp_path / "pty-child.pid"
    if os.name == "nt":
        child_script = tmp_path / "pty-child.py"
        child_script.write_text(
            "import os, time\n"
            "from pathlib import Path\n"
            f"Path({str(child_pid_file)!r}).write_text(str(os.getpid()), encoding='ascii')\n"
            "print('READY', flush=True)\n"
            "time.sleep(30)\n",
            encoding="utf-8",
        )
        command = subprocess.list2cmdline([sys.executable, str(child_script)])
    else:
        command = _python("import time; print('READY', flush=True); time.sleep(30)")
    process = await manager.start(
        session_id="s1",
        command=command,
        cwd=tmp_path,
        pty=True,
        turn_id="turn-cancel",
    )
    try:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + 3.0
        output = ""
        while "READY" not in output and loop.time() < deadline:
            output = "".join(entry.text for entry in manager.read(process.process_id, "s1", 0).entries)
            await asyncio.sleep(0.01)
        assert "READY" in output
        reader_task = process.pty_task
        assert reader_task is not None and not reader_task.done()

        await manager.shutdown_turn("s1", "turn-cancel")

        assert process.state == "exited"
        assert process.pty is not None and not process.pty.isalive()
        await asyncio.wait_for(asyncio.shield(reader_task), timeout=2.0)
        if os.name == "nt":
            child_pid = int(child_pid_file.read_text(encoding="ascii"))
            await asyncio.sleep(0.1)
            child_list = await asyncio.to_thread(
                subprocess.run,
                ["tasklist.exe", "/FI", f"PID eq {child_pid}", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                check=False,
            )
            assert child_list.returncode == 0
            assert f'"{child_pid}"' not in child_list.stdout
            assert not hasattr(process.pty, "_thread")
    finally:
        await manager.shutdown_session("s1")


@pytest.mark.asyncio
async def test_windows_stop_after_completed_pty_does_not_target_a_reused_pid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if os.name != "nt":
        pytest.skip("native Windows PTY contract")
    manager = ProcessSessionManager()
    process = await manager.start(
        session_id="s1",
        command=_python("print('DONE', flush=True)"),
        cwd=tmp_path,
        pty=True,
    )
    try:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + 3.0
        while process.state == "running" and loop.time() < deadline:
            await asyncio.sleep(0.01)
        assert process.state == "exited"

        def reject_dead_pid(_pty: object) -> bool:
            pytest.fail("a completed PTY PID must not be passed to taskkill")

        monkeypatch.setattr(
            "uthcode.integrations.tools.process_sessions._terminate_windows_pty_tree",
            reject_dead_pid,
        )
        assert await manager.stop(process.process_id, "s1") is False
        assert process.state == "unknown"
    finally:
        await manager.shutdown_session("s1")


@pytest.mark.asyncio
async def test_windows_pty_stop_failure_remains_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    if os.name != "nt":
        pytest.skip("native Windows PTY contract")

    class FakePty:
        pid = 12345
        exitstatus = None
        closed = False
        fd = -1

        def __init__(self) -> None:
            self.alive = True

        def isalive(self) -> bool:
            return self.alive

        def terminate(self, force: bool = False) -> None:
            self.alive = False

    manager = ProcessSessionManager()
    pty = FakePty()
    managed = _ManagedProcess(
        process_id="failed-pty-stop",
        session_id="s1",
        command="fake",
        cwd=Path.cwd(),
        process=None,
        control=_PtyControl(pty),
        pty=pty,
    )
    manager._processes[managed.process_id] = managed

    monkeypatch.setattr(
        "uthcode.integrations.tools.process_sessions._terminate_windows_pty_tree",
        lambda _pty: False,
    )
    assert await manager.stop(managed.process_id, "s1") is False
    assert managed.state == "unknown"
    assert pty.alive is False


@pytest.mark.asyncio
async def test_turn_cleanup_stops_only_the_cancelled_turn_and_session_shutdown_clears_all(
    tmp_path: Path,
) -> None:
    manager = ProcessSessionManager()
    first = await manager.start(
        session_id="s1",
        command=_python("import time; time.sleep(5)"),
        cwd=tmp_path,
        turn_id="turn-1",
    )
    second = await manager.start(
        session_id="s1",
        command=_python("import time; time.sleep(5)"),
        cwd=tmp_path,
        turn_id="turn-2",
    )

    await manager.shutdown_turn("s1", "turn-1")
    assert manager.get(first.process_id, "s1").state == "exited"
    assert manager.get(second.process_id, "s1").state == "running"

    await manager.shutdown_session("s1")
    assert manager.list("s1") == ()


@pytest.mark.asyncio
async def test_process_read_waits_for_bounded_time_when_running_process_is_idle(tmp_path: Path) -> None:
    manager = ProcessSessionManager()
    process = await manager.start(
        session_id="s1",
        command=_python("import time; time.sleep(1.0)"),
        cwd=tmp_path,
    )
    tool = ProcessTool(
        manager,
        session_provider=lambda: type("S", (), {"session_id": "s1"})(),
    )

    started = time.monotonic()
    result = await tool.execute(
        {"action": "read", "process_id": process.process_id, "cursor": 0, "wait_ms": 160},
        cancellation=CancellationToken(),
    )
    elapsed = time.monotonic() - started

    assert not result.is_error
    assert elapsed >= 0.12
    assert elapsed < 0.8
    assert result.process_state == "running"
    assert "no new output" in str(result.content)
    await manager.shutdown()


@pytest.mark.asyncio
async def test_process_read_wait_is_cancelled_without_waiting_for_deadline(tmp_path: Path) -> None:
    manager = ProcessSessionManager()
    process = await manager.start(
        session_id="s1",
        command=_python("import time; time.sleep(5.0)"),
        cwd=tmp_path,
    )
    tool = ProcessTool(
        manager,
        session_provider=lambda: type("S", (), {"session_id": "s1"})(),
    )
    cancellation = CancellationToken()
    task = asyncio.create_task(
        tool.execute(
            {"action": "read", "process_id": process.process_id, "wait_ms": 3000},
            cancellation=cancellation,
        )
    )
    await asyncio.sleep(0.05)
    started = time.monotonic()
    cancellation.cancel()
    result = await task
    elapsed = time.monotonic() - started

    assert result.is_error
    assert "cancelled" in str(result.content).lower()
    assert elapsed < 0.5
    await manager.shutdown()


@pytest.mark.asyncio
async def test_process_read_rejects_zero_wait_instead_of_bypassing_the_bound(tmp_path: Path) -> None:
    manager = ProcessSessionManager()
    process = await manager.start(
        session_id="s1",
        command=_python("import time; time.sleep(1.0)"),
        cwd=tmp_path,
    )
    tool = ProcessTool(
        manager,
        session_provider=lambda: type("S", (), {"session_id": "s1"})(),
    )
    result = await tool.execute(
        {"action": "read", "process_id": process.process_id, "wait_ms": 0},
        cancellation=CancellationToken(),
    )
    assert result.is_error
    assert "between 50 and 60000" in str(result.content)
    await manager.shutdown()


@pytest.mark.asyncio
async def test_process_read_returns_on_terminal_state_before_wait_deadline(tmp_path: Path) -> None:
    manager = ProcessSessionManager()
    process = await manager.start(
        session_id="s1",
        command=_python("import time; time.sleep(.12)"),
        cwd=tmp_path,
    )
    tool = ProcessTool(
        manager,
        session_provider=lambda: type("S", (), {"session_id": "s1"})(),
    )
    started = time.monotonic()
    result = await tool.execute(
        {"action": "read", "process_id": process.process_id, "wait_ms": 1000},
        cancellation=CancellationToken(),
    )
    elapsed = time.monotonic() - started
    assert not result.is_error
    assert result.process_state == "exited"
    assert elapsed < 0.8
    await manager.shutdown()
