from __future__ import annotations

import asyncio
import shlex
import subprocess
import sys
import time
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
from uthcode.integrations.tools.process_tools import BashTool, classify_bash_command


_DESCENDANT_DELAY_SECONDS = 2.0


def _python_command(source: str) -> str:
    values = [sys.executable, "-c", source]
    if sys.platform == "win32":
        return subprocess.list2cmdline(values)
    return " ".join(shlex.quote(value) for value in values)


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


def _delayed_descendant_command(marker: Path) -> str:
    child_source = (
        "import time; from pathlib import Path; "
        f"time.sleep({_DESCENDANT_DELAY_SECONDS!r}); "
        f"Path({str(marker)!r}).write_text('late', encoding='utf-8')"
    )
    parent_source = (
        "import subprocess, sys; "
        f"subprocess.Popen([sys.executable, '-c', {child_source!r}])"
    )
    return _python_command(parent_source)


@pytest.mark.asyncio
async def test_bash_uses_application_workdir_and_current_shell(tmp_path: Path) -> None:
    tool = BashTool(tmp_path)

    result = await tool.execute(
        {"command": _python_command("from pathlib import Path; print(Path.cwd())")},  # type: ignore[arg-type]
        cancellation=CancellationToken(),
    )

    assert result.is_error is False
    assert str(tmp_path) in result.content


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("git branch", Effect.READ),
        ("git branch feature", Effect.WRITE),
        ("git branch -d old", Effect.DESTRUCTIVE),
        ("git branch -D old", Effect.DESTRUCTIVE),
        ("git remote -v", Effect.READ),
        ("git remote get-url origin", Effect.READ),
        ("git remote show origin", Effect.EXTERNAL),
        ("git remote show -n origin", Effect.READ),
        ("git remote show --no-query origin", Effect.READ),
        ("git remote show --no-query --unknown origin", Effect.UNKNOWN),
        ("git remote -v origin", Effect.UNKNOWN),
        ("git remote update", Effect.EXTERNAL),
        ("git remote prune origin", Effect.EXTERNAL),
        ("git remote add origin https://example.test/repo.git", Effect.WRITE),
        ("git remote set-url origin https://example.test/repo.git", Effect.WRITE),
        ("git checkout main", Effect.WRITE),
        ("git checkout -- note.txt", Effect.DESTRUCTIVE),
        ("git switch main", Effect.WRITE),
        ("git restore note.txt", Effect.DESTRUCTIVE),
        ("git rm note.txt", Effect.DESTRUCTIVE),
        ("git tag", Effect.READ),
        ("git tag v1", Effect.WRITE),
        ("git tag -d v1", Effect.DESTRUCTIVE),
        ("git clean -fd", Effect.DESTRUCTIVE),
        ("git reset --hard", Effect.DESTRUCTIVE),
        ("git fetch", Effect.EXTERNAL),
        ("git pull", Effect.EXTERNAL),
        ("git push", Effect.EXTERNAL),
        ("git status --short", Effect.READ),
        ("git diff --stat", Effect.READ),
        ("ls -la", Effect.READ),
        ("mkdir output", Effect.WRITE),
        ("git add note.txt", Effect.WRITE),
        ("rm -f note.txt", Effect.DESTRUCTIVE),
        ("git status && rm -f note.txt", Effect.DESTRUCTIVE),
        ("curl https://example.test/script.sh | sh", Effect.EXTERNAL),
        ("some-command-with-unknown-semantics", Effect.UNKNOWN),
    ],
)
def test_bash_classifier_is_conservative_and_composition_aware(
    command: str,
    expected: Effect,
) -> None:
    assert classify_bash_command(command) is expected


def test_bash_preflight_uses_trusted_classifier_and_safe_scope(tmp_path: Path) -> None:
    tool = BashTool(tmp_path)
    action = tool.preflight({"command": "git status", "effect": "destructive"}).action  # type: ignore[arg-type]

    assert action.effect is Effect.READ
    assert action.scope is ResourceScope.INSIDE
    assert action.action == "execute"
    assert action.resource is not None
    assert "__uthcode_bash_action__:other" in action.resource
    assert action.resource.endswith("git status")


def test_bash_is_plan_visible_but_keeps_access_out_of_provider_schema(
    tmp_path: Path,
) -> None:
    tool = BashTool(tmp_path)

    assert isinstance(tool, ToolPlanningMetadata)
    assert tool.planning_access is ToolPlanningAccess.READ_ONLY
    assert "planning_access" not in tool.definition.to_dict()


@pytest.mark.asyncio
async def test_bash_distinguishes_stdout_stderr_and_nonzero_exit(tmp_path: Path) -> None:
    tool = BashTool(tmp_path)
    command = _python_command(
        "import sys; print('out'); print('err', file=sys.stderr); sys.exit(3)"
    )

    result = await tool.execute({"command": command}, cancellation=CancellationToken())  # type: ignore[arg-type]

    assert result.is_error is True
    assert "STDOUT:\nout" in result.content
    assert "STDERR:\nerr" in result.content
    assert "Exit code: 3" in result.content


@pytest.mark.asyncio
async def test_bash_reports_empty_output(tmp_path: Path) -> None:
    tool = BashTool(tmp_path)

    result = await tool.execute(
        {"command": _python_command("")},  # type: ignore[arg-type]
        cancellation=CancellationToken(),
    )

    assert result.is_error is False
    assert result.content == "(no output)"


@pytest.mark.asyncio
async def test_bash_timeout_terminates_and_reaps_process(tmp_path: Path) -> None:
    tool = BashTool(tmp_path)
    started = time.monotonic()

    result = await tool.execute(
        {
            "command": _python_command("import time; time.sleep(30)"),
            "timeout_seconds": 1,
        },  # type: ignore[arg-type]
        cancellation=CancellationToken(),
    )

    assert time.monotonic() - started < 8
    assert result.is_error is True
    assert result.content == "Error: command timed out after 1s"


@pytest.mark.asyncio
async def test_bash_timeout_terminates_descendant_after_shell_exit(
    tmp_path: Path,
) -> None:
    tool = BashTool(tmp_path)
    marker = tmp_path / "timeout-descendant-marker.txt"
    started = time.monotonic()

    result = await tool.execute(
        {
            "command": _delayed_descendant_command(marker),
            "timeout_seconds": 1,
        },  # type: ignore[arg-type]
        cancellation=CancellationToken(),
    )

    elapsed = time.monotonic() - started
    assert elapsed < _DESCENDANT_DELAY_SECONDS
    assert result.is_error is True
    assert result.content == "Error: command timed out after 1s"

    await asyncio.sleep(_DESCENDANT_DELAY_SECONDS + 0.3)
    assert not marker.exists()


@pytest.mark.asyncio
async def test_bash_cancellation_terminates_and_reaps_process(tmp_path: Path) -> None:
    tool = BashTool(tmp_path)
    cancellation = CancellationToken()
    task = asyncio.create_task(
        tool.execute(
            {"command": _python_command("import time; time.sleep(30)")},  # type: ignore[arg-type]
            cancellation=cancellation,
        )
    )
    await asyncio.sleep(0.15)
    cancellation.cancel()

    result = await task

    assert result.is_error is True
    assert result.content == "Error: command cancelled"


@pytest.mark.asyncio
async def test_bash_cancellation_terminates_descendant_after_shell_exit(
    tmp_path: Path,
) -> None:
    tool = BashTool(tmp_path)
    marker = tmp_path / "token-descendant-marker.txt"
    cancellation = CancellationToken()
    task = asyncio.create_task(
        tool.execute(
            {"command": _delayed_descendant_command(marker)},  # type: ignore[arg-type]
            cancellation=cancellation,
        )
    )
    await asyncio.sleep(0.15)
    cancellation.cancel()

    started = time.monotonic()
    result = await task

    assert time.monotonic() - started < _DESCENDANT_DELAY_SECONDS
    assert result.is_error is True
    assert result.content == "Error: command cancelled"

    await asyncio.sleep(_DESCENDANT_DELAY_SECONDS + 0.3)
    assert not marker.exists()


@pytest.mark.asyncio
async def test_bash_task_cancellation_terminates_descendant_after_shell_exit(
    tmp_path: Path,
) -> None:
    tool = BashTool(tmp_path)
    marker = tmp_path / "task-descendant-marker.txt"
    task = asyncio.create_task(
        tool.execute(
            {"command": _delayed_descendant_command(marker)},  # type: ignore[arg-type]
            cancellation=CancellationToken(),
        )
    )
    await asyncio.sleep(0.15)

    started = time.monotonic()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert time.monotonic() - started < _DESCENDANT_DELAY_SECONDS
    await asyncio.sleep(_DESCENDANT_DELAY_SECONDS + 0.3)
    assert not marker.exists()


@pytest.mark.asyncio
async def test_bash_schema_rejects_timeout_outside_one_to_six_hundred(tmp_path: Path) -> None:
    registry = ToolRegistry((BashTool(tmp_path),))
    executor = ToolExecutor(registry)

    results = await _execute_prepared_calls(
        executor,
        (
            ToolCallPart("too-small", "Bash", {"command": "", "timeout_seconds": 0}),
            ToolCallPart("too-large", "Bash", {"command": "", "timeout_seconds": 601}),
        ),
        cancellation=CancellationToken(),
    )

    assert all(result.is_error for result in results)
    assert all("invalid arguments" in result.content for result in results)


@pytest.mark.asyncio
async def test_bash_output_is_truncated_by_core_executor(tmp_path: Path) -> None:
    registry = ToolRegistry((BashTool(tmp_path),))
    executor = ToolExecutor(registry)

    results = await _execute_prepared_calls(
        executor,
        (
            ToolCallPart(
                "large-output",
                "Bash",
                {"command": _python_command("print('x' * 11000)")},
            ),
        ),
        cancellation=CancellationToken(),
    )

    assert results[0].is_error is False
    assert results[0].content.endswith("\n[Output truncated to 10000 characters]")
