from __future__ import annotations

from pathlib import Path

import pytest

from uthcode.core import (
    CancellationToken,
    PreparedToolCall,
    ToolCallPart,
    ToolExecutor,
    ToolRegistry,
    ToolResultPart,
)
from uthcode.core.permission import Effect, ResourceScope
from uthcode.core.tool import ToolPlanningAccess, ToolPlanningMetadata
from uthcode.integrations.tools.search_tools import GlobTool, GrepTool
from uthcode.integrations.tools.workspace import WorkspacePathResolver


def _search_tools(root: Path):
    resolver = WorkspacePathResolver(root)
    return resolver, GlobTool(resolver), GrepTool(resolver)


async def _execute_prepared_calls(
    executor: ToolExecutor,
    calls: tuple[ToolCallPart, ...],
    *,
    cancellation: CancellationToken,
) -> tuple[ToolResultPart, ...]:
    results: list[ToolResultPart] = []
    for call in calls:
        prepared = executor.prepare_call(call, cancellation=cancellation)
        if isinstance(prepared, ToolResultPart):
            results.append(prepared)
        else:
            assert isinstance(prepared, PreparedToolCall)
            results.append(
                await executor.execute_prepared(
                    prepared,
                    cancellation=cancellation,
                )
            )
    return tuple(results)


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


def test_search_tools_preflight_produces_read_actions(tmp_path: Path) -> None:
    resolver, glob, grep = _search_tools(tmp_path)

    glob_action = glob.preflight({"pattern": "**/*.py"}).action  # type: ignore[arg-type]
    grep_action = grep.preflight({"pattern": "needle", "path": "."}).action  # type: ignore[arg-type]

    assert (glob_action.effect, glob_action.scope) == (Effect.READ, ResourceScope.INSIDE)
    assert (grep_action.effect, grep_action.scope) == (Effect.READ, ResourceScope.INSIDE)
    assert glob_action.action == "glob"
    assert grep_action.action == "grep"
    assert glob_action.resource == grep_action.resource == "."
    assert resolver.root == tmp_path.resolve()


def test_search_tools_are_explicitly_plan_visible_without_wire_metadata(
    tmp_path: Path,
) -> None:
    _, glob, grep = _search_tools(tmp_path)

    assert isinstance(glob, ToolPlanningMetadata)
    assert isinstance(grep, ToolPlanningMetadata)
    assert glob.planning_access is ToolPlanningAccess.READ_ONLY
    assert grep.planning_access is ToolPlanningAccess.READ_ONLY
    assert "planning_access" not in glob.definition.to_dict()
    assert "planning_access" not in grep.definition.to_dict()


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
async def test_prepared_glob_binds_file_symlink_targets(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside.txt"
    workspace.mkdir()
    inside = workspace / "inside.txt"
    inside.write_text("inside marker\n", encoding="utf-8")
    outside.write_text("outside marker\n", encoding="utf-8")
    alias = workspace / "alias.txt"
    try:
        alias.symlink_to(inside)
    except OSError:
        pytest.skip("symlinks not available in this environment")

    resolver = WorkspacePathResolver(workspace)
    registry = ToolRegistry((GlobTool(resolver),))
    executor = ToolExecutor(registry)
    prepared = executor.prepare_call(
        ToolCallPart("glob-link", "Glob", {"pattern": "**/*.txt", "path": "."}),
        cancellation=CancellationToken(),
    )
    assert isinstance(prepared, PreparedToolCall)
    assert prepared.action.resource == "."

    alias.unlink()
    alias.symlink_to(outside)
    result = await executor.execute_prepared(prepared, cancellation=CancellationToken())

    assert result.is_error is False
    assert result.content == "inside.txt"
    assert "outside.txt" not in result.content


@pytest.mark.asyncio
async def test_prepared_grep_binds_file_symlink_targets(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside.txt"
    workspace.mkdir()
    inside = workspace / "inside.txt"
    inside.write_text("inside marker\n", encoding="utf-8")
    outside.write_text("outside marker\n", encoding="utf-8")
    alias = workspace / "alias.txt"
    try:
        alias.symlink_to(inside)
    except OSError:
        pytest.skip("symlinks not available in this environment")

    resolver = WorkspacePathResolver(workspace)
    registry = ToolRegistry((GrepTool(resolver),))
    executor = ToolExecutor(registry)
    prepared = executor.prepare_call(
        ToolCallPart("grep-link", "Grep", {"pattern": "marker", "path": "."}),
        cancellation=CancellationToken(),
    )
    assert isinstance(prepared, PreparedToolCall)

    alias.unlink()
    alias.symlink_to(outside)
    result = await executor.execute_prepared(prepared, cancellation=CancellationToken())

    assert result.is_error is False
    assert "inside.txt:1:inside marker" in result.content
    assert "outside marker" not in result.content


@pytest.mark.asyncio
async def test_prepared_grep_binds_directory_symlink_target(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    original = tmp_path / "original-outside"
    replacement = tmp_path / "replacement-outside"
    workspace.mkdir()
    original.mkdir()
    replacement.mkdir()
    (original / "original.txt").write_text("original marker\n", encoding="utf-8")
    (replacement / "replacement.txt").write_text("replacement marker\n", encoding="utf-8")
    alias = workspace / "alias-dir"
    try:
        alias.symlink_to(original, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks not available in this environment")

    resolver = WorkspacePathResolver(workspace)
    registry = ToolRegistry((GrepTool(resolver),))
    executor = ToolExecutor(registry)
    prepared = executor.prepare_call(
        ToolCallPart("grep-dir-link", "Grep", {"pattern": "marker", "path": "alias-dir"}),
        cancellation=CancellationToken(),
    )
    assert isinstance(prepared, PreparedToolCall)
    assert prepared.action.resource == original.resolve().as_posix()
    assert prepared.action.scope is ResourceScope.OUTSIDE

    alias.unlink()
    alias.symlink_to(replacement, target_is_directory=True)
    result = await executor.execute_prepared(prepared, cancellation=CancellationToken())

    assert result.is_error is False
    assert "original.txt:1:original marker" in result.content
    assert "replacement marker" not in result.content


@pytest.mark.asyncio
async def test_search_can_read_an_outside_directory_after_scope_classification(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    (outside / "outside.txt").write_text("outside needle\n", encoding="utf-8")
    resolver, glob, grep = _search_tools(workspace)

    glob_action = glob.preflight({"pattern": "**/*.txt", "path": str(outside)}).action  # type: ignore[arg-type]
    grep_action = grep.preflight({"pattern": "needle", "path": str(outside)}).action  # type: ignore[arg-type]
    assert glob_action.scope is ResourceScope.OUTSIDE
    assert grep_action.scope is ResourceScope.OUTSIDE

    glob_result = await glob.execute(
        {"pattern": "**/*.txt", "path": str(outside)},  # type: ignore[arg-type]
        cancellation=CancellationToken(),
    )
    grep_result = await grep.execute(
        {"pattern": "needle", "path": str(outside)},  # type: ignore[arg-type]
        cancellation=CancellationToken(),
    )
    assert glob_result.is_error is False
    assert "outside.txt" in glob_result.content
    assert grep_result.is_error is False
    assert "outside.txt:1:outside needle" in grep_result.content
    assert resolver.scope_of(outside) is ResourceScope.OUTSIDE


@pytest.mark.asyncio
async def test_search_order_is_stable_and_output_truncates_in_core(tmp_path: Path) -> None:
    for name in ["z.txt", "a.txt", "m.txt"]:
        (tmp_path / name).write_text("needle\n", encoding="utf-8")
    resolver, _, grep = _search_tools(tmp_path)
    first = await grep.execute({"pattern": "needle"}, cancellation=CancellationToken())  # type: ignore[arg-type]
    second = await grep.execute({"pattern": "needle"}, cancellation=CancellationToken())  # type: ignore[arg-type]
    registry = ToolRegistry((GrepTool(resolver),))
    executor = ToolExecutor(registry)

    truncated = await _execute_prepared_calls(
        executor,
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

    results = await _execute_prepared_calls(
        executor,
        (ToolCallPart("large-grep", "Grep", {"pattern": "x+"}),),
        cancellation=CancellationToken(),
    )

    assert results[0].is_error is False
    assert results[0].content.endswith("\n[Output truncated to 10000 characters]")
