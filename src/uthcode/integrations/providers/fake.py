"""Scriptable, offline ProviderPort implementation for tests and embedding."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Iterable

from uthcode.core.provider import (
    CancellationToken,
    ContextCountEstimate,
    GenerationCancelled,
    GenerationRequest,
    ModelLimits,
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
        model_limits: ModelLimits | None = None,
        input_token_counter: Callable[
            [GenerationRequest], ContextCountEstimate | int | None
        ]
        | None = None,
    ) -> None:
        self._identity = identity or ProviderIdentity("fake", "script", "fake-model")
        if delay < 0:
            raise ValueError("delay must be non-negative")
        if error is not None and not isinstance(error, ProviderError):
            raise TypeError("error must be a ProviderError or None")
        self._events = tuple(events)
        self._delay = delay
        self._error = error
        if model_limits is not None and not isinstance(model_limits, ModelLimits):
            raise TypeError("model_limits must be ModelLimits or None")
        self._model_limits = model_limits
        if input_token_counter is not None and not callable(input_token_counter):
            raise TypeError("input_token_counter must be callable or None")
        self._input_token_counter = input_token_counter
        self.requests: list[GenerationRequest] = []

    @property
    def identity(self) -> ProviderIdentity:
        return self._identity

    @property
    def recorded_requests(self) -> tuple[GenerationRequest, ...]:
        return tuple(self.requests)

    def resolve_model_limits(self, model: str) -> ModelLimits | None:
        if not isinstance(model, str) or not model:
            raise ValueError("model must be a non-empty string")
        return self._model_limits

    def count_input_tokens(
        self,
        request: GenerationRequest,
    ) -> ContextCountEstimate | int | None:
        if self._input_token_counter is None:
            return None
        value = self._input_token_counter(request)
        if value is not None and not isinstance(value, (ContextCountEstimate, int)):
            raise TypeError("input_token_counter must return a ContextCountEstimate, int, or None")
        return value

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
