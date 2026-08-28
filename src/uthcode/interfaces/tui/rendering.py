"""Public AgentEvent projection and immutable Markdown stream assembly."""

from __future__ import annotations

import time
import re
from dataclasses import dataclass, replace
from typing import Literal

from uthcode.application import AgentEvent, ContextUsage, TextPart, failure_message


_STREAM_RENDER_INTERVAL_SECONDS = 0.2


def context_usage_style(usage: ContextUsage) -> str:
    """Return the stable TUI severity class for dynamic usage."""

    if not isinstance(usage, ContextUsage):
        raise TypeError("usage must be ContextUsage")
    if not usage.available or usage.ratio is None:
        return "class:status"
    return "class:status.warning" if usage.ratio >= 0.90 else "class:status"


def context_usage_bar(usage: ContextUsage, *, width: int = 10) -> tuple[str, str]:
    """Render usage using the resolved operating limit when available."""

    if not isinstance(usage, ContextUsage):
        raise TypeError("usage must be ContextUsage")
    if isinstance(width, bool) or not isinstance(width, int) or width < 1:
        raise ValueError("width must be a positive integer")
    budget = usage.budget_tokens
    budget_label = (
        f"{budget // 1000}K"
        if isinstance(budget, int) and budget >= 1000
        else str(budget)
        if isinstance(budget, int)
        else "?"
    )
    if not usage.available or usage.ratio is None:
        return context_usage_style(usage), f"context: unavailable/{budget_label}"
    filled = min(width, max(0, int(round(usage.ratio * width))))
    bar = "█" * filled + "░" * (width - filled)
    return (
        context_usage_style(usage),
        f"context: [{bar}] {usage.used_tokens}/{budget_label}",
    )


def context_usage_ring(usage: ContextUsage) -> tuple[str, str]:
    """Render the compact input-area ring from the same Application usage."""

    if not isinstance(usage, ContextUsage):
        raise TypeError("usage must be ContextUsage")
    budget = usage.budget_tokens
    budget_label = (
        f"{budget // 1000}K"
        if isinstance(budget, int) and budget >= 1000
        else str(budget)
        if isinstance(budget, int)
        else "?"
    )
    if not usage.available or usage.ratio is None:
        return context_usage_style(usage), f"◌ unavailable/{budget_label}"
    glyph = (
        "●"
        if usage.ratio >= 0.90
        else "◕"
        if usage.ratio >= 0.75
        else "◑"
        if usage.ratio >= 0.50
        else "◔"
    )
    return context_usage_style(usage), f"{glyph} {usage.used_tokens}/{budget_label}"


@dataclass(frozen=True, slots=True)
class TextUpdate:
    block_id: str
    kind: str
    text: str
    mode: Literal["append", "replace"] = "append"
    authoritative: bool = False


@dataclass(frozen=True, slots=True)
class ToolUpdate:
    tool_call_id: str
    tool_name: str
    command: str
    status: str


@dataclass(frozen=True, slots=True)
class PlanUpdate:
    revision: int
    text: str


@dataclass(frozen=True, slots=True)
class TaskStateUpdate:
    items: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class RenderOperation:
    """One ordered, display-safe operation in the Agent event timeline."""

    kind: Literal["user", "plan", "task_state", "text", "tool", "terminal"]
    value: object


@dataclass(frozen=True, slots=True)
class RenderBatch:
    users: tuple[tuple[str, str], ...] = ()
    plans: tuple[PlanUpdate, ...] = ()
    task_states: tuple[TaskStateUpdate, ...] = ()
    text: tuple[TextUpdate, ...] = ()
    tools: tuple[ToolUpdate, ...] = ()
    terminal: str | None = None
    terminal_message: str | None = None
    final_text: str | None = None
    activity: str | None = None
    operations: tuple[RenderOperation, ...] = ()

    @property
    def has_updates(self) -> bool:
        return bool(
            self.users
            or self.plans
            or self.task_states
            or self.text
            or self.tools
            or self.terminal
            or self.terminal_message
            or self.activity
            or self.operations
        )


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
    block_id: str
    kind: str
    message_id: str
    segment_index: int | None = None
    pending: str = ""
    completed: str | None = None
    authoritative_emitted: bool = False
    closed: bool = False


def _message_text(message: object) -> str:
    return "".join(
        part.text
        for part in getattr(message, "parts", ())
        if isinstance(part, TextPart)
    )


def _text_value(event: AgentEvent, name: str, default: str = "") -> str:
    value = getattr(event, name, default)
    return value if isinstance(value, str) else default


def _enum_value(value: object) -> str:
    enum_value = getattr(value, "value", value)
    return enum_value if isinstance(enum_value, str) else ""


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
        self._blocks: list[_TextBuffer] = []
        self._active: _TextBuffer | None = None
        self._next_block_number = 0

    def _new_block(
        self,
        *,
        kind: str,
        message_id: str,
        segment_index: int | None = None,
    ) -> _TextBuffer:
        self._next_block_number += 1
        block = _TextBuffer(
            block_id=f"{message_id}:{kind}:{self._next_block_number}",
            kind=kind,
            message_id=message_id,
            segment_index=segment_index,
        )
        self._blocks.append(block)
        self._active = block
        return block

    def _active_block(self, *, kind: str, message_id: str) -> _TextBuffer:
        block = self._active
        if (
            block is None
            or block.closed
            or block.kind != kind
            or block.message_id != message_id
        ):
            block = self._new_block(kind=kind, message_id=message_id)
        return block

    def _latest_assistant_block(self, message_id: str) -> _TextBuffer | None:
        for block in reversed(self._blocks):
            if block.kind == "assistant" and block.message_id == message_id:
                return block
        return None

    @staticmethod
    def _with_operation(
        batch: RenderBatch,
        *,
        kind: Literal["user", "plan", "task_state", "text", "tool", "terminal"],
        value: object,
    ) -> RenderBatch:
        return replace(
            batch,
            operations=batch.operations + (RenderOperation(kind, value),),
        )

    @staticmethod
    def _visible(batch: RenderBatch) -> RenderBatch | None:
        return batch if batch.has_updates else None

    def push(self, event: AgentEvent) -> RenderBatch | None:
        if not isinstance(event, AgentEvent):
            raise TypeError("event must be an AgentEvent")
        event_type = event.event_type
        if event_type == "turn_started":
            value = (
                _text_value(event, "message_id"),
                _message_text(getattr(event, "message", None)),
            )
            return RenderBatch(
                users=(
                    value,
                ),
                operations=(RenderOperation("user", value),),
            )
        if event_type == "reasoning_started":
            batch = self.flush()
            active = self._active
            if active is not None:
                active.closed = True
            self._new_block(
                kind="reasoning",
                message_id=_text_value(event, "message_id"),
                segment_index=getattr(event, "segment_index", None),
            )
            return self._visible(batch)
        if event_type == "reasoning_finished":
            batch = self.flush()
            active = self._active
            if (
                active is not None
                and active.kind == "reasoning"
                and active.message_id == _text_value(event, "message_id")
            ):
                active.closed = True
                self._active = None
            return self._visible(batch)
        if event_type in {"reasoning_delta", "assistant_message_delta"}:
            kind = "reasoning" if event_type == "reasoning_delta" else "assistant"
            text = _text_value(event, "text")
            if not text:
                return None
            block = self._active_block(
                kind=kind,
                message_id=_text_value(event, "message_id"),
            )
            block.pending += text
            if self._clock() - self._last_flush_at >= self.interval_seconds:
                return self.flush()
            return None
        if event_type == "assistant_message_completed":
            message_id = _text_value(event, "message_id")
            buffer = self._active
            if (
                buffer is None
                or buffer.kind != "assistant"
                or buffer.message_id != message_id
                or buffer.authoritative_emitted
            ):
                buffer = self._latest_assistant_block(message_id)
            if buffer is None or buffer.authoritative_emitted:
                buffer = self._new_block(kind="assistant", message_id=message_id)
            buffer.completed = _message_text(getattr(event, "message", None))
            buffer.closed = True
            batch = self.flush()
            self._active = None
            return self._visible(batch)
        if event_type == "plan_proposed":
            batch = self.flush()
            update = PlanUpdate(
                int(getattr(event, "revision")),
                _text_value(event, "plan_text"),
            )
            return replace(
                batch,
                plans=batch.plans + (update,),
                operations=batch.operations + (RenderOperation("plan", update),),
            )
        if event_type == "task_state_changed":
            batch = self.flush()
            task_state = getattr(event, "task_state")
            items = tuple(
                (
                    _enum_value(getattr(item, "status", "")),
                    str(getattr(item, "content", "")),
                )
                for item in getattr(task_state, "items", ())
            )
            update = TaskStateUpdate(items)
            return replace(
                batch,
                task_states=batch.task_states + (update,),
                operations=batch.operations + (RenderOperation("task_state", update),),
            )
        if event_type == "behavior_mode_changed":
            mode = _enum_value(getattr(event, "behavior_mode", ""))
            return replace(self.flush(), activity=f"mode: {mode}")
        if event_type == "user_steering_requested":
            return replace(self.flush(), activity="steering…")
        if event_type == "user_steering_applied":
            return replace(self.flush(), activity="updating task…")
        if event_type == "completion_blocked":
            count = int(getattr(event, "unfinished_count"))
            return replace(
                self.flush(),
                activity=f"continuing · {count} unfinished tasks",
            )
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
            return replace(
                batch,
                tools=batch.tools + (update,),
                operations=batch.operations + (RenderOperation("tool", update),),
            )
        if event_type == "turn_pausing":
            return replace(self.flush(), activity="pausing…")
        if event_type == "turn_paused":
            return replace(self.flush(), activity="paused")
        if event_type == "turn_resumed":
            return replace(self.flush(), activity="generating")
        if event_type == "turn_completed":
            batch = self.flush()
            return replace(
                batch,
                terminal="completed",
                final_text=_text_value(event, "final_text"),
                operations=batch.operations
                + (RenderOperation("terminal", "completed"),),
            )
        if event_type == "turn_failed":
            batch = self.flush()
            return replace(
                batch,
                terminal="failed",
                terminal_message=failure_message(
                    getattr(event, "failure_reason", None)
                ),
                operations=batch.operations
                + (RenderOperation("terminal", "failed"),),
            )
        if event_type == "turn_cancelled":
            batch = self.flush()
            return replace(
                batch,
                terminal="cancelled",
                operations=batch.operations
                + (RenderOperation("terminal", "cancelled"),),
            )
        return None

    def flush(self) -> RenderBatch:
        updates: list[TextUpdate] = []
        for buffer in self._blocks:
            block_id = buffer.block_id
            if buffer.authoritative_emitted:
                continue
            was_completed = buffer.completed is not None
            if buffer.completed is not None:
                desired = buffer.completed
                # Preserve a final unflushed delta as a preview operation
                # before the authoritative replacement.  The TUI never makes
                # the former permanent for assistant blocks.
                if buffer.pending:
                    updates.append(
                        TextUpdate(block_id, buffer.kind, buffer.pending)
                    )
                    buffer.pending = ""
                updates.append(
                    TextUpdate(
                        block_id,
                        buffer.kind,
                        desired,
                        mode="replace",
                        authoritative=True,
                    )
                )
                buffer.completed = None
                buffer.pending = ""
            else:
                text = buffer.pending
                mode = "append"
                buffer.pending = ""
                if text:
                    updates.append(TextUpdate(block_id, buffer.kind, text, mode))
            if was_completed:
                buffer.authoritative_emitted = True
        operations = tuple(RenderOperation("text", update) for update in updates)
        self._last_flush_at = self._clock()
        return RenderBatch(text=tuple(updates), operations=operations)


__all__ = [
    "AgentEventRenderer",
    "MarkdownStream",
    "PlanUpdate",
    "RenderBatch",
    "RenderOperation",
    "TaskStateUpdate",
    "TextUpdate",
    "ToolUpdate",
    "context_usage_bar",
    "context_usage_ring",
    "context_usage_style",
]
