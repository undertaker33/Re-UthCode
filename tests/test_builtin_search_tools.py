from __future__ import annotations

from pathlib import Path

import pytest

from uthcode.core import CancellationToken, ToolCallPart, ToolExecutor, ToolRegistry
from uthcode.integrations.tools.search_tools import GlobTool, GrepTool
from uthcode.integrations.tools.workspace import WorkspacePathResolver


def _search_tools(root: Path):
    resolver = WorkspacePathResolver(root)
    return resolver, GlobTool(resolver), GrepTool(resolver)


@pytest.mark.asyncio
async def test_glob_returns_only_sorted_workspace_files(tmp_path: Path) -> None:
    (tmp_path / "b.py").write_text("", encoding="utf-8")
    (tmp_path / "a.py").write_text("", encoding="utf-8")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "c.py").write_text("", encoding="utf-8")
    _, glob, _ = _search_tools(tmp_path)

    result = await glob.execute({"pattern": "**/*.py"}, cancellation=CancellationToken())  # type: ignore[arg-type]

    assert result.is_error is False
    assert result.content == "a.py\nb.py\npkg/c.py"


@pytest.mark.asyncio
async def test_glob_skips_dependency_and_cache_directories(tmp_path: Path) -> None:
    (tmp_path / "visible.py").write_text("", encoding="utf-8")
    for dirname in [".git", ".venv", "node_modules", "__pycache__", ".tox", ".mypy_cache", ".pytest_cache"]:
        skipped = tmp_path / dirname
        skipped.mkdir()
        (skipped / "hidden.py").write_text("", encoding="utf-8")
    _, glob, _ = _search_tools(tmp_path)

    result = await glob.execute({"pattern": "**/*.py"}, cancellation=CancellationToken())  # type: ignore[arg-type]

    assert result.content == "visible.py"


@pytest.mark.asyncio
async def test_glob_reports_empty_and_rejects_parent_pattern(tmp_path: Path) -> None:
    _, glob, _ = _search_tools(tmp_path)

    empty = await glob.execute({"pattern": "**/*.py"}, cancellation=CancellationToken())  # type: ignore[arg-type]
    parent = await glob.execute({"pattern": "../outside/*.py"}, cancellation=CancellationToken())  # type: ignore[arg-type]

    assert empty.is_error is False
    assert empty.content == "No files matched the pattern."
    assert parent.is_error is True


@pytest.mark.asyncio
async def test_grep_returns_stable_file_line_content_and_include_filter(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("alpha\nbeta\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("alphabet\n", encoding="utf-8")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "c.py").write_text("alpha\n", encoding="utf-8")
    _, _, grep = _search_tools(tmp_path)

    all_matches = await grep.execute(
        {"pattern": "alpha"}, cancellation=CancellationToken()  # type: ignore[arg-type]
    )
    python_matches = await grep.execute(
        {"pattern": "alpha", "include": "*.py"},  # type: ignore[arg-type]
        cancellation=CancellationToken(),
    )

    assert all_matches.content == "a.py:1:alpha\nb.txt:1:alphabet\nnested/c.py:1:alpha"
    assert python_matches.content == "a.py:1:alpha\nnested/c.py:1:alpha"


@pytest.mark.asyncio
async def test_grep_invalid_regex_and_empty_result_are_non_success_errors_only_for_regex(
    tmp_path: Path,
) -> None:
    (tmp_path / "a.py").write_text("alpha\n", encoding="utf-8")
    _, _, grep = _search_tools(tmp_path)

    invalid = await grep.execute({"pattern": "["}, cancellation=CancellationToken())  # type: ignore[arg-type]
    empty = await grep.execute({"pattern": "missing"}, cancellation=CancellationToken())  # type: ignore[arg-type]

    assert invalid.is_error is True
    assert invalid.content.startswith("Error: invalid regex:")
    assert empty.is_error is False
    assert empty.content == "No matches found."


@pytest.mark.asyncio
async def test_search_skips_external_file_and_directory_symlinks(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    (outside / "secret.py").write_text("needle\n", encoding="utf-8")
    try:
        (workspace / "secret.py").symlink_to(outside / "secret.py")
        (workspace / "outside-dir").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks not available in this environment")
    _, glob, grep = _search_tools(workspace)

    glob_result = await glob.execute({"pattern": "**/*.py"}, cancellation=CancellationToken())  # type: ignore[arg-type]
    grep_result = await grep.execute(
        {"pattern": "needle", "include": "*.py"},  # type: ignore[arg-type]
        cancellation=CancellationToken(),
    )

    assert glob_result.content == "No files matched the pattern."
    assert grep_result.content == "No matches found."


@pytest.mark.asyncio
async def test_search_order_is_stable_and_output_truncates_in_core(tmp_path: Path) -> None:
    for name in ["z.txt", "a.txt", "m.txt"]:
        (tmp_path / name).write_text("needle\n", encoding="utf-8")
    resolver, _, grep = _search_tools(tmp_path)
    first = await grep.execute({"pattern": "needle"}, cancellation=CancellationToken())  # type: ignore[arg-type]
    second = await grep.execute({"pattern": "needle"}, cancellation=CancellationToken())  # type: ignore[arg-type]
    registry = ToolRegistry((GrepTool(resolver),))
    executor = ToolExecutor(registry)

    truncated = await executor.execute_batch(
        (ToolCallPart("grep-1", "Grep", {"pattern": "needle"}),),
        cancellation=CancellationToken(),
    )

    assert first.content == second.content == "a.txt:1:needle\nm.txt:1:needle\nz.txt:1:needle"
    assert truncated[0].is_error is False


@pytest.mark.asyncio
async def test_large_search_output_is_truncated_by_core_executor(tmp_path: Path) -> None:
    (tmp_path / "large.txt").write_text(("x" * 200 + "\n") * 100, encoding="utf-8")
    registry = ToolRegistry((GrepTool(WorkspacePathResolver(tmp_path)),))
    executor = ToolExecutor(registry)

    results = await executor.execute_batch(
        (ToolCallPart("large-grep", "Grep", {"pattern": "x+"}),),
        cancellation=CancellationToken(),
    )

    assert results[0].is_error is False
    assert results[0].content.endswith("\n[Output truncated to 10000 characters]")
