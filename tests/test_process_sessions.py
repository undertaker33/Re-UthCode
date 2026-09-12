from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import pytest

from uthcode.core.provider import CancellationToken
from uthcode.integrations.tools.process_sessions import ProcessSessionError, ProcessSessionManager
from uthcode.integrations.tools.process_tools import BashTool


def _python(command: str) -> str:
    return subprocess.list2cmdline([sys.executable, "-c", command])


@pytest.mark.asyncio
async def test_bash_short_wait_cross_turn_read_and_cursor_expiry(tmp_path: Path) -> None:
    manager = ProcessSessionManager(max_output_bytes=32)
    tool = BashTool(tmp_path, process_manager=manager, session_provider=lambda: type("S", (), {"session_id": "s1"})())
    result = await tool.execute(
        {"command": _python("import time,sys; print('a'*100, flush=True); time.sleep(.2); print('done', flush=True)"), "yield_time_ms": 20},
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
    assert any("hello" in entry.text for entry in after.entries)
    await manager.shutdown()


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
