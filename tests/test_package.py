from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
import textwrap
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
        AgentExecutionSegment,
        AgentEvent,
        AgentLoop,
        AgentLoopConfig,
        AgentTurnExecution,
        RunSnapshot,
        RunState,
        TurnResult,
    )

    assert AgentEvent is not None
    assert AgentExecutionSegment is not None
    assert AgentLoop is not None
    assert AgentLoopConfig is not None
    assert AgentTurnExecution is not None
    assert RunSnapshot is not None
    assert RunState is not None
    assert TurnResult is not None


def test_core_exposes_interaction_contract_without_internal_coordination_types() -> None:
    import uthcode.core as core
    from uthcode.core import (
        ASK_USER_TOOL_DEFINITION,
        PauseKind,
        PauseReason,
        PauseRequest,
        PauseResponse,
        QuestionKind,
        QuestionOption,
        RetryProviderResponse,
        ResumeTurnResponse,
        TurnPaused,
        TurnPausing,
        TurnResumed,
        UserInputRequest,
        UserInputResponse,
        UserInputRequested,
        UserQuestion,
    )

    assert all(
        value is not None
        for value in (
            ASK_USER_TOOL_DEFINITION,
            PauseKind,
            PauseReason,
            PauseRequest,
            PauseResponse,
            QuestionKind,
            QuestionOption,
            RetryProviderResponse,
            ResumeTurnResponse,
            TurnPausing,
            UserInputRequested,
            TurnPaused,
            TurnResumed,
            UserInputRequest,
            UserInputResponse,
            UserQuestion,
        )
    )
    forbidden = {
        "_TurnContinuation",
        "Continuation",
        "pause_waiter",
        "checkpoint",
        "session",
        "storage",
        "journal",
        "recovery",
    }
    assert forbidden.isdisjoint(core.__all__)
    from uthcode.core.agent import AgentTurnExecution

    assert not hasattr(AgentTurnExecution, "pending_pause")
    assert not hasattr(AgentTurnExecution, "pause")
    assert not hasattr(AgentTurnExecution, "resume")


def test_application_exposes_core_tool_values_without_integration_runtime_types() -> None:
    import uthcode.application as application
    from uthcode.application import (
        AgentEvent,
        AgentRun,
        CancellationToken,
        RunSnapshot,
        RunStatus,
        ToolCallPart,
        ToolDefinition,
        ToolResultPart,
        TurnHandle,
        TurnResult,
        PauseKind,
        PauseRequest,
        ResumeTurnResponse,
        UserInputResponse,
    )

    assert AgentEvent is not None
    assert AgentRun is not None
    assert CancellationToken is not None
    assert RunSnapshot is not None
    assert RunStatus is not None
    assert ToolCallPart is not None
    assert ToolDefinition is not None
    assert ToolResultPart is not None
    assert TurnHandle is not None
    assert TurnResult is not None
    assert PauseKind is not None
    assert PauseRequest is not None
    assert ResumeTurnResponse is not None
    assert UserInputResponse is not None
    assert "ToolRegistry" not in application.__all__
    assert "ToolExecutor" not in application.__all__
    assert "RunState" not in application.__all__
    assert not hasattr(application, "RunState")


def _restart_process_environment(home: Path) -> dict[str, str]:
    source_root = str(Path(__file__).parents[1] / "src")
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONPATH"] = source_root + os.pathsep + environment.get("PYTHONPATH", "")
    environment["HOME"] = str(home)
    environment["USERPROFILE"] = str(home)
    environment["HOMEDRIVE"] = home.drive
    environment["HOMEPATH"] = str(home)[len(home.drive):]
    environment["APPDATA"] = str(home)
    environment["LOCALAPPDATA"] = str(home)
    return environment


def _directory_snapshot(root: Path) -> tuple[str, ...]:
    return tuple(
        sorted(
            path.relative_to(root).as_posix()
            for path in root.rglob("*")
        )
    )


def _run_restart_child(script: str, *, environment: dict[str, str], workdir: Path) -> dict[str, object]:
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=workdir,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"child exited with {result.returncode}\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
    assert not result.stderr.strip(), result.stderr
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert len(lines) == 1, result.stdout
    payload = json.loads(lines[0])
    assert isinstance(payload, dict)
    return payload


def test_restart_process_boundary_creates_new_run_without_pending_or_t06_state_files(
    tmp_path: Path,
) -> None:
    home = tmp_path / "virtual-home"
    workdir = tmp_path / "virtual-workdir"
    home.mkdir()
    workdir.mkdir()
    before = {
        "home": _directory_snapshot(home),
        "workdir": _directory_snapshot(workdir),
    }
    environment = _restart_process_environment(home)

    pending_child = textwrap.dedent(
        """
        import asyncio
        import json
        import os
        from pathlib import Path

        from uthcode.application import (
            GenerationCompleted,
            Message,
            ProviderResponse,
            ToolCallPart,
            UthCodeApplication,
            Usage,
        )
        from uthcode.core import FinishReason
        from uthcode.integrations.providers.fake import FakeProvider


        async def observe_until_pending(handle):
            async for _event in handle.events():
                if handle.pending_pause is not None:
                    return


        async def main():
            request = {
                "questions": [
                    {
                        "question_id": "old-question",
                        "header": "Old",
                        "question": "This must not be replayed after restart.",
                        "kind": "text",
                    }
                ]
            }
            call = ToolCallPart("old-call", "AskUserQuestion", request)
            provider = FakeProvider(
                events=(
                    GenerationCompleted(
                        ProviderResponse(
                            message=Message("assistant", (call,)),
                            finish_reason=FinishReason.TOOL_CALLS,
                            usage=Usage(),
                        )
                    ),
                )
            )
            application = UthCodeApplication(provider)
            run = application.create_run()
            turn = run.start_turn("create a pending question")
            observer = asyncio.create_task(observe_until_pending(turn))
            for _ in range(1000):
                if turn.pending_pause is not None:
                    break
                await asyncio.sleep(0.001)
            pending = turn.pending_pause
            if pending is None:
                raise AssertionError("child A did not reach a real pending pause")
            print(
                json.dumps(
                    {
                        "pid": os.getpid(),
                        "home": str(Path.home()),
                        "workdir": str(application.runtime_context.workdir),
                        "run_id": pending.run_id,
                        "turn_id": pending.turn_id,
                        "pause_id": pending.pause_id,
                        "tool_call_id": pending.tool_call_id,
                        "pending_kind": pending.kind.value,
                        "observer_done": observer.done(),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )


        asyncio.run(main())
        """
    )
    child_a = _run_restart_child(
        pending_child,
        environment=environment,
        workdir=workdir,
    )
    after_a = {
        "home": _directory_snapshot(home),
        "workdir": _directory_snapshot(workdir),
    }

    fresh_child = textwrap.dedent(
        """
        import asyncio
        import json
        import os
        from pathlib import Path

        from uthcode.application import (
            GenerationCompleted,
            Message,
            ProviderResponse,
            TextPart,
            UthCodeApplication,
            Usage,
        )
        from uthcode.core import FinishReason
        from uthcode.integrations.providers.fake import FakeProvider


        async def main():
            provider = FakeProvider(
                events=(
                    GenerationCompleted(
                        ProviderResponse(
                            message=Message("assistant", (TextPart("fresh process"),)),
                            finish_reason=FinishReason.STOP,
                            usage=Usage(),
                        )
                    ),
                )
            )
            application = UthCodeApplication(provider)
            run = application.create_run()
            turn = run.start_turn("start a fresh process run")
            events = [event async for event in turn.events()]
            result = await turn.result()
            print(
                json.dumps(
                    {
                        "pid": os.getpid(),
                        "home": str(Path.home()),
                        "workdir": str(application.runtime_context.workdir),
                        "run_id": result.run_id,
                        "turn_id": result.turn_id,
                        "pending": turn.pending_pause is not None,
                        "events": [event.event_type for event in events],
                        "final_text": result.final_text,
                        "recovery_surface": any(
                            name in dir(application)
                            for name in (
                                "create_recoverable_run",
                                "pending_recovery",
                                "restore_recoverable_run",
                            )
                        ),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )


        asyncio.run(main())
        """
    )
    child_b = _run_restart_child(
        fresh_child,
        environment=environment,
        workdir=workdir,
    )
    after_b = {
        "home": _directory_snapshot(home),
        "workdir": _directory_snapshot(workdir),
    }

    assert Path(child_a["home"]).resolve() == home.resolve()
    assert Path(child_a["workdir"]).resolve() == workdir.resolve()
    assert child_a["pending_kind"] == "user_input_required"
    assert child_a["run_id"]
    assert child_a["turn_id"]
    assert child_a["pause_id"]
    assert child_a["tool_call_id"] == "old-call"
    assert Path(child_b["home"]).resolve() == home.resolve()
    assert Path(child_b["workdir"]).resolve() == workdir.resolve()
    assert child_b["pid"] != child_a["pid"]
    assert child_b["run_id"]
    assert child_b["turn_id"]
    assert child_b["run_id"] != child_a["run_id"]
    assert child_b["turn_id"] != child_a["turn_id"]
    assert child_b["pending"] is False
    assert child_b["recovery_surface"] is False
    assert child_b["events"] == [
        "turn_started",
        "iteration_started",
        "usage_updated",
        "assistant_message_completed",
        "turn_completed",
    ]
    assert child_b["final_text"] == "fresh process"
    assert after_a == before
    assert after_b == before
    forbidden_state_terms = (
        "recovery",
        "session",
        "checkpoint",
        "journal",
        "pending",
        "snapshot",
        "replay",
    )
    for snapshot in (*before.values(), *after_a.values(), *after_b.values()):
        assert not any(
            any(term in path.casefold() for term in forbidden_state_terms)
            for path in snapshot
        )
