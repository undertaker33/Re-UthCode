from __future__ import annotations

from collections.abc import AsyncIterator, Iterable

import pytest

from uthcode.application import (
    ApplicationRuntimeContext,
    EffectiveConfig,
    ProviderKind,
    SearchConfiguration,
    create_application,
)
from uthcode.application.tools import ApplicationToolService
from uthcode.core.provider import (
    CancellationToken,
    FinishReason,
    GenerationCompleted,
    GenerationRequest,
    Message,
    ModelLimits,
    ProviderEvent,
    ProviderIdentity,
    ProviderResponse,
    TextPart,
    ToolCallPart,
    ToolDefinition,
    Usage,
)
from uthcode.core.permission import PermissionMode
from uthcode.core.secrets import SecretValue
from uthcode.core.tool import (
    ToolExecutionOutcome,
    ToolExecutionResult,
    ToolExecutionStatus,
    ToolProgress as CoreToolProgress,
)
from uthcode.integrations.tools.factory import create_default_tools


TEST_LIMITS = ModelLimits(max_input_tokens=1_000_000, source="test.fake")


def _configuration() -> EffectiveConfig:
    return EffectiveConfig.single_model(
        "test/ref",
        provider_profile_id="test",
        provider_kind=ProviderKind.FAKE,
        remote_id="test-model",
        context_window=1_000_000,
    )


def _completed(*parts: TextPart | ToolCallPart, finish_reason: FinishReason = FinishReason.STOP) -> GenerationCompleted:
    return GenerationCompleted(
        ProviderResponse(
            message=Message("assistant", parts),
            usage=Usage(input_tokens=1, output_tokens=1),
            finish_reason=finish_reason,
        )
    )


class _ScriptedProvider:
    identity = ProviderIdentity("fake", "script", "test-model")

    def __init__(self, scripts: Iterable[Iterable[ProviderEvent]]) -> None:
        self._scripts = tuple(tuple(script) for script in scripts)
        self.requests: list[GenerationRequest] = []

    def resolve_model_limits(self, _model: str) -> ModelLimits:
        return TEST_LIMITS

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


class _EchoTool:
    definition = ToolDefinition(
        "Echo",
        "Echo one value.",
        {
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
            "additionalProperties": False,
        },
    )

    def __init__(self) -> None:
        self.arguments: list[dict[str, object]] = []

    async def execute(self, arguments, *, cancellation) -> ToolExecutionResult:  # type: ignore[no-untyped-def]
        cancellation.raise_if_cancelled()
        self.arguments.append(dict(arguments))
        return ToolExecutionResult(str(arguments["value"]))


@pytest.mark.asyncio
async def test_application_tools_are_exposed_and_execute_only_inside_a_turn(tmp_path) -> None:  # type: ignore[no-untyped-def]
    tool = _EchoTool()
    provider = _ScriptedProvider(
        (
            (_completed(ToolCallPart("echo-1", "Echo", {"value": "hello"}), finish_reason=FinishReason.TOOL_CALLS),),
            (_completed(TextPart("done")),),
        )
    )
    application = create_application(
        _configuration(),
        provider_builder=lambda _provider, _model: provider,
        runtime_context=ApplicationRuntimeContext.from_system(workdir=tmp_path),
        storage_root=tmp_path / "sessions",
        tools=(tool,),
    )

    run = application.create_run()
    run.set_permission_mode(PermissionMode.FULL_ACCESS)
    result = await run.start_turn("echo hello").result()

    assert result.final_text == "done"
    assert tool.arguments == [{"value": "hello"}]
    assert [definition.name for definition in application.tool_definitions()] == [
        "Echo",
        "ToolResultRead",
        "HistoryRead",
    ]
    assert [definition.name for definition in provider.requests[0].tools][:1] == ["Echo"]


@pytest.mark.parametrize("assignment", ("API_KEY", "AUTH_TOKEN", "CLIENT_SECRET"))
def test_application_tool_summary_redacts_sensitive_assignments(tmp_path, assignment: str) -> None:  # type: ignore[no-untyped-def]
    secret = "application-secret-918273"
    summary = ApplicationToolService(
        create_default_tools(tmp_path),
        workdir=tmp_path,
    ).describe_tool_call(
        ToolCallPart("bash", "Bash", {"command": f'$env:{assignment}="{secret}"'})
    )

    assert secret not in summary
    assert "<redacted>" in summary


def test_tool_result_redacts_key_and_auth_option_suffixes() -> None:
    service = ApplicationToolService(())
    content = (
        "--token token-value --sshkey ssh-key-value --myauth auth-value "
        "--sshkey_store store-value --keyboard layout-visible"
    )

    materialized = service.materialize_tool_result(
        ToolExecutionOutcome(
            "option-redaction",
            "HistoryRead",
            content,
            False,
            ToolExecutionStatus.SUCCEEDED,
        )
    )

    redacted = materialized.result.content
    assert all(
        secret not in redacted
        for secret in ("token-value", "ssh-key-value", "auth-value", "store-value")
    )
    assert "--keyboard layout-visible" in redacted


def test_read_file_redaction_keeps_line_numbers_and_multiline_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("W05_READ_FILE_SHORT_SECRET", "2")
    service = ApplicationToolService(())
    content = "2\tplain line\n1\tpassword='first\n2\tsecond'\n3\tvisible 2\n"

    materialized = service.materialize_tool_result(
        ToolExecutionOutcome(
            "read-file-redaction",
            "ReadFile",
            content,
            False,
            ToolExecutionStatus.SUCCEEDED,
        )
    )

    redacted = materialized.result.content
    assert redacted.startswith("2\t")
    assert "\n1\t" in redacted
    assert "first" not in redacted
    assert "second" not in redacted
    assert "\n3\tvisible <redacted>\n" in redacted


@pytest.mark.parametrize("source", ("literal", "environment"))
def test_read_file_redacts_multiline_configured_secrets_and_keeps_line_numbers(
    monkeypatch: pytest.MonkeyPatch,
    source: str,
) -> None:
    secret = "synthetic-alpha\nsynthetic-beta"
    options: dict[str, object] = {}
    if source == "literal":
        options["secret_values"] = (SecretValue(secret),)
    else:
        monkeypatch.setenv("W05_MULTILINE_READ_SECRET", secret)
        options["secret_env_names"] = ("W05_MULTILINE_READ_SECRET",)
    service = ApplicationToolService((), **options)  # type: ignore[arg-type]
    outcome = ToolExecutionOutcome(
        "read-file-multiline-secret",
        "ReadFile",
        "7\tbefore\n8\tsynthetic-alpha\n9\tsynthetic-beta\n10\tafter",
        False,
        ToolExecutionStatus.SUCCEEDED,
        details={"excerpt": secret, "line_count": 4},
    )

    materialized = service.materialize_tool_result(outcome)
    redacted = str(materialized.result.content)

    assert redacted == "7\tbefore\n8\t<redacted>\n9\t\n10\tafter"
    assert "synthetic-alpha" not in redacted
    assert "synthetic-beta" not in redacted
    assert materialized.execution.details == {
        "excerpt": "<redacted>",
        "line_count": 4,
    }
    assert materialized.result.metadata["line_count"] == 4
    assert materialized.result.metadata["persistence_status"] == "inline"


def test_projected_progress_preserves_whitespace_between_reports() -> None:
    service = ApplicationToolService(())
    context = {
        "run_id": "run",
        "turn_id": "turn",
        "iteration": 1,
        "batch_id": "batch",
        "tool_call_id": "call",
        "tool_name": "Tool",
    }

    first = service.project_tool_progress_chunks(
        (CoreToolProgress("copy", "ordinary alpha ", current=1, total=2),),
        **context,
    )
    second = service.project_tool_progress_chunks(
        (CoreToolProgress("copy", "ordinary beta", current=2, total=2),),
        **context,
    )
    flushed = service.project_tool_progress_chunks((), flush=True, **context)

    assert "".join(event.text for event in (*first, *second, *flushed)) == (
        "ordinary alpha ordinary beta"
    )


def test_formal_factory_composes_web_patch_and_git_tools_only_for_configured_search(tmp_path) -> None:  # type: ignore[no-untyped-def]
    enabled = create_default_tools(
        tmp_path,
        attachment_service=object(),
        session_provider=lambda: None,
        search_configuration=SearchConfiguration(enabled=True, api_key="search-secret"),
    )
    enabled_names = [tool.definition.name for tool in enabled]
    assert {"ApplyPatch", "GitWorkspace", "WebFetch", "WebSearch"} <= set(enabled_names)

    disabled = create_default_tools(
        tmp_path,
        attachment_service=object(),
        session_provider=lambda: None,
        search_configuration=SearchConfiguration(enabled=False, api_key="search-secret"),
    )
    assert "WebFetch" in {tool.definition.name for tool in disabled}
    assert "WebSearch" not in {tool.definition.name for tool in disabled}
