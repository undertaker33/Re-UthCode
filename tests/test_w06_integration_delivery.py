from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from uthcode.application import EffectiveConfig, GenerationCompleted, Message, ProviderEvent, ProviderIdentity, ProviderResponse, TextPart, Usage, create_application
from uthcode.application.history import transcript_entries_for_message
from uthcode.application.instructions import InstructionLoader, InstructionSourceNotFoundError
from uthcode.application.runtime_context import ApplicationRuntimeContext
from uthcode.core.history import TranscriptKind
from uthcode.core.provider import CancellationToken, FinishReason, GenerationRequest, ModelLimits
from uthcode.integrations.instruction_files import InstructionFileReader
from uthcode.integrations.session_files import SessionFileStore


def _completed(text: str = "answer") -> GenerationCompleted:
    return GenerationCompleted(ProviderResponse(Message("assistant", (TextPart(text),)), finish_reason=FinishReason.STOP, usage=Usage(input_tokens=11, output_tokens=7, total_tokens=18)))


class _Provider:
    def __init__(self, text: str = "answer") -> None:
        self.identity = ProviderIdentity("fake", "w06", "fake-model")
        self.text = text
        self.requests: list[GenerationRequest] = []

    def resolve_model_limits(self, _model: str) -> ModelLimits:
        return ModelLimits(max_input_tokens=1_000_000, source="test.runtime")

    async def stream(self, request: GenerationRequest, *, cancellation: CancellationToken) -> AsyncIterator[ProviderEvent]:
        self.requests.append(request)
        cancellation.raise_if_cancelled()
        yield _completed(self.text)


def _build_application(project: Path, sessions: SessionFileStore, provider: _Provider):
    user_root = project.parent / "home" / ".uthcode"
    user_root.mkdir(parents=True, exist_ok=True)
    loader = InstructionLoader(user_root=user_root, project_root=project, reader=InstructionFileReader())
    return create_application(EffectiveConfig.single_model("fake/ref", provider_profile_id="fake", remote_id="fake-model", context_window=1_000_000), provider_builder=lambda _profile, _model: provider, runtime_context=ApplicationRuntimeContext.from_system(workdir=project), instruction_loader=loader, session_store=sessions)


def test_w06_create_fails_closed_on_missing_instruction_include(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "AGENTS.md").write_text('parent\n@include("missing.md")\n', encoding="utf-8")
    sessions = SessionFileStore(tmp_path / "sessions")
    application = _build_application(project, sessions, _Provider())
    try:
        with pytest.raises(InstructionSourceNotFoundError):
            application.create_session("include-fails")
        assert application.session_service.active_session is None  # type: ignore[union-attr]
        assert not sessions.session_path("include-fails").exists()
    finally:
        application.close()


@pytest.mark.asyncio
async def test_formal_run_persists_closed_transcript_facts(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    provider = _Provider("final")
    sessions = SessionFileStore(tmp_path / "sessions")
    application = _build_application(project, sessions, provider)
    try:
        session = application.create_session("persist")
        result = await application.create_run().start_turn("hello").result()
        assert result.final_text == "final"
        assert session.transcript.entries
        assert all(entry.commit_boundary for entry in session.transcript.entries)
        assert not (sessions.session_path("persist") / "history.jsonl").exists()
    finally:
        application.close()


@pytest.mark.asyncio
async def test_resume_uses_transcript_and_starts_a_fresh_run(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    provider = _Provider("resumed")
    sessions = SessionFileStore(tmp_path / "sessions")
    application = _build_application(project, sessions, provider)
    try:
        session = application.create_session("resume")
        entries = transcript_entries_for_message("resume", "seed", 1, Message("user", (TextPart("DURABLE_MARKER"),)))
        session.append_transcript(entries)
        session.close()
        resumed = application.resume_session_for_command("resume")
        assert resumed.transcript.entries == entries
        assert application.create_run().snapshot().iteration_count == 0
        result = await application.create_run().start_turn("new marker").result()
        assert result.final_text == "resumed"
        text = "\n".join(part.text for message in provider.requests[0].messages for part in message.parts if isinstance(part, TextPart))
        assert "DURABLE_MARKER" in text and "new marker" in text
    finally:
        application.close()


def test_transcript_message_groups_keep_tool_call_and_result_together(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    sessions = SessionFileStore(tmp_path / "sessions")
    application = _build_application(project, sessions, _Provider())
    try:
        session = application.create_session("tool-group")
        entries = transcript_entries_for_message("tool-group", "turn", 1, Message("assistant", (TextPart("before"),)))
        session.append_transcript(entries)
        assert [entry.kind for entry in session.transcript.entries] == [TranscriptKind.ASSISTANT_MESSAGE]
    finally:
        application.close()
