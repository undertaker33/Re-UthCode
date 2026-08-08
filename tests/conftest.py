"""Global offline guard for the default W01 test suite."""

from __future__ import annotations

import asyncio
import os
import socket
from typing import Any

import pytest


@pytest.fixture(autouse=True)
def isolate_user_home(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep permission/config lifecycle files inside the test sandbox."""

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOMEDRIVE", home.drive)
    monkeypatch.setenv("HOMEPATH", str(home)[len(home.drive):])


@pytest.fixture(autouse=True)
def preserve_live_environment() -> Any:
    """Restore live-test environment values between tests without printing them."""

    original_key = os.environ.get("DEEPSEEK_API_KEY")
    original_live = os.environ.get("UTHCODE_RUN_LIVE")
    yield
    if original_key is None:
        os.environ.pop("DEEPSEEK_API_KEY", None)
    else:
        os.environ["DEEPSEEK_API_KEY"] = original_key
    if original_live is None:
        os.environ.pop("UTHCODE_RUN_LIVE", None)
    else:
        os.environ["UTHCODE_RUN_LIVE"] = original_live


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Remove live credentials from the pytest process before it exits."""

    del session, exitstatus
    os.environ.pop("DEEPSEEK_API_KEY", None)
    os.environ.pop("UTHCODE_RUN_LIVE", None)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item: pytest.Item) -> Any:
    """Block outbound connections for the default suite, not explicit live tests."""

    if item.get_closest_marker("live") is not None:
        yield
        return

    original_socket_connect = socket.socket.connect

    def blocked(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("real network access is forbidden in offline tests")

    def blocked_socket_connect(sock: socket.socket, address: Any) -> Any:
        # Windows' default asyncio loop uses a loopback socket pair during
        # construction.  That is an in-process transport, not a provider
        # network request; keep external connections blocked.
        host = address[0] if isinstance(address, tuple) and address else None
        if host in {"127.0.0.1", "::1", "localhost"}:
            return original_socket_connect(sock, address)
        return blocked(address)

    async def blocked_async(*_args: Any, **_kwargs: Any) -> None:
        blocked()

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket.socket, "connect", blocked_socket_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(asyncio, "open_connection", blocked_async)
    try:
        yield
    finally:
        monkeypatch.undo()
