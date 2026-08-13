"""Manual, offline-first entry point for the private Eval suite.

The runner owns orchestration only.  One attempt is executed through the public
``uthcode.application`` boundary by :func:`eval.execution.run_attempt`; task
verifiers are separate subprocesses and all runtime data is kept under an
explicit external Eval root.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from collections.abc import AsyncIterator, Callable, Sequence
from pathlib import Path

from eval.execution import AttemptExecution, EvalExecutionError, run_attempt
from eval.models import TaskDefinition, VerifierResult
from eval.reporting import (
    aggregate_experiment,
    compare_experiments,
    render_markdown_report,
    render_terminal_summary,
    report_to_json,
)
from eval.workspace import (
    WorkspaceSafetyError,
    clean_attempt,
    create_attempt,
    resolve_eval_root,
)
from uthcode.application import (
    EffectiveConfig,
    GenerationCompleted,
    Message,
    ProviderIdentity,
    ProviderKind,
    ProviderResponse,
    TextPart,
    ToolCallPart,
    Usage,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
TASK_ROOT = Path(__file__).resolve().parent / "tasks"
TASK_IDS = (
    "single-file-control",
    "cross-file-evidence",
    "todo-long-task",
    "plan-only",
    "ask-user-resume",
    "permission-boundary",
    "long-context-constraint",
)
REPORT_NAME = "report.json"


class _ScriptedProvider:
    """A tiny deterministic ProviderPort implementation for offline smoke runs."""

    def __init__(
        self,
        scripts: Sequence[Sequence[GenerationCompleted]],
        *,
        model_id: str = "eval-model",
    ) -> None:
        self.identity = ProviderIdentity("fake", "eval", model_id)
        self._scripts = tuple(tuple(script) for script in scripts)
        self._request_index = 0

    async def stream(self, request: object, *, cancellation: object) -> AsyncIterator[GenerationCompleted]:
        del request
        raise_if_cancelled = getattr(cancellation, "raise_if_cancelled")
        raise_if_cancelled()
        index = min(self._request_index, len(self._scripts) - 1)
        self._request_index += 1
        for event in self._scripts[index]:
            raise_if_cancelled()
            yield event


def _completed(*parts: object, finish_reason: str = "stop") -> GenerationCompleted:
    return GenerationCompleted(
        ProviderResponse(
            message=Message("assistant", tuple(parts)),  # type: ignore[arg-type]
            usage=Usage(input_tokens=24, output_tokens=8),
            finish_reason=finish_reason,
        )
    )


def _read_call(index: int, path: str) -> ToolCallPart:
    return ToolCallPart(f"fake-read-{index}", "ReadFile", {"path": path})


def _fake_script(task_id: str, task: TaskDefinition) -> tuple[tuple[GenerationCompleted, ...], ...]:
    evidence_calls = tuple(
        _read_call(index, item.path)
        for index, item in enumerate(task.required_evidence)
    )
    scripts: list[tuple[GenerationCompleted, ...]] = []
    if evidence_calls:
        scripts.append((_completed(*evidence_calls, finish_reason="tool_calls"),))
    if task_id == "ask-user-resume":
        scripts.extend(
            (
                (
                    _completed(
                        ToolCallPart(
                            "fake-ask-1",
                            "AskUserQuestion",
                            {
                                "questions": [
                                    {
                                        "question_id": "semantics",
                                        "header": "Semantics",
                                        "question": "Should the value be trimmed?",
                                        "kind": "single_select",
                                        "options": [
                                            {"label": "trim", "description": "Trim surrounding whitespace."},
                                            {"label": "preserve", "description": "Preserve surrounding whitespace."},
                                        ],
                                    }
                                ]
                            },
                        ),
                        finish_reason="tool_calls",
                    ),
                ),
                (_completed(TextPart("Fake completion after the typed answer; no fixture patch was injected.")),),
            )
        )
    elif task_id == "plan-only":
        scripts.extend(
            (
                (
                    _completed(
                        ToolCallPart(
                            "fake-plan-1",
                            "ProposePlan",
                            {"plan": "Inspect the evidence and preserve the read-only boundary."},
                        ),
                        finish_reason="tool_calls",
                    ),
                ),
                (_completed(TextPart("Plan approved; no implementation side effect was made.")),),
            )
        )
    else:
        if task_id == "permission-boundary":
            scripts.append(
                (
                    _completed(
                        ToolCallPart(
                            "fake-outside-read",
                            "ReadFile",
                            {"path": "../host-secret.txt"},
                        ),
                        finish_reason="tool_calls",
                    ),
                )
            )
        scripts.append((_completed(TextPart("Deterministic offline Eval completion.")),))
    return tuple(scripts)


def _task(task_id: str) -> tuple[Path, TaskDefinition]:
    if task_id not in TASK_IDS:
        raise EvalExecutionError(f"unknown Eval task: {task_id}")
    task_dir = TASK_ROOT / task_id
    definition = TaskDefinition.from_toml(task_dir / "task.toml")
    if definition.task_id != task_id:
        raise EvalExecutionError("task definition identifier does not match its directory")
    return task_dir, definition


def _config(
    provider_kind: ProviderKind,
    api_key_env: str | None,
    model_id: str,
) -> EffectiveConfig:
    if not isinstance(model_id, str) or not model_id.strip():
        raise EvalExecutionError("model identifier must be a non-empty string")
    model_id = model_id.strip()
    if provider_kind is ProviderKind.FAKE:
        return EffectiveConfig.single_model(
            "fake/eval",
            provider_profile_id="eval-fake",
            provider_kind=ProviderKind.FAKE,
            remote_model_id=model_id,
        )
    if provider_kind is ProviderKind.OPENAI_COMPAT:
        raise EvalExecutionError("OpenAI-compatible live runs require an explicitly supplied endpoint")
    return EffectiveConfig.single_model(
        "live/eval",
        provider_profile_id="eval-live",
        provider_kind=provider_kind,
        remote_model_id=model_id,
        api_key_env=api_key_env,
    )


def _verifier(task_dir: Path, task: TaskDefinition) -> Callable[[Path], VerifierResult]:
    verifier_path = task_dir / task.verifier_path

    def verify(workspace: Path) -> VerifierResult:
        try:
            completed = subprocess.run(
                [sys.executable, str(verifier_path), str(workspace)],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except OSError as exc:
            raise EvalExecutionError("verifier subprocess could not be started") from exc
        if completed.returncode != 0:
            raise EvalExecutionError("verifier subprocess failed")
        try:
            return VerifierResult.from_json(completed.stdout.strip())
        except (TypeError, ValueError) as exc:
            raise EvalExecutionError("verifier returned an invalid JSON contract") from exc

    return verify


def _write_attempt_record(execution: AttemptExecution) -> dict[str, object]:
    payload = execution.record.to_dict()
    payload["metric_details"] = execution.diagnostics.get("metric_details", {})
    return payload


async def _execute_attempt(
    task_dir: Path,
    task: TaskDefinition,
    eval_root: Path,
    experiment_id: str,
    attempt_id: str,
    *,
    provider_kind: ProviderKind,
    api_key_env: str | None,
    live: bool,
    live_authorized: bool,
    prompt_salt: str,
    model_id: str,
) -> dict[str, object]:
    fixture = task_dir / task.fixture_path
    attempt = create_attempt(
        REPO_ROOT,
        eval_root,
        experiment_id,
        task.task_id,
        attempt_id,
        fixture,
    )
    if provider_kind is ProviderKind.FAKE:
        provider_builder = lambda _profile, _model: _ScriptedProvider(
            _fake_script(task.task_id, task),
            model_id=model_id,
        )
    else:
        provider_builder = None
    instruction = (task_dir / task.instruction_path).read_text(encoding="utf-8")
    if prompt_salt:
        instruction += f"\n\n[manual prompt salt: {prompt_salt}]\n"
    execution = await run_attempt(
        task,
        attempt,
        instruction=instruction,
        config=_config(provider_kind, api_key_env, model_id),
        provider_builder=provider_builder,
        verifier=_verifier(task_dir, task),
        run_id=f"{experiment_id}-{task.task_id}-{attempt_id}",
        live=live,
        live_authorized=live_authorized,
    )
    return _write_attempt_record(execution)


def _report_paths(eval_root: Path, experiment_id: str) -> tuple[Path, Path]:
    directory = eval_root / "reports" / experiment_id
    directory.mkdir(parents=True, exist_ok=True)
    return directory / REPORT_NAME, directory / "report.md"


def _write_report(eval_root: Path, experiment_id: str, attempts: Sequence[dict[str, object]]) -> tuple[Path, dict[str, object]]:
    report = aggregate_experiment(experiment_id, attempts)
    json_path, markdown_path = _report_paths(eval_root, experiment_id)
    json_path.write_text(report_to_json(report), encoding="utf-8")
    markdown_path.write_text(render_markdown_report(report), encoding="utf-8")
    return json_path, report


def _read_json(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise EvalExecutionError("report JSON could not be read") from exc
    if not isinstance(payload, dict):
        raise EvalExecutionError("report JSON must contain an object")
    return payload


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _add_run_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--task", choices=TASK_IDS)
    parser.add_argument("--suite", choices=("all",))
    parser.add_argument("--experiment", required=True)
    parser.add_argument("--eval-root", required=True)
    parser.add_argument("--attempts", type=_positive_int, default=1)
    parser.add_argument("--prompt-salt", default="")
    parser.add_argument("--model")
    parser.add_argument("--provider-kind", default="fake")
    parser.add_argument("--api-key-env")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--live-authorized", action="store_true")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manual private UthCode Eval runner (offline by default).")
    subparsers = parser.add_subparsers(dest="command", required=True)
    smoke = subparsers.add_parser("smoke", help="run one task with the deterministic Fake Provider")
    smoke.add_argument("--task", choices=TASK_IDS, required=True)
    smoke.add_argument("--experiment", required=True)
    smoke.add_argument("--eval-root", required=True)
    smoke.add_argument("--attempts", type=_positive_int, default=1)
    smoke.add_argument("--prompt-salt", default="")
    smoke.add_argument("--model")
    smoke.add_argument("--provider-kind", default="fake")
    smoke.add_argument("--api-key-env")
    smoke.add_argument("--live", action="store_true")
    smoke.add_argument("--live-authorized", action="store_true")

    run = subparsers.add_parser("run", help="run one task or the complete seven-task suite")
    _add_run_arguments(run)

    compare = subparsers.add_parser("compare", help="compare two compatible experiment reports")
    compare.add_argument("--baseline", required=True)
    compare.add_argument("--candidate", required=True)

    clean = subparsers.add_parser("clean", help="clean exactly one manifest-owned attempt")
    clean.add_argument("--eval-root", required=True)
    clean.add_argument("--experiment")
    clean.add_argument("--task")
    clean.add_argument("--attempt")
    return parser


def _task_ids_for(args: argparse.Namespace) -> list[str]:
    if args.command == "smoke":
        return [args.task]
    if args.task and args.suite:
        raise EvalExecutionError("choose either --task or --suite")
    if args.task:
        return [args.task]
    if args.suite == "all":
        return list(TASK_IDS)
    raise EvalExecutionError("run requires --task or --suite all")


async def _run_command(args: argparse.Namespace) -> dict[str, object]:
    try:
        provider_kind = ProviderKind.coerce(args.provider_kind)
    except ValueError as exc:
        raise EvalExecutionError("unsupported Provider kind") from exc
    if provider_kind is not ProviderKind.FAKE:
        if not args.live or not args.live_authorized:
            raise EvalExecutionError("live Provider requires explicit live and cost authorization")
        if not args.api_key_env:
            raise EvalExecutionError("live Provider requires an API-key environment variable name")
        if not isinstance(args.model, str) or not args.model.strip():
            raise EvalExecutionError("live Provider requires an explicit --model identifier")
    if provider_kind is ProviderKind.FAKE and args.live:
        raise EvalExecutionError("Fake smoke does not accept --live")

    model_id = args.model.strip() if isinstance(args.model, str) and args.model.strip() else "eval-model"

    eval_root = resolve_eval_root(REPO_ROOT, Path(args.eval_root))
    task_ids = _task_ids_for(args)
    attempts: list[dict[str, object]] = []
    for task_id in task_ids:
        task_dir, task = _task(task_id)
        for number in range(1, args.attempts + 1):
            attempts.append(
                await _execute_attempt(
                    task_dir,
                    task,
                    eval_root,
                    args.experiment,
                    str(number),
                    provider_kind=provider_kind,
                    api_key_env=args.api_key_env,
                    live=args.live,
                    live_authorized=args.live_authorized,
                    prompt_salt=args.prompt_salt,
                    model_id=model_id,
                )
            )
    report_path, report = _write_report(eval_root, args.experiment, attempts)
    return {
        "mode": "fake" if provider_kind is ProviderKind.FAKE else "live",
        "experiment_id": args.experiment,
        "task_ids": task_ids,
        "attempt_count": len(attempts),
        "report_path": str(report_path),
        "report": report,
        "terminal_summary": render_terminal_summary(report),
    }


def _main(args: argparse.Namespace) -> dict[str, object]:
    if args.command in {"smoke", "run"}:
        return asyncio.run(_run_command(args))
    if args.command == "compare":
        return compare_experiments(_read_json(Path(args.baseline)), _read_json(Path(args.candidate)))
    if args.command == "clean":
        cleaned = clean_attempt(
            Path(args.eval_root),
            args.experiment,
            args.task,
            args.attempt,
        )
        return {"cleaned": [str(path) for path in cleaned]}
    raise EvalExecutionError("unknown Eval command")


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        payload = _main(args)
    except (EvalExecutionError, WorkspaceSafetyError, OSError, TypeError, ValueError) as exc:
        print(f"eval runner error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["TASK_IDS", "main"]
