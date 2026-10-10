from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest

from uthcode.application import (
    ApplicationRuntimeContext,
    ApplicationSessionService,
    Message,
    SessionMutation,
    SessionOperationError,
    TextPart,
    ToolCallPart,
    ToolResultPart,
    UthCodeApplication,
)
from uthcode.core.history import TranscriptEntry, TranscriptKind, transcript_entries_from_message
from uthcode.core.provider import CancellationToken, ReasoningPart
from uthcode.integrations import session_files
from uthcode.integrations.providers.fake import FakeProvider
from uthcode.integrations.session_files import (
    SESSION_TITLE_MAX_LENGTH,
    SessionFileStore,
    SessionMetadata,
)
from uthcode.interfaces.desktop.bridge import DesktopBridge
from uthcode.interfaces.desktop.protocol import RequestEnvelope
from uthcode.interfaces.tui.app import UthCodeTUI
from prompt_toolkit.output import DummyOutput


def _paths(tmp_path: Path) -> tuple[Path, Path, SessionFileStore]:
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    return source, target, SessionFileStore(tmp_path / "sessions")


def _real_application(
    store: SessionFileStore,
    project_key: str,
) -> tuple[UthCodeApplication, ApplicationSessionService]:
    service = ApplicationSessionService(
        storage_root=store.root,
        project_key=project_key,
        instruction_loader=None,
        store=store,
    )
    application = UthCodeApplication(
        FakeProvider(),
        runtime_context=ApplicationRuntimeContext.from_system(
            workdir=Path(project_key),
        ),
        session_service=service,
    )
    return application, service


def _user_transcript(session_id: str, text: str):
    return transcript_entries_from_message(
        session_id,
        "turn-title",
        1,
        Message("user", (TextPart(text),)),
    )


def test_legacy_metadata_without_title_is_read_without_rewrite(tmp_path: Path) -> None:
    source, _target, store = _paths(tmp_path)
    store.create_session("legacy", project_key=str(source.resolve()))
    metadata_path = store.session_path("legacy") / "metadata.json"
    value = json.loads(metadata_path.read_text(encoding="utf-8"))
    value.pop("title")
    value.pop("archived")
    metadata_path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    before = metadata_path.read_bytes()

    snapshot = store.read_session("legacy", expected_project_key=str(source.resolve()))

    assert snapshot.title is None
    assert snapshot.metadata.title is None
    assert snapshot.metadata.archived is False
    assert metadata_path.read_bytes() == before


def test_archive_restore_reuses_metadata_and_preserves_session_history(tmp_path: Path) -> None:
    source, _target, store = _paths(tmp_path)
    project_key = str(source.resolve())
    store.create_session(
        "archive-round-trip",
        project_key=project_key,
        title="保留标题",
        model_ref="provider/model",
    )
    with store.open_writer("archive-round-trip", expected_project_key=project_key) as writer:
        assert writer.append_transcript(
            _user_transcript("archive-round-trip", "保留的原始会话内容")
        ).transcript_appended
    before = store.read_session("archive-round-trip").metadata
    transcript_path = store.session_path("archive-round-trip") / "transcript.jsonl"
    timeline_path = store.session_path("archive-round-trip") / "timeline.jsonl"
    transcript_bytes = transcript_path.read_bytes()
    timeline_bytes = timeline_path.read_bytes()
    service = ApplicationSessionService(
        storage_root=store.root,
        project_key=project_key,
        instruction_loader=None,
        store=store,
    )

    # Reuse the active Session's existing writer; do not try to take a second
    # lock or let the archive mutation touch activity metadata.
    with service.resume_session_for_command("archive-round-trip") as active:
        last_used_before_archive = active.metadata.last_used_at
        archived = service.set_session_archived("archive-round-trip", True)
        assert archived.archived is True
        assert service.list_sessions(archived=True)[0].last_used_at == last_used_before_archive
        assert active.metadata.archived is True
        assert active.metadata.last_used_at == last_used_before_archive
        assert service.list_sessions() == ()
        assert service.list_catalog_metadata() == ()
        assert service.list_sessions(archived=True)[0].session_id == "archive-round-trip"
        archived_catalog = service.list_catalog_metadata(archived=True)
        assert archived_catalog[0].archived is True
        archive_bytes = (store.session_path("archive-round-trip") / "metadata.json").read_bytes()
        assert service.set_session_archived("archive-round-trip", True) == archived
        assert (store.session_path("archive-round-trip") / "metadata.json").read_bytes() == archive_bytes
        restored = service.set_session_archived("archive-round-trip", False)
        assert restored.archived is False
        assert active.metadata.archived is False

    restarted = SessionFileStore(store.root)
    recovered = restarted.read_session("archive-round-trip", expected_project_key=project_key)
    assert recovered.metadata.session_id == before.session_id
    assert recovered.metadata.project_key == before.project_key
    assert recovered.metadata.title == before.title
    assert recovered.metadata.model_ref == before.model_ref
    assert recovered.metadata.created_at == before.created_at
    assert recovered.metadata.archived is False
    assert recovered.transcript.entries == store.read_session("archive-round-trip").transcript.entries
    assert transcript_path.read_bytes() == transcript_bytes
    assert timeline_path.read_bytes() == timeline_bytes
    assert service.list_catalog_metadata()[0].preview == "保留的原始会话内容"


@pytest.mark.parametrize(
    "failure_mode",
    ["before-replace", "post-replace-error", "post-replace-interruption"],
    ids=["before-replace", "post-replace-error", "post-replace-interruption"],
)
def test_archive_reconciles_metadata_after_atomic_write_exception(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_mode: str,
) -> None:
    source, _target, store = _paths(tmp_path)
    project_key = str(source.resolve())
    store.create_session("archive-uncertain", project_key=project_key, title="内容保留")
    with store.open_writer("archive-uncertain", expected_project_key=project_key) as writer:
        assert writer.append_transcript(
            _user_transcript("archive-uncertain", "历史不会随归档删除")
        ).transcript_appended
    metadata_path = store.session_path("archive-uncertain") / "metadata.json"
    transcript_path = store.session_path("archive-uncertain") / "transcript.jsonl"
    transcript_before = transcript_path.read_bytes()
    original_write = session_files._atomic_write_json
    calls = 0

    def replace_then_interrupt(path: Path, value: object) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            if failure_mode == "before-replace":
                raise OSError("simulated metadata write failure before replace")
            original_write(path, value)  # type: ignore[arg-type]
            if failure_mode == "post-replace-interruption":
                raise KeyboardInterrupt()
            raise OSError("simulated post-replace metadata failure")
        original_write(path, value)  # type: ignore[arg-type]

    monkeypatch.setattr(session_files, "_atomic_write_json", replace_then_interrupt)
    service = ApplicationSessionService(
        storage_root=store.root,
        project_key=project_key,
        instruction_loader=None,
        store=store,
    )
    if failure_mode == "post-replace-interruption":
        with pytest.raises(KeyboardInterrupt):
            service.set_session_archived("archive-uncertain", True)
    else:
        with pytest.raises(SessionOperationError) as failure:
            service.set_session_archived("archive-uncertain", True)
        assert failure.value.kind == "storage"
    assert calls == 1
    persisted_archived = failure_mode != "before-replace"
    assert json.loads(metadata_path.read_text(encoding="utf-8"))["archived"] is persisted_archived
    assert (
        store.read_session("archive-uncertain", expected_project_key=project_key).metadata.archived
        is persisted_archived
    )
    assert transcript_path.read_bytes() == transcript_before

    # A retry converges from the re-read durable state and does not rewrite it.
    actual_metadata = metadata_path.read_bytes()
    assert service.set_session_archived("archive-uncertain", True).archived is True
    assert calls == (1 if persisted_archived else 2)
    if persisted_archived:
        assert metadata_path.read_bytes() == actual_metadata
    else:
        assert json.loads(metadata_path.read_text(encoding="utf-8"))["archived"] is True


def test_archive_reports_writer_conflict_without_changing_session(tmp_path: Path) -> None:
    source, _target, store = _paths(tmp_path)
    project_key = str(source.resolve())
    store.create_session("archive-busy", project_key=project_key, title="未变更")
    service = ApplicationSessionService(
        storage_root=store.root,
        project_key=project_key,
        instruction_loader=None,
        store=store,
    )
    metadata_path = store.session_path("archive-busy") / "metadata.json"
    before = metadata_path.read_bytes()
    with store.open_writer("archive-busy", expected_project_key=project_key):
        with pytest.raises(SessionOperationError) as busy:
            service.set_session_archived("archive-busy", True)
    assert busy.value.kind == "busy"
    assert metadata_path.read_bytes() == before
    assert store.read_session("archive-busy", expected_project_key=project_key).metadata.archived is False


def test_search_uses_explicit_project_scope_and_public_complete_history(tmp_path: Path) -> None:
    source, target, store = _paths(tmp_path)
    outsider = tmp_path / "unregistered"
    outsider.mkdir()
    source_key = str(source.resolve())
    target_key = str(target.resolve())
    outsider_key = str(outsider.resolve())
    session_rows = (
        (
            "search-source",
            source_key,
            (
                TranscriptEntry(
                    "search-source", 1, "old-user", TranscriptKind.USER_MESSAGE,
                    {"role": "user", "part": TextPart("FIRST_ONLY_PUBLIC_MARKER").to_dict()},
                    semantic_unit_id="old-user",
                ),
                TranscriptEntry(
                    "search-source", 2, "old-assistant", TranscriptKind.ASSISTANT_MESSAGE,
                    {"role": "assistant", "part": TextPart("ANCIENT_ASSISTANT_MARKER").to_dict()},
                    semantic_unit_id="old-assistant",
                ),
            ),
        ),
        (
            "search-target",
            target_key,
            (
                TranscriptEntry(
                    "search-target", 1, "target-user", TranscriptKind.USER_MESSAGE,
                    {"role": "user", "part": TextPart("TARGET_PUBLIC_MARKER").to_dict()},
                    semantic_unit_id="target-user",
                ),
            ),
        ),
        (
            "search-unregistered",
            outsider_key,
            (
                TranscriptEntry(
                    "search-unregistered", 1, "outsider-user", TranscriptKind.USER_MESSAGE,
                    {"role": "user", "part": TextPart("FIRST_ONLY_PUBLIC_MARKER").to_dict()},
                    semantic_unit_id="outsider-user",
                ),
            ),
        ),
    )
    for session_id, project_key, entries in session_rows:
        store.create_session(session_id, project_key=project_key, title="相同标题")
        with store.open_writer(session_id, expected_project_key=project_key) as writer:
            writer.append_transcript(entries)

    service = ApplicationSessionService(
        storage_root=store.root,
        project_key=source_key,
        instruction_loader=None,
        store=store,
    )
    service.read_session = lambda *_args, **_kwargs: (_ for _ in ()).throw(  # type: ignore[method-assign]
        AssertionError("search must not load full Session snapshots")
    )

    both_projects = service.search_sessions(
        "相同标题",
        project_keys=(source_key, target_key),
    )
    assert {hit.session_id for hit in both_projects.hits} == {"search-source", "search-target"}
    assert all(hit.snippet == "相同标题" and not hit.archived for hit in both_projects.hits)
    assert [hit.session_id for hit in service.search_sessions(
        "相同标题", project_keys=(source_key,)
    ).hits] == ["search-source"]
    assert [hit.session_id for hit in service.search_sessions(
        "FIRST_ONLY_PUBLIC_MARKER", project_keys=(source_key, target_key)
    ).hits] == ["search-source"]
    assert [hit.session_id for hit in service.search_sessions(
        "ANCIENT_ASSISTANT_MARKER", project_keys=(source_key, target_key)
    ).hits] == ["search-source"]
    assert service.search_sessions("FIRST_ONLY_PUBLIC_MARKER").hits[0].project_key == source_key

    assert service.search_sessions(" \t ", project_keys=(source_key, target_key)).hits == ()
    assert service.search_sessions("no such public text", project_keys=(source_key, target_key)).hits == ()
    assert service.search_sessions(
        "相同标题", project_keys=()
    ).hits == ()
    limited = service.search_sessions(
        "相同标题",
        project_keys=(source_key, target_key),
        max_results=1,
    )
    assert len(limited.hits) == 1
    assert limited.has_more is True
    assert len(limited.hits[0].snippet) <= 160
    with pytest.raises(ValueError):
        service.search_sessions("x" * 513)
    with pytest.raises(ValueError):
        service.search_sessions("相同标题", max_results=101)
    with pytest.raises(TypeError):
        service.search_sessions("相同标题", project_keys=source_key)  # type: ignore[arg-type]

    assert service.set_session_archived("search-source", True).archived is True
    archived_hit = service.search_sessions(
        "ANCIENT_ASSISTANT_MARKER", project_keys=(source_key, target_key)
    ).hits[0]
    assert archived_hit.session_id == "search-source"
    assert archived_hit.archived is True


@pytest.mark.parametrize(
    "damaged_identity",
    ["nonexistent", "search-identity-healthy"],
    ids=["wrong-identity", "duplicate-identity"],
)
def test_search_title_hit_skips_metadata_with_wrong_directory_identity(
    tmp_path: Path,
    damaged_identity: str,
) -> None:
    source, _target, store = _paths(tmp_path)
    project_key = str(source.resolve())
    store.create_session(
        "search-identity-healthy",
        project_key=project_key,
        title="MATCH healthy",
    )
    store.create_session(
        "search-identity-damaged",
        project_key=project_key,
        title="MATCH damaged",
    )
    healthy_path = store.session_path("search-identity-healthy") / "metadata.json"
    damaged_path = store.session_path("search-identity-damaged") / "metadata.json"
    healthy = json.loads(healthy_path.read_text(encoding="utf-8"))
    damaged = json.loads(damaged_path.read_text(encoding="utf-8"))
    damaged["session_id"] = damaged_identity
    damaged["last_used_at"] = healthy["last_used_at"]
    damaged_path.write_text(json.dumps(damaged, ensure_ascii=False), encoding="utf-8")

    service = ApplicationSessionService(
        storage_root=store.root,
        project_key=project_key,
        instruction_loader=None,
        store=store,
    )
    result = service.search_sessions("MATCH", max_results=20)

    assert [(hit.session_id, hit.title) for hit in result.hits] == [
        ("search-identity-healthy", "MATCH healthy")
    ]
    assert result.unavailable_count == 1


def test_search_excludes_reasoning_tool_results_logs_and_diagnostics(tmp_path: Path) -> None:
    source, _target, store = _paths(tmp_path)
    project_key = str(source.resolve())
    session_id = "search-private-fields"
    store.create_session(session_id, project_key=project_key, title="visible session")
    entries = (
        TranscriptEntry(
            session_id, 1, "user", TranscriptKind.USER_MESSAGE,
            {"role": "user", "part": TextPart("VISIBLE_USER_MARKER").to_dict()},
            semantic_unit_id="user",
        ),
        TranscriptEntry(
            session_id, 2, "reasoning", TranscriptKind.ASSISTANT_MESSAGE,
            {"role": "assistant", "part": ReasoningPart("PRIVATE_REASONING_MARKER").to_dict()},
            semantic_unit_id="reasoning",
        ),
        TranscriptEntry(
            session_id, 3, "tool-result", TranscriptKind.TOOL_CALL,
            {"part": ToolCallPart("call-private", "private").to_dict()},
            semantic_unit_id="tool-result",
        ),
        TranscriptEntry(
            session_id, 4, "tool-result", TranscriptKind.TOOL_RESULT,
            {"part": ToolResultPart("call-private", "PRIVATE_TOOL_RESULT_MARKER").to_dict()},
            semantic_unit_id="tool-result",
        ),
        TranscriptEntry(
            session_id, 5, "assistant", TranscriptKind.ASSISTANT_MESSAGE,
            {
                "role": "assistant",
                "part": TextPart("VISIBLE_ASSISTANT_MARKER").to_dict(),
                "log": "PRIVATE_LOG_MARKER",
                "diagnostics": "PRIVATE_DIAGNOSTIC_MARKER",
            },
            semantic_unit_id="assistant",
        ),
    )
    with store.open_writer(session_id, expected_project_key=project_key) as writer:
        writer.append_transcript(entries)
    service = ApplicationSessionService(
        storage_root=store.root,
        project_key=project_key,
        instruction_loader=None,
        store=store,
    )

    assert service.search_sessions("VISIBLE_USER_MARKER").hits[0].session_id == session_id
    assert service.search_sessions("VISIBLE_ASSISTANT_MARKER").hits[0].session_id == session_id
    for private_marker in (
        "PRIVATE_REASONING_MARKER",
        "PRIVATE_TOOL_RESULT_MARKER",
        "PRIVATE_LOG_MARKER",
        "PRIVATE_DIAGNOSTIC_MARKER",
    ):
        assert service.search_sessions(private_marker).hits == ()


@pytest.mark.parametrize(
    "failure",
    [
        session_files.SessionCorruptError("damaged transcript"),
        session_files.SessionNotFoundError("Session disappeared"),
        PermissionError("transcript is not readable"),
    ],
    ids=["damaged", "disappeared", "permission-denied"],
)
def test_search_keeps_healthy_hits_when_one_session_is_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
) -> None:
    source, _target, store = _paths(tmp_path)
    project_key = str(source.resolve())
    for session_id, text in (
        ("search-healthy", "PUBLIC_SURVIVING_HIT"),
        ("search-unavailable", "unrelated body"),
    ):
        store.create_session(session_id, project_key=project_key)
        with store.open_writer(session_id, expected_project_key=project_key) as writer:
            writer.append_transcript(_user_transcript(session_id, text))
    service = ApplicationSessionService(
        storage_root=store.root,
        project_key=project_key,
        instruction_loader=None,
        store=store,
    )
    original_read_page = store.read_history_page

    def fail_one_session(session_id: str, **kwargs: object):
        if session_id == "search-unavailable":
            raise failure
        return original_read_page(session_id, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(store, "read_history_page", fail_one_session)
    result = service.search_sessions("PUBLIC_SURVIVING_HIT")
    assert [hit.session_id for hit in result.hits] == ["search-healthy"]
    assert result.unavailable_count == 1


@pytest.mark.asyncio
async def test_application_search_does_not_create_or_resume_runtime(tmp_path: Path) -> None:
    source, _target, store = _paths(tmp_path)
    project_key = str(source.resolve())
    store.create_session("application-search", project_key=project_key)
    with store.open_writer("application-search", expected_project_key=project_key) as writer:
        writer.append_transcript(_user_transcript("application-search", "APP_SEARCH_PUBLIC_HIT"))
    application, service = _real_application(store, project_key)
    service.read_session = lambda *_args, **_kwargs: (_ for _ in ()).throw(  # type: ignore[method-assign]
        AssertionError("search must not replay Sessions")
    )
    application.create_run = lambda *_args, **_kwargs: (_ for _ in ()).throw(  # type: ignore[method-assign]
        AssertionError("search must not create a Runtime")
    )
    try:
        result = await application.search_sessions("APP_SEARCH_PUBLIC_HIT")
    finally:
        application.close()
    assert [hit.session_id for hit in result.hits] == ["application-search"]


@pytest.mark.asyncio
async def test_application_search_cancellation_stops_the_worker_scan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, _target, store = _paths(tmp_path)
    project_key = str(source.resolve())
    session_id = "search-cancelled"
    store.create_session(session_id, project_key=project_key)
    entries = tuple(
        TranscriptEntry(
            session_id,
            sequence,
            f"turn-{index}",
            TranscriptKind.USER_MESSAGE,
            {"role": "user", "part": TextPart(f"cancel scan body {index}").to_dict()},
            semantic_unit_id=f"turn-{index}",
        )
        for index, sequence in enumerate(range(1, 121))
    )
    with store.open_writer(session_id, expected_project_key=project_key) as writer:
        writer.append_transcript(entries)
    application, _service = _real_application(store, project_key)
    started = Event()
    release = Event()
    parsed = 0
    original_parse = session_files._history_entry_from_line

    def pause_first_parse(raw: bytes, *, path: Path, session_id: str):
        nonlocal parsed
        parsed += 1
        if parsed == 1:
            started.set()
            if not release.wait(timeout=5):
                raise TimeoutError("test did not release the paused transcript scan")
        return original_parse(raw, path=path, session_id=session_id)

    monkeypatch.setattr(session_files, "_history_entry_from_line", pause_first_parse)
    token = CancellationToken()
    scan_stopped = Event()
    original_raise_if_cancelled = CancellationToken.raise_if_cancelled

    def observe_cancelled_scan(cancellation: CancellationToken) -> None:
        if cancellation is token and cancellation.cancelled:
            scan_stopped.set()
        original_raise_if_cancelled(cancellation)

    monkeypatch.setattr(CancellationToken, "raise_if_cancelled", observe_cancelled_scan)
    loop = asyncio.get_running_loop()
    unhandled: list[dict[str, object]] = []
    previous_exception_handler = loop.get_exception_handler()
    loop.set_exception_handler(lambda _loop, context: unhandled.append(context))
    worker = asyncio.create_task(application.search_sessions("not present", cancellation=token))
    try:
        assert await asyncio.to_thread(started.wait, 5)
        worker.cancel()
        await asyncio.sleep(0)
        assert token.cancelled is True
        worker.cancel()
        await asyncio.sleep(0)
        assert worker.done() is False
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(worker, timeout=5)
        assert scan_stopped.wait(timeout=1)
        assert parsed == 1
        await asyncio.sleep(0)
        assert unhandled == []
    finally:
        release.set()
        if not worker.done():
            worker.cancel()
            token.cancel()
            try:
                await worker
            except BaseException:
                pass
        loop.set_exception_handler(previous_exception_handler)
        application.close()


def test_existing_text_session_reopens_without_duplicate_records_or_dual_write(
    tmp_path: Path,
) -> None:
    source, _target, store = _paths(tmp_path)
    project_key = str(source.resolve())
    session_id = "legacy-text"
    store.create_session(session_id, project_key=project_key)
    legacy = TranscriptEntry(
        session_id,
        1,
        "turn-text",
        TranscriptKind.USER_MESSAGE,
        {
            "type": "text",
            "message": Message("user", (TextPart("你好，旧文字会话"),)).to_dict(),
        },
        semantic_unit_id="turn-text",
    )
    transcript_path = store.session_path(session_id) / "transcript.jsonl"
    timeline_path = store.session_path(session_id) / "timeline.jsonl"
    session_files._append_jsonl(
        transcript_path,
        ({"schema_version": 2, "kind": "transcript", "sequence": 1, "entry": legacy.to_dict()},),
    )
    before_transcript = transcript_path.read_bytes()
    before_timeline = timeline_path.read_bytes()

    application, _service = _real_application(store, project_key)
    try:
        first = application.resume_session_for_command(session_id)
        first_replay = first.replay
        first_entries = first.transcript.entries
        application.close()
        second = application.resume_session_for_command(session_id)
        assert second.transcript.entries == first_entries == (legacy,)
        assert second.replay == first_replay
        assert transcript_path.read_bytes() == before_transcript
        assert timeline_path.read_bytes() == before_timeline
    finally:
        application.close()


@pytest.mark.parametrize("title", ["", " \n\t ", "x" * (SESSION_TITLE_MAX_LENGTH + 1)])
def test_title_validation_rejects_empty_or_overlong_values(tmp_path: Path, title: str) -> None:
    source, _target, store = _paths(tmp_path)

    with pytest.raises(ValueError):
        store.create_session("invalid", project_key=str(source.resolve()), title=title)
    assert not store.session_path("invalid").exists()


def test_title_normalization_is_persistent_and_projected_in_replay(tmp_path: Path) -> None:
    source, _target, store = _paths(tmp_path)
    project_key = str(source.resolve())
    metadata = store.create_session(
        "session-1",
        project_key=project_key,
        title="  Cafe\u0301\n\t中文  ",
    )
    assert metadata.title == "Café\n\t中文"

    with store.open_writer("session-1", expected_project_key=project_key) as writer:
        assert writer.update_title("  新标题  ").title == "新标题"

    service = ApplicationSessionService(
        storage_root=tmp_path / "sessions",
        project_key=project_key,
        instruction_loader=None,
        store=store,
    )
    assert store.read_session("session-1", expected_project_key=project_key).title == "新标题"
    assert service.list_catalog()[0].title == "新标题"
    assert json.loads((store.session_path("session-1") / "metadata.json").read_text(encoding="utf-8"))["title"] == "新标题"


def test_title_boundary_and_internal_whitespace_are_exact(tmp_path: Path) -> None:
    source, _target, store = _paths(tmp_path)
    project_key = str(source.resolve())
    accepted = "x" * SESSION_TITLE_MAX_LENGTH
    assert store.create_session(
        "title-boundary",
        project_key=project_key,
        title=accepted,
    ).title == accepted

    service = ApplicationSessionService(
        storage_root=tmp_path / "sessions",
        project_key=project_key,
        instruction_loader=None,
        store=store,
    )
    internal = "前  中\t后\n尾"
    assert service.rename_session("title-boundary", f"  {internal}  ").title == internal
    with pytest.raises(ValueError):
        service.rename_session("title-boundary", "y" * (SESSION_TITLE_MAX_LENGTH + 1))
    assert store.read_session("title-boundary", expected_project_key=project_key).title == internal


def test_application_replay_status_and_tui_prioritize_title_over_preview(
    tmp_path: Path,
) -> None:
    source, _target, store = _paths(tmp_path)
    project_key = str(source.resolve())
    store.create_session("visible", project_key=project_key, title="权威标题")
    with store.open_writer("visible", expected_project_key=project_key) as writer:
        writer.append_transcript(_user_transcript("visible", "真实首条预览"))

    application, service = _real_application(store, project_key)
    try:
        catalog = application.session_catalog()
        assert catalog[0].title == "权威标题"
        assert catalog[0].preview == "真实首条预览"
        metadata_catalog = application.session_catalog_metadata()
        assert metadata_catalog[0].title == "权威标题"
        assert metadata_catalog[0].preview == "真实首条预览"

        replay = application.session_replay("visible")
        assert replay and replay[0].title == "权威标题"
        assert replay[0].text == "真实首条预览"

        resumed = application.resume_session_for_command("visible")
        assert application.session_replay() == resumed.replay
        status = application.status().to_dict()
        assert status["active_session_title"] == "权威标题"

        tui = UthCodeTUI(application, terminal_output=DummyOutput())
        tui.session_picker.replace(catalog)
        rendered = "".join(text for _style, text in tui._candidate_fragments())
        assert "权威标题" in rendered
        assert "真实首条预览" not in rendered
    finally:
        application.close()


def test_metadata_catalog_reads_existing_first_user_message_without_full_snapshot(
    tmp_path: Path,
) -> None:
    source, _target, store = _paths(tmp_path)
    project_key = str(source.resolve())
    store.create_session("legacy-preview", project_key=project_key)
    first = TranscriptEntry(
        "legacy-preview",
        1,
        "turn-1",
        TranscriptKind.USER_MESSAGE,
        {
            "role": "user",
            "parts": [
                {"type": "text", "text": "首条\n"},
                {"type": "text", "text": "多 part"},
            ],
        },
        semantic_unit_id="turn-1",
    )
    with store.open_writer("legacy-preview", expected_project_key=project_key) as writer:
        assert writer.append_transcript(first).transcript_appended is True

    service = ApplicationSessionService(
        storage_root=store.root,
        project_key=project_key,
        instruction_loader=None,
        store=store,
    )
    service.read_session = lambda *_args, **_kwargs: (_ for _ in ()).throw(  # type: ignore[method-assign]
        AssertionError("catalog metadata must not load a complete Session snapshot")
    )

    catalog = service.list_catalog_metadata()
    assert catalog[0].preview == "首条 多 part"


def test_metadata_catalog_keeps_empty_session_preview_empty(tmp_path: Path) -> None:
    source, _target, store = _paths(tmp_path)
    project_key = str(source.resolve())
    store.create_session("empty-preview", project_key=project_key)

    service = ApplicationSessionService(
        storage_root=store.root,
        project_key=project_key,
        instruction_loader=None,
        store=store,
    )

    catalog = service.list_catalog_metadata()
    assert catalog[0].title is None
    assert catalog[0].preview == ""


def test_application_catalog_can_read_registered_project_and_uses_latest_user_timestamp(
    tmp_path: Path,
) -> None:
    source, target, store = _paths(tmp_path)
    source_key = str(source.resolve())
    target_key = str(target.resolve())
    store.create_session("source-session", project_key=source_key)
    store.create_session("target-session", project_key=target_key)
    target_entries = (
        replace(
            _user_transcript("target-session", "first input")[0],
            turn_id="turn-1",
            semantic_unit_id="turn-1",
            created_at="2026-10-01T00:00:00+00:00",
        ),
        TranscriptEntry(
            "target-session",
            2,
            "turn-2",
            TranscriptKind.ASSISTANT_MESSAGE,
            {"text": "assistant-only semantic unit"},
            created_at="2026-10-02T00:00:00+00:00",
            semantic_unit_id="turn-2",
        ),
        replace(
            _user_transcript("target-session", "latest steering")[0],
            sequence=3,
            turn_id="turn-3",
            kind=TranscriptKind.USER_STEERING,
            semantic_unit_id="turn-3",
            created_at="2026-10-03T00:00:00+00:00",
        ),
        TranscriptEntry(
            "target-session",
            4,
            "turn-4",
            TranscriptKind.ASSISTANT_MESSAGE,
            {"text": "latest assistant-only semantic unit"},
            created_at="2026-10-04T00:00:00+00:00",
            semantic_unit_id="turn-4",
        ),
    )
    with store.open_writer("target-session", expected_project_key=target_key) as writer:
        assert writer.append_transcript(target_entries).transcript_appended is True

    application, _service = _real_application(store, source_key)
    try:
        catalog = application.session_catalog_metadata(project_key=target_key)
        assert [entry.session_id for entry in catalog] == ["target-session"]
        assert catalog[0].created_at
        assert catalog[0].last_user_message_at == "2026-10-03T00:00:00+00:00"

        # A normal read/resume changes last_used_at but is not a user message
        # and must not manufacture a new Recent timestamp.
        with store.open_writer("target-session", expected_project_key=target_key) as writer:
            writer.touch()
        refreshed = application.session_catalog_metadata(project_key=target_key)
        assert refreshed[0].last_user_message_at == "2026-10-03T00:00:00+00:00"
        source_catalog = application.session_catalog_metadata(project_key=source_key)
        assert [entry.session_id for entry in source_catalog] == ["source-session"]
    finally:
        application.close()


def test_first_user_preview_read_does_not_grow_with_appended_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, _target, store = _paths(tmp_path)
    project_key = str(source.resolve())
    session_id = "head-read"
    store.create_session(session_id, project_key=project_key)

    entries = [
        *_user_transcript(session_id, "首条请求"),
        *(
            TranscriptEntry(
                session_id,
                sequence,
                f"turn-{sequence}",
                TranscriptKind.ASSISTANT_MESSAGE,
                {"text": "history " + ("x" * 256)},
                semantic_unit_id=f"turn-{sequence}",
            )
            for sequence in range(2, 200)
        ),
    ]
    with store.open_writer(session_id, expected_project_key=project_key) as writer:
        assert writer.append_transcript(entries).transcript_appended is True

    transcript_path = store.session_path(session_id) / "transcript.jsonl"
    original_open = Path.open
    reads: list[int] = []

    class _ReadMeter:
        def __init__(self, handle: object) -> None:
            self._handle = handle

        def read(self, size: int = -1) -> bytes:
            value = self._handle.read(size)  # type: ignore[attr-defined]
            reads.append(len(value))
            return value

        def __enter__(self) -> "_ReadMeter":
            self._handle.__enter__()  # type: ignore[attr-defined]
            return self

        def __exit__(self, exc_type: object, exc: object, traceback: object) -> object:
            return self._handle.__exit__(exc_type, exc, traceback)  # type: ignore[attr-defined]

        def __getattr__(self, name: str) -> object:
            return getattr(self._handle, name)

    def counting_open(path: Path, mode: str = "r", *args: object, **kwargs: object) -> object:
        handle = original_open(path, mode, *args, **kwargs)
        if path.resolve() == transcript_path.resolve() and mode == "rb":
            return _ReadMeter(handle)
        return handle

    monkeypatch.setattr(Path, "open", counting_open)
    service = ApplicationSessionService(
        storage_root=store.root,
        project_key=project_key,
        instruction_loader=None,
        store=store,
    )
    first_entry = store.read_first_user_entry(
        session_id,
        expected_project_key=project_key,
    )
    first_bytes = sum(reads)
    assert first_entry is not None
    assert first_entry.kind == TranscriptKind.USER_MESSAGE
    assert first_bytes > 0

    with store.open_writer(session_id, expected_project_key=project_key) as writer:
        next_sequence = writer.snapshot.transcript.last_sequence + 1
        appended = tuple(
            TranscriptEntry(
                session_id,
                next_sequence + offset,
                f"turn-more-{offset}",
                TranscriptKind.ASSISTANT_MESSAGE,
                {"text": "more history " + ("y" * 256)},
                semantic_unit_id=f"turn-more-{offset}",
            )
            for offset in range(999)
        )
        assert writer.append_transcript(appended).transcript_appended is True

    reads.clear()
    second_entry = store.read_first_user_entry(
        session_id,
        expected_project_key=project_key,
    )
    second_bytes = sum(reads)
    assert second_entry is not None
    assert second_entry.kind == TranscriptKind.USER_MESSAGE
    assert second_bytes == first_bytes

    catalog = service.list_catalog_metadata()
    assert catalog[0].preview == "首条请求"


def test_metadata_catalog_reads_first_user_message_longer_than_read_block(
    tmp_path: Path,
) -> None:
    source, _target, store = _paths(tmp_path)
    project_key = str(source.resolve())
    session_id = "long-first-user"
    store.create_session(session_id, project_key=project_key)

    first_message = "首条用户消息 " + (
        "x" * (session_files.HISTORY_READ_BLOCK_BYTES + 1_024)
    )
    with store.open_writer(session_id, expected_project_key=project_key) as writer:
        assert writer.append_transcript(_user_transcript(session_id, first_message)).transcript_appended

    transcript_path = store.session_path(session_id) / "transcript.jsonl"
    assert transcript_path.stat().st_size > session_files.HISTORY_READ_BLOCK_BYTES

    service = ApplicationSessionService(
        storage_root=store.root,
        project_key=project_key,
        instruction_loader=None,
        store=store,
    )

    catalog = service.list_catalog_metadata()
    expected = " ".join(first_message.split())[:159] + "…"
    assert catalog[0].title is None
    assert catalog[0].preview == expected
    assert len(catalog[0].preview) == 160
    assert catalog[0].preview != session_id


def test_move_changes_only_authoritative_membership_and_is_target_idempotent(
    tmp_path: Path,
) -> None:
    source, target, store = _paths(tmp_path)
    source_key = str(source.resolve())
    target_key = str(target.resolve())
    store.create_session("move-me", project_key=source_key, title="保留标题")
    tool_reference = store.persist_tool_result("move-me", "非空工具结果 bytes")
    before_tool_result = store.read_tool_result("move-me", tool_reference.ref).content
    metadata_path = store.session_path("move-me") / "metadata.json"
    transcript_path = store.session_path("move-me") / "transcript.jsonl"
    timeline_path = store.session_path("move-me") / "timeline.jsonl"
    tool_results_path = store.session_path("move-me") / "tool-results"
    before_transcript = transcript_path.read_bytes()
    before_timeline = timeline_path.read_bytes()

    source_service = ApplicationSessionService(
        storage_root=tmp_path / "sessions",
        project_key=source_key,
        instruction_loader=None,
        store=store,
    )
    target_service = ApplicationSessionService(
        storage_root=tmp_path / "sessions",
        project_key=target_key,
        instruction_loader=None,
        store=store,
    )

    moved = source_service.move_session("move-me", target_key)
    assert moved.project_key == target_key
    assert source_service.list_sessions() == ()
    assert target_service.list_sessions()[0].session_id == "move-me"
    assert target_service.list_catalog()[0].title == "保留标题"
    assert transcript_path.read_bytes() == before_transcript
    assert timeline_path.read_bytes() == before_timeline
    assert store.read_tool_result("move-me", tool_reference.ref).content == before_tool_result
    assert (tool_results_path / tool_reference.ref / "content.bin").is_file()

    with pytest.raises(SessionOperationError) as source_resume:
        source_service.resume_session_for_command("move-me")
    assert source_resume.value.kind == "unknown"

    # Repeating the same convergent operation through the original source
    # Application must also succeed; it does not rewrite
    # metadata or create a second Session.
    before_metadata = metadata_path.read_bytes()
    repeated = source_service.move_session("move-me", target_key)
    assert repeated == moved
    assert metadata_path.read_bytes() == before_metadata

    other = tmp_path / "other"
    other.mkdir()
    other_service = ApplicationSessionService(
        storage_root=tmp_path / "sessions",
        project_key=str(other.resolve()),
        instruction_loader=None,
        store=store,
    )
    with pytest.raises(SessionOperationError) as other_source:
        other_service.move_session("move-me", str(other.resolve()))
    assert other_source.value.kind == "unknown"

    with target_service.resume_session_for_command("move-me") as resumed:
        assert resumed.session_id == "move-me"
        assert resumed.title == "保留标题"


def test_move_open_idle_session_and_failed_metadata_write_keeps_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, target, store = _paths(tmp_path)
    source_key = str(source.resolve())
    target_key = str(target.resolve())
    store.create_session("busy", project_key=source_key, title="原始")
    service = ApplicationSessionService(
        storage_root=tmp_path / "sessions",
        project_key=source_key,
        instruction_loader=None,
        store=store,
    )
    active = service.resume_session_for_command("busy")
    moved = service.move_session("busy", target_key)
    assert moved.project_key == target_key
    assert service.active_session is None
    assert store.read_session("busy", expected_project_key=target_key).project_key == target_key
    active.close()  # the successful move already released this writer

    store.create_session("rename-failure", project_key=source_key, title="原始")
    metadata_path = store.session_path("rename-failure") / "metadata.json"
    before = metadata_path.read_bytes()

    def fail_write(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated metadata failure")

    import uthcode.integrations.session_files as session_files

    monkeypatch.setattr(session_files, "_atomic_write_json", fail_write)
    with pytest.raises(SessionOperationError) as failed:
        service.rename_session("rename-failure", "新标题")
    assert failed.value.kind == "storage"
    assert metadata_path.read_bytes() == before
    assert store.read_session("rename-failure", expected_project_key=source_key).title == "原始"


def test_move_write_failure_keeps_project_history_title_and_tool_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, target, store = _paths(tmp_path)
    source_key = str(source.resolve())
    target_key = str(target.resolve())
    store.create_session("move-failure", project_key=source_key, title="原始标题")
    with store.open_writer("move-failure", expected_project_key=source_key) as writer:
        writer.append_transcript(_user_transcript("move-failure", "不可丢失的历史"))
        tool_reference = writer.persist_tool_result("非空工具结果 bytes")

    metadata_path = store.session_path("move-failure") / "metadata.json"
    transcript_path = store.session_path("move-failure") / "transcript.jsonl"
    timeline_path = store.session_path("move-failure") / "timeline.jsonl"
    before_metadata = metadata_path.read_bytes()
    before_transcript = transcript_path.read_bytes()
    before_timeline = timeline_path.read_bytes()
    before_tool_result = store.read_tool_result(
        "move-failure",
        tool_reference.ref,
    ).content
    service = ApplicationSessionService(
        storage_root=tmp_path / "sessions",
        project_key=source_key,
        instruction_loader=None,
        store=store,
    )

    def fail_write(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated move metadata failure")

    monkeypatch.setattr(session_files, "_atomic_write_json", fail_write)
    with pytest.raises(SessionOperationError) as failed:
        service.move_session("move-failure", target_key)
    assert failed.value.kind == "storage"
    assert metadata_path.read_bytes() == before_metadata
    assert transcript_path.read_bytes() == before_transcript
    assert timeline_path.read_bytes() == before_timeline
    snapshot = store.read_session("move-failure", expected_project_key=source_key)
    assert snapshot.project_key == source_key
    assert snapshot.title == "原始标题"
    assert service.project_replay("move-failure")[0].text == "不可丢失的历史"
    assert store.read_tool_result("move-failure", tool_reference.ref).content == before_tool_result


def test_replay_projects_only_complete_successful_plans_without_raw_tool_body(
    tmp_path: Path,
) -> None:
    source, _target, store = _paths(tmp_path)
    source_key = str(source.resolve())
    store.create_session("plan-replay", project_key=source_key)
    entries = []
    entries.extend(_user_transcript("plan-replay", "开始"))
    entries.extend(
        transcript_entries_from_message(
            "plan-replay",
            "turn-plan",
            2,
            Message("assistant", (ToolCallPart("plan-1", "ProposePlan", {"plan": "先检查，再验证"}),)),
        )
    )
    entries.extend(
        transcript_entries_from_message(
            "plan-replay",
            "turn-plan",
            3,
            Message("tool", (ToolResultPart("plan-1", "private approval body"),)),
        )
    )
    entries.extend(
        transcript_entries_from_message(
            "plan-replay",
            "turn-malformed",
            4,
            Message("assistant", (ToolCallPart("plan-2", "ProposePlan", {"plan": 7}),)),
        )
    )
    entries.extend(
        transcript_entries_from_message(
            "plan-replay",
            "turn-malformed",
            5,
            Message("tool", (ToolResultPart("plan-2", "malformed private body"),)),
        )
    )
    entries.extend(
        transcript_entries_from_message(
            "plan-replay",
            "turn-pending",
            6,
            Message("assistant", (ToolCallPart("plan-3", "ProposePlan", {"plan": "unfinished"}),)),
        )
    )
    with store.open_writer("plan-replay", expected_project_key=source_key) as writer:
        writer.append_transcript(tuple(entries))

    service = ApplicationSessionService(
        storage_root=tmp_path / "sessions",
        project_key=source_key,
        instruction_loader=None,
        store=store,
    )
    replay = service.project_replay("plan-replay")
    plans = [record for record in replay if record.kind == "plan"]
    assert len(plans) == 1
    assert plans[0].text == "先检查，再验证"
    assert plans[0].tool_name == "ProposePlan"
    serialized = json.dumps([record.to_dict() for record in replay], ensure_ascii=False)
    assert "private approval body" not in serialized
    assert "malformed private body" not in serialized
    assert "unfinished" not in serialized


def test_open_idle_move_failure_keeps_source_writer_and_membership(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, target, store = _paths(tmp_path)
    source_key = str(source.resolve())
    target_key = str(target.resolve())
    store.create_session("active-move-failure", project_key=source_key)
    service = ApplicationSessionService(
        storage_root=tmp_path / "sessions",
        project_key=source_key,
        instruction_loader=None,
        store=store,
    )
    active = service.resume_session_for_command("active-move-failure")

    def fail_write(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated active move metadata failure")

    import uthcode.integrations.session_files as session_files

    monkeypatch.setattr(session_files, "_atomic_write_json", fail_write)
    with pytest.raises(SessionOperationError) as failed:
        service.move_session("active-move-failure", target_key)
    assert failed.value.kind == "storage"
    assert service.active_session is active
    assert active.project_key == source_key
    assert store.read_session(
        "active-move-failure",
        expected_project_key=source_key,
    ).project_key == source_key
    monkeypatch.undo()
    active.close()


def test_move_receipt_is_instance_local_and_same_target_converges_concurrently(
    tmp_path: Path,
) -> None:
    source, target, store = _paths(tmp_path)
    source_key = str(source.resolve())
    target_key = str(target.resolve())
    store.create_session("same-target", project_key=source_key, title="同目标")
    service = ApplicationSessionService(
        storage_root=tmp_path / "sessions",
        project_key=source_key,
        instruction_loader=None,
        store=store,
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(service.move_session, "same-target", target_key)
            for _ in range(2)
        ]
        results = [future.result() for future in futures]
    assert results[0] == results[1]
    assert results[0].project_key == target_key

    restarted_source = ApplicationSessionService(
        storage_root=tmp_path / "sessions",
        project_key=source_key,
        instruction_loader=None,
        store=store,
    )
    with pytest.raises(SessionOperationError) as restarted:
        restarted_source.move_session("same-target", target_key)
    assert restarted.value.kind == "unknown"

    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    unrelated_service = ApplicationSessionService(
        storage_root=tmp_path / "sessions",
        project_key=str(unrelated.resolve()),
        instruction_loader=None,
        store=store,
    )
    with pytest.raises(SessionOperationError) as other_owner:
        unrelated_service.move_session("same-target", target_key)
    assert other_owner.value.kind == "unknown"


def test_move_different_targets_has_one_success_and_one_controlled_failure(
    tmp_path: Path,
) -> None:
    source, target, store = _paths(tmp_path)
    other_target = tmp_path / "other-target"
    other_target.mkdir()
    source_key = str(source.resolve())
    service = ApplicationSessionService(
        storage_root=tmp_path / "sessions",
        project_key=source_key,
        instruction_loader=None,
        store=store,
    )
    store.create_session("different-targets", project_key=source_key)

    def move(target_key: str) -> tuple[str, object]:
        try:
            return "success", service.move_session("different-targets", target_key)
        except SessionOperationError as exc:
            return "error", exc

    target_keys = [str(target.resolve()), str(other_target.resolve())]
    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(move, target_keys))
    assert [kind for kind, _value in outcomes].count("success") == 1
    assert [kind for kind, _value in outcomes].count("error") == 1
    failure = next(value for kind, value in outcomes if kind == "error")
    assert isinstance(failure, SessionOperationError)
    assert failure.kind == "unknown"
    assert store.read_session("different-targets").project_key in target_keys


class _AuthorityApplication:
    def __init__(self, project_key: str) -> None:
        self.project_key = project_key
        self.runtime_context = SimpleNamespace(workdir=Path(project_key))

    def create_run(self) -> object:
        return SimpleNamespace()

    def rename_session(self, session_id: str, title: str) -> SessionMutation:
        return SessionMutation(session_id, self.project_key, title=title)

    def move_session(self, session_id: str, target_project_key: str) -> SessionMutation:
        self.project_key = target_project_key
        return SessionMutation(session_id, target_project_key, title="移动后")

    def session_catalog(self) -> tuple[object, ...]:
        return ()

    def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_bridge_exposes_session_mutation_dtos_and_controlled_errors(
    tmp_path: Path,
) -> None:
    source, target, _store = _paths(tmp_path)
    application = _AuthorityApplication(str(source.resolve()))
    bridge = DesktopBridge(application=application)

    renamed = await bridge.handle_request(
        RequestEnvelope("rename", "session.rename", {"session_id": "s", "title": "命名"})
    )
    assert renamed.ok is True
    assert renamed.result["title"] == "命名"  # type: ignore[index]
    assert renamed.result["session"]["title"] == "命名"  # type: ignore[index]
    assert set(renamed.result["session"]) == {"session_id", "project_key", "title"}  # type: ignore[index]
    assert "instruction_state" not in renamed.result["session"]  # type: ignore[operator]
    assert "schema_version" not in renamed.result["session"]  # type: ignore[operator]
    assert "created_at" not in renamed.result["session"]  # type: ignore[operator]

    moved = await bridge.handle_request(
        RequestEnvelope(
            "move",
            "session.move",
            {"session_id": "s", "target_project_key": str(target)},
        )
    )
    assert moved.ok is True
    assert moved.result["project_key"] == str(target.resolve())  # type: ignore[index]
    assert moved.result["session"]["project_key"] == str(target.resolve())  # type: ignore[index]

    bridge._active_handle = object()
    busy = await bridge.handle_request(
        RequestEnvelope(
            "move-busy",
            "session.move",
            {"session_id": "s", "target_project_key": str(target)},
        )
    )
    assert busy.ok is False
    assert busy.error is not None and busy.error.kind == "turn_active"
    bridge._active_handle = None

    invalid = await bridge.handle_request(
        RequestEnvelope(
            "move-invalid",
            "session.move",
            {"session_id": "s", "target_project_key": str(tmp_path / "missing")},
        )
    )
    assert invalid.ok is False
    assert invalid.error is not None and invalid.error.kind == "project_not_found"
    await bridge.shutdown()


@pytest.mark.asyncio
async def test_real_bridge_maps_application_membership_busy_and_storage_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, target, store = _paths(tmp_path)
    source_key = str(source.resolve())
    target_key = str(target.resolve())
    store.create_session("bridge-real", project_key=source_key, title="真实")
    application, service = _real_application(store, source_key)
    bridge = DesktopBridge(application=application)
    try:
        moved = await bridge.handle_request(
            RequestEnvelope(
                "real-move",
                "session.move",
                {"session_id": "bridge-real", "target_project_key": target_key},
            )
        )
        assert moved.ok is True
        assert moved.result["session"]["project_key"] == target_key  # type: ignore[index]
        moved_again = await bridge.handle_request(
            RequestEnvelope(
                "real-move-retry",
                "session.move",
                {"session_id": "bridge-real", "target_project_key": target_key},
            )
        )
        assert moved_again.ok is True
        assert moved_again.result == moved.result

        source_resume = await bridge.handle_request(
            RequestEnvelope("source-resume", "session.resume", {"session_id": "bridge-real"})
        )
        assert source_resume.ok is False
        assert source_resume.error is not None and source_resume.error.kind == "session_unknown"

        invalid_target = await bridge.handle_request(
            RequestEnvelope(
                "invalid-target",
                "session.move",
                {"session_id": "bridge-real", "target_project_key": str(tmp_path / "missing")},
            )
        )
        assert invalid_target.ok is False
        assert invalid_target.error is not None and invalid_target.error.kind == "project_not_found"

        store.create_session("bridge-busy", project_key=source_key, title="忙碌")
        active = application.resume_session_for_command("bridge-busy")
        bridge._active_handle = object()
        busy = await bridge.handle_request(
            RequestEnvelope(
                "busy-move-active-turn",
                "session.move",
                {"session_id": "bridge-busy", "target_project_key": target_key},
            )
        )
        assert busy.ok is False
        assert busy.error is not None and busy.error.kind == "turn_active"
        bridge._active_handle = None
        active.close()

        store.create_session("bridge-failure", project_key=source_key, title="失败前")
        metadata_path = store.session_path("bridge-failure") / "metadata.json"
        before_metadata = metadata_path.read_bytes()

        def fail_write(*_args: object, **_kwargs: object) -> None:
            raise OSError("simulated bridge move failure")

        monkeypatch.setattr(session_files, "_atomic_write_json", fail_write)
        failed = await bridge.handle_request(
            RequestEnvelope(
                "failed-move",
                "session.move",
                {"session_id": "bridge-failure", "target_project_key": target_key},
            )
        )
        assert failed.ok is False
        assert failed.error is not None and failed.error.kind == "session_error"
        assert metadata_path.read_bytes() == before_metadata
        assert service.read_session("bridge-failure").project_key == source_key
    finally:
        await bridge.shutdown()
