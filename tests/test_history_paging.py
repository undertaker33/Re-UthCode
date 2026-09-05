from __future__ import annotations

from pathlib import Path
import json

import pytest

from uthcode.application.sessions import ApplicationSessionService
from uthcode.core.history import TranscriptEntry, TranscriptKind
from uthcode.core.provider import Message, ReasoningPart, TextPart
from uthcode.integrations.session_files import SessionCorruptError, SessionFileStore


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
