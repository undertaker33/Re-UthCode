"""Provider-independent tool contracts and sequential execution semantics."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Protocol, TypeAlias, runtime_checkable

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


class ToolExecutionStatus(str, Enum):
    """The fact known about the Tool execution itself."""

    SUCCEEDED = "succeeded"
    SUCCESS = "succeeded"
    FAILED = "failed"
    ERROR = "failed"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


class ToolResultPersistenceStatus(str, Enum):
    """The separate materialization fact for one executed Tool result."""

    INLINE = "inline"
    EXTERNALIZED = "externalized"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ToolExecutionOutcome:
    """Full, provider-independent outcome returned by Core execution.

    Core deliberately keeps the complete content.  Resource policy belongs to
    Application/Integration materialization and therefore cannot silently turn
    a successfully executed side effect into an unexecuted call.
    """

    tool_call_id: str
    tool_name: str
    content: str
    is_error: bool
    status: ToolExecutionStatus

    def __post_init__(self) -> None:
        if not isinstance(self.tool_call_id, str) or not self.tool_call_id:
            raise ValueError("tool_call_id must be a non-empty string")
        if not isinstance(self.tool_name, str) or not self.tool_name:
            raise ValueError("tool_name must be a non-empty string")
        if not isinstance(self.content, str):
            raise TypeError("content must be a string")
        if not isinstance(self.is_error, bool):
            raise TypeError("is_error must be a boolean")
        if not isinstance(self.status, ToolExecutionStatus):
            try:
                object.__setattr__(self, "status", ToolExecutionStatus(self.status))
            except (TypeError, ValueError) as exc:
                raise ValueError("status must be a ToolExecutionStatus") from exc

    @property
    def result(self) -> ToolResultPart:
        return ToolResultPart(self.tool_call_id, self.content, self.is_error)


@dataclass(frozen=True, slots=True)
class ToolResultMaterialization:
    """The result visible to the next model request plus persistence facts."""

    execution: ToolExecutionOutcome
    result: ToolResultPart
    persistence_status: ToolResultPersistenceStatus
    reference: str | None = None
    size_bytes: int = 0
    sha256: str | None = None
    error_code: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.execution, ToolExecutionOutcome):
            raise TypeError("execution must be a ToolExecutionOutcome")
        if not isinstance(self.result, ToolResultPart):
            raise TypeError("result must be a ToolResultPart")
        if self.result.tool_call_id != self.execution.tool_call_id:
            raise ValueError("materialized result must preserve the Tool call id")
        if not isinstance(self.persistence_status, ToolResultPersistenceStatus):
            try:
                object.__setattr__(
                    self,
                    "persistence_status",
                    ToolResultPersistenceStatus(self.persistence_status),
                )
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    "persistence_status must be a ToolResultPersistenceStatus"
                ) from exc
        if isinstance(self.size_bytes, bool) or not isinstance(self.size_bytes, int):
            raise TypeError("size_bytes must be an integer")
        if self.size_bytes < 0:
            raise ValueError("size_bytes must be non-negative")
        if self.reference is not None and (
            not isinstance(self.reference, str) or not self.reference
        ):
            raise ValueError("reference must be a non-empty string or None")
        if self.sha256 is not None and (
            not isinstance(self.sha256, str) or not self.sha256
        ):
            raise ValueError("sha256 must be a non-empty string or None")
        if self.error_code is not None and (
            not isinstance(self.error_code, str) or not self.error_code
        ):
            raise ValueError("error_code must be a non-empty string or None")


ToolResultMaterializer: TypeAlias = Callable[
    [ToolExecutionOutcome],
    ToolResultMaterialization | ToolResultPart | Awaitable[ToolResultMaterialization | ToolResultPart],
]


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


class ToolPlanningAccess(str, Enum):
    """Whether an ordinary Tool may appear in the PLAN provider view."""

    HIDDEN = "hidden"
    READ_ONLY = "read_only"


@runtime_checkable
class ToolPlanningMetadata(Protocol):
    """Optional Core-only metadata; undeclared Tools stay hidden in PLAN."""

    @property
    def planning_access(self) -> ToolPlanningAccess:
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
        self._planning_access: dict[str, ToolPlanningAccess] = {}
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
        planning_access = _planning_access_for(tool)
        self._tools[name] = tool
        self._definitions[name] = definition
        self._planning_access[name] = planning_access
        self._validators[name] = validator

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def list_tools(self) -> tuple[Tool, ...]:
        return tuple(self._tools.values())

    def definitions(self) -> tuple[ToolDefinition, ...]:
        return tuple(self._definitions.values())

    def planning_access_for(self, name: str) -> ToolPlanningAccess | None:
        return self._planning_access.get(name)

    def plan_definitions(self) -> tuple[ToolDefinition, ...]:
        """Return the stable PLAN-visible subset without changing wire schemas."""

        return tuple(
            definition
            for name, definition in self._definitions.items()
            if self._planning_access[name] is ToolPlanningAccess.READ_ONLY
        )

    def _validator_for(self, name: str) -> Draft202012Validator | None:
        return self._validators.get(name)


class ToolExecutor:
    """Validate and execute ToolCalls one at a time in strict FIFO order."""

    def __init__(
        self,
        registry: ToolRegistry,
    ) -> None:
        if not isinstance(registry, ToolRegistry):
            raise TypeError("registry must be a ToolRegistry")
        self._registry = registry

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

        return (await self.execute_prepared_outcome(prepared, cancellation=cancellation)).result

    async def execute_prepared_outcome(
        self,
        prepared: PreparedToolCall,
        *,
        cancellation: CancellationToken,
    ) -> ToolExecutionOutcome:
        """Execute one call and return the complete execution fact.

        This method performs no resource-policy materialization and never
        retries a Tool.  ``execute_prepared`` remains as a small compatibility
        convenience for Core callers that only need the inline result object.
        """

        if not isinstance(prepared, PreparedToolCall):
            raise TypeError("prepared must be a PreparedToolCall")
        if not isinstance(cancellation, CancellationToken):
            raise TypeError("cancellation must be a CancellationToken")
        call = prepared.call
        tool = prepared.tool
        if cancellation.cancelled:
            return ToolExecutionOutcome(
                call.tool_call_id,
                call.name,
                "Error: tool call cancelled",
                True,
                ToolExecutionStatus.CANCELLED,
            )
        try:
            result = await tool.execute(
                prepared.execution_arguments,
                cancellation=cancellation,
            )
        except GenerationCancelled:
            return ToolExecutionOutcome(
                call.tool_call_id,
                call.name,
                "Error: tool call cancelled",
                True,
                ToolExecutionStatus.CANCELLED,
            )
        except asyncio.CancelledError:
            if cancellation.cancelled:
                return ToolExecutionOutcome(
                    call.tool_call_id,
                    call.name,
                    "Error: tool call cancelled",
                    True,
                    ToolExecutionStatus.CANCELLED,
                )
            raise
        except Exception:
            return ToolExecutionOutcome(
                call.tool_call_id,
                call.name,
                f"Error: tool execution failed for {call.name}",
                True,
                ToolExecutionStatus.UNKNOWN,
            )

        if not isinstance(result, ToolExecutionResult):
            return ToolExecutionOutcome(
                call.tool_call_id,
                call.name,
                "Error: tool execution returned an invalid result",
                True,
                ToolExecutionStatus.UNKNOWN,
            )
        return ToolExecutionOutcome(
            call.tool_call_id,
            call.name,
            result.content,
            result.is_error,
            ToolExecutionStatus.FAILED if result.is_error else ToolExecutionStatus.SUCCEEDED,
        )

    def _cancelled(self, call: ToolCallPart) -> ToolResultPart:
        return self._error(call, "Error: tool call cancelled")

    def _error(self, call: ToolCallPart, content: str) -> ToolResultPart:
        return ToolResultPart(
            tool_call_id=call.tool_call_id,
            content=content,
            is_error=True,
        )


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


def _planning_access_for(tool: Tool) -> ToolPlanningAccess:
    if not isinstance(tool, ToolPlanningMetadata):
        return ToolPlanningAccess.HIDDEN
    access = tool.planning_access
    if not isinstance(access, ToolPlanningAccess):
        raise TypeError("tool planning_access must be a ToolPlanningAccess")
    return access


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
    "ToolExecutionOutcome",
    "ToolExecutionResult",
    "ToolExecutionStatus",
    "ToolExecutor",
    "ToolPlanningAccess",
    "ToolPlanningMetadata",
    "ToolPreparation",
    "ToolResultMaterialization",
    "ToolResultMaterializer",
    "ToolResultPersistenceStatus",
    "ToolRegistry",
]
