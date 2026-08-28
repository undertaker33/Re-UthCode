from __future__ import annotations

from pathlib import Path

import pytest

from uthcode.application import ApplicationRuntimeContext, EffectiveConfig, InstructionLoader, create_application
from uthcode.application.context import ApplicationContextService
from uthcode.core.context import (
    CompactionPolicy,
    ContextCompactor,
    ContextCompilationError,
    ContextCompiler,
    ContextSourceBundle,
    ContextSnapshot,
    messages_from_context_snapshot,
)
from uthcode.core.history import ActiveCheckpoint, SemanticEntry, Timeline, Transcript, TranscriptEntry, TranscriptKind
from uthcode.core.prompt import ContextAuthority, ContextBlock, ContextScope, ContextSourceKind, ContextStability, ProjectInstructionSource, RuntimePromptContext, ToolDefinitionSource
from uthcode.core.planning import BehaviorMode
from uthcode.core.provider import GenerationRequest, Message, TextPart, ToolDefinition
from uthcode.integrations.instruction_files import InstructionFileReader
from uthcode.integrations.session_files import SessionFileStore
from uthcode.integrations.providers.openai_responses import _prompt_cache_key


def _project_source(content: str, epoch: int = 1) -> ProjectInstructionSource:
    block = ContextBlock(ContextSourceKind.PROJECT_INSTRUCTION, ContextAuthority.PROJECT_INSTRUCTION, ContextStability.STABLE, ContextScope.PROJECT, "project/AGENTS.md", content)
    return ProjectInstructionSource((block,), epoch, "persisted-fingerprint", "initial" if epoch == 1 else "instruction_content_changed")


def _transcript() -> Transcript:
    values = (
        TranscriptEntry("session-1", 1, "turn-1", TranscriptKind.USER_MESSAGE, {"text": "new turn"}, semantic_unit_id="turn-1"),
        TranscriptEntry("session-1", 2, "turn-2", TranscriptKind.TOOL_CALL, {"type": "tool_call", "tool_call_id": "call-1", "name": "ReadFile"}, semantic_unit_id="turn-2"),
        TranscriptEntry("session-1", 3, "turn-2", TranscriptKind.TOOL_RESULT, {"type": "tool_result", "tool_call_id": "call-1", "content": "complete result ref"}, semantic_unit_id="turn-2"),
    )
    return Transcript("session-1", values)


def _runtime_block(content: str) -> ContextBlock:
    return ContextBlock(
        ContextSourceKind.RUNTIME_FACT,
        ContextAuthority.RUNTIME,
        ContextStability.DYNAMIC,
        ContextScope.TURN,
        "test:runtime",
        content,
    )


def _history_block(content: str) -> ContextBlock:
    return ContextBlock(
        ContextSourceKind.USER_MESSAGE,
        ContextAuthority.HISTORY,
        ContextStability.DYNAMIC,
        ContextScope.TURN,
        "test:history",
        content,
    )


def test_compiler_is_deterministic_and_keeps_tool_semantic_group_atomic() -> None:
    compiler = ContextCompiler(budget_tokens=258_000, token_estimator=lambda text: 180_000 if '"sequence":' in text else max(1, len(text) // 4))
    tool_source = ToolDefinitionSource((ToolDefinition("ReadFile", "read", {"type": "object"}),))
    sources = ContextSourceBundle(transcript=_transcript(), current_turn=("current user turn",), tool_source=tool_source)
    first = compiler.compile(sources)
    second = compiler.compile(sources)
    assert first == second
    assert first.tool_schema_fingerprint == tool_source.tool_schema_fingerprint
    assert any("call-1" in block.content for block in first.selected_blocks)
    assert all(block.semantic_unit_id is None or not ("call-1" in block.content and block in first.omitted_blocks) for block in first.omitted_blocks)


def test_runtime_and_timeline_changes_do_not_change_stable_prefix() -> None:
    compiler = ContextCompiler()
    project = _project_source("project rule")
    first = compiler.compile(ContextSourceBundle(project_instruction_source=project, current_turn=("hello",)))
    second = compiler.compile(
        ContextSourceBundle(
            project_instruction_source=project,
            current_turn=("hello",),
            runtime_sources=(_runtime_block("runtime fact"),),
        ),
        previous_snapshot=first,
    )
    changed = compiler.compile(ContextSourceBundle(project_instruction_source=_project_source("changed", 2)), previous_snapshot=second)
    assert second.stable_prefix_fingerprint == first.stable_prefix_fingerprint
    assert second.prefix_changed is False
    assert changed.prefix_changed is True


def test_compact_and_conversation_growth_preserve_provider_cache_prefix() -> None:
    transcript = Transcript(
        "cache-session",
        tuple(
            TranscriptEntry(
                "cache-session",
                index,
                f"turn-{index}",
                TranscriptKind.USER_MESSAGE,
                {
                    "role": "user",
                    "part": {"type": "text", "text": f"fact-{index}"},
                },
                semantic_unit_id=f"turn-{index}",
            )
            for index in range(1, 5)
        ),
    )
    project = _project_source("project rule")
    tool = ToolDefinition(
        "ReadFile",
        "read files",
        {"type": "object", "properties": {"path": {"type": "string"}}},
    )
    tool_source = ToolDefinitionSource((tool,))
    compiler = ContextCompiler(token_estimator=lambda text: max(1, len(text) // 20))

    def cache_key(snapshot: ContextSnapshot, model: str = "gpt-test") -> str | None:
        assert snapshot.tool_schema_fingerprint is not None
        request = GenerationRequest(
            messages=messages_from_context_snapshot(snapshot),
            model=model,
            tools=snapshot.tool_definitions,
            metadata={
                "stable_prefix_fingerprint": snapshot.stable_prefix_fingerprint,
                "tool_schema_fingerprint": snapshot.tool_schema_fingerprint,
            },
        )
        return _prompt_cache_key(request, model)

    before = compiler.compile(
        ContextSourceBundle(
            project_instruction_source=project,
            transcript=transcript,
            current_turn=("current user",),
            tool_source=tool_source,
        )
    )
    before_key = cache_key(before)
    assert before_key is not None

    grown_transcript = transcript.append(
        TranscriptEntry(
            "cache-session",
            5,
            "turn-5",
            TranscriptKind.USER_MESSAGE,
            {
                "role": "user",
                "part": {"type": "text", "text": "ordinary conversation growth"},
            },
            semantic_unit_id="turn-5",
        )
    )
    grown = compiler.compile(
        ContextSourceBundle(
            project_instruction_source=project,
            transcript=grown_transcript,
            current_turn=("new current user",),
            tool_source=tool_source,
        ),
        previous_snapshot=before,
    )
    assert grown.stable_prefix_fingerprint == before.stable_prefix_fingerprint
    assert grown.prefix_changed is False
    assert cache_key(grown) == before_key

    compaction = ContextCompactor(
        policy=CompactionPolicy(input_budget=500, output_reserve=50, summary_hard_cap=100),
        token_estimator=lambda text: max(1, len(text) // 20),
    ).compact(transcript, summarize=lambda _text: "bounded summary")
    assert compaction.changed is True
    assert compaction.timeline is not None
    assert compaction.timeline.active_checkpoint is not None
    compacted = compiler.compile(
        ContextSourceBundle(
            project_instruction_source=project,
            transcript=transcript,
            timeline=compaction.timeline,
            current_turn=("current user",),
            tool_source=tool_source,
        ),
        previous_snapshot=before,
    )
    assert compacted.timeline_checkpoint_id == compaction.timeline.active_checkpoint.turn_id
    assert compacted.stable_prefix_fingerprint == before.stable_prefix_fingerprint
    assert compacted.prefix_changed is False
    assert compacted.tool_schema_fingerprint == before.tool_schema_fingerprint
    assert cache_key(compacted) == before_key

    changed_instruction = compiler.compile(
        ContextSourceBundle(
            project_instruction_source=_project_source("changed project rule", 2),
            transcript=transcript,
            timeline=compaction.timeline,
            current_turn=("current user",),
            tool_source=tool_source,
        ),
        previous_snapshot=compacted,
    )
    assert changed_instruction.stable_prefix_fingerprint != before.stable_prefix_fingerprint
    assert changed_instruction.prefix_changed is True
    assert cache_key(changed_instruction) != before_key

    changed_tool = ToolDefinition(
        "ReadFile",
        "read changed files",
        {"type": "object", "properties": {"filename": {"type": "string"}}},
    )
    changed_tool_snapshot = compiler.compile(
        ContextSourceBundle(
            project_instruction_source=project,
            transcript=transcript,
            timeline=compaction.timeline,
            current_turn=("current user",),
            tool_source=ToolDefinitionSource((changed_tool,)),
        ),
        previous_snapshot=compacted,
    )
    assert changed_tool_snapshot.tool_schema_fingerprint != before.tool_schema_fingerprint
    assert cache_key(changed_tool_snapshot) != before_key
    assert cache_key(compacted, model="gpt-other") != before_key


def test_timeline_summary_is_conversation_data_and_raw_tail_remains_visible() -> None:
    transcript = _transcript()
    fine = SemanticEntry("turn-1", "summary of first", (transcript.reference(1, 1),), session_id="session-1")
    timeline = Timeline("session-1").append_transaction((fine,), ActiveCheckpoint("turn-1", ("turn-1",), session_id="session-1"))
    snapshot = ContextCompiler(token_estimator=lambda _text: 1).compile(ContextSourceBundle(transcript=transcript, timeline=timeline, current_turn=("current user",)))
    assert any(block.source_kind is ContextSourceKind.TIMELINE_ENTRY for block in snapshot.selected_blocks)
    assert any(block.semantic_unit_id == "turn-2" for block in snapshot.selected_blocks)
    assert snapshot.timeline_checkpoint_id == "turn-1"
    messages = messages_from_context_snapshot(snapshot)
    assert any("summary of first" in part.text for message in messages for part in message.parts if isinstance(part, TextPart))


def test_current_user_is_protected_and_remains_at_conversation_tail_over_budget() -> None:
    snapshot = ContextCompiler(
        budget_tokens=2,
        token_estimator=lambda text: 300_000 if text == "current user" else 1,
    ).compile(
        ContextSourceBundle(
            transcript=_transcript(),
            current_turn=("other current turn", "current user"),
        )
    )
    assert snapshot.over_budget is True
    assert snapshot.selected_blocks[-1].content == "current user"


def test_compiler_accepts_only_bundle_and_rejects_invalid_source_boundaries() -> None:
    compiler = ContextCompiler()

    with pytest.raises(TypeError, match="sources must be ContextSourceBundle"):
        compiler.compile(object())
    with pytest.raises(TypeError):
        compiler.compile()  # type: ignore[call-arg]
    with pytest.raises(ContextCompilationError, match="Instruction Plane"):
        ContextSourceBundle(instruction_sources=(_history_block("not instruction"),))
    with pytest.raises(TypeError, match="runtime_sources must contain ContextBlock"):
        ContextSourceBundle(runtime_sources=("not a block",))


def test_application_context_service_keeps_current_user_at_tail() -> None:
    snapshot = ApplicationContextService().compile(current_turn=("a", "b"), current_user="user")
    assert [block.content for block in snapshot.conversation_plane][-3:] == ["a", "b", "user"]


def test_context_projection_keeps_contextual_sources_out_of_current_user_tail() -> None:
    snapshot = ContextCompiler().compile(
        ContextSourceBundle(
            current_turn=("？",),
            runtime_sources=(_runtime_block("runtime: deepseek/v4-flash"),),
            environment_sources=(
                ContextBlock(
                    ContextSourceKind.ENVIRONMENT_FACT,
                    ContextAuthority.ENVIRONMENT,
                    ContextStability.DYNAMIC,
                    ContextScope.TURN,
                    "test:environment",
                    "environment: D:/project/Re-UthCode",
                ),
            ),
        )
    )

    messages = messages_from_context_snapshot(snapshot)

    assert messages[-1] == Message("user", (TextPart("？"),))
    assert any(
        message.role == "user"
        and any("runtime: deepseek/v4-flash" in part.text for part in message.parts if isinstance(part, TextPart))
        for message in messages[:-1]
    )
    assert any(
        message.role == "user"
        and any("environment: D:/project/Re-UthCode" in part.text for part in message.parts if isinstance(part, TextPart))
        for message in messages[:-1]
    )


def test_application_request_keeps_current_user_exact_after_runtime_composition() -> None:
    request, _snapshot = ApplicationContextService().compose_generation_request(
        (Message("user", (TextPart("？"),)),),
        run_id="run-current-user",
        runtime_context=RuntimePromptContext(),
        environment_sources=(
            ContextBlock(
                ContextSourceKind.ENVIRONMENT_FACT,
                ContextAuthority.ENVIRONMENT,
                ContextStability.DYNAMIC,
                ContextScope.TURN,
                "test:environment",
                "environment: model=deepseek/v4-flash",
            ),
        ),
    )

    assert request.messages[-1] == Message("user", (TextPart("？"),))


def test_application_composition_keeps_user_identity_across_context_changes_and_turns() -> None:
    service = ApplicationContextService()
    current_user = Message("user", (TextPart("？"),))

    def environment(content: str) -> ContextBlock:
        return ContextBlock(
            ContextSourceKind.ENVIRONMENT_FACT,
            ContextAuthority.ENVIRONMENT,
            ContextStability.DYNAMIC,
            ContextScope.TURN,
            "test:environment",
            content,
        )

    first, _ = service.compose_generation_request(
        (current_user,),
        run_id="context-change-1",
        runtime_context=RuntimePromptContext(behavior_mode=BehaviorMode.DEFAULT),
        environment_sources=(environment("environment: one"),),
    )
    second, _ = service.compose_generation_request(
        (current_user,),
        run_id="context-change-2",
        runtime_context=RuntimePromptContext(behavior_mode=BehaviorMode.PLAN),
        environment_sources=(environment("environment: two"),),
    )

    assert first.messages[-1] == current_user
    assert second.messages[-1] == current_user
    assert first.messages[-1].parts == second.messages[-1].parts == (TextPart("？"),)
    assert any(
        isinstance(part, TextPart) and "environment: one" in part.text
        for message in first.messages[:-1]
        for part in message.parts
    )
    assert any(
        isinstance(part, TextPart) and "environment: two" in part.text
        for message in second.messages[:-1]
        for part in message.parts
    )
    assert any(
        isinstance(part, TextPart) and "当前行为模式：DEFAULT" in part.text
        for message in first.messages[:-1]
        for part in message.parts
    )
    assert any(
        isinstance(part, TextPart) and "当前行为模式：PLAN" in part.text
        for message in second.messages[:-1]
        for part in message.parts
    )

    turns, _ = service.compose_generation_request(
        (
            Message("user", (TextPart("same"),)),
            Message("user", (TextPart("steering"),)),
            Message("user", (TextPart("same"),)),
        ),
        run_id="adjacent-turns",
    )
    non_context_user_texts = tuple(
        part.text
        for message in turns.messages
        if message.role == "user"
        and not (
            len(message.parts) == 1
            and isinstance(message.parts[0], TextPart)
            and message.parts[0].text.startswith("[Context]\n")
        )
        for part in message.parts
        if isinstance(part, TextPart)
    )
    assert non_context_user_texts == ("same", "steering", "same")
    assert turns.messages[-1] == Message("user", (TextPart("same"),))


def test_prompt_has_no_parallel_standalone_system_builder() -> None:
    import uthcode.core.prompt as prompt_module

    assert not hasattr(prompt_module, "build_system_prompt")


def test_application_composes_context_and_resumes_instruction_state(tmp_path: Path) -> None:
    user_root = tmp_path / "home" / ".uthcode"
    project_root = tmp_path / "project"
    nested = project_root / "src"
    user_root.mkdir(parents=True)
    nested.mkdir(parents=True)
    (project_root / "AGENTS.md").write_text("project rule", encoding="utf-8")
    (nested / "AGENTS.md").write_text("nested rule", encoding="utf-8")
    target = nested / "module.py"
    target.write_text("value = 1", encoding="utf-8")
    sessions = SessionFileStore(tmp_path / "sessions")

    def build_loader() -> InstructionLoader:
        return InstructionLoader(user_root=user_root, project_root=project_root, reader=InstructionFileReader())

    app = create_application(EffectiveConfig.single_model("fake/model"), runtime_context=ApplicationRuntimeContext.from_system(workdir=project_root), instruction_loader=build_loader(), session_store=sessions)
    session = app.create_session("session-1")
    loader = app.instruction_loader
    assert loader is not None
    loader.load_for_path(target)
    epoch = loader.instruction_epoch
    fingerprint = loader.stable_prefix_fingerprint
    session.close()
    app.close()
    resumed_app = create_application(EffectiveConfig.single_model("fake/model"), runtime_context=ApplicationRuntimeContext.from_system(workdir=project_root), instruction_loader=build_loader(), session_store=sessions)
    resumed = resumed_app.resume_session("session-1")
    assert resumed.instruction_state.instruction_epoch == epoch
    assert resumed.instruction_state.stable_prefix_fingerprint == fingerprint
    resumed.close()
    resumed_app.close()


def test_application_session_service_allows_only_one_active_session(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    app = create_application(EffectiveConfig.single_model("fake/model"), runtime_context=ApplicationRuntimeContext.from_system(workdir=project_root), session_store=SessionFileStore(tmp_path / "sessions"))
    first = app.create_session("session-1")
    from uthcode.application import SessionActiveError
    with pytest.raises(SessionActiveError):
        app.create_session("session-2")
    first.close()
    app.close()
