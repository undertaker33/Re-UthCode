from __future__ import annotations

import importlib
import os
import subprocess
import sys
from pathlib import Path


def test_root_package_exposes_version_without_provider_side_effects() -> None:
    package = importlib.import_module("uthcode")
    assert package.__version__ == "0.1.0"

    source_root = str(Path(__file__).parents[1] / "src")
    environment = os.environ.copy()
    environment["PYTHONPATH"] = source_root + os.pathsep + environment.get("PYTHONPATH", "")
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys, uthcode; assert uthcode.__version__ == '0.1.0'; "
            "assert 'openai' not in sys.modules; "
            "assert 'anthropic' not in sys.modules; "
            "assert 'uthcode.integrations.providers.factory' not in sys.modules",
        ],
        cwd=Path(__file__).parents[1],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_root_package_keeps_composition_in_subpackages() -> None:
    package_root = Path(__file__).parents[1] / "src" / "uthcode"

    assert (package_root / "__init__.py").is_file()
    assert not any(
        (package_root / name).is_file()
        for name in ("application.py", "config.py", "runtime.py", "cli.py")
    )
    assert (package_root / "__main__.py").is_file()
    assert (package_root / "interfaces" / "cli.py").is_file()


def test_config_integration_exposes_raw_loader_not_effective_config() -> None:
    import uthcode.integrations.config as config

    assert "load_config_data" in config.__all__
    assert "LoadedConfigData" in config.__all__
    assert "LoadedConfigSource" in config.__all__
    assert "load_effective_config" not in config.__dict__
    assert "load_effective_config" not in config.__all__


def test_core_exposes_the_single_tool_contract() -> None:
    from uthcode.core import Tool, ToolExecutionResult, ToolExecutor, ToolRegistry

    assert Tool is not None
    assert ToolExecutionResult is not None
    assert ToolExecutor is not None
    assert ToolRegistry is not None


def test_core_exposes_agent_contract_without_provider_side_effects() -> None:
    from uthcode.core import (
        AgentEvent,
        AgentLoop,
        AgentLoopConfig,
        AgentTurnExecution,
        RunSnapshot,
        RunState,
        TurnResult,
    )

    assert AgentEvent is not None
    assert AgentLoop is not None
    assert AgentLoopConfig is not None
    assert AgentTurnExecution is not None
    assert RunSnapshot is not None
    assert RunState is not None
    assert TurnResult is not None


def test_application_exposes_core_tool_values_without_integration_runtime_types() -> None:
    import uthcode.application as application
    from uthcode.application import (
        CancellationToken,
        ToolCallPart,
        ToolDefinition,
        ToolResultPart,
    )

    assert CancellationToken is not None
    assert ToolCallPart is not None
    assert ToolDefinition is not None
    assert ToolResultPart is not None
    assert "ToolRegistry" not in application.__all__
    assert "ToolExecutor" not in application.__all__
