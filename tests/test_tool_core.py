from __future__ import annotations

from dataclasses import FrozenInstanceError, dataclass, field

import pytest
from jsonschema.exceptions import SchemaError

from uthcode.core.tool import (
    PreparedToolCall,
    Tool,
    ToolExecutionResult,
    ToolExecutor,
    ToolPlanningAccess,
    ToolPlanningMetadata,
    ToolRegistry,
    ToolPreparation,
)
from uthcode.core.permission import (
    Decision,
    Effect,
    PermissionAction,
    PermissionEvaluator,
    PermissionMode,
    ResourceScope,
)
from uthcode.core.provider import (
    CancellationToken,
    JsonPayload,
    ToolCallPart,
    ToolDefinition,
    ToolResultPart,
)


@dataclass
class FakeTool:
    name: str
    handler: str = "success"
    started: list[str] = field(default_factory=list)
    cancel_on_execute: bool = False

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            self.name,
            parameters={
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
                "additionalProperties": False,
            },
        )

    async def execute(
        self,
        arguments: JsonPayload,
        *,
        cancellation: CancellationToken,
    ) -> ToolExecutionResult:
        self.started.append(str(arguments["value"]))
        if self.cancel_on_execute:
            cancellation.cancel()
        if self.handler == "raise":
            raise RuntimeError("implementation detail must not leak")
        return ToolExecutionResult(f"{self.name}:{arguments['value']}")


@dataclass
class OutputTool:
    name: str
    output: str
    is_error: bool = False

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            self.name,
            parameters={"type": "object", "additionalProperties": False},
        )

    async def execute(
        self,
        arguments: JsonPayload,
        *,
        cancellation: CancellationToken,
    ) -> ToolExecutionResult:
        del arguments, cancellation
        return ToolExecutionResult(self.output, self.is_error)


@dataclass
class MutableDefinitionTool:
    name: str
    property_name: str
    executed: list[JsonPayload] = field(default_factory=list)

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            self.name,
            parameters={
                "type": "object",
                "properties": {self.property_name: {"type": "string"}},
                "required": [self.property_name],
                "additionalProperties": False,
            },
        )

    async def execute(
        self,
        arguments: JsonPayload,
        *,
        cancellation: CancellationToken,
    ) -> ToolExecutionResult:
        del cancellation
        self.executed.append(arguments)
        return ToolExecutionResult("executed")


@dataclass
class PreflightTool(FakeTool):
    preflight_started: list[str] = field(default_factory=list)

    def preflight(self, arguments: JsonPayload) -> ToolPreparation:
        self.preflight_started.append(str(arguments["value"]))
        return ToolPreparation(
            action=PermissionAction(
                tool=self.name,
                action="test",
                effect=Effect.WRITE,
                resource=f"project/{arguments['value']}",
                scope=ResourceScope.INSIDE,
            ),
            execution_arguments=arguments,
        )


@dataclass
class PlanningAwareFakeTool(FakeTool):
    access: ToolPlanningAccess = ToolPlanningAccess.READ_ONLY

    @property
    def planning_access(self) -> ToolPlanningAccess:
        return self.access


@dataclass
class SpyPermissionEvaluator:
    evaluated: list[PermissionAction] = field(default_factory=list)

    def evaluate(self, action: PermissionAction) -> None:
        self.evaluated.append(action)


def _prepare_then_evaluate(
    executor: ToolExecutor,
    call: ToolCallPart,
    evaluator: SpyPermissionEvaluator,
) -> PreparedToolCall | ToolResultPart:
    prepared = executor.prepare_call(call)
    if isinstance(prepared, PreparedToolCall):
        evaluator.evaluate(prepared.action)
    return prepared


async def _execute_prepared_calls_for_test(
    executor: ToolExecutor,
    calls: tuple[ToolCallPart, ...],
    *,
    cancellation: CancellationToken,
) -> tuple[ToolResultPart, ...]:
    """Exercise the prepared boundary with an explicit test evaluator gate."""

    evaluator = PermissionEvaluator()
    results: list[ToolResultPart] = []
    for call in calls:
        prepared = executor.prepare_call(call, cancellation=cancellation)
        if isinstance(prepared, ToolResultPart):
            results.append(prepared)
            continue
        decision = evaluator.evaluate(prepared.action, mode=PermissionMode.FULL_ACCESS)
        assert decision.decision is Decision.ALLOW
        results.append(
            await executor.execute_prepared(prepared, cancellation=cancellation)
        )
    return tuple(results)


def _call(call_id: str, name: str, value: str = "input") -> ToolCallPart:
    return ToolCallPart(call_id, name, {"value": value})


def test_registry_validates_schemas_and_preserves_definition_order() -> None:
    first = FakeTool("first")
    second = FakeTool("second")
    registry = ToolRegistry()
    registry.register(first)
    registry.register(second)

    assert registry.list_tools() == (first, second)
    assert registry.definitions() == (first.definition, second.definition)
    assert registry.definitions() == registry.definitions()
    assert isinstance(registry.definitions(), tuple)
    assert isinstance(registry.list_tools(), tuple)
    assert registry.get("first") is first
    assert registry.get("missing") is None


def test_registry_snapshots_explicit_planning_access_and_fails_closed_by_default() -> None:
    hidden_by_default = FakeTool("undeclared")
    visible = PlanningAwareFakeTool("visible")
    explicit_hidden = PlanningAwareFakeTool("hidden", access=ToolPlanningAccess.HIDDEN)
    registry = ToolRegistry((hidden_by_default, visible, explicit_hidden))

    assert isinstance(visible, ToolPlanningMetadata)
    assert not isinstance(hidden_by_default, ToolPlanningMetadata)
    assert registry.planning_access_for("undeclared") is ToolPlanningAccess.HIDDEN
    assert registry.planning_access_for("visible") is ToolPlanningAccess.READ_ONLY
    assert registry.planning_access_for("hidden") is ToolPlanningAccess.HIDDEN
    assert registry.planning_access_for("missing") is None
    assert tuple(item.name for item in registry.plan_definitions()) == ("visible",)
    assert tuple(item.name for item in registry.definitions()) == (
        "undeclared",
        "visible",
        "hidden",
    )
    assert all("planning_access" not in item.to_dict() for item in registry.definitions())

    visible.access = ToolPlanningAccess.HIDDEN
    assert registry.planning_access_for("visible") is ToolPlanningAccess.READ_ONLY
    assert tuple(item.name for item in registry.plan_definitions()) == ("visible",)


def test_registry_rejects_invalid_declared_planning_access() -> None:
    class InvalidPlanningTool(FakeTool):
        @property
        def planning_access(self) -> str:
            return "read_only"

    with pytest.raises(TypeError, match="planning_access"):
        ToolRegistry((InvalidPlanningTool("invalid"),))


def test_registry_rejects_duplicate_names_and_invalid_json_schema() -> None:
    registry = ToolRegistry()
    registry.register(FakeTool("same"))

    with pytest.raises(ValueError, match="already registered"):
        registry.register(FakeTool("same"))

    class InvalidSchemaTool(OutputTool):
        @property
        def definition(self) -> ToolDefinition:
            return ToolDefinition(self.name, parameters={"type": "not-a-json-type"})

    with pytest.raises(ValueError, match="invalid JSON Schema") as error:
        registry.register(InvalidSchemaTool("bad", "unused"))

    assert error.value.__cause__ is None
    assert tuple(tool.name for tool in registry.list_tools()) == ("same",)


def test_registry_keeps_definition_and_schema_snapshot_when_tool_definition_drifts() -> None:
    tool = MutableDefinitionTool("before", "before_value")
    registry = ToolRegistry((tool,))
    registered_definition = registry.definitions()[0]

    tool.name = "after"
    tool.property_name = "after_value"

    assert registry.definitions() == (registered_definition,)
    assert registry.definitions()[0].name == "before"
    assert registry.definitions()[0].parameters["required"] == ["before_value"]
    assert registry.get("before") is tool
    assert registry.get("after") is None


@pytest.mark.asyncio
async def test_registry_snapshot_controls_execution_after_tool_definition_drifts() -> None:
    tool = MutableDefinitionTool("before", "before_value")
    registry = ToolRegistry((tool,))
    tool.name = "after"
    tool.property_name = "after_value"
    executor = ToolExecutor(registry)

    results = await _execute_prepared_calls_for_test(
        executor,
        (
            ToolCallPart("call-before", "before", {"before_value": "ok"}),
            ToolCallPart("call-after", "after", {"after_value": "wrong-name"}),
            ToolCallPart("call-new-args", "before", {"after_value": "wrong-schema"}),
        ),
        cancellation=CancellationToken(),
    )

    assert [result.tool_call_id for result in results] == [
        "call-before",
        "call-after",
        "call-new-args",
    ]
    assert results[0].is_error is False
    assert results[1].is_error is True
    assert "unknown tool" in results[1].content
    assert results[2].is_error is True
    assert "invalid arguments" in results[2].content
    assert len(tool.executed) == 1
    assert tool.executed[0] == {"before_value": "ok"}


def test_invalid_schema_error_hides_jsonschema_cause_and_details() -> None:
    class InvalidSchemaTool(OutputTool):
        @property
        def definition(self) -> ToolDefinition:
            return ToolDefinition(
                self.name,
                parameters={"type": "not-a-jsonschema-type"},
            )

    registry = ToolRegistry()
    with pytest.raises(ValueError) as error:
        registry.register(InvalidSchemaTool("bad-schema", "unused"))

    assert not isinstance(error.value, SchemaError)
    assert error.value.__cause__ is None
    text = str(error.value).lower()
    assert "jsonschema" not in text
    assert "metaschema" not in text
    assert "validator" not in text
    assert "bad-schema" in text
    assert registry.list_tools() == ()
    assert registry.definitions() == ()
    assert registry.get("bad-schema") is None


@pytest.mark.asyncio
async def test_executor_keeps_fifo_and_normalizes_unknown_invalid_and_exception() -> None:
    successful = FakeTool("success")
    failing = FakeTool("failing", handler="raise")
    registry = ToolRegistry((successful, failing))
    executor = ToolExecutor(registry)
    calls = (
        ToolCallPart("call-unknown", "missing", {"value": "one"}),
        ToolCallPart("call-invalid", "success", {}),
        _call("call-failing", "failing", "three"),
        _call("call-success", "success", "four"),
    )

    results = await _execute_prepared_calls_for_test(executor, calls, cancellation=CancellationToken())

    assert [result.tool_call_id for result in results] == [call.tool_call_id for call in calls]
    assert [result.is_error for result in results] == [True, True, True, False]
    assert "unknown tool" in results[0].content
    assert "invalid arguments" in results[1].content
    assert "RuntimeError" not in results[2].content
    assert successful.started == ["four"]
    assert failing.started == ["three"]


@pytest.mark.asyncio
async def test_prepare_call_validates_once_and_execute_prepared_does_not_preflight_again() -> None:
    tool = PreflightTool("prepared")
    executor = ToolExecutor(ToolRegistry((tool,)))
    prepared = executor.prepare_call(_call("prepared-1", "prepared", "one"))

    assert isinstance(prepared, PreparedToolCall)
    assert prepared.action.effect is Effect.WRITE
    assert prepared.action.resource == "project/one"
    assert prepared.execution_arguments["value"] == "one"
    assert tool.preflight_started == ["one"]

    result = await executor.execute_prepared(prepared, cancellation=CancellationToken())

    assert result.tool_call_id == "prepared-1"
    assert result.is_error is False
    assert tool.preflight_started == ["one"]
    assert tool.started == ["one"]


@pytest.mark.asyncio
async def test_unknown_invalid_and_cancelled_calls_do_not_enter_action_preflight() -> None:
    tool = PreflightTool("prepared")
    executor = ToolExecutor(ToolRegistry((tool,)))
    token = CancellationToken()
    token.cancel()

    results = await _execute_prepared_calls_for_test(
        executor,
        (
            ToolCallPart("unknown", "missing", {"value": "unknown"}),
            ToolCallPart("invalid", "prepared", {}),
            ToolCallPart("cancelled", "prepared", {"value": "cancelled"}),
        ),
        cancellation=token,
    )

    assert all(result.is_error for result in results)
    assert tool.preflight_started == []


def test_permission_gate_only_evaluates_prepared_calls() -> None:
    tool = PreflightTool("prepared")
    executor = ToolExecutor(ToolRegistry((tool,)))
    evaluator = SpyPermissionEvaluator()

    unknown = _prepare_then_evaluate(
        executor,
        ToolCallPart("unknown", "missing", {"value": "unknown"}),
        evaluator,
    )
    invalid = _prepare_then_evaluate(
        executor,
        ToolCallPart("invalid", "prepared", {}),
        evaluator,
    )

    assert isinstance(unknown, ToolResultPart)
    assert unknown.is_error is True
    assert "unknown tool" in unknown.content
    assert isinstance(invalid, ToolResultPart)
    assert invalid.is_error is True
    assert "invalid arguments" in invalid.content
    assert evaluator.evaluated == []

    valid = _prepare_then_evaluate(
        executor,
        _call("valid", "prepared", "value"),
        evaluator,
    )

    assert isinstance(valid, PreparedToolCall)
    assert evaluator.evaluated == [valid.action]
    assert len(evaluator.evaluated) == 1


@pytest.mark.asyncio
async def test_executor_cancellation_never_starts_later_calls_and_returns_all_results() -> None:
    cancelling = FakeTool("cancelling", cancel_on_execute=True)
    later = FakeTool("later")
    final = FakeTool("final")
    executor = ToolExecutor(ToolRegistry((cancelling, later, final)))
    calls = (
        _call("call-1", "cancelling", "one"),
        _call("call-2", "later", "two"),
        _call("call-3", "final", "three"),
    )
    token = CancellationToken()

    results = await _execute_prepared_calls_for_test(executor, calls, cancellation=token)

    assert [result.tool_call_id for result in results] == ["call-1", "call-2", "call-3"]
    assert results[0].is_error is False
    assert results[1].is_error is True
    assert results[2].is_error is True
    assert "cancelled" in results[1].content
    assert "cancelled" in results[2].content
    assert cancelling.started == ["one"]
    assert later.started == []
    assert final.started == []


@pytest.mark.asyncio
async def test_executor_pre_cancel_does_not_start_any_tool() -> None:
    first = FakeTool("first")
    second = FakeTool("second")
    executor = ToolExecutor(ToolRegistry((first, second)))
    token = CancellationToken()
    token.cancel()

    results = await _execute_prepared_calls_for_test(
        executor,
        (_call("call-1", "first"), _call("call-2", "second")),
        cancellation=token,
    )

    assert [result.tool_call_id for result in results] == ["call-1", "call-2"]
    assert all(result.is_error for result in results)
    assert first.started == []
    assert second.started == []


@pytest.mark.asyncio
async def test_executor_truncates_success_and_error_results_once() -> None:
    long_output = "x" * 10_500
    success = OutputTool("success", long_output)
    error = OutputTool("error", long_output, is_error=True)
    executor = ToolExecutor(ToolRegistry((success, error)))

    results = await _execute_prepared_calls_for_test(
        executor,
        (
            ToolCallPart("call-success", "success"),
            ToolCallPart("call-error", "error"),
        ),
        cancellation=CancellationToken(),
    )

    suffix = "[Output truncated to 10000 characters]"
    assert all(len(result.content) <= 10_000 for result in results)
    assert all(result.content.endswith(suffix) for result in results)
    assert all(result.content.count(suffix) == 1 for result in results)
    assert results[0].is_error is False
    assert results[1].is_error is True


def test_tool_execution_result_is_immutable_and_type_checked() -> None:
    result = ToolExecutionResult("ok")
    with pytest.raises(FrozenInstanceError):
        result.content = "changed"  # type: ignore[misc]
    with pytest.raises(TypeError):
        ToolExecutionResult(1)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        ToolExecutionResult("ok", 1)  # type: ignore[arg-type]


def test_tool_protocol_is_runtime_checkable() -> None:
    assert isinstance(FakeTool("tool"), Tool)
