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
