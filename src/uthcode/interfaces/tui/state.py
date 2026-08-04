"""Small, interface-local state machines for the default Textual view."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum


class TranscriptEntryKind(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    REASONING = "reasoning"
    COMMAND = "command"
    SYSTEM = "system"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class TranscriptEntry:
    kind: TranscriptEntryKind
    text: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, TranscriptEntryKind):
            object.__setattr__(self, "kind", TranscriptEntryKind(self.kind))
        if not isinstance(self.text, str):
            raise TypeError("transcript text must be a string")


@dataclass(slots=True)
class ScrollFollowState:
    """Remember whether new content should keep the view at the bottom."""

    follow: bool = True
    tolerance: float = 1.0

    def observe(self, scroll_y: float, max_scroll_y: float) -> None:
        at_bottom = max_scroll_y - scroll_y <= self.tolerance
        if at_bottom:
            self.follow = True
        elif scroll_y < max_scroll_y:
            self.follow = False

    def reset(self) -> None:
        self.follow = True


@dataclass(slots=True)
class EscArmState:
    window_seconds: float = 1.0
    armed_until: float = 0.0

    @property
    def armed(self) -> bool:
        return self.armed_until > time.monotonic()

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


@dataclass(slots=True)
class StreamRenderState:
    """Accumulate deltas until the renderer reaches its batch boundary."""

    text_buffer: str = ""
    reasoning_buffer: str = ""
    rendered_text: str = ""
    rendered_reasoning: str = ""
    last_flush_at: float = field(default_factory=time.monotonic)

    def append_text(self, text: str) -> None:
        self.text_buffer += text

    def append_reasoning(self, text: str) -> None:
        self.reasoning_buffer += text

    @property
    def has_pending(self) -> bool:
        return bool(self.text_buffer or self.reasoning_buffer)

    def flush(self, now: float | None = None) -> tuple[str, str]:
        text = self.text_buffer
        reasoning = self.reasoning_buffer
        self.text_buffer = ""
        self.reasoning_buffer = ""
        self.rendered_text += text
        self.rendered_reasoning += reasoning
        self.last_flush_at = time.monotonic() if now is None else now
        return text, reasoning


@dataclass(slots=True)
class TranscriptState:
    entries: list[TranscriptEntry] = field(default_factory=list)
    scroll: ScrollFollowState = field(default_factory=ScrollFollowState)

    def add(self, kind: TranscriptEntryKind, text: str) -> TranscriptEntry:
        entry = TranscriptEntry(kind, text)
        self.entries.append(entry)
        return entry

    def clear(self) -> None:
        self.entries.clear()
        self.scroll.reset()

    def append_to_last(self, kind: TranscriptEntryKind, text: str) -> None:
        if not self.entries or self.entries[-1].kind is not kind:
            self.add(kind, text)
            return
        current = self.entries[-1]
        self.entries[-1] = TranscriptEntry(kind, current.text + text)


__all__ = [
    "EscArmState",
    "ScrollFollowState",
    "StreamRenderState",
    "TranscriptEntry",
    "TranscriptEntryKind",
    "TranscriptState",
]
