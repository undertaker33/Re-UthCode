from __future__ import annotations

from pathlib import Path

import pytest

from uthcode.application import (
    ApplicationRuntimeContext,
    EffectiveConfig,
    InstructionLoader,
    SessionActiveError,
    create_application,
)
from uthcode.application.context import ApplicationContextService
from uthcode.core.context import (
    ContextCompiler,
    ContextSourceBundle,
    UTHCODE_CONTEXT_BUDGET_TOKENS,
)
from uthcode.core.history import CanonicalHistory, HistoryKind
from uthcode.core.prompt import (
    ContextAuthority,
    ContextBlock,
    ContextPlane,
    ContextScope,
    ContextSourceKind,
    ContextStability,
    ProjectInstructionSource,
    RuntimePromptContext,
)
from uthcode.core.provider import ToolDefinition
from uthcode.core.prompt import ToolDefinitionSource
from uthcode.integrations.instruction_files import InstructionFileReader
from uthcode.integrations.session_files import SessionCorruptError, SessionFileStore


def _project_source(content: str, epoch: int) -> ProjectInstructionSource:
    block = ContextBlock(
        source_kind=ContextSourceKind.PROJECT_INSTRUCTION,
        authority=ContextAuthority.PROJECT_INSTRUCTION,
        stability=ContextStability.STABLE,
        scope=ContextScope.PROJECT,
        provenance="project/AGENTS.md",
        content=content,
    )
    # The compiler recomputes the actual prefix fingerprint.  The supplied
    # value models the persisted W01 source contract and is not trusted as a
    # text copy.
    return ProjectInstructionSource((block,), epoch, "persisted-fingerprint", "initial" if epoch == 1 else "instruction_content_changed")


def _history() -> CanonicalHistory:
    history = CanonicalHistory("session-1")
    history = history.append(
        turn_id="turn-1",
        kind=HistoryKind.USER_MESSAGE,
        payload={"text": "new turn"},
    )
    history = history.append(
        turn_id="turn-2",
        kind=HistoryKind.TOOL_CALL,
        payload={"tool_call_id": "call-1", "name": "ReadFile"},
    )
    return history.append(
        turn_id="turn-2",
        kind=HistoryKind.TOOL_RESULT,
        payload={"tool_call_id": "call-1", "content": "complete result ref"},
    )


def test_compiler_is_fixed_budget_deterministic_and_unit_atomic() -> None:
    def estimate(text: str) -> int:
        if '"sequence":1' in text:
            return 180_000
        if '"sequence":2' in text:
            return 180_000
        return max(1, len(text) // 4)

    compiler = ContextCompiler(token_estimator=estimate)
    project = _project_source("project rule", 1)
    tool_source = ToolDefinitionSource((ToolDefinition("ReadFile", "read", {"type": "object"}),))
    sources = ContextSourceBundle(
        project_instruction_source=project,
        history=_history(),
        current_turn=("current user turn",),
        tool_source=tool_source,
    )

    first = compiler.compile(sources)
    second = compiler.compile(sources)

    assert first == second
    assert first.budget_tokens == UTHCODE_CONTEXT_BUDGET_TOKENS
    assert first.token_estimate >= first.stable_prefix_estimated_tokens + first.tool_schema_estimated_tokens
    assert first.tool_schema_fingerprint == tool_source.tool_schema_fingerprint
    assert "ReadFile" not in "\n".join(block.content for block in first.instruction_plane)
    assert any("call-1" in block.content and "complete result ref" in block.content for block in first.selected_blocks)
    assert first.omitted_blocks
    assert all(block.semantic_unit_id is None or "call-1" not in block.content for block in first.omitted_blocks)


def test_budget_is_not_a_model_window_resolver() -> None:
    with pytest.raises(ValueError, match="fixed 258K"):
        ContextCompiler(budget_tokens=1)


def test_runtime_and_projection_changes_do_not_change_stable_prefix() -> None:
    compiler = ContextCompiler()
    project = _project_source("project rule", 1)
    first = compiler.compile(
        ContextSourceBundle(
            project_instruction_source=project,
            current_turn=("hello",),
        )
    )
    second = compiler.compile(
        ContextSourceBundle(
            project_instruction_source=project,
            current_turn=("hello",),
            runtime_sources=(
                ContextBlock(
                    ContextSourceKind.RUNTIME_FACT,
                    ContextAuthority.RUNTIME,
                    ContextStability.DYNAMIC,
                    ContextScope.TURN,
                    "runtime",
                    "new runtime fact",
                ),
            ),
        ),
        previous_snapshot=first,
    )
    changed = compiler.compile(
        ContextSourceBundle(project_instruction_source=_project_source("changed", 2)),
        previous_snapshot=second,
    )

    assert second.stable_prefix_fingerprint == first.stable_prefix_fingerprint
    assert second.instruction_epoch == first.instruction_epoch
    assert second.prefix_changed is False
    assert second.prefix_change_reason == "stable"
    assert changed.prefix_changed is True
    assert changed.instruction_epoch == 2
    assert changed.prefix_change_reason == "instruction_content_changed"
    assert changed.stable_prefix_fingerprint != first.stable_prefix_fingerprint


def test_snapshot_composition_order_is_separate_from_selection_priority() -> None:
    history = CanonicalHistory("session-1")
    history = history.append(
        turn_id="turn-1",
        kind=HistoryKind.USER_MESSAGE,
        payload={"text": "first"},
    )
    history = history.append(
        turn_id="turn-1",
        kind=HistoryKind.ASSISTANT_MESSAGE,
        payload={"text": "answer"},
    )
    projection = history.project(revision=1)
    runtime = ContextBlock(
        ContextSourceKind.RUNTIME_FACT,
        ContextAuthority.RUNTIME,
        ContextStability.DYNAMIC,
        ContextScope.TURN,
        "runtime",
        "runtime fact",
    )
    environment = ContextBlock(
        ContextSourceKind.ENVIRONMENT_FACT,
        ContextAuthority.ENVIRONMENT,
        ContextStability.DYNAMIC,
        ContextScope.TURN,
        "environment",
        "environment fact",
    )

    snapshot = ContextCompiler(token_estimator=lambda _text: 1).compile(
        history=history,
        projection=projection,
        runtime_sources=(runtime,),
        environment_sources=(environment,),
        current_turn=("current user",),
    )

    contents = [block.content for block in snapshot.selected_blocks]
    index_containing = lambda marker: next(index for index, content in enumerate(contents) if marker in content)
    assert index_containing(projection.to_json()) < index_containing('"text":"first"')
    assert index_containing('"text":"first"') < contents.index("runtime fact")
    assert contents.index("runtime fact") < contents.index("environment fact")
    assert contents[-1] == "current user"
    assert all(block.plane is not ContextPlane.INSTRUCTION for block in snapshot.conversation_plane)
    assert runtime not in snapshot.instruction_plane
    assert environment not in snapshot.instruction_plane


def test_core_current_user_is_appended_after_current_turn_blocks() -> None:
    snapshot = ContextCompiler().compile(
        current_turn=("a", "b"),
        current_user="user",
    )

    assert [block.content for block in snapshot.conversation_plane][-3:] == ["a", "b", "user"]

    without_user = ContextCompiler().compile(current_turn=("a", "b"))
    with_explicit_none = ContextCompiler().compile(
        current_turn=("a", "b"),
        current_user=None,
    )
    assert without_user.selected_blocks == with_explicit_none.selected_blocks
    assert all(block.content != "None" for block in with_explicit_none.selected_blocks)


def test_application_context_service_keeps_current_user_at_conversation_tail() -> None:
    snapshot = ApplicationContextService().compile(
        current_turn=("a", "b"),
        current_user="user",
    )

    assert [block.content for block in snapshot.conversation_plane][-3:] == ["a", "b", "user"]
    assert snapshot.selected_blocks[-1].content == "user"


def test_current_user_is_protected_and_remains_at_conversation_tail_over_budget() -> None:
    snapshot = ContextCompiler(
        token_estimator=lambda text: 300_000 if text == "current user" else 1,
    ).compile(
        history=_history(),
        current_turn=("other current turn",),
        current_user="current user",
    )

    assert snapshot.over_budget is True
    assert snapshot.selected_blocks[-2].content == "other current turn"
    assert snapshot.selected_blocks[-1].content == "current user"


def test_recent_history_selection_is_newest_first_but_composed_in_time_order() -> None:
    history = CanonicalHistory("session-1")
    for marker in ("old", "middle", "new"):
        history = history.append(
            turn_id=marker,
            kind=HistoryKind.USER_MESSAGE,
            payload={"marker": marker},
        )

    def estimate(text: str) -> int:
        if any(f'"marker":"{marker}"' in text for marker in ("old", "middle", "new")):
            return 100_000
        return 1

    snapshot = ContextCompiler(token_estimator=estimate).compile(history=history)
    history_blocks = [block for block in snapshot.selected_blocks if block.semantic_unit_id is not None]

    assert len(history_blocks) == 2
    assert '"marker":"middle"' in history_blocks[0].content
    assert '"marker":"new"' in history_blocks[1].content
    assert all('"marker":"old"' not in block.content for block in history_blocks)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"current_turn": ("user",)},
        {"protected_context": ("protected",)},
        {"runtime_sources": ("runtime",)},
        {"environment_sources": ("environment",)},
        {"tool_source": ToolDefinitionSource(())},
        {"history": _history()},
        {"projection": _history().project(revision=1)},
    ],
)
def test_bundle_and_individual_compiler_inputs_are_mutually_exclusive(kwargs: dict[str, object]) -> None:
    with pytest.raises(TypeError, match="ContextSourceBundle or individual"):
        ContextCompiler().compile(ContextSourceBundle(), **kwargs)


def test_unclosed_semantic_unit_is_protected_and_snapshot_does_not_change_history() -> None:
    history = CanonicalHistory("session-1").append(
        turn_id="turn-1",
        kind=HistoryKind.TOOL_CALL,
        payload={"tool_call_id": "call-1", "name": "ReadFile"},
        commit_boundary=False,
    )
    before = history.to_jsonl()
    snapshot = ContextCompiler().compile(ContextSourceBundle(history=history))

    assert snapshot.over_budget is False
    assert snapshot.selected_blocks
    assert snapshot.selected_blocks[-1].semantic_unit_id == "unit-1"
    assert history.to_jsonl() == before


def test_unclosed_tool_unit_stays_before_the_current_user_turn() -> None:
    history = CanonicalHistory("session-1").append(
        turn_id="turn-1",
        kind=HistoryKind.TOOL_CALL,
        payload={"tool_call_id": "call-1", "name": "ReadFile"},
    )

    snapshot = ContextCompiler().compile(history=history, current_turn=("current user",))

    assert snapshot.selected_blocks[-1].content == "current user"
    assert snapshot.selected_blocks[-2].semantic_unit_id == "unit-1"


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
        return InstructionLoader(
            user_root=user_root,
            project_root=project_root,
            reader=InstructionFileReader(),
        )

    config = EffectiveConfig.single_model("fake/model")
    first_app = create_application(
        config,
        runtime_context=ApplicationRuntimeContext.from_system(workdir=project_root),
        instruction_loader=build_loader(),
        session_store=sessions,
    )
    snapshot = first_app.compile_context(current_user="inspect this")
    assert snapshot.budget_tokens == UTHCODE_CONTEXT_BUDGET_TOKENS
    assert snapshot.tool_schema_fingerprint is not None

    session = first_app.create_session("session-1")
    loader = first_app.instruction_loader
    assert loader is not None
    loader.load_for_path(target)
    persisted_epoch = loader.instruction_epoch
    persisted_fingerprint = loader.stable_prefix_fingerprint
    session.close()
    first_app.close()

    second_app = create_application(
        config,
        runtime_context=ApplicationRuntimeContext.from_system(workdir=project_root),
        instruction_loader=build_loader(),
        session_store=sessions,
    )
    resumed = second_app.resume_session("session-1")
    assert resumed.instruction_state.instruction_epoch == persisted_epoch
    assert resumed.instruction_state.stable_prefix_fingerprint == persisted_fingerprint
    assert str(nested.resolve()) in resumed.instruction_state.activated_directory_scopes
    resumed.close()
    second_app.close()

    (nested / "AGENTS.md").unlink()
    third_app = create_application(
        config,
        runtime_context=ApplicationRuntimeContext.from_system(workdir=project_root),
        instruction_loader=build_loader(),
        session_store=sessions,
    )
    changed = third_app.resume_session("session-1")
    assert changed.instruction_state.instruction_epoch == persisted_epoch + 1
    assert changed.instruction_state.change_reason == "instruction_source_removed"
    assert str(nested.resolve()) in changed.instruction_state.activated_directory_scopes
    changed.close()
    third_app.close()


def test_uthcode_application_compile_context_keeps_user_after_runtime_environment_and_turn(
    tmp_path: Path,
) -> None:
    user_root = tmp_path / "home" / ".uthcode"
    project_root = tmp_path / "project"
    user_root.mkdir(parents=True)
    project_root.mkdir(parents=True)
    config = EffectiveConfig.single_model("fake/model")
    environment = ContextBlock(
        ContextSourceKind.ENVIRONMENT_FACT,
        ContextAuthority.ENVIRONMENT,
        ContextStability.DYNAMIC,
        ContextScope.TURN,
        "test:environment",
        "environment fact",
    )
    app = create_application(
        config,
        runtime_context=ApplicationRuntimeContext.from_system(workdir=project_root),
        instruction_loader=InstructionLoader(
            user_root=user_root,
            project_root=project_root,
            reader=InstructionFileReader(),
        ),
        session_store=SessionFileStore(tmp_path / "sessions"),
    )

    try:
        snapshot = app.compile_context(
            runtime_context=RuntimePromptContext(),
            environment_sources=(environment,),
            current_turn=("a", "b"),
            current_user="user",
        )
    finally:
        app.close()

    contents = [block.content for block in snapshot.selected_blocks]
    runtime_index = next(index for index, content in enumerate(contents) if "当前行为模式" in content)
    environment_index = contents.index("environment fact")
    assert contents[runtime_index : environment_index + 1] == [
        contents[runtime_index],
        "environment fact",
    ]
    assert contents[environment_index + 1 :][-3:] == ["a", "b", "user"]
    assert contents[-1] == "user"


def test_application_session_service_allows_only_one_active_session(tmp_path: Path) -> None:
    user_root = tmp_path / "home" / ".uthcode"
    project_root = tmp_path / "project"
    user_root.mkdir(parents=True)
    project_root.mkdir()
    (project_root / "AGENTS.md").write_text("project rule", encoding="utf-8")
    config = EffectiveConfig.single_model("fake/model")
    store = SessionFileStore(tmp_path / "sessions")
    app = create_application(
        config,
        runtime_context=ApplicationRuntimeContext.from_system(workdir=project_root),
        instruction_loader=InstructionLoader(
            user_root=user_root,
            project_root=project_root,
            reader=InstructionFileReader(),
        ),
        session_store=store,
    )
    first = app.create_session("session-1")
    before = store.read_session("session-1").metadata.to_dict()

    with pytest.raises(SessionActiveError, match="is active"):
        app.create_session("session-2")
    with pytest.raises(SessionActiveError, match="is active"):
        app.resume_session("session-2")
    assert store.read_session("session-1").metadata.to_dict() == before

    first.close()
    second = app.create_session("session-2")
    second.close()
    app.close()


def test_application_resume_failure_releases_writer_and_close_releases_active_lock(tmp_path: Path) -> None:
    user_root = tmp_path / "home" / ".uthcode"
    project_root = tmp_path / "project"
    user_root.mkdir(parents=True)
    project_root.mkdir()
    config = EffectiveConfig.single_model("fake/model")
    store = SessionFileStore(tmp_path / "sessions")
    app = create_application(
        config,
        runtime_context=ApplicationRuntimeContext.from_system(workdir=project_root),
        instruction_loader=InstructionLoader(
            user_root=user_root,
            project_root=project_root,
            reader=InstructionFileReader(),
        ),
        session_store=store,
    )
    app.create_session("broken")
    app.close()
    history_path = tmp_path / "sessions" / "broken" / "history.jsonl"
    history_path.write_text("not-json\n", encoding="utf-8")

    with pytest.raises(SessionCorruptError):
        app.resume_session("broken")

    history_path.write_text("", encoding="utf-8")
    resumed = app.resume_session("broken")
    resumed.close()
    app.close()

    with store.open_writer("broken") as writer:
        assert writer.snapshot.session_id == "broken"
