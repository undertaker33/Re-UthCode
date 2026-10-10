from __future__ import annotations

import asyncio
import base64
from collections.abc import AsyncIterator
from dataclasses import replace
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest

from uthcode.application import (
    AttachmentService,
    ApplicationSessionService,
    SessionHistoryPage,
    SessionReplayRecord,
    UthCodeApplication,
)
from uthcode.core.history import TranscriptKind, transcript_entries_from_message
from uthcode.core.provider import (
    CancellationToken,
    FilePart,
    FinishReason,
    GenerationCompleted,
    GenerationRequest,
    ImagePart,
    Message,
    ModelLimits,
    ProviderEvent,
    ProviderError,
    ProviderIdentity,
    ProviderResponse,
    ReasoningPart,
    ReasoningDelta as ProviderReasoningDelta,
    TextDelta,
    TextPart,
    ToolCallPart,
)
from uthcode.integrations.providers.fake import FakeProvider
from uthcode.integrations.session_files import SessionFileStore
from uthcode.interfaces.desktop.bridge import DesktopBridge
from uthcode.interfaces.desktop.protocol import RequestEnvelope


class _IdentityScriptProvider:
    def __init__(self, scripts: tuple[tuple[ProviderEvent, ...], ...]) -> None:
        self.identity = ProviderIdentity("fake", "identity", "identity-test")
        self.scripts = scripts
        self.requests: list[GenerationRequest] = []

    def resolve_model_limits(self, _model: str) -> ModelLimits:
        return ModelLimits(max_input_tokens=256_000, source="test.history_identity")

    async def stream(
        self,
        request: GenerationRequest,
        *,
        cancellation: CancellationToken,
    ) -> AsyncIterator[ProviderEvent]:
        self.requests.append(request)
        script = self.scripts[min(len(self.requests) - 1, len(self.scripts) - 1)]
        for event in script:
            cancellation.raise_if_cancelled()
            yield event


class _GatedLimitsProvider:
    def __init__(self) -> None:
        self.identity = ProviderIdentity("fake", "gated-limits", "history-gate")
        self.limits_entered = asyncio.Event()
        self.release_limits = asyncio.Event()
        self.stream_entered = asyncio.Event()
        self.release_stream = asyncio.Event()
        self.requests: list[GenerationRequest] = []
        self.gate_limits = False

    async def resolve_model_limits(self, _model: str) -> ModelLimits:
        if self.gate_limits:
            self.limits_entered.set()
            await self.release_limits.wait()
        return ModelLimits(max_input_tokens=256_000, source="test.gated_limits")

    async def stream(
        self,
        request: GenerationRequest,
        *,
        cancellation: CancellationToken,
    ) -> AsyncIterator[ProviderEvent]:
        self.requests.append(request)
        self.stream_entered.set()
        await self.release_stream.wait()
        cancellation.raise_if_cancelled()
        yield _provider_response(TextPart("completed"))


def _provider_response(*parts: object, finish_reason: FinishReason = FinishReason.STOP) -> GenerationCompleted:
    return GenerationCompleted(
        ProviderResponse(
            message=Message("assistant", tuple(parts)),
            finish_reason=finish_reason,
        )
    )


class _HistoryApplication:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None, int]] = []

    def create_run(self) -> object:
        return SimpleNamespace()

    def session_history_page(
        self,
        session_id: str,
        *,
        cursor: str | None,
        page_size: int,
    ) -> SessionHistoryPage:
        self.calls.append((session_id, cursor, page_size))
        record = SessionReplayRecord(
            session_id,
            4,
            "turn-4",
            "assistant",
            text="answer",
            message_id="message-4",
        )
        return SessionHistoryPage(
            session_id=session_id,
            records=(record,),
            next_cursor="opaque-next",
            has_more=True,
            unit_count=1,
            bytes_read=128,
        )


@pytest.mark.asyncio
async def test_history_page_is_exposed_as_a_safe_desktop_dto() -> None:
    application = _HistoryApplication()
    bridge = DesktopBridge(application)

    response = await bridge.handle_request(
        RequestEnvelope(
            "history-1",
            "history.page",
            {"session_id": "session-1", "page_size": 1},
        )
    )

    assert response.ok is True
    assert response.result == {
        "session_id": "session-1",
        "records": [
            {
                "session_id": "session-1",
                "sequence": 4,
                "turn_id": "turn-4",
                "kind": "assistant",
                "text": "answer",
                "is_error": False,
                "message_id": "message-4",
                "record_id": "session-1:4:assistant::-",
            }
        ],
        "next_cursor": "opaque-next",
        "has_more": True,
        "unit_count": 1,
    }
    assert application.calls == [("session-1", None, 1)]

    second = await bridge.handle_request(
        RequestEnvelope(
            "history-2",
            "history.page",
            {"session_id": "session-1", "cursor": "opaque-prev", "page_size": 1},
        )
    )
    assert second.ok is True
    assert application.calls[-1] == ("session-1", "opaque-prev", 1)


@pytest.mark.asyncio
async def test_live_event_message_ids_survive_run_persistence_and_history_page(
    tmp_path: Path,
) -> None:
    project_key = str(tmp_path.resolve())
    store = SessionFileStore(tmp_path / "sessions")
    store.create_session("session-message-identity", project_key=project_key)
    first_tool = _provider_response(
        ReasoningPart("first reasoning"),
        ToolCallPart(
            "call-identity",
            "TodoWrite",
            {"todos": [{"content": "check identity", "status": "completed"}]},
        ),
        finish_reason=FinishReason.TOOL_CALLS,
    )
    provider = _IdentityScriptProvider(
        (
            (ProviderReasoningDelta("first reasoning"), first_tool),
            (ProviderReasoningDelta("second reasoning"), _provider_response(ReasoningPart("second reasoning"), TextPart("answer"))),
            (ProviderReasoningDelta("new turn reasoning"), _provider_response(ReasoningPart("new turn reasoning"), TextPart("next answer"))),
        )
    )
    application = UthCodeApplication(
        provider,  # type: ignore[arg-type]
        session_service=ApplicationSessionService(
            storage_root=store.root,
            project_key=project_key,
            instruction_loader=None,
            store=store,
        ),
    )
    application.resume_session_for_command("session-message-identity")
    bridge = DesktopBridge(application)
    try:
        started = await bridge.handle_request(
            RequestEnvelope("identity-turn-one", "turn.start", {"prompt": "inspect"})
        )
        assert started.ok is True
        await bridge.wait_for_idle()
        first_events = [
            envelope.event
            for envelope in bridge.drain_outbox()
            if envelope.type == "agent_event"
        ]
        first_page = await bridge.handle_request(
            RequestEnvelope(
                "identity-page-one",
                "history.page",
                {"session_id": "session-message-identity", "page_size": 30},
            )
        )
        assert first_page.ok is True and first_page.result is not None
        first_records = first_page.result["records"]
        assert isinstance(first_records, list)
        first_turn_started = next(event for event in first_events if event["type"] == "turn_started")
        first_assistants = [
            event["message_id"]
            for event in first_events
            if event["type"] == "assistant_message_completed"
        ]
        assert len(first_assistants) == 2
        assert [record["kind"] for record in first_records] == [
            "user",
            "reasoning",
            "tool",
            "reasoning",
            "assistant",
        ]
        assert [
            record["message_id"]
            for record in first_records
            if record["kind"] in {"user", "reasoning", "assistant"}
        ] == [
            first_turn_started["message_id"],
            first_assistants[0],
            first_assistants[1],
            first_assistants[1],
        ]
        assert first_records[2]["tool_call_id"] == "call-identity"
        assert all(
            isinstance(message_id, str) and len(message_id) == 32
            for message_id in [first_turn_started["message_id"], *first_assistants]
        )

        second = await bridge.handle_request(
            RequestEnvelope("identity-turn-two", "turn.start", {"prompt": "next"})
        )
        assert second.ok is True
        await bridge.wait_for_idle()
        second_events = [
            envelope.event
            for envelope in bridge.drain_outbox()
            if envelope.type == "agent_event"
        ]
        second_page = await bridge.handle_request(
            RequestEnvelope(
                "identity-page-two",
                "history.page",
                {"session_id": "session-message-identity", "page_size": 30},
            )
        )
        assert second_page.ok is True and second_page.result is not None
        all_records = second_page.result["records"]
        assert isinstance(all_records, list)
        second_turn_started = next(event for event in second_events if event["type"] == "turn_started")
        second_assistant = next(
            event["message_id"]
            for event in second_events
            if event["type"] == "assistant_message_completed"
        )
        second_turn_id = second_turn_started["turn_id"]
        second_turn_records = [record for record in all_records if record["turn_id"] == second_turn_id]
        assert [record["kind"] for record in second_turn_records] == ["user", "reasoning", "assistant"]
        assert [record["message_id"] for record in second_turn_records] == [
            second_turn_started["message_id"],
            second_assistant,
            second_assistant,
        ]
        assert len({record["message_id"] for record in second_turn_records}) == 2
    finally:
        await bridge.shutdown()


@pytest.mark.asyncio
async def test_user_event_is_published_after_durable_retry_before_gated_provider_limits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_key = str(tmp_path.resolve())
    store = SessionFileStore(tmp_path / "sessions")
    store.create_session("session-user-entry-boundary", project_key=project_key)
    provider = _GatedLimitsProvider()
    application = UthCodeApplication(
        provider,  # type: ignore[arg-type]
        session_service=ApplicationSessionService(
            storage_root=store.root,
            project_key=project_key,
            instruction_loader=None,
            store=store,
        ),
    )
    await application.resume_session_for_command_async("session-user-entry-boundary")
    provider.gate_limits = True
    real_persist = application._persist_run_messages
    persist_attempts = 0

    def fail_first_persist(messages, *, session_id, turn_id, **metadata):  # type: ignore[no-untyped-def]
        nonlocal persist_attempts
        persist_attempts += 1
        if persist_attempts == 1:
            return SimpleNamespace(
                persisted_message_count=0,
                terminal_failure_appended=False,
                transcript_durability="not_durable",
            )
        return real_persist(messages, session_id=session_id, turn_id=turn_id, **metadata)

    monkeypatch.setattr(application, "_persist_run_messages", fail_first_persist)
    handle = application.create_run().start_turn("durable before provider")
    events = handle.events()

    started = await asyncio.wait_for(anext(events), timeout=1)
    assert started.event_type == "turn_started"
    assert started.message_id
    await asyncio.wait_for(provider.limits_entered.wait(), timeout=1)
    assert persist_attempts == 2, "the first failed append is retried before async Provider limits"
    assert provider.requests == [], "the Provider generation request remains gated"

    transcript = store.read_session("session-user-entry-boundary").transcript
    user_entries = [
        entry
        for entry in transcript.entries
        if entry.kind is TranscriptKind.USER_MESSAGE and entry.turn_id == started.turn_id
    ]
    assert len(user_entries) == 1
    assert user_entries[0].payload.get("message_id") == started.message_id
    assert isinstance(user_entries[0].created_at, str) and user_entries[0].created_at

    provider.release_limits.set()
    await asyncio.wait_for(provider.stream_entered.wait(), timeout=1)
    assert not handle._driver._result_future.done()  # type: ignore[union-attr]
    assert len(provider.requests) == 1
    handle.cancel()
    provider.release_stream.set()
    remaining = [event async for event in events]
    result = await asyncio.wait_for(handle.result(), timeout=1)

    assert result.status.value == "cancelled"
    assert any(event.event_type == "turn_cancelled" for event in remaining)
    final_users = [
        entry
        for entry in store.read_session("session-user-entry-boundary").transcript.entries
        if entry.kind is TranscriptKind.USER_MESSAGE and entry.turn_id == started.turn_id
    ]
    assert len(final_users) == 1, "cancel after the durable boundary does not duplicate or remove the user entry"


@pytest.mark.asyncio
async def test_unpersisted_user_event_is_released_with_terminal_failure_without_provider_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_key = str(tmp_path.resolve())
    store = SessionFileStore(tmp_path / "sessions")
    store.create_session("session-user-entry-failure", project_key=project_key)
    provider = _GatedLimitsProvider()
    application = UthCodeApplication(
        provider,  # type: ignore[arg-type]
        session_service=ApplicationSessionService(
            storage_root=store.root,
            project_key=project_key,
            instruction_loader=None,
            store=store,
        ),
    )
    await application.resume_session_for_command_async("session-user-entry-failure")
    provider.gate_limits = True

    def fail_persist(_messages, *, session_id, turn_id, **_metadata):  # type: ignore[no-untyped-def]
        return SimpleNamespace(
            persisted_message_count=0,
            terminal_failure_appended=False,
            transcript_durability="not_durable",
        )

    monkeypatch.setattr(application, "_persist_run_messages", fail_persist)
    handle = application.create_run().start_turn("must not reach provider")

    async def collect_events():
        return [event async for event in handle.events()]

    events = await asyncio.wait_for(collect_events(), timeout=1)
    result = await asyncio.wait_for(handle.result(), timeout=1)

    assert result.status.value == "failed"
    assert result.failure_reason.value == "persistence_unavailable"
    assert events[0].event_type == "turn_started"
    assert events[-1].event_type == "turn_failed"
    assert not provider.limits_entered.is_set()
    assert provider.requests == []
    user_entries = [
        entry
        for entry in store.read_session("session-user-entry-failure").transcript.entries
        if entry.kind is TranscriptKind.USER_MESSAGE
    ]
    assert user_entries == [], "a live event released at terminal does not claim failed persistence as durable"


@pytest.mark.asyncio
async def test_failed_visible_tail_keeps_its_live_message_identity_in_history(
    tmp_path: Path,
) -> None:
    project_key = str(tmp_path.resolve())
    store = SessionFileStore(tmp_path / "sessions")
    store.create_session("session-failed-identity", project_key=project_key)
    application = UthCodeApplication(
        FakeProvider(
            events=(ProviderReasoningDelta("visible reasoning"), TextDelta("unfinished answer")),
            error=ProviderError("provider failed after visible output"),
            model_limits=ModelLimits(max_input_tokens=256_000, source="test.history_identity"),
        ),
        session_service=ApplicationSessionService(
            storage_root=store.root,
            project_key=project_key,
            instruction_loader=None,
            store=store,
        ),
    )
    application.resume_session_for_command("session-failed-identity")
    bridge = DesktopBridge(application)
    try:
        started = await bridge.handle_request(
            RequestEnvelope("failed-identity-turn", "turn.start", {"prompt": "fail visibly"})
        )
        assert started.ok is True
        await bridge.wait_for_idle()
        events = [
            envelope.event
            for envelope in bridge.drain_outbox()
            if envelope.type == "agent_event"
        ]
        live_ids = {
            event["message_id"]
            for event in events
            if event["type"] in {"reasoning_delta", "assistant_message_delta"}
        }
        assert len(live_ids) == 1
        assert not any(event["type"] == "assistant_message_completed" for event in events)
        page = await bridge.handle_request(
            RequestEnvelope(
                "failed-identity-page",
                "history.page",
                {"session_id": "session-failed-identity", "page_size": 30},
            )
        )
        assert page.ok is True and page.result is not None
        records = page.result["records"]
        assert isinstance(records, list)
        visible_records = [record for record in records if record["kind"] in {"reasoning", "assistant"}]
        assert [(record["kind"], record["message_id"]) for record in visible_records] == [
            ("reasoning", next(iter(live_ids))),
            ("assistant", next(iter(live_ids))),
        ]
        assert any(record["kind"] == "failure" for record in records)
    finally:
        await bridge.shutdown()


@pytest.mark.asyncio
async def test_pending_assistant_batch_retry_keeps_frozen_event_message_ids(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_key = str(tmp_path.resolve())
    store = SessionFileStore(tmp_path / "sessions")
    store.create_session("session-pending-message-identity", project_key=project_key)
    provider = _IdentityScriptProvider(
        (
            (
                ProviderReasoningDelta("prepare the tool"),
                _provider_response(
                    ToolCallPart(
                        "call-persist-identity",
                        "TodoWrite",
                            {"todos": [{"content": "keep identity", "status": "completed"}]},
                    ),
                    finish_reason=FinishReason.TOOL_CALLS,
                ),
            ),
            _provider_response(TextPart("unreached")),
        )
    )
    application = UthCodeApplication(
        provider,  # type: ignore[arg-type]
        session_service=ApplicationSessionService(
            storage_root=store.root,
            project_key=project_key,
            instruction_loader=None,
            store=store,
        ),
    )
    application.resume_session_for_command("session-pending-message-identity")
    real_persist = application._persist_run_messages
    attempts: list[tuple[tuple[Message, ...], tuple[str | None, ...], object]] = []

    def fail_closed_assistant_once(messages, *, session_id, turn_id, **metadata):  # type: ignore[no-untyped-def]
        attempts.append((tuple(messages), tuple(metadata["message_ids"]), metadata.get("termination_reason")))
        if len(attempts) == 2:
            return SimpleNamespace(
                persisted_message_count=0,
                terminal_failure_appended=False,
                transcript_durability="not_durable",
            )
        return real_persist(messages, session_id=session_id, turn_id=turn_id, **metadata)

    monkeypatch.setattr(application, "_persist_run_messages", fail_closed_assistant_once)
    handle = application.create_run().start_turn("use the todo tool")
    events = [event async for event in handle.events()]
    result = await handle.result()

    user_message_id = next(event.message_id for event in events if event.event_type == "turn_started")
    assistant_message_id = next(
        event.message_id
        for event in events
        if event.event_type == "assistant_message_completed"
    )
    assert result.status.value != "completed"
    assert result.failure_reason.value == "persistence_unavailable"
    assert len(provider.requests) == 1
    assert len(attempts) == 3
    assert attempts[0][1] == (user_message_id,)
    assert attempts[1][0] == attempts[2][0]
    assert attempts[1][1] == attempts[2][1]
    assert attempts[1][1][0] == assistant_message_id
    assert attempts[1][2] is None and attempts[2][2] is not None, "the terminal retry extends the pending batch without changing its captured message identity"
    page = application.session_history_page("session-pending-message-identity", page_size=30)
    assert any(record.kind == "tool" and record.tool_call_id == "call-persist-identity" for record in page.records)
    transcript = store.read_session("session-pending-message-identity").transcript
    tool_calls = [entry for entry in transcript.entries if entry.kind is TranscriptKind.TOOL_CALL]
    assert len(tool_calls) == 1
    assert tool_calls[0].payload["message_id"] == assistant_message_id


@pytest.mark.asyncio
async def test_restarted_session_history_keeps_image_with_same_user_message(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    sessions = SessionFileStore(tmp_path / "sessions")
    session_id = "image-history"
    project_key = str(project.resolve())
    sessions.create_session(session_id, project_key=project_key)

    first = UthCodeApplication(
        FakeProvider(),
        session_service=ApplicationSessionService(
            storage_root=sessions.root,
            project_key=project_key,
            instruction_loader=None,
            store=sessions,
        ),
        attachment_service=AttachmentService(sessions),
    )
    try:
        session = first.resume_session_for_command(session_id)
        source_image = tmp_path / "actual-photo.png"
        source_image.write_bytes(
            base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
            )
        )
        image = first.import_attachment(
            source_image.read_bytes(),
            display_name=source_image.name,
            mime_type="image/png",
        )
        source_image.unlink()
        missing = first.import_attachment(
            b"will be removed after submission",
            display_name="missing-report.txt",
            mime_type="text/plain",
        )
        message_entries = transcript_entries_from_message(
            session_id,
            "turn-image",
            1,
            Message(
                "user",
                (
                    TextPart("正文"),
                    ImagePart(image.asset_ref, image.mime_type, image.width, image.height),
                    FilePart(
                        missing.asset_ref,
                        missing.display_name,
                        missing.mime_type,
                        missing.size_bytes,
                    ),
                ),
            ),
        )
        steering_entries = transcript_entries_from_message(
            session_id,
            "turn-image",
            4,
            Message("user", (TextPart("后续引导"),)),
        )
        steering = replace(steering_entries[0], kind=TranscriptKind.USER_STEERING)
        assert session.append_transcript((*message_entries, steering)).transcript_appended
    finally:
        first.close()

    missing_content = sessions.session_path(session_id) / "attachments" / missing.ref / "content.bin"
    missing_content.unlink()

    restarted_store = SessionFileStore(sessions.root)
    restarted = UthCodeApplication(
        FakeProvider(),
        session_service=ApplicationSessionService(
            storage_root=sessions.root,
            project_key=project_key,
            instruction_loader=None,
            store=restarted_store,
        ),
        attachment_service=AttachmentService(restarted_store),
    )
    bridge = DesktopBridge(restarted)
    try:
        resumed = restarted.resume_session_for_command(session_id)
        assert resumed.session_id == session_id
        replay_image = next(
            record.attachments[0]
            for record in resumed.replay
            if record.message_id == "turn-image:1" and record.attachments
        )
        assert replay_image == {
            "type": "image",
            "asset_ref": image.asset_ref,
            "mime_type": "image/png",
            "width": image.width,
            "height": image.height,
            "ref": image.ref,
            "display_name": "actual-photo.png",
            "size_bytes": image.size_bytes,
            "available": True,
        }
        replay_missing = next(
            record.attachments[0]
            for record in resumed.replay
            if record.message_id == "turn-image:1"
            and record.attachments
            and record.attachments[0].get("asset_ref") == missing.asset_ref
        )
        assert replay_missing == {
            "type": "file",
            "asset_ref": missing.asset_ref,
            "mime_type": "text/plain",
            "ref": missing.ref,
            "available": False,
            "error_code": "attachment_unavailable",
        }
        response = await bridge.handle_request(
            RequestEnvelope(
                "history-image",
                "history.page",
                {"session_id": session_id, "page_size": 10},
            )
        )
        assert response.ok is True
        assert response.result is not None
        records = response.result["records"]
        assert isinstance(records, list)
        user_records = [record for record in records if record.get("message_id") == "turn-image:1"]
        assert [(record["kind"], record["text"]) for record in user_records] == [
            ("user", "正文"),
            ("user", ""),
            ("user", ""),
        ]
        assert user_records[0]["message_id"] == user_records[1]["message_id"]
        image_record = next(
            record
            for record in user_records
            if record.get("attachments", [{}])[0].get("asset_ref") == image.asset_ref
        )
        assert image_record["attachments"][0] == dict(replay_image)
        assert "data_url" not in image_record["attachments"][0]
        missing_record = next(
            record
            for record in user_records
            if record.get("attachments", [{}])[0].get("asset_ref") == missing.asset_ref
        )
        assert missing_record["attachments"][0] == dict(replay_missing)
        assert "display_name" not in missing_record["attachments"][0]
        assert "size_bytes" not in missing_record["attachments"][0]
        steering_records = [record for record in records if record.get("text") == "后续引导"]
        assert len(steering_records) == 1
        assert steering_records[0]["kind"] == "steering"
    finally:
        await bridge.shutdown()


@pytest.mark.asyncio
async def test_cold_application_resume_offloads_real_session_file_recovery(
    tmp_path: Path,
) -> None:
    """A blocked real JSONL recovery must not stop another Bridge request."""

    store = SessionFileStore(tmp_path / "sessions")
    store.create_session("session-a", project_key="project")
    store.create_session("session-b", project_key="project")
    source_service = ApplicationSessionService(
        storage_root=tmp_path / "sessions",
        project_key="project",
        instruction_loader=None,
        store=store,
    )
    source = UthCodeApplication(FakeProvider(), session_service=source_service)
    source.resume_session_for_command("session-a")

    recovery_started = Event()
    release_recovery = Event()
    candidate_stores: list[SessionFileStore] = []

    def factory(_workdir: Path) -> UthCodeApplication:
        candidate_store = SessionFileStore(tmp_path / "sessions")
        original_load = candidate_store._load_snapshot

        def blocked_load(path: Path, **kwargs: object):
            if not release_recovery.is_set():
                recovery_started.set()
                release_recovery.wait(timeout=2)
            return original_load(path, **kwargs)

        candidate_store._load_snapshot = blocked_load  # type: ignore[method-assign]
        candidate_stores.append(candidate_store)
        return UthCodeApplication(
            FakeProvider(),
            session_service=ApplicationSessionService(
                storage_root=tmp_path / "sessions",
                project_key="project",
                instruction_loader=None,
                store=candidate_store,
            ),
        )

    bridge = DesktopBridge(
        source,
        application_factory=factory,
        workdir=tmp_path,
    )
    started = await bridge.handle_request(
        RequestEnvelope(
            "resume-cold",
            "session.resume",
            {"session_id": "session-b"},
        )
    )
    assert started.ok is True
    assert started.result["preparing"] is True
    await asyncio.wait_for(asyncio.to_thread(recovery_started.wait, 1), timeout=1)
    assert candidate_stores

    # This request uses the source Application while the target candidate is
    # blocked in the real SessionFileStore._load_snapshot call.  If the async
    # Application boundary ran that recovery on the Bridge loop, this await
    # would not complete until release_recovery was set below.
    before = asyncio.get_running_loop().time()
    page = await asyncio.wait_for(
        bridge.handle_request(
            RequestEnvelope(
                "page-while-cold",
                "history.page",
                {"session_id": "session-b"},
            )
        ),
        timeout=0.5,
    )
    elapsed = asyncio.get_running_loop().time() - before
    assert page.ok is True
    assert elapsed < 0.5
    assert not release_recovery.is_set()

    release_recovery.set()
    runtime_task = bridge._background_runtimes["session-b"]["task"]
    assert isinstance(runtime_task, asyncio.Task)
    await asyncio.wait_for(runtime_task, timeout=2)
    ready = await bridge.handle_request(
        RequestEnvelope(
            "resume-ready",
            "session.resume",
            {"session_id": "session-b"},
        )
    )
    assert ready.ok is True
    assert ready.result["preparing"] is False
    await bridge.shutdown()


@pytest.mark.asyncio
async def test_cold_prepare_captures_owner_workdir_before_project_switch(
    tmp_path: Path,
) -> None:
    """A queued cold task keeps the project boundary it was created for."""

    sessions_root = tmp_path / "sessions"
    source_store = SessionFileStore(sessions_root)
    source_store.create_session("session-a", project_key="project")
    source_store.create_session("session-b", project_key="project")
    source_service = ApplicationSessionService(
        storage_root=sessions_root,
        project_key="project",
        instruction_loader=None,
        store=source_store,
    )
    source = UthCodeApplication(FakeProvider(), session_service=source_service)
    source.resume_session_for_command("session-a")

    owner_workdir = tmp_path / "project-a"
    switched_workdir = tmp_path / "project-b"
    factory_started = Event()
    release_factory = Event()
    factory_paths: list[Path] = []

    def factory(workdir: Path) -> UthCodeApplication:
        factory_paths.append(workdir)
        factory_started.set()
        release_factory.wait(timeout=2)
        candidate_store = SessionFileStore(sessions_root)
        return UthCodeApplication(
            FakeProvider(),
            session_service=ApplicationSessionService(
                storage_root=sessions_root,
                project_key="project",
                instruction_loader=None,
                store=candidate_store,
            ),
        )

    bridge = DesktopBridge(
        source,
        application_factory=factory,
        workdir=owner_workdir,
    )
    try:
        started = await bridge.handle_request(
            RequestEnvelope(
                "resume-cold",
                "session.resume",
                {"session_id": "session-b"},
            )
        )
        assert started.ok is True
        await asyncio.wait_for(asyncio.to_thread(factory_started.wait, 1), timeout=1)

        # Simulate a project switch while the worker is still queued inside
        # the candidate factory.  The task must retain its original owner
        # boundary instead of consulting the Bridge's mutable current path.
        bridge._workdir = switched_workdir
        release_factory.set()
        runtime_task = bridge._background_runtimes["session-b"]["task"]
        assert isinstance(runtime_task, asyncio.Task)
        await asyncio.wait_for(runtime_task, timeout=2)

        assert factory_paths == [owner_workdir]
        assert bridge._background_runtimes["session-b"]["project_key"] == str(owner_workdir)
    finally:
        release_factory.set()
        await bridge.shutdown()
