from __future__ import annotations

import ast
import asyncio
import inspect
from pathlib import Path

import pytest
from pydantic_ai.models.function import FunctionModel

from uthcode.application import UthCodeApplication
from uthcode.core.provider import (
    CancellationToken,
    AuthenticationError,
    FinishReason,
    GenerationCompleted,
    GenerationRequest,
    InvalidProviderResponseError,
    Message,
    NetworkError,
    ProviderIdentity,
    RateLimitError,
    TextDelta,
    TextPart,
)
from uthcode.integrations.providers.pydantic_ai import (
    PydanticAIProvider,
    _NativeTracker,
    _map_exception,
)


ROOT = Path(__file__).parents[1]
SRC = ROOT / "src" / "uthcode"


def _request() -> GenerationRequest:
    return GenerationRequest(messages=(Message("user", (TextPart("hello"),)),))


@pytest.mark.asyncio
async def test_function_model_flows_through_shared_bridge() -> None:
    seen_messages: list[object] = []

    async def stream_function(messages, _agent_info):
        seen_messages.extend(messages)
        yield "hello "
        yield "world"

    provider = PydanticAIProvider(
        model=FunctionModel(stream_function=stream_function, model_name="function-test"),
        identity=ProviderIdentity("test", "direct", "function-test"),
    )

    events = [
        event
        async for event in provider.stream(
            _request(),
            cancellation=CancellationToken(),
        )
    ]

    assert [event.text for event in events if isinstance(event, TextDelta)] == [
        "hello ",
        "world",
    ]
    terminal = [event for event in events if isinstance(event, GenerationCompleted)]
    assert len(terminal) == 1
    assert terminal[0].response.finish_reason is FinishReason.STOP
    assert seen_messages
    assert terminal[0].response.usage.output_tokens > 0


def test_shared_bridge_public_surface_does_not_leak_sdk_types() -> None:
    for function in (
        UthCodeApplication.__init__,
        UthCodeApplication.stream_generation,
    ):
        for annotation in function.__annotations__.values():
            assert "pydantic_ai" not in repr(annotation)
            assert "anthropic" not in repr(annotation)
            assert "openai" not in repr(annotation)


def test_core_and_application_have_only_allowed_dependency_edges() -> None:
    forbidden = (
        "pydantic_ai",
        "anthropic",
        "openai",
        "langgraph",
        "langchain",
    )
    for source_path in (SRC / "core").rglob("*.py"):
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        values = [
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        ] + [
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        ]
        assert not any(forbidden_name in value for value in values for forbidden_name in forbidden), source_path

    for source_path in (SRC / "application").rglob("*.py"):
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        imports = [
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        ]
        imported_names = [
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        ]
        values = imports + imported_names
        allowed_integration_imports = {
            "uthcode.integrations.providers.config"
        }
        if source_path.name == "bootstrap.py":
            allowed_integration_imports.add("uthcode.integrations.providers.factory")
        for value in values:
            if value.startswith("uthcode.integrations"):
                assert value in allowed_integration_imports, source_path
            assert not any(forbidden_name in value for forbidden_name in forbidden), source_path


def test_forbidden_future_modules_and_graph_dependencies_are_absent() -> None:
    forbidden_names = {
        "cli.py",
        "__main__.py",
        "runtime.py",
        "graph",
        "tools",
        "prompts",
        "permissions",
        "context",
        "memory",
        "session",
        "storage",
        "journal",
        "sandbox",
        "commands",
        "hooks",
        "skills",
        "mcp",
        "agents",
        "worktree",
    }
    actual = {
        path.name
        for path in SRC.rglob("*")
        if path.name != "__pycache__"
    }
    assert not forbidden_names.intersection(actual)


def test_provider_errors_are_classified_without_copying_secret_text() -> None:
    class AuthenticationFailure(Exception):
        status_code = 401

        def __str__(self) -> str:
            return "secret-test-key"

    mapped = _map_exception(AuthenticationFailure())

    assert type(mapped).__name__ == "AuthenticationError"
    assert "secret-test-key" not in str(mapped)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure_name", "status_code", "expected_error"),
    [
        ("AuthenticationFailure", 401, AuthenticationError),
        ("RateLimitFailure", 429, RateLimitError),
        ("NetworkFailure", None, NetworkError),
        ("ResponseValidationFailure", None, InvalidProviderResponseError),
    ],
)
async def test_formal_stream_maps_error_matrix_without_secret_leakage(
    failure_name: str,
    status_code: int | None,
    expected_error: type[Exception],
) -> None:
    secret = "sk-secret-must-not-escape"

    failure_type = type(
        failure_name,
        (OSError,) if failure_name == "NetworkFailure" else (Exception,),
        {"status_code": status_code},
    )

    async def failing_stream(_messages, _agent_info):
        raise failure_type(secret)
        yield "unreachable"

    provider = PydanticAIProvider(
        model=FunctionModel(stream_function=failing_stream, model_name="error-test"),
        identity=ProviderIdentity("test", "direct", "error-test"),
    )

    with pytest.raises(expected_error) as raised:
        async for _ in provider.stream(_request(), cancellation=CancellationToken()):
            pass

    assert secret not in str(raised.value)
    assert secret not in repr(raised.value)
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None


def test_provider_details_become_json_safe_native_items() -> None:
    tracker = _NativeTracker(ProviderIdentity("test", "direct", "details-test"))

    item = tracker.add({"opaque": {"values": [1, "two"]}})

    assert item is not None
    assert item.payload == {"opaque": {"values": [1, "two"]}}
    with pytest.raises(InvalidProviderResponseError):
        tracker.add({"bad": object()})


@pytest.mark.asyncio
async def test_cancellation_closes_function_stream_and_returns_uthcode_error() -> None:
    closed = False
    model_context_entries = 0
    model_context_exits = 0

    class ExternallyOwnedFunctionModel(FunctionModel):
        async def __aenter__(self):
            nonlocal model_context_entries
            model_context_entries += 1
            return await super().__aenter__()

        async def __aexit__(self, exc_type, exc_value, traceback):
            nonlocal model_context_exits
            model_context_exits += 1
            return await super().__aexit__(exc_type, exc_value, traceback)

    async def infinite_stream(_messages, _agent_info):
        nonlocal closed
        try:
            while True:
                yield "chunk"
                await asyncio.sleep(0.01)
        finally:
            closed = True

    external_model = ExternallyOwnedFunctionModel(
        stream_function=infinite_stream,
        model_name="cancel-test",
    )
    provider = PydanticAIProvider(
        model=external_model,
        identity=ProviderIdentity("test", "direct", "cancel-test"),
    )
    token = CancellationToken()

    async def consume() -> None:
        async for _ in provider.stream(_request(), cancellation=token):
            await asyncio.sleep(0)

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.05)
    token.cancel()

    with pytest.raises(Exception) as raised:
        await task
    assert type(raised.value).__name__ == "GenerationCancelled"
    assert closed is True
    assert model_context_entries == 0
    assert model_context_exits == 0


def test_runtime_source_contains_no_legacy_graph_or_compatibility_names() -> None:
    forbidden = (
        "langgraph",
        "langchain",
        "stategraph",
        "graphstate",
        "checkpoint",
        "mewcode",
        "conversationmanager",
    )

    for source_path in SRC.rglob("*.py"):
        source = source_path.read_text(encoding="utf-8").lower()
        assert not any(name in source for name in forbidden), source_path

    assert not (SRC / "interfaces").exists()


def test_protocol_wire_fields_stay_in_their_physical_modules() -> None:
    paths = {
        "anthropic": SRC / "integrations" / "providers" / "anthropic.py",
        "responses": SRC / "integrations" / "providers" / "openai_responses.py",
        "chat": SRC / "integrations" / "providers" / "openai_compat.py",
        "bridge": SRC / "integrations" / "providers" / "pydantic_ai.py",
    }
    sources = {name: path.read_text(encoding="utf-8") for name, path in paths.items()}
    markers = {
        "anthropic": ("redacted_thinking", "tool_use", "message_stop"),
        "responses": ("function_call", "output_index", "encrypted_content"),
        "chat": ("reasoning_carrier", "assistant_tool_call", "prompt_tokens_details"),
    }

    for owner, fields in markers.items():
        for field in fields:
            assert field in sources[owner], (owner, field)
            assert all(
                field not in sources[other]
                for other in sources
                if other != owner
            ), (field, owner)


def test_shared_bridge_has_no_provider_dispatch_branch() -> None:
    bridge = (SRC / "integrations" / "providers" / "pydantic_ai.py").read_text(
        encoding="utf-8"
    ).lower()

    for protocol_name in ("anthropic", "openai_responses", "openai_compat"):
        assert protocol_name not in bridge

    for protocol_field in (
        "redacted_thinking",
        "function_call",
        "reasoning_carrier",
        "prompt_tokens_details",
    ):
        assert protocol_field not in bridge


def test_provider_construction_has_one_formal_composition_root() -> None:
    factory = SRC / "integrations" / "providers" / "factory.py"
    bootstrap = SRC / "application" / "bootstrap.py"
    generation = SRC / "application" / "generation.py"
    providers_init = SRC / "integrations" / "providers" / "__init__.py"

    mentions = {
        path.relative_to(SRC).as_posix()
        for path in SRC.rglob("*.py")
        if "create_provider" in path.read_text(encoding="utf-8")
    }
    assert mentions == {
        "application/bootstrap.py",
        "integrations/providers/factory.py",
    }
    assert factory.read_text(encoding="utf-8").count("def create_provider") == 1
    assert "create_provider" not in generation.read_text(encoding="utf-8")
    assert "create_provider" not in providers_init.read_text(encoding="utf-8")
    assert '__all__ = ["create_provider"]' in factory.read_text(encoding="utf-8")
    assert '__all__: list[str] = []' in providers_init.read_text(encoding="utf-8")
    assert "create_provider" in bootstrap.read_text(encoding="utf-8")
