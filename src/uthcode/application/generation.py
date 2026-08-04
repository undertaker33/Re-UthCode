"""Headless generation use case built only on the Core Provider Port."""

from __future__ import annotations

from collections.abc import AsyncIterator

from uthcode.core.provider import (
    CancellationToken,
    GenerationCompleted,
    GenerationRequest,
    InvalidProviderResponseError,
    ProviderEvent,
    ProviderPort,
)


class UthCodeApplication:
    """The smallest headless application boundary for provider generation."""

    def __init__(self, provider: ProviderPort) -> None:
        self._provider = provider

    @property
    def provider(self) -> ProviderPort:
        return self._provider

    async def stream_generation(
        self,
        request: GenerationRequest,
        *,
        cancellation: CancellationToken | None = None,
    ) -> AsyncIterator[ProviderEvent]:
        """Yield one provider stream and enforce its terminal-event contract."""

        token = cancellation or CancellationToken()
        terminal: GenerationCompleted | None = None
        stream = self._provider.stream(request, cancellation=token)
        try:
            async for event in stream:
                if terminal is not None:
                    raise InvalidProviderResponseError(
                        "Provider emitted an event after GenerationCompleted"
                    )
                if isinstance(event, GenerationCompleted):
                    # A terminal event is only trustworthy after the provider
                    # iterator reaches EOF. Hold it back until then so callers
                    # can never observe a success that is later invalidated.
                    terminal = event
                    continue
                yield event
        finally:
            close = getattr(stream, "aclose", None)
            if close is not None:
                await close()

        if terminal is None:
            raise InvalidProviderResponseError(
                "Provider stream ended without GenerationCompleted"
            )
        yield terminal
