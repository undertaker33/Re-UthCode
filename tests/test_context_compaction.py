from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence

import pytest

import uthcode.core as core
from uthcode.application.context import ApplicationContextService
from uthcode.core.compaction import (
    CompactionEntry,
    CompactionInProgress,
    CompactionPolicy,
    CompactionStructuredResult,
    CompactionValidationError,
    ContextCompactor,
)
from uthcode.core.history import ActiveCheckpoint, EpochMacroSummary, SemanticEntry, Timeline, Transcript, TranscriptEntry, TranscriptKind, TranscriptRef
from uthcode.core.provider import CancellationToken


def _transcript() -> Transcript:
    entries = tuple(
        TranscriptEntry("compact-session", index, f"turn-{index}", TranscriptKind.USER_MESSAGE, {"text": f"fact-{index}"}, semantic_unit_id=f"turn-{index}")
        for index in range(1, 5)
    )
    return Transcript("compact-session", entries)


def _valid_epoch_response(epoch, summary: str = "summary") -> dict[str, object]:
    return {
        "entries": [
            {
                "turn_id": turn_id,
                "summary": f"{summary} for {turn_id}",
                "refs": [ref.to_dict()],
            }
            for turn_id, ref in zip(epoch.turn_ids, epoch.refs, strict=True)
        ],
        "coverage": list(epoch.turn_ids),
    }


def _oversized_transcript() -> Transcript:
    return Transcript(
        "oversized-session",
        (
            TranscriptEntry(
                "oversized-session",
                1,
                "turn-oversized",
                TranscriptKind.USER_MESSAGE,
                {
                    "role": "user",
                    "part": {"type": "text", "text": "x" * 1_000},
                },
                semantic_unit_id="turn-oversized",
            ),
        ),
    )


def _oversized_compactor() -> ContextCompactor:
    return ContextCompactor(
        policy=CompactionPolicy(
            input_budget=400,
            output_reserve=50,
            summary_hard_cap=100,
        ),
        token_estimator=len,
    )


def test_core_all_exports_are_resolvable() -> None:
    namespace: dict[str, object] = {}

    exec("from uthcode.core import *", namespace)

    assert set(core.__all__) <= namespace.keys()
    assert all(namespace[name] is getattr(core, name) for name in core.__all__)


def test_multiturn_compaction_requires_explicit_entries_refs_and_coverage() -> None:
    transcript = _transcript()
    compactor = ContextCompactor(token_estimator=lambda _text: 1)
    epoch = compactor.plan_epoch(transcript)
    assert epoch is not None
    assert len(epoch.units) == 4

    with pytest.raises(CompactionValidationError):
        compactor.parse_epoch_result("plain text", epoch=epoch)
    with pytest.raises(CompactionValidationError):
        compactor.parse_epoch_result(
            {"summary": "summary", "coverage": list(epoch.turn_ids)},
            epoch=epoch,
        )
    with pytest.raises(CompactionValidationError):
        compactor.parse_epoch_result(
            {"entries": ["summary"] * len(epoch.units), "coverage": list(epoch.turn_ids)},
            epoch=epoch,
        )
    with pytest.raises(CompactionValidationError):
        compactor.parse_epoch_result(
            {
                "entries": [
                    {"turn_id": turn_id, "summary": "summary"}
                    for turn_id in epoch.turn_ids
                ],
                "coverage": list(epoch.turn_ids),
            },
            epoch=epoch,
        )
    with pytest.raises(CompactionValidationError):
        compactor.parse_epoch_result(
            {
                "entries": [
                    {
                        "turn_id": turn_id,
                        "summary": "summary",
                        "refs": [ref.to_dict()],
                    }
                    for turn_id, ref in zip(epoch.turn_ids, epoch.refs, strict=True)
                ]
            },
            epoch=epoch,
        )
    wrong_order = _valid_epoch_response(epoch)
    wrong_order["entries"] = list(reversed(wrong_order["entries"]))  # type: ignore[arg-type]
    with pytest.raises(CompactionValidationError):
        compactor.parse_epoch_result(wrong_order, epoch=epoch)
    wrong_ref = _valid_epoch_response(epoch)
    wrong_ref_entries = list(wrong_ref["entries"])  # type: ignore[arg-type]
    wrong_ref_entries[1] = {
        **wrong_ref_entries[1],
        "refs": [epoch.refs[0].to_dict()],
    }
    wrong_ref["entries"] = wrong_ref_entries
    with pytest.raises(CompactionValidationError):
        compactor.parse_epoch_result(wrong_ref, epoch=epoch)

    parsed = compactor.parse_epoch_result(_valid_epoch_response(epoch), epoch=epoch)
    assert parsed.coverage == epoch.turn_ids
    assert tuple(entry.turn_id for entry in parsed.entries) == epoch.turn_ids
    assert tuple(entry.refs for entry in parsed.entries) == tuple((ref,) for ref in epoch.refs)


def test_single_turn_compatibility_accepts_bounded_legacy_shapes() -> None:
    transcript = Transcript(
        "single-session",
        (
            TranscriptEntry(
                "single-session",
                1,
                "turn-1",
                TranscriptKind.USER_MESSAGE,
                {"text": "fact"},
                semantic_unit_id="turn-1",
            ),
        ),
    )
    compactor = ContextCompactor(token_estimator=lambda _text: 1)
    epoch = compactor.plan_epoch(transcript)
    assert epoch is not None
    assert compactor.parse_epoch_result("plain", epoch=epoch).coverage == epoch.turn_ids
    assert compactor.parse_epoch_result(
        {"summary": "summary"}, epoch=epoch
    ).coverage == epoch.turn_ids
    assert compactor.parse_epoch_result(
        {"entries": ["summary"], "coverage": list(epoch.turn_ids)}, epoch=epoch
    ).entries[0].refs == epoch.refs


def test_oversized_complete_turn_builds_one_fine_with_full_refs() -> None:
    transcript = _oversized_transcript()
    compactor = _oversized_compactor()
    plan = compactor.plan_oversized_turn(transcript)
    assert plan is not None
    assert plan.subpass_count > 1
    assert all(
        subpass.input_tokens <= subpass.input_budget - subpass.output_reserve
        for subpass in plan.subpasses
    )
    assert tuple(
        sequence
        for subpass in plan.subpasses
        for sequence in subpass.source_sequences
    ) == (1,) * plan.subpass_count

    subpass_results = ["a" * 90] * plan.subpass_count
    fold_rounds: list[list[str]] = []
    fold_sources: Sequence[object] = subpass_results
    for round_index in range(8):
        fold_plan = compactor.plan_oversized_fold_round(fold_sources)
        if fold_plan is None:
            break
        assert all(
            fold.input_tokens <= fold.input_budget - fold.output_reserve
            for fold in fold_plan.folds
        )
        folded = [
            "b" * 90 if round_index == 0 else "folded summary"
        ] * fold_plan.fold_count
        fold_rounds.append(folded)
        fold_sources = folded
    assert fold_rounds
    assert len(fold_rounds) >= 2
    assert compactor.plan_oversized_fold_round(fold_sources) is None
    first_fold = compactor.plan_oversized_fold_round(subpass_results)
    assert first_fold is not None
    assert first_fold.aggregate_input_tokens > first_fold.input_budget - first_fold.output_reserve

    result = compactor.build_oversized_candidate(
        transcript,
        plan=plan,
        subpass_results=subpass_results,
        fold_results=fold_rounds,
    )
    assert result.changed is True
    assert result.timeline is not None
    assert len(result.timeline.fine_entries) == 1
    fine = result.timeline.fine_entries[0]
    assert fine.turn_id == "turn-oversized"
    assert fine.refs == (TranscriptRef("oversized-session", 1, 1),)
    assert len(result.timeline.records) == 2
    assert isinstance(result.timeline.active_checkpoint, ActiveCheckpoint)


def test_oversized_subpass_failure_cancel_and_invalid_leave_no_candidate() -> None:
    transcript = _oversized_transcript()
    compactor = _oversized_compactor()
    plan = compactor.plan_oversized_turn(transcript)
    assert plan is not None

    subpass_results = ["a" * 90] * plan.subpass_count
    first_fold = compactor.plan_oversized_fold_round(subpass_results)
    assert first_fold is not None

    missing = compactor.build_oversized_candidate(
        transcript,
        plan=plan,
        subpass_results=subpass_results,
    )
    assert missing.changed is False
    assert missing.failure == "oversized_fold_required"
    assert missing.timeline is None

    failed = compactor.build_oversized_candidate(
        transcript,
        plan=plan,
        subpass_results=subpass_results,
        fold_results=[
            [{"failure": "fold_failed"}] + ["ok"] * (first_fold.fold_count - 1)
        ],
    )
    assert failed.changed is False
    assert failed.failure == "fold_failed"
    assert failed.timeline is None

    cancelled = compactor.build_oversized_candidate(
        transcript,
        plan=plan,
        subpass_results=subpass_results,
        fold_results=[
            [{"cancelled": True}] + ["ok"] * (first_fold.fold_count - 1)
        ],
    )
    assert cancelled.changed is False
    assert cancelled.failure == "compaction_cancelled"
    assert cancelled.timeline is None

    token = CancellationToken()
    assert token.cancel() is True
    pre_cancelled = compactor.build_oversized_candidate(
        transcript,
        plan=plan,
        subpass_results=["ok"] * plan.subpass_count,
        cancellation=token,
    )
    assert pre_cancelled.changed is False
    assert pre_cancelled.failure == "compaction_cancelled"
    assert pre_cancelled.timeline is None

    with pytest.raises(CompactionValidationError):
        compactor.build_oversized_candidate(
            transcript,
            plan=plan,
            subpass_results=subpass_results,
            fold_results=[[{"entries": []}] * first_fold.fold_count],
        )


def test_compaction_top_level_summary_hard_cap_is_checked_for_objects_and_json() -> None:
    transcript = _transcript()
    compactor = ContextCompactor(
        policy=CompactionPolicy(
            input_budget=10_000,
            output_reserve=100,
            summary_hard_cap=5,
        ),
        token_estimator=len,
    )
    epoch = compactor.plan_epoch(transcript)
    assert epoch is not None
    entries = tuple(
        CompactionEntry(turn_id, "ok", (ref,))
        for turn_id, ref in zip(epoch.turn_ids, epoch.refs, strict=True)
    )
    structured = CompactionStructuredResult(
        entries=entries,
        coverage=epoch.turn_ids,
        summary="x" * 6,
    )
    with pytest.raises(CompactionValidationError, match="summary_hard_cap_exceeded"):
        compactor.parse_epoch_result(structured, epoch=epoch)

    payload = {
        "entries": [
            {
                "turn_id": turn_id,
                "summary": "ok",
                "refs": [ref.to_dict()],
            }
            for turn_id, ref in zip(epoch.turn_ids, epoch.refs, strict=True)
        ],
        "coverage": list(epoch.turn_ids),
        "summary": "x" * 6,
    }
    with pytest.raises(CompactionValidationError, match="summary_hard_cap_exceeded"):
        compactor.parse_epoch_result(json.dumps(payload), epoch=epoch)


@pytest.mark.asyncio
async def test_application_context_compact_records_bounded_diagnostics() -> None:
    transcript = _transcript()
    service = ApplicationContextService()

    async def summarize(epoch):
        return _valid_epoch_response(epoch)

    result = await service.compact_async(transcript, summarize=summarize)
    assert result.timeline is not None
    diagnostics = service.public_diagnostics()
    assert diagnostics["compaction"]["count"] == 1
    assert diagnostics["compaction"]["last"]["coverage_count"] >= 1


@pytest.mark.asyncio
async def test_application_compaction_status_covers_running_and_terminal_boundaries() -> None:
    transcript = _transcript()
    service = ApplicationContextService()
    observed: list[tuple[str, str | None, bool | None]] = []

    async def summarize(epoch):
        status = service.compaction_status
        observed.append((status.state, status.trigger, status.changed))
        return _valid_epoch_response(epoch)

    result = await service.compact_async(
        transcript,
        summarize=summarize,
        trigger="auto",
    )
    assert observed == [("running", "auto", None)]
    assert result.changed is True
    assert service.compaction_status.to_dict() == {
        "state": "completed",
        "trigger": "auto",
        "changed": True,
    }


@pytest.mark.asyncio
async def test_compaction_triggers_share_single_flight_without_clobbering_owner_status() -> None:
    transcript = _transcript()
    service = ApplicationContextService()
    entered = asyncio.Event()
    release = asyncio.Event()

    async def summarize(epoch):
        entered.set()
        await release.wait()
        return _valid_epoch_response(epoch)

    owner = asyncio.create_task(
        service.compact_async(transcript, summarize=summarize, trigger="auto")
    )
    await entered.wait()
    with pytest.raises(CompactionInProgress):
        await service.compact_async(
            transcript,
            summarize=summarize,
            trigger="overflow",
        )
    assert service.compaction_status.to_dict() == {
        "state": "running",
        "trigger": "auto",
        "changed": None,
    }
    release.set()
    result = await owner
    assert result.changed is True
    assert service.compaction_status.state == "completed"


@pytest.mark.asyncio
async def test_invalid_first_attempt_then_success_clears_transient_failure_and_commits() -> None:
    transcript = _transcript()
    service = ApplicationContextService()
    attempts = 0
    committed = []

    async def summarize(epoch):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return {"entries": "not-a-list", "coverage": []}
        return _valid_epoch_response(epoch)

    def commit(candidate):
        committed.append(candidate)
        return candidate

    result = await service.compact_async(
        transcript,
        summarize=summarize,
        commit=commit,
    )

    assert attempts == 2
    assert result.changed is True
    assert result.failure is None
    assert len(committed) == 1
    assert result.timeline is not None
    assert result.timeline.active_checkpoint is not None


@pytest.mark.asyncio
async def test_compaction_stops_at_configured_epoch_limit_and_keeps_last_checkpoint() -> None:
    transcript = _transcript()
    service = ApplicationContextService(
        compactor=ContextCompactor(
            token_estimator=lambda text: text.count('"unit_id"') * 10 + 1
        )
    )
    summarized: list[tuple[str, ...]] = []
    committed = []

    async def summarize(epoch):
        summarized.append(epoch.turn_ids)
        return _valid_epoch_response(epoch, "ok")

    def commit(candidate):
        committed.append(candidate)
        return candidate

    result = await service.compact_async(
        transcript,
        summarize=summarize,
        commit=commit,
        should_continue=lambda _timeline: True,
        max_epochs=2,
        input_budget=25,
        output_reserve=5,
        summary_hard_cap=5,
    )

    assert summarized == [("turn-1",), ("turn-2",)]
    assert len(committed) == 2
    assert result.changed is True
    assert result.failure == "epoch_limit_reached"
    assert result.timeline is not None
    assert [entry.turn_id for entry in result.timeline.fine_entries] == [
        "turn-1",
        "turn-2",
    ]
    assert result.timeline.active_checkpoint is not None
    assert result.timeline.active_checkpoint.turn_id == "turn-2"
    assert result.timeline.records[-1].record_type == "active_checkpoint"
    assert all(
        getattr(record, "turn_id", None) != "turn-3"
        for record in result.timeline.records
    )


def test_context_compactor_single_flight_rejects_reentrant_lock() -> None:
    compactor = ContextCompactor()
    transcript = _transcript()
    lock = compactor._acquire_single_flight(transcript.session_id)
    try:
        with pytest.raises(CompactionInProgress, match="already running"):
            compactor._acquire_single_flight(transcript.session_id)
    finally:
        lock.release()


@pytest.mark.asyncio
async def test_timeline_aging_uses_raw_transcript_and_logically_supersedes_fine() -> None:
    transcript = _transcript()
    fine = tuple(
        SemanticEntry(
            f"turn-{index}",
            f"Fine summary {index}",
            (transcript.reference(index, index),),
            session_id=transcript.session_id,
        )
        for index in range(1, 5)
    )
    timeline = Timeline(transcript.session_id).append_transaction(
        fine,
        ActiveCheckpoint("turn-4", tuple(entry.turn_id for entry in fine), session_id=transcript.session_id),
    )
    compactor = ContextCompactor(
        policy=CompactionPolicy(input_budget=500, output_reserve=50, summary_hard_cap=100),
        token_estimator=lambda text: max(1, len(text) // 20),
    )
    service = ApplicationContextService(compactor=compactor)
    captured: list[str] = []

    async def summarize(epoch):
        captured.append(epoch.input_text)
        return {"summary": "one macro", "coverage": list(epoch.turn_ids)}

    result = await service.age_timeline_async(
        transcript,
        timeline=timeline,
        summarize=summarize,
        fine_budget=1,
        input_budget=500,
        output_reserve=50,
        summary_hard_cap=100,
    )

    assert result.changed is True
    assert result.timeline is not None
    assert len(captured) == 1
    assert "Fine summary" not in captured[0]
    assert "fact-1" in captured[0]
    assert result.timeline.physical_fine_entries == fine
    assert result.timeline.fine_entries == ()
    assert len(result.timeline.macro_summaries) == 1
    assert isinstance(result.timeline.logical_records[-2], EpochMacroSummary)
    assert result.timeline.records[-1].record_type == "active_checkpoint"
    assert service.public_diagnostics()["compaction"]["last"]["level"] == "L5"


@pytest.mark.asyncio
async def test_timeline_aging_rejects_an_unsafe_oldest_fine_epoch_without_model_call() -> None:
    transcript = _transcript()
    malformed = SemanticEntry(
        "turn-1",
        "Fine summary",
        (TranscriptRef(transcript.session_id, 1, 2),),
        session_id=transcript.session_id,
    )
    timeline = Timeline(transcript.session_id).append_transaction(
        (malformed,),
        ActiveCheckpoint("turn-1", ("turn-1",), session_id=transcript.session_id),
    )
    service = ApplicationContextService(
        compactor=ContextCompactor(token_estimator=lambda text: max(1, len(text) // 20))
    )
    called = False

    async def summarize(_epoch):
        nonlocal called
        called = True
        return {"summary": "must not run"}

    result = await service.age_timeline_async(
        transcript,
        timeline=timeline,
        summarize=summarize,
        fine_budget=1,
    )
    assert result.changed is False
    assert result.failure == "no_safe_epoch"
    assert called is False
