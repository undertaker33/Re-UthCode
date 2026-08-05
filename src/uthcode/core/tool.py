"""Provider-independent tool contracts and sequential execution semantics."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

from .provider import (
    CancellationToken,
    GenerationCancelled,
    JsonPayload,
    ToolCallPart,
    ToolDefinition,
    ToolResultPart,
)


_DEFAULT_MAX_RESULT_CHARS = 10_000
_TRUNCATION_SUFFIX_TEMPLATE = "\n[Output truncated to {limit} characters]"


@dataclass(frozen=True, slots=True)
class ToolExecutionResult:
    """The small result returned by one Core Tool implementation."""

    content: str
    is_error: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.content, str):
            raise TypeError("content must be a string")
        if not isinstance(self.is_error, bool):
            raise TypeError("is_error must be a boolean")


@runtime_checkable
class Tool(Protocol):
    """The only execution contract required from an Integration Tool."""

    @property
    def definition(self) -> ToolDefinition:
        ...

    async def execute(
        self,
        arguments: JsonPayload,
        *,
        cancellation: CancellationToken,
    ) -> ToolExecutionResult:
        ...


class ToolRegistry:
    """An ordered registry whose names and schemas are validated at registration."""

    def __init__(self, tools: Sequence[Tool] | None = None) -> None:
        self._tools: dict[str, Tool] = {}
        self._definitions: dict[str, ToolDefinition] = {}
        self._validators: dict[str, Draft202012Validator] = {}
        if tools is not None:
            for tool in tools:
                self.register(tool)

    def register(self, tool: Tool) -> None:
        if not isinstance(tool, Tool):
            raise TypeError("tool must implement the Tool protocol")

        definition = tool.definition
        if not isinstance(definition, ToolDefinition):
            raise TypeError("tool.definition must be a ToolDefinition")
        name = definition.name
        if name in self._tools:
            raise ValueError(f"tool name already registered: {name}")

        schema = _to_json_data(definition.parameters)
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError:
            raise ValueError(f"invalid JSON Schema for tool: {name}") from None

        validator = Draft202012Validator(schema)
        self._tools[name] = tool
        self._definitions[name] = definition
        self._validators[name] = validator

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def list_tools(self) -> tuple[Tool, ...]:
        return tuple(self._tools.values())

    def definitions(self) -> tuple[ToolDefinition, ...]:
        return tuple(self._definitions.values())

    def _validator_for(self, name: str) -> Draft202012Validator | None:
        return self._validators.get(name)


class ToolExecutor:
    """Validate and execute ToolCalls one at a time in strict FIFO order."""

    def __init__(
        self,
        registry: ToolRegistry,
        *,
        max_result_chars: int = _DEFAULT_MAX_RESULT_CHARS,
    ) -> None:
        if isinstance(max_result_chars, bool) or not isinstance(max_result_chars, int):
            raise TypeError("max_result_chars must be an integer")
        if max_result_chars <= 0:
            raise ValueError("max_result_chars must be positive")
        self._registry = registry
        self._max_result_chars = max_result_chars

    async def execute_call(
        self,
        call: ToolCallPart,
        *,
        cancellation: CancellationToken,
    ) -> ToolResultPart:
        _require_tool_call(call)
        if cancellation.cancelled:
            return self._cancelled(call)

        tool = self._registry.get(call.name)
        if tool is None:
            return self._error(call, f"Error: unknown tool: {call.name}")

        validator = self._registry._validator_for(call.name)
        if validator is None:  # pragma: no cover - registry keeps the maps aligned.
            return self._error(call, f"Error: unknown tool: {call.name}")

        try:
            validator.validate(_to_json_data(call.arguments))
        except ValidationError as exc:
            return self._error(call, _invalid_arguments_message(call.name, exc))

        if cancellation.cancelled:
            return self._cancelled(call)

        try:
            result = await tool.execute(call.arguments, cancellation=cancellation)
        except GenerationCancelled:
            return self._cancelled(call)
        except asyncio.CancelledError:
            if cancellation.cancelled:
                return self._cancelled(call)
            raise
        except Exception:
            return self._error(call, f"Error: tool execution failed for {call.name}")

        if not isinstance(result, ToolExecutionResult):
            return self._error(call, "Error: tool execution returned an invalid result")
        return ToolResultPart(
            tool_call_id=call.tool_call_id,
            content=self._truncate(result.content),
            is_error=result.is_error,
        )

    async def execute_batch(
        self,
        calls: Sequence[ToolCallPart],
        *,
        cancellation: CancellationToken,
    ) -> tuple[ToolResultPart, ...]:
        call_values = tuple(calls)
        for call in call_values:
            _require_tool_call(call)

        results: list[ToolResultPart] = []
        for call in call_values:
            if cancellation.cancelled:
                results.append(self._cancelled(call))
                continue
            results.append(await self.execute_call(call, cancellation=cancellation))
        return tuple(results)

    def _cancelled(self, call: ToolCallPart) -> ToolResultPart:
        return self._error(call, "Error: tool call cancelled")

    def _error(self, call: ToolCallPart, content: str) -> ToolResultPart:
        return ToolResultPart(
            tool_call_id=call.tool_call_id,
            content=self._truncate(content),
            is_error=True,
        )

    def _truncate(self, content: str) -> str:
        if len(content) <= self._max_result_chars:
            return content
        suffix = _TRUNCATION_SUFFIX_TEMPLATE.format(limit=self._max_result_chars)
        prefix_length = max(0, self._max_result_chars - len(suffix))
        if prefix_length == 0:
            return suffix[: self._max_result_chars]
        return content[:prefix_length] + suffix


def _require_tool_call(call: ToolCallPart) -> None:
    if not isinstance(call, ToolCallPart):
        raise TypeError("call must be a ToolCallPart")


def _to_json_data(value: object) -> object:
    """Convert immutable Core JSON values to ordinary data for jsonschema."""

    if isinstance(value, Mapping):
        return {key: _to_json_data(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_to_json_data(item) for item in value]
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


def _invalid_arguments_message(name: str, error: ValidationError) -> str:
    path = ".".join(str(part) for part in error.absolute_path) or "<root>"
    keyword = str(error.validator or "schema")
    details = [f"path={path}", f"keyword={keyword}"]
    if keyword == "required" and isinstance(error.validator_value, list):
        missing = ",".join(str(item) for item in error.validator_value)
        details.append(f"required={missing}")
    return f"Error: invalid arguments for {name} ({'; '.join(details)})"


__all__ = [
    "Tool",
    "ToolExecutionResult",
    "ToolExecutor",
    "ToolRegistry",
]
