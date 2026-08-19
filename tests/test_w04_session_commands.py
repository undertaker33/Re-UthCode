from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from prompt_toolkit.output import DummyOutput

from uthcode.application import (
    ApplicationContextService,
    CommandDispatcher,
    ContextUsage,
    EffectiveConfig,
    OpenSessionPicker,
    OutcomeStatus,
    SessionChanged,
    SessionOperationError,
    create_application,
    create_builtin_registry,
)
from uthcode.application.instructions import InstructionLoader
from uthcode.application.history import history_entries_for_message
from uthcode.application.runtime_context import ApplicationRuntimeContext
from uthcode.core.history import (
    CanonicalHistory,
    HistoryKind,
    history_entries_from_message,
)
from uthcode.core.provider import (
    FinishReason,
    GenerationCompleted,
    Message,
    ModelLimits,
    ProviderResponse,
    TextPart,
    ToolCallPart,
    ToolResultPart,
    Usage,
)
from uthcode.integrations.instruction_files import InstructionFileReader
from uthcode.integrations.providers.fake import FakeProvider
from uthcode.integrations.session_files import (
    SessionBusyError,
    SessionFileError,
    SessionFileStore,
)
from uthcode.interfaces.tui.picker import SessionPickerState
from uthcode.interfaces.tui.app import UthCodeTUI
from uthcode.interfaces.tui.rendering import (
    context_usage_bar,
    context_usage_ring,
    context_usage_style,
)


TEST_LIMITS = ModelLimits(max_input_tokens=1_000_000, source="test.fake")


def _application(
    tmp_path: Path,
    store: SessionFileStore,
    *,
    provider: FakeProvider | None = None,
):
    user_root = tmp_path / "home" / ".uthcode"
    project_root = tmp_path / "project"
    user_root.mkdir(parents=True, exist_ok=True)
    project_root.mkdir(parents=True, exist_ok=True)
    (project_root / "AGENTS.md").write_text("project rule", encoding="utf-8")
    loader = InstructionLoader(
        user_root=user_root,
        project_root=project_root,
        reader=InstructionFileReader(),
    )
    config = EffectiveConfig.single_model("fake/model", context_window=1_000_000)
    return create_application(
        config,
        provider_builder=(
            None
            if provider is None
            else lambda _profile, _model: provider
        ),
        runtime_context=ApplicationRuntimeContext.from_system(workdir=project_root),
        instruction_loader=loader,
        session_store=store,
    )


def _completed(text: str = "done") -> GenerationCompleted:
    return GenerationCompleted(
        ProviderResponse(
            Message("assistant", (TextPart(text),)),
            finish_reason=FinishReason.STOP,
            usage=Usage(),
        )
    )


def _message_history(
    session_id: str,
    messages: tuple[Message, ...],
) -> CanonicalHistory:
    history = CanonicalHistory(session_id)
    sequence = 1
    for index, message in enumerate(messages, start=1):
        entries = history_entries_from_message(
            session_id,
            f"history-turn-{index}",
            sequence,
            message,
        )
        history = CanonicalHistory(session_id, history.entries + entries)
        sequence += len(entries)
    return history


def _request_text(request) -> str:
    return "\n".join(
        part.text
        for message in request.messages
        for part in message.parts
        if isinstance(part, TextPart)
    )


def _seed_session(application, session_id: str = "session-1"):
    session = application.create_session(session_id)
    history = CanonicalHistory(session_id).append(
        turn_id="turn-1",
        kind=HistoryKind.USER_MESSAGE,
        payload={"text": "first prompt\nwith a second line"},
    )
    session.append_history(history.entries)
    session.append_projection(history.project(revision=1))
    session.close()
    return history


def test_w04_commands_are_implemented_and_compact_rejects_focus() -> None:
    registry = create_builtin_registry()
    dispatcher = CommandDispatcher(registry)

    assert registry.resolve("compact").implemented  # type: ignore[union-attr]
    assert registry.resolve("new").implemented  # type: ignore[union-attr]
    assert registry.resolve("resume").implemented  # type: ignore[union-attr]
    picker = dispatcher.dispatch_text("/resume")
    assert picker is not None
    assert picker.status is OutcomeStatus.SUCCESS
    assert isinstance(picker.ui_action, OpenSessionPicker)

    rejected = dispatcher.dispatch_text("/compact -- focus")
    assert rejected is not None
    assert rejected.status is OutcomeStatus.USAGE_ERROR


def test_new_resume_restore_history_projection_instruction_state_and_status(
    tmp_path: Path,
) -> None:
    store = SessionFileStore(tmp_path / "sessions")
    application = _application(tmp_path, store)
    try:
        history = _seed_session(application)
        loader = application.instruction_loader
        assert loader is not None
        target = Path(loader.project_root) / "src"
        target.mkdir()
        application.resume_session("session-1")
        loader.load_for_path(target / "module.py")
        application.close()

        dispatcher = CommandDispatcher(create_builtin_registry(), application)
        outcome = dispatcher.dispatch_text("/resume session-1")
        assert outcome is not None
        assert outcome.status is OutcomeStatus.SUCCESS
        assert outcome.ui_action == SessionChanged("session-1", restored=True)

        active = application.session_service.active_session  # type: ignore[union-attr]
        assert active is not None
        assert active.history.entries == history.entries
        assert active.projection is not None
        assert active.projection.revision == 1
        assert str(target.resolve()) in active.instruction_state.activated_directory_scopes

        status = dispatcher.dispatch_text("/status")
        assert status is not None and status.output is not None
        assert "context: " in status.output and "dynamic input operating limit" in status.output
        assert "projection revision: 1" in status.output
        assert "instruction epoch:" in status.output
        assert "compact count: 1" in status.output
        assert "not a remote physical window" not in status.output
        assert "stage limitation" not in status.output
        assert "258K" not in status.output

        # A resumed process gets a new in-memory Run; durable History is not a
        # Task/Plan/Pending-Tool checkpoint and is not copied into RunState.
        assert application.create_run().snapshot().iteration_count == 0
    finally:
        application.close()


@pytest.mark.asyncio
async def test_resumed_canonical_history_enters_headless_provider_request(
    tmp_path: Path,
) -> None:
    provider = FakeProvider(events=(_completed(),), model_limits=TEST_LIMITS)
    store = SessionFileStore(tmp_path / "sessions")
    application = _application(tmp_path, store, provider=provider)
    try:
        session = application.create_session("resume-history")
        history = _message_history(
            "resume-history",
            (Message("user", (TextPart("OLD_HISTORY_MARKER"),)),),
        )
        session.append_history(history.entries)
        session.close()

        application.resume_session_for_command("resume-history")
        result = await application.create_run().start_turn("NEW_TURN_MARKER").result()

        assert result.final_text == "done"
        request = provider.recorded_requests[0]
        assert "OLD_HISTORY_MARKER" in _request_text(request)
        assert "NEW_TURN_MARKER" in _request_text(request)
        assert request.messages[-1].role == "user"
        assert request.messages[-1].parts[-1] == TextPart("NEW_TURN_MARKER")
    finally:
        application.close()


@pytest.mark.asyncio
async def test_resumed_projection_keeps_summary_and_raw_history_tail(
    tmp_path: Path,
) -> None:
    provider = FakeProvider(events=(_completed(),), model_limits=TEST_LIMITS)
    store = SessionFileStore(tmp_path / "sessions")
    application = _application(tmp_path, store, provider=provider)
    try:
        session = application.create_session("resume-projection")
        history = _message_history(
            "resume-projection",
            (
                Message("user", (TextPart("HISTORY_UNIT_1"),)),
                Message("user", (TextPart("HISTORY_UNIT_2"),)),
                Message("user", (TextPart("HISTORY_UNIT_3"),)),
            ),
        )
        session.append_history(history.entries)
        session.append_projection(
            history.project(
                revision=1,
                sequence_start=1,
                sequence_end=2,
                summary="OLD_SUMMARY_MARKER",
            )
        )
        session.close()

        application.resume_session_for_command("resume-projection")
        await application.create_run().start_turn("NEW_TURN_MARKER").result()

        request = provider.recorded_requests[0]
        text = _request_text(request)
        assert "OLD_SUMMARY_MARKER" in text
        assert "HISTORY_UNIT_3" in text
        assert "HISTORY_UNIT_1" not in text
        assert "HISTORY_UNIT_2" not in text
        assert request.messages[-1].parts[-1] == TextPart("NEW_TURN_MARKER")
    finally:
        application.close()


@pytest.mark.asyncio
async def test_resumed_tool_history_keeps_native_tool_pair(
    tmp_path: Path,
) -> None:
    provider = FakeProvider(events=(_completed(),), model_limits=TEST_LIMITS)
    store = SessionFileStore(tmp_path / "sessions")
    application = _application(tmp_path, store, provider=provider)
    try:
        session = application.create_session("resume-tools")
        history = _message_history(
            "resume-tools",
            (
                Message(
                    "assistant",
                    (ToolCallPart("call-1", "ReadFile", {"path": "note.txt"}),),
                ),
                Message(
                    "tool",
                    (ToolResultPart("call-1", "tool result"),),
                ),
            ),
        )
        session.append_history(history.entries)
        session.close()

        application.resume_session_for_command("resume-tools")
        await application.create_run().start_turn("continue after tool").result()

        request = provider.recorded_requests[0]
        assert any(
            message.role == "assistant"
            and message.parts == (ToolCallPart("call-1", "ReadFile", {"path": "note.txt"}),)
            for message in request.messages
        )
        assert any(
            message.role == "tool"
            and message.parts == (ToolResultPart("call-1", "tool result"),)
            for message in request.messages
        )
    finally:
        application.close()


@pytest.mark.asyncio
async def test_resumed_history_is_injected_once_across_multiple_turns(
    tmp_path: Path,
) -> None:
    provider = FakeProvider(
        events=(_completed("first"), _completed("second")), model_limits=TEST_LIMITS
    )
    store = SessionFileStore(tmp_path / "sessions")
    application = _application(tmp_path, store, provider=provider)
    try:
        session = application.create_session("resume-multi")
        history = _message_history(
            "resume-multi",
            (Message("user", (TextPart("OLD_HISTORY_MARKER"),)),),
        )
        session.append_history(history.entries)
        session.close()
        application.resume_session_for_command("resume-multi")

        run = application.create_run()
        await run.start_turn("TURN_1_MARKER").result()
        await run.start_turn("TURN_2_MARKER").result()

        first_request, second_request = provider.recorded_requests
        assert _request_text(first_request).count("OLD_HISTORY_MARKER") == 1
        assert _request_text(second_request).count("OLD_HISTORY_MARKER") == 1
        assert "TURN_1_MARKER" in _request_text(second_request)
        assert "TURN_2_MARKER" in _request_text(second_request)
        assert second_request.messages[-1].parts[-1] == TextPart("TURN_2_MARKER")
    finally:
        application.close()


@pytest.mark.asyncio
async def test_resume_preserves_adjacent_same_role_messages_within_one_turn(
    tmp_path: Path,
) -> None:
    provider = FakeProvider(events=(_completed(),), model_limits=TEST_LIMITS)
    store = SessionFileStore(tmp_path / "sessions")
    application = _application(tmp_path, store, provider=provider)
    try:
        session = application.create_session("resume-same-turn")
        messages = (
            Message("user", (TextPart("initial request"),)),
            Message("user", (TextPart("steering request"),)),
            Message("assistant", (TextPart("first answer"),)),
            Message("assistant", (TextPart("second answer"),)),
            Message("user", (TextPart("part-one"), TextPart("part-two"))),
        )
        history = CanonicalHistory("resume-same-turn")
        sequence = 1
        for message in messages:
            entries = history_entries_for_message(
                "resume-same-turn",
                "same-turn",
                sequence,
                message,
            )
            history = CanonicalHistory("resume-same-turn", history.entries + entries)
            sequence += len(entries)
        session.append_history(history.entries)
        session.close()

        application.resume_session_for_command("resume-same-turn")
        await application.create_run().start_turn("continue").result()

        request = provider.recorded_requests[0]
        assert request.messages[: len(messages)] == messages
        assert request.messages[-1].parts[-1] == TextPart("continue")
    finally:
        application.close()


def test_same_text_process_turn_is_not_deduplicated_against_durable_history() -> None:
    session_id = "same-text-session"
    durable = _message_history(
        session_id,
        (Message("user", (TextPart("repeat"),)),),
    )
    request, _snapshot = ApplicationContextService().compose_generation_request(
        (
            Message("user", (TextPart("repeat"),)),
            Message("assistant", (TextPart("answer"),)),
            Message("user", (TextPart("repeat"),)),
        ),
        run_id="same-text-run",
        session_id=session_id,
        canonical_history=durable,
    )

    user_repeat_messages = [
        message
        for message in request.messages
        if message.role == "user"
        and any(
            isinstance(part, TextPart) and part.text == "repeat"
            for part in message.parts
        )
    ]
    assert len(user_repeat_messages) == 3
    assert request.messages[-1].parts[-1] == TextPart("repeat")


@pytest.mark.asyncio
async def test_formal_run_keeps_same_text_turn_after_restored_history(
    tmp_path: Path,
) -> None:
    provider = FakeProvider(
        events=(_completed("first answer"), _completed("second answer")),
        model_limits=TEST_LIMITS,
    )
    store = SessionFileStore(tmp_path / "sessions")
    application = _application(tmp_path, store, provider=provider)
    try:
        session = application.create_session("same-text-formal")
        history = _message_history(
            "same-text-formal",
            (Message("user", (TextPart("repeat"),)),),
        )
        session.append_history(history.entries)
        session.close()
        application.resume_session_for_command("same-text-formal")

        run = application.create_run()
        await run.start_turn("repeat").result()
        await run.start_turn("repeat").result()

        second_request = provider.recorded_requests[1]
        repeated_users = [
            message
            for message in second_request.messages
            if message.role == "user"
            and any(
                isinstance(part, TextPart) and part.text == "repeat"
                for part in message.parts
            )
        ]
        assert len(repeated_users) == 3
        assert second_request.messages[-1].parts[-1] == TextPart("repeat")
    finally:
        application.close()


def test_new_command_releases_old_writer_and_opens_a_fresh_session(tmp_path: Path) -> None:
    store = SessionFileStore(tmp_path / "sessions")
    application = _application(tmp_path, store)
    try:
        _seed_session(application)
        outcome = CommandDispatcher(
            create_builtin_registry(), application
        ).dispatch_text("/new")
        assert outcome is not None
        assert outcome.status is OutcomeStatus.SUCCESS
        assert isinstance(outcome.ui_action, SessionChanged)
        assert outcome.ui_action.restored is False
        active = application.session_service.active_session  # type: ignore[union-attr]
        assert active is not None
        assert active.session_id != "session-1"
        assert store.read_session("session-1").session_id == "session-1"
    finally:
        application.close()


def test_resume_busy_corrupt_and_unknown_are_user_visible(tmp_path: Path) -> None:
    store = SessionFileStore(tmp_path / "sessions")
    owner = _application(tmp_path, store)
    contender = _application(tmp_path, store)
    try:
        _seed_session(owner, "busy")
        held = owner.resume_session("busy")
        busy = CommandDispatcher(
            create_builtin_registry(), contender
        ).dispatch_text("/resume busy")
        assert busy is not None
        assert busy.status is OutcomeStatus.EXECUTION_ERROR
        assert busy.error is not None and "Session busy" in busy.error
        held.close()

        corrupt_path = store.session_path("busy") / "history.jsonl"
        corrupt_path.write_text("not-json\n", encoding="utf-8")
        corrupt = CommandDispatcher(
            create_builtin_registry(), contender
        ).dispatch_text("/resume busy")
        assert corrupt is not None
        assert corrupt.status is OutcomeStatus.EXECUTION_ERROR
        assert corrupt.error is not None and "Session corrupt" in corrupt.error

        unknown = CommandDispatcher(
            create_builtin_registry(), contender
        ).dispatch_text("/resume missing")
        assert unknown is not None
        assert unknown.status is OutcomeStatus.EXECUTION_ERROR
        assert unknown.error == "unknown Session: missing"
    finally:
        owner.close()
        contender.close()


@pytest.mark.asyncio
async def test_failed_resume_keeps_current_session_lock_state_and_continuation(
    tmp_path: Path,
) -> None:
    store = SessionFileStore(tmp_path / "sessions")
    setup = _application(tmp_path, store)
    owner_provider = FakeProvider(events=(_completed(),), model_limits=TEST_LIMITS)
    owner = _application(tmp_path, store, provider=owner_provider)
    held_app = _application(tmp_path, store)
    try:
        for session_id in ("busy-target", "corrupt-target"):
            session = setup.create_session(session_id)
            session.close()
        (store.session_path("corrupt-target") / "history.jsonl").write_text(
            "not-json\n",
            encoding="utf-8",
        )
        held = held_app.resume_session("busy-target")

        current = owner.create_session("current")
        current_history = _message_history(
            "current",
            (Message("user", (TextPart("CURRENT_HISTORY_MARKER"),)),),
        )
        current.append_history(current_history.entries)
        loader = owner.instruction_loader
        assert loader is not None
        active_directory = Path(loader.project_root) / "current-scope"
        active_directory.mkdir()
        loader.load_for_path(active_directory / "module.py")
        current.persist_instruction_state()
        expected_history = current.history
        expected_projection = current.projection
        expected_instruction_state = current.instruction_state

        dispatcher = CommandDispatcher(create_builtin_registry(), owner)
        for target, expected_error in (
            ("busy-target", "Session busy"),
            ("missing-target", "unknown Session: missing-target"),
            ("corrupt-target", "Session corrupt"),
        ):
            outcome = dispatcher.dispatch_text(f"/resume {target}")
            assert outcome is not None
            assert outcome.status is OutcomeStatus.EXECUTION_ERROR
            assert outcome.error is not None and expected_error in outcome.error
            active = owner.session_service.active_session  # type: ignore[union-attr]
            assert active is current
            assert active.history == expected_history
            assert active.projection == expected_projection
            assert active.instruction_state == expected_instruction_state

            probe = store.open_writer("current", expected_project_key=str(loader.project_root))
            with pytest.raises(SessionBusyError):
                probe.__enter__()
            probe.close()

        held.close()
        result = await owner.create_run().start_turn("CURRENT_CONTINUATION").result()
        assert result.final_text == "done"
        request_text = _request_text(owner_provider.recorded_requests[0])
        assert "CURRENT_HISTORY_MARKER" in request_text
        assert "CURRENT_CONTINUATION" in request_text
    finally:
        setup.close()
        held_app.close()
        owner.close()


def test_new_failure_does_not_clear_current_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = SessionFileStore(tmp_path / "sessions")
    application = _application(tmp_path, store)
    try:
        current = application.create_session("current")
        loader = application.instruction_loader
        assert loader is not None
        expected_state = current.instruction_state

        def fail_create(*_args, **_kwargs):
            raise SessionFileError("synthetic create failure")

        monkeypatch.setattr(store, "create_session", fail_create)
        with pytest.raises(SessionOperationError) as failure:
            application.new_session_for_command()
        assert failure.value.kind == "storage"
        assert application.session_service.active_session is current  # type: ignore[union-attr]
        assert current.instruction_state == expected_state

        probe = store.open_writer("current", expected_project_key=str(loader.project_root))
        with pytest.raises(SessionBusyError):
            probe.__enter__()
        probe.close()
    finally:
        application.close()


def test_commit_sync_failure_keeps_current_session_open_and_locked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = SessionFileStore(tmp_path / "sessions")
    application = _application(tmp_path, store)
    failure_enabled = True
    try:
        target = application.create_session("target")
        target.close()
        current = application.create_session("current")
        current_history = _message_history(
            "current",
            (Message("user", (TextPart("CURRENT_BEFORE_COMMIT"),)),),
        )
        current.append_history(current_history.entries)
        expected_history = current.history
        expected_projection = current.projection
        expected_instruction_state = current.instruction_state
        loader = application.instruction_loader
        assert loader is not None

        def fail_sync(_writer) -> object:
            if failure_enabled:
                raise RuntimeError("injected old Session sync failure")
            return object()

        service = application.session_service
        assert service is not None
        monkeypatch.setattr(service, "_sync_instruction_state", fail_sync)

        with pytest.raises(RuntimeError, match="injected old Session sync failure"):
            application.resume_session_for_command("target")

        assert service.active_session is current
        assert current._closed is False
        assert current.history == expected_history
        assert current.projection == expected_projection
        assert current.instruction_state == expected_instruction_state

        current_probe = store.open_writer(
            "current",
            expected_project_key=str(loader.project_root),
        )
        with pytest.raises(SessionBusyError):
            current_probe.__enter__()
        current_probe.close()

        target_probe = store.open_writer(
            "target",
            expected_project_key=str(loader.project_root),
        )
        target_probe.__enter__()
        target_probe.close()
    finally:
        failure_enabled = False
        application.close()


def test_successful_session_switch_commits_target_after_old_writer_release(
    tmp_path: Path,
) -> None:
    store = SessionFileStore(tmp_path / "sessions")
    setup = _application(tmp_path, store)
    application = _application(tmp_path, store)
    try:
        target = setup.create_session("target")
        target_loader = setup.instruction_loader
        assert target_loader is not None
        target_scope = Path(target_loader.project_root) / "target-scope"
        target_scope.mkdir()
        target_loader.load_for_path(target_scope / "module.py")
        target.persist_instruction_state()
        target.close()

        current = application.create_session("current")
        switched = application.resume_session_for_command("target")

        assert application.session_service.active_session is switched  # type: ignore[union-attr]
        assert switched.session_id == "target"
        assert str(target_scope.resolve()) in switched.instruction_state.activated_directory_scopes

        old_probe = store.open_writer("current", expected_project_key=str(target_loader.project_root))
        old_probe.__enter__()
        old_probe.close()

        target_probe = store.open_writer("target", expected_project_key=str(target_loader.project_root))
        with pytest.raises(SessionBusyError):
            target_probe.__enter__()
        target_probe.close()
        with pytest.raises(RuntimeError):
            current.history
    finally:
        setup.close()
        application.close()


def test_compact_command_surfaces_failure_and_success(tmp_path: Path, monkeypatch) -> None:
    store = SessionFileStore(tmp_path / "sessions")
    application = _application(tmp_path, store)
    try:
        history = _seed_session(application, "compact")
        active = application.resume_session("compact")
        extended = history.append(
            turn_id="turn-2",
            kind=HistoryKind.USER_MESSAGE,
            payload={"text": "second prompt"},
        )
        active.append_history(extended.entries[-1])
        dispatcher = CommandDispatcher(create_builtin_registry(), application)

        failed = dispatcher.dispatch_text("/compact")
        assert failed is not None
        assert failed.status is OutcomeStatus.EXECUTION_ERROR
        assert failed.error is not None and "summarizer_unavailable" in failed.error

        real_compact = application.compact_session
        monkeypatch.setattr(
            application,
            "compact_session",
            lambda: real_compact(summarize=lambda _input: "bounded summary"),
        )
        succeeded = dispatcher.dispatch_text("/compact")
        assert succeeded is not None
        assert succeeded.status is OutcomeStatus.SUCCESS
        assert succeeded.output is not None and "Projection revision: 2" in succeeded.output
        assert application.session_service.active_session.projection.revision == 2  # type: ignore[union-attr]
        assert application.session_service.active_session.history.entries == extended.entries  # type: ignore[union-attr]
    finally:
        application.close()


def test_session_picker_has_fixed_ten_page_and_keyboard_state() -> None:
    entries = tuple(
        SimpleNamespace(
            session_id=f"session-{index:02d}",
            last_used_at=f"2026-08-17T00:{index:02d}:00+00:00",
            preview=f"prompt {index}",
        )
        for index in range(21)
    )
    picker = SessionPickerState()
    picker.replace(entries)
    assert picker.page_size == 10
    assert picker.page_count == 3
    picker.move(1)
    assert picker.selected.session_id == "session-01"
    picker.next_page()
    assert picker.selected.session_id == "session-11"
    picker.next_page()
    assert picker.selected.session_id == "session-20"
    picker.previous_page()
    assert picker.selected.session_id == "session-10"
    picker.close()
    assert picker.open is False


def test_status_bar_and_input_ring_share_dynamic_usage_projection() -> None:
    low = ContextUsage(10, budget_tokens=25_000)
    high = ContextUsage(250_000, budget_tokens=250_000)
    unavailable = ContextUsage(0, budget_tokens=None, available=False)

    assert context_usage_style(low) == "class:status"
    assert context_usage_style(high) == "class:status.warning"
    assert context_usage_style(unavailable) == "class:status"
    assert context_usage_bar(low)[1].endswith("10/25K")
    assert context_usage_ring(high)[1].endswith("250000/250K")
    assert "unavailable/?" in context_usage_ring(unavailable)[1]


@pytest.mark.asyncio
async def test_tui_session_picker_is_application_backed_and_enter_starts_new_run(
    tmp_path: Path,
) -> None:
    store = SessionFileStore(tmp_path / "sessions")
    application = _application(tmp_path, store)
    tui = UthCodeTUI(application, terminal_output=DummyOutput())
    try:
        _seed_session(application)
        outcome = tui.dispatcher.dispatch_text("/resume")
        assert outcome is not None
        await tui._apply_command_outcome("/resume", outcome)
        assert tui.session_picker.open is True
        assert tui.session_picker.selected.session_id == "session-1"

        previous_run = tui._run
        tui._select_session()
        await asyncio.gather(*tuple(tui._background_tasks))
        assert tui.session_picker.open is False
        assert tui._run is not previous_run
        assert application.session_service.active_session.session_id == "session-1"  # type: ignore[union-attr]
    finally:
        await tui.shutdown()


@pytest.mark.asyncio
async def test_tui_blocks_compact_during_active_turn_without_changing_session(
    tmp_path: Path,
) -> None:
    store = SessionFileStore(tmp_path / "sessions")
    application = _application(tmp_path, store)
    tui = UthCodeTUI(application, terminal_output=DummyOutput())
    try:
        session = application.create_session("active")
        tui._active_handle = SimpleNamespace(  # type: ignore[assignment]
            pending_pause=None,
            cancel=lambda: None,
        )
        await tui._handle_submission("/compact")
        assert application.session_service.active_session.session_id == "active"  # type: ignore[union-attr]
        tui._active_handle = None
        session.close()
    finally:
        await tui.shutdown()
