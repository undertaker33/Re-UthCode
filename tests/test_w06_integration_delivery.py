from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from uthcode.application import (
    EffectiveConfig,
    GenerationCompleted,
    Message,
    PermissionMode,
    ProviderIdentity,
    ProviderResponse,
    ProviderEvent,
    ToolResultPart,
    ToolCallPart,
    TextPart,
    Usage,
    create_application,
)
from uthcode.application.instructions import (
    InstructionLoader,
    InstructionSourceNotFoundError,
)
from uthcode.application.runtime_context import ApplicationRuntimeContext
from uthcode.application.sessions import ApplicationSession, SessionOperationError
from uthcode.core.context import ContextCompactor
from uthcode.core.history import HistoryKind
from uthcode.core.provider import (
    CancellationToken,
    FinishReason,
    GenerationRequest,
)
from uthcode.integrations.instruction_files import InstructionFileReader
from uthcode.integrations.session_files import (
    ProjectionAppendOutcome,
    SessionFileStore,
    SessionWriter,
)


def _completed(
    text: str = "",
    *parts: object,
    finish_reason: FinishReason = FinishReason.STOP,
) -> GenerationCompleted:
    message_parts = ((TextPart(text),) if text else ()) + tuple(parts)
    return GenerationCompleted(
        ProviderResponse(
            message=Message("assistant", message_parts),
            finish_reason=finish_reason,
            usage=Usage(input_tokens=11, output_tokens=7, total_tokens=18),
        )
    )


def _externalized_ref(request: GenerationRequest) -> str:
    for message in reversed(request.messages):
        if message.role != "tool":
            continue
        for part in reversed(message.parts):
            if isinstance(part, ToolResultPart):
                ref = part.metadata.get("ref")
                if isinstance(ref, str) and ref:
                    return ref
    raise AssertionError("the formal request did not carry an externalized result ref")


class _IntegrationProvider:
    def __init__(self, *, final_text: str = "resumed final") -> None:
        self.identity = ProviderIdentity("fake", "w06", "fake-model")
        self.final_text = final_text
        self.requests: list[GenerationRequest] = []

    async def stream(
        self,
        request: GenerationRequest,
        *,
        cancellation: CancellationToken,
    ) -> AsyncIterator[ProviderEvent]:
        self.requests.append(request)
        cancellation.raise_if_cancelled()
        index = len(self.requests) - 1
        if index == 0:
            event = _completed(
                "",
                ToolCallPart(
                    "read-large",
                    "ReadFile",
                    {"path": "src/large.txt"},
                ),
                finish_reason=FinishReason.TOOL_CALLS,
            )
        elif index == 1:
            event = _completed(
                "",
                ToolCallPart(
                    "read-page",
                    "ToolResultRead",
                    {"ref": _externalized_ref(request), "offset": 0, "limit": 128},
                ),
                finish_reason=FinishReason.TOOL_CALLS,
            )
        else:
            event = _completed(self.final_text)
        yield event


class _TerminalProvider:
    def __init__(self) -> None:
        self.identity = ProviderIdentity("fake", "p0", "fake-model")
        self.requests: list[GenerationRequest] = []

    async def stream(
        self,
        request: GenerationRequest,
        *,
        cancellation: CancellationToken,
    ) -> AsyncIterator[ProviderEvent]:
        self.requests.append(request)
        cancellation.raise_if_cancelled()
        yield _completed(f"answer-{len(self.requests)}")


class _ToolTerminalProvider:
    def __init__(self) -> None:
        self.identity = ProviderIdentity("fake", "p0", "fake-model")
        self.requests: list[GenerationRequest] = []

    async def stream(
        self,
        request: GenerationRequest,
        *,
        cancellation: CancellationToken,
    ) -> AsyncIterator[ProviderEvent]:
        self.requests.append(request)
        cancellation.raise_if_cancelled()
        if len(self.requests) == 1:
            yield _completed(
                "",
                ToolCallPart(
                    "retry-call-1",
                    "ReadFile",
                    {"path": "src/tool.txt"},
                ),
                finish_reason=FinishReason.TOOL_CALLS,
            )
            return
        yield _completed(f"tool-answer-{len(self.requests)}")


def _build_application(
    project: Path,
    sessions: SessionFileStore,
    provider: _IntegrationProvider | _TerminalProvider | _ToolTerminalProvider,
):
    user_root = project.parent / "home" / ".uthcode"
    user_root.mkdir(parents=True, exist_ok=True)
    loader = InstructionLoader(
        user_root=user_root,
        project_root=project,
        reader=InstructionFileReader(),
    )
    config = EffectiveConfig.single_model(
        "fake/ref",
        provider_profile_id="fake",
        remote_id="fake-model",
    )
    return create_application(
        config,
        provider_builder=lambda _profile, _model: provider,
        runtime_context=ApplicationRuntimeContext.from_system(workdir=project),
        instruction_loader=loader,
        session_store=sessions,
    )


def _request_message_dicts(request: GenerationRequest) -> list[dict[str, object]]:
    return [message.to_dict() for message in request.messages if message.role in {"user", "assistant", "tool"}]


def _has_user_text(message: dict[str, object], marker: str) -> bool:
    if message.get("role") != "user":
        return False
    parts = message.get("parts")
    return isinstance(parts, list) and any(
        isinstance(part, dict)
        and part.get("type") == "text"
        and marker in part.get("text", "")
        for part in parts
    )


def _history_message_entries(session: ApplicationSession, turn_id: str):
    return [
        entry
        for entry in session.history.entries
        if entry.turn_id == turn_id
        and entry.kind in {
            HistoryKind.USER_MESSAGE,
            HistoryKind.ASSISTANT_MESSAGE,
        }
    ]


def _history_entries_for_turn(session: ApplicationSession, turn_id: str):
    return [entry for entry in session.history.entries if entry.turn_id == turn_id]


def test_w06_formal_create_fails_closed_on_include_without_partial_parent_prefix(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    sessions = SessionFileStore(tmp_path / "sessions")
    application = _build_application(project, sessions, _TerminalProvider())
    try:
        (project / "AGENTS.md").write_text(
            "parent instruction\n@include(\"missing.md\")\n",
            encoding="utf-8",
        )
        with pytest.raises(InstructionSourceNotFoundError):
            application.create_session("include-create-fails-closed")
        assert application.session_service is not None
        assert application.session_service.active_session is None
        assert application.instruction_loader is not None
        # reset_for_new_session happens before the strict rebuild; a failed
        # include cannot leave the parent AGENTS block active in a new Session.
        assert application.instruction_loader.blocks == ()
        assert not sessions.session_path("include-create-fails-closed").exists()
    finally:
        application.close()


def test_w06_direct_create_failure_preserves_loader_until_successful_commit(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "AGENTS.md").write_text("stable parent\n", encoding="utf-8")
    sessions = SessionFileStore(tmp_path / "sessions")
    application = _build_application(project, sessions, _TerminalProvider())
    loader = application.instruction_loader
    assert loader is not None
    before = (
        loader.blocks,
        loader.instruction_epoch,
        loader.stable_prefix_fingerprint,
        loader.activated_directory_scopes,
    )
    try:
        (project / "AGENTS.md").write_text(
            "parent must not partially commit\n@include(\"missing.md\")\n",
            encoding="utf-8",
        )
        with pytest.raises(InstructionSourceNotFoundError):
            application.create_session("direct-create-fails-closed")
        assert (
            loader.blocks,
            loader.instruction_epoch,
            loader.stable_prefix_fingerprint,
            loader.activated_directory_scopes,
        ) == before
        assert not sessions.session_path("direct-create-fails-closed").exists()

        (project / "AGENTS.md").write_text("committed parent\n", encoding="utf-8")
        session = application.create_session("direct-create-succeeds")
        assert session.session_id == "direct-create-succeeds"
        assert any(block.content == "committed parent\n" for block in loader.blocks)
        session.close()
    finally:
        application.close()


def test_w06_formal_resume_and_refresh_fail_closed_without_adopting_partial_include(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "AGENTS.md").write_text("stable parent\n", encoding="utf-8")
    sessions = SessionFileStore(tmp_path / "sessions")

    first = _build_application(project, sessions, _TerminalProvider())
    first.create_session("include-resume-fails-closed").close()
    first.close()

    second = _build_application(project, sessions, _TerminalProvider())
    try:
        (project / "AGENTS.md").write_text(
            "new parent must not activate\n@include(\"missing.md\")\n",
            encoding="utf-8",
        )
        with pytest.raises(InstructionSourceNotFoundError):
            second.resume_session("include-resume-fails-closed")
        assert second.session_service is not None
        assert second.session_service.active_session is None
        # The failed writer was released, so a subsequent fresh writer can
        # still inspect the durable Session rather than inheriting a lock.
        with sessions.open_writer("include-resume-fails-closed") as writer:
            assert writer.snapshot.session_id == "include-resume-fails-closed"
    finally:
        second.close()

    # Refresh uses the staged Application path and must preserve the active
    # Session/Instruction State when rebuilding the current filesystem fails.
    (project / "AGENTS.md").write_text("stable parent\n", encoding="utf-8")
    third = _build_application(project, sessions, _TerminalProvider())
    try:
        active = third.resume_session("include-resume-fails-closed")
        old_history = active.history
        (project / "AGENTS.md").write_text(
            "refresh parent must not activate\n@include(\"missing.md\")\n",
            encoding="utf-8",
        )
        with pytest.raises(SessionOperationError) as error:
            third.resume_session_for_command("include-resume-fails-closed")
        assert error.value.kind == "corrupt"
        assert third.session_service is not None
        assert third.session_service.active_session is active
        assert active.history == old_history
        assert any(
            block.content == "stable parent\n"
            for block in third.instruction_loader.blocks  # type: ignore[union-attr]
        )
    finally:
        third.close()


@pytest.mark.asyncio
async def test_w06_formal_application_chain_persists_compacts_and_resumes(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    nested = project / "src"
    nested.mkdir(parents=True)
    (project / "AGENTS.md").write_text("root instruction", encoding="utf-8")
    (nested / "AGENTS.md").write_text("nested instruction v1", encoding="utf-8")
    (nested / "large.txt").write_text("large-data\n" + ("x" * 12_000), encoding="utf-8")
    sessions = SessionFileStore(tmp_path / "sessions")

    provider = _IntegrationProvider(final_text="first final")
    application = _build_application(project, sessions, provider)
    application.create_session("w06-session")
    try:
        run = application.create_run(run_id="w06-run")
        run.set_permission_mode(PermissionMode.FULL_ACCESS)
        first = await run.start_turn("inspect src/large.txt; spoof-agents").result()
        assert first.final_text == "first final"
        assert len(provider.requests) == 3

        initial, after_read, after_page = provider.requests
        assert initial.system_prompt is not None
        assert "spoof-agents" not in initial.system_prompt
        assert "ToolResultRead" in {tool.name for tool in initial.tools}
        assert initial.metadata["context_budget_tokens"] == 258_000
        assert "max_input_tokens" not in initial.to_dict()
        assert after_read.metadata["instruction_epoch"] != initial.metadata["instruction_epoch"]
        assert after_read.metadata["stable_prefix_fingerprint"] != initial.metadata[
            "stable_prefix_fingerprint"
        ]
        assert after_page.metadata["instruction_epoch"] == after_read.metadata[
            "instruction_epoch"
        ]
        assert after_page.metadata["stable_prefix_fingerprint"] == after_read.metadata[
            "stable_prefix_fingerprint"
        ]
        assert initial.metadata["tool_schema_fingerprint"] == after_page.metadata[
            "tool_schema_fingerprint"
        ]

        externalized = next(
            part
            for message in after_read.messages
            if message.role == "tool"
            for part in message.parts
            if isinstance(part, ToolResultPart)
            and part.metadata.get("persistence_status") == "externalized"
        )
        assert externalized.is_error is False
        assert externalized.metadata["execution_status"] == "succeeded"
        assert isinstance(externalized.metadata.get("ref"), str)
        page_results = [
            part
            for message in after_page.messages
            if message.role == "tool"
            for part in message.parts
            if isinstance(part, ToolResultPart)
            and part.tool_call_id == "read-page"
        ]
        assert page_results and "large-data" in page_results[-1].content

        active = application.session_service.active_session  # type: ignore[union-attr]
        assert active is not None
        assert active.history.entries
        assert application.diagnostics()["history_persistence"]["status"] == "committed"
        assert application.session_catalog()[0].session_id == "w06-session"

        application.context_service._compactor = ContextCompactor(
            input_budget=10,
            output_reserve=1,
            summary_hard_cap=2,
            token_estimator=lambda value: len(value),
        )
        overflow = application.compact_session(summarize=lambda _value: "should not commit")
        assert overflow.changed is False
        assert overflow.failure in {
            "single_semantic_unit_exceeds_compaction_budget",
            "compaction_input_overflow",
        }
        assert active.projection is None

        application.context_service._compactor = ContextCompactor()
        compacted = application.compact_session(summarize=lambda _value: "W06_COMPACT_SUMMARY")
        assert compacted.changed is True
        assert compacted.projection is not None
        epoch_before_resume = application.instruction_loader.instruction_epoch  # type: ignore[union-attr]
        fingerprint_before_resume = application.instruction_loader.stable_prefix_fingerprint  # type: ignore[union-attr]

        second = await run.start_turn("continue after the page").result()
        assert second.final_text == "first final"
        assert "continue after the page" in "\n".join(
            part.text
            for part in provider.requests[3].messages[-1].parts
            if isinstance(part, TextPart)
        )
    finally:
        application.close()

    resumed_provider = _IntegrationProvider(final_text="resume final")
    resumed_app = _build_application(project, sessions, resumed_provider)
    try:
        resumed = resumed_app.resume_session("w06-session")
        assert resumed.instruction_state.instruction_epoch == epoch_before_resume
        assert (
            resumed.instruction_state.stable_prefix_fingerprint
            == fingerprint_before_resume
        )
        resumed_run = resumed_app.create_run(run_id="fresh-after-resume")
        assert resumed_run.snapshot().iteration_count == 0
        result = await resumed_run.start_turn("final after resume").result()
        assert result.final_text == "resume final"
        resumed_request = resumed_provider.requests[0]
        assert resumed_request.metadata["projection_revision"] == 1
        assert resumed_request.metadata["instruction_epoch"] == epoch_before_resume
        assert "W06_COMPACT_SUMMARY" in "\n".join(
            part.text
            for message in resumed_request.messages
            for part in message.parts
            if isinstance(part, TextPart)
        )
    finally:
        resumed_app.close()

    (nested / "AGENTS.md").write_text("nested instruction v2", encoding="utf-8")
    changed_app = _build_application(project, sessions, _IntegrationProvider())
    try:
        changed = changed_app.resume_session("w06-session")
        assert changed.instruction_state.instruction_epoch == epoch_before_resume + 1
        assert changed.instruction_state.change_reason == "instruction_content_changed"
    finally:
        changed_app.close()


@pytest.mark.asyncio
async def test_w06_history_append_then_instruction_sync_failure_advances_cursor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    sessions = SessionFileStore(tmp_path / "sessions")
    provider = _TerminalProvider()
    application = _build_application(project, sessions, provider)
    sync_calls = 0
    original_sync = ApplicationSession.persist_instruction_state

    def fail_first_instruction_sync(self: ApplicationSession):
        nonlocal sync_calls
        sync_calls += 1
        if sync_calls == 1:
            raise RuntimeError("injected instruction state sync failure")
        return original_sync(self)

    monkeypatch.setattr(
        ApplicationSession,
        "persist_instruction_state",
        fail_first_instruction_sync,
    )
    try:
        session = application.create_session("p0-sync-failure")
        run = application.create_run(run_id="p0-sync-run")
        first = await run.start_turn("P0_FIRST").result()

        diagnostics = application.diagnostics()["history_persistence"]
        assert first.final_text == "answer-1"
        assert diagnostics["status"] == "partial"
        assert diagnostics["history_appended"] is True
        assert diagnostics["instruction_state_synced"] is False
        assert diagnostics["failure_stage"] == "instruction_state_sync"
        assert diagnostics["error_code"] == "instruction_state_sync_failed"
        assert diagnostics["persisted_message_count"] == 2
        assert run._persisted_message_count == 2

        first_entries = _history_message_entries(session, first.turn_id)
        assert [entry.kind for entry in first_entries] == [
            HistoryKind.USER_MESSAGE,
            HistoryKind.ASSISTANT_MESSAGE,
        ]
        first_identity = [entry.payload["message"] for entry in first_entries]

        second = await run.start_turn("P0_SECOND").result()
        second_request = provider.requests[1]
        request_messages = _request_message_dicts(second_request)
        assert request_messages.count(first_identity[0]) == 1
        assert request_messages.count(first_identity[1]) == 1
        assert sum(
            _has_user_text(message, "P0_SECOND")
            for message in request_messages
        ) == 1

        all_entries = session.history.entries
        assert [entry.sequence for entry in all_entries] == list(
            range(1, len(all_entries) + 1)
        )
        assert len(_history_message_entries(session, first.turn_id)) == 2
        assert len(_history_message_entries(session, second.turn_id)) == 2
        assert all(
            entry.kind in {HistoryKind.USER_MESSAGE, HistoryKind.ASSISTANT_MESSAGE}
            for entry in all_entries
        )
        final_diagnostics = application.diagnostics()["history_persistence"]
        assert final_diagnostics["status"] == "committed"
        assert final_diagnostics["history_appended"] is True
        assert final_diagnostics["instruction_state_synced"] is True
        assert final_diagnostics["error_code"] is None
    finally:
        application.close()


@pytest.mark.asyncio
async def test_w06_history_append_touch_failure_is_durable_and_not_retried(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    sessions = SessionFileStore(tmp_path / "sessions")
    provider = _TerminalProvider()
    application = _build_application(project, sessions, provider)
    touch_calls = 0
    original_touch = SessionWriter.touch

    def fail_first_touch(self: SessionWriter):
        nonlocal touch_calls
        touch_calls += 1
        if touch_calls == 1:
            raise OSError("injected post-append metadata touch failure")
        return original_touch(self)

    monkeypatch.setattr(SessionWriter, "touch", fail_first_touch)
    try:
        session = application.create_session("p0-post-append-touch")
        run = application.create_run(run_id="p0-post-append-touch-run")
        first = await run.start_turn("P0_TOUCH_FIRST").result()

        first_diagnostics = application.diagnostics()["history_persistence"]
        assert first.final_text == "answer-1"
        assert first_diagnostics["status"] == "partial"
        assert first_diagnostics["history_appended"] is True
        assert first_diagnostics["history_durability"] == "durable"
        assert first_diagnostics["history_reload_succeeded"] is True
        assert first_diagnostics["history_metadata_synced"] is False
        assert first_diagnostics["instruction_state_synced"] is True
        assert first_diagnostics["failure_stage"] == "history_metadata_sync"
        assert first_diagnostics["error_code"] == "history_metadata_sync_failed"
        assert run._persisted_message_count == 2
        assert run._pending_persistence_batches == []

        first_entries = _history_entries_for_turn(session, first.turn_id)
        first_identity = [entry.payload["message"] for entry in first_entries]

        second = await run.start_turn("P0_TOUCH_SECOND").result()
        second_request_messages = _request_message_dicts(provider.requests[1])
        assert second.final_text == "answer-2"
        assert second_request_messages.count(first_identity[0]) == 1
        assert second_request_messages.count(first_identity[1]) == 1

        second_entries = _history_entries_for_turn(session, second.turn_id)
        assert [entry.payload["message"] for entry in first_entries] == [
            message.to_dict() for message in run._state.messages[:2]
        ]
        assert [entry.payload["message"] for entry in second_entries] == [
            message.to_dict() for message in run._state.messages[2:]
        ]
        assert [entry.sequence for entry in session.history.entries] == list(
            range(1, len(session.history.entries) + 1)
        )
        assert len(_history_entries_for_turn(session, first.turn_id)) == 2
        assert len(_history_entries_for_turn(session, second.turn_id)) == 2
    finally:
        application.close()


@pytest.mark.asyncio
async def test_w06_unknown_history_append_durability_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    sessions = SessionFileStore(tmp_path / "sessions")
    provider = _TerminalProvider()
    application = _build_application(project, sessions, provider)
    application.create_session("p0-unknown-durability")
    run = application.create_run(run_id="p0-unknown-durability-run")
    original_reload = SessionWriter._reload
    original_load = SessionFileStore._load_snapshot

    def fail_reload(self: SessionWriter, *, touch: bool):
        raise OSError("injected reload failure")

    def fail_load(self: SessionFileStore, *args: object, **kwargs: object):
        raise OSError("injected reconciliation read failure")

    monkeypatch.setattr(SessionWriter, "_reload", fail_reload)
    monkeypatch.setattr(SessionFileStore, "_load_snapshot", fail_load)
    try:
        await run.start_turn("P0_UNKNOWN").result()

        diagnostics = application.diagnostics()["history_persistence"]
        assert diagnostics["status"] == "failed"
        assert diagnostics["history_appended"] is False
        assert diagnostics["history_durability"] == "unknown"
        assert diagnostics["failure_stage"] == "history_durability_unknown"
        assert run._persisted_message_count == 0
        assert len(run._pending_persistence_batches) == 1
        assert run._pending_persistence_batches[0].blocked is True
        history_path = sessions.session_path("p0-unknown-durability") / "history.jsonl"
        before_new_run = history_path.read_bytes()
        assert len(before_new_run.splitlines()) == 2

        second_run = application.create_run(run_id="p0-unknown-durability-run-2")
        with pytest.raises(RuntimeError, match="durability is unknown"):
            second_run.start_turn("P0_MUST_NOT_RETRY")
        assert len(provider.requests) == 1
        assert history_path.read_bytes() == before_new_run
        assert len(history_path.read_bytes().splitlines()) == 2

        monkeypatch.setattr(SessionWriter, "_reload", original_reload)
        monkeypatch.setattr(SessionFileStore, "_load_snapshot", original_load)
        application.close()

        reopened = application.resume_session("p0-unknown-durability")
        recovered_run = application.create_run(run_id="p0-unknown-durability-run-3")
        recovered = await recovered_run.start_turn("P0_AFTER_REOPEN").result()
        assert recovered.final_text == "answer-2"
        assert len(provider.requests) == 2
        assert len(history_path.read_bytes().splitlines()) == 4
        assert [entry.sequence for entry in reopened.history.entries] == [1, 2, 3, 4]
        assert [entry.turn_id for entry in reopened.history.entries[:2]] == [
            run.snapshot().turn_id,
            run.snapshot().turn_id,
        ]
    finally:
        application.close()


@pytest.mark.asyncio
async def test_w06_unknown_projection_durability_blocks_new_run_until_reopen(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    sessions = SessionFileStore(tmp_path / "sessions")
    provider = _TerminalProvider()
    application = _build_application(project, sessions, provider)
    session = application.create_session("p0-projection-unknown")
    first = await application.create_run(run_id="p0-projection-run-1").start_turn(
        "P0_PROJECTION_FIRST"
    ).result()
    history_path = sessions.session_path("p0-projection-unknown") / "history.jsonl"
    original_reload = SessionWriter._reload
    original_load = SessionFileStore._load_snapshot

    def fail_reload(self: SessionWriter, *, touch: bool):
        raise OSError("injected Projection reload failure")

    def fail_load(self: SessionFileStore, *args: object, **kwargs: object):
        raise OSError("injected Projection reconciliation read failure")

    monkeypatch.setattr(SessionWriter, "_reload", fail_reload)
    monkeypatch.setattr(SessionFileStore, "_load_snapshot", fail_load)
    try:
        failed = application.compact_session(summarize=lambda _value: "P0_PROJECTION_SUMMARY")
        assert first.final_text == "answer-1"
        assert failed.changed is False
        assert failed.failure == "projection_durability_unknown"
        assert session.durability_unknown is True
        before_new_run = history_path.read_bytes()

        second_run = application.create_run(run_id="p0-projection-run-2")
        with pytest.raises(RuntimeError, match="durability is unknown"):
            await second_run.start_turn("P0_PROJECTION_MUST_NOT_RUN").result()
        assert len(provider.requests) == 1
        assert history_path.read_bytes() == before_new_run
    finally:
        monkeypatch.setattr(SessionWriter, "_reload", original_reload)
        monkeypatch.setattr(SessionFileStore, "_load_snapshot", original_load)
        application.close()

    reopened = application.resume_session("p0-projection-unknown")
    try:
        assert reopened.projection is not None
        assert reopened.projection.revision == 1
        recovered = await application.create_run(run_id="p0-projection-run-3").start_turn(
            "P0_PROJECTION_AFTER_REOPEN"
        ).result()
        assert recovered.final_text == "answer-2"
        assert len(provider.requests) == 2
        assert len(history_path.read_bytes().splitlines()) == 5
    finally:
        application.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_mode", ["unknown", "not_durable", "append"])
async def test_w06_compaction_diagnostics_match_projection_persistence_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_mode: str,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    sessions = SessionFileStore(tmp_path / "sessions")
    application = _build_application(project, sessions, _TerminalProvider())
    session = application.create_session(f"p0-compaction-{failure_mode}")
    await application.create_run(run_id=f"p0-compaction-run-{failure_mode}").start_turn(
        "P0_COMPACTION_SEED"
    ).result()

    if failure_mode == "unknown":
        def fail_unknown(self: ApplicationSession, projection: object):
            del projection
            self._quarantine_unknown_durability()
            return ProjectionAppendOutcome(
                snapshot=self.snapshot,
                projection_appended=False,
                reload_succeeded=False,
                metadata_synced=False,
                failure_stage="projection_durability_unknown",
                durability="unknown",
            )

        monkeypatch.setattr(ApplicationSession, "append_projection", fail_unknown)
    elif failure_mode == "not_durable":
        def fail_not_durable(self: ApplicationSession, projection: object):
            del projection
            return ProjectionAppendOutcome(
                snapshot=self.snapshot,
                projection_appended=False,
                reload_succeeded=False,
                metadata_synced=False,
                failure_stage="projection_append",
                durability="not_durable",
            )

        monkeypatch.setattr(ApplicationSession, "append_projection", fail_not_durable)
    else:
        def fail_append(self: ApplicationSession, projection: object):
            del self, projection
            raise OSError("injected Projection append failure")

        monkeypatch.setattr(ApplicationSession, "append_projection", fail_append)

    try:
        result = application.compact_session(summarize=lambda _value: "P0_COMPACTION_SUMMARY")
        expected_failure = (
            "projection_durability_unknown"
            if failure_mode == "unknown"
            else ("projection_append" if failure_mode == "not_durable" else "projection_append_failed")
        )
        assert result.changed is False
        assert result.failure == expected_failure
        last = application.diagnostics()["compaction"]["last"]
        assert isinstance(last, dict)
        assert last["status"] == "failed"
        assert last["changed"] is False
        assert last["failure"] == expected_failure
        assert session.projection is None
    finally:
        application.close()


@pytest.mark.asyncio
async def test_w06_history_append_failure_keeps_cursor_and_retries_unpersisted_messages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    sessions = SessionFileStore(tmp_path / "sessions")
    provider = _TerminalProvider()
    application = _build_application(project, sessions, provider)
    append_calls = 0
    original_append = ApplicationSession.append_history

    def fail_first_history_append(
        self: ApplicationSession,
        entries: object,
    ):
        nonlocal append_calls
        append_calls += 1
        if append_calls == 1:
            raise RuntimeError("injected history append failure")
        return original_append(self, entries)  # type: ignore[arg-type]

    monkeypatch.setattr(ApplicationSession, "append_history", fail_first_history_append)
    try:
        session = application.create_session("p0-history-failure")
        run = application.create_run(run_id="p0-history-run")
        first = await run.start_turn("P0_UNPERSISTED").result()

        diagnostics = application.diagnostics()["history_persistence"]
        assert first.final_text == "answer-1"
        assert diagnostics["status"] == "failed"
        assert diagnostics["history_appended"] is False
        assert diagnostics["instruction_state_synced"] is False
        assert diagnostics["failure_stage"] == "history_append"
        assert diagnostics["error_code"] == "history_persistence_failed"
        assert diagnostics["persisted_message_count"] == 0
        assert run._persisted_message_count == 0
        assert session.history.entries == ()

        first_user = run._state.messages[0].to_dict()

        second = await run.start_turn("P0_RETRY_WITH_SECOND").result()
        second_request_messages = _request_message_dicts(provider.requests[1])
        assert second.final_text == "answer-2"
        assert second_request_messages.count(first_user) == 1
        assert sum(
            _has_user_text(message, "P0_RETRY_WITH_SECOND")
            for message in second_request_messages
        ) == 1
        assert run._persisted_message_count == len(run._state.messages)

        all_entries = session.history.entries
        assert [entry.sequence for entry in all_entries] == list(
            range(1, len(all_entries) + 1)
        )
        assert len(
            [
                entry
                for entry in all_entries
                if entry.kind is HistoryKind.USER_MESSAGE
                and entry.payload["message"]["parts"][0]["text"]
                in ("P0_UNPERSISTED", "P0_RETRY_WITH_SECOND")
            ]
        ) == 2
        first_entries = _history_entries_for_turn(session, first.turn_id)
        second_entries = _history_entries_for_turn(session, second.turn_id)
        assert first.turn_id != second.turn_id
        assert [entry.payload["message"] for entry in first_entries] == [
            message.to_dict() for message in run._state.messages[:2]
        ]
        assert [entry.payload["message"] for entry in second_entries] == [
            message.to_dict() for message in run._state.messages[2:]
        ]
        assert all(entry.turn_id == first.turn_id for entry in first_entries)
        assert all(entry.turn_id == second.turn_id for entry in second_entries)
        final_diagnostics = application.diagnostics()["history_persistence"]
        assert final_diagnostics["status"] == "committed"
        assert final_diagnostics["history_appended"] is True
        assert final_diagnostics["instruction_state_synced"] is True
        assert final_diagnostics["error_code"] is None
    finally:
        application.close()


@pytest.mark.asyncio
async def test_w06_history_append_retry_preserves_turn_and_tool_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    source = project / "src"
    source.mkdir(parents=True)
    (source / "tool.txt").write_text("tool payload", encoding="utf-8")
    sessions = SessionFileStore(tmp_path / "sessions")
    provider = _ToolTerminalProvider()
    application = _build_application(project, sessions, provider)
    append_calls = 0
    original_append = ApplicationSession.append_history

    def fail_first_history_append(
        self: ApplicationSession,
        entries: object,
    ):
        nonlocal append_calls
        append_calls += 1
        if append_calls == 1:
            raise RuntimeError("injected history append failure")
        return original_append(self, entries)  # type: ignore[arg-type]

    monkeypatch.setattr(ApplicationSession, "append_history", fail_first_history_append)
    try:
        session = application.create_session("p0-turn-identity")
        run = application.create_run(run_id="p0-turn-identity-run")
        run.set_permission_mode(PermissionMode.FULL_ACCESS)

        first = await run.start_turn("P0_TOOL_FIRST").result()
        first_message_count = len(run._state.messages)
        first_messages = tuple(run._state.messages[:first_message_count])
        assert any(
            isinstance(part, ToolCallPart)
            for message in first_messages
            for part in message.parts
        )
        assert any(
            isinstance(part, ToolResultPart)
            for message in first_messages
            for part in message.parts
        )
        assert run._persisted_message_count == 0
        assert session.history.entries == ()

        second = await run.start_turn("P0_TOOL_SECOND").result()
        second_messages = tuple(run._state.messages[first_message_count:])
        assert first.turn_id != second.turn_id
        assert run._persisted_message_count == len(run._state.messages)

        first_entries = _history_entries_for_turn(session, first.turn_id)
        second_entries = _history_entries_for_turn(session, second.turn_id)
        assert first_entries and second_entries
        assert all(entry.turn_id == first.turn_id for entry in first_entries)
        assert all(entry.turn_id == second.turn_id for entry in second_entries)
        assert [entry.payload["message"] for entry in first_entries] == [
            message.to_dict() for message in first_messages
        ]
        assert [entry.payload["message"] for entry in second_entries] == [
            message.to_dict() for message in second_messages
        ]

        first_tool_calls = [
            entry for entry in first_entries if entry.kind is HistoryKind.TOOL_CALL
        ]
        first_tool_results = [
            entry for entry in first_entries if entry.kind is HistoryKind.TOOL_RESULT
        ]
        assert [entry.tool_call_id for entry in first_tool_calls] == ["retry-call-1"]
        assert [entry.tool_call_id for entry in first_tool_results] == ["retry-call-1"]
        tool_units = [
            unit
            for unit in session.history.semantic_units()
            if unit.contains_tool_pair
        ]
        assert len(tool_units) == 1
        assert {entry.turn_id for entry in tool_units[0].entries} == {first.turn_id}
        assert [entry.sequence for entry in session.history.entries] == list(
            range(1, len(session.history.entries) + 1)
        )
    finally:
        application.close()
