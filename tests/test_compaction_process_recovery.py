from __future__ import annotations

import json
from contextlib import contextmanager
import os
from pathlib import Path
import subprocess
import sys
import textwrap
import time
from typing import Any, Iterator

from uthcode.core.history import (
    ActiveCheckpoint,
    SemanticEntry,
    TranscriptEntry,
    TranscriptKind,
)
from uthcode.integrations.session_files import SessionFileStore


_CHILD_SCRIPT = textwrap.dedent(
    r'''
    from __future__ import annotations

    import json
    import os
    from pathlib import Path
    import sys
    import time

    from uthcode.core.history import ActiveCheckpoint, SemanticEntry, TranscriptEntry, TranscriptKind
    from uthcode.integrations import session_files
    from uthcode.integrations.session_files import SessionFileStore


    def _write_ready(path: Path, stage: str) -> None:
        path.write_text(json.dumps({"pid": os.getpid(), "stage": stage}), encoding="utf-8")


    def _hold_until_forced_exit() -> None:
        time.sleep(3600)


    root = Path(sys.argv[1])
    mode = sys.argv[2]
    ready = Path(sys.argv[3])
    store = SessionFileStore(root)
    store.create_session("session-1", project_key="project")

    with store.open_writer("session-1", expected_project_key="project") as writer:
        entry = TranscriptEntry(
            "session-1",
            1,
            "turn-1",
            TranscriptKind.USER_MESSAGE,
            {"text": "persisted before crash"},
            semantic_unit_id="turn-1",
        )
        if not writer.append_transcript(entry).transcript_appended:
            raise RuntimeError("initial transcript append was not durable")
        reference = writer.snapshot.transcript.reference(1, 1)
        fine = SemanticEntry(
            "turn-1",
            "checkpointed summary",
            (reference,),
            session_id="session-1",
        )
        checkpoint = ActiveCheckpoint("turn-1", ("turn-1",), session_id="session-1")

        if mode == "checkpoint":
            outcome = writer.append_timeline_transaction((fine,), checkpoint)
            if not outcome.timeline_appended:
                raise RuntimeError("timeline checkpoint append was not durable")
            _write_ready(ready, "checkpoint_committed")
            _hold_until_forced_exit()
        elif mode == "tail":
            original_append = session_files._append_jsonl

            def append_derived_then_partial_checkpoint(path: Path, values: object) -> None:
                envelopes = tuple(values)  # type: ignore[arg-type]
                if path.name != "timeline.jsonl" or len(envelopes) != 2:
                    raise RuntimeError("unexpected timeline transaction shape")
                original_append(path, envelopes[:1])
                checkpoint_bytes = (
                    json.dumps(envelopes[1], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                    .encode("utf-8")
                )
                with path.open("ab") as handle:
                    handle.write(checkpoint_bytes[: max(1, len(checkpoint_bytes) // 2)])
                    handle.flush()
                    os.fsync(handle.fileno())
                _write_ready(ready, "derived_written_partial_checkpoint")
                _hold_until_forced_exit()

            session_files._append_jsonl = append_derived_then_partial_checkpoint
            writer.append_timeline_transaction((fine,), checkpoint)
        else:
            raise RuntimeError(f"unknown mode: {mode}")
    '''
)


def _start_crashing_writer(tmp_path: Path, mode: str) -> tuple[subprocess.Popen[str], Path]:
    session_root = tmp_path / "sessions"
    ready_path = tmp_path / f"{mode}-ready.json"
    process = subprocess.Popen(
        [sys.executable, "-c", _CHILD_SCRIPT, str(session_root), mode, str(ready_path)],
        cwd=Path(__file__).resolve().parents[1],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return process, ready_path


@contextmanager
def _crashing_writer(tmp_path: Path, mode: str) -> Iterator[tuple[subprocess.Popen[str], dict[str, Any]]]:
    process, ready_path = _start_crashing_writer(tmp_path, mode)
    try:
        yield process, _wait_for_ready(process, ready_path)
    finally:
        if process.pid == os.getpid():
            raise AssertionError("crash writer unexpectedly has the parent PID")
        if process.poll() is None:
            process.kill()
        process.wait(timeout=10)
        process.communicate(timeout=5)


def _wait_for_ready(process: subprocess.Popen[str], ready_path: Path) -> dict[str, Any]:
    deadline = time.monotonic() + 20.0
    while time.monotonic() < deadline:
        if ready_path.is_file():
            try:
                payload = json.loads(ready_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                time.sleep(0.02)
                continue
            if isinstance(payload, dict):
                return payload
        if process.poll() is not None:
            stdout, stderr = process.communicate(timeout=5)
            raise AssertionError(
                f"crash writer exited before ready: returncode={process.returncode}, "
                f"stdout={stdout!r}, stderr={stderr!r}"
            )
        time.sleep(0.02)
    if process.poll() is None:
        process.kill()
        process.wait(timeout=5)
    stdout, stderr = process.communicate(timeout=5)
    raise AssertionError(f"crash writer did not signal ready: stdout={stdout!r}, stderr={stderr!r}")


def _force_exit(process: subprocess.Popen[str], ready_payload: dict[str, Any]) -> None:
    child_pid = ready_payload.get("pid")
    assert isinstance(child_pid, int)
    assert child_pid == process.pid
    assert child_pid != os.getpid()
    assert process.poll() is None
    process.kill()
    process.wait(timeout=10)
    stdout, stderr = process.communicate(timeout=5)
    assert stdout == ""
    assert stderr == ""


def _assert_transcript_entry(entry: TranscriptEntry, *, sequence: int, turn_id: str, text: str) -> None:
    assert entry.session_id == "session-1"
    assert entry.sequence == sequence
    assert entry.turn_id == turn_id
    assert entry.kind is TranscriptKind.USER_MESSAGE
    assert entry.payload == {"text": text}
    assert entry.semantic_unit_id == turn_id


def test_process_exit_after_checkpoint_reopens_lock_history_and_timeline(tmp_path: Path) -> None:
    with _crashing_writer(tmp_path, "checkpoint") as (process, ready):
        assert ready["stage"] == "checkpoint_committed"
        _force_exit(process, ready)

    store = SessionFileStore(tmp_path / "sessions")
    recovered = store.read_session("session-1", expected_project_key="project")
    assert len(recovered.transcript.entries) == 1
    _assert_transcript_entry(recovered.transcript.entries[0], sequence=1, turn_id="turn-1", text="persisted before crash")
    assert recovered.timeline.trailing_records == ()
    assert [record.summary for record in recovered.timeline.fine_entries] == ["checkpointed summary"]
    assert len(recovered.timeline.committed_records) == 2
    assert store.read_history_page("session-1", page_size=2).units[0].unit_id == "turn-1"

    with store.open_writer("session-1", expected_project_key="project") as writer:
        assert writer.snapshot.timeline.fine_entries[0].summary == "checkpointed summary"
        next_entry = TranscriptEntry(
            "session-1",
            2,
            "turn-2",
            TranscriptKind.USER_MESSAGE,
            {"text": "continued after restart"},
            semantic_unit_id="turn-2",
        )
        assert writer.append_transcript(next_entry).transcript_appended is True
        next_reference = writer.snapshot.transcript.reference(2, 2)
        next_fine = SemanticEntry(
            "turn-2",
            "continued summary",
            (next_reference,),
            session_id="session-1",
        )
        next_checkpoint = ActiveCheckpoint("turn-2", ("turn-2",), session_id="session-1")
        assert writer.append_timeline_transaction((next_fine,), next_checkpoint).timeline_appended is True

    resumed = store.read_session("session-1", expected_project_key="project")
    assert len(resumed.transcript.entries) == 2
    _assert_transcript_entry(resumed.transcript.entries[0], sequence=1, turn_id="turn-1", text="persisted before crash")
    _assert_transcript_entry(resumed.transcript.entries[1], sequence=2, turn_id="turn-2", text="continued after restart")
    assert [record.summary for record in resumed.timeline.fine_entries] == [
        "checkpointed summary",
        "continued summary",
    ]
    assert len(resumed.timeline.committed_records) == 4
    assert resumed.timeline.trailing_records == ()
    history = store.read_history_page("session-1", page_size=2)
    assert [unit.unit_id for unit in history.units] == ["turn-1", "turn-2"]


def test_process_exit_between_derived_and_checkpoint_reopens_and_does_not_commit_tail(tmp_path: Path) -> None:
    with _crashing_writer(tmp_path, "tail") as (process, ready):
        assert ready["stage"] == "derived_written_partial_checkpoint"
        _force_exit(process, ready)

    store = SessionFileStore(tmp_path / "sessions")
    recovered = store.read_session("session-1", expected_project_key="project")
    assert len(recovered.transcript.entries) == 1
    _assert_transcript_entry(recovered.transcript.entries[0], sequence=1, turn_id="turn-1", text="persisted before crash")
    assert recovered.timeline.committed_records == ()
    assert [record.summary for record in recovered.timeline.trailing_records] == ["checkpointed summary"]
    assert "ignored_incomplete_tail" in recovered.recovery_diagnostics
    assert "ignored_uncommitted_timeline_tail" in recovered.recovery_diagnostics
    assert store.read_history_page("session-1", page_size=2).units[0].unit_id == "turn-1"

    with store.open_writer("session-1", expected_project_key="project") as writer:
        assert writer.snapshot.timeline.committed_records == ()
        assert [record.summary for record in writer.snapshot.timeline.trailing_records] == ["checkpointed summary"]
        next_entry = TranscriptEntry(
            "session-1",
            2,
            "turn-2",
            TranscriptKind.USER_MESSAGE,
            {"text": "history after tail recovery"},
            semantic_unit_id="turn-2",
        )
        assert writer.append_transcript(next_entry).transcript_appended is True
        next_reference = writer.snapshot.transcript.reference(2, 2)
        next_fine = SemanticEntry(
            "turn-2",
            "tail recovery summary",
            (next_reference,),
            session_id="session-1",
        )
        next_checkpoint = ActiveCheckpoint("turn-2", ("turn-2",), session_id="session-1")
        assert writer.append_timeline_transaction((next_fine,), next_checkpoint).timeline_appended is True

    resumed = store.read_session("session-1", expected_project_key="project")
    assert len(resumed.transcript.entries) == 2
    _assert_transcript_entry(resumed.transcript.entries[0], sequence=1, turn_id="turn-1", text="persisted before crash")
    _assert_transcript_entry(resumed.transcript.entries[1], sequence=2, turn_id="turn-2", text="history after tail recovery")
    assert [record.summary for record in resumed.timeline.trailing_records] == ["checkpointed summary"]
    assert [record.summary for record in resumed.timeline.fine_entries] == ["tail recovery summary"]
    assert [record.summary for record in resumed.timeline.committed_records if isinstance(record, SemanticEntry)] == [
        "tail recovery summary"
    ]
    assert len(resumed.timeline.records) == 3
    assert resumed.recovery_diagnostics == ("ignored_uncommitted_timeline_tail",)
    assert [unit.unit_id for unit in store.read_history_page("session-1", page_size=2).units] == ["turn-1", "turn-2"]
