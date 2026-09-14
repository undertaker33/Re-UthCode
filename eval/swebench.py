"""SWE-bench prediction adapter built on the formal Eval/Application path.

This module deliberately does not import or depend on the SWE-bench harness.  A
caller supplies one already materialized, clean Git checkout, the problem
statement, and the model reference.  The checkout is used as the Application
workdir, while home and Eval artifacts live in a dedicated external Eval root.
The resulting JSONL line is the three-field prediction contract consumed by the
official harness.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import uuid
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eval.execution import AttemptExecution, EvalExecutionError, run_attempt
from eval.models import BehaviorMode, ScoringSpec, TaskDefinition
from eval.workspace import AttemptPaths, WorkspaceSafetyError, resolve_eval_root
from uthcode.application import EffectiveConfig, ProviderKind
from uthcode.core import SecretValue


_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_SECRET_KEY = re.compile(
    r"(?i)(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|passwd|secret|credential|authorization)"
)
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)(?P<prefix>(?<![A-Za-z0-9_-])(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|passwd|secret|credential|authorization)\s*[:=]\s*)(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)"
)
_BEARER = re.compile(r"(?i)\bBearer\s+[^\s,;\"']+")
_API_KEY_SHAPE = re.compile(r"(?i)(?<![A-Za-z0-9_])sk-[A-Za-z0-9][A-Za-z0-9_.:/-]*")
_TRACE_DROP_KEY = re.compile(
    r"(?i)(?:native|payload|image(?:_bytes|_data)?|raw[_-]?bytes|binary|base64)"
)
_REDACTED = "<redacted>"
_BINARY = "<binary file; patch omitted>"


def _safe_identifier(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or _IDENTIFIER.fullmatch(value) is None:
        raise EvalExecutionError(f"{field} must be a safe non-empty identifier")
    return value


def _physical_git_root(path: Path) -> Path:
    candidate = Path(path).expanduser().resolve(strict=False)
    if not candidate.is_dir():
        raise EvalExecutionError("SWE-bench workdir must be an existing directory")
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=candidate,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise EvalExecutionError("SWE-bench workdir must be a Git repository") from exc
    root = Path(completed.stdout.strip()).resolve(strict=False)
    if root != candidate or not (candidate / ".git").exists():
        raise EvalExecutionError("SWE-bench workdir must be the physical Git repository root")
    return candidate


@dataclass(frozen=True, slots=True)
class SWEbenchInstance:
    """The external inputs needed to run one SWE-bench instance."""

    instance_id: str
    workdir: Path
    problem_statement: str
    model_name_or_path: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "instance_id", _safe_identifier(self.instance_id, "instance_id"))
        object.__setattr__(self, "workdir", _physical_git_root(Path(self.workdir)))
        if not isinstance(self.problem_statement, str) or not self.problem_statement.strip():
            raise EvalExecutionError("problem_statement must be a non-empty string")
        if not isinstance(self.model_name_or_path, str) or not self.model_name_or_path.strip():
            raise EvalExecutionError("model_name_or_path must be a non-empty string")
        object.__setattr__(self, "problem_statement", self.problem_statement)
        object.__setattr__(self, "model_name_or_path", self.model_name_or_path.strip())


@dataclass(frozen=True, slots=True)
class SWEbenchPrediction:
    """The exact three-field JSON object expected by the official harness."""

    instance_id: str
    model_name_or_path: str
    model_patch: str

    def __post_init__(self) -> None:
        _safe_identifier(self.instance_id, "instance_id")
        if not isinstance(self.model_name_or_path, str) or not self.model_name_or_path.strip():
            raise EvalExecutionError("model_name_or_path must be a non-empty string")
        if not isinstance(self.model_patch, str):
            raise TypeError("model_patch must be a string")

    def to_dict(self) -> dict[str, str]:
        return {
            "instance_id": self.instance_id,
            "model_name_or_path": self.model_name_or_path,
            "model_patch": self.model_patch,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"))


@dataclass(frozen=True, slots=True)
class SWEbenchRun:
    """Safe result of one adapter invocation."""

    instance: SWEbenchInstance
    attempt: AttemptPaths
    execution: AttemptExecution
    prediction: SWEbenchPrediction
    prediction_path: Path
    trace_path: Path

    def to_dict(self) -> dict[str, object]:
        return {
            "instance_id": self.prediction.instance_id,
            "prediction_path": str(self.prediction_path),
            "trace_path": str(self.trace_path),
            "attempt_id": self.attempt.attempt_id,
            "finish_category": self.execution.finish_category.value,
            "model_patch_bytes": len(self.prediction.model_patch.encode("utf-8")),
        }


def _run_git(
    workdir: Path,
    args: Sequence[str],
    *,
    env: Mapping[str, str] | None = None,
) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(workdir), *args],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=None if env is None else dict(env),
        )
    except OSError as exc:
        raise EvalExecutionError("SWE-bench patch generation requires the Git executable") from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "unknown Git error"
        raise EvalExecutionError(f"Git operation failed: {detail}")
    return completed.stdout


def _git_head(workdir: Path) -> str:
    head = _run_git(workdir, ["rev-parse", "--verify", "HEAD"]).strip()
    if not head:
        raise EvalExecutionError("SWE-bench workdir must have a resolvable HEAD commit")
    return head


def _require_clean_workdir(workdir: Path) -> None:
    status = _run_git(workdir, ["status", "--porcelain=v1", "--untracked-files=all"])
    if status.strip():
        raise EvalExecutionError(
            "SWE-bench workdir must be clean before model execution; "
            "tracked, staged, or untracked changes were detected"
        )


def _git_patch_with_index(
    workdir: Path,
    baseline_ref: str,
    index_path: Path,
    *,
    exclude_paths: Sequence[str] = (),
) -> str:
    if not isinstance(baseline_ref, str) or not baseline_ref.strip():
        raise ValueError("baseline_ref must be a non-empty Git revision")
    index_path = Path(index_path)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    if index_path.exists() or index_path.is_symlink():
        index_path.unlink()
    env = os.environ.copy()
    env["GIT_INDEX_FILE"] = str(index_path)
    try:
        _run_git(workdir, ["read-tree", baseline_ref], env=env)
        add_args = ["add", "-A", "--", "."]
        add_args.extend(f":(exclude){path}" for path in exclude_paths)
        _run_git(workdir, add_args, env=env)
        return _run_git(
            workdir,
            [
                "--no-pager",
                "diff",
                "--cached",
                "--binary",
                "--full-index",
                "--find-renames",
                "--find-copies",
                "--no-ext-diff",
                "--no-textconv",
                baseline_ref,
                "--",
            ],
            env=env,
        )
    finally:
        if index_path.exists() or index_path.is_symlink():
            index_path.unlink()


def build_model_patch(
    workdir: Path,
    *,
    baseline_ref: str = "HEAD",
    exclude_paths: Sequence[str] = (),
) -> str:
    """Build a standard Git patch from a clean baseline and current worktree.

    A temporary index is populated from the worktree, leaving the caller's
    real index untouched.  Git then supplies its binary, rename, mode,
    symlink, line-ending and untracked-file handling; ignored files remain
    ignored according to the instance repository's normal rules.
    """

    workdir = Path(workdir).expanduser().resolve(strict=False)
    if not workdir.is_dir():
        raise EvalExecutionError("SWE-bench workdir must be an existing directory")
    with tempfile.TemporaryDirectory(prefix="uthcode-swebench-index-") as temporary:
        return _git_patch_with_index(
            workdir,
            baseline_ref,
            Path(temporary) / "index",
            exclude_paths=exclude_paths,
        )


def _git_baseline_fingerprint(workdir: Path, baseline_ref: str) -> str:
    return hashlib.sha256(baseline_ref.encode("ascii", errors="strict")).hexdigest()


def _redact_trace_text(value: str, secret_values: Sequence[str]) -> str:
    result = _SECRET_ASSIGNMENT.sub(lambda match: f"{match.group('prefix')}{_REDACTED}", value)
    result = _BEARER.sub(f"Bearer {_REDACTED}", result)
    result = _API_KEY_SHAPE.sub(_REDACTED, result)
    for secret in sorted(
        {item for item in secret_values if isinstance(item, str) and item},
        key=len,
        reverse=True,
    ):
        result = result.replace(secret, _REDACTED)
    return result


def sanitize_trace(value: object, secret_values: Sequence[str] = (), *, key: str | None = None) -> object:
    """Return a JSON-safe trace projection without secret/native media data."""

    if key is not None and (_SECRET_KEY.search(key) or _TRACE_DROP_KEY.search(key)):
        return _REDACTED if _SECRET_KEY.search(key) else None
    if isinstance(value, str):
        return _REDACTED if key is not None and _SECRET_KEY.search(key) else _redact_trace_text(value, secret_values)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return _REDACTED
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, Mapping):
        projected: dict[str, object] = {}
        for raw_key, item in value.items():
            item_key = str(raw_key)
            if _TRACE_DROP_KEY.search(item_key):
                continue
            sanitized = sanitize_trace(item, secret_values, key=item_key)
            if sanitized is not None:
                projected[item_key] = sanitized
        return projected
    if isinstance(value, (tuple, list)):
        return [sanitize_trace(item, secret_values) for item in value]
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return sanitize_trace(to_dict(), secret_values, key=key)
    return _REDACTED


def _atomic_write_text(path: Path, text: str) -> None:
    path = path.expanduser()
    if path.exists() and path.is_symlink():
        raise EvalExecutionError("output path must not be a symbolic link")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(text, encoding="utf-8", newline="\n")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _outside_workdir(path: Path, workdir: Path) -> Path:
    candidate = path.expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    candidate = candidate.resolve(strict=False)
    try:
        candidate.relative_to(workdir)
    except ValueError:
        return candidate
    raise EvalExecutionError("prediction and trace outputs must be outside the instance workdir")


def _external_attempt(
    instance: SWEbenchInstance,
    eval_root: Path,
    *,
    experiment_id: str,
    attempt_id: str,
    fixture_sha256: str,
) -> AttemptPaths:
    try:
        root = resolve_eval_root(instance.workdir, eval_root)
    except WorkspaceSafetyError as exc:
        raise EvalExecutionError(str(exc)) from exc
    for value, field in ((experiment_id, "experiment_id"), (instance.instance_id, "task_id"), (attempt_id, "attempt_id")):
        _safe_identifier(value, field)
    workspace = instance.workdir
    home = root / "homes" / experiment_id / instance.instance_id / attempt_id
    artifacts = root / "artifacts" / experiment_id / instance.instance_id / attempt_id
    manifest = artifacts / "manifest.json"
    if home.exists() or artifacts.exists() or manifest.exists():
        raise EvalExecutionError("SWE-bench attempt already exists")
    home.mkdir(parents=True, exist_ok=False)
    artifacts.mkdir(parents=True, exist_ok=False)
    payload: dict[str, object] = {
        "kind": "uthcode-eval-attempt",
        "schema_version": 1,
        "status": "ready",
        "repo_root": str(instance.workdir),
        "eval_root": str(root),
        "experiment_id": experiment_id,
        "task_id": instance.instance_id,
        "attempt_id": attempt_id,
        "workspace": str(workspace),
        "home": str(home),
        "artifacts": str(artifacts),
        "fixture": "external-swebench-worktree",
        "fixture_sha256": fixture_sha256,
        "components": {
            "workspace": str(workspace),
            "home": str(home),
            "artifacts": str(artifacts),
        },
    }
    _atomic_write_text(manifest, json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    return AttemptPaths(
        repo_root=instance.workdir,
        eval_root=root,
        experiment_id=experiment_id,
        task_id=instance.instance_id,
        attempt_id=attempt_id,
        workspace=workspace,
        home=home,
        artifacts=artifacts,
        manifest=manifest,
        fixture_sha256=fixture_sha256,
    )


def _task(instance_id: str, timeout_seconds: int) -> TaskDefinition:
    return TaskDefinition(
        schema_version=1,
        task_id=instance_id,
        task_version="swebench-external-v1",
        instruction_path="problem-statement.txt",
        fixture_path="external-worktree",
        verifier_path="external-harness",
        behavior_mode=BehaviorMode.DEFAULT,
        timeout_seconds=timeout_seconds,
        required_evidence=(),
        interactions=(),
        permission_rules=(),
        scoring=ScoringSpec(1, 0, ("correctness",)),
    )


def _trace_path(path: Path, events: Sequence[object], secret_values: Sequence[str]) -> None:
    lines: list[str] = []
    for event in events:
        if hasattr(event, "to_dict") and callable(event.to_dict):
            payload = event.to_dict()
        else:
            payload = event
        safe = sanitize_trace(payload, secret_values)
        lines.append(json.dumps(safe, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    _atomic_write_text(path, "".join(f"{line}\n" for line in lines))


def _trace_secret_values(config: EffectiveConfig, secret_values: Sequence[str]) -> tuple[str, ...]:
    configured = tuple(
        profile.api_key.reveal()
        for profile in config.providers.values()
        if profile.api_key is not None
    )
    if config.search.api_key is not None:
        configured = (*configured, config.search.api_key.reveal())
    return tuple(dict.fromkeys((*secret_values, *configured)))


def _write_prediction(path: Path, prediction: SWEbenchPrediction) -> None:
    _atomic_write_text(path, prediction.to_json() + "\n")


def _default_eval_root(instance: SWEbenchInstance) -> Path:
    digest = hashlib.sha256(str(instance.workdir).encode("utf-8")).hexdigest()[:12]
    return instance.workdir.parent / f".uthcode-swebench-eval-{digest}"


async def run_swebench_instance(
    instance: SWEbenchInstance,
    *,
    config: EffectiveConfig,
    eval_root: Path | None = None,
    experiment_id: str = "swebench",
    attempt_id: str | None = None,
    prediction_path: Path | None = None,
    trace_path: Path | None = None,
    provider_builder: Any | None = None,
    application_factory: Any = None,
    tools: Sequence[Any] | None = None,
    timeout_seconds: float | None = None,
    live: bool = False,
    live_authorized: bool = False,
    secret_values: Sequence[str] = (),
) -> SWEbenchRun:
    """Run one external instance via :func:`eval.execution.run_attempt`."""

    if not isinstance(instance, SWEbenchInstance):
        raise TypeError("instance must be SWEbenchInstance")
    if not isinstance(config, EffectiveConfig):
        raise TypeError("config must be EffectiveConfig")
    if application_factory is None:
        from uthcode.application import create_application

        application_factory = create_application
    if not callable(application_factory):
        raise TypeError("application_factory must be callable")
    if timeout_seconds is None:
        timeout_seconds = 3600.0
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    timeout_int = max(1, min(86400, int(timeout_seconds)))
    root = _default_eval_root(instance) if eval_root is None else Path(eval_root)
    attempt_value = uuid.uuid4().hex if attempt_id is None else attempt_id
    _safe_identifier(experiment_id, "experiment_id")
    _safe_identifier(attempt_value, "attempt_id")

    _require_clean_workdir(instance.workdir)
    baseline_ref = _git_head(instance.workdir)
    runtime_permissions = ".uthcode/permissions.toml"
    exclude_paths = () if (instance.workdir / runtime_permissions).exists() else (runtime_permissions,)
    attempt = _external_attempt(
        instance,
        root,
        experiment_id=experiment_id,
        attempt_id=attempt_value,
        fixture_sha256=_git_baseline_fingerprint(instance.workdir, baseline_ref),
    )
    execution_kwargs: dict[str, object] = {
        "task": _task(instance.instance_id, timeout_int),
        "attempt": attempt,
        "instruction": instance.problem_statement,
        "config": config,
        "provider_builder": provider_builder,
        "application_factory": application_factory,
        "tools": tools,
        "run_id": f"{experiment_id}-{instance.instance_id}-{attempt_value}",
        "timeout_seconds": timeout_seconds,
        "live": live,
        "live_authorized": live_authorized,
        "secret_values": tuple(secret_values),
        "allow_external_workspace": True,
    }
    execution = await run_attempt(**execution_kwargs)
    patch = _git_patch_with_index(
        instance.workdir,
        baseline_ref,
        attempt.artifacts / ".patch-index",
        exclude_paths=exclude_paths,
    )
    prediction = SWEbenchPrediction(instance.instance_id, instance.model_name_or_path, patch)
    resolved_prediction = (
        _outside_workdir(prediction_path, instance.workdir)
        if prediction_path is not None
        else attempt.eval_root / "reports" / f"{instance.instance_id}.jsonl"
    )
    resolved_trace = (
        _outside_workdir(trace_path, instance.workdir)
        if trace_path is not None
        else attempt.artifacts / "trace.jsonl"
    )
    _write_prediction(resolved_prediction, prediction)
    _trace_path(resolved_trace, execution.events, _trace_secret_values(config, secret_values))
    return SWEbenchRun(
        instance=instance,
        attempt=attempt,
        execution=execution,
        prediction=prediction,
        prediction_path=resolved_prediction,
        trace_path=resolved_trace,
    )


run_instance = run_swebench_instance


def _config_from_cli(args: argparse.Namespace) -> EffectiveConfig:
    provider_kind = ProviderKind.coerce(args.provider_kind)
    if provider_kind is ProviderKind.FAKE:
        return EffectiveConfig.single_model(
            "swebench/eval",
            provider_profile_id="swebench-fake",
            provider_kind=provider_kind,
            remote_id=args.model_name_or_path,
        )
    if not args.api_key_env or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", args.api_key_env):
        raise EvalExecutionError("live Provider requires --api-key-env with a valid environment variable name")
    value = os.environ.get(args.api_key_env)
    if not value or not value.strip():
        raise EvalExecutionError("live Provider API-key environment variable is missing or empty")
    return EffectiveConfig.single_model(
        "swebench/eval",
        provider_profile_id="swebench-live",
        provider_kind=provider_kind,
        remote_id=args.model_name_or_path,
        api_key=SecretValue(value),
        base_url=args.base_url,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export one SWE-bench prediction through UthCode Headless.")
    parser.add_argument("--instance-id", required=True)
    parser.add_argument("--workdir", type=Path, required=True, help="External clean Git checkout for the instance.")
    statement = parser.add_mutually_exclusive_group(required=True)
    statement.add_argument("--problem-statement")
    statement.add_argument("--problem-file", type=Path)
    parser.add_argument("--model-name-or-path", required=True)
    parser.add_argument("--eval-root", type=Path)
    parser.add_argument("--experiment-id", default="swebench")
    parser.add_argument("--attempt-id")
    parser.add_argument("--predictions-path", type=Path)
    parser.add_argument("--trace-path", type=Path)
    parser.add_argument("--provider-kind", choices=[item.value for item in ProviderKind], default=ProviderKind.FAKE.value)
    parser.add_argument("--api-key-env")
    parser.add_argument("--base-url")
    parser.add_argument("--timeout-seconds", type=float, default=3600.0)
    parser.add_argument("--live", action="store_true", help="Permit a configured live Provider call.")
    parser.add_argument("--live-authorized", action="store_true", help="Explicit cost authorization for a live call.")
    return parser


async def _main_async(args: argparse.Namespace) -> int:
    problem = args.problem_statement
    if args.problem_file is not None:
        try:
            problem = args.problem_file.read_text(encoding="utf-8")
        except OSError as exc:
            raise EvalExecutionError("problem statement file could not be read") from exc
    instance = SWEbenchInstance(args.instance_id, args.workdir, problem, args.model_name_or_path)
    result = await run_swebench_instance(
        instance,
        config=_config_from_cli(args),
        eval_root=args.eval_root,
        experiment_id=args.experiment_id,
        attempt_id=args.attempt_id,
        prediction_path=args.predictions_path,
        trace_path=args.trace_path,
        timeout_seconds=args.timeout_seconds,
        live=args.live,
        live_authorized=args.live_authorized,
    )
    print(json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    try:
        return asyncio.run(_main_async(_parser().parse_args(argv)))
    except (EvalExecutionError, OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover - exercised by the CLI smoke command
    raise SystemExit(main())


__all__ = [
    "SWEbenchInstance",
    "SWEbenchPrediction",
    "SWEbenchRun",
    "build_model_patch",
    "main",
    "run_instance",
    "run_swebench_instance",
    "sanitize_trace",
]
