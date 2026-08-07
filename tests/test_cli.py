from __future__ import annotations

import io
import os
from pathlib import Path
import subprocess
import sys
from collections.abc import AsyncIterator, Iterable
from types import SimpleNamespace

import pytest

from uthcode.application import (
    ApplicationRuntimeContext,
    EffectiveConfig,
    GenerationCompleted,
    LaunchOptions,
    Message,
    ProviderKind,
    ProviderResponse,
    create_application,
    TextDelta,
    TextPart,
    TurnHandle,
    UthCodeApplication,
    Usage,
)
from uthcode.core.provider import (
    CancellationToken,
    FinishReason,
    GenerationCancelled,
    GenerationRequest,
    NetworkError,
    ProviderError,
    RateLimitError,
    ReasoningPart,
    ReasoningDelta,
    ToolCallPart,
    ToolDefinition,
)
from uthcode.core.tool import ToolExecutionResult
from uthcode.interfaces.cli import main
from uthcode.integrations.providers.fake import FakeProvider


def _completed(
    text: str = "done",
    *parts: object,
    finish_reason: FinishReason = FinishReason.STOP,
) -> GenerationCompleted:
    return GenerationCompleted(
        ProviderResponse(
            message=Message("assistant", (TextPart(text), *parts)),
            usage=Usage(),
            finish_reason=finish_reason,
        )
    )


def _config(model: str = "fake/ref") -> EffectiveConfig:
    return EffectiveConfig.single_model(
        model,
        provider_profile_id="fake",
        provider_kind=ProviderKind.FAKE,
        remote_model_id="fake-model",
    )


def _application(
    *,
    events: tuple[object, ...] = (_completed("fake response"),),
    error: NetworkError | None = None,
) -> UthCodeApplication:
    return UthCodeApplication(
        FakeProvider(
            events=events,  # type: ignore[arg-type]
            error=error,
        )
    )


class _ScriptedProvider(FakeProvider):
    def __init__(self, scripts: Iterable[Iterable[ProviderEvent]]) -> None:
        super().__init__()
        self._scripts = tuple(tuple(script) for script in scripts)

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


class _CancelledProvider(FakeProvider):
    async def stream(
        self,
        request: GenerationRequest,
        *,
        cancellation: CancellationToken,
    ) -> AsyncIterator[ProviderEvent]:
        del request, cancellation
        raise GenerationCancelled()
        yield  # pragma: no cover


class _TerminalLessTurn:
    def events(self):  # type: ignore[no-untyped-def]
        async def stream():  # type: ignore[no-untyped-def]
            yield SimpleNamespace(event_type="turn_started")

        return stream()

    def cancel(self) -> bool:
        return True


class _TerminalLessRun:
    def __init__(self) -> None:
        self.turn = _TerminalLessTurn()

    def start_turn(self, prompt: str) -> _TerminalLessTurn:
        del prompt
        return self.turn


class _TerminalLessApplication:
    def __init__(self) -> None:
        self.run = _TerminalLessRun()

    def create_run(self) -> _TerminalLessRun:
        return self.run


class _SecretTool:
    definition = ToolDefinition(
        "Reveal",
        "Return a secret test value.",
        {
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
            "additionalProperties": False,
        },
    )

    async def execute(
        self,
        arguments: dict[str, object],
        *,
        cancellation: CancellationToken,
    ) -> ToolExecutionResult:
        del arguments, cancellation
        return ToolExecutionResult("CLI-TOOL-RESULT-SECRET")


def _injected_main(
    argv: list[str],
    application: UthCodeApplication,
    *,
    stdin: io.StringIO | None = None,
) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    result = main(
        argv,
        config_loader=lambda _options: _config(),
        application_factory=lambda _config, *, runtime_context: application,
        stdin=stdin,
        stdout=stdout,
        stderr=stderr,
    )
    return result, stdout.getvalue(), stderr.getvalue()


def test_default_cli_passes_one_formal_application_to_injected_tui_runner() -> None:
    application = _application()
    seen: list[UthCodeApplication] = []

    result = main(
        [],
        config_loader=lambda _options: _config(),
        application_factory=lambda _config, *, runtime_context: application,
        tui_runner=lambda received: seen.append(received) or 17,
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )

    assert result == 17
    assert seen == [application]


def test_exec_position_prompt_streams_text_and_finishes_with_newline() -> None:
    application = _application(events=(TextDelta("hello"), _completed("ignored")))

    result, stdout, stderr = _injected_main(["exec", "hello"], application)

    assert result == 0
    assert stdout == "ignored\n"
    assert stderr == ""
    request = application.provider.recorded_requests[0]
    assert request.messages[0].parts[0].text == "hello"


def test_exec_reads_stdin_and_keeps_slash_prompt_as_plain_text() -> None:
    application = _application()

    result, stdout, stderr = _injected_main(
        ["exec"],
        application,
        stdin=io.StringIO("/help\n"),
    )

    assert result == 0
    assert stdout == "fake response\n"
    assert stderr == ""
    assert application.provider.recorded_requests[0].messages[0].parts[0].text == "/help"


def test_exec_rejects_empty_prompt_without_creating_a_request() -> None:
    application = _application()
    result, stdout, stderr = _injected_main(["exec"], application, stdin=io.StringIO("  \n"))

    assert result == 2
    assert stdout == ""
    assert "prompt" in stderr
    assert application.provider.recorded_requests == ()


def test_exec_classifies_provider_errors_and_cancellation() -> None:
    secret = "sk-live-secret"
    failed = _application(events=(), error=NetworkError(secret))
    result, stdout, stderr = _injected_main(["exec", "hello"], failed)
    assert result == 1
    assert stdout == ""
    assert "provider" in stderr
    assert secret not in stderr

    cancelled = UthCodeApplication(_CancelledProvider())
    result, stdout, stderr = _injected_main(["exec", "hello"], cancelled)
    assert result == 130
    assert stdout == ""
    assert "cancelled" in stderr


def test_exec_projects_reasoning_and_unclassified_text_only_to_stderr_or_terminal() -> None:
    application = _application(
        events=(
            # The first delta is deliberately not classified until the
            # terminal assistant message arrives.
            ReasoningDelta("thinking"),
            TextDelta("unclassified partial"),
            _completed("final answer", ReasoningPart("terminal reasoning")),
        )
    )

    result, stdout, stderr = _injected_main(["exec", "hello"], application)

    assert result == 0
    assert stdout == "final answer\n"
    assert stderr == "thinking\n"
    assert "unclassified partial" not in stdout + stderr


def test_exec_projects_incomplete_message_to_stderr_and_fails() -> None:
    application = _application(
        events=(_completed("incomplete answer", finish_reason=FinishReason.INCOMPLETE),)
    )

    result, stdout, stderr = _injected_main(["exec", "hello"], application)

    assert result == 1
    assert stdout == ""
    assert "incomplete answer" in stderr
    assert "max_output_tokens" in stderr


def test_exec_projects_tool_activity_without_tool_result_or_arguments() -> None:
    secret = "CLI-TOOL-RESULT-SECRET"
    call = ToolCallPart("call-1", "Reveal", {"value": secret})
    provider = _ScriptedProvider(
        (
            (_completed("working", call, finish_reason=FinishReason.TOOL_CALLS),),
            (_completed("final answer"),),
        )
    )
    application = create_application(
        _config(),
        provider_builder=lambda _provider, _model: provider,
        runtime_context=ApplicationRuntimeContext.from_system(workdir=Path.cwd()),
        tools=(_SecretTool(),),
    )

    result, stdout, stderr = _injected_main(["exec", "hello"], application)

    assert result == 0
    assert stdout == "final answer\n"
    assert "working" in stderr
    assert "tool running: Reveal (Reveal)" in stderr
    assert "tool finished: Reveal (Reveal)" in stderr
    assert secret not in stdout + stderr
    assert "ToolResult" not in stdout + stderr
    assert provider.requests[1].messages[-1].parts[0].content == secret


def test_exec_cancels_turn_when_agent_pauses_for_user_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cancel_calls = 0
    original_cancel = TurnHandle.cancel

    def record_cancel(handle: TurnHandle) -> bool:
        nonlocal cancel_calls
        cancel_calls += 1
        return original_cancel(handle)

    monkeypatch.setattr(TurnHandle, "cancel", record_cancel)
    call = ToolCallPart(
        "ask-1",
        "AskUserQuestion",
        {
            "questions": [
                {
                    "question_id": "q1",
                    "header": "Choice",
                    "question": "Which value should be used?",
                    "kind": "text",
                }
            ]
        },
    )
    provider = _ScriptedProvider(
        ((_completed("need input", call, finish_reason=FinishReason.TOOL_CALLS),),)
    )
    application = create_application(
        _config(),
        provider_builder=lambda _provider, _model: provider,
        runtime_context=ApplicationRuntimeContext.from_system(workdir=Path.cwd()),
    )

    result, stdout, stderr = _injected_main(["exec", "hello"], application)

    assert result == 1
    assert stdout == ""
    assert "generation requires interactive input" in stderr
    assert "TurnPaused" not in stderr
    assert "turn ended without a terminal event" not in stderr
    assert "provider error" not in stderr
    assert cancel_calls == 1


@pytest.mark.parametrize(
    ("error", "diagnostic"),
    [
        (NetworkError("network-secret"), "provider temporarily unavailable"),
        (RateLimitError("rate-secret"), "provider temporarily unavailable"),
    ],
)
def test_exec_cancels_turn_when_provider_pauses(
    error: ProviderError,
    diagnostic: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cancel_calls = 0
    original_cancel = TurnHandle.cancel

    def record_cancel(handle: TurnHandle) -> bool:
        nonlocal cancel_calls
        cancel_calls += 1
        return original_cancel(handle)

    monkeypatch.setattr(TurnHandle, "cancel", record_cancel)
    application = UthCodeApplication(
        FakeProvider(events=(), error=error),  # type: ignore[arg-type]
    )

    result, stdout, stderr = _injected_main(["exec", "hello"], application)

    assert result == 1
    assert stdout == ""
    assert diagnostic in stderr
    assert "network-secret" not in stderr
    assert "rate-secret" not in stderr
    assert "turn ended without a terminal event" not in stderr
    assert "provider error" not in stderr
    assert cancel_calls == 1


def test_exec_keeps_missing_terminal_diagnostic_for_non_pause_stream() -> None:
    application = _TerminalLessApplication()

    result, stdout, stderr = _injected_main(
        ["exec", "hello"],
        application,  # type: ignore[arg-type]
    )

    assert result == 1
    assert stdout == ""
    assert stderr == "provider error: turn ended without a terminal event\n"


@pytest.mark.parametrize("arguments", [["exec", "hello"], []])
def test_provider_factory_errors_are_redacted_for_all_cli_entries(
    arguments: list[str],
) -> None:
    secret = "sk-factory-secret"
    stdout = io.StringIO()
    stderr = io.StringIO()

    def fail_factory(
        _configuration: EffectiveConfig,
        *,
        runtime_context,
    ) -> UthCodeApplication:
        raise NetworkError(secret)

    result = main(
        arguments,
        config_loader=lambda _options: _config(),
        application_factory=fail_factory,
        tui_runner=lambda _application: 0,
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 1
    assert stdout.getvalue() == ""
    assert "provider error" in stderr.getvalue()
    assert secret not in stderr.getvalue()


def test_exec_cwd_and_model_are_process_overrides_only(tmp_path: Path) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    project.mkdir()
    user_config = home / ".uthcode" / "config.toml"
    user_config.parent.mkdir(parents=True)
    original = '''model = "fake/ref"\n\n[providers.fake]\nkind = "fake"\n\n[models."fake/ref"]\nprovider = "fake"\nmodel = "fake-model"\n'''
    user_config.write_text(original, encoding="utf-8")

    captured: list[LaunchOptions] = []

    def loader(options: LaunchOptions) -> EffectiveConfig:
        captured.append(options)
        return _config()

    application = _application()
    result = main(
        ["exec", "--cwd", str(project), "--model", "fake/ref", "hello"],
        config_loader=loader,
        application_factory=lambda _config, *, runtime_context: application,
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )

    assert result == 0
    assert captured[0].cwd == project
    assert captured[0].model == "fake/ref"
    assert user_config.read_text(encoding="utf-8") == original


def test_exec_uses_one_normalized_workdir_for_config_and_prompt(
    tmp_path: Path,
) -> None:
    requested = tmp_path / "nested" / ".." / "project"
    expected = (tmp_path / "project").resolve()
    captured_options: list[LaunchOptions] = []
    captured_contexts = []
    providers: list[FakeProvider] = []

    def loader(options: LaunchOptions) -> EffectiveConfig:
        captured_options.append(options)
        return _config()

    def factory(
        _configuration: EffectiveConfig,
        *,
        runtime_context,
    ) -> UthCodeApplication:
        captured_contexts.append(runtime_context)
        provider = FakeProvider(events=(_completed("response"),))
        providers.append(provider)
        return UthCodeApplication(provider, runtime_context=runtime_context)

    stdout = io.StringIO()
    stderr = io.StringIO()
    result = main(
        ["exec", "--cwd", str(requested), "hello"],
        config_loader=loader,
        application_factory=factory,
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0
    assert captured_options[0].cwd == expected
    assert captured_contexts[0].workdir == expected
    prompt = providers[0].recorded_requests[0].system_prompt
    assert prompt is not None
    assert "工作目录：" in prompt
    assert "project" in prompt


def test_exec_default_workdir_is_shared_with_application_context() -> None:
    workdir = Path.cwd()
    captured_options: list[LaunchOptions] = []
    captured_contexts = []

    def loader(options: LaunchOptions) -> EffectiveConfig:
        captured_options.append(options)
        return _config()

    def factory(
        _configuration: EffectiveConfig,
        *,
        runtime_context,
    ) -> UthCodeApplication:
        captured_contexts.append(runtime_context)
        return _application()

    result = main(
        ["exec", "hello"],
        config_loader=loader,
        application_factory=factory,
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )

    assert result == 0
    assert captured_options[0].cwd == workdir.resolve()
    assert captured_contexts[0].workdir == workdir.resolve()


def test_module_entry_import_does_not_require_a_textual_app_for_exec() -> None:
    script = """
import io
import sys
from uthcode.application import EffectiveConfig, ProviderKind, create_application
from uthcode.interfaces.cli import main

configuration = EffectiveConfig.single_model('fake/ref', provider_kind=ProviderKind.FAKE)
result = main(
    ['exec', 'hello'],
    config_loader=lambda _options: configuration,
    application_factory=create_application,
    stdout=io.StringIO(),
    stderr=io.StringIO(),
)
assert result == 0
assert 'uthcode.interfaces.tui' not in sys.modules
"""
    environment = os.environ.copy()
    source_root = str(Path(__file__).parents[1] / "src")
    environment["PYTHONPATH"] = source_root + os.pathsep + environment.get("PYTHONPATH", "")
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).parents[1],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def _subprocess_environment(home: Path) -> dict[str, str]:
    environment = os.environ.copy()
    source_root = str(Path(__file__).parents[1] / "src")
    environment["PYTHONPATH"] = source_root + os.pathsep + environment.get("PYTHONPATH", "")
    environment["HOME"] = str(home)
    environment["USERPROFILE"] = str(home)
    return environment


def _write_fake_user_config(home: Path) -> Path:
    path = home / ".uthcode" / "config.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '''model = "local/echo"\n\n[providers.local]\nkind = "fake"\n\n[models."local/echo"]\nprovider = "local"\nmodel = "echo"\n''',
        encoding="utf-8",
    )
    return path


def test_formal_module_exec_uses_fake_config_without_tui_or_network(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_fake_user_config(home)
    result = subprocess.run(
        [sys.executable, "-m", "uthcode", "exec", "hello"],
        cwd=tmp_path,
        env=_subprocess_environment(home),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout == "fake response\n"
    assert result.stderr == ""
    assert "\x1b[" not in result.stdout + result.stderr


def test_formal_module_exec_first_run_creates_template_and_stops(tmp_path: Path) -> None:
    home = tmp_path / "empty-home"
    first_run = subprocess.run(
        [sys.executable, "-m", "uthcode", "exec", "hello"],
        cwd=tmp_path,
        env=_subprocess_environment(home),
        capture_output=True,
        text=True,
        check=False,
    )

    template = home / ".uthcode" / "config.toml"
    assert first_run.returncode == 2
    assert first_run.stdout == ""
    assert str(template.resolve()) in first_run.stderr
    assert "configuration is not initialized" in first_run.stderr
    assert template.is_file()
    assert "sk-" not in template.read_text(encoding="utf-8")

    second_run = subprocess.run(
        [sys.executable, "-m", "uthcode", "exec", "hello"],
        cwd=tmp_path,
        env=_subprocess_environment(home),
        capture_output=True,
        text=True,
        check=False,
    )

    assert second_run.returncode == 2
    assert second_run.stdout == ""
    assert "configuration is not initialized" in second_run.stderr
    assert "edit and uncomment" in second_run.stderr


def test_formal_entries_reject_project_provider_data(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_fake_user_config(home)
    root = tmp_path / "repo"
    cwd = root / "nested"
    cwd.mkdir(parents=True)
    (root / ".git").mkdir()
    project_config = root / ".uthcode" / "config.toml"
    project_config.parent.mkdir()
    project_config.write_text(
        '[providers.evil]\nkind = "fake"\n',
        encoding="utf-8",
    )

    for arguments in (
        ["exec", "hello"],
        [],
    ):
        result = subprocess.run(
            [sys.executable, "-m", "uthcode", *arguments],
            cwd=cwd,
            env=_subprocess_environment(home),
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 2
        assert str(project_config.resolve()) in result.stderr
        assert "providers" in result.stderr
