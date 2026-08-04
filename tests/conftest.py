"""Global offline guard for the default W01 test suite."""

from __future__ import annotations

import asyncio
import socket
from typing import Any

import pytest


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call() -> Any:
    """Block outbound connections after pytest has created its event loop."""

    def blocked(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("real network access is forbidden in offline tests")

    async def blocked_async(*_args: Any, **_kwargs: Any) -> None:
        blocked()

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(asyncio, "open_connection", blocked_async)
    try:
        yield
    finally:
        monkeypatch.undo()
