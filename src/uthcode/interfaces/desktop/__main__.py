"""Run the Desktop child process JSONL bridge."""

from __future__ import annotations

import asyncio
import sys

from uthcode.interfaces.desktop.bridge import DesktopBridge


def _configure_utf8_stdio() -> None:
    """Fix the Desktop JSONL transport encoding independently of Windows ACP."""

    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="strict")


def main() -> None:
    _configure_utf8_stdio()
    asyncio.run(DesktopBridge().serve_forever())


if __name__ == "__main__":  # pragma: no cover - exercised in subprocess tests
    main()
