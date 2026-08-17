"""One-shot, headless execution for the private Eval tool.

This module is intentionally an adapter around the public ``uthcode.application``
boundary.  It owns attempt bookkeeping and safe projections, but it does not
reimplement a Run, an Agent Loop, a Tool registry, or permission evaluation.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import os
import platform
import re
import subprocess
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypeAlias

from eval.models import (
    FinishCategory,
    InteractionKind,
    InteractionSpec,
    TaskDefinition,
    VerifierResult,
)
from eval.metrics import (
    compute_attempt_metrics,
    compute_diagnostic_facts,
    compute_metric_details,
)
from eval.workspace import AttemptPaths, capture_repository_snapshot, repository_status_delta
from uthcode.application import (
    AgentEvent,
    ApplicationRuntimeContext,
    EffectiveConfig,
    PauseKind,
    PlanReviewChoice,
    PlanReviewResponse,
    ProviderKind,
    TurnResult,
    UserInputResponse,
    create_application,
)


ApplicationFactory: TypeAlias = Callable[..., Any]
ProviderBuilder: TypeAlias = Callable[..., Any]
Verifier: TypeAlias = Callable[[Path], VerifierResult | Mapping[str, object] | Awaitable[VerifierResult | Mapping[str, object]]]

_REDACTED = "<redacted>"
_SECRET_KEY = re.compile(
    r"(?i)(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|passwd|secret|credential|authorization)"
)
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)(?P<prefix>(?<![A-Za-z0-9_-])(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|passwd|secret|credential|authorization)\s*[:=]\s*)(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)"
)
_BEARER = re.compile(r"(?i)\bBearer\s+[^\s,;\"']+")
_API_KEY_SHAPE = re.compile(r"(?i)(?<![A-Za-z0-9_])sk-[A-Za-z0-9][A-Za-z0-9_.:/-]*")


class EvalExecutionError(RuntimeError):
    """Raised only for invalid execution inputs before an attempt can run."""


@dataclass(frozen=True, slots=True)
class AttemptExecution:
    """Safe in-memory projection of one completed attempt."""

    task_id: str
    attempt_id: str
    events: tuple[AgentEvent, ...]
    turn_result: TurnResult | None
    verifier_result: VerifierResult | None
    finish_category: FinishCategory
    diagnostics: Mapping[str, object]
    record: Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _hash_payload(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _redact_text(value: str, secret_values: Sequence[str] = ()) -> str:
    text = _SECRET_ASSIGNMENT.sub(lambda match: f"{match.group('prefix')}{_REDACTED}", value)
    text = _BEARER.sub(f"Bearer {_REDACTED}", text)
    text = _API_KEY_SHAPE.sub(_REDACTED, text)
    for secret in sorted({item for item in secret_values if isinstance(item, str) and item}, key=len, reverse=True):
        text = text.replace(secret, _REDACTED)
    return text


def _safe_projection(value: object, secret_values: Sequence[str] = (), *, key: str | None = None) -> object:
    if isinstance(value, str):
        if key is not None and _SECRET_KEY.search(key):
            return _REDACTED
        return _redact_text(value, secret_values)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, Mapping):
        return {
            str(item_key): _safe_projection(item_value, secret_values, key=str(item_key))
            for item_key, item_value in value.items()
        }
    if isinstance(value, (tuple, list)):
        return [_safe_projection(item, secret_values) for item in value]
    return _REDACTED


def _json_write(path: Path, value: object, secret_values: Sequence[str] = ()) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(_safe_projection(value, secret_values), ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, path)


def _jsonl_write(path: Path, events: Sequence[AgentEvent], secret_values: Sequence[str]) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        for event in events:
            payload = _safe_projection(event.to_dict(), secret_values)
            stream.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
    os.replace(temporary, path)


def _git_revision(repo_root: Path) -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        ).stdout.strip() or "unknown"
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _code_fingerprint(repo_root: Path) -> str:
    """Hash the current source and Eval code, including uncommitted edits."""

    digest = hashlib.sha256()
    for root_name in ("src", "eval"):
        root = repo_root / root_name
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(repo_root).as_posix()):
            if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
                continue
            relative = path.relative_to(repo_root).as_posix().encode("utf-8")
            digest.update(relative)
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _git_worktree_root(repo_root: Path) -> Path:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise EvalExecutionError("attempt repo_root must be a physical Git repository") from exc
    output = completed.stdout.strip()
    if not output:
        raise EvalExecutionError("attempt repo_root must be a physical Git repository")
    return Path(output).resolve(strict=False)


def _config_fingerprint(config: EffectiveConfig) -> dict[str, str]:
    providers = {
        key: {
            "kind": profile.kind.value,
            "base_url": profile.base_url,
            "api_key_env": profile.api_key_env,
        }
        for key, profile in config.providers.items()
    }
    models = {
        key: {
            "provider_profile_id": profile.provider_profile_id,
            "remote_model_id": profile.remote_model_id,
            "label": profile.label,
            "max_output_tokens": profile.max_output_tokens,
        }
        for key, profile in config.models.items()
    }
    payload = {
        "model": config.model,
        "providers": providers,
        "models": models,
        "default_permission_mode": config.default_permission_mode.value,
    }
    current = config.current_model
    provider = config.provider_for()
    return {
        "config": _hash_payload(payload),
        "model": _hash_payload({"model": current.model_ref, "remote_model_id": current.remote_model_id}),
        "model_id": current.remote_model_id,
        "provider": _hash_payload({"kind": provider.kind.value, "base_url": provider.base_url}),
    }


def _task_permission_file(task: TaskDefinition, workspace: Path) -> None:
    if not task.permission_rules:
        return
    target = workspace / ".uthcode" / "permissions.toml"
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = ["[policy]", ""]
    for rule in task.permission_rules:
        lines.append("[[policy.rules]]")
        lines.append(f"id = {json.dumps(rule.id, ensure_ascii=False)}")
        lines.append(f"decision = {json.dumps(rule.decision.value)}")
        lines.append(f"tool = {json.dumps(rule.tool, ensure_ascii=False)}")
        lines.append(f"action = {json.dumps(rule.action, ensure_ascii=False)}")
        lines.append(f"effect = {json.dumps(rule.effect.value)}")
        lines.append(f"scope = {json.dumps(rule.scope.value)}")
        lines.append(f"resource = {json.dumps(rule.resource, ensure_ascii=False)}")
        lines.append(f"resource_prefix = {str(rule.resource_prefix).lower()}")
        lines.append("")
    target.write_text("\n".join(lines), encoding="utf-8", newline="\n")


@contextmanager
def _isolated_home(home: Path):
    """Make the existing Application loader discover only this attempt home."""

    names = ("HOME", "USERPROFILE", "HOMEDRIVE", "HOMEPATH")
    previous = {name: os.environ.get(name) for name in names}
    os.environ["HOME"] = str(home)
    os.environ["USERPROFILE"] = str(home)
    os.environ["HOMEDRIVE"] = home.drive
    os.environ["HOMEPATH"] = str(home)[len(home.drive):]
    try:
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _workspace_tree(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    if not path.exists():
        return result
    for item in sorted(path.rglob("*"), key=lambda candidate: candidate.relative_to(path).as_posix()):
        if item.is_symlink() or not item.is_file():
            continue
        result[item.relative_to(path).as_posix()] = hashlib.sha256(item.read_bytes()).hexdigest()
    return result


def _workspace_diff(before: Mapping[str, str], after: Mapping[str, str]) -> dict[str, list[str]]:
    before_keys = set(before)
    after_keys = set(after)
    return {
        "added": sorted(after_keys - before_keys),
        "deleted": sorted(before_keys - after_keys),
        "changed": sorted(key for key in before_keys & after_keys if before[key] != after[key]),
    }


def _interaction_for_kind(task: TaskDefinition, kind: InteractionKind, used: set[str]) -> InteractionSpec | None:
    for interaction in task.interactions:
        if interaction.id not in used and interaction.kind is kind:
            return interaction
    return None


def _build_typed_response(task: TaskDefinition, pause: Any, run_id: str, turn_id: str, used: set[str]) -> tuple[str, object]:
    if pause.kind is PauseKind.USER_INPUT_REQUIRED:
        spec = _interaction_for_kind(task, InteractionKind.ASK_USER, used)
        if spec is None or pause.user_input_request is None or pause.tool_call_id is None:
            raise LookupError("undeclared user input interaction")
        response = spec.response
        answers = response.get("answers")
        if not isinstance(answers, Mapping):
            raise ValueError("declared AskUser response is invalid")
        # The Application/Pause contract performs the final question-kind and
        # option validation.  Calling it before resume keeps this adapter from
        # fabricating an answer for a differently shaped question.
        pause.user_input_request.validate_answers(answers)
        return spec.id, UserInputResponse(
            pause.pause_id,
            run_id,
            turn_id,
            pause.tool_call_id,
            answers,
        )
    if pause.kind is PauseKind.PLAN_REVIEW_REQUIRED:
        spec = _interaction_for_kind(task, InteractionKind.PLAN_REVIEW, used)
        if spec is None or pause.plan_review_request is None:
            raise LookupError("undeclared Plan Review interaction")
        choice = spec.response.get("choice")
        feedback = spec.response.get("feedback")
        if choice == PlanReviewChoice.APPROVE.value:
            return spec.id, PlanReviewResponse(
                pause.pause_id,
                run_id,
                turn_id,
                pause.plan_review_request.revision,
                PlanReviewChoice.APPROVE,
            )
        if choice == PlanReviewChoice.REVISE.value and isinstance(feedback, str):
            return spec.id, PlanReviewResponse(
                pause.pause_id,
                run_id,
                turn_id,
                pause.plan_review_request.revision,
                PlanReviewChoice.REVISE,
                feedback,
            )
        raise ValueError("declared Plan Review response is invalid")
    raise LookupError("unsupported interaction kind")


def _failure_class(result: TurnResult | None) -> str:
    if result is None:
        return "runner"
    reason = result.termination_reason.value
    if reason in {"provider_error", "invalid_provider_response"}:
        return "provider"
    if reason == "internal_error":
        return "runtime"
    return "agent"


def _record_paths(attempt: AttemptPaths) -> dict[str, str]:
    return {
        "workspace": str(attempt.workspace),
        "home": str(attempt.home),
        "artifacts": str(attempt.artifacts),
        "manifest": str(attempt.manifest),
    }


def _validate_attempt_paths(attempt: AttemptPaths) -> None:
    repo = attempt.repo_root.resolve(strict=False)
    if repo != attempt.repo_root or not repo.is_dir():
        raise EvalExecutionError("attempt repo_root must be a physical directory")
    try:
        if _git_worktree_root(repo) != repo:
            raise EvalExecutionError("attempt repo_root must be the physical Git repository root")
        repository = capture_repository_snapshot(repo)
    except EvalExecutionError:
        raise
    except Exception as exc:
        raise EvalExecutionError("attempt repo_root must be a physical Git repository") from exc
    if repository.repo_root != repo:
        raise EvalExecutionError("attempt repo_root must be the physical Git repository root")

    root = attempt.eval_root.resolve(strict=False)
    if root != attempt.eval_root or not root.is_dir():
        raise EvalExecutionError("attempt Eval root must be a physical directory")
    try:
        root.relative_to(repo)
    except ValueError:
        pass
    else:
        raise EvalExecutionError("attempt Eval root must be outside the source repository")
    marker = root / ".uthcode-eval-root.json"
    try:
        marker_payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise EvalExecutionError("attempt Eval root marker is invalid") from exc
    if (
        not isinstance(marker_payload, Mapping)
        or marker_payload.get("kind") != "uthcode-eval-root"
        or marker_payload.get("schema_version") != 1
        or marker_payload.get("repo_root") != str(repo)
    ):
        raise EvalExecutionError("attempt Eval root marker does not match the source repository")
    for name in ("workspace", "home", "artifacts"):
        path = getattr(attempt, name)
        resolved = path.resolve(strict=False)
        if resolved != path or resolved == root:
            raise EvalExecutionError(f"attempt {name} must be a physical child of the Eval root")
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise EvalExecutionError(f"attempt {name} is outside the Eval root") from exc
        if not path.is_dir():
            raise EvalExecutionError(f"attempt {name} is not an existing directory")
    manifest = attempt.manifest.resolve(strict=False)
    if manifest != attempt.manifest or manifest.parent != attempt.artifacts or not attempt.manifest.is_file():
        raise EvalExecutionError("attempt manifest is not the expected physical file")
    try:
        manifest_payload = json.loads(attempt.manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise EvalExecutionError("attempt manifest is invalid") from exc
    if (
        not isinstance(manifest_payload, Mapping)
        or manifest_payload.get("kind") != "uthcode-eval-attempt"
        or manifest_payload.get("experiment_id") != attempt.experiment_id
        or manifest_payload.get("task_id") != attempt.task_id
        or manifest_payload.get("attempt_id") != attempt.attempt_id
        or manifest_payload.get("eval_root") != str(root)
    ):
        raise EvalExecutionError("attempt manifest identity does not match the attempt")
    components = manifest_payload.get("components")
    if not isinstance(components, Mapping):
        raise EvalExecutionError("attempt manifest has no component map")
    for name in ("workspace", "home", "artifacts"):
        if components.get(name) != str(getattr(attempt, name)):
            raise EvalExecutionError("attempt manifest component does not match the attempt")


def _set_trigger(diagnostics: dict[str, object], category: FinishCategory) -> None:
    diagnostics.setdefault("trigger_category", category.value)


async def run_attempt(
    task: TaskDefinition,
    attempt: AttemptPaths,
    *,
    instruction: str,
    config: EffectiveConfig,
    provider_builder: ProviderBuilder | None = None,
    application_factory: ApplicationFactory = create_application,
    tools: Sequence[Any] | None = None,
    verifier: Verifier | None = None,
    run_id: str | None = None,
    timeout_seconds: float | None = None,
    live: bool = False,
    live_authorized: bool = False,
    secret_values: Sequence[str] = (),
) -> AttemptExecution:
    """Run exactly one Application Run/Turn and persist safe attempt artifacts.

    The caller supplies a Provider builder in offline tests.  A non-Fake
    configuration is rejected unless both ``live`` and ``live_authorized`` are
    explicitly true; this function never infers cost or network consent.
    """

    if not isinstance(task, TaskDefinition):
        raise TypeError("task must be TaskDefinition")
    if not isinstance(attempt, AttemptPaths):
        raise TypeError("attempt must be AttemptPaths")
    _validate_attempt_paths(attempt)
    if task.task_id != attempt.task_id:
        raise EvalExecutionError("task and attempt identifiers do not match")
    if not isinstance(instruction, str) or not instruction.strip():
        raise ValueError("instruction must be a non-empty string")
    if not isinstance(config, EffectiveConfig):
        raise TypeError("config must be EffectiveConfig")
    if not callable(application_factory):
        raise TypeError("application_factory must be callable")
    if verifier is not None and not callable(verifier):
        raise TypeError("verifier must be callable or None")
    if timeout_seconds is None:
        timeout_seconds = float(task.timeout_seconds)
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    if not isinstance(live, bool) or not isinstance(live_authorized, bool):
        raise TypeError("live flags must be booleans")

    started_at = _now()
    started_clock = time.monotonic()
    before_tree = _workspace_tree(attempt.workspace)
    before_repo = None
    try:
        before_repo = capture_repository_snapshot(attempt.repo_root)
    except Exception:
        before_repo = None

    config_fingerprints = _config_fingerprint(config)
    configured_secret_values = tuple(
        value
        for profile in config.providers.values()
        if profile.api_key_env is not None
        for value in (os.environ.get(profile.api_key_env),)
        if value
    )
    effective_secret_values = tuple(dict.fromkeys((*secret_values, *configured_secret_values)))
    revision = _git_revision(attempt.repo_root)
    platform_fingerprint = _hash_payload({"system": platform.system(), "release": platform.release()})
    run_args_fingerprint = _hash_payload(
        {
            "timeout_seconds": timeout_seconds,
            "live": live,
            "live_authorized": live_authorized,
        }
    )
    fingerprints = {
        **config_fingerprints,
        "task": _hash_payload(task.to_dict()),
        "prompt": _hash_payload(instruction),
        "permission": _hash_payload([rule.to_dict() for rule in task.permission_rules]),
        "runtime": _hash_payload({"timeout_seconds": timeout_seconds, "platform": platform.system()}),
        "run_args": run_args_fingerprint,
        "platform": platform_fingerprint,
        "code": _code_fingerprint(attempt.repo_root),
        "uthcode_revision": revision,
    }
    diagnostics: dict[str, object] = {
        "event_consumer_count": 0,
        "result_waiter_count": 0,
        "verifier_call_count": 0,
        "interaction_count": 0,
        "interaction_ids": [],
        "cancel_requests": 0,
        "cancel_accepted": False,
        "retry_count": 0,
        "session_grant_count": 0,
        "failure_class": None,
        "context_diagnostics": "not_available",
    }
    events: list[AgentEvent] = []
    turn_result: TurnResult | None = None
    verifier_result: VerifierResult | None = None
    finish_category = FinishCategory.RUNNER_ERROR
    error_type: str | None = None
    used_interactions: set[str] = set()
    execution_error: BaseException | None = None
    app: Any = None
    run_ref: Any = None

    try:
        provider_kind = config.provider_for().kind
        if provider_kind is not ProviderKind.FAKE and not (live and live_authorized):
            raise EvalExecutionError("live Provider requires explicit live and cost authorization")
        if provider_kind is not ProviderKind.FAKE and provider_builder is None and not (live and live_authorized):
            raise EvalExecutionError("a non-Fake Provider requires an explicit builder")

        _task_permission_file(task, attempt.workspace)
        runtime_context = ApplicationRuntimeContext.from_system(workdir=attempt.workspace)
        factory_kwargs: dict[str, object] = {
            "runtime_context": runtime_context,
            "tools": tuple(tools) if tools is not None else None,
        }
        if provider_builder is not None:
            factory_kwargs["provider_builder"] = provider_builder
        if factory_kwargs["tools"] is None:
            factory_kwargs.pop("tools")
        with _isolated_home(attempt.home):
            app = application_factory(config, **factory_kwargs)
            run_ref = app.create_run(run_id=run_id)
            run_ref.set_permission_mode("auto")
            run_ref.set_behavior_mode(task.behavior_mode.value)
            handle = run_ref.start_turn(instruction)
            diagnostics["event_consumer_count"] = 1
            diagnostics["result_waiter_count"] = 1
            def cancel_once() -> None:
                if diagnostics["cancel_requests"]:
                    return
                diagnostics["cancel_requests"] = 1
                accepted = bool(handle.cancel())
                diagnostics["cancel_accepted"] = accepted

            event_task = asyncio.create_task(
                _consume_events_guarded(
                    handle,
                    task,
                    events,
                    used_interactions,
                    diagnostics,
                    cancel_once,
                )
            )
            result_task = asyncio.create_task(handle.result())

            deadline = time.monotonic() + float(timeout_seconds)
            done, pending = await asyncio.wait(
                {event_task, result_task},
                timeout=max(0.0, deadline - time.monotonic()),
                return_when=asyncio.ALL_COMPLETED,
            )
            if pending:
                _set_trigger(diagnostics, FinishCategory.TIMEOUT)
                cancel_once()
                await asyncio.shield(result_task)
                await asyncio.shield(event_task)
            for completed in done | pending:
                if completed.cancelled():
                    continue
                failure = completed.exception()
                if failure is not None and execution_error is None:
                    execution_error = failure
            if result_task.done() and not result_task.cancelled():
                turn_result = result_task.result()
            if isinstance(execution_error, EvalExecutionError):
                raise execution_error

            if diagnostics.get("trigger_category") == FinishCategory.BLOCKED_BY_PERMISSION.value:
                finish_category = FinishCategory.BLOCKED_BY_PERMISSION
            elif diagnostics.get("trigger_category") == FinishCategory.UNDECLARED_INTERACTION.value:
                finish_category = FinishCategory.UNDECLARED_INTERACTION
            elif diagnostics.get("trigger_category") == FinishCategory.TIMEOUT.value:
                finish_category = FinishCategory.TIMEOUT
            elif diagnostics.get("trigger_category") == FinishCategory.RUNNER_ERROR.value:
                finish_category = FinishCategory.RUNNER_ERROR
            elif execution_error is not None:
                raise execution_error
            elif turn_result is None:
                raise RuntimeError("Application did not return a TurnResult")
            elif turn_result.status.value != "completed":
                finish_category = FinishCategory.AGENT_FAILURE
            else:
                finish_category = FinishCategory.SUCCESS
    except asyncio.CancelledError:
        raise
    except BaseException as exc:
        error_type = type(exc).__name__
        execution_error = exc
        diagnostics["failure_class"] = "runner" if app is None else _failure_class(turn_result)
        if finish_category not in {
            FinishCategory.BLOCKED_BY_PERMISSION,
            FinishCategory.UNDECLARED_INTERACTION,
            FinishCategory.TIMEOUT,
        }:
            finish_category = FinishCategory.RUNNER_ERROR if app is None or turn_result is None else FinishCategory.AGENT_FAILURE

    if turn_result is not None and diagnostics.get("failure_class") is None:
        diagnostics["failure_class"] = _failure_class(turn_result)
    if finish_category is FinishCategory.AGENT_FAILURE and turn_result is not None:
        diagnostics["termination_reason"] = turn_result.termination_reason.value
    if error_type is not None:
        diagnostics["error_type"] = error_type

    public_diagnostics = getattr(app, "diagnostics", None)
    if callable(public_diagnostics):
        try:
            value = public_diagnostics()
            if isinstance(value, Mapping):
                diagnostics["application_diagnostics"] = dict(value)
                context = value.get("context")
                diagnostics["context_diagnostics"] = (
                    dict(context) if isinstance(context, Mapping) else "not_available"
                )
        except Exception:
            # A diagnostics projection is observational; it must never turn a
            # completed attempt into a different execution result.
            diagnostics["application_diagnostics"] = "not_available"

    # The verifier is deliberately called once after the Turn, including a
    # permission block, so partial side effects remain inspectable.
    if verifier is not None:
        diagnostics["verifier_call_count"] = 1
        try:
            value = verifier(attempt.workspace)
            if inspect.isawaitable(value):
                value = await value
            if isinstance(value, VerifierResult):
                verifier_result = value
            elif isinstance(value, Mapping):
                verifier_result = VerifierResult.from_mapping(value)
            else:
                raise TypeError("verifier must return VerifierResult or a mapping")
            if not verifier_result.success and finish_category is FinishCategory.SUCCESS:
                finish_category = FinishCategory.AGENT_FAILURE
                diagnostics["failure_class"] = "verifier_check"
        except asyncio.CancelledError:
            raise
        except BaseException as exc:
            verifier_result = None
            finish_category = FinishCategory.VERIFIER_ERROR
            diagnostics["failure_class"] = "verifier"
            diagnostics["error_type"] = type(exc).__name__

    diagnostics["session_grant_count"] = (
        len(run_ref.session_grants) if run_ref is not None else 0
    )
    diagnostics["duration_seconds"] = round(time.monotonic() - started_clock, 6)
    workspace_diff = _workspace_diff(before_tree, _workspace_tree(attempt.workspace))
    for key in ("added", "deleted", "changed"):
        values = workspace_diff[key]
        workspace_diff[key] = [
            value for value in values if value != ".uthcode/permissions.toml"
        ]
    diagnostics["workspace_diff"] = workspace_diff
    if before_repo is not None:
        try:
            after_repo = capture_repository_snapshot(attempt.repo_root)
            diagnostics["repository_status_delta"] = list(repository_status_delta(before_repo, after_repo))
        except Exception:
            diagnostics["repository_status_delta"] = "not_available"
    else:
        diagnostics["repository_status_delta"] = "not_available"

    safe_events = tuple(events)
    diagnostics["finish_category"] = finish_category.value
    diagnostics["metric_details"] = compute_metric_details(
        verifier_result=verifier_result,
        turn_result=None if turn_result is None else turn_result.to_dict(),
        diagnostics=diagnostics,
        events=safe_events,
        task=task,
    )
    diagnostics["diagnostic_facts"] = compute_diagnostic_facts(
        verifier_result=verifier_result,
        turn_result=None if turn_result is None else turn_result.to_dict(),
        diagnostics=diagnostics,
        events=safe_events,
    )
    ended_at = _now()
    artifact_files = {
        "metadata": "metadata.json",
        "events": "events.jsonl",
        "turn_result": "turn_result.json",
        "verifier_result": "verifier_result.json",
        "diagnostics": "diagnostics.json",
        "workspace_diff": "workspace-diff.json",
        "output_manifest": "output-manifest.json",
        "record": "record.json",
    }
    _json_write(
        attempt.artifacts / artifact_files["metadata"],
        {
            "schema_version": 1,
            "experiment_id": attempt.experiment_id,
            "task_id": task.task_id,
            "attempt_id": attempt.attempt_id,
            "fingerprints": fingerprints,
            "started_at": started_at,
            "ended_at": ended_at,
            "instruction_sha256": _hash_payload(instruction),
        },
        effective_secret_values,
    )
    _jsonl_write(attempt.artifacts / artifact_files["events"], safe_events, effective_secret_values)
    _json_write(
        attempt.artifacts / artifact_files["turn_result"],
        None if turn_result is None else turn_result.to_dict(),
        effective_secret_values,
    )
    _json_write(
        attempt.artifacts / artifact_files["verifier_result"],
        None if verifier_result is None else verifier_result.to_dict(),
        effective_secret_values,
    )
    _json_write(attempt.artifacts / artifact_files["diagnostics"], diagnostics, effective_secret_values)
    _json_write(attempt.artifacts / artifact_files["workspace_diff"], diagnostics["workspace_diff"], effective_secret_values)
    _json_write(
        attempt.artifacts / artifact_files["output_manifest"],
        {
            "stdout": {"available": False, "path": None},
            "stderr": {"available": False, "path": None},
        },
        effective_secret_values,
    )

    safe_turn = None if turn_result is None else _safe_projection(turn_result.to_dict(), effective_secret_values)
    safe_verifier = None if verifier_result is None else VerifierResult.from_mapping(
        _safe_projection(verifier_result.to_dict(), effective_secret_values)
    )
    record = _make_record(
        task,
        attempt,
        fingerprints,
        started_at,
        ended_at,
        finish_category,
        safe_turn,
        safe_verifier,
        diagnostics,
        artifact_files,
        safe_events,
    )
    _json_write(
        attempt.artifacts / artifact_files["record"],
        record.to_dict(),
        effective_secret_values,
    )
    _update_manifest(
        attempt,
        {
            "execution": {
                "status": "completed",
                "finish_category": finish_category.value,
                "started_at": started_at,
                "ended_at": ended_at,
                "duration_seconds": diagnostics["duration_seconds"],
                "fingerprints": fingerprints,
                "artifact_files": artifact_files,
            }
        },
    )
    return AttemptExecution(
        task_id=task.task_id,
        attempt_id=attempt.attempt_id,
        events=safe_events,
        turn_result=turn_result,
        verifier_result=verifier_result,
        finish_category=finish_category,
        diagnostics=dict(diagnostics),
        record=record,
    )


async def _consume_events(
    handle: Any,
    task: TaskDefinition,
    events: list[AgentEvent],
    used: set[str],
    diagnostics: dict[str, object],
    cancel_once: Callable[[], None],
) -> None:
    async for event in handle.events():
        events.append(event)
        if event.type != "turn_paused":
            continue
        pause = handle.pending_pause
        if pause is None:
            raise RuntimeError("turn_paused event has no pending public pause")
        if pause.kind is PauseKind.PERMISSION_REQUIRED:
            _set_trigger(diagnostics, FinishCategory.BLOCKED_BY_PERMISSION)
            cancel_once()
            continue
        try:
            interaction_id, response = _build_typed_response(task, pause, pause.run_id, pause.turn_id, used)
        except LookupError:
            _set_trigger(diagnostics, FinishCategory.UNDECLARED_INTERACTION)
            diagnostics["undeclared_interaction_kind"] = pause.kind.value
            cancel_once()
            continue
        except (TypeError, ValueError) as exc:
            _set_trigger(diagnostics, FinishCategory.RUNNER_ERROR)
            diagnostics["failure_class"] = "interaction_contract"
            diagnostics["error_type"] = type(exc).__name__
            cancel_once()
            continue
        if not handle.resume(response):
            raise RuntimeError("typed response was rejected by the public TurnHandle")
        used.add(interaction_id)
        diagnostics["interaction_count"] = int(diagnostics["interaction_count"]) + 1
        interaction_ids = diagnostics["interaction_ids"]
        assert isinstance(interaction_ids, list)
        interaction_ids.append(interaction_id)


async def _consume_events_guarded(
    handle: Any,
    task: TaskDefinition,
    events: list[AgentEvent],
    used: set[str],
    diagnostics: dict[str, object],
    cancel_once: Callable[[], None],
) -> None:
    try:
        await _consume_events(handle, task, events, used, diagnostics, cancel_once)
    except asyncio.CancelledError:
        raise
    except BaseException:
        cancel_once()
        raise


def _make_record(
    task: TaskDefinition,
    attempt: AttemptPaths,
    fingerprints: Mapping[str, str],
    started_at: str,
    ended_at: str,
    finish_category: FinishCategory,
    turn_result: object,
    verifier_result: VerifierResult | None,
    diagnostics: Mapping[str, object],
    artifact_files: Mapping[str, str],
    events: Sequence[AgentEvent],
) -> Any:
    from eval.models import AttemptRecord

    metric_values = compute_attempt_metrics(
        verifier_result=verifier_result,
        turn_result=turn_result,
        diagnostics=diagnostics,
        events=events,
        task=task,
    )

    return AttemptRecord(
        schema_version=1,
        experiment_id=attempt.experiment_id,
        task_id=task.task_id,
        attempt_id=attempt.attempt_id,
        fingerprints=dict(fingerprints),
        paths=_record_paths(attempt),
        timestamps={"started": started_at, "ended": ended_at},
        duration_seconds=float(diagnostics["duration_seconds"]),
        finish_category=finish_category,
        turn_result=turn_result if isinstance(turn_result, Mapping) else None,
        verifier_result=verifier_result,
        metrics=metric_values,
        artifact_manifest=dict(artifact_files),
    )


def _update_manifest(attempt: AttemptPaths, payload: Mapping[str, object]) -> None:
    try:
        current = json.loads(attempt.manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        current = {}
    if not isinstance(current, dict):
        current = {}
    current.update(_safe_projection(payload))
    _json_write(attempt.manifest, current)


__all__ = ["AttemptExecution", "EvalExecutionError", "run_attempt"]
