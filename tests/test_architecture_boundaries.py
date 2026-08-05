from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).parents[1]
SRC = ROOT / "src" / "uthcode"
PROVIDER_ROOT = SRC / "integrations" / "providers"


def _imports(source_path: Path) -> list[str]:
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    return [
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    ] + [
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    ]


def test_core_and_application_have_only_allowed_dependency_edges() -> None:
    forbidden = (
        "anthropic",
        "openai",
        "langgraph",
        "langchain",
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
            allowed_integration_imports.add("uthcode.integrations.providers.factory")
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
        "tools",
        "prompts",
        "permissions",
        "context",
        "memory",
        "session",
        "storage",
        "journal",
        "sandbox",
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

    assert (SRC / "interfaces").is_dir()


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
