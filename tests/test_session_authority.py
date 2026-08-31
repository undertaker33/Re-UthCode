from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from uthcode.application import (
    ApplicationRuntimeContext,
    ApplicationSessionService,
    Message,
    SessionMutation,
    SessionOperationError,
    TextPart,
    UthCodeApplication,
)
from uthcode.application.history import _transcript_entries_for_message
from uthcode.integrations import session_files
from uthcode.integrations.providers.fake import FakeProvider
from uthcode.integrations.session_files import (
    SESSION_TITLE_MAX_LENGTH,
    SessionFileStore,
    SessionMetadata,
)
from uthcode.interfaces.desktop.bridge import DesktopBridge
from uthcode.interfaces.desktop.protocol import RequestEnvelope
from uthcode.interfaces.tui.app import UthCodeTUI
from prompt_toolkit.output import DummyOutput


def _paths(tmp_path: Path) -> tuple[Path, Path, SessionFileStore]:
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    return source, target, SessionFileStore(tmp_path / "sessions")


def _real_application(
    store: SessionFileStore,
    project_key: str,
) -> tuple[UthCodeApplication, ApplicationSessionService]:
    service = ApplicationSessionService(
        storage_root=store.root,
        project_key=project_key,
        instruction_loader=None,
        store=store,
    )
    application = UthCodeApplication(
        FakeProvider(),
        runtime_context=ApplicationRuntimeContext.from_system(
            workdir=Path(project_key),
        ),
        session_service=service,
    )
    return application, service


def _user_transcript(session_id: str, text: str):
    return _transcript_entries_for_message(
        session_id,
        "turn-title",
        1,
        Message("user", (TextPart(text),)),
    )


def test_legacy_metadata_without_title_is_read_without_rewrite(tmp_path: Path) -> None:
    source, _target, store = _paths(tmp_path)
    store.create_session("legacy", project_key=str(source.resolve()))
    metadata_path = store.session_path("legacy") / "metadata.json"
    value = json.loads(metadata_path.read_text(encoding="utf-8"))
    value.pop("title")
    metadata_path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    before = metadata_path.read_bytes()

    snapshot = store.read_session("legacy", expected_project_key=str(source.resolve()))

    assert snapshot.title is None
    assert snapshot.metadata.title is None
    assert metadata_path.read_bytes() == before


@pytest.mark.parametrize("title", ["", " \n\t ", "x" * (SESSION_TITLE_MAX_LENGTH + 1)])
def test_title_validation_rejects_empty_or_overlong_values(tmp_path: Path, title: str) -> None:
    source, _target, store = _paths(tmp_path)

    with pytest.raises(ValueError):
        store.create_session("invalid", project_key=str(source.resolve()), title=title)
    assert not store.session_path("invalid").exists()


def test_title_normalization_is_persistent_and_projected_in_replay(tmp_path: Path) -> None:
    source, _target, store = _paths(tmp_path)
    project_key = str(source.resolve())
    metadata = store.create_session(
        "session-1",
        project_key=project_key,
        title="  Cafe\u0301\n\t中文  ",
    )
    assert metadata.title == "Café\n\t中文"

    with store.open_writer("session-1", expected_project_key=project_key) as writer:
        assert writer.update_title("  新标题  ").title == "新标题"

    service = ApplicationSessionService(
        storage_root=tmp_path / "sessions",
        project_key=project_key,
        instruction_loader=None,
        store=store,
    )
    assert store.read_session("session-1", expected_project_key=project_key).title == "新标题"
    assert service.list_catalog()[0].title == "新标题"
    assert json.loads((store.session_path("session-1") / "metadata.json").read_text(encoding="utf-8"))["title"] == "新标题"


def test_title_boundary_and_internal_whitespace_are_exact(tmp_path: Path) -> None:
    source, _target, store = _paths(tmp_path)
    project_key = str(source.resolve())
    accepted = "x" * SESSION_TITLE_MAX_LENGTH
    assert store.create_session(
        "title-boundary",
        project_key=project_key,
        title=accepted,
    ).title == accepted

    service = ApplicationSessionService(
        storage_root=tmp_path / "sessions",
        project_key=project_key,
        instruction_loader=None,
        store=store,
    )
    internal = "前  中\t后\n尾"
    assert service.rename_session("title-boundary", f"  {internal}  ").title == internal
    with pytest.raises(ValueError):
        service.rename_session("title-boundary", "y" * (SESSION_TITLE_MAX_LENGTH + 1))
    assert store.read_session("title-boundary", expected_project_key=project_key).title == internal


def test_application_replay_status_and_tui_prioritize_title_over_preview(
    tmp_path: Path,
) -> None:
    source, _target, store = _paths(tmp_path)
    project_key = str(source.resolve())
    store.create_session("visible", project_key=project_key, title="权威标题")
    with store.open_writer("visible", expected_project_key=project_key) as writer:
        writer.append_transcript(_user_transcript("visible", "真实首条预览"))

    application, service = _real_application(store, project_key)
    try:
        catalog = application.session_catalog()
        assert catalog[0].title == "权威标题"
        assert catalog[0].preview == "真实首条预览"

        replay = application.session_replay("visible")
        assert replay and replay[0].title == "权威标题"
        assert replay[0].text == "真实首条预览"

        resumed = application.resume_session_for_command("visible")
        assert application.session_replay() == resumed.replay
        status = application.status().to_dict()
        assert status["active_session_title"] == "权威标题"

        tui = UthCodeTUI(application, terminal_output=DummyOutput())
        tui.session_picker.replace(catalog)
        rendered = "".join(text for _style, text in tui._candidate_fragments())
        assert "权威标题" in rendered
        assert "真实首条预览" not in rendered
    finally:
        application.close()


def test_move_changes_only_authoritative_membership_and_is_target_idempotent(
    tmp_path: Path,
) -> None:
    source, target, store = _paths(tmp_path)
    source_key = str(source.resolve())
    target_key = str(target.resolve())
    store.create_session("move-me", project_key=source_key, title="保留标题")
    tool_reference = store.persist_tool_result("move-me", "非空工具结果 bytes")
    before_tool_result = store.read_tool_result("move-me", tool_reference.ref).content
    metadata_path = store.session_path("move-me") / "metadata.json"
    transcript_path = store.session_path("move-me") / "transcript.jsonl"
    timeline_path = store.session_path("move-me") / "timeline.jsonl"
    tool_results_path = store.session_path("move-me") / "tool-results"
    before_transcript = transcript_path.read_bytes()
    before_timeline = timeline_path.read_bytes()

    source_service = ApplicationSessionService(
        storage_root=tmp_path / "sessions",
        project_key=source_key,
        instruction_loader=None,
        store=store,
    )
    target_service = ApplicationSessionService(
        storage_root=tmp_path / "sessions",
        project_key=target_key,
        instruction_loader=None,
        store=store,
    )

    moved = source_service.move_session("move-me", target_key)
    assert moved.project_key == target_key
    assert source_service.list_sessions() == ()
    assert target_service.list_sessions()[0].session_id == "move-me"
    assert target_service.list_catalog()[0].title == "保留标题"
    assert transcript_path.read_bytes() == before_transcript
    assert timeline_path.read_bytes() == before_timeline
    assert store.read_tool_result("move-me", tool_reference.ref).content == before_tool_result
    assert (tool_results_path / tool_reference.ref / "content.bin").is_file()

    with pytest.raises(SessionOperationError) as source_resume:
        source_service.resume_session_for_command("move-me")
    assert source_resume.value.kind == "unknown"

    # Repeating the same convergent operation through the original source
    # Application must also succeed; it does not rewrite
    # metadata or create a second Session.
    before_metadata = metadata_path.read_bytes()
    repeated = source_service.move_session("move-me", target_key)
    assert repeated == moved
    assert metadata_path.read_bytes() == before_metadata

    other = tmp_path / "other"
    other.mkdir()
    other_service = ApplicationSessionService(
        storage_root=tmp_path / "sessions",
        project_key=str(other.resolve()),
        instruction_loader=None,
        store=store,
    )
    with pytest.raises(SessionOperationError) as other_source:
        other_service.move_session("move-me", str(other.resolve()))
    assert other_source.value.kind == "unknown"

    with target_service.resume_session_for_command("move-me") as resumed:
        assert resumed.session_id == "move-me"
        assert resumed.title == "保留标题"


def test_move_rejects_active_session_and_failed_metadata_write_keeps_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, target, store = _paths(tmp_path)
    source_key = str(source.resolve())
    target_key = str(target.resolve())
    store.create_session("busy", project_key=source_key, title="原始")
    service = ApplicationSessionService(
        storage_root=tmp_path / "sessions",
        project_key=source_key,
        instruction_loader=None,
        store=store,
    )
    active = service.resume_session_for_command("busy")
    try:
        with pytest.raises(SessionOperationError) as busy:
            service.move_session("busy", target_key)
        assert busy.value.kind == "busy"
    finally:
        active.close()

    metadata_path = store.session_path("busy") / "metadata.json"
    before = metadata_path.read_bytes()

    def fail_write(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated metadata failure")

    import uthcode.integrations.session_files as session_files

    monkeypatch.setattr(session_files, "_atomic_write_json", fail_write)
    with pytest.raises(SessionOperationError) as failed:
        service.rename_session("busy", "新标题")
    assert failed.value.kind == "storage"
    assert metadata_path.read_bytes() == before
    assert store.read_session("busy", expected_project_key=source_key).title == "原始"


def test_move_write_failure_keeps_project_history_title_and_tool_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, target, store = _paths(tmp_path)
    source_key = str(source.resolve())
    target_key = str(target.resolve())
    store.create_session("move-failure", project_key=source_key, title="原始标题")
    with store.open_writer("move-failure", expected_project_key=source_key) as writer:
        writer.append_transcript(_user_transcript("move-failure", "不可丢失的历史"))
        tool_reference = writer.persist_tool_result("非空工具结果 bytes")

    metadata_path = store.session_path("move-failure") / "metadata.json"
    transcript_path = store.session_path("move-failure") / "transcript.jsonl"
    timeline_path = store.session_path("move-failure") / "timeline.jsonl"
    before_metadata = metadata_path.read_bytes()
    before_transcript = transcript_path.read_bytes()
    before_timeline = timeline_path.read_bytes()
    before_tool_result = store.read_tool_result(
        "move-failure",
        tool_reference.ref,
    ).content
    service = ApplicationSessionService(
        storage_root=tmp_path / "sessions",
        project_key=source_key,
        instruction_loader=None,
        store=store,
    )

    def fail_write(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated move metadata failure")

    monkeypatch.setattr(session_files, "_atomic_write_json", fail_write)
    with pytest.raises(SessionOperationError) as failed:
        service.move_session("move-failure", target_key)
    assert failed.value.kind == "storage"
    assert metadata_path.read_bytes() == before_metadata
    assert transcript_path.read_bytes() == before_transcript
    assert timeline_path.read_bytes() == before_timeline
    snapshot = store.read_session("move-failure", expected_project_key=source_key)
    assert snapshot.project_key == source_key
    assert snapshot.title == "原始标题"
    assert service.project_replay("move-failure")[0].text == "不可丢失的历史"
    assert store.read_tool_result("move-failure", tool_reference.ref).content == before_tool_result


def test_move_receipt_is_instance_local_and_same_target_converges_concurrently(
    tmp_path: Path,
) -> None:
    source, target, store = _paths(tmp_path)
    source_key = str(source.resolve())
    target_key = str(target.resolve())
    store.create_session("same-target", project_key=source_key, title="同目标")
    service = ApplicationSessionService(
        storage_root=tmp_path / "sessions",
        project_key=source_key,
        instruction_loader=None,
        store=store,
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(service.move_session, "same-target", target_key)
            for _ in range(2)
        ]
        results = [future.result() for future in futures]
    assert results[0] == results[1]
    assert results[0].project_key == target_key

    restarted_source = ApplicationSessionService(
        storage_root=tmp_path / "sessions",
        project_key=source_key,
        instruction_loader=None,
        store=store,
    )
    with pytest.raises(SessionOperationError) as restarted:
        restarted_source.move_session("same-target", target_key)
    assert restarted.value.kind == "unknown"

    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    unrelated_service = ApplicationSessionService(
        storage_root=tmp_path / "sessions",
        project_key=str(unrelated.resolve()),
        instruction_loader=None,
        store=store,
    )
    with pytest.raises(SessionOperationError) as other_owner:
        unrelated_service.move_session("same-target", target_key)
    assert other_owner.value.kind == "unknown"


def test_move_different_targets_has_one_success_and_one_controlled_failure(
    tmp_path: Path,
) -> None:
    source, target, store = _paths(tmp_path)
    other_target = tmp_path / "other-target"
    other_target.mkdir()
    source_key = str(source.resolve())
    service = ApplicationSessionService(
        storage_root=tmp_path / "sessions",
        project_key=source_key,
        instruction_loader=None,
        store=store,
    )
    store.create_session("different-targets", project_key=source_key)

    def move(target_key: str) -> tuple[str, object]:
        try:
            return "success", service.move_session("different-targets", target_key)
        except SessionOperationError as exc:
            return "error", exc

    target_keys = [str(target.resolve()), str(other_target.resolve())]
    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(move, target_keys))
    assert [kind for kind, _value in outcomes].count("success") == 1
    assert [kind for kind, _value in outcomes].count("error") == 1
    failure = next(value for kind, value in outcomes if kind == "error")
    assert isinstance(failure, SessionOperationError)
    assert failure.kind == "unknown"
    assert store.read_session("different-targets").project_key in target_keys


class _AuthorityApplication:
    def __init__(self, project_key: str) -> None:
        self.project_key = project_key
        self.runtime_context = SimpleNamespace(workdir=Path(project_key))

    def create_run(self) -> object:
        return SimpleNamespace()

    def rename_session(self, session_id: str, title: str) -> SessionMutation:
        return SessionMutation(session_id, self.project_key, title=title)

    def move_session(self, session_id: str, target_project_key: str) -> SessionMutation:
        self.project_key = target_project_key
        return SessionMutation(session_id, target_project_key, title="移动后")

    def session_catalog(self) -> tuple[object, ...]:
        return ()

    def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_bridge_exposes_session_mutation_dtos_and_controlled_errors(
    tmp_path: Path,
) -> None:
    source, target, _store = _paths(tmp_path)
    application = _AuthorityApplication(str(source.resolve()))
    bridge = DesktopBridge(application=application)

    renamed = await bridge.handle_request(
        RequestEnvelope("rename", "session.rename", {"session_id": "s", "title": "命名"})
    )
    assert renamed.ok is True
    assert renamed.result["title"] == "命名"  # type: ignore[index]
    assert renamed.result["session"]["title"] == "命名"  # type: ignore[index]
    assert set(renamed.result["session"]) == {"session_id", "project_key", "title"}  # type: ignore[index]
    assert "instruction_state" not in renamed.result["session"]  # type: ignore[operator]
    assert "schema_version" not in renamed.result["session"]  # type: ignore[operator]
    assert "created_at" not in renamed.result["session"]  # type: ignore[operator]

    moved = await bridge.handle_request(
        RequestEnvelope(
            "move",
            "session.move",
            {"session_id": "s", "target_project_key": str(target)},
        )
    )
    assert moved.ok is True
    assert moved.result["project_key"] == str(target.resolve())  # type: ignore[index]
    assert moved.result["session"]["project_key"] == str(target.resolve())  # type: ignore[index]

    bridge._active_handle = object()
    busy = await bridge.handle_request(
        RequestEnvelope(
            "move-busy",
            "session.move",
            {"session_id": "s", "target_project_key": str(target)},
        )
    )
    assert busy.ok is False
    assert busy.error is not None and busy.error.kind == "turn_active"
    bridge._active_handle = None

    invalid = await bridge.handle_request(
        RequestEnvelope(
            "move-invalid",
            "session.move",
            {"session_id": "s", "target_project_key": str(tmp_path / "missing")},
        )
    )
    assert invalid.ok is False
    assert invalid.error is not None and invalid.error.kind == "project_not_found"
    await bridge.shutdown()


@pytest.mark.asyncio
async def test_real_bridge_maps_application_membership_busy_and_storage_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, target, store = _paths(tmp_path)
    source_key = str(source.resolve())
    target_key = str(target.resolve())
    store.create_session("bridge-real", project_key=source_key, title="真实")
    application, service = _real_application(store, source_key)
    bridge = DesktopBridge(application=application)
    try:
        moved = await bridge.handle_request(
            RequestEnvelope(
                "real-move",
                "session.move",
                {"session_id": "bridge-real", "target_project_key": target_key},
            )
        )
        assert moved.ok is True
        assert moved.result["session"]["project_key"] == target_key  # type: ignore[index]
        moved_again = await bridge.handle_request(
            RequestEnvelope(
                "real-move-retry",
                "session.move",
                {"session_id": "bridge-real", "target_project_key": target_key},
            )
        )
        assert moved_again.ok is True
        assert moved_again.result == moved.result

        source_resume = await bridge.handle_request(
            RequestEnvelope("source-resume", "session.resume", {"session_id": "bridge-real"})
        )
        assert source_resume.ok is False
        assert source_resume.error is not None and source_resume.error.kind == "session_unknown"

        invalid_target = await bridge.handle_request(
            RequestEnvelope(
                "invalid-target",
                "session.move",
                {"session_id": "bridge-real", "target_project_key": str(tmp_path / "missing")},
            )
        )
        assert invalid_target.ok is False
        assert invalid_target.error is not None and invalid_target.error.kind == "project_not_found"

        store.create_session("bridge-busy", project_key=source_key, title="忙碌")
        active = application.resume_session_for_command("bridge-busy")
        busy = await bridge.handle_request(
            RequestEnvelope(
                "busy-move",
                "session.move",
                {"session_id": "bridge-busy", "target_project_key": target_key},
            )
        )
        assert busy.ok is False
        assert busy.error is not None and busy.error.kind == "session_busy"
        active.close()

        store.create_session("bridge-failure", project_key=source_key, title="失败前")
        metadata_path = store.session_path("bridge-failure") / "metadata.json"
        before_metadata = metadata_path.read_bytes()

        def fail_write(*_args: object, **_kwargs: object) -> None:
            raise OSError("simulated bridge move failure")

        monkeypatch.setattr(session_files, "_atomic_write_json", fail_write)
        failed = await bridge.handle_request(
            RequestEnvelope(
                "failed-move",
                "session.move",
                {"session_id": "bridge-failure", "target_project_key": target_key},
            )
        )
        assert failed.ok is False
        assert failed.error is not None and failed.error.kind == "session_error"
        assert metadata_path.read_bytes() == before_metadata
        assert service.read_session("bridge-failure").project_key == source_key
    finally:
        await bridge.shutdown()
