"""Public AgentEvent projection and immutable Markdown stream assembly."""

from __future__ import annotations

import time
import re
from dataclasses import dataclass, replace
from typing import Literal

from uthcode.application import AgentEvent, TextPart


_STREAM_RENDER_INTERVAL_SECONDS = 0.2


@dataclass(frozen=True, slots=True)
class TextUpdate:
    block_id: str
    kind: str
    text: str
    mode: Literal["append", "replace"] = "append"


@dataclass(frozen=True, slots=True)
class ToolUpdate:
    tool_call_id: str
    tool_name: str
    command: str
    status: str


@dataclass(frozen=True, slots=True)
class RenderBatch:
    users: tuple[tuple[str, str], ...] = ()
    text: tuple[TextUpdate, ...] = ()
    tools: tuple[ToolUpdate, ...] = ()
    terminal: str | None = None
    final_text: str | None = None

    @property
    def has_updates(self) -> bool:
        return bool(self.users or self.text or self.tools or self.terminal)


@dataclass(slots=True)
class MarkdownStream:
    """Split an append-only Markdown stream into committed and preview text."""

    committed: str = ""
    pending: str = ""

    @property
    def full_text(self) -> str:
        return self.committed + self.pending

    def append(self, text: str) -> tuple[str, ...]:
        self.pending += text
        return self._drain_complete_blocks()

    def replace(self, authoritative: str) -> tuple[tuple[str, ...], bool]:
        current = self.full_text
        if authoritative.startswith(self.committed):
            self.pending = authoritative[len(self.committed) :]
            return self._drain_complete_blocks(), False
        if authoritative == current:
            return (), False
        self.pending = ""
        return (), True

    def force(self) -> str:
        value = self.pending
        self.committed += value
        self.pending = ""
        return value

    def _drain_complete_blocks(self) -> tuple[str, ...]:
        boundary = _safe_markdown_boundary(self.pending)
        if boundary <= 0:
            return ()
        value = self.pending[:boundary]
        self.pending = self.pending[boundary:]
        self.committed += value
        return (value,)


def _safe_markdown_boundary(text: str) -> int:
    """Return the last block boundary safe to print irreversibly."""

    in_fence = False
    fence_char = ""
    fence_size = 0
    last_safe = 0
    offset = 0
    for line in text.splitlines(keepends=True):
        if not line.endswith(("\n", "\r")):
            break
        body = line.rstrip("\r\n")
        fence = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", body)
        if fence is not None:
            marker, remainder = fence.groups()
            char = marker[0]
            count = len(marker)
            if not in_fence:
                in_fence = True
                fence_char = char
                fence_size = count
            elif (
                char == fence_char
                and count >= fence_size
                and not remainder.strip()
            ):
                in_fence = False
                last_safe = offset + len(line)
        elif not in_fence and not body.strip():
            last_safe = offset + len(line)
        offset += len(line)
    return last_safe


@dataclass(slots=True)
class _TextBuffer:
    kind: str
    pending: str = ""
    rendered: str = ""
    completed: str | None = None


def _message_text(message: object) -> str:
    return "".join(
        part.text
        for part in getattr(message, "parts", ())
        if isinstance(part, TextPart)
    )


def _text_value(event: AgentEvent, name: str, default: str = "") -> str:
    value = getattr(event, name, default)
    return value if isinstance(value, str) else default


class AgentEventRenderer:
    """Batch display-safe public events without retaining tool results."""

    def __init__(
        self,
        *,
        interval_seconds: float = _STREAM_RENDER_INTERVAL_SECONDS,
        clock=time.monotonic,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        self.interval_seconds = interval_seconds
        self._clock = clock
        self._last_flush_at = clock()
        self._buffers: dict[str, _TextBuffer] = {}

    def push(self, event: AgentEvent) -> RenderBatch | None:
        if not isinstance(event, AgentEvent):
            raise TypeError("event must be an AgentEvent")
        event_type = event.event_type
        if event_type == "turn_started":
            return RenderBatch(
                users=(
                    (
                        _text_value(event, "message_id"),
                        _message_text(getattr(event, "message", None)),
                    ),
                )
            )
        if event_type in {"reasoning_delta", "assistant_message_delta"}:
            kind = "reasoning" if event_type == "reasoning_delta" else "assistant"
            key = f"{_text_value(event, 'message_id')}:{kind}"
            text = _text_value(event, "text")
            if not text:
                return None
            self._buffers.setdefault(key, _TextBuffer(kind)).pending += text
            if self._clock() - self._last_flush_at >= self.interval_seconds:
                return self.flush()
            return None
        if event_type == "assistant_message_completed":
            key = f"{_text_value(event, 'message_id')}:assistant"
            buffer = self._buffers.setdefault(key, _TextBuffer("assistant"))
            buffer.completed = _message_text(getattr(event, "message", None))
            return self.flush()
        if event_type in {"tool_started", "tool_finished"}:
            batch = self.flush()
            status = (
                "running"
                if event_type == "tool_started"
                else _text_value(event, "status", "finished")
            )
            update = ToolUpdate(
                _text_value(event, "tool_call_id"),
                _text_value(event, "tool_name", "unknown tool"),
                _text_value(event, "command", "<tool summary unavailable>"),
                status,
            )
            return replace(batch, tools=batch.tools + (update,))
        if event_type == "turn_completed":
            return replace(
                self.flush(),
                terminal="completed",
                final_text=_text_value(event, "final_text"),
            )
        if event_type == "turn_failed":
            return replace(self.flush(), terminal="failed")
        if event_type == "turn_cancelled":
            return replace(self.flush(), terminal="cancelled")
        return None

    def flush(self) -> RenderBatch:
        updates: list[TextUpdate] = []
        for block_id, buffer in self._buffers.items():
            if buffer.completed is not None:
                desired = buffer.completed
                if desired.startswith(buffer.rendered):
                    text = desired[len(buffer.rendered) :]
                    mode: Literal["append", "replace"] = "append"
                else:
                    text = desired
                    mode = "replace"
                buffer.completed = None
                buffer.pending = ""
                buffer.rendered = desired
            else:
                text = buffer.pending
                mode = "append"
                buffer.pending = ""
                buffer.rendered += text
            if text or mode == "replace":
                updates.append(TextUpdate(block_id, buffer.kind, text, mode))
        self._last_flush_at = self._clock()
        return RenderBatch(text=tuple(updates))


__all__ = [
    "AgentEventRenderer",
    "MarkdownStream",
    "RenderBatch",
    "TextUpdate",
    "ToolUpdate",
]
