from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from types import SimpleNamespace

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
    EpochMacroSummary,
    SemanticEntry,
    Timeline,
    Transcript,
    TranscriptEntry,
    TranscriptKind,
)
from uthcode.core.provider import (
    CancellationToken,
    ContextOverflowError,
    FinishReason,
    GenerationCancelled,
    GenerationCompleted,
    GenerationRequest,
    ModelLimits,
    ProviderEvent,
    ProviderIdentity,
    ProviderResponse,
    ToolCallPart,
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
        compaction_summary: str | None = None,
        max_input_tokens: int = 6_000,
        pressure_extra: int = 4_000,
    ) -> None:
        self.identity = ProviderIdentity("fake", "l4", "provider-model")
        self.requests: list[GenerationRequest] = []
        self._safe_ordinary_count = safe_ordinary_count
        self._compaction_failure = compaction_failure
        self._compaction_summary = compaction_summary
        self._max_input_tokens = max_input_tokens
        self._pressure_extra = pressure_extra
        self.compaction_token_cancelled: list[bool] = []

    def resolve_model_limits(self, _model: str) -> ModelLimits:
        return ModelLimits(
            max_input_tokens=self._max_input_tokens,
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
            return estimate + self._pressure_extra
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
            summary = self._compaction_summary
            payload = {
                "entries": [
                    {
                        "turn_id": turn_id,
                        "summary": summary or f"summary for {turn_id}",
                    }
                    for turn_id in turn_ids
                ],
                "coverage": list(turn_ids),
            }
            yield _completed(json.dumps(payload, ensure_ascii=False))
            return
        yield _completed("ordinary answer")


class _L5Provider:
    def __init__(self) -> None:
        self.identity = ProviderIdentity("fake", "l5", "provider-model")
        self.requests: list[GenerationRequest] = []

    def resolve_model_limits(self, _model: str) -> ModelLimits:
        return ModelLimits(max_input_tokens=6_000, max_output_tokens=2_048, source="test.l5")

    def count_input_tokens(self, request: GenerationRequest) -> int:
        if request.metadata.get("context_compaction_request") is True:
            return account_generation_request(request).input_tokens
        return 1

    async def stream(
        self,
        request: GenerationRequest,
        *,
        cancellation: CancellationToken,
    ) -> AsyncIterator[ProviderEvent]:
        self.requests.append(request)
        cancellation.raise_if_cancelled()
        if request.metadata.get("context_compaction_level") == "L5":
            turns = tuple(
                value
                for value in request.metadata.get("context_timeline_aging_epoch_turns", ())
                if isinstance(value, str)
            )
            yield _completed(json.dumps({"summary": "macro summary", "coverage": list(turns)}))
            return
        yield _completed("ordinary answer")


class _SessionAwareScriptedProvider:
    def __init__(self, session_service: ApplicationSessionService) -> None:
        self.identity = ProviderIdentity("fake", "session-aware", "provider-model")
        self.session_service = session_service
        self.requests: list[GenerationRequest] = []
        self.observed_transcript_lengths: list[int] = []
        self.scripts = (
            (
                GenerationCompleted(
                    ProviderResponse(
                        message=Message(
                            "assistant",
                            (ToolCallPart("unknown-1", "UnknownTool", {}),),
                        ),
                        usage=Usage(),
                        finish_reason=FinishReason.TOOL_CALLS,
                    )
                ),
            ),
            (_completed("terminal answer"),),
        )

    def resolve_model_limits(self, _model: str) -> ModelLimits:
        return ModelLimits(max_input_tokens=1_000_000, source="test.session-aware")

    async def stream(
        self,
        request: GenerationRequest,
        *,
        cancellation: CancellationToken,
    ) -> AsyncIterator[ProviderEvent]:
        self.requests.append(request)
        active = self.session_service.active_session
        assert active is not None
        self.observed_transcript_lengths.append(len(active.transcript.entries))
        cancellation.raise_if_cancelled()
        index = min(len(self.requests) - 1, len(self.scripts) - 1)
        for event in self.scripts[index]:
            cancellation.raise_if_cancelled()
            yield event


class _OverflowRecoveryProvider:
    def __init__(
        self,
        *,
        ordinary_overflows: int,
        compaction_summary: str | None = None,
        max_input_tokens: int = 6_000,
    ) -> None:
        self.identity = ProviderIdentity("fake", "overflow", "provider-model")
        self.ordinary_overflows = ordinary_overflows
        self.compaction_summary = compaction_summary
        self.max_input_tokens = max_input_tokens
        self.requests: list[GenerationRequest] = []

    def resolve_model_limits(self, _model: str) -> ModelLimits:
        return ModelLimits(
            max_input_tokens=self.max_input_tokens,
            max_output_tokens=2_048,
            source="test.overflow",
        )

    def count_input_tokens(self, request: GenerationRequest) -> int:
        return account_generation_request(request).input_tokens

    async def stream(
        self,
        request: GenerationRequest,
        *,
        cancellation: CancellationToken,
    ) -> AsyncIterator[ProviderEvent]:
        self.requests.append(request)
        cancellation.raise_if_cancelled()
        if request.metadata.get("context_compaction_request") is True:
            turn_ids = tuple(
                value
                for value in request.metadata.get("context_compaction_epoch_turns", ())
                if isinstance(value, str)
            )
            payload = {
                "entries": [
                    {
                        "turn_id": turn_id,
                        "summary": self.compaction_summary or f"summary for {turn_id}",
                    }
                    for turn_id in turn_ids
                ],
                "coverage": list(turn_ids),
            }
            yield _completed(json.dumps(payload, ensure_ascii=False))
            return
        ordinary_calls = sum(
            1
            for item in self.requests
            if item.metadata.get("context_compaction_request") is not True
        )
        if ordinary_calls <= self.ordinary_overflows:
            raise ContextOverflowError()
        yield _completed("overflow recovered")


class _PostToolOverflowProvider:
    def __init__(self, session_service: ApplicationSessionService) -> None:
        self.identity = ProviderIdentity("fake", "post-tool-overflow", "provider-model")
        self.session_service = session_service
        self.requests: list[GenerationRequest] = []
        self.observed_transcript_entries: list[tuple[TranscriptEntry, ...]] = []

    def resolve_model_limits(self, _model: str) -> ModelLimits:
        return ModelLimits(
            max_input_tokens=1_000_000,
            max_output_tokens=2_048,
            source="test.post-tool-overflow",
        )

    def count_input_tokens(self, request: GenerationRequest) -> int:
        return account_generation_request(request).input_tokens

    async def stream(
        self,
        request: GenerationRequest,
        *,
        cancellation: CancellationToken,
    ) -> AsyncIterator[ProviderEvent]:
        self.requests.append(request)
        active = self.session_service.active_session
        assert active is not None
        self.observed_transcript_entries.append(tuple(active.transcript.entries))
        cancellation.raise_if_cancelled()
        if request.metadata.get("context_compaction_request") is True:
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
        ordinary_calls = sum(
            1
            for item in self.requests
            if item.metadata.get("context_compaction_request") is not True
        )
        if ordinary_calls == 1:
            yield GenerationCompleted(
                ProviderResponse(
                    message=Message(
                        "assistant",
                        (ToolCallPart("unknown-post-tool", "UnknownTool", {}),),
                    ),
                    usage=Usage(),
                    finish_reason=FinishReason.TOOL_CALLS,
                )
            )
            return
        if ordinary_calls == 2:
            raise ContextOverflowError()
        yield _completed("post-tool overflow recovered")


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


def _assert_timeline_refs_are_complete(session) -> None:
    for record in session.timeline.records:
        for ref in getattr(record, "refs", ()):
            assert session.transcript.select(
                ref.sequence_start,
                ref.sequence_end,
                complete_only=True,
            )


@pytest.mark.asyncio
async def test_w05_persists_closed_facts_before_provider_and_appends_terminal_tail(tmp_path) -> None:
    session_service = ApplicationSessionService(
        storage_root=tmp_path,
        project_key="w05-persistence",
        instruction_loader=None,
    )
    provider = _SessionAwareScriptedProvider(session_service)
    application = UthCodeApplication(provider, session_service=session_service)
    session = application.create_session("w05-persistence-session")

    result = await application.create_run().start_turn("first request").result()

    assert result.status.value == "completed"
    assert len(provider.observed_transcript_lengths) == 2
    assert provider.observed_transcript_lengths[0] > 0
    assert provider.observed_transcript_lengths[1] > provider.observed_transcript_lengths[0]
    final_entries = session.transcript.entries
    message_ids = tuple(
        entry.payload.get("message_id")
        for entry in final_entries
        if isinstance(entry.payload.get("message_id"), str)
    )
    assert len(message_ids) == len(set(message_ids))
    assert len(final_entries) > provider.observed_transcript_lengths[-1]


@pytest.mark.asyncio
async def test_w05_manual_compact_is_async_low_pressure_and_noop_without_candidate(tmp_path) -> None:
    provider = _L4Provider(safe_ordinary_count=True)
    session_service = ApplicationSessionService(
        storage_root=tmp_path,
        project_key="w05-manual-compact",
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
    session = _seed_session(application, count=1)

    first = await application.compact_session()
    records_after_first = session.timeline.records
    second = await application.compact_session()

    assert first.changed is True
    assert first.failure is None
    assert second.changed is False
    assert second.failure is None
    assert session.timeline.records == records_after_first
    assert len(
        [
            request
            for request in provider.requests
            if request.metadata.get("context_compaction_request") is True
        ]
    ) == 1


@pytest.mark.asyncio
async def test_w05_context_overflow_recovers_once_then_retries_with_frozen_limits(tmp_path) -> None:
    provider = _OverflowRecoveryProvider(ordinary_overflows=1)
    session_service = ApplicationSessionService(
        storage_root=tmp_path,
        project_key="w05-overflow",
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
    session = _seed_session(application, count=1)

    result = await application.create_run().start_turn("overflow once").result()

    ordinary = [
        request
        for request in provider.requests
        if request.metadata.get("context_compaction_request") is not True
    ]
    compact = [
        request
        for request in provider.requests
        if request.metadata.get("context_compaction_request") is True
    ]
    assert result.status.value == "completed"
    assert len(ordinary) == 2
    assert len(compact) == 1
    assert compact[0].tools == ()
    assert compact[0].metadata["context_gate"]["hard_safe"] is True
    assert ordinary[0].metadata["context_budget"] == ordinary[1].metadata["context_budget"]
    assert result.turn_id not in compact[0].metadata["context_compaction_epoch_turns"]
    assert compact[0].metadata["context_compaction_epoch_turns"] == ["turn-1"]

    application.close()
    reopened = application.resume_session("l4-session")
    _assert_timeline_refs_are_complete(reopened)
    assert result.turn_id not in {
        entry.turn_id for entry in reopened.timeline.fine_entries
    }
    application.close()


@pytest.mark.asyncio
async def test_w05_post_tool_overflow_excludes_whole_active_turn_and_reloads(tmp_path) -> None:
    session_service = ApplicationSessionService(
        storage_root=tmp_path,
        project_key="w05-post-tool-overflow",
        instruction_loader=None,
    )
    provider = _PostToolOverflowProvider(session_service)
    application = UthCodeApplication(
        provider,
        configuration=EffectiveConfig.single_model(
            "configured/ref",
            remote_id="frozen-model",
            context_window=1_000_000,
            max_output_tokens=256,
        ),
        session_service=session_service,
    )
    _seed_session(application, count=1)

    result = await application.create_run().start_turn("post-tool overflow").result()

    ordinary = [
        request
        for request in provider.requests
        if request.metadata.get("context_compaction_request") is not True
    ]
    compact = [
        request
        for request in provider.requests
        if request.metadata.get("context_compaction_request") is True
    ]
    assert result.status is RunStatus.COMPLETED
    assert len(ordinary) == 3
    assert len(compact) == 1
    assert provider.observed_transcript_entries[1]
    active_entries = tuple(
        entry
        for entry in provider.observed_transcript_entries[1]
        if entry.turn_id == result.turn_id
    )
    assert {entry.kind for entry in active_entries} >= {
        TranscriptKind.TOOL_CALL,
        TranscriptKind.TOOL_RESULT,
    }
    assert compact[0].metadata["context_compaction_epoch_turns"] == ["turn-1"]
    assert result.turn_id not in compact[0].metadata["context_compaction_epoch_turns"]

    application.close()
    reopened = application.resume_session("l4-session")
    _assert_timeline_refs_are_complete(reopened)
    assert result.turn_id not in {
        entry.turn_id for entry in reopened.timeline.fine_entries
    }
    application.close()


@pytest.mark.asyncio
async def test_w05_second_context_overflow_stops_without_mutating_limits(tmp_path) -> None:
    provider = _OverflowRecoveryProvider(ordinary_overflows=2)
    session_service = ApplicationSessionService(
        storage_root=tmp_path,
        project_key="w05-overflow-twice",
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
    _seed_session(application, count=1)

    result = await application.create_run().start_turn("overflow twice").result()

    ordinary = [
        request
        for request in provider.requests
        if request.metadata.get("context_compaction_request") is not True
    ]
    compact = [
        request
        for request in provider.requests
        if request.metadata.get("context_compaction_request") is True
    ]
    assert result.status.value != "completed"
    assert len(ordinary) == 2
    assert len(compact) == 1
    assert ordinary[0].metadata["context_budget"] == ordinary[1].metadata["context_budget"]


@pytest.mark.asyncio
async def test_w05_transcript_append_failure_retries_same_batch_identity_in_fifo_order(tmp_path, monkeypatch) -> None:
    provider = _L4Provider(safe_ordinary_count=True)
    session_service = ApplicationSessionService(
        storage_root=tmp_path,
        project_key="w05-persistence-retry",
        instruction_loader=None,
    )
    application = UthCodeApplication(provider, session_service=session_service)
    application.create_session("w05-persistence-retry-session")
    real_persist = application._persist_run_messages
    calls: list[tuple[tuple[Message, ...], str | None, str]] = []

    def flaky_persist(messages, *, session_id, turn_id):  # type: ignore[no-untyped-def]
        calls.append((tuple(messages), session_id, turn_id))
        if len(calls) == 1:
            return SimpleNamespace(
                persisted_message_count=0,
                transcript_durability="not_durable",
            )
        return real_persist(messages, session_id=session_id, turn_id=turn_id)

    monkeypatch.setattr(application, "_persist_run_messages", flaky_persist)
    result = await application.create_run().start_turn("retry this closed fact").result()

    assert result.status.value != "completed"
    assert len(provider.requests) == 0
    assert len(calls) == 2
    assert calls[0][1:] == calls[1][1:]
    assert calls[0][0] == calls[1][0]
    assert application.diagnostics()["history_persistence"]["status"] == "committed"  # type: ignore[index]


@pytest.mark.asyncio
async def test_w05_unknown_transcript_durability_quarantines_session_and_blocks_new_run(tmp_path, monkeypatch) -> None:
    provider = _L4Provider(safe_ordinary_count=True)
    session_service = ApplicationSessionService(
        storage_root=tmp_path,
        project_key="w05-persistence-unknown",
        instruction_loader=None,
    )
    application = UthCodeApplication(provider, session_service=session_service)
    session = application.create_session("w05-persistence-unknown-session")

    def unknown_persist(messages, *, session_id, turn_id):  # type: ignore[no-untyped-def]
        del messages, session_id, turn_id
        session._quarantine_unknown_durability()
        return SimpleNamespace(
            persisted_message_count=0,
            transcript_durability="unknown",
        )

    monkeypatch.setattr(application, "_persist_run_messages", unknown_persist)
    result = await application.create_run().start_turn("unknown durability").result()

    assert result.status.value != "completed"
    assert len(provider.requests) == 0
    assert session.durability_unknown is True
    with pytest.raises(RuntimeError, match="durability is unknown"):
        application.create_run().start_turn("must not start")


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
    assert result.turn_id not in covered_turns

    application.close()
    reopened = application.resume_session("l4-session")
    _assert_timeline_refs_are_complete(reopened)
    assert result.turn_id not in {
        entry.turn_id for entry in reopened.timeline.fine_entries
    }
    application.close()


@pytest.mark.asyncio
async def test_l5_ages_fine_timeline_before_ordinary_request_at_low_pressure(tmp_path) -> None:
    provider = _L5Provider()
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
    session = application.create_session("l5-session")
    entries = transcript_entries_for_message(
        session.session_id,
        "turn-1",
        session.transcript.last_sequence + 1,
        Message("user", (TextPart("raw fact"),)),
    )
    assert session.append_transcript(entries).durability == "durable"
    fine = SemanticEntry(
        "turn-1",
        "fine-" + "x" * 2_000,
        (session.transcript.reference(1, 1),),
        session_id=session.session_id,
    )
    assert session.append_timeline_transaction(
        (fine,),
        ActiveCheckpoint("turn-1", ("turn-1",), session_id=session.session_id),
    ).durability == "durable"

    result = await application.create_run().start_turn("current fact").result()
    assert result.status is RunStatus.COMPLETED
    assert len(provider.requests) == 2
    aging_request, ordinary_request = provider.requests
    assert aging_request.metadata["context_compaction_level"] == "L5"
    assert aging_request.metadata["context_timeline_aging_request"] is True
    assert result.turn_id not in aging_request.metadata["context_timeline_aging_epoch_turns"]
    assert aging_request.tools == ()
    assert aging_request.model == "frozen-model"
    assert "fine-" not in aging_request.messages[0].parts[0].text
    assert "raw fact" in aging_request.messages[0].parts[0].text
    assert ordinary_request.metadata["context_compaction"]["timeline_aging"]["status"] == "completed"
    assert session.timeline.fine_entries == ()
    assert session.timeline.physical_fine_entries == (fine,)
    assert len(session.timeline.macro_summaries) == 1
    assert isinstance(session.timeline.logical_records[-2], EpochMacroSummary)


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
        compactor=ContextCompactor(token_estimator=len)
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
@pytest.mark.parametrize("extra_tokens", [0, 1])
async def test_l4_equal_or_larger_output_is_a_non_committing_no_reduction(
    extra_tokens: int,
) -> None:
    transcript = Transcript(
        "non-reducing",
        (
            TranscriptEntry(
                "non-reducing",
                1,
                "turn-1",
                TranscriptKind.USER_MESSAGE,
                {"text": "fact"},
                semantic_unit_id="turn-1",
            ),
        ),
    )
    timeline = Timeline(transcript.session_id)
    service = ApplicationContextService(
        compactor=ContextCompactor(token_estimator=len)
    )
    commits = 0

    async def summarize(epoch: CompactionEpoch) -> str:
        summary = "x" * (epoch.input_tokens + extra_tokens)
        return json.dumps(
            {
                "entries": [{"turn_id": "turn-1", "summary": summary}],
                "coverage": ["turn-1"],
            }
        )

    def commit(_candidate: CompactionResult) -> bool:
        nonlocal commits
        commits += 1
        return True

    result = await service.compact_async(
        transcript,
        timeline=timeline,
        session_id=transcript.session_id,
        summarize=summarize,
        commit=commit,
        summary_hard_cap=100_000,
    )

    assert result.changed is False
    assert result.failure == "no_reduction"
    assert result.timeline == timeline
    assert commits == 0
    assert timeline.records == ()


@pytest.mark.asyncio
async def test_w05_auto_non_reduction_is_not_recovered_or_committed(tmp_path) -> None:
    provider = _L4Provider(
        max_input_tokens=1_000_000,
        pressure_extra=1_000_000,
        compaction_summary="x" * 8_000,
    )
    session_service = ApplicationSessionService(
        storage_root=tmp_path,
        project_key="w05-auto-non-reducing",
        instruction_loader=None,
    )
    application = UthCodeApplication(
        provider,
        configuration=EffectiveConfig.single_model(
            "configured/ref",
            remote_id="frozen-model",
            context_window=1_000_000,
            max_output_tokens=256,
        ),
        session_service=session_service,
    )
    session = _seed_session(application, count=1)

    result = await application.create_run().start_turn("auto non-reducing").result()

    compact = [
        request
        for request in provider.requests
        if request.metadata.get("context_compaction_request") is True
    ]
    assert result.status is not RunStatus.COMPLETED
    assert len(compact) == 1
    assert session.timeline.records == ()
    assert any(
        event.get("failure") == "no_reduction"
        for event in application.diagnostics()["compaction"]["events"]  # type: ignore[index]
    )


@pytest.mark.asyncio
async def test_w05_overflow_non_reduction_does_not_retry_or_commit(tmp_path) -> None:
    provider = _OverflowRecoveryProvider(
        ordinary_overflows=1,
        max_input_tokens=1_000_000,
        compaction_summary="x" * 8_000,
    )
    session_service = ApplicationSessionService(
        storage_root=tmp_path,
        project_key="w05-overflow-non-reducing",
        instruction_loader=None,
    )
    application = UthCodeApplication(
        provider,
        configuration=EffectiveConfig.single_model(
            "configured/ref",
            remote_id="frozen-model",
            context_window=1_000_000,
            max_output_tokens=256,
        ),
        session_service=session_service,
    )
    session = _seed_session(application, count=1)

    result = await application.create_run().start_turn("overflow non-reducing").result()

    ordinary = [
        request
        for request in provider.requests
        if request.metadata.get("context_compaction_request") is not True
    ]
    compact = [
        request
        for request in provider.requests
        if request.metadata.get("context_compaction_request") is True
    ]
    assert result.status is not RunStatus.COMPLETED
    assert len(ordinary) == 1
    assert len(compact) == 1
    assert session.timeline.records == ()
    assert any(
        event.get("failure") == "no_reduction"
        for event in application.diagnostics()["compaction"]["events"]  # type: ignore[index]
    )


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
