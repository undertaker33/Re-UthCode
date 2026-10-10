from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import pytest

from uthcode.application import ApplicationSessionService, SessionOperationError, UthCodeApplication
from uthcode.application.tools import ApplicationToolService
from uthcode.core.agent import AgentLoop, RunState
from uthcode.core.agent_events import ToolFinished, agent_event_from_dict
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
    ImagePart,
    FilePart,
    Message,
    ModelLimits,
    ProviderIdentity,
    ProviderResponse,
    SourcePart,
    TextPart,
    ToolCallPart,
    ToolDefinition,
    ToolResultPart,
    Usage,
)
from uthcode.core.tool import (
    ToolExecutionOutcome,
    ToolExecutionStatus,
    ToolResultPersistenceStatus,
    ToolExecutionResult,
    ToolExecutor,
    ToolFailure,
    ToolFailureKind,
    ToolPreparation,
    ToolRegistry,
    ToolSideEffect,
    ToolProgress as CoreToolProgress,
)
from uthcode.core.secrets import SecretValue
from uthcode.integrations.session_files import SessionFileStore, SessionNotFoundError
from uthcode.integrations.providers.fake import FakeProvider
from uthcode.integrations.tools import tool_result_read
from uthcode.integrations.tools.tool_result_read import (
    ToolResultFileStore,
    ToolResultIntegrityError,
    ToolResultPolicy,
    ToolResultPersistenceError,
    ToolResultQuotaExceeded,
    ToolResultReferenceError,
    ToolResultReadTool,
    ToolResultError,
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


class _ObservedOutputTool:
    definition = ToolDefinition(
        "ObservedOutput",
        "A test read Tool with a safely externalized result.",
        {"type": "object", "properties": {}, "additionalProperties": False},
    )

    def preflight(self, arguments):
        del arguments
        return ToolPreparation(
            PermissionAction(
                tool="ObservedOutput",
                action="read",
                effect=Effect.READ,
                resource="observed-output",
                scope=ResourceScope.INSIDE,
            ),
            {},
        )

    async def execute(self, arguments, *, cancellation):
        del arguments
        cancellation.report_progress(
            CoreToolProgress("reading", "PROGRESS-ONLY-OBSERVATION", current=1, total=1)
        )
        await asyncio.sleep(0.01)
        return ToolExecutionResult("persisted output content that exceeds the inline threshold")


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
    assert materialized.result.metadata["persistence_status"] == "inline"
    assert materialized.result.metadata["size_bytes"] == 5


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
        application_page = service.read_tool_result_page(
            "session-a",
            materialized.reference,
            offset=0,
            limit=4,
        )
        assert application_page.content == "abcd"
        assert application_page.ref == materialized.reference
        with pytest.raises(ToolResultError):
            service.read_tool_result_page(
                "different-session",
                materialized.reference,
            )
        with pytest.raises(ToolResultReferenceError):
            service.read_tool_result_page(
                "session-a",
                materialized.reference,
                limit=policy.read_page_limit_bytes + 1,
            )
    finally:
        writer.close()


@pytest.mark.asyncio
async def test_application_commits_observed_tool_times_and_keeps_progress_live_only(
    tmp_path: Path,
) -> None:
    session_service = ApplicationSessionService(
        storage_root=tmp_path / "sessions",
        project_key="project",
        instruction_loader=None,
    )
    policy = _policy(
        inline_threshold_bytes=4,
        preview_limit_bytes=4,
        single_result_hard_cap_bytes=256,
        session_quota_bytes=512,
        read_page_limit_bytes=32,
        read_output_limit_bytes=32,
    )
    tool_service = ApplicationToolService(
        (_ObservedOutputTool(),),
        session_provider=lambda: session_service.active_session,
        tool_result_policy=policy,
    )
    class ObservedOutputProvider:
        identity = ProviderIdentity("fake", "observed", "observed-output")

        def __init__(self) -> None:
            self.requests: list[GenerationRequest] = []

        async def stream(
            self,
            request: GenerationRequest,
            *,
            cancellation: CancellationToken,
        ):
            cancellation.raise_if_cancelled()
            self.requests.append(request)
            if len(self.requests) == 1:
                yield GenerationCompleted(
                    ProviderResponse(
                        Message(
                            "assistant",
                            (ToolCallPart("observed-call", "ObservedOutput", {}),),
                        ),
                        finish_reason=FinishReason.TOOL_CALLS,
                        usage=Usage(),
                    )
                )
            else:
                yield GenerationCompleted(
                    ProviderResponse(
                        Message("assistant", (TextPart("finished"),)),
                        finish_reason=FinishReason.STOP,
                        usage=Usage(),
                    )
                )

    provider = ObservedOutputProvider()
    application = UthCodeApplication(
        provider,
        session_service=session_service,
        tool_service=tool_service,
    )
    try:
        session = application.create_session("session-tool-observation")
        handle = application.create_run().start_turn("inspect")
        events = [event async for event in handle.events()]
        result = await handle.result()

        assert result.status.value == "completed", (
            result,
            [(event.type, event.to_dict()) for event in events],
        )
        progress = next(event for event in events if event.type == "tool_progress")
        assert progress.stage == "reading"  # type: ignore[attr-defined]
        assert progress.text == "PROGRESS-ONLY-OBSERVATION"  # type: ignore[attr-defined]
        page = application.session_history_page(session.session_id)
        tool_record = next(record for record in page.records if record.kind == "tool")
        assert tool_record.started_at is not None
        assert tool_record.completed_at is not None
        assert tool_record.started_at < tool_record.completed_at
        assert tool_record.output_ref is not None

        persisted = session_service.read_session(session.session_id)
        transcript_json = persisted.transcript.to_jsonl()
        assert "PROGRESS-ONLY-OBSERVATION" not in transcript_json
        assert "tool_progress" not in transcript_json
        assert "PROGRESS-ONLY-OBSERVATION" not in repr(provider.requests)
        tool_result = next(
            part
            for entry in persisted.transcript.entries
            for part in (
                (ToolResultPart.from_dict(entry.payload["part"]),)
                if entry.kind.value == "tool_result"
                else ()
            )
            if isinstance(part, ToolResultPart)
        )
        assert tool_result.metadata["observed_started_at"] == tool_record.started_at
        assert tool_result.metadata["observed_completed_at"] == tool_record.completed_at

        read_page = application.read_tool_result_page(
            session.session_id,
            tool_record.output_ref,
            limit=16,
        )
        assert read_page.ref == tool_record.output_ref
        assert read_page.offset == 0
        assert read_page.content
        with pytest.raises(SessionOperationError):
            application.read_tool_result_page("another-session", tool_record.output_ref)
    finally:
        application.close()


@pytest.mark.asyncio
async def test_inline_tool_output_is_redacted_bounded_and_session_owned(
    tmp_path: Path,
) -> None:
    secret = "inline-output-secret-92017"

    class InlineOutputTool(_ObservedOutputTool):
        definition = ToolDefinition(
            "InlineOutput",
            "A test read Tool returning a short result.",
            {"type": "object", "properties": {}, "additionalProperties": False},
        )

        async def execute(self, arguments, *, cancellation):
            del arguments, cancellation
            return ToolExecutionResult(f"echo result: {secret}")

    class LongInlineOutputTool(_ObservedOutputTool):
        definition = ToolDefinition(
            "LongInlineOutput",
            "A test read Tool returning a bounded inline preview.",
            {"type": "object", "properties": {}, "additionalProperties": False},
        )

        async def execute(self, arguments, *, cancellation):
            del arguments, cancellation
            return ToolExecutionResult("x" * 1500)

    class InlineOutputProvider:
        identity = ProviderIdentity("fake", "inline-output", "inline-output")

        def __init__(self) -> None:
            self.requests: list[GenerationRequest] = []

        async def stream(self, request, *, cancellation):
            cancellation.raise_if_cancelled()
            self.requests.append(request)
            if len(self.requests) == 1:
                yield GenerationCompleted(
                    ProviderResponse(
                        Message(
                            "assistant",
                            (
                                ToolCallPart("inline-secret-call", "InlineOutput", {}),
                                ToolCallPart("inline-long-call", "LongInlineOutput", {}),
                            ),
                        ),
                        finish_reason=FinishReason.TOOL_CALLS,
                        usage=Usage(),
                    )
                )
            else:
                yield GenerationCompleted(
                    ProviderResponse(
                        Message("assistant", (TextPart("finished"),)),
                        finish_reason=FinishReason.STOP,
                        usage=Usage(),
                    )
                )

    session_service = ApplicationSessionService(
        storage_root=tmp_path / "sessions",
        project_key="registered-project",
        instruction_loader=None,
    )
    tool_service = ApplicationToolService(
        (InlineOutputTool(), LongInlineOutputTool()),
        secret_values=(SecretValue(secret),),
        session_provider=lambda: session_service.active_session,
        tool_result_policy=_policy(
            inline_threshold_bytes=2048,
            single_result_hard_cap_bytes=4096,
            session_quota_bytes=8192,
        ),
    )
    provider = InlineOutputProvider()
    application = UthCodeApplication(
        provider,
        session_service=session_service,
        tool_service=tool_service,
    )
    try:
        session = application.create_session("session-inline-output")
        handle = application.create_run().start_turn("inspect command output")
        events = [event async for event in handle.events()]
        result = await handle.result()
        assert result.status.value == "completed"

        finished = {
            event.tool_call_id: event
            for event in events
            if isinstance(event, ToolFinished)
        }
        safe_live = finished["inline-secret-call"]
        assert safe_live.output_preview is not None
        assert secret not in safe_live.output_preview
        assert "redact" in safe_live.output_preview.lower()
        assert safe_live.output_preview_truncated is False
        decoded_live = agent_event_from_dict(safe_live.to_dict())
        assert isinstance(decoded_live, ToolFinished)
        assert decoded_live.output_preview == safe_live.output_preview
        long_live = finished["inline-long-call"]
        assert long_live.output_preview is not None
        assert len(long_live.output_preview) == 1024
        assert long_live.output_preview_truncated is True

        page = application.session_history_page(session.session_id)
        tools = {record.tool_call_id: record for record in page.records if record.kind == "tool"}
        safe_replay = tools["inline-secret-call"]
        assert safe_replay.output_preview == safe_live.output_preview
        assert safe_replay.output_ref is None
        long_replay = tools["inline-long-call"]
        assert long_replay.output_preview == long_live.output_preview
        assert long_replay.output_preview_truncated is True
        encoded = json.dumps(page.to_dict(), ensure_ascii=False)
        assert secret not in encoded
        assert "echo result" in encoded
        durable = session_service.read_session(session.session_id).transcript.to_jsonl()
        assert secret not in durable
        assert secret not in repr(provider.requests)

        other_owner = ApplicationSessionService(
            storage_root=tmp_path / "sessions",
            project_key="another-registered-project",
            instruction_loader=None,
        )
        with pytest.raises(SessionNotFoundError):
            other_owner.read_history_page(session.session_id)
        assert secret not in json.dumps(application.session_history_page(session.session_id).to_dict())
    finally:
        application.close()


def test_materialization_externalizes_only_text_and_keeps_reference_order(
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
            session_provider=lambda: type(
                "ActiveSession",
                (),
                {
                    "session_id": "session-a",
                    "persist_tool_result": writer.persist_tool_result,
                    "read_tool_result": writer.read_tool_result,
                },
            )(),
            tool_result_policy=policy,
        )
        content = (
            TextPart("abcdefgh"),
            ImagePart("asset://image", "image/png"),
            FilePart("asset://file", "report.pdf", "application/pdf"),
            SourcePart("asset://file", page=2),
        )
        materialized = service.materialize_tool_result(
            ToolExecutionOutcome(
                "structured-call",
                "BigTool",
                content,
                False,
                ToolExecutionStatus.SUCCEEDED,
            )
        )

        assert materialized.persistence_status is ToolResultPersistenceStatus.EXTERNALIZED
        assert [type(part) for part in materialized.result.content.parts] == [
            TextPart,
            ImagePart,
            FilePart,
            SourcePart,
        ]
        assert materialized.result.content.parts[1:] == content[1:]
        assert materialized.reference is not None
        page = writer.read_tool_result(materialized.reference, limit=8, policy=policy)
        assert page.content == "abcdefgh"
    finally:
        writer.close()


def test_materialization_hard_cap_keeps_structured_references() -> None:
    service = ApplicationToolService(
        (),
        tool_result_policy=_policy(
            inline_threshold_bytes=4,
            preview_limit_bytes=4,
            single_result_hard_cap_bytes=6,
        ),
    )
    content = (
        TextPart("abcdefgh"),
        ImagePart("asset://image", "image/png"),
        FilePart("asset://file", "report.pdf", "application/pdf"),
        SourcePart("asset://file", page=2),
    )

    materialized = service.materialize_tool_result(
        ToolExecutionOutcome(
            "hard-cap-call",
            "BigTool",
            content,
            False,
            ToolExecutionStatus.SUCCEEDED,
        )
    )

    assert materialized.persistence_status is ToolResultPersistenceStatus.FAILED
    assert [type(part) for part in materialized.result.content.parts] == [
        TextPart,
        ImagePart,
        FilePart,
        SourcePart,
    ]
    assert materialized.result.metadata["error_code"] == ToolResultTooLarge.code


def test_materialization_inline_keeps_structured_references() -> None:
    service = ApplicationToolService(
        (),
        tool_result_policy=_policy(
            inline_threshold_bytes=16,
            single_result_hard_cap_bytes=32,
        ),
    )
    content = (
        TextPart("ok"),
        ImagePart("asset://image", "image/png"),
        FilePart("asset://file", "report.pdf", "application/pdf"),
        SourcePart("asset://file", page=2),
    )

    materialized = service.materialize_tool_result(
        ToolExecutionOutcome(
            "inline-structured-call",
            "SmallTool",
            content,
            False,
            ToolExecutionStatus.SUCCEEDED,
        )
    )

    assert materialized.persistence_status is ToolResultPersistenceStatus.INLINE
    assert materialized.result.content.parts == content


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
        (
            TextPart("side effect completed"),
            ImagePart("asset://image", "image/png"),
            FilePart("asset://file", "report.pdf", "application/pdf"),
            SourcePart("asset://file", page=2),
        ),
        False,
        ToolExecutionStatus.SUCCEEDED,
    )

    materialized = service.materialize_tool_result(outcome)

    assert materialized.execution.status is ToolExecutionStatus.SUCCEEDED
    assert materialized.persistence_status is ToolResultPersistenceStatus.FAILED
    assert materialized.result.is_error is False
    assert materialized.result.metadata["execution_status"] == "succeeded"
    assert materialized.result.metadata["persistence_status"] == "failed"
    assert [type(part) for part in materialized.result.content.parts] == [
        TextPart,
        ImagePart,
        FilePart,
        SourcePart,
    ]
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
        ToolFailure(ToolFailureKind.PROCESS_FAILED.value, retryable=True),
        ToolSideEffect.PARTIAL,
        "workspace/output.txt",
        "proc-7",
        "exited",
        17,
        "stderr",
        "cursor-7",
    )

    materialized = service.materialize_tool_result(outcome)

    assert materialized.result.is_error is True
    assert materialized.result.metadata["execution_status"] == "failed"
    assert materialized.result.metadata["persistence_status"] == "failed"
    assert materialized.result.metadata["failure"] == {
        "kind": "process_failed",
        "retryable": True,
    }
    assert materialized.result.metadata["side_effect"] == "partial"
    assert materialized.result.metadata["resource"] == "workspace/output.txt"
    assert materialized.result.metadata["process_id"] == "proc-7"
    assert materialized.result.metadata["process_state"] == "exited"
    assert materialized.result.metadata["exit_code"] == 17
    assert materialized.result.metadata["stream"] == "stderr"
    assert materialized.result.metadata["next_cursor"] == "cursor-7"


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
