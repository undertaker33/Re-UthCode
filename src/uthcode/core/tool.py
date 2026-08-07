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
from .permission import Effect, PermissionAction, ResourceScope


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
    """The only execution contract required from an Integration Tool.

    Permission-aware concrete tools additionally expose a synchronous
    ``preflight(arguments)`` hook.  The hook is intentionally optional at the
    structural Core Tool boundary so existing embedded tools remain valid;
    tools without it receive a conservative UNKNOWN Action.
    """

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


@runtime_checkable
class ToolPreflight(Protocol):
    """The no-side-effect preparation implemented by trusted tools."""

    def preflight(self, arguments: JsonPayload) -> ToolPreparation:
        ...


@dataclass(frozen=True, slots=True)
class ToolPreparation:
    """Trusted Action plus the exact immutable payload reserved for execute."""

    action: PermissionAction
    execution_arguments: JsonPayload

    def __post_init__(self) -> None:
        if not isinstance(self.action, PermissionAction):
            raise TypeError("action must be a PermissionAction")
        if not isinstance(self.execution_arguments, JsonPayload):
            object.__setattr__(
                self,
                "execution_arguments",
                JsonPayload(self.execution_arguments),
            )


@dataclass(frozen=True, slots=True)
class PreparedToolCall:
    """A registered, schema-validated, preflighted call before execution."""

    call: ToolCallPart
    tool: Tool
    action: PermissionAction
    execution_arguments: JsonPayload

    def __post_init__(self) -> None:
        if not isinstance(self.call, ToolCallPart):
            raise TypeError("call must be a ToolCallPart")
        if not isinstance(self.tool, Tool):
            raise TypeError("tool must implement the Tool protocol")
        if not isinstance(self.action, PermissionAction):
            raise TypeError("action must be a PermissionAction")
        if not isinstance(self.execution_arguments, JsonPayload):
            object.__setattr__(
                self,
                "execution_arguments",
                JsonPayload(self.execution_arguments),
            )


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
        prepared = self.prepare_call(call, cancellation=cancellation)
        if isinstance(prepared, ToolResultPart):
            return prepared
        return await self.execute_prepared(prepared, cancellation=cancellation)

    def prepare_call(
        self,
        call: ToolCallPart,
        *,
        cancellation: CancellationToken | None = None,
    ) -> PreparedToolCall | ToolResultPart:
        """Validate and preflight one call without invoking ``Tool.execute``.

        A ``ToolResultPart`` is returned for unknown, invalid, cancelled, or
        otherwise unpreparable calls so callers can preserve the existing
        FIFO/error contract without entering Permission evaluation.
        """

        _require_tool_call(call)
        if cancellation is not None and cancellation.cancelled:
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

        if cancellation is not None and cancellation.cancelled:
            return self._cancelled(call)

        try:
            preparation = _preflight_tool(tool, call)
        except (TypeError, ValueError) as exc:
            message = str(exc) or f"Error: tool preflight failed for {call.name}"
            if not message.startswith("Error:"):
                message = f"Error: tool preflight failed for {call.name}: {message}"
            return self._error(call, message)
        except Exception:
            return self._error(call, f"Error: tool preflight failed for {call.name}")

        return PreparedToolCall(
            call=call,
            tool=tool,
            action=preparation.action,
            execution_arguments=preparation.execution_arguments,
        )

    async def execute_prepared(
        self,
        prepared: PreparedToolCall,
        *,
        cancellation: CancellationToken,
    ) -> ToolResultPart:
        """Execute one already-prepared call without validation or preflight."""

        if not isinstance(prepared, PreparedToolCall):
            raise TypeError("prepared must be a PreparedToolCall")
        if not isinstance(cancellation, CancellationToken):
            raise TypeError("cancellation must be a CancellationToken")
        call = prepared.call
        tool = prepared.tool
        if cancellation.cancelled:
            return self._cancelled(call)
        try:
            result = await tool.execute(
                prepared.execution_arguments,
                cancellation=cancellation,
            )
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


def _preflight_tool(tool: Tool, call: ToolCallPart) -> ToolPreparation:
    preflight = getattr(tool, "preflight", None)
    if preflight is None:
        return ToolPreparation(
            action=PermissionAction(
                tool=call.name,
                action="execute",
                effect=Effect.UNKNOWN,
                resource=None,
                scope=ResourceScope.UNKNOWN,
            ),
            execution_arguments=call.arguments,
        )
    preparation = preflight(call.arguments)
    if not isinstance(preparation, ToolPreparation):
        raise TypeError("tool preflight must return a ToolPreparation")
    return preparation


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
    "PreparedToolCall",
    "Tool",
    "ToolExecutionResult",
    "ToolExecutor",
    "ToolPreflight",
    "ToolPreparation",
    "ToolRegistry",
]
