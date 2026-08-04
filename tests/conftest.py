"""Global offline guard for the default W01 test suite."""

from __future__ import annotations

import asyncio
import os
import socket
from typing import Any

import pytest


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
