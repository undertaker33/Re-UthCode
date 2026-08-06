"""Display-only state for the default Textual interface."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum


class TranscriptEntryKind(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    REASONING = "reasoning"
    TOOL = "tool"
    COMMAND = "command"
    SYSTEM = "system"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class TranscriptEntry:
    kind: TranscriptEntryKind
    text: str
    display_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, TranscriptEntryKind):
            object.__setattr__(self, "kind", TranscriptEntryKind(self.kind))
        if not isinstance(self.text, str):
            raise TypeError("transcript text must be a string")
        if self.display_id is not None and not isinstance(self.display_id, str):
            raise TypeError("display_id must be a string or None")


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
class TranscriptState:
    """The transcript's visible entries and widget associations only.

    This state never stores an AgentEvent or a Provider/Core object.  The
    widget maps contain display widgets keyed by public message/tool IDs; tool
    result content is therefore not retained by the interface state.
    """

    entries: list[TranscriptEntry] = field(default_factory=list)
    widgets: dict[str, object] = field(default_factory=dict)
    tool_rows: dict[str, object] = field(default_factory=dict)
    scroll: ScrollFollowState = field(default_factory=ScrollFollowState)
    active_turn_id: str | None = None
    cancel_prompt: str | None = None

    def add(
        self,
        kind: TranscriptEntryKind,
        text: str,
        *,
        display_id: str | None = None,
    ) -> TranscriptEntry:
        entry = TranscriptEntry(kind, text, display_id)
        self.entries.append(entry)
        return entry

    def update_display(self, display_id: str, text: str) -> None:
        for index in range(len(self.entries) - 1, -1, -1):
            entry = self.entries[index]
            if entry.display_id == display_id:
                self.entries[index] = TranscriptEntry(
                    entry.kind,
                    text,
                    display_id,
                )
                return
        raise KeyError(display_id)

    def append_to_last(self, kind: TranscriptEntryKind, text: str) -> None:
        if not self.entries or self.entries[-1].kind is not kind:
            self.add(kind, text)
            return
        current = self.entries[-1]
        self.entries[-1] = TranscriptEntry(
            kind,
            current.text + text,
            current.display_id,
        )

    def clear(self) -> None:
        self.entries.clear()
        self.widgets.clear()
        self.tool_rows.clear()
        self.scroll.reset()
        self.active_turn_id = None
        self.cancel_prompt = None


__all__ = [
    "EscArmState",
    "ScrollFollowState",
    "TranscriptEntry",
    "TranscriptEntryKind",
    "TranscriptState",
]
