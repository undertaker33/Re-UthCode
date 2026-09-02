from __future__ import annotations

import json
from pathlib import Path

import pytest

from uthcode.application.sessions import ApplicationSessionService
from uthcode.core.history import ActiveCheckpoint, SemanticEntry, TranscriptEntry, TranscriptKind, TranscriptRef
from uthcode.core.provider import Message, ReasoningPart, TextPart, ToolCallPart, ToolResultPart
from uthcode.integrations import session_files
from uthcode.integrations.session_files import (
    SessionBusyError,
    SessionCorruptError,
    SessionDurabilityUnknownError,
    SessionFileError,
    SessionFileStore,
    SessionIncompatibleError,
    SessionMetadata,
    SessionNotFoundError,
)


def _entries(session_id: str = "session-1") -> tuple[TranscriptEntry, ...]:
    return (
        TranscriptEntry(session_id, 1, "turn-1", TranscriptKind.USER_MESSAGE, {"text": "hello"}, semantic_unit_id="turn-1"),
        TranscriptEntry(session_id, 2, "turn-2", TranscriptKind.TOOL_CALL, {"type": "tool_call", "tool_call_id": "call-1", "name": "read"}, semantic_unit_id="turn-2"),
        TranscriptEntry(session_id, 3, "turn-2", TranscriptKind.TOOL_RESULT, {"type": "tool_result", "tool_call_id": "call-1", "content": "done"}, semantic_unit_id="turn-2"),
    )


def test_session_v3_layout_preserves_transcript_and_timeline(tmp_path: Path) -> None:
    store = SessionFileStore(tmp_path / "sessions")
    store.create_session("session-1", project_key="project")
    path = store.session_path("session-1")
    assert {item.name for item in path.iterdir()} == {"metadata.json", "transcript.jsonl", "timeline.jsonl", "writer.lock", "tool-results"}
    assert json.loads((path / "metadata.json").read_text(encoding="utf-8"))["schema_version"] == 3
    assert not (path / "history.jsonl").exists()
    entries = _entries()
    with store.open_writer("session-1", expected_project_key="project") as writer:
        transcript_outcome = writer.append_transcript(entries)
        assert transcript_outcome.transcript_appended is True
        fine = SemanticEntry("turn-2", "tool work complete", (writer.snapshot.transcript.reference(2, 3),), session_id="session-1")
        timeline_outcome = writer.append_timeline_transaction((fine,), ActiveCheckpoint("turn-2", ("turn-2",), session_id="session-1"))
        assert timeline_outcome.timeline_appended is True
    recovered = store.read_session("session-1", expected_project_key="project")
    assert recovered.transcript.entries == entries
    assert recovered.timeline.fine_entries[0].summary == "tool work complete"
    assert recovered.timeline.active_checkpoint is not None


def test_session_jsonl_preserves_chinese_user_assistant_reasoning_and_tool_text(tmp_path: Path) -> None:
    store = SessionFileStore(tmp_path / "sessions")
    store.create_session("unicode", project_key="中文项目")
    entries = (
        TranscriptEntry("unicode", 1, "turn-中文", TranscriptKind.USER_MESSAGE, {"role": "user", "part": TextPart("你好").to_dict()}, semantic_unit_id="turn-中文"),
        TranscriptEntry("unicode", 2, "turn-中文", TranscriptKind.ASSISTANT_MESSAGE, {"role": "assistant", "part": ReasoningPart("正在分析中文输入").to_dict()}, semantic_unit_id="turn-中文"),
        TranscriptEntry("unicode", 3, "turn-中文", TranscriptKind.ASSISTANT_MESSAGE, {"role": "assistant", "part": TextPart("你好，这是中文回答。").to_dict()}, semantic_unit_id="turn-中文"),
        TranscriptEntry("unicode", 4, "turn-中文", TranscriptKind.TOOL_CALL, {"role": "assistant", "part": ToolCallPart("call-中文", "读取", {}).to_dict()}, semantic_unit_id="turn-中文"),
        TranscriptEntry("unicode", 5, "turn-中文", TranscriptKind.TOOL_RESULT, {"role": "tool", "part": ToolResultPart("call-中文", "工具执行完成").to_dict()}, semantic_unit_id="turn-中文"),
    )
    with store.open_writer("unicode", expected_project_key="中文项目") as writer:
        writer.append_transcript(entries)
        summary = SemanticEntry("turn-中文", "工具摘要：执行成功", (writer.snapshot.transcript.reference(1, 5),), session_id="unicode")
        writer.append_timeline_transaction((summary,), ActiveCheckpoint("turn-中文", ("turn-中文",), session_id="unicode"))
    # A fresh store instance models the post-restart reader and ensures the
    # persisted UTF-8 payload, rather than an in-process cache, is authoritative.
    restarted_store = SessionFileStore(tmp_path / "sessions")
    recovered = restarted_store.read_session("unicode", expected_project_key="中文项目")
    assert recovered.transcript.entries == entries
    assert recovered.timeline.fine_entries[0].summary == "工具摘要：执行成功"
    replay = ApplicationSessionService(storage_root=tmp_path / "sessions", project_key="中文项目", instruction_loader=None, store=restarted_store).project_replay("unicode", tool_summary=lambda part: f"工具摘要：{part.name}")
    assert [(record.kind, record.text) for record in replay] == [
        ("user", "你好"),
        ("reasoning", "正在分析中文输入"),
        ("assistant", "你好，这是中文回答。"),
        ("tool", "工具摘要：读取"),
    ]
    raw = (store.session_path("unicode") / "transcript.jsonl").read_bytes()
    decoded = raw.decode("utf-8", errors="strict")
    assert "你好" in decoded
    assert "正在分析中文输入" in decoded
    assert "工具执行完成" in decoded


def test_session_v3_reads_legacy_full_message_payload_without_rewriting(tmp_path: Path) -> None:
    store = SessionFileStore(tmp_path / "sessions")
    store.create_session("legacy", project_key="project")
    message = Message("assistant", (ReasoningPart("plan"), TextPart("answer")))
    legacy_entry = TranscriptEntry(
        "legacy",
        1,
        "turn-legacy",
        TranscriptKind.ASSISTANT_MESSAGE,
        {
            "type": "reasoning",
            "text": "plan",
            "message_id": "turn-legacy:1",
            "message": message.to_dict(),
        },
        semantic_unit_id="turn-legacy",
    )
    path = store.session_path("legacy") / "transcript.jsonl"
    session_files._append_jsonl(
        path,
        (
            {
                "schema_version": 2,
                "kind": "transcript",
                "sequence": 1,
                "entry": legacy_entry.to_dict(),
            },
        ),
    )
    before_bytes = path.read_bytes()
    before_mtime = path.stat().st_mtime_ns

    recovered = store.read_session("legacy")

    assert recovered.transcript.entries == (legacy_entry,)
    assert path.read_bytes() == before_bytes
    assert path.stat().st_mtime_ns == before_mtime


def test_timeline_trailing_derived_record_is_not_logically_committed(tmp_path: Path) -> None:
    store = SessionFileStore(tmp_path / "sessions")
    store.create_session("session-1", project_key="project")
    entries = _entries()
    with store.open_writer("session-1") as writer:
        writer.append_transcript(entries)
        fine = SemanticEntry("turn-1", "first", (writer.snapshot.transcript.reference(1, 1),), session_id="session-1")
        writer.append_timeline_transaction((fine,), ActiveCheckpoint("turn-1", ("turn-1",), session_id="session-1"))
    trailing = SemanticEntry("turn-2", "crashed before checkpoint", (store.read_session("session-1").transcript.reference(2, 3),), session_id="session-1")
    session_files._append_jsonl(path := store.session_path("session-1") / "timeline.jsonl", ({"schema_version": 2, "kind": "timeline", "sequence": 3, "record": trailing.to_dict()},))
    recovered = store.read_session("session-1")
    assert recovered.timeline.trailing_records == (trailing,)
    assert recovered.timeline.committed_records[-1].record_type == "active_checkpoint"
    before_committed = tuple(record.summary for record in recovered.timeline.committed_records if isinstance(record, SemanticEntry))

    with store.open_writer("session-1") as writer:
        fresh = SemanticEntry(
            "turn-3",
            "fresh",
            (writer.snapshot.transcript.reference(1, 1),),
            session_id="session-1",
        )
        outcome = writer.append_timeline_transaction(
            (fresh,),
            ActiveCheckpoint("turn-3", ("turn-3",), session_id="session-1"),
        )
        assert outcome.timeline_appended is True

    after = store.read_session("session-1")
    assert tuple(record.summary for record in after.timeline.committed_records if isinstance(record, SemanticEntry)) == (*before_committed, "fresh")
    assert after.timeline.trailing_records == (trailing,)
    with store.open_writer("session-1"):
        reopened = store.read_session("session-1")
    assert tuple(record.summary for record in reopened.timeline.committed_records if isinstance(record, SemanticEntry)) == (*before_committed, "fresh")
    assert reopened.timeline.trailing_records == (trailing,)


@pytest.mark.parametrize("version", (1, 2))
def test_pre_v3_session_is_explicitly_incompatible_without_migration(tmp_path: Path, version: int) -> None:
    store = SessionFileStore(tmp_path / "sessions")
    store.create_session("old", project_key="project")
    metadata_path = store.session_path("old") / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["schema_version"] = version
    fixture = json.dumps(metadata, sort_keys=True)
    metadata_path.write_text(fixture, encoding="utf-8")
    with pytest.raises(SessionIncompatibleError, match="incompatible"):
        store.read_session("old")
    assert metadata_path.read_text(encoding="utf-8") == fixture


def test_unknown_durability_quarantines_writer_until_reopen(tmp_path: Path) -> None:
    store = SessionFileStore(tmp_path / "sessions")
    store.create_session("session-1", project_key="project")
    with store.open_writer("session-1") as writer:
        writer.quarantine_unknown_durability()
        with pytest.raises(SessionDurabilityUnknownError):
            writer.append_transcript(_entries()[:1])
    with store.open_writer("session-1") as writer:
        assert writer.durability_unknown is False
        assert writer.append_transcript(_entries()[:1]).transcript_appended is True


def test_non_tool_open_continuation_is_rejected_before_any_write(tmp_path: Path) -> None:
    store = SessionFileStore(tmp_path / "sessions")
    store.create_session("session-1", project_key="project")
    open_message = TranscriptEntry(
        "session-1",
        1,
        "turn-open",
        TranscriptKind.USER_MESSAGE,
        {"text": "partial"},
        commit_boundary=False,
        semantic_unit_id="turn-open",
    )
    path = store.session_path("session-1") / "transcript.jsonl"
    with store.open_writer("session-1") as writer:
        before = writer.snapshot
        with pytest.raises(SessionFileError, match="incomplete"):
            writer.append_transcript(open_message)
        assert writer.snapshot.transcript == before.transcript
        assert path.read_bytes() == b""
    assert store.read_session("session-1").transcript.entries == ()


def test_non_tool_open_continuation_cannot_hide_in_a_matching_tool_pair(tmp_path: Path) -> None:
    store = SessionFileStore(tmp_path / "sessions")
    store.create_session("session-1", project_key="project")
    entries = (
        TranscriptEntry("session-1", 1, "turn-mixed", TranscriptKind.ASSISTANT_MESSAGE, {"text": "partial"}, commit_boundary=False, semantic_unit_id="turn-mixed"),
        TranscriptEntry("session-1", 2, "turn-mixed", TranscriptKind.TOOL_CALL, {"type": "tool_call", "tool_call_id": "call-1", "name": "read"}, semantic_unit_id="turn-mixed"),
        TranscriptEntry("session-1", 3, "turn-mixed", TranscriptKind.TOOL_RESULT, {"type": "tool_result", "tool_call_id": "call-1", "content": "done"}, semantic_unit_id="turn-mixed"),
    )
    path = store.session_path("session-1") / "transcript.jsonl"
    with store.open_writer("session-1") as writer:
        before = writer.snapshot
        with pytest.raises(SessionFileError, match="incomplete"):
            writer.append_transcript(entries)
        assert writer.snapshot.transcript == before.transcript
        assert path.read_bytes() == b""
    assert store.read_session("session-1").transcript.entries == ()


def test_closed_normal_message_is_persisted(tmp_path: Path) -> None:
    store = SessionFileStore(tmp_path / "sessions")
    store.create_session("session-1", project_key="project")
    message = _entries()[:1]
    with store.open_writer("session-1") as writer:
        outcome = writer.append_transcript(message)
        assert outcome.transcript_appended is True
        assert outcome.durability == "durable"
    assert store.read_session("session-1").transcript.entries == message


def test_unmatched_tool_call_can_close_after_writer_reopen_and_mismatch_is_not_written(tmp_path: Path) -> None:
    store = SessionFileStore(tmp_path / "sessions")
    store.create_session("session-1", project_key="project")
    call = TranscriptEntry("session-1", 1, "turn-2", TranscriptKind.TOOL_CALL, {"type": "tool_call", "tool_call_id": "call-1", "name": "read"}, semantic_unit_id="turn-2")
    result = TranscriptEntry("session-1", 2, "turn-2", TranscriptKind.TOOL_RESULT, {"type": "tool_result", "tool_call_id": "call-1", "content": "done"}, semantic_unit_id="turn-2")
    with store.open_writer("session-1") as writer:
        assert writer.append_transcript(call).transcript_appended is True
    with store.open_writer("session-1") as writer:
        assert writer.snapshot.transcript.entries == (call,)
        with pytest.raises(Exception, match="matching ToolResult"):
            writer.append_transcript(_entries()[:1])
        assert writer.append_transcript(result).transcript_appended is True
    recovered = store.read_session("session-1")
    assert recovered.transcript.last_sequence == 2
    assert recovered.transcript.semantic_units(complete_only=True)[0].complete is True


def test_transcript_append_reconciles_when_append_reports_failure_after_data_is_durable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = SessionFileStore(tmp_path / "sessions")
    store.create_session("session-1", project_key="project")
    original_append = session_files._append_jsonl

    def append_then_fail(path: Path, values: object) -> None:
        original_append(path, values)  # type: ignore[arg-type]
        raise OSError("post-fsync failure")

    monkeypatch.setattr(session_files, "_append_jsonl", append_then_fail)
    with store.open_writer("session-1") as writer:
        outcome = writer.append_transcript(_entries()[:1])
        assert outcome.transcript_appended is True
        assert outcome.durability == "durable"
        assert outcome.reload_succeeded is True
        assert outcome.metadata_synced is True
        assert outcome.failure_stage == "transcript_append_reconciled"
    assert store.read_session("session-1").transcript.last_sequence == 1


def test_timeline_append_reconciles_when_append_reports_failure_after_data_is_durable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = SessionFileStore(tmp_path / "sessions")
    store.create_session("session-1", project_key="project")
    original_append = session_files._append_jsonl

    def append_then_fail(path: Path, values: object) -> None:
        original_append(path, values)  # type: ignore[arg-type]
        raise OSError("post-fsync failure")

    with store.open_writer("session-1") as writer:
        writer.append_transcript(_entries()[:1])
        monkeypatch.setattr(session_files, "_append_jsonl", append_then_fail)
        fine = SemanticEntry("timeline-turn", "durable", (writer.snapshot.transcript.reference(1, 1),), session_id="session-1")
        outcome = writer.append_timeline_transaction((fine,), ActiveCheckpoint("timeline-turn", ("timeline-turn",), session_id="session-1"))
        assert outcome.timeline_appended is True
        assert outcome.durability == "durable"
        assert outcome.reload_succeeded is True
        assert outcome.metadata_synced is True
        assert outcome.failure_stage == "timeline_append_reconciled"
    assert store.read_session("session-1").timeline.summary == "durable"


def test_transcript_metadata_sync_failure_still_reports_durable_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = SessionFileStore(tmp_path / "sessions")
    store.create_session("session-1", project_key="project")
    writer = store.open_writer("session-1")
    writer.__enter__()
    original_touch = writer.touch

    def fail_touch() -> object:
        raise OSError("metadata sync failed")

    monkeypatch.setattr(writer, "touch", fail_touch)
    try:
        outcome = writer.append_transcript(_entries()[:1])
        assert outcome.transcript_appended is True
        assert outcome.durability == "durable"
        assert outcome.metadata_synced is False
        assert outcome.reload_succeeded is True
        assert outcome.failure_stage == "transcript_metadata_sync"
    finally:
        monkeypatch.setattr(writer, "touch", original_touch)
        writer.close()
    assert store.read_session("session-1").transcript.last_sequence == 1


def test_timeline_metadata_sync_failure_still_reports_durable_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = SessionFileStore(tmp_path / "sessions")
    store.create_session("session-1", project_key="project")
    writer = store.open_writer("session-1")
    writer.__enter__()
    writer.append_transcript(_entries()[:1])
    original_touch = writer.touch

    def fail_touch() -> object:
        raise OSError("metadata sync failed")

    monkeypatch.setattr(writer, "touch", fail_touch)
    try:
        fine = SemanticEntry("timeline-turn", "durable", (writer.snapshot.transcript.reference(1, 1),), session_id="session-1")
        outcome = writer.append_timeline_transaction((fine,), ActiveCheckpoint("timeline-turn", ("timeline-turn",), session_id="session-1"))
        assert outcome.timeline_appended is True
        assert outcome.durability == "durable"
        assert outcome.metadata_synced is False
        assert outcome.reload_succeeded is True
        assert outcome.failure_stage == "timeline_metadata_sync"
    finally:
        monkeypatch.setattr(writer, "touch", original_touch)
        writer.close()
    assert store.read_session("session-1").timeline.summary == "durable"


def test_transcript_reload_failure_reconciles_from_disk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = SessionFileStore(tmp_path / "sessions")
    store.create_session("session-1", project_key="project")
    with store.open_writer("session-1") as writer:
        original_reload = writer._reload
        calls = 0

        def fail_once(*, touch: bool) -> None:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise OSError("reload failed")
            original_reload(touch=touch)

        monkeypatch.setattr(writer, "_reload", fail_once)
        outcome = writer.append_transcript(_entries()[:1])
        assert outcome.transcript_appended is True
        assert outcome.durability == "durable"
        assert outcome.reload_succeeded is False
        assert outcome.metadata_synced is True
        assert outcome.failure_stage == "transcript_reload"
    assert store.read_session("session-1").transcript.last_sequence == 1


def test_timeline_reload_failure_reconciles_from_disk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = SessionFileStore(tmp_path / "sessions")
    store.create_session("session-1", project_key="project")
    with store.open_writer("session-1") as writer:
        writer.append_transcript(_entries()[:1])
        original_reload = writer._reload
        calls = 0

        def fail_once(*, touch: bool) -> None:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise OSError("reload failed")
            original_reload(touch=touch)

        monkeypatch.setattr(writer, "_reload", fail_once)
        fine = SemanticEntry("timeline-turn", "reloaded", (writer.snapshot.transcript.reference(1, 1),), session_id="session-1")
        outcome = writer.append_timeline_transaction((fine,), ActiveCheckpoint("timeline-turn", ("timeline-turn",), session_id="session-1"))
        assert outcome.timeline_appended is True
        assert outcome.durability == "durable"
        assert outcome.reload_succeeded is False
        assert outcome.metadata_synced is True
        assert outcome.failure_stage == "timeline_reload"
    assert store.read_session("session-1").timeline.summary == "reloaded"


def test_transcript_not_durable_outcome_is_distinguished_from_unknown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = SessionFileStore(tmp_path / "sessions")
    store.create_session("session-1", project_key="project")

    def fail_without_write(path: Path, values: object) -> None:
        raise OSError("append did not reach disk")

    monkeypatch.setattr(session_files, "_append_jsonl", fail_without_write)
    with store.open_writer("session-1") as writer:
        outcome = writer.append_transcript(_entries()[:1])
        assert outcome.transcript_appended is False
        assert outcome.durability == "not_durable"
        assert outcome.reload_succeeded is False
        assert outcome.metadata_synced is False
        assert outcome.failure_stage == "transcript_append"
        assert writer.durability_unknown is False
        assert writer.snapshot.transcript.entries == ()


def test_timeline_not_durable_outcome_is_distinguished_from_unknown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = SessionFileStore(tmp_path / "sessions")
    store.create_session("session-1", project_key="project")

    def fail_without_write(path: Path, values: object) -> None:
        raise OSError("append did not reach disk")

    with store.open_writer("session-1") as writer:
        writer.append_transcript(_entries()[:1])
        monkeypatch.setattr(session_files, "_append_jsonl", fail_without_write)
        fine = SemanticEntry("timeline-turn", "not durable", (writer.snapshot.transcript.reference(1, 1),), session_id="session-1")
        outcome = writer.append_timeline_transaction((fine,), ActiveCheckpoint("timeline-turn", ("timeline-turn",), session_id="session-1"))
        assert outcome.timeline_appended is False
        assert outcome.durability == "not_durable"
        assert outcome.reload_succeeded is False
        assert outcome.metadata_synced is False
        assert outcome.failure_stage == "timeline_append"
        assert writer.durability_unknown is False
        assert writer.snapshot.timeline.records == ()


def test_transcript_unknown_durability_is_reached_from_an_ambiguous_real_append(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = SessionFileStore(tmp_path / "sessions")
    store.create_session("session-1", project_key="project")
    original_append = session_files._append_jsonl

    def append_extra_then_fail(path: Path, values: object) -> None:
        batch = tuple(values)  # type: ignore[arg-type]
        original_append(path, batch)
        extra = dict(batch[-1])
        extra_entry = dict(extra["entry"])
        extra["sequence"] = int(extra["sequence"]) + 1
        extra_entry["sequence"] = int(extra_entry["sequence"]) + 1
        extra_entry["turn_id"] = "ambiguous"
        extra_entry["semantic_unit_id"] = "ambiguous"
        extra["entry"] = extra_entry
        original_append(path, (extra,))
        raise OSError("append outcome is ambiguous")

    monkeypatch.setattr(session_files, "_append_jsonl", append_extra_then_fail)
    with store.open_writer("session-1") as writer:
        outcome = writer.append_transcript(_entries()[:1])
        assert outcome.transcript_appended is False
        assert outcome.durability == "unknown"
        assert outcome.reload_succeeded is False
        assert outcome.metadata_synced is False
        assert outcome.failure_stage == "transcript_durability_unknown"
        assert writer.durability_unknown is True
        with pytest.raises(SessionDurabilityUnknownError):
            writer.append_transcript(
                TranscriptEntry("session-1", 2, "later", TranscriptKind.USER_MESSAGE, {"text": "later"}, semantic_unit_id="later")
            )
    monkeypatch.setattr(session_files, "_append_jsonl", original_append)

    with store.open_writer("session-1") as writer:
        assert writer.durability_unknown is False
        assert writer.snapshot.transcript.last_sequence == 2
        next_entry = TranscriptEntry("session-1", 3, "later", TranscriptKind.USER_MESSAGE, {"text": "later"}, semantic_unit_id="later")
        assert writer.append_transcript(next_entry).transcript_appended is True
    assert store.read_session("session-1").transcript.last_sequence == 3


def test_timeline_unknown_durability_is_reconciled_after_close_and_reopen(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = SessionFileStore(tmp_path / "sessions")
    store.create_session("session-1", project_key="project")
    original_append = session_files._append_jsonl

    def append_extra_then_fail(path: Path, values: object) -> None:
        batch = tuple(values)  # type: ignore[arg-type]
        original_append(path, batch)
        extra_record = dict(batch[0]["record"])
        extra_record["turn_id"] = "ambiguous"
        extra_record["summary"] = "ambiguous"
        extra_record["transaction_id"] = "ambiguous-tx"
        extra = {
            "schema_version": 2,
            "kind": "timeline",
            "sequence": int(batch[-1]["sequence"]) + 1,
            "record": extra_record,
        }
        original_append(path, (extra,))
        raise OSError("append outcome is ambiguous")

    with store.open_writer("session-1") as writer:
        writer.append_transcript(_entries()[:1])
        monkeypatch.setattr(session_files, "_append_jsonl", append_extra_then_fail)
        fine = SemanticEntry("timeline-turn", "expected", (writer.snapshot.transcript.reference(1, 1),), session_id="session-1")
        outcome = writer.append_timeline_transaction((fine,), ActiveCheckpoint("timeline-turn", ("timeline-turn",), session_id="session-1"))
        assert outcome.timeline_appended is False
        assert outcome.durability == "unknown"
        assert outcome.reload_succeeded is False
        assert outcome.metadata_synced is False
        assert outcome.failure_stage == "timeline_durability_unknown"
        assert writer.durability_unknown is True
        with pytest.raises(SessionDurabilityUnknownError):
            writer.append_timeline_transaction(
                (SemanticEntry("later", "blocked", (writer.snapshot.transcript.reference(1, 1),), session_id="session-1"),),
                ActiveCheckpoint("later", ("later",), session_id="session-1"),
            )
    monkeypatch.setattr(session_files, "_append_jsonl", original_append)

    with store.open_writer("session-1") as writer:
        assert writer.durability_unknown is False
        assert writer.snapshot.timeline.trailing_records
        fresh = SemanticEntry("later", "fresh", (writer.snapshot.transcript.reference(1, 1),), session_id="session-1")
        outcome = writer.append_timeline_transaction((fresh,), ActiveCheckpoint("later", ("later",), session_id="session-1"))
        assert outcome.timeline_appended is True
    recovered = store.read_session("session-1")
    assert "fresh" in tuple(record.summary for record in recovered.timeline.committed_records if isinstance(record, SemanticEntry))
    assert "ambiguous" in tuple(record.summary for record in recovered.timeline.trailing_records if isinstance(record, SemanticEntry))


def test_incomplete_byte_tail_is_recovered_and_repaired_by_writer_open(tmp_path: Path) -> None:
    store = SessionFileStore(tmp_path / "sessions")
    store.create_session("session-1", project_key="project")
    with store.open_writer("session-1") as writer:
        writer.append_transcript(_entries()[:1])
    path = store.session_path("session-1") / "transcript.jsonl"
    with path.open("ab") as handle:
        handle.write(b'{"schema_version":2')
    recovered = store.read_session("session-1")
    assert "ignored_incomplete_tail" in recovered.recovery_diagnostics
    with store.open_writer("session-1"):
        pass
    repaired = store.read_session("session-1")
    assert repaired.transcript.last_sequence == 1
    assert "ignored_incomplete_tail" not in repaired.recovery_diagnostics


def test_middle_corruption_fails_closed(tmp_path: Path) -> None:
    store = SessionFileStore(tmp_path / "sessions")
    store.create_session("session-1", project_key="project")
    with store.open_writer("session-1") as writer:
        writer.append_transcript(_entries()[:1])
    path = store.session_path("session-1") / "transcript.jsonl"
    with path.open("ab") as handle:
        handle.write(b"not-json\n")
    with pytest.raises(SessionCorruptError, match="corrupt middle record"):
        store.read_session("session-1")


def test_single_writer_identity_sequence_and_project_checks_fail_closed(tmp_path: Path) -> None:
    store = SessionFileStore(tmp_path / "sessions")
    store.create_session("session-1", project_key="project")
    first = store.open_writer("session-1", expected_project_key="project")
    first.__enter__()
    try:
        second = store.open_writer("session-1", expected_project_key="project")
        with pytest.raises(SessionBusyError):
            second.__enter__()
    finally:
        first.close()
    with pytest.raises(SessionNotFoundError):
        with store.open_writer("session-1", expected_project_key="other"):
            pass
    with store.open_writer("session-1") as writer:
        wrong_session = TranscriptEntry("other", 1, "wrong", TranscriptKind.USER_MESSAGE, {"text": "wrong"}, semantic_unit_id="wrong")
        with pytest.raises(SessionFileError):
            writer.append_transcript(wrong_session)
        wrong_sequence = TranscriptEntry("session-1", 2, "wrong", TranscriptKind.USER_MESSAGE, {"text": "wrong"}, semantic_unit_id="wrong")
        with pytest.raises(SessionFileError):
            writer.append_transcript(wrong_sequence)
        assert writer.snapshot.transcript.entries == ()


def test_timeline_ref_ownership_is_enforced(tmp_path: Path) -> None:
    store = SessionFileStore(tmp_path / "sessions")
    store.create_session("session-1", project_key="project")
    with store.open_writer("session-1") as writer:
        writer.append_transcript(_entries()[:1])
        foreign_ref = TranscriptRef("other-session", 1, 1)
        fine = SemanticEntry("turn-1", "foreign", (foreign_ref,), session_id="session-1")
        with pytest.raises(SessionFileError, match="another Session"):
            writer.append_timeline_transaction((fine,), ActiveCheckpoint("turn-1", ("turn-1",), session_id="session-1"))
        assert writer.snapshot.timeline.records == ()
