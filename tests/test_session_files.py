from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from uthcode.core.history import CanonicalHistory, HistoryKind, RuntimeLogEntry
from uthcode.integrations.session_files import (
    HistoryAppendOutcome,
    SessionBusyError,
    SessionCorruptError,
    SessionFileError,
    SessionFileStore,
    SessionWriter,
)


def _entries() -> tuple:
    history = CanonicalHistory("session-1")
    history = history.append(
        turn_id="turn-1",
        kind=HistoryKind.USER_MESSAGE,
        payload={"text": "inspect"},
    )
    history = history.append(
        turn_id="turn-1",
        kind=HistoryKind.TOOL_CALL,
        payload={"tool_call_id": "call-1", "name": "ReadFile"},
    )
    history = history.append(
        turn_id="turn-1",
        kind=HistoryKind.TOOL_RESULT,
        payload={"tool_call_id": "call-1", "content": "ok"},
    )
    return history.entries, history


def _entry_after(entries: tuple, *, kind: HistoryKind, payload: dict) -> object:
    history = CanonicalHistory("session-1", entries)
    return history.append(turn_id="turn-2", kind=kind, payload=payload).entries[-1]


def test_session_layout_durable_append_projection_and_runtime_boundary(tmp_path: Path) -> None:
    store = SessionFileStore(tmp_path / "sessions")
    metadata = store.create_session(
        "session-1",
        project_key="project-1",
        instruction_state={
            "activated_directory_scopes": [str(tmp_path / "project" / "src")],
            "instruction_epoch": 2,
            "stable_prefix_fingerprint": "hash",
            "source_fingerprints": [["id", "path", "directory", "content-hash"]],
            "change_reason": "instruction_scope_added",
        },
    )
    assert metadata.session_id == "session-1"
    session_dir = tmp_path / "sessions" / "session-1"
    assert {"metadata.json", "history.jsonl", "runtime.jsonl", "writer.lock", "tool-results"} <= {
        item.name for item in session_dir.iterdir()
    }

    entries, history = _entries()
    with store.open_writer("session-1", expected_project_key="project-1") as writer:
        writer.append_history(entries)
        writer.append_projection(history.project(revision=1))
        writer.append_runtime(RuntimeLogEntry("stream_delta", {"text": "partial"}))

    recovered = store.read_session("session-1", expected_project_key="project-1")
    assert recovered.history.entries == entries
    assert recovered.projection is not None
    assert recovered.runtime_log.entries[0].kind == "stream_delta"
    assert recovered.last_record_sequence == 4
    assert "AGENTS" not in json.dumps(recovered.metadata.to_dict(), ensure_ascii=False)

    (session_dir / "runtime.jsonl").unlink()
    without_runtime = store.read_session("session-1", expected_project_key="project-1")
    assert without_runtime.history == recovered.history
    assert without_runtime.projection == recovered.projection
    assert without_runtime.runtime_log.entries == ()


def test_append_history_reports_durable_when_post_append_touch_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = SessionFileStore(tmp_path / "sessions")
    store.create_session("session-1", project_key="project-1")
    entries, _history = _entries()
    touch_calls = 0
    original_touch = SessionWriter.touch

    def fail_first_touch(self: SessionWriter):
        nonlocal touch_calls
        touch_calls += 1
        if touch_calls == 1:
            raise OSError("injected post-append metadata touch failure")
        return original_touch(self)

    monkeypatch.setattr(SessionWriter, "touch", fail_first_touch)
    with store.open_writer("session-1") as writer:
        outcome = writer.append_history(entries[:1])
        assert isinstance(outcome, HistoryAppendOutcome)
        assert outcome.history_appended is True
        assert outcome.durability == "durable"
        assert outcome.reload_succeeded is True
        assert outcome.metadata_synced is False
        assert outcome.failure_stage == "history_metadata_sync"
        assert outcome.snapshot.history.entries == entries[:1]
        assert writer.snapshot.history.entries == entries[:1]

    assert store.read_session("session-1").history.entries == entries[:1]


def test_append_history_reconciles_post_append_reload_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = SessionFileStore(tmp_path / "sessions")
    store.create_session("session-1", project_key="project-1")
    entries, _history = _entries()
    reload_calls = 0
    original_reload = SessionWriter._reload

    def fail_first_reload(self: SessionWriter, *, touch: bool):
        nonlocal reload_calls
        reload_calls += 1
        if reload_calls == 1:
            raise OSError("injected post-append reload failure")
        return original_reload(self, touch=touch)

    monkeypatch.setattr(SessionWriter, "_reload", fail_first_reload)
    with store.open_writer("session-1") as writer:
        outcome = writer.append_history(entries[:1])
        assert outcome.history_appended is True
        assert outcome.durability == "durable"
        assert outcome.reload_succeeded is False
        assert outcome.metadata_synced is True
        assert outcome.failure_stage == "history_reload"
        assert writer.snapshot.history.entries == entries[:1]

    assert store.read_session("session-1").history.entries == entries[:1]


def test_append_history_reports_unknown_when_post_append_reconciliation_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = SessionFileStore(tmp_path / "sessions")
    store.create_session("session-1", project_key="project-1")
    entries, _history = _entries()

    def fail_reload(self: SessionWriter, *, touch: bool):
        raise OSError("injected reload failure")

    def fail_load(*args: object, **kwargs: object):
        raise OSError("injected reconciliation read failure")

    monkeypatch.setattr(SessionWriter, "_reload", fail_reload)
    history_path = tmp_path / "sessions" / "session-1" / "history.jsonl"
    with store.open_writer("session-1") as writer:
        monkeypatch.setattr(store, "_load_snapshot", fail_load)
        outcome = writer.append_history(entries[:1])
        assert outcome.history_appended is False
        assert outcome.durability == "unknown"
        assert outcome.failure_stage == "history_durability_unknown"
        assert writer.durability_unknown is True
        with pytest.raises(SessionFileError, match="durability is unknown"):
            writer.append_history(entries[:1])
        with pytest.raises(SessionFileError, match="durability is unknown"):
            writer.append_projection(_history.project(revision=1))
        assert history_path.read_bytes().splitlines()


def test_tail_recovery_repairs_before_next_append_and_middle_damage_fails_closed(tmp_path: Path) -> None:
    store = SessionFileStore(tmp_path / "sessions")
    store.create_session("session-1", project_key="project-1")
    entries, _history = _entries()
    with store.open_writer("session-1") as writer:
        writer.append_history(entries[:1])

    history_path = tmp_path / "sessions" / "session-1" / "history.jsonl"
    with history_path.open("ab") as handle:
        handle.write(b'{"schema_version":1,"kind":"interaction"')
    recovered = store.read_session("session-1")
    assert recovered.history.last_sequence == 1
    assert "ignored_incomplete_tail" in recovered.recovery_diagnostics

    with store.open_writer("session-1") as writer:
        writer.append_history(entries[1:])
    assert store.read_session("session-1").history.last_sequence == 3

    lines = history_path.read_bytes().splitlines(keepends=True)
    lines[1] = b"not-json\n"
    history_path.write_bytes(b"".join(lines))
    with pytest.raises(SessionCorruptError, match="corrupt middle record"):
        store.read_session("session-1")


def test_incomplete_semantic_unit_in_middle_fails_closed_without_truncation(tmp_path: Path) -> None:
    store = SessionFileStore(tmp_path / "sessions")
    store.create_session("session-1", project_key="project-1")
    entries, _history = _entries()
    with store.open_writer("session-1") as writer:
        writer.append_history(entries[:2])

    later_user = _entry_after(
        entries[:2],
        kind=HistoryKind.USER_MESSAGE,
        payload={"text": "later user"},
    )
    history_path = tmp_path / "sessions" / "session-1" / "history.jsonl"
    with history_path.open("ab") as handle:
        handle.write(
            (
                json.dumps(
                    {
                        "schema_version": 1,
                        "kind": "interaction",
                        "sequence": 3,
                        "entry": later_user.to_dict(),
                    },
                    sort_keys=True,
                )
                + "\n"
            ).encode("utf-8")
        )
    before = history_path.read_bytes()

    with pytest.raises(SessionCorruptError, match="incomplete semantic unit in the middle"):
        store.read_session("session-1")
    writer = store.open_writer("session-1")
    try:
        with pytest.raises(SessionCorruptError, match="incomplete semantic unit in the middle"):
            writer.__enter__()
    finally:
        writer.close()
    assert history_path.read_bytes() == before


def test_incomplete_semantic_tail_is_diagnosed_and_writer_repairs_only_the_tail(tmp_path: Path) -> None:
    store = SessionFileStore(tmp_path / "sessions")
    store.create_session("session-1", project_key="project-1")
    entries, _history = _entries()
    with store.open_writer("session-1") as writer:
        writer.append_history(entries[:2])

    history_path = tmp_path / "sessions" / "session-1" / "history.jsonl"
    recovered = store.read_session("session-1")
    assert recovered.history.last_sequence == 1
    assert "ignored_incomplete_semantic_tail" in recovered.recovery_diagnostics

    with store.open_writer("session-1"):
        pass
    assert len(history_path.read_bytes().splitlines()) == 1
    assert store.read_session("session-1").history.last_sequence == 1


def test_append_rejects_unrelated_entry_after_pending_tool_call_without_writing(tmp_path: Path) -> None:
    store = SessionFileStore(tmp_path / "sessions")
    store.create_session("session-1", project_key="project-1")
    entries, _history = _entries()
    later_user = _entry_after(
        entries[:2],
        kind=HistoryKind.USER_MESSAGE,
        payload={"text": "unrelated"},
    )
    history_path = tmp_path / "sessions" / "session-1" / "history.jsonl"
    with store.open_writer("session-1") as writer:
        writer.append_history(entries[:2])
        before = history_path.read_bytes()
        with pytest.raises(SessionFileError, match="matching ToolResult"):
            writer.append_history(later_user)
        assert history_path.read_bytes() == before


def test_append_rejects_mismatched_tool_result_without_writing_then_accepts_matching_result(tmp_path: Path) -> None:
    store = SessionFileStore(tmp_path / "sessions")
    store.create_session("session-1", project_key="project-1")
    entries, _history = _entries()
    mismatched = _entry_after(
        entries[:2],
        kind=HistoryKind.TOOL_RESULT,
        payload={"tool_call_id": "call-2", "content": "wrong"},
    )
    history_path = tmp_path / "sessions" / "session-1" / "history.jsonl"
    with store.open_writer("session-1") as writer:
        writer.append_history(entries[:2])
        before = history_path.read_bytes()
        with pytest.raises(SessionFileError, match="does not match"):
            writer.append_history(mismatched)
        assert history_path.read_bytes() == before
        writer.append_history(entries[2])
        assert writer.snapshot.history.last_sequence == 3


def test_projection_after_incomplete_unit_fails_closed_without_truncation(tmp_path: Path) -> None:
    store = SessionFileStore(tmp_path / "sessions")
    store.create_session("session-1", project_key="project-1")
    entries, _history = _entries()
    with store.open_writer("session-1") as writer:
        writer.append_history(entries[:2])

    projection = CanonicalHistory("session-1", entries[:1]).project(revision=1)
    history_path = tmp_path / "sessions" / "session-1" / "history.jsonl"
    with history_path.open("ab") as handle:
        handle.write(
            (
                json.dumps(
                    {
                        "schema_version": 1,
                        "kind": "projection",
                        "sequence": 3,
                        "projection": projection.to_dict(),
                    },
                    sort_keys=True,
                )
                + "\n"
            ).encode("utf-8")
        )
    before = history_path.read_bytes()

    with pytest.raises(SessionCorruptError, match="Projection follows"):
        store.read_session("session-1")
    assert history_path.read_bytes() == before


def test_writer_can_append_a_tool_pair_across_one_process_boundary(tmp_path: Path) -> None:
    store = SessionFileStore(tmp_path / "sessions")
    store.create_session("session-1", project_key="project-1")
    entries, _history = _entries()
    with store.open_writer("session-1") as writer:
        writer.append_history(entries[:2])
        assert writer.snapshot.history.last_sequence == 2
        assert not any(unit.contains_tool_pair for unit in writer.snapshot.history.complete_semantic_units())
        writer.append_history(entries[2])
    recovered = store.read_session("session-1")
    assert recovered.history.last_sequence == 3
    assert recovered.history.complete_semantic_units()


def test_unknown_record_kind_and_busy_writer_fail_closed(tmp_path: Path) -> None:
    store = SessionFileStore(tmp_path / "sessions")
    store.create_session("session-1", project_key="project-1")
    writer = store.open_writer("session-1")
    writer.__enter__()
    try:
        competing = store.open_writer("session-1")
        with pytest.raises(SessionBusyError, match="session busy"):
            competing.__enter__()
        competing.close()
    finally:
        writer.close()

    entries, _history = _entries()
    with store.open_writer("session-1") as handle:
        handle.append_history(entries[:1])
    path = tmp_path / "sessions" / "session-1" / "history.jsonl"
    value = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    value["kind"] = "future_kind"
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")
    with pytest.raises(SessionCorruptError, match="unknown Session record kind"):
        store.read_session("session-1")


def test_second_process_cannot_resume_same_session(tmp_path: Path) -> None:
    store = SessionFileStore(tmp_path / "sessions")
    store.create_session("session-1", project_key="project-1")
    script = (
        "import sys,time; "
        "from uthcode.integrations.session_files import SessionFileStore; "
        "s=SessionFileStore(sys.argv[1]); "
        "w=s.open_writer('session-1', expected_project_key='project-1'); "
        "w.__enter__(); print('ready', flush=True); time.sleep(2); w.close()"
    )
    child = subprocess.Popen(
        [sys.executable, "-c", script, str(tmp_path / "sessions")],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert child.stdout is not None
        deadline = time.time() + 10
        line = ""
        while time.time() < deadline and line.strip() != "ready":
            line = child.stdout.readline()
        assert line.strip() == "ready"
        with pytest.raises(SessionBusyError):
            with store.open_writer("session-1", expected_project_key="project-1"):
                pass
    finally:
        child.wait(timeout=10)
    assert child.returncode == 0, (child.stderr.read() if child.stderr is not None else "")


def test_catalog_filters_project_and_uses_durable_last_used_not_mtime(tmp_path: Path) -> None:
    store = SessionFileStore(tmp_path / "sessions")
    store.create_session("old", project_key="project-1")
    time.sleep(0.01)
    store.create_session("new", project_key="project-1")
    store.create_session("other", project_key="project-2")
    metadata_path = tmp_path / "sessions" / "old" / "metadata.json"
    os.utime(metadata_path, (time.time() + 1000, time.time() + 1000))

    values = store.list_metadata(project_key="project-1")
    assert [item.session_id for item in values] == ["new", "old"]
    assert all(item.project_key == "project-1" for item in values)
