from __future__ import annotations

import asyncio
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest

from uthcode.application import (
    ApplicationSessionService,
    SessionHistoryPage,
    SessionReplayRecord,
    UthCodeApplication,
)
from uthcode.integrations.providers.fake import FakeProvider
from uthcode.integrations.session_files import SessionFileStore
from uthcode.interfaces.desktop.bridge import DesktopBridge
from uthcode.interfaces.desktop.protocol import RequestEnvelope


class _HistoryApplication:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None, int]] = []

    def create_run(self) -> object:
        return SimpleNamespace()

    def session_history_page(
        self,
        session_id: str,
        *,
        cursor: str | None,
        page_size: int,
    ) -> SessionHistoryPage:
        self.calls.append((session_id, cursor, page_size))
        record = SessionReplayRecord(
            session_id,
            4,
            "turn-4",
            "assistant",
            text="answer",
            message_id="message-4",
        )
        return SessionHistoryPage(
            session_id=session_id,
            records=(record,),
            next_cursor="opaque-next",
            has_more=True,
            unit_count=1,
            bytes_read=128,
        )


@pytest.mark.asyncio
async def test_history_page_is_exposed_as_a_safe_desktop_dto() -> None:
    application = _HistoryApplication()
    bridge = DesktopBridge(application)

    response = await bridge.handle_request(
        RequestEnvelope(
            "history-1",
            "history.page",
            {"session_id": "session-1", "page_size": 1},
        )
    )

    assert response.ok is True
    assert response.result == {
        "session_id": "session-1",
        "records": [
            {
                "session_id": "session-1",
                "sequence": 4,
                "turn_id": "turn-4",
                "kind": "assistant",
                "text": "answer",
                "is_error": False,
                "message_id": "message-4",
                "record_id": "session-1:4:assistant::-",
            }
        ],
        "next_cursor": "opaque-next",
        "has_more": True,
        "unit_count": 1,
    }
    assert application.calls == [("session-1", None, 1)]

    second = await bridge.handle_request(
        RequestEnvelope(
            "history-2",
            "history.page",
            {"session_id": "session-1", "cursor": "opaque-prev", "page_size": 1},
        )
    )
    assert second.ok is True
    assert application.calls[-1] == ("session-1", "opaque-prev", 1)


@pytest.mark.asyncio
async def test_cold_application_resume_offloads_real_session_file_recovery(
    tmp_path: Path,
) -> None:
    """A blocked real JSONL recovery must not stop another Bridge request."""

    store = SessionFileStore(tmp_path / "sessions")
    store.create_session("session-a", project_key="project")
    store.create_session("session-b", project_key="project")
    source_service = ApplicationSessionService(
        storage_root=tmp_path / "sessions",
        project_key="project",
        instruction_loader=None,
        store=store,
    )
    source = UthCodeApplication(FakeProvider(), session_service=source_service)
    source.resume_session_for_command("session-a")

    recovery_started = Event()
    release_recovery = Event()
    candidate_stores: list[SessionFileStore] = []

    def factory(_workdir: Path) -> UthCodeApplication:
        candidate_store = SessionFileStore(tmp_path / "sessions")
        original_load = candidate_store._load_snapshot

        def blocked_load(path: Path, **kwargs: object):
            if not release_recovery.is_set():
                recovery_started.set()
                release_recovery.wait(timeout=2)
            return original_load(path, **kwargs)

        candidate_store._load_snapshot = blocked_load  # type: ignore[method-assign]
        candidate_stores.append(candidate_store)
        return UthCodeApplication(
            FakeProvider(),
            session_service=ApplicationSessionService(
                storage_root=tmp_path / "sessions",
                project_key="project",
                instruction_loader=None,
                store=candidate_store,
            ),
        )

    bridge = DesktopBridge(
        source,
        application_factory=factory,
        workdir=tmp_path,
    )
    started = await bridge.handle_request(
        RequestEnvelope(
            "resume-cold",
            "session.resume",
            {"session_id": "session-b"},
        )
    )
    assert started.ok is True
    assert started.result["preparing"] is True
    await asyncio.wait_for(asyncio.to_thread(recovery_started.wait, 1), timeout=1)
    assert candidate_stores

    # This request uses the source Application while the target candidate is
    # blocked in the real SessionFileStore._load_snapshot call.  If the async
    # Application boundary ran that recovery on the Bridge loop, this await
    # would not complete until release_recovery was set below.
    before = asyncio.get_running_loop().time()
    page = await asyncio.wait_for(
        bridge.handle_request(
            RequestEnvelope(
                "page-while-cold",
                "history.page",
                {"session_id": "session-b"},
            )
        ),
        timeout=0.5,
    )
    elapsed = asyncio.get_running_loop().time() - before
    assert page.ok is True
    assert elapsed < 0.5
    assert not release_recovery.is_set()

    release_recovery.set()
    runtime_task = bridge._background_runtimes["session-b"]["task"]
    assert isinstance(runtime_task, asyncio.Task)
    await asyncio.wait_for(runtime_task, timeout=2)
    ready = await bridge.handle_request(
        RequestEnvelope(
            "resume-ready",
            "session.resume",
            {"session_id": "session-b"},
        )
    )
    assert ready.ok is True
    assert ready.result["preparing"] is False
    await bridge.shutdown()


@pytest.mark.asyncio
async def test_cold_prepare_captures_owner_workdir_before_project_switch(
    tmp_path: Path,
) -> None:
    """A queued cold task keeps the project boundary it was created for."""

    sessions_root = tmp_path / "sessions"
    source_store = SessionFileStore(sessions_root)
    source_store.create_session("session-a", project_key="project")
    source_store.create_session("session-b", project_key="project")
    source_service = ApplicationSessionService(
        storage_root=sessions_root,
        project_key="project",
        instruction_loader=None,
        store=source_store,
    )
    source = UthCodeApplication(FakeProvider(), session_service=source_service)
    source.resume_session_for_command("session-a")

    owner_workdir = tmp_path / "project-a"
    switched_workdir = tmp_path / "project-b"
    factory_started = Event()
    release_factory = Event()
    factory_paths: list[Path] = []

    def factory(workdir: Path) -> UthCodeApplication:
        factory_paths.append(workdir)
        factory_started.set()
        release_factory.wait(timeout=2)
        candidate_store = SessionFileStore(sessions_root)
        return UthCodeApplication(
            FakeProvider(),
            session_service=ApplicationSessionService(
                storage_root=sessions_root,
                project_key="project",
                instruction_loader=None,
                store=candidate_store,
            ),
        )

    bridge = DesktopBridge(
        source,
        application_factory=factory,
        workdir=owner_workdir,
    )
    try:
        started = await bridge.handle_request(
            RequestEnvelope(
                "resume-cold",
                "session.resume",
                {"session_id": "session-b"},
            )
        )
        assert started.ok is True
        await asyncio.wait_for(asyncio.to_thread(factory_started.wait, 1), timeout=1)

        # Simulate a project switch while the worker is still queued inside
        # the candidate factory.  The task must retain its original owner
        # boundary instead of consulting the Bridge's mutable current path.
        bridge._workdir = switched_workdir
        release_factory.set()
        runtime_task = bridge._background_runtimes["session-b"]["task"]
        assert isinstance(runtime_task, asyncio.Task)
        await asyncio.wait_for(runtime_task, timeout=2)

        assert factory_paths == [owner_workdir]
        assert bridge._background_runtimes["session-b"]["project_key"] == str(owner_workdir)
    finally:
        release_factory.set()
        await bridge.shutdown()
