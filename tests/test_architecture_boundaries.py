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
    for path in (SRC / "core", SRC / "application"):
        for source_path in path.rglob("*.py"):
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
            assert not any(
                forbidden in value
                for value in values
                for forbidden in (
                    "pydantic_ai",
                    "anthropic",
                    "openai",
                    "langgraph",
                    "langchain",
                    "integrations",
                )
            ), source_path


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
