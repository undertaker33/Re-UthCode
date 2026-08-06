"""Small interface-local state helpers."""

from __future__ import annotations

import time
from dataclasses import dataclass

import regex


@dataclass(slots=True)
class EscArmState:
    window_seconds: float = 1.0
    armed_until: float = 0.0

    def arm(self, now: float | None = None) -> None:
        current = time.monotonic() if now is None else now
        self.armed_until = current + self.window_seconds

    def consume(self, now: float | None = None) -> bool:
        current = time.monotonic() if now is None else now
        if self.armed_until and current <= self.armed_until:
            self.armed_until = 0.0
            return True
        self.armed_until = 0.0
        return False

    def clear(self) -> None:
        self.armed_until = 0.0


def previous_grapheme_length(text: str) -> int:
    """Return the code-point length of the final Unicode grapheme."""

    match = regex.search(r"\X\Z", text)
    return len(match.group(0)) if match is not None else 0


__all__ = ["EscArmState", "previous_grapheme_length"]
