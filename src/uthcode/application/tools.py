"""Application-owned access to the Core Tool runtime."""

from __future__ import annotations

from collections.abc import Sequence

from uthcode.core.provider import (
    CancellationToken,
    ToolCallPart,
    ToolDefinition,
    ToolResultPart,
)
from uthcode.core.tool import Tool, ToolExecutor, ToolRegistry


class ApplicationToolService:
    """Hide Registry and Executor details behind the Application boundary."""

    __slots__ = ("_executor", "_registry")

    def __init__(self, tools: Sequence[Tool]) -> None:
        self._registry = ToolRegistry(tuple(tools))
        self._executor = ToolExecutor(self._registry)

    def definitions(self) -> tuple[ToolDefinition, ...]:
        """Return the immutable, registration-ordered public definitions."""

        return self._registry.definitions()

    async def execute_calls(
        self,
        calls: Sequence[ToolCallPart],
        *,
        cancellation: CancellationToken | None = None,
    ) -> tuple[ToolResultPart, ...]:
        """Execute one batch with a caller token or a fresh local token."""

        if cancellation is None:
            cancellation = CancellationToken()
        elif not isinstance(cancellation, CancellationToken):
            raise TypeError("cancellation must be a CancellationToken or None")
        return await self._executor.execute_batch(
            tuple(calls),
            cancellation=cancellation,
        )


__all__ = ["ApplicationToolService"]
