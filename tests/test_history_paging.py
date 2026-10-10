from __future__ import annotations

from pathlib import Path
import json

import pytest

from uthcode.application.sessions import ApplicationSessionService
from uthcode.core.history import (
    ActiveCheckpoint,
    SemanticEntry,
    TranscriptEntry,
    TranscriptKind,
    timeline_record_from_dict,
)
from uthcode.core.provider import CancellationToken, GenerationCancelled, Message, ReasoningPart, TextPart
from uthcode.core.provider import ToolCallPart, ToolResultPart
from uthcode.integrations import session_files
from uthcode.integrations.session_files import SessionCorruptError, SessionFileStore, SessionWriter


def _append_units(store: SessionFileStore, session_id: str, count: int) -> None:
    entries: list[TranscriptEntry] = []
    sequence = 1
    for index in range(count):
        unit_id = f"turn-{index:04d}"
        entries.append(
            TranscriptEntry(
                session_id,
                sequence,
                unit_id,
                TranscriptKind.USER_MESSAGE,
                {
                    "role": "user",
                    "part": TextPart(f"message-{index:04d}").to_dict(),
                },
                semantic_unit_id=unit_id,
            )
        )
        sequence += 1
        entries.append(
            TranscriptEntry(
                session_id,
                sequence,
                unit_id,
                TranscriptKind.ASSISTANT_MESSAGE,
                {
                    "role": "assistant",
                    "part": TextPart(f"answer-{index:04d}").to_dict(),
                },
                semantic_unit_id=unit_id,
            )
        )
        sequence += 1
    with store.open_writer(session_id, expected_project_key="project") as writer:
        writer.append_transcript(entries)


def _append_units_to_writer(writer: SessionWriter, start_index: int, count: int) -> None:
    """Append complete text units after the writer's current transcript tail."""

    entries: list[TranscriptEntry] = []
    sequence = writer.snapshot.transcript.last_sequence + 1
    session_id = writer.session_id
    for index in range(start_index, start_index + count):
        unit_id = f"turn-{index:04d}"
        entries.extend(
            (
                TranscriptEntry(
                    session_id,
                    sequence,
                    unit_id,
                    TranscriptKind.USER_MESSAGE,
                    {
                        "role": "user",
                        "part": TextPart(f"message-{index:04d}").to_dict(),
                    },
                    semantic_unit_id=unit_id,
                ),
                TranscriptEntry(
                    session_id,
                    sequence + 1,
                    unit_id,
                    TranscriptKind.ASSISTANT_MESSAGE,
                    {
                        "role": "assistant",
                        "part": TextPart(f"answer-{index:04d}").to_dict(),
                    },
                    semantic_unit_id=unit_id,
                ),
            )
        )
        sequence += 2
    writer.append_transcript(entries)


def _commit_compaction(writer: SessionWriter) -> ActiveCheckpoint:
    end = writer.snapshot.transcript.last_sequence
    turn = writer.snapshot.transcript.entries[-1].turn_id
    summary = SemanticEntry(turn, "summary", (writer.snapshot.transcript.reference(end - 1, end),), session_id=writer.session_id)
    outcome = writer.append_timeline_transaction((summary,), ActiveCheckpoint(turn, (turn,), session_id=writer.session_id))
    assert outcome.timeline_appended
    checkpoint = writer.snapshot.timeline.active_checkpoint
    assert checkpoint is not None
    return checkpoint


def test_compaction_notices_restore_actual_position_and_stable_identity_after_restart(tmp_path: Path) -> None:
    store = SessionFileStore(tmp_path)
    store.create_session("session-1", project_key="project")
    with store.open_writer("session-1", expected_project_key="project") as writer:
        _append_units_to_writer(writer, 0, 1)
        first = _commit_compaction(writer)
        _append_units_to_writer(writer, 1, 1)
        second = _commit_compaction(writer)
        _append_units_to_writer(writer, 2, 1)
    restarted = SessionFileStore(tmp_path)
    service = ApplicationSessionService(storage_root=tmp_path, project_key="project", instruction_loader=None, store=restarted)
    page = service.read_history_page("session-1")
    assert [(record.kind, record.sequence) for record in page.records] == [
        ("user", 1), ("assistant", 2), ("compaction", 2),
        ("user", 3), ("assistant", 4), ("compaction", 4),
        ("user", 5), ("assistant", 6),
    ]
    notices = [record for record in page.records if record.kind == "compaction"]
    assert [record.message_id for record in notices] == [first.transaction_id, second.transaction_id]
    assert all(record.text == "Context compacted" for record in notices)
    assert page.to_dict() == service.read_history_page("session-1").to_dict()
    snapshot = restarted.read_session("session-1")
    assert len(snapshot.transcript.entries) == 6
    assert all("Context compacted" not in str(entry.to_dict()) for entry in snapshot.transcript.entries)
    assert timeline_record_from_dict(second.to_dict()).display_after_sequence == 4

    collected = []
    cursor = None
    while True:
        older = service.read_history_page("session-1", page_size=1, cursor=cursor)
        collected.extend(older.records)
        if not older.has_more:
            break
        cursor = older.next_cursor
    assert len({record.record_id for record in collected}) == len(collected)
    assert {record.record_id for record in collected} == {record.record_id for record in page.records}


def test_history_does_not_publish_uncommitted_or_partial_checkpoint_notice(tmp_path: Path) -> None:
    store = SessionFileStore(tmp_path)
    store.create_session("session-1", project_key="project")
    with store.open_writer("session-1", expected_project_key="project") as writer:
        _append_units_to_writer(writer, 0, 1)
        committed = _commit_compaction(writer)
    path = store.session_path("session-1") / "timeline.jsonl"
    pending = SemanticEntry("pending", "not committed", (), session_id="session-1", transaction_id="pending")
    session_files._append_jsonl(path, [{"schema_version": 2, "kind": "timeline", "sequence": 3, "record": pending.to_dict()}])
    with path.open("ab") as handle:
        handle.write(b'{"schema_version":2,"kind":"timeline","sequence":4,"record":')
    fresh = SessionFileStore(tmp_path)
    page = fresh.read_history_page("session-1")
    assert [record.transaction_id for record in page.compactions] == [committed.transaction_id]
    with fresh.open_writer("session-1", expected_project_key="project") as writer:
        _append_units_to_writer(writer, 1, 1)
        later = _commit_compaction(writer)
    assert [record.transaction_id for record in fresh.read_history_page("session-1").compactions] == [committed.transaction_id, later.transaction_id]


def test_old_checkpoint_without_occurrence_position_is_not_guessed(tmp_path: Path) -> None:
    store = SessionFileStore(tmp_path)
    store.create_session("session-1", project_key="project")
    _append_units(store, "session-1", 2)
    summary = SemanticEntry("turn-0000", "old summary", (), session_id="session-1", transaction_id="old")
    checkpoint = ActiveCheckpoint("turn-0000", ("turn-0000",), session_id="session-1", transaction_id="old")
    session_files._append_jsonl(store.session_path("session-1") / "timeline.jsonl", [
        {"schema_version": 2, "kind": "timeline", "sequence": index, "record": record.to_dict()}
        for index, record in enumerate((summary, checkpoint), 1)
    ])
    assert store.read_history_page("session-1").compactions == ()


def test_older_page_cursor_does_not_rescan_newer_timeline_bytes(tmp_path: Path) -> None:
    store = SessionFileStore(tmp_path)
    store.create_session("session-1", project_key="project")
    with store.open_writer("session-1", expected_project_key="project") as writer:
        _append_units_to_writer(writer, 0, 1)
        _commit_compaction(writer)
        _append_units_to_writer(writer, 1, 4)
    latest = store.read_history_page("session-1", page_size=1)
    baseline = store.read_history_page("session-1", page_size=1, cursor=latest.next_cursor)
    with store.open_writer("session-1", expected_project_key="project") as writer:
        summary = SemanticEntry("turn-0004", "newer summary " * 20_000, (writer.snapshot.transcript.reference(9, 10),), session_id="session-1")
        writer.append_timeline_transaction((summary,), ActiveCheckpoint("turn-0004", ("turn-0004",), session_id="session-1"))
    older = store.read_history_page("session-1", page_size=1, cursor=latest.next_cursor)
    assert older.units == baseline.units
    assert older.compactions == baseline.compactions
    assert older.bytes_read <= baseline.bytes_read
    assert older.bytes_read < (store.session_path("session-1") / "timeline.jsonl").stat().st_size


def test_history_page_returns_recent_complete_units_and_opaque_cursor(tmp_path: Path) -> None:
    store = SessionFileStore(tmp_path)
    store.create_session("session-1", project_key="project", title="Paged")
    _append_units(store, "session-1", 65)

    service = ApplicationSessionService(
        storage_root=tmp_path,
        project_key="project",
        instruction_loader=None,
        store=store,
    )
    first = service.read_history_page("session-1")

    assert first.unit_count == 30
    assert first.has_more is True
    assert first.next_cursor
    assert "session-1" not in first.next_cursor
    assert first.records[0].text == "message-0035"
    assert first.records[-1].text == "answer-0064"
    assert len({record.record_id for record in first.records}) == len(first.records)

    second = service.read_history_page("session-1", cursor=first.next_cursor)
    assert second.unit_count == 30
    assert second.records[0].text == "message-0005"
    assert second.records[-1].text == "answer-0034"
    assert {record.record_id for record in first.records}.isdisjoint(
        record.record_id for record in second.records
    )


def test_history_page_skips_incomplete_tool_tail_and_reads_bounded_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = SessionFileStore(tmp_path)
    store.create_session("session-1", project_key="project")
    _append_units(store, "session-1", 80)
    with store.open_writer("session-1", expected_project_key="project") as writer:
        writer.append_transcript(
            TranscriptEntry(
                "session-1",
                161,
                "turn-incomplete",
                TranscriptKind.TOOL_CALL,
                {
                    "type": "tool_call",
                    "tool_call_id": "call-incomplete",
                    "name": "read",
                },
                semantic_unit_id="turn-incomplete",
            )
        )

    # A page must use the reverse block reader, not Path.read_bytes() for the
    # whole transcript.  The monkeypatch makes that accidental implementation
    # fail loudly while metadata reads remain available.
    monkeypatch.setattr(Path, "read_bytes", lambda _path: (_ for _ in ()).throw(AssertionError("full read")))
    page = store.read_history_page("session-1", page_size=30)

    assert page.units[-1].turn_id == "turn-0079"
    assert all(unit.complete for unit in page.units)
    assert page.bytes_read < (tmp_path / "session-1" / "transcript.jsonl").stat().st_size


def test_session_search_finds_text_older_than_the_default_history_page(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = SessionFileStore(tmp_path)
    store.create_session("session-1", project_key="project")
    _append_units(store, "session-1", 100)
    service = ApplicationSessionService(
        storage_root=tmp_path,
        project_key="project",
        instruction_loader=None,
        store=store,
    )
    service.read_session = lambda *_args, **_kwargs: (_ for _ in ()).throw(  # type: ignore[method-assign]
        AssertionError("search must not materialize the Session transcript")
    )
    page_calls: list[tuple[int, bool, bool]] = []
    original_page = store.read_history_page

    def record_page(session_id: str, **kwargs: object):
        page_calls.append(
            (
                int(kwargs["page_size"]),
                bool(kwargs["include_compactions"]),
                isinstance(kwargs["cancellation"], CancellationToken),
            )
        )
        return original_page(session_id, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(store, "read_history_page", record_page)
    result = service.search_sessions("message-0000")

    assert [hit.session_id for hit in result.hits] == ["session-1"]
    assert "message-0000" in result.hits[0].snippet
    assert len(page_calls) > 30
    assert set(page_calls) == {(1, False, True)}


def test_session_search_cancellation_stops_the_reverse_reader(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = SessionFileStore(tmp_path)
    store.create_session("session-1", project_key="project")
    _append_units(store, "session-1", 50)
    service = ApplicationSessionService(
        storage_root=tmp_path,
        project_key="project",
        instruction_loader=None,
        store=store,
    )
    token = CancellationToken()
    parsed = 0
    original_parse = session_files._history_entry_from_line

    def cancel_after_first_parse(raw: bytes, *, path: Path, session_id: str):
        nonlocal parsed
        parsed += 1
        token.cancel()
        return original_parse(raw, path=path, session_id=session_id)

    monkeypatch.setattr(session_files, "_history_entry_from_line", cancel_after_first_parse)

    with pytest.raises(GenerationCancelled):
        service.search_sessions("no match", cancellation=token)
    assert token.cancelled is True
    assert parsed == 1


def test_history_page_rejects_cursor_for_another_session(tmp_path: Path) -> None:
    store = SessionFileStore(tmp_path)
    store.create_session("session-1", project_key="project")
    store.create_session("session-2", project_key="project")
    _append_units(store, "session-1", 35)
    cursor = store.read_history_page("session-1").next_cursor
    assert cursor

    with pytest.raises(ValueError):
        store.read_history_page("session-2", cursor=cursor)


def test_history_page_validates_envelope_identity_with_entry_sequence(tmp_path: Path) -> None:
    store = SessionFileStore(tmp_path)
    store.create_session("session-1", project_key="project")
    _append_units(store, "session-1", 2)
    path = tmp_path / "session-1" / "transcript.jsonl"
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    lines[-1]["sequence"] = 99
    path.write_text("\n".join(json.dumps(line, separators=(",", ":")) for line in lines) + "\n", encoding="utf-8")

    with pytest.raises(SessionCorruptError):
        store.read_history_page("session-1", page_size=1)


def test_history_page_identity_disambiguates_legacy_multi_part_message(tmp_path: Path) -> None:
    store = SessionFileStore(tmp_path)
    store.create_session("session-1", project_key="project")
    entry = TranscriptEntry(
        "session-1",
        1,
        "turn-1",
        TranscriptKind.ASSISTANT_MESSAGE,
        {
            "message_id": "legacy-message",
            "message": Message(
                "assistant",
                (ReasoningPart("thinking"), TextPart("answer")),
            ).to_dict(),
        },
        semantic_unit_id="turn-1",
    )
    with store.open_writer("session-1", expected_project_key="project") as writer:
        writer.append_transcript(entry)

    service = ApplicationSessionService(
        storage_root=tmp_path,
        project_key="project",
        instruction_loader=None,
        store=store,
    )
    page = service.read_history_page("session-1")
    assert [record.text for record in page.records] == ["thinking", "answer"]
    assert [record.message_id for record in page.records] == ["legacy-message", "legacy-message"]
    assert len({record.record_id for record in page.records}) == 2


def test_history_replays_observed_tool_times_and_only_the_opaque_result_reference(
    tmp_path: Path,
) -> None:
    store = SessionFileStore(tmp_path)
    store.create_session("session-1", project_key="project")
    started_at = "2026-10-10T10:00:00+00:00"
    completed_at = "2026-10-10T10:00:01+00:00"
    external_ref = "opaque-tool-result-ref"
    private_output = "PRIVATE-TOOL-OUTPUT-MUST-NOT-ENTER-REPLAY"
    entries = (
        TranscriptEntry(
            "session-1",
            1,
            "turn-1",
            TranscriptKind.USER_MESSAGE,
            {"role": "user", "message_id": "user-1", "part": TextPart("inspect").to_dict()},
            created_at="2026-10-10T09:59:59+00:00",
            semantic_unit_id="turn-1",
        ),
        TranscriptEntry(
            "session-1",
            2,
            "turn-1",
            TranscriptKind.ASSISTANT_MESSAGE,
            {"role": "assistant", "message_id": "assistant-progress-1", "part": TextPart("I will inspect the file").to_dict()},
            created_at="2026-10-10T10:00:00+00:00",
            semantic_unit_id="turn-1",
        ),
        TranscriptEntry(
            "session-1",
            3,
            "turn-1",
            TranscriptKind.TOOL_CALL,
            {"role": "assistant", "message_id": "assistant-progress-1", "part": ToolCallPart("call-1", "ReadFile", {"path": "notes.txt"}).to_dict()},
            created_at="2026-10-10T10:00:00+00:00",
            semantic_unit_id="turn-1",
        ),
        TranscriptEntry(
            "session-1",
            4,
            "turn-1",
            TranscriptKind.TOOL_RESULT,
            {
                "role": "tool",
                "message_id": "tool-result-1",
                "part": ToolResultPart(
                    "call-1",
                    private_output,
                    metadata={
                        "execution_status": "succeeded",
                        "persistence_status": "externalized",
                        "ref": external_ref,
                        "size_bytes": len(private_output.encode("utf-8")),
                        "sha256": "a" * 64,
                        "observed_started_at": started_at,
                        "observed_completed_at": completed_at,
                    },
                ).to_dict(),
            },
            created_at="2026-10-10T10:00:01+00:00",
            semantic_unit_id="turn-1",
        ),
        TranscriptEntry(
            "session-1",
            5,
            "turn-1",
            TranscriptKind.ASSISTANT_MESSAGE,
            {"role": "assistant", "message_id": "assistant-final-1", "part": TextPart("The file is ready").to_dict()},
            created_at="2026-10-10T10:00:02+00:00",
            semantic_unit_id="turn-1",
        ),
    )
    with store.open_writer("session-1", expected_project_key="project") as writer:
        writer.append_transcript(entries)

    page = ApplicationSessionService(
        storage_root=tmp_path,
        project_key="project",
        instruction_loader=None,
        store=store,
    ).read_history_page("session-1")
    assistants = [record for record in page.records if record.kind == "assistant"]
    tool = next(record for record in page.records if record.kind == "tool")

    assert [(record.message_id, record.assistant_kind) for record in assistants] == [
        ("assistant-progress-1", "progress"),
        ("assistant-final-1", "final"),
    ]
    assert tool.turn_id == "turn-1"
    assert tool.message_id == "assistant-progress-1"
    assert tool.tool_call_id == "call-1"
    assert tool.started_at == started_at
    assert tool.completed_at == completed_at
    assert tool.output_ref == external_ref
    encoded = json.dumps(page.to_dict(), ensure_ascii=False)
    assert private_output not in encoded
    assert external_ref in encoded


def test_history_file_change_summary_uses_only_paired_formal_write_evidence(
    tmp_path: Path,
) -> None:
    store = SessionFileStore(tmp_path)
    store.create_session("session-1", project_key="project")
    digest = "a" * 64
    tool_pairs = (
        ("write", "WriteFile", {"path": "notes/one.txt", "content": "secret payload"}, {
            "execution_status": "succeeded",
            "evidence": "file_change",
            "changed": True,
            "content_digest": digest,
        }),
        ("escape", "EditFile", {"path": "../outside.txt", "old_text": "x", "new_text": "y"}, {
            "execution_status": "succeeded",
            "evidence": "file_change",
            "changed": True,
            "content_digest": digest,
        }),
        ("absolute", "WriteFile", {"path": "C:/outside.txt", "content": "x"}, {
            "execution_status": "succeeded",
            "evidence": "file_change",
            "changed": True,
            "content_digest": digest,
        }),
        ("patch", "ApplyPatch", {"patch": "opaque patch body"}, {
            "side_effect": "partial",
            "applied": ["src/new.py", "../outside.py"],
            "failed": ["src/failed.py"],
            "not_applied": ["src/skipped.py"],
        }),
        ("shell", "Bash", {"command": "echo wrote made-up.txt"}, {
            "execution_status": "succeeded",
            "changed": True,
            "content_digest": digest,
        }),
    )
    entries: list[TranscriptEntry] = [
        TranscriptEntry(
            "session-1",
            1,
            "turn-1",
            TranscriptKind.USER_MESSAGE,
            {"role": "user", "part": TextPart("update files").to_dict()},
            semantic_unit_id="turn-1",
        )
    ]
    sequence = 2
    for call_id, tool_name, arguments, metadata in tool_pairs:
        entries.append(
            TranscriptEntry(
                "session-1",
                sequence,
                "turn-1",
                TranscriptKind.TOOL_CALL,
                {
                    "role": "assistant",
                    "message_id": f"assistant-{call_id}",
                    "part": ToolCallPart(call_id, tool_name, arguments).to_dict(),
                },
                semantic_unit_id="turn-1",
            )
        )
        sequence += 1
        entries.append(
            TranscriptEntry(
                "session-1",
                sequence,
                "turn-1",
                TranscriptKind.TOOL_RESULT,
                {
                    "role": "tool",
                    "part": ToolResultPart(call_id, "private raw result", metadata=metadata).to_dict(),
                },
                semantic_unit_id="turn-1",
            )
        )
        sequence += 1
    with store.open_writer("session-1", expected_project_key="project") as writer:
        writer.append_transcript(entries)

    page = ApplicationSessionService(
        storage_root=tmp_path,
        project_key="project",
        instruction_loader=None,
        store=store,
    ).read_history_page("session-1")
    by_call = {record.tool_call_id: record for record in page.records if record.kind == "tool"}
    assert by_call["write"].file_changes == (
        {"tool_name": "WriteFile", "path": "notes/one.txt", "status": "changed"},
    )
    assert by_call["escape"].file_changes == ()
    assert by_call["absolute"].file_changes == ()
    assert by_call["patch"].file_changes == (
        {
            "tool_name": "ApplyPatch",
            "status": "partial",
            "applied_paths": ("src/new.py",),
            "failed_count": 1,
            "not_applied_count": 1,
        },
    )
    assert by_call["shell"].file_changes == ()
    serialized = json.dumps(page.to_dict(), ensure_ascii=False)
    assert "content_digest" not in serialized
    assert "opaque patch body" not in serialized
    assert "private raw result" not in serialized
    assert "../outside.py" not in serialized


def test_legacy_transcript_without_timestamp_remains_unavailable() -> None:
    raw = TranscriptEntry(
        "session-1",
        1,
        "turn-1",
        TranscriptKind.USER_MESSAGE,
        {"text": "older durable message"},
    ).to_dict()
    raw.pop("created_at")

    restored = TranscriptEntry.from_dict(raw)

    assert restored.created_at is None
