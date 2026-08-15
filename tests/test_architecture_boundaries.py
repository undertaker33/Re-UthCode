from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
SRC = ROOT / "src" / "uthcode"
PROVIDER_ROOT = SRC / "integrations" / "providers"


def _source_package(source_path: Path) -> tuple[str, ...]:
    relative = source_path.relative_to(SRC)
    module_parts = list(relative.with_suffix("").parts)
    package_parts = module_parts[:-1]
    return ("uthcode", *package_parts)


def _resolve_from_import(source_path: Path, node: ast.ImportFrom) -> str:
    if node.level == 0:
        return node.module or ""

    package_parts = list(_source_package(source_path))
    parent_count = node.level - 1
    if parent_count >= len(package_parts):
        raise ValueError(
            f"relative import escapes the uthcode package: "
            f"{source_path} (level={node.level})"
        )

    resolved_parts = package_parts[: len(package_parts) - parent_count]
    if node.module:
        resolved_parts.extend(node.module.split("."))
    return ".".join(resolved_parts)


def _resolved_imports(source_path: Path, tree: ast.AST) -> list[str]:
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = _resolve_from_import(source_path, node)
            if module:
                imports.append(module)
            if node.module is None:
                imports.extend(
                    f"{module}.{alias.name}" if module else alias.name
                    for alias in node.names
                    if alias.name != "*"
                )
        elif isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
    return imports


def _imports(source_path: Path) -> list[str]:
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    return _resolved_imports(source_path, tree)


def _fixture_imports(
    source: str,
    relative_path: str = "integrations/config/_boundary_fixture.py",
) -> list[str]:
    fixture_path = SRC / relative_path
    return _resolved_imports(fixture_path, ast.parse(source))


def _assert_no_integration_reverse_dependency(
    source_path: Path, imports: list[str]
) -> None:
    assert not any(
        value == "uthcode.application"
        or value.startswith("uthcode.application.")
        or value == "uthcode.interfaces"
        or value.startswith("uthcode.interfaces.")
        for value in imports
    ), source_path


def test_core_and_application_have_only_allowed_dependency_edges() -> None:
    forbidden = (
        "anthropic",
        "openai",
        "lang" + "graph",
        "lang" + "chain",
    )
    for source_path in (SRC / "core").rglob("*.py"):
        assert not any(
            forbidden_name in value
            for value in _imports(source_path)
            for forbidden_name in forbidden
        ), source_path

    for source_path in (SRC / "application").rglob("*.py"):
        values = _imports(source_path)
        allowed_integration_imports = {
            "uthcode.integrations.providers.config"
        }
        if source_path.name == "bootstrap.py":
            allowed_integration_imports.update(
                {
                    "uthcode.integrations.config.data",
                    "uthcode.integrations.config.loader",
                    "uthcode.integrations.instruction_files",
                    "uthcode.integrations.permissions",
                    "uthcode.integrations.providers.factory",
                    "uthcode.integrations.tools.factory",
                }
            )
        for value in values:
            if value.startswith("uthcode.integrations"):
                assert value in allowed_integration_imports, source_path
            assert not any(
                forbidden_name in value
                for forbidden_name in forbidden
            ), source_path


def test_sdk_imports_are_confined_to_native_provider_modules() -> None:
    allowed = {
        "integrations/providers/anthropic.py": {"anthropic"},
        "integrations/providers/openai_responses.py": {"openai"},
        "integrations/providers/openai_compat.py": {"openai"},
    }

    for source_path in SRC.rglob("*.py"):
        relative = source_path.relative_to(SRC).as_posix()
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        sdk_roots: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                root = node.module.split(".", maxsplit=1)[0]
                if root in {"anthropic", "openai"}:
                    sdk_roots.add(root)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".", maxsplit=1)[0]
                    if root in {"anthropic", "openai"}:
                        sdk_roots.add(root)
        assert sdk_roots <= allowed.get(relative, set()), source_path


def test_integrations_never_depend_on_application_or_interfaces() -> None:
    for source_path in (SRC / "integrations").rglob("*.py"):
        _assert_no_integration_reverse_dependency(source_path, _imports(source_path))


def test_concrete_integration_tools_stay_below_application_boundary() -> None:
    tools_root = SRC / "integrations" / "tools"
    assert tools_root.is_dir()
    for source_path in tools_root.rglob("*.py"):
        imports = _imports(source_path)
        _assert_no_integration_reverse_dependency(source_path, imports)
        assert not any(
            value.startswith("anthropic")
            or value.startswith("openai")
            for value in imports
        ), source_path


@pytest.mark.parametrize(
    "source",
    [
        "import uthcode.application",
        "from uthcode.application import EffectiveConfig",
        "import uthcode.interfaces",
        "from uthcode.interfaces import UthCodeTUI",
        "from ...application import EffectiveConfig",
        "from ...interfaces import UthCodeTUI",
    ],
)
def test_integration_boundary_rejects_absolute_and_resolved_relative_reverse_imports(
    source: str,
) -> None:
    imports = _fixture_imports(source)
    assert any(
        value == "uthcode.application"
        or value.startswith("uthcode.application.")
        or value == "uthcode.interfaces"
        or value.startswith("uthcode.interfaces.")
        for value in imports
    )
    with pytest.raises(AssertionError):
        _assert_no_integration_reverse_dependency(
            SRC / "integrations" / "config" / "_boundary_fixture.py",
            imports,
        )


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("from .data import LoadedConfigData", "uthcode.integrations.config.data"),
        ("from ..providers import factory", "uthcode.integrations.providers"),
        ("from . import data", "uthcode.integrations.config.data"),
    ],
)
def test_integration_internal_relative_imports_are_not_false_positives(
    source: str, expected: str
) -> None:
    imports = _fixture_imports(source)
    assert expected in imports
    _assert_no_integration_reverse_dependency(
        SRC / "integrations" / "config" / "_boundary_fixture.py",
        imports,
    )


def test_relative_imports_use_the_package_name_of_init_modules() -> None:
    imports = _fixture_imports(
        "from .config import data",
        relative_path="integrations/__init__.py",
    )
    assert "uthcode.integrations.config" in imports
    _assert_no_integration_reverse_dependency(
        SRC / "integrations" / "__init__.py",
        imports,
    )


def test_provider_modules_use_public_sdk_surfaces_and_no_private_stream_access() -> None:
    for source_path in PROVIDER_ROOT.glob("*.py"):
        source = source_path.read_text(encoding="utf-8")
        assert "._response" not in source
        assert "_source_iter" not in source
        assert "record_model_stream" not in source


def test_forbidden_future_modules_and_graph_dependencies_are_absent() -> None:
    forbidden_names = {
        "runtime.py",
        "graph",
        "prompts",
        "permissions",
        "context",
        "memory",
        "session",
        "storage",
        "journal",
        "sandbox",
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
    hook_paths = {
        path.relative_to(SRC).as_posix()
        for path in SRC.rglob("*")
        if path.name in {"hooks", "hooks.py"}
    }
    assert hook_paths == {"core/hooks.py"}


def test_t08_core_contracts_stay_pure_and_hooks_have_only_two_sync_points() -> None:
    planning_path = SRC / "core" / "planning.py"
    hooks_path = SRC / "core" / "hooks.py"
    assert planning_path.is_file()
    assert hooks_path.is_file()

    for source_path in (planning_path, hooks_path):
        imports = _imports(source_path)
        assert not any(
            value.startswith("uthcode.application")
            or value.startswith("uthcode.integrations")
            or value.startswith("uthcode.interfaces")
            for value in imports
        ), source_path

    hooks_source = hooks_path.read_text(encoding="utf-8")
    hooks_tree = ast.parse(hooks_source)
    assert not any(isinstance(node, (ast.AsyncFunctionDef, ast.Await)) for node in ast.walk(hooks_tree))
    assert "before_tool_execution" in hooks_source
    assert "before_completion" in hooks_source
    assert "after_tool" not in hooks_source
    assert "after_completion" not in hooks_source
    assert "create_task" not in hooks_source
    assert "ToolExecutor" not in hooks_source
    assert "ProviderPort" not in hooks_source
    assert "RunState" not in hooks_source
    assert "registry" not in hooks_source.lower()


def test_interfaces_only_depend_on_application_and_their_ui_toolkit() -> None:
    interfaces = SRC / "interfaces"
    assert interfaces.is_dir()

    for source_path in interfaces.rglob("*.py"):
        imports = _imports(source_path)
        assert not any(
            value.startswith("uthcode.core")
            or value.startswith("uthcode.integrations")
            or value.startswith("anthropic")
            or value.startswith("openai")
            for value in imports
        ), source_path
        if "tui" not in source_path.parts:
            assert not any(
                value == "textual" or value.startswith("textual.")
                for value in imports
            ), source_path


def test_headless_application_runs_without_importing_the_interface_tree() -> None:
    script = """
import asyncio
import sys
from uthcode.application import EffectiveConfig, GenerationRequest, Message, TextPart, create_application

async def main():
    application = create_application(EffectiveConfig.single_model('fake/ref'))
    request = GenerationRequest(messages=(Message('user', (TextPart('hello'),)),))
    events = [event async for event in application.stream_generation(request)]
    assert events
    assert 'uthcode.interfaces' not in sys.modules

asyncio.run(main())
"""
    environment = os.environ.copy()
    source_root = str(SRC.parent)
    environment["PYTHONPATH"] = source_root + os.pathsep + environment.get("PYTHONPATH", "")
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_runtime_source_contains_no_graph_or_compatibility_names() -> None:
    forbidden = (
        "lang" + "graph",
        "lang" + "chain",
        "stategraph",
        "graphstate",
        "check" + "point",
        "mewcode",
        "conversationmanager",
    )

    for source_path in SRC.rglob("*.py"):
        source = source_path.read_text(encoding="utf-8").lower()
        assert not any(name in source for name in forbidden), source_path

    assert (SRC / "interfaces").is_dir()


def test_t06_pause_control_and_ask_tool_have_no_duplicate_runtime_path() -> None:
    core_pause_sources = (
        SRC / "core" / "agent.py",
        SRC / "core" / "interaction.py",
    )
    forbidden_async_names = {"Future", "Event", "Queue", "Task", "Lock"}
    for source_path in core_pause_sources:
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        asyncio_imported_names = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module == "asyncio"
            for alias in node.names
        }
        assert not asyncio_imported_names.intersection(forbidden_async_names), source_path
        assert not {
            node.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Name)
        }.intersection(forbidden_async_names), source_path

    integration_sources = (SRC / "integrations").rglob("*.py")
    assert not any(
        "AskUserQuestion" in source_path.read_text(encoding="utf-8")
        or "ASK_USER_TOOL_DEFINITION" in source_path.read_text(encoding="utf-8")
        for source_path in integration_sources
    )

    application_tools = (SRC / "application" / "tools.py").read_text(encoding="utf-8")
    generation = (SRC / "application" / "generation.py").read_text(encoding="utf-8")
    assert "AskUserQuestion is reserved for the Application Agent path" in application_tools
    assert "manual Tool execution is disabled" in generation
    assert "async def execute_calls" not in application_tools
    assert "ordinary_tool_definitions + (ASK_USER_TOOL_DEFINITION,)" in generation


def test_protocol_wire_fields_stay_in_their_physical_modules() -> None:
    paths = {
        "anthropic": PROVIDER_ROOT / "anthropic.py",
        "responses": PROVIDER_ROOT / "openai_responses.py",
        "chat": PROVIDER_ROOT / "openai_compat.py",
    }
    sources = {
        name: path.read_text(encoding="utf-8")
        for name, path in paths.items()
    }
    markers = {
        "anthropic": ("redacted_thinking", "tool_use", "message_stop"),
        "responses": ("function_call_output", "output_index", "encrypted_content"),
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


def test_provider_construction_has_one_formal_composition_root() -> None:
    factory = PROVIDER_ROOT / "factory.py"
    bootstrap = SRC / "application" / "bootstrap.py"
    generation = SRC / "application" / "generation.py"
    providers_init = PROVIDER_ROOT / "__init__.py"

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
