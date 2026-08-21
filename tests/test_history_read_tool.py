from __future__ import annotations

import json

import pytest

from uthcode.application.history import transcript_entries_for_message
from uthcode.application.tools import ApplicationToolService
from uthcode.core.history import Transcript, TranscriptRef
from uthcode.core.provider import CancellationToken, Message, TextPart
from uthcode.core.permission import Effect, ResourceScope
from uthcode.core.tool import ToolExecutionOutcome, ToolExecutionStatus, ToolResultPersistenceStatus
from uthcode.integrations.tools.history_read import (
    HistoryReadBoundaryError,
    HistoryReadPage,
    HistoryReadPolicy,
    HistoryReadSessionError,
    HistoryReadTool,
    decode_history_ref,
)


def _transcript(session_id: str = "session-a", count: int = 3) -> Transcript:
    entries = []
    sequence = 1
    for index in range(count):
        message_entries = transcript_entries_for_message(
            session_id,
            f"turn-{index + 1}",
            sequence,
            Message("user", (TextPart(f"raw-{index + 1}"),)),
        )
        entries.extend(message_entries)
        sequence += len(message_entries)
    return Transcript(session_id, tuple(entries))


class _Session:
    def __init__(self, transcript: Transcript) -> None:
        self.session_id = transcript.session_id
        self.transcript = transcript

    def read_transcript(self, ref: TranscriptRef):
        return self.transcript.select(
            ref.sequence_start,
            ref.sequence_end,
            complete_only=True,
        )


def _reader_for(transcript: Transcript):
    def read(session_id: str, token: str, offset: int, limit: int) -> HistoryReadPage:
        if session_id != transcript.session_id:
            raise HistoryReadSessionError("wrong Session")
        ref = decode_history_ref(token)
        entries = transcript.select(ref.sequence_start, ref.sequence_end, complete_only=True)
        page_entries = entries[offset : offset + limit]
        next_offset = offset + len(page_entries)
        return HistoryReadPage(
            ref=token,
            entries=page_entries,
            offset=offset,
            next_offset=next_offset,
            total_entries=len(entries),
            eof=next_offset >= len(entries),
        )

    return read


@pytest.mark.asyncio
async def test_history_read_reads_only_the_active_session_ref_in_bounded_pages() -> None:
    transcript = _transcript(count=4)
    session = _Session(transcript)
    policy = HistoryReadPolicy(page_entry_limit=1, read_output_limit_bytes=2048)
    tool = HistoryReadTool(_reader_for(transcript), lambda: session, policy=policy)
    ref = transcript.reference(1, 4)

    preparation = tool.preflight({"ref": ref.to_token(), "limit": 1})
    assert preparation.action.tool == "HistoryRead"
    assert preparation.action.action == "read"
    assert preparation.action.effect is Effect.READ
    assert preparation.action.scope is ResourceScope.INSIDE
    assert preparation.action.resource == f"session-transcript:{ref.to_token()}"

    offset = 0
    recovered: list[str] = []
    while True:
        result = await tool.execute(
            {"ref": ref.to_token(), "offset": offset, "limit": 1},
            cancellation=CancellationToken(),
        )
        assert result.is_error is False
        assert len(result.content.encode("utf-8")) <= policy.read_output_limit_bytes
        payload = json.loads(result.content)
        assert payload["schema_version"] == 1
        assert payload["ref"] == ref.to_token()
        recovered.extend(entry["payload"]["message"]["parts"][0]["text"] for entry in payload["entries"])
        if payload["eof"]:
            assert payload["next_offset"] == payload["total_entries"]
            break
        assert payload["next_offset"] > payload["offset"]
        offset = payload["next_offset"]

    assert recovered == ["raw-1", "raw-2", "raw-3", "raw-4"]


@pytest.mark.asyncio
async def test_application_history_read_uses_only_the_active_session_transcript() -> None:
    transcript = _transcript(count=2)
    session = _Session(transcript)
    service = ApplicationToolService(
        (),
        session_provider=lambda: session,
        history_read_policy=HistoryReadPolicy(page_entry_limit=2, read_output_limit_bytes=2048),
    )
    tool = service._registry.get("HistoryRead")
    assert tool is not None
    result = await tool.execute(  # type: ignore[attr-defined]
        {"ref": transcript.reference(1, 2).to_token(), "offset": 0, "limit": 2},
        cancellation=CancellationToken(),
    )
    assert result.is_error is False
    assert [entry["sequence"] for entry in json.loads(result.content)["entries"]] == [1, 2]

    foreign = TranscriptRef("session-b", 1, 1).to_token()
    result = await tool.execute(  # type: ignore[attr-defined]
        {"ref": foreign},
        cancellation=CancellationToken(),
    )
    assert result.is_error is True
    assert "history_session_mismatch" in result.content


def test_history_read_rejects_noncanonical_and_cross_session_refs() -> None:
    transcript = _transcript()
    session = _Session(transcript)
    tool = HistoryReadTool(_reader_for(transcript), lambda: session)
    ref = transcript.reference(1, 1)

    with pytest.raises(Exception, match="canonical"):
        decode_history_ref(ref.to_token() + "=")

    foreign = TranscriptRef("session-b", 1, 1).to_token()
    with pytest.raises(HistoryReadSessionError):
        tool.preflight({"ref": foreign})

    with pytest.raises(HistoryReadBoundaryError):
        tool.preflight({"ref": ref.to_token(), "offset": -1})


@pytest.mark.asyncio
async def test_history_read_keeps_boundary_and_output_failures_controlled() -> None:
    transcript = _transcript(count=1)
    session = _Session(transcript)
    ref = transcript.reference(1, 1)

    def bad_reader(_session_id: str, _token: str, _offset: int, _limit: int) -> HistoryReadPage:
        raise HistoryReadBoundaryError("split semantic unit")

    tool = HistoryReadTool(
        bad_reader,
        lambda: session,
        policy=HistoryReadPolicy(page_entry_limit=4, read_output_limit_bytes=512),
    )
    result = await tool.execute(
        {"ref": ref.to_token(), "offset": 0, "limit": 1},
        cancellation=CancellationToken(),
    )
    assert result.is_error is True
    assert "invalid_history_boundary" in result.content

    large = TranscriptRef("session-a", 1, 1)

    oversized_transcript = Transcript(
        "session-a",
        (
            transcript.entries[0].__class__(
                **{
                    **transcript.entries[0].to_dict(),
                    "payload": {"message": {"text": "x" * 2000}},
                }
            ),
        ),
    )

    def oversized_reader(_session_id: str, token: str, offset: int, limit: int) -> HistoryReadPage:
        del limit
        return HistoryReadPage(
            ref=token,
            entries=tuple(oversized_transcript.entries[offset : offset + 1]),
            offset=offset,
            next_offset=offset + 1,
            total_entries=1,
            eof=True,
        )

    oversized_session = _Session(oversized_transcript)
    oversized_tool = HistoryReadTool(
        oversized_reader,
        lambda: oversized_session,
        policy=HistoryReadPolicy(page_entry_limit=4, read_output_limit_bytes=128),
    )
    result = await oversized_tool.execute(
        {"ref": large.to_token(), "offset": 0, "limit": 1},
        cancellation=CancellationToken(),
    )
    assert result.is_error is True
    assert "history_read_output_limit_exceeded" in result.content


def test_history_read_results_are_never_externalized_recursively() -> None:
    service = ApplicationToolService(
        (),
        session_provider=lambda: None,
    )
    outcome = ToolExecutionOutcome(
        "call-1",
        "HistoryRead",
        "x" * 100_000,
        False,
        ToolExecutionStatus.SUCCEEDED,
    )
    materialized = service.materialize_tool_result(outcome)
    assert materialized.persistence_status is ToolResultPersistenceStatus.INLINE
    assert materialized.reference is None
