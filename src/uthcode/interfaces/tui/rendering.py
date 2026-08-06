"""AgentEvent projection and bounded stream batching for the TUI."""

from __future__ import annotations

import time
from dataclasses import dataclass, replace
from typing import Literal

from uthcode.application import AgentEvent, TextPart


STREAM_RENDER_INTERVAL_SECONDS = 0.2


@dataclass(frozen=True, slots=True)
class TextUpdate:
    block_id: str
    kind: str
    text: str
    mode: Literal["append", "replace"] = "append"

    def __post_init__(self) -> None:
        if self.mode not in {"append", "replace"}:
            raise ValueError("text update mode must be append or replace")


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
class _TextBuffer:
    kind: str
    pending: str = ""
    rendered: str = ""
    completed: str | None = None


def _message_text(message: object) -> str:
    parts = getattr(message, "parts", ())
    return "".join(
        part.text
        for part in parts
        if isinstance(part, TextPart)
    )


def _text_value(event: AgentEvent, name: str, default: str = "") -> str:
    value = getattr(event, name, default)
    return value if isinstance(value, str) else default


def _block_id(message_id: str, kind: str) -> str:
    return f"{message_id}:{kind}"


class AgentEventRenderer:
    """Convert public AgentEvent values into display-only batches.

    Only display-safe fields exposed by AgentEvent are read.  In particular,
    this renderer never receives or inspects a ToolResult or raw ToolCall
    arguments; Tool rows use the Application-provided command summary.
    """

    __slots__ = ("_clock", "_last_flush_at", "_buffers", "interval_seconds")

    def __init__(
        self,
        *,
        interval_seconds: float = STREAM_RENDER_INTERVAL_SECONDS,
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
            message_id = _text_value(event, "message_id")
            return RenderBatch(
                users=((message_id, _message_text(getattr(event, "message", None))),),
            )

        if event_type in {"reasoning_delta", "assistant_message_delta"}:
            kind = "reasoning" if event_type == "reasoning_delta" else "assistant"
            message_id = _text_value(event, "message_id")
            text = _text_value(event, "text")
            if not text:
                return None
            buffer = self._buffers.setdefault(
                _block_id(message_id, kind),
                _TextBuffer(kind),
            )
            buffer.pending += text
            buffer.completed = None
            if self._clock() - self._last_flush_at >= self.interval_seconds:
                return self.flush()
            return None

        if event_type == "assistant_message_completed":
            message_id = _text_value(event, "message_id")
            kind = "assistant"
            buffer = self._buffers.setdefault(
                _block_id(message_id, kind),
                _TextBuffer(kind),
            )
            buffer.completed = _message_text(getattr(event, "message", None))
            return self.flush()

        if event_type in {"tool_started", "tool_finished"}:
            batch = self.flush()
            status = "running" if event_type == "tool_started" else _text_value(
                event,
                "status",
                "finished",
            )
            update = ToolUpdate(
                tool_call_id=_text_value(event, "tool_call_id"),
                tool_name=_text_value(event, "tool_name", "unknown tool"),
                command=_text_value(event, "command", "<tool summary unavailable>"),
                status=status,
            )
            return replace(batch, tools=batch.tools + (update,))

        if event_type == "turn_completed":
            batch = self.flush()
            return replace(
                batch,
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
                current = buffer.rendered
                if desired.startswith(current):
                    delta = desired[len(current) :]
                    mode: Literal["append", "replace"] = "append"
                else:
                    delta = desired
                    mode = "replace"
                buffer.completed = None
            else:
                desired = buffer.rendered + buffer.pending
                delta = buffer.pending
                mode = "append"
            buffer.pending = ""
            buffer.rendered = desired
            if delta or mode == "replace":
                updates.append(TextUpdate(block_id, buffer.kind, delta, mode))
        self._last_flush_at = self._clock()
        return RenderBatch(text=tuple(updates))


__all__ = [
    "AgentEventRenderer",
    "RenderBatch",
    "STREAM_RENDER_INTERVAL_SECONDS",
    "TextUpdate",
    "ToolUpdate",
]
