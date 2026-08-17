from __future__ import annotations

import os
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
from uthcode.integrations.tools.file_tools import (
    EditFileTool,
    ReadFileTool,
    WriteFileTool,
)
from uthcode.integrations.tools.factory import create_default_tools
from uthcode.integrations.tools.workspace import (
    FileReadTracker,
    WorkspacePathError,
    WorkspacePathResolver,
)


def _tools(root: Path):
    resolver = WorkspacePathResolver(root)
    tracker = FileReadTracker()
    return resolver, tracker, ReadFileTool(resolver, tracker), WriteFileTool(resolver, tracker), EditFileTool(resolver, tracker)


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


def test_workspace_resolver_resolves_outside_scope_and_rejects_null(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside.txt"
    workspace.mkdir()
    outside.write_text("outside", encoding="utf-8")
    resolver = WorkspacePathResolver(workspace)

    for value in ("bad\x00path",):
        with pytest.raises(WorkspacePathError):
            resolver.resolve(value)

    resolved, scope = resolver.resolve_with_scope("../outside.txt")
    assert resolved == outside.resolve()
    assert scope is ResourceScope.OUTSIDE
    assert resolver.display(resolved) == outside.resolve().as_posix()


def test_workspace_resolver_allows_new_nested_path_and_displays_posix_relative(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    resolver = WorkspacePathResolver(workspace)

    resolved = resolver.resolve("nested\\file.txt")

    assert resolved == workspace / "nested" / "file.txt"
    assert resolver.display(resolved) == "nested/file.txt"


def test_workspace_resolver_classifies_file_and_directory_symlinks_to_outside(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    (outside / "secret.txt").write_text("secret", encoding="utf-8")
    try:
        (workspace / "secret.txt").symlink_to(outside / "secret.txt")
        (workspace / "directory").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks not available in this environment")

    resolver = WorkspacePathResolver(workspace)
    resolved_file, file_scope = resolver.resolve_with_scope("secret.txt")
    assert resolved_file == (outside / "secret.txt").resolve()
    assert file_scope is ResourceScope.OUTSIDE
    resolved_directory, directory_scope = resolver.resolve_with_scope(
        "directory/secret.txt"
    )
    assert resolved_directory == (outside / "secret.txt").resolve()
    assert directory_scope is ResourceScope.OUTSIDE


def test_file_tools_preflight_produces_trusted_effect_and_ignores_pseudo_effect(
    tmp_path: Path,
) -> None:
    resolver = WorkspacePathResolver(tmp_path)
    tracker = FileReadTracker()
    read = ReadFileTool(resolver, tracker)
    write = WriteFileTool(resolver, tracker)
    edit = EditFileTool(resolver, tracker)

    read_action = read.preflight({"path": "note.txt", "effect": "write"}).action  # type: ignore[arg-type]
    write_action = write.preflight({"path": "note.txt", "effect": "read"}).action  # type: ignore[arg-type]
    edit_action = edit.preflight({"path": "note.txt"}).action  # type: ignore[arg-type]

    assert (read_action.effect, read_action.scope) == (Effect.READ, ResourceScope.INSIDE)
    assert (write_action.effect, write_action.scope) == (Effect.WRITE, ResourceScope.INSIDE)
    assert (edit_action.effect, edit_action.scope) == (Effect.WRITE, ResourceScope.INSIDE)
    assert read_action.resource == write_action.resource == edit_action.resource == "note.txt"


def test_file_tools_declare_planning_access_without_provider_wire_metadata(
    tmp_path: Path,
) -> None:
    _, _, read, write, edit = _tools(tmp_path)

    assert all(isinstance(tool, ToolPlanningMetadata) for tool in (read, write, edit))
    assert read.planning_access is ToolPlanningAccess.READ_ONLY
    assert write.planning_access is ToolPlanningAccess.HIDDEN
    assert edit.planning_access is ToolPlanningAccess.HIDDEN
    assert all(
        "planning_access" not in tool.definition.to_dict()
        for tool in (read, write, edit)
    )


def test_default_tool_factory_returns_only_explicit_planning_metadata(
    tmp_path: Path,
) -> None:
    tools = create_default_tools(tmp_path)

    assert tuple(tool.definition.name for tool in tools) == (
        "ReadFile",
        "WriteFile",
        "EditFile",
        "Glob",
        "Grep",
        "Bash",
    )
    assert all(isinstance(tool, ToolPlanningMetadata) for tool in tools)


def test_tracker_requires_read_and_detects_content_change_with_restored_mtime(
    tmp_path: Path,
) -> None:
    target = tmp_path / "file.txt"
    target.write_text("before", encoding="utf-8")
    tracker = FileReadTracker()
    assert tracker.check(target) == (
        False,
        "Error: file has not been read yet. Read it first before editing.",
    )

    original = target.stat()
    tracker.record(target, "before", original.st_mtime_ns)
    target.write_text("after", encoding="utf-8")
    os.utime(target, ns=(original.st_atime_ns, original.st_mtime_ns))

    assert tracker.check(target) == (
        False,
        "Error: file has been modified since last read. Read it again before editing.",
    )


@pytest.mark.asyncio
async def test_read_file_returns_one_based_pages_and_records_state(tmp_path: Path) -> None:
    target = tmp_path / "file.txt"
    target.write_text("one\ntwo\nthree\n", encoding="utf-8")
    _, tracker, read, _, _ = _tools(tmp_path)

    result = await read.execute(
        {"path": "file.txt", "offset": 2, "limit": 1},  # type: ignore[arg-type]
        cancellation=CancellationToken(),
    )

    assert result == type(result)("2\ttwo")
    assert tracker.check(target) == (True, "")


@pytest.mark.asyncio
async def test_prepared_read_binds_the_original_physical_symlink_target(
    tmp_path: Path,
) -> None:
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
    tracker = FileReadTracker()
    registry = ToolRegistry((ReadFileTool(resolver, tracker),))
    executor = ToolExecutor(registry)
    prepared = executor.prepare_call(
        ToolCallPart("read-link", "ReadFile", {"path": "alias.txt"}),
        cancellation=CancellationToken(),
    )
    assert isinstance(prepared, PreparedToolCall)
    assert prepared.action.resource == "inside.txt"

    alias.unlink()
    alias.symlink_to(outside)
    result = await executor.execute_prepared(prepared, cancellation=CancellationToken())

    assert result.is_error is False
    assert "inside marker" in result.content
    assert "outside marker" not in result.content


@pytest.mark.asyncio
async def test_prepared_write_binds_the_original_physical_symlink_target(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside.txt"
    workspace.mkdir()
    inside = workspace / "inside.txt"
    inside.write_text("before\n", encoding="utf-8")
    outside.write_text("outside stays\n", encoding="utf-8")
    alias = workspace / "alias.txt"
    try:
        alias.symlink_to(inside)
    except OSError:
        pytest.skip("symlinks not available in this environment")

    resolver = WorkspacePathResolver(workspace)
    tracker = FileReadTracker()
    read = ReadFileTool(resolver, tracker)
    registry = ToolRegistry((WriteFileTool(resolver, tracker),))
    executor = ToolExecutor(registry)
    await read.execute({"path": "alias.txt"}, cancellation=CancellationToken())  # type: ignore[arg-type]
    prepared = executor.prepare_call(
        ToolCallPart("write-link", "WriteFile", {"path": "alias.txt", "content": "inside changed\n"}),
        cancellation=CancellationToken(),
    )
    assert isinstance(prepared, PreparedToolCall)
    assert prepared.action.resource == "inside.txt"

    alias.unlink()
    alias.symlink_to(outside)
    result = await executor.execute_prepared(prepared, cancellation=CancellationToken())

    assert result.is_error is False
    assert inside.read_text(encoding="utf-8") == "inside changed\n"
    assert outside.read_text(encoding="utf-8") == "outside stays\n"


@pytest.mark.asyncio
async def test_prepared_edit_binds_the_original_physical_symlink_target(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside.txt"
    workspace.mkdir()
    inside = workspace / "inside.txt"
    inside.write_text("before\n", encoding="utf-8")
    outside.write_text("outside stays\n", encoding="utf-8")
    alias = workspace / "alias.txt"
    try:
        alias.symlink_to(inside)
    except OSError:
        pytest.skip("symlinks not available in this environment")

    resolver = WorkspacePathResolver(workspace)
    tracker = FileReadTracker()
    read = ReadFileTool(resolver, tracker)
    registry = ToolRegistry((EditFileTool(resolver, tracker),))
    executor = ToolExecutor(registry)
    await read.execute({"path": "alias.txt"}, cancellation=CancellationToken())  # type: ignore[arg-type]
    prepared = executor.prepare_call(
        ToolCallPart(
            "edit-link",
            "EditFile",
            {"path": "alias.txt", "old_string": "before", "new_string": "inside changed"},
        ),
        cancellation=CancellationToken(),
    )
    assert isinstance(prepared, PreparedToolCall)
    assert prepared.action.resource == "inside.txt"

    alias.unlink()
    alias.symlink_to(outside)
    result = await executor.execute_prepared(prepared, cancellation=CancellationToken())

    assert result.is_error is False
    assert inside.read_text(encoding="utf-8") == "inside changed\n"
    assert outside.read_text(encoding="utf-8") == "outside stays\n"


@pytest.mark.asyncio
async def test_file_tools_can_operate_on_outside_target_after_scope_classification(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside.txt"
    workspace.mkdir()
    outside.write_text("outside", encoding="utf-8")
    resolver, tracker, read, write, _ = _tools(workspace)

    action = read.preflight({"path": str(outside)}).action  # type: ignore[arg-type]
    assert action.scope is ResourceScope.OUTSIDE

    read_result = await read.execute(
        {"path": str(outside)},  # type: ignore[arg-type]
        cancellation=CancellationToken(),
    )
    assert read_result.is_error is False
    assert read_result.content == "1\toutside"
    assert tracker.check(outside) == (True, "")

    write_action = write.preflight({"path": str(outside)}).action  # type: ignore[arg-type]
    assert write_action.scope is ResourceScope.OUTSIDE
    write_result = await write.execute(
        {"path": str(outside), "content": "changed"},  # type: ignore[arg-type]
        cancellation=CancellationToken(),
    )
    assert write_result.is_error is False
    assert outside.read_text(encoding="utf-8") == "changed"


@pytest.mark.asyncio
async def test_read_file_reports_empty_missing_directory_and_encoding_errors(
    tmp_path: Path,
) -> None:
    (tmp_path / "empty.txt").write_text("", encoding="utf-8")
    (tmp_path / "folder").mkdir()
    (tmp_path / "binary.txt").write_bytes(b"\xff\xfe")
    _, _, read, _, _ = _tools(tmp_path)
    cancellation = CancellationToken()

    empty = await read.execute({"path": "empty.txt"}, cancellation=cancellation)  # type: ignore[arg-type]
    missing = await read.execute({"path": "missing.txt"}, cancellation=cancellation)  # type: ignore[arg-type]
    directory = await read.execute({"path": "folder"}, cancellation=cancellation)  # type: ignore[arg-type]
    binary = await read.execute({"path": "binary.txt"}, cancellation=cancellation)  # type: ignore[arg-type]

    assert empty.is_error is False
    assert empty.content == ""
    assert missing.is_error is True
    assert "file not found" in missing.content
    assert directory.is_error is True
    assert "not a file" in directory.content
    assert binary.is_error is True
    assert "failed to read file" in binary.content


@pytest.mark.asyncio
async def test_write_new_file_creates_parents_but_existing_file_requires_read(
    tmp_path: Path,
) -> None:
    _, _, _, write, _ = _tools(tmp_path)
    cancellation = CancellationToken()

    created = await write.execute(
        {"path": "new/nested/file.txt", "content": "hello"},  # type: ignore[arg-type]
        cancellation=cancellation,
    )
    assert created.is_error is False
    assert (tmp_path / "new" / "nested" / "file.txt").read_text(encoding="utf-8") == "hello"

    repeated = await write.execute(
        {"path": "new/nested/file.txt", "content": "changed"},  # type: ignore[arg-type]
        cancellation=cancellation,
    )
    assert repeated.is_error is False
    assert (tmp_path / "new" / "nested" / "file.txt").read_text(encoding="utf-8") == "changed"


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["change", "delete", "replace"])
async def test_write_rejects_external_change_delete_and_replace(
    tmp_path: Path,
    mutation: str,
) -> None:
    target = tmp_path / "file.txt"
    target.write_text("before", encoding="utf-8")
    _, _, read, write, _ = _tools(tmp_path)
    cancellation = CancellationToken()
    await read.execute({"path": "file.txt"}, cancellation=cancellation)  # type: ignore[arg-type]

    if mutation == "change":
        target.write_text("external", encoding="utf-8")
    elif mutation == "delete":
        target.unlink()
    else:
        replacement = tmp_path / "replacement.txt"
        replacement.write_text("replacement", encoding="utf-8")
        target.unlink()
        replacement.replace(target)

    result = await write.execute(
        {"path": "file.txt", "content": "new"},  # type: ignore[arg-type]
        cancellation=cancellation,
    )

    assert result.is_error is True
    assert "modified since last read" in result.content
    assert target.read_text(encoding="utf-8") != "new" if target.exists() else True


@pytest.mark.asyncio
async def test_edit_requires_unique_nonempty_old_string_and_refreshes_tracker(
    tmp_path: Path,
) -> None:
    target = tmp_path / "file.txt"
    target.write_text("one two two", encoding="utf-8")
    _, tracker, read, _, edit = _tools(tmp_path)
    cancellation = CancellationToken()
    await read.execute({"path": "file.txt"}, cancellation=cancellation)  # type: ignore[arg-type]

    empty = await edit.execute(
        {"path": "file.txt", "old_string": "", "new_string": "x"},  # type: ignore[arg-type]
        cancellation=cancellation,
    )
    missing = await edit.execute(
        {"path": "file.txt", "old_string": "absent", "new_string": "x"},  # type: ignore[arg-type]
        cancellation=cancellation,
    )
    duplicate = await edit.execute(
        {"path": "file.txt", "old_string": "two", "new_string": "x"},  # type: ignore[arg-type]
        cancellation=cancellation,
    )
    success = await edit.execute(
        {"path": "file.txt", "old_string": "one", "new_string": "ONE"},  # type: ignore[arg-type]
        cancellation=cancellation,
    )

    assert empty.is_error is True
    assert missing.content == "Error: old_string not found in file"
    assert duplicate.content == "Error: old_string found 2 times, must be unique"
    assert success.is_error is False
    assert target.read_text(encoding="utf-8") == "ONE two two"
    assert tracker.check(target) == (True, "")


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["change", "delete", "replace"])
async def test_edit_rejects_external_file_state_before_side_effect(
    tmp_path: Path,
    mutation: str,
) -> None:
    target = tmp_path / "file.txt"
    target.write_text("before", encoding="utf-8")
    _, _, read, _, edit = _tools(tmp_path)
    cancellation = CancellationToken()
    await read.execute({"path": "file.txt"}, cancellation=cancellation)  # type: ignore[arg-type]

    if mutation == "change":
        target.write_text("external", encoding="utf-8")
    elif mutation == "delete":
        target.unlink()
    else:
        replacement = tmp_path / "replacement.txt"
        replacement.write_text("replacement", encoding="utf-8")
        target.unlink()
        replacement.replace(target)

    result = await edit.execute(
        {"path": "file.txt", "old_string": "before", "new_string": "after"},  # type: ignore[arg-type]
        cancellation=cancellation,
    )

    assert result.is_error is True
    assert "file not found" in result.content if mutation == "delete" else "modified since last read" in result.content
    assert target.read_text(encoding="utf-8") != "after" if target.exists() else True


@pytest.mark.asyncio
async def test_cancelled_write_has_no_file_side_effect(tmp_path: Path) -> None:
    target = tmp_path / "file.txt"
    target.write_text("before", encoding="utf-8")
    _, _, read, write, _ = _tools(tmp_path)
    await read.execute({"path": "file.txt"}, cancellation=CancellationToken())  # type: ignore[arg-type]
    cancellation = CancellationToken()
    cancellation.cancel()

    result = await write.execute(
        {"path": "file.txt", "content": "after"},  # type: ignore[arg-type]
        cancellation=cancellation,
    )

    assert result.is_error is True
    assert target.read_text(encoding="utf-8") == "before"


@pytest.mark.asyncio
async def test_file_output_reaches_application_materialization_unchanged(tmp_path: Path) -> None:
    target = tmp_path / "large.txt"
    target.write_text("x" * 11_000, encoding="utf-8")
    resolver = WorkspacePathResolver(tmp_path)
    tracker = FileReadTracker()
    registry = ToolRegistry((ReadFileTool(resolver, tracker),))
    executor = ToolExecutor(registry)

    results = await _execute_prepared_calls(
        executor,
        (ToolCallPart("read-1", "ReadFile", {"path": "large.txt"}),),
        cancellation=CancellationToken(),
    )

    assert results[0].is_error is False
    assert len(results[0].content) > 10_000
    assert "[Output truncated" not in results[0].content
