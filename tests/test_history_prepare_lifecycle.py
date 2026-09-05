from __future__ import annotations

import asyncio
from pathlib import Path
from threading import Event

import pytest

from uthcode.application import ApplicationSessionService, UthCodeApplication
from uthcode.integrations.providers.fake import FakeProvider
from uthcode.integrations.session_files import SessionFileStore
from uthcode.interfaces.desktop.bridge import DesktopBridge
from uthcode.interfaces.desktop.protocol import RequestEnvelope


async def _wait_for_event(event: Event, *, timeout: float = 1.0) -> None:
    reached = await asyncio.wait_for(
        asyncio.to_thread(event.wait, timeout),
        timeout=timeout + 0.5,
    )
    assert reached is True


async def _wait_for_cancel_request(
    task: asyncio.Task[object],
    *,
    timeout: float = 1.0,
) -> None:
    async def poll() -> None:
        while not task.cancelling() and not task.done():
            await asyncio.sleep(0.001)

    await asyncio.wait_for(poll(), timeout=timeout)
    assert task.cancelling() > 0 or task.done()


@pytest.mark.asyncio
async def test_cancelled_cold_prepare_releases_staged_writer_before_shutdown_returns(
    tmp_path: Path,
) -> None:
    """A cancelled cold resume must not leave a staged writer or active Session."""

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

    writer_entered = Event()
    release_stage = Event()
    candidate_close_started = Event()
    resume_finished = Event()
    candidate_stores: list[SessionFileStore] = []
    candidate_services: list[ApplicationSessionService] = []
    staged_writers: list[object] = []

    def factory(_workdir: Path) -> UthCodeApplication:
        candidate_store = SessionFileStore(sessions_root)
        original_open_writer = candidate_store.open_writer

        def gated_open_writer(
            session_id: str,
            *,
            expected_project_key: str | None = None,
        ) -> object:
            writer = original_open_writer(
                session_id,
                expected_project_key=expected_project_key,
            )
            original_enter = writer.__enter__

            def gated_enter() -> object:
                entered = original_enter()
                staged_writers.append(writer)
                writer_entered.set()
                release_stage.wait(timeout=2)
                return entered

            writer.__enter__ = gated_enter  # type: ignore[method-assign]
            return writer

        candidate_store.open_writer = gated_open_writer  # type: ignore[method-assign]
        candidate_service = ApplicationSessionService(
            storage_root=sessions_root,
            project_key="project",
            instruction_loader=None,
            store=candidate_store,
        )
        original_resume = candidate_service.resume_session_for_command

        def observed_resume(*args: object, **kwargs: object) -> object:
            try:
                return original_resume(*args, **kwargs)
            finally:
                resume_finished.set()

        candidate_service.resume_session_for_command = observed_resume  # type: ignore[method-assign]
        candidate = UthCodeApplication(
            FakeProvider(),
            session_service=candidate_service,
        )
        original_close = candidate.close

        def observed_close() -> None:
            candidate_close_started.set()
            original_close()

        candidate.close = observed_close  # type: ignore[method-assign]
        candidate_stores.append(candidate_store)
        candidate_services.append(candidate_service)
        return candidate

    bridge = DesktopBridge(
        source,
        application_factory=factory,
        workdir=tmp_path,
        shutdown_timeout=0.01,
    )
    shutdown_task: asyncio.Task[None] | None = None
    try:
        started = await bridge.handle_request(
            RequestEnvelope(
                "resume-cold",
                "session.resume",
                {"session_id": "session-b"},
            )
        )
        assert started.ok is True
        assert started.result["preparing"] is True
        await _wait_for_event(writer_entered)
        assert candidate_stores
        assert candidate_services
        assert staged_writers

        runtime = bridge._background_runtimes["session-b"]
        runtime_task = runtime["task"]
        assert isinstance(runtime_task, asyncio.Task)
        shutdown_task = asyncio.create_task(bridge.shutdown())

        # The shutdown timeout must cancel the Bridge task while the actual
        # worker thread remains blocked in the real staged Session boundary.
        await _wait_for_cancel_request(runtime_task)
        release_stage.set()
        await _wait_for_event(resume_finished)
        await asyncio.wait_for(shutdown_task, timeout=2)
        shutdown_task = None

        candidate_service = candidate_services[0]
        assert candidate_service.active_session is None
        assert getattr(staged_writers[0], "_closed") is True

        # The same durable Session can immediately acquire the lock and resume
        # through the real Application boundary after the cancelled prepare.
        candidate_store = candidate_stores[0]
        with candidate_store.open_writer(
            "session-b",
            expected_project_key="project",
        ) as writer:
            assert writer.metadata.session_id == "session-b"
        resumed = candidate_service.resume_session_for_command("session-b")
        assert resumed.session_id == "session-b"
        candidate_service.close()
        assert candidate_service.active_session is None
    finally:
        release_stage.set()
        if candidate_services and not resume_finished.is_set():
            try:
                await _wait_for_event(resume_finished, timeout=2)
            except (AssertionError, asyncio.TimeoutError):
                pass
        if shutdown_task is not None:
            try:
                await asyncio.wait_for(shutdown_task, timeout=2)
            except asyncio.TimeoutError:
                shutdown_task.cancel()
                await asyncio.gather(shutdown_task, return_exceptions=True)
        else:
            # The successful path already closed the Bridge.  This is a no-op
            # and keeps the cleanup bounded if an assertion failed earlier.
            await bridge.shutdown()
        for candidate_service in candidate_services:
            try:
                candidate_service.close()
            except Exception:
                pass
