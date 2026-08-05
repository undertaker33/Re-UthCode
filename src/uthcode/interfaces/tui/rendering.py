"""Application event batching for the visible transcript."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from uthcode.application import GenerationCompleted, ReasoningDelta, TextDelta

from .state import StreamRenderState


STREAM_RENDER_INTERVAL_SECONDS = 0.2


@dataclass(frozen=True, slots=True)
class RenderBatch:
    text: str = ""
    reasoning: str = ""
    completed: bool = False
    cancelled: bool = False


def _response_text(event: GenerationCompleted) -> str:
    message = getattr(event.response, "message", None)
    parts = getattr(message, "parts", ())
    return "".join(
        str(getattr(part, "text", ""))
        for part in parts
        if isinstance(getattr(part, "text", ""), str)
    )


class StreamRenderer:
    """Batch deltas and force a final update for every terminal path."""

    def __init__(
        self,
        *,
        interval_seconds: float = STREAM_RENDER_INTERVAL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        self.interval_seconds = interval_seconds
        self._clock = clock
        self.state = StreamRenderState(last_flush_at=clock())

    def push(self, event: object) -> RenderBatch | None:
        now = self._clock()
        if isinstance(event, TextDelta):
            self.state.append_text(event.text)
        elif isinstance(event, ReasoningDelta):
            self.state.append_reasoning(event.text)
        elif isinstance(event, GenerationCompleted):
            if not self.state.rendered_text and not self.state.text_buffer:
                self.state.append_text(_response_text(event))
            return self._flush(now, completed=True)
        else:
            return None

        if now - self.state.last_flush_at >= self.interval_seconds:
            return self._flush(now)
        return None

    def flush(self) -> RenderBatch:
        return self._flush(self._clock())

    def finish_cancelled(self) -> RenderBatch:
        return self._flush(self._clock(), cancelled=True)

    def _flush(
        self,
        now: float,
        *,
        completed: bool = False,
        cancelled: bool = False,
    ) -> RenderBatch:
        text, reasoning = self.state.flush(now)
        return RenderBatch(
            text=text,
            reasoning=reasoning,
            completed=completed,
            cancelled=cancelled,
        )


__all__ = ["RenderBatch", "STREAM_RENDER_INTERVAL_SECONDS", "StreamRenderer"]
