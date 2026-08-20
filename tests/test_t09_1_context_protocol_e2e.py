from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

import pytest

from uthcode.application import (
    EffectiveConfig,
    Message,
    RunStatus,
    TextPart,
    UthCodeApplication,
)
from uthcode.application.history import transcript_entries_for_message
from uthcode.application.context import ApplicationContextService
from uthcode.application.sessions import ApplicationSessionService
from uthcode.core.compaction import CompactionEpoch
from uthcode.core.context import (
    CompactionResult,
    ContextCompactor,
    account_generation_request,
)
from uthcode.core.history import (
    ActiveCheckpoint,
    Timeline,
    Transcript,
    TranscriptEntry,
    TranscriptKind,
)
from uthcode.core.provider import (
    CancellationToken,
    FinishReason,
    GenerationCancelled,
    GenerationCompleted,
    GenerationRequest,
    ModelLimits,
    ProviderEvent,
    ProviderIdentity,
    ProviderResponse,
    Usage,
)


def _completed(text: str) -> GenerationCompleted:
    return GenerationCompleted(
        ProviderResponse(
            message=Message("assistant", (TextPart(text),)),
            usage=Usage(),
            finish_reason=FinishReason.STOP,
        )
    )


class _L4Provider:
    def __init__(
        self,
        *,
        safe_ordinary_count: bool = False,
        compaction_failure: BaseException | None = None,
    ) -> None:
        self.identity = ProviderIdentity("fake", "l4", "provider-model")
        self.requests: list[GenerationRequest] = []
        self._safe_ordinary_count = safe_ordinary_count
        self._compaction_failure = compaction_failure
        self.compaction_token_cancelled: list[bool] = []

    def resolve_model_limits(self, _model: str) -> ModelLimits:
        return ModelLimits(
            max_input_tokens=6_000,
            max_output_tokens=2_048,
            source="test.l4",
        )

    def count_input_tokens(self, request: GenerationRequest) -> int:
        estimate = account_generation_request(request).input_tokens
        if request.metadata.get("context_compaction_request") is True:
            return estimate
        if self._safe_ordinary_count:
            return 1
        if request.metadata.get("timeline_checkpoint_id") is None:
            return estimate + 4_000
        return estimate

    async def stream(
        self,
        request: GenerationRequest,
        *,
        cancellation: CancellationToken,
    ) -> AsyncIterator[ProviderEvent]:
        self.requests.append(request)
        cancellation.raise_if_cancelled()
        if request.metadata.get("context_compaction_request") is True:
            self.compaction_token_cancelled.append(cancellation.cancelled)
            if self._compaction_failure is not None:
                yield _completed("partial compaction output")
                raise self._compaction_failure
            turn_ids = tuple(
                value
                for value in request.metadata.get("context_compaction_epoch_turns", ())
                if isinstance(value, str)
            )
            payload = {
                "entries": [
                    {"turn_id": turn_id, "summary": f"summary for {turn_id}"}
                    for turn_id in turn_ids
                ],
                "coverage": list(turn_ids),
            }
            yield _completed(json.dumps(payload, ensure_ascii=False))
            return
        yield _completed("ordinary answer")


def _seed_session(application: UthCodeApplication, *, count: int = 70):
    session = application.create_session("l4-session")
    for index in range(1, count + 1):
        message = Message("user", (TextPart(f"fact-{index} " + "x" * 2_000),))
        entries = transcript_entries_for_message(
            session.session_id,
            f"turn-{index}",
            session.transcript.last_sequence + 1,
            message,
        )
        outcome = session.append_transcript(entries)
        assert outcome.durability == "durable"
    return session


@pytest.mark.asyncio
async def test_l4_is_tool_free_bounded_and_commits_one_fine_entry_per_turn(tmp_path) -> None:
    provider = _L4Provider()
    session_service = ApplicationSessionService(
        storage_root=tmp_path,
        project_key="test-project",
        instruction_loader=None,
    )
    application = UthCodeApplication(
        provider,
        configuration=EffectiveConfig.single_model(
            "configured/ref",
            remote_id="frozen-model",
            context_window=6_000,
            max_output_tokens=256,
        ),
        session_service=session_service,
    )
    session = _seed_session(application)

    result = await application.create_run().start_turn("current fact").result()

    assert result.status.value == "completed"
    compact_requests = [
        request
        for request in provider.requests
        if request.metadata.get("context_compaction_request") is True
    ]
    ordinary_requests = [
        request
        for request in provider.requests
        if request.metadata.get("context_compaction_request") is not True
    ]
    assert compact_requests
    assert ordinary_requests
    assert len(compact_requests) <= 4
    assert all(request.tools == () for request in compact_requests)
    assert all(request.model == "frozen-model" for request in compact_requests)
    assert all(request.metadata["context_gate"]["hard_safe"] is True for request in compact_requests)

    timeline = session.timeline
    assert timeline.active_checkpoint is not None
    assert isinstance(timeline.records[-1], ActiveCheckpoint)
    assert timeline.fine_entries
    covered_turns = {
        turn_id
        for request in compact_requests
        for turn_id in request.metadata["context_compaction_epoch_turns"]
    }
    assert {entry.turn_id for entry in timeline.fine_entries} == covered_turns
    assert len(timeline.fine_entries) == len(
        {entry.turn_id for entry in timeline.fine_entries}
    )
    assert all(len(entry.refs) == 1 for entry in timeline.fine_entries)
    assert all(entry.refs[0].session_id == session.session_id for entry in timeline.fine_entries)
    assert ordinary_requests[-1].metadata["context_gate"]["hard_safe"] is True
    compaction_note = ordinary_requests[-1].metadata["context_compaction"]
    assert compaction_note["attempted"] is True
    assert isinstance(compaction_note["previous_estimate"], int)
    assert isinstance(compaction_note["headroom"], int)
    assert compaction_note["headroom"] > 0


@pytest.mark.asyncio
async def test_invalid_l4_coverage_has_no_timeline_commit() -> None:
    entries = tuple(
        TranscriptEntry(
            "invalid-l4",
            index,
            f"turn-{index}",
            TranscriptKind.USER_MESSAGE,
            {"text": f"fact-{index}"},
            semantic_unit_id=f"turn-{index}",
        )
        for index in range(1, 3)
    )
    transcript = Transcript("invalid-l4", entries)
    service = ApplicationContextService(
        compactor=ContextCompactor(token_estimator=lambda _text: 1)
    )
    commits = 0

    async def summarize(_epoch: CompactionEpoch) -> str:
        return json.dumps(
            {
                "entries": [{"turn_id": "turn-1", "summary": "only one"}],
                "coverage": ["turn-1"],
            }
        )

    def commit(_result: CompactionResult) -> bool:
        nonlocal commits
        commits += 1
        return True

    result = await service.compact_async(
        transcript,
        session_id=transcript.session_id,
        summarize=summarize,
        commit=commit,
    )

    assert result.changed is False
    assert result.failure == "repeated_failure"
    assert result.timeline is None
    assert commits == 0
    assert all(
        event.get("failure") in {"compaction_result_invalid", "repeated_failure"}
        for event in service.public_diagnostics()["compaction"]["events"]
    )


@pytest.mark.asyncio
async def test_cancelled_l4_stops_without_a_pseudo_checkpoint() -> None:
    transcript = Transcript(
        "cancelled-l4",
        (
            TranscriptEntry(
                "cancelled-l4",
                1,
                "turn-1",
                TranscriptKind.USER_MESSAGE,
                {"text": "fact"},
                semantic_unit_id="turn-1",
            ),
        ),
    )
    service = ApplicationContextService(
        compactor=ContextCompactor(token_estimator=lambda _text: 1)
    )
    cancellation = CancellationToken()
    cancellation.cancel()

    async def summarize(_epoch: CompactionEpoch) -> str:
        raise AssertionError("cancelled compaction must not call the Provider")

    result = await service.compact_async(
        transcript,
        session_id=transcript.session_id,
        summarize=summarize,
        cancellation=cancellation,
    )

    assert result.changed is False
    assert result.failure == "compaction_cancelled"
    assert result.timeline is None


async def _assert_mid_call_compaction_cancellation(
    failure: BaseException,
) -> None:
    transcript = Transcript(
        "mid-call-cancelled-l4",
        (
            TranscriptEntry(
                "mid-call-cancelled-l4",
                1,
                "turn-1",
                TranscriptKind.USER_MESSAGE,
                {"text": "fact"},
                semantic_unit_id="turn-1",
            ),
        ),
    )
    transcript_before = transcript
    service = ApplicationContextService(
        compactor=ContextCompactor(token_estimator=lambda _text: 1)
    )
    cancellation = CancellationToken()
    commit_candidates: list[CompactionResult] = []
    continue_calls = 0
    summarize_calls = 0

    async def summarize(_epoch: CompactionEpoch) -> str:
        nonlocal summarize_calls
        summarize_calls += 1
        assert cancellation.cancelled is False
        raise failure

    def commit(candidate: CompactionResult) -> bool:
        commit_candidates.append(candidate)
        return True

    def should_continue(_timeline: Timeline) -> bool:
        nonlocal continue_calls
        continue_calls += 1
        return True

    with pytest.raises(type(failure)):
        await service.compact_async(
            transcript,
            session_id=transcript.session_id,
            summarize=summarize,
            commit=commit,
            should_continue=should_continue,
            cancellation=cancellation,
        )

    assert summarize_calls == 1
    assert cancellation.cancelled is False
    assert commit_candidates == []
    assert continue_calls == 0
    assert transcript == transcript_before


@pytest.mark.asyncio
async def test_generation_cancelled_during_l4_summarize_is_propagated_once() -> None:
    await _assert_mid_call_compaction_cancellation(GenerationCancelled())


@pytest.mark.asyncio
async def test_asyncio_cancelled_error_during_l4_summarize_is_propagated_once() -> None:
    await _assert_mid_call_compaction_cancellation(asyncio.CancelledError())


@pytest.mark.asyncio
async def test_mid_call_l4_generation_cancelled_uses_agent_run_cancel_exit_without_ordinary_request(
    tmp_path,
) -> None:
    provider = _L4Provider(compaction_failure=GenerationCancelled())
    session_service = ApplicationSessionService(
        storage_root=tmp_path,
        project_key="mid-call-cancelled-app",
        instruction_loader=None,
    )
    application = UthCodeApplication(
        provider,
        configuration=EffectiveConfig.single_model(
            "configured/ref",
            remote_id="frozen-model",
            context_window=6_000,
            max_output_tokens=256,
        ),
        session_service=session_service,
    )
    session = _seed_session(application)
    run = application.create_run(run_id="mid-call-cancelled-run")

    result = await run.start_turn("current fact").result()

    compact_requests = [
        request
        for request in provider.requests
        if request.metadata.get("context_compaction_request") is True
    ]
    ordinary_requests = [
        request
        for request in provider.requests
        if request.metadata.get("context_compaction_request") is not True
    ]
    assert result.status is RunStatus.CANCELLED
    assert run.snapshot().status is RunStatus.CANCELLED
    assert len(compact_requests) == 1
    assert provider.compaction_token_cancelled == [False]
    assert ordinary_requests == []
    assert session.timeline.records == ()
    assert session.timeline.fine_entries == ()
    assert session.timeline.active_checkpoint is None


@pytest.mark.asyncio
async def test_l4_catchup_commits_multiple_epochs_and_stops_at_no_progress() -> None:
    entries = tuple(
        TranscriptEntry(
            "multi-epoch",
            index,
            f"turn-{index}",
            TranscriptKind.USER_MESSAGE,
            {"text": f"fact-{index}"},
            semantic_unit_id=f"turn-{index}",
        )
        for index in range(1, 4)
    )
    transcript = Transcript("multi-epoch", entries)
    service = ApplicationContextService(
        compactor=ContextCompactor(
            token_estimator=lambda text: text.count('"unit_id"') * 10 + 1
        )
    )
    summarized: list[tuple[str, ...]] = []
    rebuilt: list[int] = []

    async def summarize(epoch: CompactionEpoch) -> object:
        summarized.append(epoch.turn_ids)
        return {
            "entries": [
                {"turn_id": turn_id, "summary": "ok"}
                for turn_id in epoch.turn_ids
            ],
            "coverage": list(epoch.turn_ids),
        }

    def should_continue(timeline: Timeline) -> bool:
        rebuilt.append(len(timeline.fine_entries))
        return len(rebuilt) < 3

    result = await service.compact_async(
        transcript,
        session_id=transcript.session_id,
        summarize=summarize,
        should_continue=should_continue,
        max_epochs=4,
        input_budget=25,
        output_reserve=5,
        summary_hard_cap=5,
    )

    assert result.changed is True
    assert result.failure is None
    assert summarized == [("turn-1",), ("turn-2",), ("turn-3",)]
    assert rebuilt == [1, 2, 3]
    assert result.timeline is not None
    assert [entry.turn_id for entry in result.timeline.fine_entries] == [
        "turn-1",
        "turn-2",
        "turn-3",
    ]

    async def never_called(_epoch: CompactionEpoch) -> str:
        raise AssertionError("no-safe-epoch must not call the summarizer")

    no_safe = await service.compact_async(
        transcript,
        timeline=result.timeline,
        session_id=transcript.session_id,
        summarize=never_called,
    )
    assert no_safe.changed is False
    assert no_safe.failure == "no_safe_epoch"
    assert no_safe.timeline == result.timeline


@pytest.mark.asyncio
async def test_l4_no_progress_does_not_create_a_pseudo_checkpoint() -> None:
    transcript = Transcript(
        "no-progress",
        (
            TranscriptEntry(
                "no-progress",
                1,
                "turn-1",
                TranscriptKind.USER_MESSAGE,
                {"text": "fact"},
                semantic_unit_id="turn-1",
            ),
        ),
    )
    service = ApplicationContextService(
        compactor=ContextCompactor(token_estimator=lambda _text: 1)
    )
    commit_calls = 0

    async def summarize(_epoch: CompactionEpoch) -> str:
        return "bounded summary"

    def commit(_candidate: CompactionResult) -> CompactionResult:
        nonlocal commit_calls
        commit_calls += 1
        return CompactionResult(
            timeline=Timeline(transcript.session_id),
            summary=None,
            changed=True,
        )

    result = await service.compact_async(
        transcript,
        session_id=transcript.session_id,
        summarize=summarize,
        commit=commit,
    )

    assert commit_calls == 1
    assert result.changed is False
    assert result.failure == "no_progress"
    assert result.timeline is None


@pytest.mark.asyncio
async def test_hard_unsafe_ordinary_request_never_streams_to_provider(tmp_path) -> None:
    provider = _L4Provider()
    session_service = ApplicationSessionService(
        storage_root=tmp_path,
        project_key="hard-unsafe",
        instruction_loader=None,
    )
    application = UthCodeApplication(
        provider,
        configuration=EffectiveConfig.single_model(
            "configured/ref",
            remote_id="frozen-model",
            context_window=1_000,
            max_output_tokens=256,
        ),
        session_service=session_service,
    )
    _seed_session(application, count=1)

    result = await application.create_run().start_turn("current fact").result()

    assert result.status.value == "failed"
    assert provider.requests == []


@pytest.mark.asyncio
async def test_l4_does_not_skip_an_incomplete_unit_to_reach_later_turn() -> None:
    transcript = Transcript(
        "incomplete-boundary",
        (
            TranscriptEntry(
                "incomplete-boundary",
                1,
                "turn-1",
                TranscriptKind.USER_MESSAGE,
                {"text": "open"},
                commit_boundary=False,
                semantic_unit_id="turn-1",
            ),
            TranscriptEntry(
                "incomplete-boundary",
                2,
                "turn-2",
                TranscriptKind.USER_MESSAGE,
                {"text": "closed"},
                semantic_unit_id="turn-2",
            ),
        ),
    )
    service = ApplicationContextService(
        compactor=ContextCompactor(token_estimator=lambda _text: 1)
    )

    async def never_called(_epoch: CompactionEpoch) -> str:
        raise AssertionError("an incomplete leading unit must stop the epoch")

    result = await service.compact_async(
        transcript,
        session_id=transcript.session_id,
        summarize=never_called,
    )

    assert result.changed is False
    assert result.failure == "no_safe_epoch"
    assert result.timeline is None


@pytest.mark.asyncio
async def test_auto_pressure_unresolved_but_hard_safe_still_sends_with_reason(tmp_path) -> None:
    provider = _L4Provider(safe_ordinary_count=True)
    session_service = ApplicationSessionService(
        storage_root=tmp_path,
        project_key="auto-unresolved",
        instruction_loader=None,
    )
    application = UthCodeApplication(
        provider,
        configuration=EffectiveConfig.single_model(
            "configured/ref",
            remote_id="frozen-model",
            context_window=6_000,
            max_output_tokens=256,
        ),
        session_service=session_service,
    )
    session = application.create_session("auto-unresolved-session")

    result = await application.create_run().start_turn("x" * 30_000).result()

    assert result.status.value == "completed"
    assert len(provider.requests) == 1
    request = provider.requests[0]
    assert request.metadata["context_gate"]["hard_safe"] is True
    assert request.metadata["context_gate"]["auto_pressure"] is True
    note = request.metadata["context_compaction"]
    assert note["attempted"] is True
    assert note["auto_pressure_unresolved"] is True
    assert note["failure"] == "no_safe_epoch"
    assert session.timeline.active_checkpoint is None
