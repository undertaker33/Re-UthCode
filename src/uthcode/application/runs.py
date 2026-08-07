"""Application-owned in-memory Agent Runs and Turn coordination."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from uthcode.core.agent import (
    AgentTurnExecution,
    RunSnapshot,
    RunState,
    RunStatus,
    TurnResult,
)
from uthcode.core.agent_events import AgentEvent, TurnPaused, TurnResumed
from uthcode.core.interaction import (
    PauseRequest,
    PauseResponse,
    RetryProviderResponse,
    ResumeTurnResponse,
    UserInputResponse,
)
from uthcode.core.provider import CancellationToken

if TYPE_CHECKING:
    from .generation import UthCodeApplication


_END = object()
_CANCELLED = object()


def _new_identifier(value: str | None, field_name: str) -> str:
    if value is None:
        return uuid.uuid4().hex
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string or None")
    if not value:
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


class AgentRun:
    """One private, in-memory conversation with at most one active Turn."""

    __slots__ = ("_application", "_state", "_active_turn")

    def __init__(self, application: UthCodeApplication, *, run_id: str | None) -> None:
        self._application = application
        self._state = RunState.initial(_new_identifier(run_id, "run_id"))
        self._active_turn: TurnHandle | None = None

    def start_turn(self, user_input: str) -> TurnHandle:
        """Synchronously reserve the Run and return a lazily driven Turn."""

        if not isinstance(user_input, str):
            raise TypeError("user_input must be a string")
        if not user_input.strip():
            raise ValueError("user_input must be a non-empty string")
        if self._active_turn is not None:
            raise RuntimeError("AgentRun already has an active Turn")

        turn_id = uuid.uuid4().hex
        cancellation = CancellationToken()
        execution = self._application._start_agent_turn(
            self._state,
            user_input,
            turn_id=turn_id,
            cancellation=cancellation,
        )
        self._state = execution.state
        driver = _TurnDriver(self, execution)
        handle = TurnHandle(self, driver)
        driver.attach(handle)
        self._active_turn = handle
        return handle

    def snapshot(self) -> RunSnapshot:
        """Return a safe snapshot without exposing conversation content."""

        if self._active_turn is not None:
            return self._active_turn._snapshot()
        return RunSnapshot.from_state(self._state)

    def _complete_turn(self, handle: TurnHandle) -> None:
        if self._active_turn is not handle:
            return
        self._state = handle._driver.execution.state
        self._active_turn = None


class _TurnDriver:
    """Private Application driver for one sequence of Core segments."""

    __slots__ = (
        "_run",
        "execution",
        "_queue",
        "_result_future",
        "_result_value",
        "_task",
        "_segment_signal",
        "_response_waiter",
        "_pending_pause",
        "_pause_requested",
        "_events_claimed",
        "_end_enqueued",
        "_handle",
    )

    def __init__(self, run: AgentRun, execution: AgentTurnExecution) -> None:
        self._run = run
        self.execution = execution
        self._queue: asyncio.Queue[object] | None = None
        self._result_future: asyncio.Future[TurnResult] | None = None
        self._result_value: TurnResult | None = None
        self._task: asyncio.Task[None] | None = None
        self._segment_signal: CancellationToken | None = None
        self._response_waiter: asyncio.Future[object] | None = None
        self._pending_pause: PauseRequest | None = None
        self._pause_requested = False
        self._events_claimed = False
        self._end_enqueued = False
        self._handle: TurnHandle | None = None

    def attach(self, handle: TurnHandle) -> None:
        if self._handle is not None:
            raise RuntimeError("Turn driver is already attached")
        self._handle = handle

    @property
    def pending_pause(self) -> PauseRequest | None:
        return self._pending_pause

    @property
    def result_value(self) -> TurnResult | None:
        return self._result_value

    def ensure_started(self) -> None:
        if self._task is not None:
            return
        if self._result_future is not None and self._result_future.done():
            return
        loop = asyncio.get_running_loop()
        if self._queue is None:
            self._queue = asyncio.Queue()
        if self._result_future is None:
            self._result_future = loop.create_future()
        self._task = loop.create_task(self._drive())

    def request_pause(self) -> bool:
        if self._result_value is not None or self.execution.state.status is not RunStatus.RUNNING:
            return False
        if self._pending_pause is not None or self._pause_requested:
            return False
        self._pause_requested = True
        self.ensure_started_if_possible()
        if self._segment_signal is not None:
            self._segment_signal.cancel()
        return True

    def request_cancel(self) -> bool:
        if self._result_value is not None or self.execution.state.status is not RunStatus.RUNNING:
            return False
        changed = self.execution.cancel()
        if not changed:
            return False
        self._pause_requested = False
        self._pending_pause = None
        if self._segment_signal is not None:
            self._segment_signal.cancel()
        waiter = self._response_waiter
        if waiter is not None and not waiter.done():
            waiter.set_result(_CANCELLED)
        self.ensure_started_if_possible()
        return True

    def ensure_started_if_possible(self) -> None:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return
        self.ensure_started()

    async def result(self) -> TurnResult:
        self.ensure_started()
        assert self._result_future is not None
        return await asyncio.shield(self._result_future)

    async def events(self) -> AsyncIterator[AgentEvent]:
        self.ensure_started()
        assert self._queue is not None
        while True:
            item = await self._queue.get()
            if item is _END:
                await self.result()
                return
            if not isinstance(item, AgentEvent):
                raise RuntimeError("Application driver produced an invalid event")
            yield item

    def _emit_event(self, event: AgentEvent) -> None:
        """Publish one Core event while preserving the single live stream."""

        assert self._queue is not None
        if isinstance(event, TurnPaused):
            if self._pending_pause is not None or self._response_waiter is not None:
                raise RuntimeError("Application received more than one pending pause")
            self._pending_pause = event.pause
            self._response_waiter = asyncio.get_running_loop().create_future()
        self._queue.put_nowait(event)

    async def _drive(self) -> None:
        response: PauseResponse | None = None
        try:
            while True:
                signal = CancellationToken()
                self._segment_signal = signal
                if self._pause_requested:
                    self._pause_requested = False
                    signal.cancel()
                segment = await self.execution.run_segment(
                    pause_signal=signal,
                    response=response,
                    event_sink=self._emit_event,
                )
                response = None
                if self._segment_signal is signal:
                    self._segment_signal = None

                if segment.paused:
                    # The requested boundary has now been reached.  The
                    # request must not be carried into the resumed segment.
                    self._pause_requested = False
                    if self.execution.cancelled():
                        self._clear_pause_coordination()
                        continue
                    pending = self._pending_pause
                    waiter = self._response_waiter
                    if pending is None or waiter is None:
                        raise RuntimeError("paused boundary has no Application response waiter")
                    response_value = await asyncio.shield(waiter)
                    self._response_waiter = None
                    self._pending_pause = None
                    if response_value is _CANCELLED or self.execution.cancelled():
                        response = None
                        continue
                    if not isinstance(
                        response_value,
                        (RetryProviderResponse, ResumeTurnResponse, UserInputResponse),
                    ):
                        raise RuntimeError("Application waiter returned an invalid response")
                    response = response_value
                    await asyncio.sleep(0)
                    if self.execution.cancelled():
                        response = None
                        continue
                    self._queue.put_nowait(
                        TurnResumed(
                            self.execution.state.run_id,
                            self.execution.state.turn_id,
                            pending.pause_id,
                            pending.kind,
                        )
                    )
                    continue

                if not segment.terminal:
                    raise RuntimeError("Core segment did not end at a boundary")
                result = segment.result
                if result is None:
                    raise RuntimeError("terminal segment has no result")
                self._finish_terminal(result)
                return
        except asyncio.CancelledError:
            self.execution.cancel()
            self._clear_pause_coordination()
            try:
                segment = await self.execution.run_segment(
                    pause_signal=CancellationToken(),
                    event_sink=self._emit_event,
                )
            except asyncio.CancelledError:
                segment = self.execution.cancelled_segment(event_sink=self._emit_event)
            if segment.terminal and segment.result is not None:
                self._finish_terminal(segment.result)
            else:
                self._finish_unexpected()
        except Exception:
            self._finish_unexpected()
        finally:
            if self._task is asyncio.current_task():
                self._task = None

    def _clear_pause_coordination(self) -> None:
        self._pending_pause = None
        waiter = self._response_waiter
        self._response_waiter = None
        if waiter is not None and not waiter.done():
            waiter.set_result(_CANCELLED)
        self._segment_signal = None
        self._pause_requested = False

    def _close_event_stream(self) -> None:
        if self._queue is None or self._end_enqueued:
            return
        self._end_enqueued = True
        self._queue.put_nowait(_END)

    def _finish_terminal(self, result: TurnResult) -> None:
        if self._result_value is None:
            self._result_value = result
            if self._result_future is None:
                self._result_future = asyncio.get_running_loop().create_future()
            if not self._result_future.done():
                self._result_future.set_result(result)
            handle = self._handle
            if handle is not None:
                self._run._complete_turn(handle)
        self._clear_pause_coordination()
        self._close_event_stream()

    def _finish_unexpected(self) -> None:
        try:
            segment = self.execution.fail_internal(event_sink=self._emit_event)
        except Exception:
            segment = self.execution.fail_internal()
            for event in segment.events:
                self._emit_event(event)
        if segment.result is not None:
            self._finish_terminal(segment.result)
        else:
            self._clear_pause_coordination()
            self._close_event_stream()


class TurnHandle:
    """Public, content-safe control for one Application-owned Turn."""

    __slots__ = ("_run", "_driver")

    def __init__(self, run: AgentRun, driver: _TurnDriver) -> None:
        self._run = run
        self._driver = driver

    def events(self) -> AsyncIterator[AgentEvent]:
        """Claim the single event consumer and return its async iterator."""

        if self._driver._events_claimed:
            raise RuntimeError("TurnHandle.events() can only be consumed once")
        self._driver._events_claimed = True
        self._driver.ensure_started_if_possible()
        return self._driver.events()

    def pause(self) -> bool:
        """Request a cooperative pause at the next safe boundary."""

        return self._driver.request_pause()

    @property
    def pending_pause(self) -> PauseRequest | None:
        return self._driver.pending_pause

    @property
    def paused(self) -> bool:
        return self.pending_pause is not None

    def resume(self, response: PauseResponse) -> bool:
        """Submit exactly one typed response for the current pause."""

        pending = self._driver.pending_pause
        if pending is None:
            return False
        if self._driver.execution.cancelled():
            return False
        pending.validate_response(response)
        waiter = self._driver._response_waiter
        if waiter is None or waiter.done():
            return False
        waiter.set_result(response)
        return True

    def cancel(self) -> bool:
        """Cancel the Turn; cancellation wins over a pending response."""

        return self._driver.request_cancel()

    def cancelled(self) -> bool:
        return self._driver.execution.cancelled()

    def _snapshot(self) -> RunSnapshot:
        return self._driver.execution.snapshot()

    async def result(self) -> TurnResult:
        """Wait for and return the same terminal result on every call."""

        return await self._driver.result()


__all__ = ["AgentRun", "TurnHandle"]
