"""Scriptable, offline ProviderPort implementation for tests and embedding."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterable

from uthcode.core.provider import (
    CancellationToken,
    GenerationCancelled,
    GenerationRequest,
    ProviderError,
    ProviderEvent,
    ProviderIdentity,
    ProviderPort,
)


class FakeProvider:
    """Replay a deterministic event script without opening a network client."""

    def __init__(
        self,
        identity: ProviderIdentity | None = None,
        events: Iterable[ProviderEvent] = (),
        *,
        delay: float = 0.0,
        error: ProviderError | None = None,
    ) -> None:
        self._identity = identity or ProviderIdentity("fake", "script", "fake-model")
        if delay < 0:
            raise ValueError("delay must be non-negative")
        if error is not None and not isinstance(error, ProviderError):
            raise TypeError("error must be a ProviderError or None")
        self._events = tuple(events)
        self._delay = delay
        self._error = error
        self.requests: list[GenerationRequest] = []

    @property
    def identity(self) -> ProviderIdentity:
        return self._identity

    @property
    def recorded_requests(self) -> tuple[GenerationRequest, ...]:
        return tuple(self.requests)

    async def _wait_for_delay(self, cancellation: CancellationToken) -> None:
        cancellation.raise_if_cancelled()
        if self._delay == 0:
            return

        sleep_task = asyncio.create_task(asyncio.sleep(self._delay))
        cancel_task = asyncio.create_task(cancellation.wait())
        try:
            done, _ = await asyncio.wait(
                (sleep_task, cancel_task),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if cancel_task in done:
                raise GenerationCancelled()
        finally:
            for task in (sleep_task, cancel_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(sleep_task, cancel_task, return_exceptions=True)

    async def stream(
        self,
        request: GenerationRequest,
        *,
        cancellation: CancellationToken,
    ) -> AsyncIterator[ProviderEvent]:
        self.requests.append(request)
        cancellation.raise_if_cancelled()

        for event in self._events:
            await self._wait_for_delay(cancellation)
            cancellation.raise_if_cancelled()
            yield event

        if self._error is not None:
            raise self._error
