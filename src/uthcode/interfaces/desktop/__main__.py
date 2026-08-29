"""Run the Desktop child process JSONL bridge."""

from __future__ import annotations

import asyncio

from uthcode.interfaces.desktop.bridge import DesktopBridge


def main() -> None:
    asyncio.run(DesktopBridge().serve_forever())


if __name__ == "__main__":  # pragma: no cover - exercised in subprocess tests
    main()
