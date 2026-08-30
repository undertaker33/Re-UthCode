"""Global offline guard for the default W01 test suite."""

from __future__ import annotations

import asyncio
import ntpath
import os
import socket
import tempfile
from pathlib import Path
from typing import Any

import pytest


def _lexical_windows_path(path: Path | str) -> str:
    """Normalize Windows paths without touching the filesystem."""

    return ntpath.normcase(ntpath.normpath(ntpath.abspath(os.fspath(path))))


_WORKSPACE_ROOT = _lexical_windows_path(Path(__file__).parent.parent)
_SYSTEM_TEMP_ROOT = _lexical_windows_path(tempfile.gettempdir())
_REAL_USER_PROFILE = r"C:\Users\93445"
_REAL_USER_CONFIG = r"C:\Users\93445\.uthcode\config.toml"
_REAL_USER_PROFILE_KEY = _lexical_windows_path(_REAL_USER_PROFILE)
_REAL_USER_CONFIG_KEY = _lexical_windows_path(_REAL_USER_CONFIG)


def _within(path: str, root: str) -> bool:
    normalized_path = _lexical_windows_path(path)
    normalized_root = _lexical_windows_path(root).rstrip("\\")
    return normalized_path == normalized_root or normalized_path.startswith(f"{normalized_root}\\")


def _assert_isolated_test_path(label: str, path: Path) -> Path:
    """Reject real-user state using lexical Windows path semantics only."""

    normalized = _lexical_windows_path(path)
    if normalized in {_REAL_USER_PROFILE_KEY, _REAL_USER_CONFIG_KEY}:
        raise AssertionError(f"{label} resolves to the real user profile/config")
    if _within(normalized, _REAL_USER_PROFILE_KEY) and not _within(normalized, _SYSTEM_TEMP_ROOT):
        raise AssertionError(f"{label} resolves inside the real user profile")
    if not (_within(normalized, _WORKSPACE_ROOT) or _within(normalized, _SYSTEM_TEMP_ROOT)):
        raise AssertionError(f"{label} must be under the workspace or system temp")
    return path


@pytest.fixture(autouse=True)
def isolate_user_home(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep permission/config lifecycle files inside the test sandbox."""

    temporary_root = _assert_isolated_test_path("pytest temporary root", Path(tmp_path))
    home = temporary_root / "home"
    appdata = home / "AppData" / "Roaming"
    local_appdata = home / "AppData" / "Local"
    config_path = home / ".uthcode" / "config.toml"
    _assert_isolated_test_path("test HOME", home)
    _assert_isolated_test_path("test APPDATA", appdata)
    _assert_isolated_test_path("test LOCALAPPDATA", local_appdata)
    _assert_isolated_test_path("test config", config_path)
    home.mkdir()
    appdata.mkdir(parents=True)
    local_appdata.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setenv("LOCALAPPDATA", str(local_appdata))
    monkeypatch.setenv("HOMEDRIVE", home.drive)
    monkeypatch.setenv("HOMEPATH", str(home)[len(home.drive):])
    monkeypatch.setenv("UTHCODE_CONFIG_PATH", str(config_path))


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
