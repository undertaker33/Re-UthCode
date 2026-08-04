from __future__ import annotations

import importlib
from pathlib import Path


def test_root_package_exposes_version_without_provider_side_effects() -> None:
    package = importlib.import_module("uthcode")

    assert package.__version__ == "0.1.0"
    assert "pydantic_ai" not in package.__dict__


def test_task_one_has_only_the_root_package() -> None:
    package_root = Path(__file__).parents[1] / "src" / "uthcode"

    assert (package_root / "__init__.py").is_file()
    assert not any(
        (package_root / name).is_file()
        for name in ("application.py", "config.py", "runtime.py", "cli.py", "__main__.py")
    )
