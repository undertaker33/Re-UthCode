from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from collections.abc import AsyncIterator, Iterable
from pathlib import Path

import pytest

from uthcode.application import (
    AgentEvent,
    AgentRun,
    ApplicationRuntimeContext,
    EffectiveConfig,
    ModelProfile,
    ProviderKind,
    ProviderProfile,
    RunSnapshot,
    RunStatus,
    TextPart,
    TurnHandle,
    TurnResult,
    UthCodeApplication,
    create_application,
)
from uthcode.core.agent_events import (
    ToolFinished,
    ToolStarted,
    TurnCancelled,
    TurnCompleted,
)
from uthcode.core.provider import (
    CancellationToken,
    FinishReason,
    GenerationCompleted,
    GenerationRequest,
    Message,
    ProviderEvent,
    ProviderIdentity,
    ProviderResponse,
    ProviderError,
    ReasoningDelta as ProviderReasoningDelta,
    TextPart,
    ToolCallPart,
    ToolResultPart,
    Usage,
)
from uthcode.integrations.providers.fake import FakeProvider
from uthcode.integrations.tools.factory import create_default_tools
from uthcode.application.tools import ApplicationToolService


def _response(
    *parts: object,
    finish_reason: FinishReason = FinishReason.STOP,
    usage: Usage | None = None,
) -> GenerationCompleted:
    return GenerationCompleted(
        ProviderResponse(
            message=Message("assistant", tuple(parts)),
            finish_reason=finish_reason,
            usage=usage or Usage(),
        )
    )


class _ScriptedProvider:
    def __init__(self, scripts: Iterable[Iterable[ProviderEvent]], *, model: str = "fake-model") -> None:
        self.identity = ProviderIdentity("fake", "script", model)
        self.scripts = tuple(tuple(script) for script in scripts)
        self.requests: list[GenerationRequest] = []

    async def stream(
        self,
        request: GenerationRequest,
        *,
        cancellation: CancellationToken,
    ) -> AsyncIterator[ProviderEvent]:
        self.requests.append(request)
        cancellation.raise_if_cancelled()
        index = min(len(self.requests) - 1, len(self.scripts) - 1)
        for event in self.scripts[index]:
            cancellation.raise_if_cancelled()
            yield event


async def _collect(handle: TurnHandle) -> list[AgentEvent]:
    return [event async for event in handle.events()]


async def _start_after_release(run: AgentRun, user_input: str) -> TurnHandle:
    for _ in range(200):
        try:
            return run.start_turn(user_input)
        except RuntimeError as exc:
            if "active Turn" not in str(exc):
                raise
            await asyncio.sleep(0)
    raise AssertionError("terminal Turn did not release the Run")


def _config() -> EffectiveConfig:
    return EffectiveConfig.single_model(
        "local/ref",
        provider_profile_id="local",
        provider_kind=ProviderKind.FAKE,
        remote_model_id="fake-model",
    )


def _context(workdir: Path) -> ApplicationRuntimeContext:
    return ApplicationRuntimeContext.from_system(
        workdir=workdir,
        platform_name="TestOS",
        platform_release="1.0",
        current_date="2026-08-06",
    )


@pytest.mark.asyncio
async def test_turn_can_start_without_an_event_loop_and_result_is_reusable() -> None:
    application = UthCodeApplication(
        FakeProvider(events=(_response(TextPart("answer")),))
    )
    run = application.create_run(run_id="run-1")
    handle = run.start_turn("hello")

    assert isinstance(run, AgentRun)
    assert isinstance(handle, TurnHandle)
    assert isinstance(run.snapshot(), RunSnapshot)
    assert run.snapshot().status is RunStatus.RUNNING
    assert isinstance(await handle.result(), TurnResult)
    first = await handle.result()
    second = await handle.result()

    assert first is second
    assert first.status is RunStatus.COMPLETED
    assert run.snapshot().status is RunStatus.COMPLETED
    assert handle.cancel() is False


@pytest.mark.asyncio
async def test_events_and_result_share_one_execution_and_events_are_single_consumer() -> None:
    provider = FakeProvider(events=(_response(TextPart("answer")),))
    run = UthCodeApplication(provider).create_run()
    handle = run.start_turn("hello")

    events_task = asyncio.create_task(_collect(handle))
    result_task = asyncio.create_task(handle.result())
    events = await events_task
    result = await result_task

    assert isinstance(events[-1], TurnCompleted)
    assert result.final_text == "answer"
    assert len(provider.recorded_requests) == 1
    with pytest.raises(RuntimeError, match="only be consumed once"):
        handle.events()


@pytest.mark.asyncio
async def test_active_turn_is_exclusive_and_cancel_is_idempotent() -> None:
    provider = FakeProvider(events=(_response(TextPart("answer")),), delay=0.05)
    run = UthCodeApplication(provider).create_run()
    active = run.start_turn("first")

    with pytest.raises(RuntimeError, match="active Turn"):
        run.start_turn("second")
    assert active.cancel() is True
    assert active.cancel() is False
    result = await active.result()

    assert result.status is RunStatus.CANCELLED
    assert run.snapshot().status is RunStatus.CANCELLED
    assert isinstance((await run.start_turn("after cancel").result()), TurnResult)


@pytest.mark.asyncio
async def test_completed_turn_releases_run_when_event_iterator_is_closed_after_first_event() -> None:
    provider = FakeProvider(events=(_response(TextPart("answer")),), delay=0.01)
    run = UthCodeApplication(provider).create_run()
    handle = run.start_turn("first")
    event_iterator = handle.events()

    assert (await anext(event_iterator)).event_type == "turn_started"
    await event_iterator.aclose()

    next_handle = await _start_after_release(run, "second")
    assert (await next_handle.result()).status is RunStatus.COMPLETED
    assert len(provider.recorded_requests) == 2


@pytest.mark.asyncio
async def test_events_call_without_iteration_starts_and_releases_the_run() -> None:
    provider = FakeProvider(events=(_response(TextPart("answer")),), delay=0.01)
    run = UthCodeApplication(provider).create_run()
    event_iterator = run.start_turn("first").events()

    next_handle = await _start_after_release(run, "second")
    assert (await next_handle.result()).status is RunStatus.COMPLETED
    await event_iterator.aclose()
    assert len(provider.recorded_requests) == 2


@pytest.mark.asyncio
async def test_cancelled_event_consumer_does_not_hold_a_completed_run() -> None:
    provider = FakeProvider(events=(_response(TextPart("answer")),), delay=0.01)
    run = UthCodeApplication(provider).create_run()
    handle = run.start_turn("first")
    first_event_seen = asyncio.Event()

    async def consume_until_cancelled() -> None:
        async for _event in handle.events():
            first_event_seen.set()
            await asyncio.Future()

    consumer = asyncio.create_task(consume_until_cancelled())
    await asyncio.wait_for(first_event_seen.wait(), timeout=1)
    consumer.cancel()
    with pytest.raises(asyncio.CancelledError):
        await consumer

    next_handle = await _start_after_release(run, "second")
    assert (await next_handle.result()).status is RunStatus.COMPLETED
    assert len(provider.recorded_requests) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal_path", ("completed", "failed", "cancelled"))
async def test_every_provider_terminal_path_releases_run_once(terminal_path: str) -> None:
    if terminal_path == "failed":
        provider = FakeProvider(error=ProviderError("synthetic provider failure"))
    elif terminal_path == "cancelled":
        provider = FakeProvider(
            events=(_response(TextPart("answer")),),
            delay=0.02,
        )
    else:
        provider = FakeProvider(events=(_response(TextPart("answer")),))

    run = UthCodeApplication(provider).create_run()
    handle = run.start_turn("first")
    if terminal_path == "cancelled":
        result_task = asyncio.create_task(handle.result())
        await asyncio.sleep(0.005)
        assert handle.cancel() is True
        result = await result_task
    else:
        result = await handle.result()
    expected_status = {
        "completed": RunStatus.COMPLETED,
        "failed": RunStatus.FAILED,
        "cancelled": RunStatus.CANCELLED,
    }[terminal_path]
    assert result.status is expected_status

    next_handle = await _start_after_release(run, "second")
    await next_handle.result()
    assert len(provider.recorded_requests) == 2


@pytest.mark.asyncio
async def test_same_run_history_is_retained_and_different_runs_are_isolated() -> None:
    provider = _ScriptedProvider(
        (
            (_response(TextPart("first answer")),),
            (_response(TextPart("second answer")),),
            (_response(TextPart("other answer")),),
        )
    )
    application = UthCodeApplication(provider)
    first_run = application.create_run(run_id="first-run")
    second_run = application.create_run(run_id="second-run")

    await first_run.start_turn("first question").result()
    await first_run.start_turn("second question").result()
    await second_run.start_turn("isolated question").result()

    first_second_request = provider.requests[1]
    isolated_request = provider.requests[2]
    assert [message.role for message in first_second_request.messages] == [
        "user",
        "assistant",
        "user",
    ]
    assert first_second_request.messages[0].parts == (TextPart("first question"),)
    assert isolated_request.messages[0].parts == (TextPart("isolated question"),)
    assert len(isolated_request.messages) == 1
    assert first_run.snapshot().run_id == "first-run"
    assert second_run.snapshot().run_id == "second-run"


@pytest.mark.asyncio
async def test_model_switch_after_start_does_not_change_active_turn(tmp_path: Path) -> None:
    first_provider = _ScriptedProvider(((_response(TextPart("old answer")),),), model="remote-one")
    second_provider = _ScriptedProvider(((_response(TextPart("new answer")),),), model="remote-two")
    config = EffectiveConfig(
        model="one/ref",
        providers={
            "one": ProviderProfile("one", ProviderKind.FAKE),
            "two": ProviderProfile("two", ProviderKind.FAKE),
        },
        models={
            "one/ref": ModelProfile("one/ref", "one", "remote-one"),
            "two/ref": ModelProfile("two/ref", "two", "remote-two"),
        },
    )
    providers = {"one/ref": first_provider, "two/ref": second_provider}

    def build(_provider, model):
        return providers[model.model_ref]

    application = create_application(
        config,
        provider_builder=build,
        model_writer=lambda _model_ref: None,
        runtime_context=_context(tmp_path),
    )
    run = application.create_run()
    active = run.start_turn("keep old snapshot")
    application.select_model("two/ref")
    await active.result()

    assert len(first_provider.requests) == 1
    assert len(second_provider.requests) == 0
    assert "模型选择：one/ref" in (first_provider.requests[0].system_prompt or "")

    await run.start_turn("use new snapshot").result()
    assert len(second_provider.requests) == 1
    assert "模型选择：two/ref" in (second_provider.requests[0].system_prompt or "")


@pytest.mark.asyncio
async def test_application_formal_headless_e2e_hides_tool_result_and_uses_real_read_file(
    tmp_path: Path,
) -> None:
    hidden_content = "W02-HIDDEN-READFILE-CONTENT"
    note = tmp_path / "note.txt"
    note.write_text(hidden_content + "\n", encoding="utf-8")
    call = ToolCallPart("read-call", "ReadFile", {"path": "note.txt"})
    provider = _ScriptedProvider(
        (
            (
                ProviderReasoningDelta("I will read the note."),
                _response(
                    TextPart("Reading the note."),
                    call,
                    finish_reason=FinishReason.TOOL_CALLS,
                    usage=Usage(input_tokens=2, output_tokens=3),
                ),
            ),
            (
                ProviderReasoningDelta("I have the result."),
                _response(
                    TextPart("The note says exactly what was requested."),
                    usage=Usage(input_tokens=4, output_tokens=5),
                ),
            ),
        )
    )
    application = create_application(
        _config(),
        provider_builder=lambda _provider, _model: provider,
        runtime_context=_context(tmp_path),
    )

    run = application.create_run(run_id="headless-run")
    handle = run.start_turn("Read note.txt")
    events = await _collect(handle)
    result = await handle.result()

    assert [event.event_type for event in events].index("reasoning_delta") < [
        event.event_type for event in events
    ].index("tool_started")
    assert sum(isinstance(event, ToolFinished) for event in events) == 1
    assert sum(isinstance(event, TurnCompleted) for event in events) == 1
    assert not any(isinstance(event, TurnCancelled) for event in events)
    tool_finished = next(event for event in events if isinstance(event, ToolFinished))
    assert tool_finished.command == "ReadFile note.txt"
    assert hidden_content not in tool_finished.to_json()
    assert hidden_content not in result.to_json()
    assert hidden_content not in run.snapshot().to_json()

    second_request = provider.requests[1]
    assert second_request.tools == application.tool_definitions()
    assert second_request.messages[-2].role == "assistant"
    tool_message = second_request.messages[-1]
    assert tool_message.role == "tool"
    assert tool_message.parts == (ToolResultPart("read-call", f"1\t{hidden_content}"),)
    assert result.final_text == "The note says exactly what was requested."
    assert "I have the result." not in (result.final_text or "")


@pytest.mark.asyncio
async def test_tool_summary_failure_does_not_block_tool_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hidden_content = "W02-SUMMARY-FAILURE-READ-CONTENT"
    (tmp_path / "note.txt").write_text(hidden_content + "\n", encoding="utf-8")
    call = ToolCallPart("read-call", "ReadFile", {"path": "note.txt"})
    provider = _ScriptedProvider(
        (
            (_response(call, finish_reason=FinishReason.TOOL_CALLS),),
            (_response(TextPart("done")),),
        )
    )

    def fail_summary(_self: ApplicationToolService, _call: ToolCallPart) -> str:
        raise RuntimeError("summary failed")

    monkeypatch.setattr(ApplicationToolService, "describe_tool_call", fail_summary)
    application = create_application(
        _config(),
        provider_builder=lambda _provider, _model: provider,
        runtime_context=_context(tmp_path),
    )

    events = await _collect(application.create_run().start_turn("read"))

    tool_finished = next(event for event in events if isinstance(event, ToolFinished))
    assert tool_finished.command == "<tool summary unavailable>"
    assert provider.requests[1].messages[-1].parts == (
        ToolResultPart("read-call", f"1\t{hidden_content}"),
    )


def test_headless_application_import_does_not_load_interfaces() -> None:
    source_root = str(Path(__file__).parents[1] / "src")
    environment = os.environ.copy()
    environment["PYTHONPATH"] = source_root + os.pathsep + environment.get("PYTHONPATH", "")
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys, uthcode.application; "
            "assert 'uthcode.interfaces' not in sys.modules",
        ],
        cwd=Path(__file__).parents[1],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_tool_descriptions_are_bounded_and_do_not_echo_write_content_or_unknown_arguments(
    tmp_path: Path,
) -> None:
    service = ApplicationToolService(
        create_default_tools(tmp_path),
        workdir=tmp_path,
    )
    secret = "W02-SECRET-DO-NOT-DISPLAY"

    write_summary = service.describe_tool_call(
        ToolCallPart("write", "WriteFile", {"path": "note.txt", "content": secret})
    )
    read_summary = service.describe_tool_call(
        ToolCallPart("read", "ReadFile", {"path": "note.txt", "offset": 4})
    )
    edit_summary = service.describe_tool_call(
        ToolCallPart(
            "edit",
            "EditFile",
            {"path": "note.txt", "old_string": secret, "new_string": secret},
        )
    )
    bash_summary = service.describe_tool_call(
        ToolCallPart("bash", "Bash", {"command": f"echo {secret}"})
    )
    grep_summary = service.describe_tool_call(
        ToolCallPart("grep", "Grep", {"pattern": "needle", "path": "src"})
    )
    unknown_summary = service.describe_tool_call(
        ToolCallPart("unknown", "Missing", {"value": secret})
    )
    long_summary = service.describe_tool_call(
        ToolCallPart("glob", "Glob", {"pattern": "x" * 500, "path": "."})
    )

    assert write_summary == "WriteFile note.txt"
    assert read_summary == "ReadFile note.txt"
    assert edit_summary == "EditFile note.txt"
    assert secret not in bash_summary
    assert grep_summary == "Grep pattern=needle path=src"
    assert unknown_summary == "<unknown tool>"
    assert len(long_summary) == 240
    assert long_summary.endswith("…")


@pytest.mark.asyncio
async def test_tool_summaries_redact_known_values_and_common_credentials_in_both_events(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment_value = "W02-ENV-PLAIN-VALUE-ALPHA-123456"
    short_environment_value = "q7z"
    two_character_environment_value = "qz"
    one_character_environment_value = "q"
    bare_api_key = "sk-W02SyntheticKeyValue123456789"
    bearer_token = "W02BearerTokenValue123456789"
    spaced_token = "W02PlainCredential739184"
    assigned_api_key = "W02AssignedCredential846291"
    basic_credential = "W02BasicCredential517293"
    monkeypatch.setenv("W02_RUNTIME_VALUE_SOURCE", environment_value)
    monkeypatch.setenv("W02_SHORT_RUNTIME_VALUE_SOURCE", short_environment_value)
    monkeypatch.setenv("W02_TWO_CHARACTER_VALUE_SOURCE", two_character_environment_value)
    monkeypatch.setenv("W02_ONE_CHARACTER_VALUE_SOURCE", one_character_environment_value)
    call = ToolCallPart(
        "bash-call",
        "Bash",
        {
            "command": (
                f"echo {environment_value} {short_environment_value} "
                f"{two_character_environment_value} {one_character_environment_value} "
                f"{bare_api_key} "
                f"--token {spaced_token} --api-key={assigned_api_key} "
                f'Authorization: Bearer {bearer_token} '
                f'-H "Authorization: Basic {basic_credential}"'
            )
        },
    )
    provider = _ScriptedProvider(
        (
            (_response(call, finish_reason=FinishReason.TOOL_CALLS),),
            (_response(TextPart("done")),),
        )
    )
    application = create_application(
        _config(),
        provider_builder=lambda _provider, _model: provider,
        runtime_context=_context(tmp_path),
    )

    events = await _collect(application.create_run().start_turn("run safe Bash"))
    tool_events = [
        event for event in events if isinstance(event, (ToolStarted, ToolFinished))
    ]

    assert len(tool_events) == 2
    assert all(event.command.startswith("Bash echo") for event in tool_events)
    serialized = " ".join(event.to_json() for event in tool_events)
    assert environment_value not in serialized
    assert short_environment_value not in serialized
    assert two_character_environment_value not in serialized
    assert all(
        f" {one_character_environment_value} " not in event.command
        for event in tool_events
    )
    assert bare_api_key not in serialized
    assert bearer_token not in serialized
    assert spaced_token not in serialized
    assert "PlainCredential739184" not in serialized
    assert assigned_api_key not in serialized
    assert "AssignedCredential846291" not in serialized
    assert basic_credential not in serialized
    assert "BasicCredential517293" not in serialized
    assert "W02" not in serialized
    assert all("<redacted>" in event.command for event in tool_events)

    monkeypatch.setenv("W02_SHORT_ZERO", "0")
    monkeypatch.setenv("W02_SHORT_ONE", "1")
    ordinary_summary = ApplicationToolService(
        create_default_tools(tmp_path),
        workdir=tmp_path,
    ).describe_tool_call(
        ToolCallPart("ordinary", "Bash", {"command": "echo 2026-08-06"})
    )
    assert ordinary_summary == "Bash echo 2026-08-06"

    configured_secret = "xy7"
    monkeypatch.setenv("W02_CONFIG_SECRET_SOURCE", configured_secret)
    configured_summary = ApplicationToolService(
        create_default_tools(tmp_path),
        workdir=tmp_path,
        secret_env_names=("W02_CONFIG_SECRET_SOURCE",),
    ).describe_tool_call(
        ToolCallPart("configured", "Bash", {"command": f"echo {configured_secret}"})
    )
    assert configured_summary == "Bash echo <redacted>"
