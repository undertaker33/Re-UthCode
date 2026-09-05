from __future__ import annotations

from pathlib import Path
from time import perf_counter
from typing import Any

import pytest

from uthcode.application.sessions import ApplicationSessionService
from uthcode.core.history import TranscriptEntry, TranscriptKind
from uthcode.core.provider import TextPart, ToolCallPart, ToolResultPart
from uthcode.integrations.session_files import (
    HISTORY_READ_BLOCK_BYTES,
    SessionFileStore,
)
from uthcode.integrations.tools.tool_result_read import (
    ToolResultPolicy,
    format_externalized_preview,
)


class _ReadStats:
    """Aggregate reads for every handle opened for one transcript."""

    def __init__(self) -> None:
        self.read_calls = 0
        self.bytes_read = 0


class _ReadMeter:
    """Count bytes returned by one real transcript file handle."""

    def __init__(self, handle: Any, stats: _ReadStats) -> None:
        self._handle = handle
        self._stats = stats

    def read(self, size: int = -1) -> bytes:
        self._stats.read_calls += 1
        value = self._handle.read(size)
        self._stats.bytes_read += len(value)
        return value

    def __getattr__(self, name: str) -> Any:
        return getattr(self._handle, name)

    def __enter__(self) -> _ReadMeter:
        self._handle.__enter__()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> object:
        return self._handle.__exit__(exc_type, exc, traceback)


def _fixed_text(prefix: str, size: int) -> str:
    if len(prefix) >= size:
        return prefix[:size]
    return prefix + ("x" * (size - len(prefix)))


def _append_units(
    store: SessionFileStore,
    session_id: str,
    count: int,
    *,
    text_size: int = 256,
    externalized_tool_index: int | None = None,
    externalized_preview: str | None = None,
    externalized_reference: object | None = None,
    cross_block_tool_index: int | None = None,
) -> None:
    entries: list[TranscriptEntry] = []
    sequence = 1
    for index in range(count):
        unit_id = f"turn-{index:05d}"
        entries.append(
            TranscriptEntry(
                session_id,
                sequence,
                unit_id,
                TranscriptKind.USER_MESSAGE,
                {
                    "role": "user",
                    "part": TextPart(_fixed_text(f"message-{index:05d} ", text_size)).to_dict(),
                },
                semantic_unit_id=unit_id,
            )
        )
        sequence += 1

        if index == externalized_tool_index:
            assert externalized_preview is not None
            reference = externalized_reference
            assert reference is not None
            argument_size = (
                HISTORY_READ_BLOCK_BYTES + 2_048
                if index == cross_block_tool_index
                else 32
            )
            call_id = f"call-{index:05d}"
            entries.append(
                TranscriptEntry(
                    session_id,
                    sequence,
                    unit_id,
                    TranscriptKind.TOOL_CALL,
                    {
                        "role": "assistant",
                        "part": ToolCallPart(
                            call_id,
                            "read",
                            {"path": _fixed_text("fixture-", argument_size)},
                        ).to_dict(),
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
                    TranscriptKind.TOOL_RESULT,
                    {
                        "role": "tool",
                        "part": ToolResultPart(
                            call_id,
                            externalized_preview,
                            metadata={
                                "execution_status": "succeeded",
                                "persistence_status": "externalized",
                                "ref": reference.ref,
                                "size_bytes": reference.size_bytes,
                                "sha256": reference.sha256,
                            },
                        ).to_dict(),
                    },
                    semantic_unit_id=unit_id,
                )
            )
            sequence += 1
            continue

        entries.append(
            TranscriptEntry(
                session_id,
                sequence,
                unit_id,
                TranscriptKind.ASSISTANT_MESSAGE,
                {
                    "role": "assistant",
                    "part": TextPart(_fixed_text(f"answer-{index:05d} ", text_size)).to_dict(),
                },
                semantic_unit_id=unit_id,
            )
        )
        sequence += 1

    with store.open_writer(session_id, expected_project_key="project") as writer:
        writer.append_transcript(entries)


def _instrument_transcript_reads(
    monkeypatch: pytest.MonkeyPatch,
    transcript_paths: set[Path],
    *,
    forbidden_paths: set[Path] | None = None,
) -> dict[Path, _ReadStats]:
    meters: dict[Path, _ReadStats] = {}
    original_open = Path.open
    original_read_bytes = Path.read_bytes
    original_read_text = Path.read_text
    resolved_paths = {path.resolve() for path in transcript_paths}
    resolved_forbidden_paths = {
        path.resolve() for path in (forbidden_paths or set())
    }

    def counting_open(
        path: Path,
        mode: str = "r",
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        resolved = path.resolve()
        if resolved in resolved_forbidden_paths:
            raise AssertionError("history paging must not open raw Tool Result content")
        handle = original_open(path, mode, *args, **kwargs)
        if resolved in resolved_paths and "r" in mode and "b" in mode:
            stats = meters.setdefault(resolved, _ReadStats())
            meter = _ReadMeter(handle, stats)
            return meter
        return handle

    def reject_full_read(path: Path) -> bytes:
        resolved = path.resolve()
        if resolved in resolved_forbidden_paths:
            raise AssertionError("history paging must not read raw Tool Result content")
        if resolved in resolved_paths:
            raise AssertionError("history paging must not use Path.read_bytes()")
        return original_read_bytes(path)

    def reject_text_read(path: Path, *args: Any, **kwargs: Any) -> str:
        resolved = path.resolve()
        if resolved in resolved_forbidden_paths:
            raise AssertionError("history paging must not read raw Tool Result content")
        if resolved in resolved_paths:
            raise AssertionError("history paging must not use Path.read_text()")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", counting_open)
    monkeypatch.setattr(Path, "read_bytes", reject_full_read)
    monkeypatch.setattr(Path, "read_text", reject_text_read)
    return meters


def test_recent_history_page_io_does_not_scale_with_total_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = SessionFileStore(tmp_path)
    counts = (100, 1_000, 5_000)
    services: dict[int, ApplicationSessionService] = {}
    transcript_paths: set[Path] = set()

    for count in counts:
        session_id = f"history-{count}"
        store.create_session(session_id, project_key="project")
        _append_units(store, session_id, count)
        services[count] = ApplicationSessionService(
            storage_root=tmp_path,
            project_key="project",
            instruction_loader=None,
            store=store,
        )
        transcript_paths.add(tmp_path / session_id / "transcript.jsonl")

    meters = _instrument_transcript_reads(monkeypatch, transcript_paths)
    measurements: list[tuple[int, int, int, float]] = []
    for count in counts:
        transcript_path = tmp_path / f"history-{count}" / "transcript.jsonl"
        total_bytes = transcript_path.stat().st_size
        started = perf_counter()
        page = services[count].read_history_page(f"history-{count}")
        elapsed_ms = (perf_counter() - started) * 1_000
        actual_read = meters[transcript_path.resolve()].bytes_read
        measurements.append((count, total_bytes, actual_read, elapsed_ms))

        assert page.unit_count == 30
        assert len(page.records) == 60
        assert page.has_more is True
        assert page.records[0].text == _fixed_text(
            f"message-{count - 30:05d} ", 256
        )
        assert page.records[-1].text == _fixed_text(
            f"answer-{count - 1:05d} ", 256
        )
        assert page.bytes_read > 0
        assert page.bytes_read == actual_read
        assert actual_read < total_bytes
        assert meters[transcript_path.resolve()].read_calls <= (
            (actual_read + HISTORY_READ_BLOCK_BYTES - 1) // HISTORY_READ_BLOCK_BYTES
        ) + 2

        print(
            "history_page_perf "
            f"units={count} total_bytes={total_bytes} "
            f"page_bytes={page.bytes_read} actual_read={actual_read} "
            f"read_calls={meters[transcript_path.resolve()].read_calls} "
            f"read_minus_page={actual_read - page.bytes_read} "
            f"elapsed_ms={elapsed_ms:.3f}"
        )

    first_count, first_total, first_read, _ = measurements[0]
    last_count, last_total, last_read, _ = measurements[-1]
    assert last_count / first_count == 50
    assert last_total / first_total > 40
    # A full-file implementation would track the 50x history growth.  The
    # reverse 16 KiB reader should stay within a couple of block boundaries.
    assert last_read <= first_read + (2 * HISTORY_READ_BLOCK_BYTES)


def test_externalized_tool_result_is_bounded_and_cross_block_unit_stays_complete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = SessionFileStore(tmp_path)
    session_id = "history-external-ref"
    store.create_session(session_id, project_key="project")
    policy = ToolResultPolicy(
        inline_threshold_bytes=64,
        preview_limit_bytes=96,
        single_result_hard_cap_bytes=256 * 1024,
        session_quota_bytes=512 * 1024,
    )
    raw_marker = "RAW_TOOL_RESULT_MUST_REMAIN_EXTERNAL_7f0d"
    raw_content = "visible-row\n" + ("r" * 120_000) + raw_marker
    reference = store.persist_tool_result(session_id, raw_content, policy=policy)
    preview = format_externalized_preview(
        raw_content,
        reference,
        preview_limit_bytes=policy.preview_limit_bytes,
    )
    _append_units(
        store,
        session_id,
        100,
        externalized_tool_index=99,
        externalized_preview=preview,
        externalized_reference=reference,
        cross_block_tool_index=99,
    )

    transcript_path = tmp_path / session_id / "transcript.jsonl"
    raw_content_path = (
        store.session_path(session_id)
        / "tool-results"
        / reference.ref
        / "content.bin"
    )
    assert raw_content_path.is_file()
    meters = _instrument_transcript_reads(
        monkeypatch,
        {transcript_path},
        forbidden_paths={raw_content_path},
    )
    page = store.read_history_page(session_id)
    actual_read = meters[transcript_path.resolve()].bytes_read
    total_bytes = transcript_path.stat().st_size

    assert page.units[-1].turn_id == "turn-00099"
    assert page.units[-1].complete is True
    assert len(page.units) == 30
    assert actual_read < total_bytes
    assert page.bytes_read == actual_read
    assert meters[transcript_path.resolve()].read_calls <= (
        (actual_read + HISTORY_READ_BLOCK_BYTES - 1) // HISTORY_READ_BLOCK_BYTES
    ) + 2

    call_entries = [
        entry
        for entry in page.units[-1].entries
        if entry.kind is TranscriptKind.TOOL_CALL
    ]
    assert len(call_entries) == 1
    call_payload = call_entries[0].payload["part"]
    assert len(call_payload["arguments"]["path"].encode("utf-8")) > HISTORY_READ_BLOCK_BYTES

    result_entries = [
        entry
        for entry in page.units[-1].entries
        if entry.kind is TranscriptKind.TOOL_RESULT
    ]
    assert len(result_entries) == 1
    result_payload = result_entries[0].payload["part"]
    assert result_payload["metadata"]["ref"] == reference.ref
    assert result_payload["metadata"]["size_bytes"] == reference.size_bytes
    assert result_payload["content"] == preview
    assert raw_marker not in result_payload["content"]

    print(
        "history_page_external_ref "
        f"total_bytes={total_bytes} page_bytes={page.bytes_read} "
        f"actual_read={actual_read} "
        f"read_calls={meters[transcript_path.resolve()].read_calls} "
        f"read_minus_page={actual_read - page.bytes_read} "
        f"raw_bytes={reference.size_bytes}"
    )


def test_transcript_read_instrumentation_accumulates_reopened_handles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transcript_path = tmp_path / "transcript.jsonl"
    transcript_path.write_bytes(b"first\nsecond\n")
    meters = _instrument_transcript_reads(monkeypatch, {transcript_path})

    with transcript_path.open("rb") as handle:
        assert handle.read(2) == b"fi"
    with transcript_path.open("rb") as handle:
        assert handle.read() == b"first\nsecond\n"

    stats = meters[transcript_path.resolve()]
    assert stats.read_calls == 2
    assert stats.bytes_read == 2 + len(b"first\nsecond\n")
