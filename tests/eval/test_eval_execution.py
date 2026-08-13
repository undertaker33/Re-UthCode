from __future__ import annotations

import ast
import asyncio
import json
import subprocess
from collections.abc import AsyncIterator, Iterable, Mapping
from pathlib import Path

import pytest

from eval.execution import EvalExecutionError, run_attempt
from eval.models import (
    FinishCategory,
    InteractionSpec,
    PermissionDecision,
    PermissionEffect,
    PermissionRule,
    PermissionRuleKind,
    PermissionScope,
    TaskDefinition,
    ScoringSpec,
    VerifierCheck,
    VerifierResult,
)
from eval.workspace import AttemptPaths, create_attempt, resolve_eval_root
from uthcode.application import (
    ApplicationRuntimeContext,
    EffectiveConfig,
    ProviderKind,
    create_application,
)
from uthcode.core.permission import Effect, PermissionAction, ResourceScope
from uthcode.core.provider import (
    CancellationToken,
    FinishReason,
    GenerationCompleted,
    GenerationRequest,
    Message,
    ProviderError,
    ProviderEvent,
    ProviderIdentity,
    ProviderResponse,
    TextPart,
    ToolCallPart,
    ToolDefinition,
    Usage,
)
from uthcode.core.tool import ToolExecutionResult, ToolPreparation
from uthcode.integrations.providers.fake import FakeProvider


def _response(*parts: object, finish_reason: FinishReason = FinishReason.STOP) -> GenerationCompleted:
    return GenerationCompleted(
        ProviderResponse(
            message=Message("assistant", tuple(parts)),
            finish_reason=finish_reason,
            usage=Usage(input_tokens=3, output_tokens=2),
        )
    )


class _ScriptedProvider:
    def __init__(self, scripts: Iterable[Iterable[ProviderEvent]]) -> None:
        self.identity = ProviderIdentity("fake", "eval-script", "eval-model")
        self._scripts = tuple(tuple(script) for script in scripts)
        self.requests: list[GenerationRequest] = []

    async def stream(
        self,
        request: GenerationRequest,
        *,
        cancellation: CancellationToken,
    ) -> AsyncIterator[ProviderEvent]:
        self.requests.append(request)
        cancellation.raise_if_cancelled()
        index = min(len(self.requests) - 1, len(self._scripts) - 1)
        for event in self._scripts[index]:
            cancellation.raise_if_cancelled()
            yield event


class _OutsideWriteTool:
    definition = ToolDefinition(
        "OutsideWrite",
        parameters={
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
            "additionalProperties": False,
        },
    )

    def __init__(self, resource: Path) -> None:
        self.resource = resource
        self.executions = 0

    def preflight(self, arguments: Mapping[str, object]) -> ToolPreparation:
        return ToolPreparation(
            PermissionAction(
                "OutsideWrite",
                "write",
                Effect.WRITE,
                str(self.resource),
                ResourceScope.OUTSIDE,
            ),
            arguments,
        )

    async def execute(
        self,
        arguments: Mapping[str, object],
        *,
        cancellation: CancellationToken,
    ) -> ToolExecutionResult:
        del arguments
        cancellation.raise_if_cancelled()
        self.executions += 1
        return ToolExecutionResult("written")


def _task(
    *,
    interactions: tuple[InteractionSpec, ...] = (),
    permission_rules: tuple[PermissionRule, ...] = (),
    timeout_seconds: int = 5,
    behavior_mode: str = "default",
) -> TaskDefinition:
    return TaskDefinition(
        schema_version=1,
        task_id="execution-task",
        task_version="0.1.0",
        instruction_path="instruction.md",
        fixture_path="fixture",
        verifier_path="verify.py",
        behavior_mode=behavior_mode,
        timeout_seconds=timeout_seconds,
        required_evidence=(),
        interactions=interactions,
        permission_rules=permission_rules,
        scoring=ScoringSpec(1, 0.5, ("correctness", "safety")),
    )


def _attempt(tmp_path: Path, task: TaskDefinition, *, attempt_id: str = "attempt-1"):
    repo = tmp_path / attempt_id / "repo"
    repo.mkdir(parents=True)
    subprocess.run(
        ["git", "init", "--quiet", str(repo)],
        check=True,
        capture_output=True,
        text=True,
    )
    fixture = repo / "fixture"
    fixture.mkdir()
    (fixture / "seed.txt").write_text("fixture\n", encoding="utf-8")
    root = resolve_eval_root(repo, tmp_path / attempt_id / "external-eval")
    return create_attempt(repo, root, "experiment-1", task.task_id, attempt_id, fixture)


def _forged_attempt(
    repo: Path,
    root: Path,
    task: TaskDefinition,
    *,
    repo_root: Path | None = None,
 ) -> AttemptPaths:
    """Build the public AttemptPaths shape without using create_attempt."""

    source_repo = (repo_root or repo).resolve()
    root = root.resolve()
    workspace = root / "workspaces" / "experiment-1" / task.task_id / "forged"
    home = root / "homes" / "experiment-1" / task.task_id / "forged"
    artifacts = root / "artifacts" / "experiment-1" / task.task_id / "forged"
    for directory in (workspace, home, artifacts):
        directory.mkdir(parents=True, exist_ok=True)
    marker = root / ".uthcode-eval-root.json"
    marker.write_text(
        json.dumps({"kind": "uthcode-eval-root", "schema_version": 1, "repo_root": str(source_repo)}) + "\n",
        encoding="utf-8",
    )
    manifest = artifacts / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "kind": "uthcode-eval-attempt",
                "schema_version": 1,
                "status": "ready",
                "repo_root": str(source_repo),
                "eval_root": str(root),
                "experiment_id": "experiment-1",
                "task_id": task.task_id,
                "attempt_id": "forged",
                "workspace": str(workspace),
                "home": str(home),
                "artifacts": str(artifacts),
                "components": {
                    "workspace": str(workspace),
                    "home": str(home),
                    "artifacts": str(artifacts),
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return AttemptPaths(
        source_repo,
        root,
        "experiment-1",
        task.task_id,
        "forged",
        workspace,
        home,
        artifacts,
        manifest,
        "fixture-sha256",
    )


def _config() -> EffectiveConfig:
    return EffectiveConfig.single_model(
        "fake/eval",
        provider_profile_id="eval-fake",
        provider_kind=ProviderKind.FAKE,
        remote_model_id="eval-model",
    )


def _builder(provider: object):
    def build(_provider_profile: object, _model_profile: object) -> object:
        return provider

    return build


def _verifier_calls() -> tuple[list[Path], object]:
    calls: list[Path] = []

    def verify(workspace: Path) -> VerifierResult:
        calls.append(workspace)
        check = VerifierCheck("workspace-present", "hard", workspace.is_dir(), 1, 1, "checked")
        return VerifierResult(1, (check,), 100 if check.passed else 0, check.passed)

    return calls, verify


def _deny_outside_write() -> PermissionRule:
    return PermissionRule(
        "deny-outside-write",
        PermissionRuleKind.POLICY,
        PermissionDecision.DENY,
        "OutsideWrite",
        "write",
        PermissionEffect.WRITE,
        PermissionScope.OUTSIDE,
        "host-target.txt",
    )


@pytest.mark.asyncio
async def test_forged_repo_child_attempt_is_rejected_before_permission_or_artifact_write(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(
        ["git", "init", "--quiet", str(repo)],
        check=True,
        capture_output=True,
        text=True,
    )
    task = _task(permission_rules=(_deny_outside_write(),))
    forged_root = repo / "forged-eval"
    attempt = _forged_attempt(repo, forged_root, task)
    permission_file = attempt.workspace / ".uthcode" / "permissions.toml"
    before_artifacts = sorted(path.relative_to(attempt.artifacts).as_posix() for path in attempt.artifacts.rglob("*"))
    factory_calls: list[object] = []

    def factory(*_args: object, **_kwargs: object) -> object:
        factory_calls.append(True)
        raise AssertionError("forged attempt must be rejected before Application creation")

    with pytest.raises(EvalExecutionError, match="outside the source repository"):
        await run_attempt(
            task,
            attempt,
            instruction="must not execute inside the source repository",
            config=_config(),
            application_factory=factory,
            run_id="run-forged-repo-child",
        )

    assert factory_calls == []
    assert not permission_file.exists()
    assert sorted(path.relative_to(attempt.artifacts).as_posix() for path in attempt.artifacts.rglob("*")) == before_artifacts


@pytest.mark.asyncio
async def test_forged_attempt_with_non_git_repo_root_is_rejected_before_writes(tmp_path: Path) -> None:
    non_repo = tmp_path / "not-a-repo"
    non_repo.mkdir()
    task = _task(permission_rules=(_deny_outside_write(),))
    attempt = _forged_attempt(non_repo, tmp_path / "external-eval", task)
    permission_file = attempt.workspace / ".uthcode" / "permissions.toml"
    before_artifacts = sorted(path.relative_to(attempt.artifacts).as_posix() for path in attempt.artifacts.rglob("*"))

    with pytest.raises(EvalExecutionError, match="physical Git repository"):
        await run_attempt(
            task,
            attempt,
            instruction="must not execute without a Git repository",
            config=_config(),
            run_id="run-forged-non-git",
        )

    assert not permission_file.exists()
    assert sorted(path.relative_to(attempt.artifacts).as_posix() for path in attempt.artifacts.rglob("*")) == before_artifacts


@pytest.mark.asyncio
async def test_run_attempt_uses_one_run_turn_event_stream_result_and_verifier(tmp_path: Path) -> None:
    task = _task()
    attempt = _attempt(tmp_path, task)
    provider = FakeProvider(events=(_response(TextPart("done")),))
    calls, verifier = _verifier_calls()
    factory_calls: list[object] = []

    def application_factory(config: EffectiveConfig, **kwargs: object) -> object:
        factory_calls.append(config)
        return create_application(config, **kwargs)

    execution = await run_attempt(
        task,
        attempt,
        instruction="inspect the fixture",
        config=_config(),
        provider_builder=_builder(provider),
        application_factory=application_factory,
        verifier=verifier,
        run_id="run-1",
    )

    assert execution.finish_category is FinishCategory.SUCCESS
    assert execution.turn_result is not None
    assert execution.turn_result.final_text == "done"
    assert len(factory_calls) == 1
    assert len(provider.recorded_requests) == 1
    assert len(execution.events) == len({(event.type, index) for index, event in enumerate(execution.events)})
    assert {event.run_id for event in execution.events} == {"run-1"}
    assert {event.turn_id for event in execution.events} == {execution.turn_result.turn_id}
    assert execution.diagnostics["event_consumer_count"] == 1
    assert execution.diagnostics["result_waiter_count"] == 1
    assert execution.diagnostics["verifier_call_count"] == 1
    assert calls == [attempt.workspace]
    assert execution.record is not None

    manifest = json.loads(attempt.manifest.read_text(encoding="utf-8"))
    assert manifest["execution"]["finish_category"] == "success"
    assert (attempt.artifacts / "events.jsonl").is_file()
    assert (attempt.artifacts / "turn_result.json").is_file()
    assert (attempt.artifacts / "verifier_result.json").is_file()


@pytest.mark.asyncio
async def test_declared_ask_user_resumes_same_run_and_turn_with_typed_response(tmp_path: Path) -> None:
    question = {
        "question_id": "scope",
        "header": "Scope",
        "question": "Which scope?",
        "kind": "text",
    }
    task = _task(
        interactions=(
            InteractionSpec(
                "clarify-scope",
                "ask_user",
                {"answers": {"scope": ["module"]}},
            ),
        )
    )
    attempt = _attempt(tmp_path, task)
    provider = _ScriptedProvider(
        (
            (_response(
                ToolCallPart(
                    "ask-1",
                    "AskUserQuestion",
                    {"questions": [question]},
                ),
                finish_reason=FinishReason.TOOL_CALLS,
            ),),
            (_response(TextPart("resumed")),),
        )
    )
    calls, verifier = _verifier_calls()

    execution = await run_attempt(
        task,
        attempt,
        instruction="ask before continuing",
        config=_config(),
        provider_builder=_builder(provider),
        verifier=verifier,
        run_id="run-ask",
    )

    assert execution.finish_category is FinishCategory.SUCCESS
    assert execution.turn_result is not None
    assert execution.turn_result.final_text == "resumed"
    assert len(provider.requests) == 2
    assert execution.diagnostics["interaction_count"] == 1
    assert execution.diagnostics["cancel_requests"] == 0
    assert calls == [attempt.workspace]
    assert sum(event.type == "turn_started" for event in execution.events) == 1
    assert sum(event.type == "turn_resumed" for event in execution.events) == 1


@pytest.mark.asyncio
async def test_declared_plan_review_uses_typed_approve_on_same_run_and_turn(tmp_path: Path) -> None:
    task = _task(
        behavior_mode="plan",
        interactions=(
            InteractionSpec(
                "review-plan",
                "plan_review",
                {"choice": "approve"},
            ),
        ),
    )
    attempt = _attempt(tmp_path, task)
    provider = _ScriptedProvider(
        (
            (_response(
                ToolCallPart(
                    "plan-1",
                    "ProposePlan",
                    {"plan": "inspect and verify"},
                ),
                finish_reason=FinishReason.TOOL_CALLS,
            ),),
            (_response(TextPart("plan approved")),),
        )
    )
    calls, verifier = _verifier_calls()

    execution = await run_attempt(
        task,
        attempt,
        instruction="propose a plan",
        config=_config(),
        provider_builder=_builder(provider),
        verifier=verifier,
        run_id="run-plan",
    )

    assert execution.finish_category is FinishCategory.SUCCESS
    assert execution.turn_result is not None
    assert execution.turn_result.final_text == "plan approved"
    assert len(provider.requests) == 2
    assert execution.diagnostics["interaction_count"] == 1
    assert execution.diagnostics["interaction_ids"] == ["review-plan"]
    assert sum(event.type == "turn_started" for event in execution.events) == 1
    assert sum(event.type == "turn_resumed" for event in execution.events) == 1
    assert calls == [attempt.workspace]


@pytest.mark.asyncio
async def test_permission_ask_is_cancelled_once_without_session_grant(tmp_path: Path) -> None:
    task = _task()
    attempt = _attempt(tmp_path, task)
    provider = _ScriptedProvider(
        (
            (_response(
                ToolCallPart("outside-1", "OutsideWrite", {"value": "blocked"}),
                finish_reason=FinishReason.TOOL_CALLS,
            ),),
        )
    )
    tool = _OutsideWriteTool(tmp_path / "host-target.txt")
    calls, verifier = _verifier_calls()

    execution = await run_attempt(
        task,
        attempt,
        instruction="do the safe work",
        config=_config(),
        provider_builder=_builder(provider),
        tools=(tool,),
        verifier=verifier,
        run_id="run-permission",
    )

    assert execution.finish_category is FinishCategory.BLOCKED_BY_PERMISSION
    assert execution.turn_result is not None
    assert execution.turn_result.status.value == "cancelled"
    assert execution.diagnostics["cancel_requests"] == 1
    assert execution.diagnostics["session_grant_count"] == 0
    assert tool.executions == 0
    assert len(provider.requests) == 1
    assert calls == [attempt.workspace]


@pytest.mark.asyncio
async def test_undeclared_interaction_is_not_answered_and_is_cancelled_once(tmp_path: Path) -> None:
    task = _task()
    attempt = _attempt(tmp_path, task)
    provider = _ScriptedProvider(
        (
            (_response(
                ToolCallPart(
                    "ask-1",
                    "AskUserQuestion",
                    {
                        "questions": [
                            {
                                "question_id": "missing",
                                "header": "Missing",
                                "question": "No declaration",
                                "kind": "text",
                            }
                        ]
                    },
                ),
                finish_reason=FinishReason.TOOL_CALLS,
            ),),
        )
    )

    execution = await run_attempt(
        task,
        attempt,
        instruction="do not invent an answer",
        config=_config(),
        provider_builder=_builder(provider),
        run_id="run-undeclared",
    )

    assert execution.finish_category is FinishCategory.UNDECLARED_INTERACTION
    assert execution.diagnostics["cancel_requests"] == 1
    assert execution.diagnostics["undeclared_interaction_kind"] == "user_input_required"
    assert len(provider.requests) == 1


@pytest.mark.asyncio
async def test_timeout_cancels_once_and_does_not_retry_workspace(tmp_path: Path) -> None:
    task = _task(timeout_seconds=1)
    attempt = _attempt(tmp_path, task)
    provider = FakeProvider(events=(_response(TextPart("late")),), delay=1.0)

    execution = await run_attempt(
        task,
        attempt,
        instruction="wait",
        config=_config(),
        provider_builder=_builder(provider),
        timeout_seconds=0.02,
        run_id="run-timeout",
    )

    assert execution.finish_category is FinishCategory.TIMEOUT
    assert execution.diagnostics["cancel_requests"] == 1
    assert execution.diagnostics["retry_count"] == 0
    assert len(provider.requests) == 1
    assert execution.turn_result is not None


@pytest.mark.asyncio
async def test_provider_and_verifier_failures_remain_separate_categories(tmp_path: Path) -> None:
    task = _task()
    provider_attempt = _attempt(tmp_path, task, attempt_id="provider")
    provider = FakeProvider(error=ProviderError("provider secret must not be echoed"))
    provider_execution = await run_attempt(
        task,
        provider_attempt,
        instruction="fail at provider",
        config=_config(),
        provider_builder=_builder(provider),
        run_id="run-provider",
    )
    assert provider_execution.finish_category is FinishCategory.AGENT_FAILURE
    assert provider_execution.diagnostics["failure_class"] == "provider"

    verifier_attempt = _attempt(tmp_path, task, attempt_id="verifier")
    verifier_provider = FakeProvider(events=(_response(TextPart("done")),))

    def broken_verifier(_workspace: Path) -> VerifierResult:
        raise RuntimeError("verifier secret must not be echoed")

    verifier_execution = await run_attempt(
        task,
        verifier_attempt,
        instruction="fail at verifier",
        config=_config(),
        provider_builder=_builder(verifier_provider),
        verifier=broken_verifier,
        run_id="run-verifier",
    )
    assert verifier_execution.finish_category is FinishCategory.VERIFIER_ERROR
    assert verifier_execution.diagnostics["failure_class"] == "verifier"
    assert verifier_execution.diagnostics["verifier_call_count"] == 1


@pytest.mark.asyncio
async def test_artifacts_are_redacted_and_runner_errors_are_structured(tmp_path: Path) -> None:
    task = _task()
    attempt = _attempt(tmp_path, task)
    secret = "TOP-SECRET-EVAL-123"
    provider = FakeProvider(events=(_response(TextPart(f"api_key={secret}")),))

    execution = await run_attempt(
        task,
        attempt,
        instruction="keep output safe",
        config=_config(),
        provider_builder=_builder(provider),
        run_id="run-secret",
        secret_values=(secret,),
    )
    assert execution.finish_category is FinishCategory.SUCCESS
    artifact_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in attempt.artifacts.iterdir()
        if path.is_file() and path.name != "manifest.json"
    )
    assert secret not in artifact_text
    assert "<redacted>" in artifact_text

    runner_attempt = _attempt(tmp_path, task, attempt_id="runner")

    def failing_factory(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("runner secret must not be echoed")

    runner_execution = await run_attempt(
        task,
        runner_attempt,
        instruction="fail before run",
        config=_config(),
        application_factory=failing_factory,
        run_id="run-runner",
    )
    assert runner_execution.finish_category is FinishCategory.RUNNER_ERROR
    assert runner_execution.diagnostics["failure_class"] == "runner"
    assert runner_execution.diagnostics["error_type"] == "RuntimeError"
    assert "runner secret" not in (runner_attempt.artifacts / "diagnostics.json").read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_non_fake_provider_is_rejected_before_factory_without_live_authorization(tmp_path: Path) -> None:
    task = _task()
    attempt = _attempt(tmp_path, task)
    config = EffectiveConfig.single_model(
        "remote/eval",
        provider_profile_id="remote",
        provider_kind=ProviderKind.ANTHROPIC,
        remote_model_id="remote-model",
        api_key_env="EVAL_TEST_API_KEY",
    )
    factory_calls: list[object] = []

    def factory(*_args: object, **_kwargs: object) -> object:
        factory_calls.append(True)
        raise AssertionError("live factory must not be reached")

    execution = await run_attempt(
        task,
        attempt,
        instruction="do not call a live provider",
        config=config,
        application_factory=factory,
        run_id="run-no-live",
    )

    assert execution.finish_category is FinishCategory.RUNNER_ERROR
    assert execution.diagnostics["failure_class"] == "runner"
    assert execution.diagnostics["error_type"] == "EvalExecutionError"
    assert factory_calls == []


def test_execution_module_uses_only_application_public_imports() -> None:
    tree = ast.parse(Path("eval/execution.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith("uthcode.core")
            assert not node.module.startswith("uthcode.integrations")
        if isinstance(node, ast.Import):
            assert all(not alias.name.startswith("uthcode.core") for alias in node.names)
            assert all(not alias.name.startswith("uthcode.integrations") for alias in node.names)
