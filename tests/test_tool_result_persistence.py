from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from uthcode.application.tools import ApplicationToolService
from uthcode.core.agent import AgentLoop, RunState
from uthcode.core.permission import (
    Decision,
    DecisionReason,
    Effect,
    PermissionAction,
    PermissionDecision,
    PermissionMode,
    ResourceScope,
)
from uthcode.core.provider import (
    CancellationToken,
    FinishReason,
    GenerationCompleted,
    GenerationRequest,
    Message,
    ProviderIdentity,
    ProviderResponse,
    TextPart,
    ToolCallPart,
    ToolDefinition,
    Usage,
)
from uthcode.core.tool import (
    ToolExecutionOutcome,
    ToolExecutionStatus,
    ToolResultPersistenceStatus,
    ToolExecutionResult,
    ToolExecutor,
    ToolPreparation,
    ToolRegistry,
)
from uthcode.integrations.session_files import SessionFileStore
from uthcode.integrations.tools import tool_result_read
from uthcode.integrations.tools.tool_result_read import (
    ToolResultFileStore,
    ToolResultIntegrityError,
    ToolResultPolicy,
    ToolResultPersistenceError,
    ToolResultQuotaExceeded,
    ToolResultReferenceError,
    ToolResultReadTool,
    ToolResultTooLarge,
    format_externalized_preview,
)


def _policy(**overrides: int) -> ToolResultPolicy:
    values = {
        "inline_threshold_bytes": 4,
        "preview_limit_bytes": 8,
        "single_result_hard_cap_bytes": 32,
        "session_quota_bytes": 64,
        "read_page_limit_bytes": 8,
    }
    values.update(overrides)
    return ToolResultPolicy(**values)


def _session(tmp_path: Path, session_id: str = "session-a"):
    store = SessionFileStore(tmp_path)
    store.create_session(session_id, project_key="project")
    writer = store.open_writer(session_id, expected_project_key="project")
    writer.__enter__()
    return store, writer


class _SideEffectTool:
    definition = ToolDefinition(
        "SideEffect",
        "A test Tool whose side effect is counted before materialization.",
        {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    )

    def __init__(self) -> None:
        self.calls = 0

    def preflight(self, arguments):
        del arguments
        return ToolPreparation(
            PermissionAction(
                tool="SideEffect",
                action="write",
                effect=Effect.WRITE,
                resource="session-side-effect",
                scope=ResourceScope.INSIDE,
            ),
            {},
        )

    async def execute(self, arguments, *, cancellation):
        del arguments
        cancellation.raise_if_cancelled()
        self.calls += 1
        return ToolExecutionResult("side effect completed and was not persisted")


class _PersistenceFailureProvider:
    def __init__(self) -> None:
        self.identity = ProviderIdentity("fake", "persistence", "model")
        self.requests: list[GenerationRequest] = []

    async def stream(self, request: GenerationRequest, *, cancellation: CancellationToken):
        self.requests.append(request)
        cancellation.raise_if_cancelled()
        if len(self.requests) == 1:
            yield GenerationCompleted(
                ProviderResponse(
                    Message(
                        "assistant",
                        (ToolCallPart("side-call", "SideEffect", {}),),
                    ),
                    finish_reason=FinishReason.TOOL_CALLS,
                    usage=Usage(),
                )
            )
            return
        yield GenerationCompleted(
            ProviderResponse(
                Message("assistant", (TextPart("finished"),)),
                finish_reason=FinishReason.STOP,
                usage=Usage(),
            )
        )


def test_externalization_preserves_full_bytes_and_returns_bounded_pages(tmp_path: Path) -> None:
    store, writer = _session(tmp_path)
    try:
        policy = _policy()
        content = "0123456789abcdefghij"
        reference = writer.persist_tool_result(content, policy=policy)

        assert reference.size_bytes == len(content.encode("utf-8"))
        assert reference.sha256 == hashlib.sha256(content.encode("utf-8")).hexdigest()
        assert reference.ref not in {".", ".."}
        assert "/" not in reference.ref and "\\" not in reference.ref
        page = writer.read_tool_result(reference.ref, offset=3, limit=8, policy=policy)
        assert page.content == content[3:11]
        assert page.next_offset == 11
        assert page.eof is False
        assert page.sha256 == reference.sha256

        preview = format_externalized_preview(
            content,
            reference,
            preview_limit_bytes=policy.preview_limit_bytes,
        )
        assert content not in preview
        assert content[: policy.preview_limit_bytes] in preview
        assert reference.ref in preview
        assert str(reference.size_bytes) in preview
    finally:
        writer.close()


def test_application_keeps_small_results_inline_without_a_session_write() -> None:
    service = ApplicationToolService(
        (),
        session_provider=lambda: (_ for _ in ()).throw(AssertionError("must not persist inline")),
        tool_result_policy=_policy(inline_threshold_bytes=8),
    )
    outcome = ToolExecutionOutcome(
        "inline-call",
        "SmallTool",
        "small",
        False,
        ToolExecutionStatus.SUCCEEDED,
    )

    materialized = service.materialize_tool_result(outcome)

    assert materialized.persistence_status is ToolResultPersistenceStatus.INLINE
    assert materialized.reference is None
    assert materialized.result.content == "small"
    assert materialized.result.is_error is False


def test_hard_cap_and_session_quota_reject_before_creating_a_ref(tmp_path: Path) -> None:
    store, writer = _session(tmp_path)
    try:
        policy = _policy(single_result_hard_cap_bytes=10, session_quota_bytes=15)
        with pytest.raises(ToolResultTooLarge):
            writer.persist_tool_result("x" * 11, policy=policy)
        assert not tuple((tmp_path / "session-a" / "tool-results").iterdir())

        writer.persist_tool_result("x" * 10, policy=policy)
        with pytest.raises(ToolResultQuotaExceeded):
            writer.persist_tool_result("y" * 10, policy=policy)
        result_dirs = tuple(
            path
            for path in (tmp_path / "session-a" / "tool-results").iterdir()
            if path.is_dir()
        )
        assert len(result_dirs) == 1
        assert not any(path.name.startswith(".") for path in (tmp_path / "session-a" / "tool-results").iterdir())
    finally:
        writer.close()


def test_partial_write_failure_leaves_no_temp_or_dangling_ref(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, writer = _session(tmp_path)
    try:
        def fail_metadata(*_args, **_kwargs):
            raise OSError("simulated metadata failure")

        monkeypatch.setattr(tool_result_read, "_atomic_json", fail_metadata)
        with pytest.raises(ToolResultPersistenceError, match="persist"):
            writer.persist_tool_result("durable content", policy=_policy())
        assert not tuple((tmp_path / "session-a" / "tool-results").iterdir())
    finally:
        writer.close()


def test_ref_isolation_and_integrity_checks_fail_closed(tmp_path: Path) -> None:
    store = SessionFileStore(tmp_path)
    store.create_session("session-a", project_key="project")
    store.create_session("session-b", project_key="project")
    result_store = ToolResultFileStore(store)
    reference = result_store.persist("session-a", "secret result", policy=_policy())

    with pytest.raises(ToolResultReferenceError):
        result_store.read_page("session-b", reference.ref, policy=_policy())
    with pytest.raises(ToolResultReferenceError):
        result_store.read_page("session-a", "..\\metadata.json", policy=_policy())
    with pytest.raises(ToolResultReferenceError):
        result_store.read_page("session-a", reference.ref, limit=9, policy=_policy())
    with pytest.raises(ToolResultReferenceError):
        result_store.read_page("session-a", reference.ref, offset=10_000, policy=_policy())

    content_path = (
        tmp_path / "session-a" / "tool-results" / reference.ref / "content.bin"
    )
    content_path.write_bytes(b"tampered")
    with pytest.raises(ToolResultIntegrityError):
        result_store.read_page("session-a", reference.ref, policy=_policy())


def test_application_materialization_separates_execution_and_persistence_facts(
    tmp_path: Path,
) -> None:
    _store, writer = _session(tmp_path)
    try:
        policy = _policy(
            inline_threshold_bytes=4,
            preview_limit_bytes=4,
            single_result_hard_cap_bytes=64,
            session_quota_bytes=64,
        )
        service = ApplicationToolService(
            (),
            session_provider=lambda: type("ActiveSession", (), {
                "session_id": "session-a",
                "persist_tool_result": writer.persist_tool_result,
                "read_tool_result": writer.read_tool_result,
            })(),
            tool_result_policy=policy,
        )
        outcome = ToolExecutionOutcome(
            "call-1",
            "BigTool",
            "abcdefghij",
            False,
            ToolExecutionStatus.SUCCEEDED,
        )
        materialized = service.materialize_tool_result(outcome)
        assert materialized.persistence_status is ToolResultPersistenceStatus.EXTERNALIZED
        assert materialized.result.is_error is False
        assert materialized.result.content != outcome.content
        assert materialized.result.metadata["execution_status"] == "succeeded"
        assert materialized.result.metadata["persistence_status"] == "externalized"
        assert materialized.reference is not None
        page = writer.read_tool_result(materialized.reference, limit=4, policy=policy)
        assert page.content == "abcd"
    finally:
        writer.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("content", ["abcdefghi", "A😀B中C😀D"])
async def test_tool_result_read_returns_bounded_page_metadata_and_utf8_continuation(
    tmp_path,
    content: str,
) -> None:
    _store, writer = _session(tmp_path)
    policy = _policy(read_page_limit_bytes=512, read_output_limit_bytes=512)
    session = type("ActiveSession", (), {"session_id": "session-a"})()
    reference = writer.persist_tool_result(content, policy=policy)
    reader = ToolResultReadTool(
        lambda session_id, ref, offset, limit: writer.read_tool_result(
            ref,
            offset=offset,
            limit=limit,
            policy=policy,
        ),
        lambda: session,
        policy=policy,
    )

    try:
        offset = 0
        pages: list[dict[str, object]] = []
        while True:
            result = await reader.execute(
                {"ref": reference.ref, "offset": offset, "limit": 4},
                cancellation=CancellationToken(),
            )
            page = json.loads(result.content)
            pages.append(page)
            assert len(result.content.encode("utf-8")) <= policy.effective_read_output_limit
            assert set(page) >= {
                "ref",
                "offset",
                "next_offset",
                "total_bytes",
                "eof",
                "content",
            }
            assert page["ref"] == reference.ref
            assert page["total_bytes"] == len(content.encode("utf-8"))
            assert page["next_offset"] >= page["offset"]
            if page["eof"]:
                assert page["next_offset"] == page["total_bytes"]
                break
            offset = int(page["next_offset"])

        assert "".join(str(page["content"]) for page in pages) == content
        assert pages[-1]["eof"] is True
    finally:
        writer.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content",
    [
        "\x00" * 300,
        '"' * 200,
        "\\" * 200,
        "ordinary-ascii-" * 25,
        "汉😀" * 80,
    ],
)
async def test_tool_result_read_bounds_final_json_after_escape_expansion(
    tmp_path,
    content: str,
) -> None:
    _store, writer = _session(tmp_path)
    policy = _policy(
        read_page_limit_bytes=512,
        read_output_limit_bytes=256,
        single_result_hard_cap_bytes=4096,
        session_quota_bytes=8192,
    )
    session = type("ActiveSession", (), {"session_id": "session-a"})()
    reference = writer.persist_tool_result(content, policy=policy)
    reader = ToolResultReadTool(
        lambda session_id, ref, offset, limit: writer.read_tool_result(
            ref,
            offset=offset,
            limit=limit,
            policy=policy,
        ),
        lambda: session,
        policy=policy,
    )

    try:
        offset = 0
        recovered = bytearray()
        final_page: dict[str, object] | None = None
        while True:
            result = await reader.execute(
                {"ref": reference.ref, "offset": offset, "limit": 64},
                cancellation=CancellationToken(),
            )
            assert result.is_error is False
            assert len(result.content.encode("utf-8")) <= policy.effective_read_output_limit
            page = json.loads(result.content)
            final_page = page
            recovered.extend(str(page["content"]).encode("utf-8"))
            if page["eof"]:
                assert page["next_offset"] == page["total_bytes"]
                break
            assert page["content"] != ""
            assert page["next_offset"] > page["offset"]
            offset = int(page["next_offset"])

        assert final_page is not None
        assert bytes(recovered) == content.encode("utf-8")
    finally:
        writer.close()


@pytest.mark.asyncio
async def test_tool_result_read_reports_controlled_error_when_envelope_cannot_fit(
    tmp_path,
) -> None:
    _store, writer = _session(tmp_path)
    policy = _policy(
        read_page_limit_bytes=512,
        read_output_limit_bytes=128,
        single_result_hard_cap_bytes=64,
        session_quota_bytes=128,
    )
    session = type("ActiveSession", (), {"session_id": "session-a"})()
    reference = writer.persist_tool_result("x", policy=policy)
    reader = ToolResultReadTool(
        lambda session_id, ref, offset, limit: writer.read_tool_result(
            ref,
            offset=offset,
            limit=limit,
            policy=policy,
        ),
        lambda: session,
        policy=policy,
    )

    try:
        result = await reader.execute(
            {"ref": reference.ref, "offset": 0, "limit": 64},
            cancellation=CancellationToken(),
        )
        assert result.is_error is True
        assert "tool_result_output_limit_exceeded" in result.content
    finally:
        writer.close()


def test_persistence_failure_keeps_successful_execution_and_never_requests_retry() -> None:
    policy = _policy(
        inline_threshold_bytes=4,
        preview_limit_bytes=4,
        single_result_hard_cap_bytes=64,
        session_quota_bytes=64,
    )

    class ActiveSession:
        session_id = "session-a"

        def persist_tool_result(self, _content: str, *, policy: object):
            del policy
            raise ToolResultQuotaExceeded("quota reached")

    service = ApplicationToolService(
        (),
        session_provider=lambda: ActiveSession(),
        tool_result_policy=policy,
    )
    outcome = ToolExecutionOutcome(
        "call-2",
        "WriteTool",
        "side effect completed",
        False,
        ToolExecutionStatus.SUCCEEDED,
    )

    materialized = service.materialize_tool_result(outcome)

    assert materialized.execution.status is ToolExecutionStatus.SUCCEEDED
    assert materialized.persistence_status is ToolResultPersistenceStatus.FAILED
    assert materialized.result.is_error is False
    assert materialized.result.metadata["execution_status"] == "succeeded"
    assert materialized.result.metadata["persistence_status"] == "failed"
    assert "already ran" in materialized.result.content
    assert "retried" in materialized.result.content


def test_persistence_failure_preserves_failed_execution_error_truth() -> None:
    policy = _policy(
        inline_threshold_bytes=4,
        preview_limit_bytes=4,
        single_result_hard_cap_bytes=64,
        session_quota_bytes=64,
    )

    class ActiveSession:
        session_id = "session-a"

        def persist_tool_result(self, _content: str, *, policy: object):
            del policy
            raise ToolResultPersistenceError("disk unavailable")

    service = ApplicationToolService(
        (),
        session_provider=lambda: ActiveSession(),
        tool_result_policy=policy,
    )
    outcome = ToolExecutionOutcome(
        "call-failed",
        "FailedTool",
        "the Tool returned an error",
        True,
        ToolExecutionStatus.FAILED,
    )

    materialized = service.materialize_tool_result(outcome)

    assert materialized.result.is_error is True
    assert materialized.result.metadata["execution_status"] == "failed"
    assert materialized.result.metadata["persistence_status"] == "failed"


@pytest.mark.asyncio
async def test_agent_loop_does_not_retry_a_tool_after_materialization_failure() -> None:
    policy = _policy(
        inline_threshold_bytes=4,
        preview_limit_bytes=4,
        single_result_hard_cap_bytes=64,
        session_quota_bytes=64,
    )

    class ActiveSession:
        session_id = "session-a"

        def persist_tool_result(self, _content: str, *, policy: object):
            del policy
            raise ToolResultQuotaExceeded("quota reached")

    tool = _SideEffectTool()
    service = ApplicationToolService(
        (),
        session_provider=lambda: ActiveSession(),
        tool_result_policy=policy,
    )
    provider = _PersistenceFailureProvider()
    registry = ToolRegistry((tool,))
    action = PermissionAction(
        tool="SideEffect",
        action="write",
        effect=Effect.WRITE,
        resource="session-side-effect",
        scope=ResourceScope.INSIDE,
    )
    decision = PermissionDecision(
        Decision.ALLOW,
        DecisionReason.MODE_FALLBACK,
        action,
        PermissionMode.FULL_ACCESS,
        guard_allowed=True,
    )
    loop = AgentLoop(
        provider,
        registry,
        ToolExecutor(registry),
        lambda messages, tools, _runtime: GenerationRequest(
            messages=messages,
            tools=tools,
        ),
        permission_resolver=lambda _action: decision,
        result_materializer=service.materialize_tool_result,
    )

    execution = loop.start_turn(
        RunState.initial("persistence-run"),
        "perform side effect",
    )
    segment = await execution.run_segment(pause_signal=CancellationToken())

    assert segment.result is not None and segment.result.final_text == "finished"
    assert tool.calls == 1
    assert len(provider.requests) == 2
    tool_result = provider.requests[1].messages[-1].parts[0]
    assert tool_result.metadata["execution_status"] == "succeeded"
    assert tool_result.metadata["persistence_status"] == "failed"
    assert "will not be retried" in tool_result.content
