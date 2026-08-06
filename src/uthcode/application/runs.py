"""Application-owned in-memory Agent Run and Turn handles."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from uthcode.core.agent import AgentTurnExecution, RunSnapshot, RunState, RunStatus, TurnResult
from uthcode.core.agent_events import AgentEvent
from uthcode.core.provider import CancellationToken

if TYPE_CHECKING:
    from .generation import UthCodeApplication


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
        """Synchronously reserve the Run and return a lazily executed Turn."""

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
        handle = TurnHandle(self, execution, cancellation)
        self._active_turn = handle
        execution.add_completion_listener(handle._on_completed)
        return handle

    def snapshot(self) -> RunSnapshot:
        """Return a safe snapshot without exposing conversation content."""

        if self._active_turn is not None:
            return self._active_turn._snapshot()
        return RunSnapshot.from_state(self._state)

    def _complete_turn(self, handle: TurnHandle) -> None:
        if self._active_turn is not handle:
            return
        self._state = handle._execution.state
        self._active_turn = None


class TurnHandle:
    """A public, content-safe wrapper around one Core Turn execution."""

    __slots__ = (
        "_run",
        "_execution",
        "_cancellation",
        "_events_started",
        "_result_value",
    )

    def __init__(
        self,
        run: AgentRun,
        execution: AgentTurnExecution,
        cancellation: CancellationToken,
    ) -> None:
        self._run = run
        self._execution = execution
        self._cancellation = cancellation
        self._events_started = False
        self._result_value: TurnResult | None = None

    def events(self) -> AsyncIterator[AgentEvent]:
        """Claim the single event consumer and return its async iterator."""

        if self._events_started:
            raise RuntimeError("TurnHandle.events() can only be consumed once")
        self._events_started = True
        # The Core execution is deliberately lazy because start_turn() may be
        # called outside an event loop.  When events() is invoked in an async
        # context, start it immediately; the iterator remains the sole event
        # consumer.
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            self._execution.start()
        return self._events()

    async def _events(self) -> AsyncIterator[AgentEvent]:
        async for event in self._execution.events():
            yield event
        await self._wait_result()

    def cancel(self) -> bool:
        """Request cancellation once; terminal Turns cannot be cancelled."""

        if self._result_value is not None or self._execution.state.status is not RunStatus.RUNNING:
            return False
        return self._cancellation.cancel()

    def cancelled(self) -> bool:
        return self._cancellation.cancelled

    async def result(self) -> TurnResult:
        """Wait for and return the same immutable result on every call."""

        return await self._wait_result()

    def _snapshot(self) -> RunSnapshot:
        return self._execution.snapshot()

    def _on_completed(self, result: TurnResult) -> None:
        if self._result_value is None:
            self._result_value = result
        self._run._complete_turn(self)

    async def _wait_result(self) -> TurnResult:
        if self._result_value is None:
            result = await self._execution.result()
            self._on_completed(result)
        return self._result_value


__all__ = ["AgentRun", "TurnHandle"]
