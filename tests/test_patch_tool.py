from __future__ import annotations

import os
from pathlib import Path

import pytest

from uthcode.core import CancellationToken
from uthcode.integrations.tools.patch_tools import ApplyPatchTool
from uthcode.integrations.tools.workspace import FileReadTracker, WorkspacePathResolver


def _tool(root: Path) -> tuple[ApplyPatchTool, FileReadTracker]:
    tracker = FileReadTracker()
    return ApplyPatchTool(WorkspacePathResolver(root), tracker), tracker


@pytest.mark.asyncio
async def test_patch_add_update_delete_and_move_use_read_facts(tmp_path: Path) -> None:
    tool, tracker = _tool(tmp_path)
    add = "*** Begin Patch\n*** Add File: added.txt\n+hello\n*** End Patch"
    preparation = tool.preflight({"patch": add})
    assert preparation.action.effect.value == "write"
    result = await tool.execute(preparation.execution_arguments, cancellation=CancellationToken())
    assert result.is_error is False
    assert (tmp_path / "added.txt").read_text(encoding="utf-8") == "hello"

    source = tmp_path / "source.txt"
    source.write_text("old\n", encoding="utf-8")
    tracker.record(source, "old\n")
    update = "*** Begin Patch\n*** Update File: source.txt\n@@\n-old\n+new\n*** End Patch"
    await tool.execute(tool.preflight({"patch": update}).execution_arguments, cancellation=CancellationToken())
    assert source.read_text(encoding="utf-8") == "new\n"

    tracker.record(source, "new\n")
    move = "*** Begin Patch\n*** Update File: source.txt\n*** Move to: moved.txt\n@@\n-new\n+moved\n*** End Patch"
    moved = await tool.execute(tool.preflight({"patch": move}).execution_arguments, cancellation=CancellationToken())
    assert moved.is_error is False
    assert not source.exists()
    assert (tmp_path / "moved.txt").read_text(encoding="utf-8") == "moved\n"

    tracker.record(tmp_path / "moved.txt", "moved\n")
    delete = "*** Begin Patch\n*** Delete File: moved.txt\n*** End Patch"
    deleted = await tool.execute(tool.preflight({"patch": delete}).execution_arguments, cancellation=CancellationToken())
    assert deleted.is_error is False
    assert not (tmp_path / "moved.txt").exists()


@pytest.mark.asyncio
async def test_patch_preflight_failures_make_no_change(tmp_path: Path) -> None:
    tool, tracker = _tool(tmp_path)
    target = tmp_path / "target.txt"
    target.write_text("same\n", encoding="utf-8")
    patch = "*** Begin Patch\n*** Update File: target.txt\n@@\n-missing\n+changed\n*** End Patch"
    with pytest.raises(ValueError):
        tool.preflight({"patch": patch})
    assert target.read_text(encoding="utf-8") == "same\n"

    tracker.record(target, "same\n")
    duplicate = "*** Begin Patch\n*** Update File: target.txt\n@@\n-same\n-one\n+changed\n*** Update File: target.txt\n@@\n-same\n+again\n*** End Patch"
    with pytest.raises(ValueError):
        tool.preflight({"patch": duplicate})
    assert target.read_text(encoding="utf-8") == "same\n"


@pytest.mark.asyncio
async def test_patch_partial_commit_reports_applied_and_not_applied(tmp_path: Path) -> None:
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("one\n", encoding="utf-8")
    second.write_text("two\n", encoding="utf-8")

    class FailingTool(ApplyPatchTool):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, **kwargs)  # type: ignore[arg-type]
            self._count = 0

        def _commit(self, operation):  # type: ignore[no-untyped-def]
            self._count += 1
            if self._count == 2:
                raise OSError("synthetic commit failure")
            return super()._commit(operation)

    tracker = FileReadTracker()
    tracker.record(first, "one\n")
    tracker.record(second, "two\n")
    tool = FailingTool(WorkspacePathResolver(tmp_path), tracker)
    patch = "*** Begin Patch\n*** Update File: first.txt\n@@\n-one\n+ONE\n*** Update File: second.txt\n@@\n-two\n+TWO\n*** End Patch"
    # Full preflight succeeds; the injected failure occurs only during commit.
    result = await tool.execute(tool.preflight({"patch": patch}).execution_arguments, cancellation=CancellationToken())
    assert result.is_error is True
    assert result.details["applied"] == ["first.txt"]
    assert result.details["not_applied"] == []
    assert first.read_text(encoding="utf-8") == "ONE\n"
    assert second.read_text(encoding="utf-8") == "two\n"


@pytest.mark.asyncio
async def test_patch_windows_case_alias_is_one_physical_target_before_any_change(
    tmp_path: Path,
) -> None:
    if os.name != "nt":
        pytest.skip("Windows physical case alias contract")
    source = tmp_path / "Foo.txt"
    source.write_text("same\n", encoding="utf-8")
    tracker = FileReadTracker()
    tracker.record(source, "same\n")
    tool = ApplyPatchTool(WorkspacePathResolver(tmp_path), tracker)
    patch = (
        "*** Begin Patch\n"
        "*** Update File: Foo.txt\n"
        "*** Move to: foo.txt\n"
        "@@\n"
        "-same\n"
        "+changed\n"
        "*** End Patch"
    )

    with pytest.raises(ValueError, match="target conflict"):
        tool.preflight({"patch": patch})
    assert source.read_text(encoding="utf-8") == "same\n"
