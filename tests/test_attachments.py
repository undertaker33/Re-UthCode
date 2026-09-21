from __future__ import annotations

import base64
import json
import struct
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace

import pytest

from uthcode.application import (
    ApplicationRuntimeContext,
    ApplicationSessionService,
    EffectiveConfig,
    ModelProfile,
    ProviderKind,
    ProviderProfile,
    RunStatus,
    UthCodeApplication,
    create_application,
)
from uthcode.core.context import account_generation_request
from uthcode.core.history import Timeline, transcript_entries_from_message
from uthcode.core.provider import (
    CancellationToken,
    FinishReason,
    GenerationCompleted,
    ImagePart,
    Message,
    MessageInput,
    ModelLimits,
    ProviderConfigurationError,
    ProviderIdentity,
    ProviderResponse,
    TextPart,
    Usage,
)
from uthcode.integrations.attachment_files import (
    AttachmentImageTooLarge,
    AttachmentPolicy,
    AttachmentQuotaExceeded,
    AttachmentReferenceError,
)
from uthcode.integrations import attachment_files
from uthcode.integrations.providers.fake import FakeProvider
from uthcode.integrations.providers.openai_responses import (
    OpenAIResponsesProvider,
    build_openai_responses_provider,
)
from uthcode.integrations.session_files import SessionFileStore


_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _runtime(root: Path) -> ApplicationRuntimeContext:
    return ApplicationRuntimeContext.from_system(
        workdir=root,
        platform_name="test",
        platform_release="1",
        current_date="2026-09-12",
    )


def _config(*, default_model: str = "vision/ref") -> EffectiveConfig:
    return EffectiveConfig(
        default_model=default_model,
        providers={
            "vision": ProviderProfile("vision", ProviderKind.FAKE),
            "text": ProviderProfile("text", ProviderKind.FAKE),
        },
        models={
            "vision/ref": ModelProfile(
                "vision/ref",
                "vision",
                "vision-model",
                supports_images=True,
            ),
            "text/ref": ModelProfile(
                "text/ref",
                "text",
                "text-model",
                supports_images=False,
            ),
        },
    )


def _completed(text: str = "done") -> GenerationCompleted:
    return GenerationCompleted(
        ProviderResponse(
            message=Message("assistant", (TextPart(text),)),
            finish_reason=FinishReason.STOP,
            usage=Usage(),
        )
    )


def _app_with_fake_provider(
    root: Path,
    *,
    providers: dict[str, FakeProvider] | None = None,
) -> UthCodeApplication:
    selected = providers or {
        "vision/ref": FakeProvider(
            events=(_completed(),),
            model_limits=ModelLimits(max_input_tokens=256_000, source="test.fake"),
        ),
        "text/ref": FakeProvider(
            events=(_completed(),),
            model_limits=ModelLimits(max_input_tokens=256_000, source="test.fake"),
        ),
    }
    return create_application(
        _config(),
        provider_builder=lambda _provider, model: selected[model.model_ref],
        runtime_context=_runtime(root),
        storage_root=root / "sessions",
    )


def test_application_attachment_copy_survives_source_change_and_restart_history(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.png"
    source.write_bytes(_PNG)
    application = _app_with_fake_provider(tmp_path)
    session = application.new_session_for_command()
    session_id = session.session_id
    try:
        imported = application.import_attachment(
            source.read_bytes(),
            display_name=source.name,
            mime_type="image/png",
        )
        source.write_bytes(b"changed source")
        source.unlink()
        assert application.attachment_service is not None
        assert application.attachment_service.read(session_id, imported.ref) == _PNG
        preview = application.preview_attachment(imported.ref, session_id=session_id)
        assert preview["mime_type"] == "image/png"
        assert isinstance(preview.get("data_url"), str)

        entries = transcript_entries_from_message(
            session_id,
            "image-turn",
            1,
            Message(
                "user",
                (ImagePart(imported.asset_ref, imported.mime_type, imported.width, imported.height),),
            ),
        )
        outcome = session.append_transcript(entries)
        assert outcome.transcript_appended is True
        assert application.attachment_service.reference(session_id, imported.ref).submitted is True

        attachments_root = application.session_service.store.session_path(session_id) / "attachments"  # type: ignore[union-attr]
        abandoned = attachments_root / ".abandoned.tmp"
        abandoned.mkdir()
        (abandoned / "content.bin").write_bytes(b"temporary")
        derived = attachments_root / "derived"
        derived.mkdir()
        (derived / "preview.bin").write_bytes(b"derived")
        application.close()
        assert not abandoned.exists()
        assert not derived.exists()
        assert application.attachment_service.read(session_id, imported.ref) == _PNG
        session = application.resume_session_for_command(session_id)
        draft = application.import_attachment(
            b"unsubmitted draft",
            display_name="draft.txt",
            mime_type="text/plain",
        )
        application.remove_attachment(draft.ref, session_id=session_id)
        with pytest.raises(AttachmentReferenceError):
            application.attachment_service.reference(session_id, draft.ref)
        with pytest.raises(AttachmentReferenceError):
            application.remove_attachment(imported.ref, session_id=session_id)
        restarted_store = SessionFileStore(tmp_path / "sessions")
        restarted = ApplicationSessionService(
            storage_root=tmp_path / "sessions",
            project_key=str(tmp_path.resolve()),
            instruction_loader=None,
            store=restarted_store,
        )
        recovered = restarted_store.read_session(session_id, expected_project_key=str(tmp_path.resolve()))
        assert recovered.transcript.entries[0].payload["part"]["asset_ref"] == imported.asset_ref
        history = restarted_store.read_history_page(session_id)
        assert history.units and history.units[0].entries[0].payload["part"]["type"] == "image"
        replay = restarted.project_replay(session_id)
        assert replay and replay[0].attachments[0]["asset_ref"] == imported.asset_ref
        assert replay[0].attachments[0]["mime_type"] == "image/png"
    finally:
        application.close()


def test_attachment_previews_are_bounded_and_system_resolution_keeps_original(
    tmp_path: Path,
) -> None:
    import random

    from PIL import Image

    raw = random.Random(12345).randbytes(700 * 500 * 3)
    source = tmp_path / "large.png"
    Image.frombytes("RGB", (700, 500), raw).save(source, optimize=False)
    application = _app_with_fake_provider(tmp_path)
    session = application.new_session_for_command()
    try:
        imported = application.import_attachment(
            source.read_bytes(),
            display_name="report.final.PDF",
            mime_type="application/pdf",
        )
        image = application.import_attachment(
            source.read_bytes(),
            display_name="large.png",
            mime_type="image/png",
        )
        thumbnail = application.preview_attachment(image.ref, session_id=session.session_id)
        full = application.preview_attachment(
            image.ref,
            session_id=session.session_id,
            mode="full",
        )
        assert thumbnail["preview_kind"] == "thumbnail"
        assert thumbnail["scaled"] is True
        assert int(thumbnail["preview_width"]) <= 160
        assert int(thumbnail["preview_height"]) <= 160
        assert len(str(thumbnail["data_url"])) < 400_000
        assert full["preview_kind"] == "full"
        assert int(full["preview_width"]) <= 2048
        assert len(str(full["data_url"])) < 6_000_000

        resolved = application.resolve_attachment(imported.ref, session_id=session.session_id)
        resolved_path = Path(str(resolved["path"]))
        assert resolved["source"] == "session_attachment"
        assert resolved["ref"] == imported.ref
        assert resolved["name"] == "report.final.PDF"
        assert resolved["mime"] == "application/pdf"
        assert resolved["display_name"] == "report.final.PDF"
        assert resolved_path.name == "report.final.PDF"
        assert resolved_path.read_bytes() == source.read_bytes()
        resolved_path.write_bytes(b"edited derived copy")
        refreshed = application.resolve_attachment(imported.ref, session_id=session.session_id)
        assert Path(str(refreshed["path"])).read_bytes() == source.read_bytes()
        cleanup = application.attachment_service.cleanup(session.session_id)
        assert cleanup["derived"] == 1
        assert not resolved_path.exists()
        original = (
            application.session_service.store.session_path(session.session_id)
            / "attachments"
            / imported.ref
            / "content.bin"
        )
        assert original.read_bytes() == source.read_bytes()
        with pytest.raises(ProviderConfigurationError):
            application.resolve_attachment(imported.ref, session_id="foreign-session")
    finally:
        application.close()


def test_text_attachment_preview_uses_name_extension_and_stays_bounded(
    tmp_path: Path,
) -> None:
    application = _app_with_fake_provider(tmp_path)
    session = application.new_session_for_command()
    try:
        imported = application.import_attachment(
            ("print('ok')\n" * 40_000).encode("utf-8"),
            display_name="script.py",
            mime_type="application/octet-stream",
        )
        preview = application.preview_attachment(
            imported.ref,
            session_id=session.session_id,
        )
        assert preview["preview_kind"] == "text"
        assert "print('ok')" in str(preview["text"])
        assert preview["truncated"] is True
        assert len(str(preview["text"]).encode("utf-8")) <= application.attachment_service.policy.preview_limit_bytes  # type: ignore[union-attr]
    finally:
        application.close()


def test_image_preview_rechecks_decoded_dimensions_after_import(
    tmp_path: Path,
) -> None:
    from PIL import Image

    application = _app_with_fake_provider(tmp_path)
    session = application.new_session_for_command()
    source = tmp_path / "oversized.png"
    Image.new("1", (9_000, 9_000), 0).save(source, format="PNG", optimize=True)
    try:
        imported = application.import_attachment(
            source.read_bytes(),
            display_name="claimed.tiff",
            mime_type="image/tiff",
        )
        with pytest.raises(AttachmentImageTooLarge):
            application.preview_attachment(imported.ref, session_id=session.session_id)
    finally:
        application.close()


def test_attachment_system_open_cache_obeys_derived_quota(tmp_path: Path) -> None:
    store = SessionFileStore(tmp_path / "sessions")
    session = store.create_session(project_key=str(tmp_path.resolve()))
    from uthcode.application.attachments import AttachmentService

    service = AttachmentService(
        store,
        policy=AttachmentPolicy(derived_quota_bytes=5),
    )
    first = service.import_bytes(
        session.session_id,
        b"123",
        display_name="first.txt",
        mime_type="text/plain",
    )
    second = service.import_bytes(
        session.session_id,
        b"456",
        display_name="second.txt",
        mime_type="text/plain",
    )

    service.resolve_for_system_descriptor(session.session_id, first.ref)
    with pytest.raises(AttachmentQuotaExceeded):
        service.resolve_for_system_descriptor(session.session_id, second.ref)


def test_attachment_import_rejects_excessive_decoded_image_dimensions(tmp_path: Path) -> None:
    application = _app_with_fake_provider(tmp_path)
    session = application.new_session_for_command()
    oversized = bytearray(_PNG)
    oversized[16:24] = struct.pack(">II", 100_000, 100_000)
    try:
        with pytest.raises(AttachmentImageTooLarge):
            application.import_attachment(
                bytes(oversized),
                display_name="oversized.png",
                mime_type="image/png",
            )
        assert application.attachment_service is not None
        assert application.attachment_service.files.list_references(session.session_id) == ()
    finally:
        application.close()


def test_headless_attachment_reference_must_belong_to_active_session(tmp_path: Path) -> None:
    application = _app_with_fake_provider(tmp_path)
    session_a = application.new_session_for_command()
    session_id = session_a.session_id
    try:
        imported = application.import_attachment(
            _PNG,
            display_name="owned.png",
            mime_type="image/png",
        )
        application.close()
        application.resume_session_for_command(session_id)
        foreign = ImagePart(
            f"attachment:other-session:{imported.ref}",
            imported.mime_type,
            imported.width,
            imported.height,
        )
        with pytest.raises(ProviderConfigurationError, match="active Session"):
            application.create_run().start_turn(MessageInput((foreign,)))
    finally:
        application.close()


def test_durable_transcript_reconciles_failed_submission_on_reopen_and_protects_original(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = _app_with_fake_provider(tmp_path)
    session = application.new_session_for_command()
    session_id = session.session_id
    try:
        imported = application.import_attachment(
            _PNG,
            display_name="reconcile.png",
            mime_type="image/png",
        )
        original_atomic_json = attachment_files._atomic_json

        def fail_attachment_metadata(path: Path, value: object) -> None:
            if path.name == "metadata.json":
                raise OSError("metadata write failed")
            original_atomic_json(path, value)  # type: ignore[arg-type]

        monkeypatch.setattr(attachment_files, "_atomic_json", fail_attachment_metadata)
        entries = transcript_entries_from_message(
            session.session_id,
            "reconcile-turn",
            1,
            Message("user", (ImagePart(imported.asset_ref, imported.mime_type, imported.width, imported.height),)),
        )
        outcome = session.append_transcript(entries)
        assert outcome.transcript_appended is True
        assert application.attachment_service is not None
        assert application.attachment_service.reference(session.session_id, imported.ref).submitted is False
        with pytest.raises(AttachmentReferenceError):
            application.remove_attachment(imported.ref, session_id=session.session_id)
        application.close()

        monkeypatch.undo()
        reopened = application.resume_session_for_command(session_id)
        assert len(reopened.transcript.entries) == 1
        assert application.attachment_service.reference(session_id, imported.ref).submitted is True
        with pytest.raises(AttachmentReferenceError):
            application.remove_attachment(imported.ref, session_id=session_id)
    finally:
        application.close()

@pytest.mark.asyncio
async def test_application_image_request_has_gate_accounting_and_real_responses_wire(
    tmp_path: Path,
) -> None:
    class _AsyncStream:
        def __init__(self, events: list[object]) -> None:
            self._events = iter(events)
            self.closed = False

        def __aiter__(self) -> "_AsyncStream":
            return self

        async def __anext__(self) -> object:
            try:
                return next(self._events)
            except StopIteration as exc:
                raise StopAsyncIteration from exc

        async def close(self) -> None:
            self.closed = True

    response = {
        "id": "response-1",
        "status": "completed",
        "output": [
            {
                "type": "message",
                "id": "message-1",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": "received"}],
            }
        ],
        "usage": {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12},
    }

    class _ResponsesClient:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []
            self.responses = SimpleNamespace(create=self.create)

        async def create(self, **kwargs: object) -> _AsyncStream:
            self.calls.append(kwargs)
            return _AsyncStream([{"type": "response.completed", "response": response}])

    class _RecordingProvider:
        def __init__(self, provider: OpenAIResponsesProvider) -> None:
            self.provider = provider
            self.identity = provider.identity
            self.requests = []

        def set_asset_resolver(self, resolver) -> None:
            self.provider.set_asset_resolver(resolver)

        async def stream(
            self,
            request,
            *,
            cancellation: CancellationToken,
        ) -> AsyncIterator[object]:
            self.requests.append(request)
            async for event in self.provider.stream(request, cancellation=cancellation):
                yield event

    client = _ResponsesClient()
    provider = _RecordingProvider(
        build_openai_responses_provider("vision-model", client=client)  # type: ignore[arg-type]
    )
    config = EffectiveConfig.single_model(
        "vision/ref",
        provider_profile_id="vision",
        provider_kind=ProviderKind.OPENAI_RESPONSES,
        remote_id="vision-model",
        api_key="configured-key",
        supports_images=True,
    )
    application = create_application(
        config,
        provider_builder=lambda _profile, _model: provider,
        runtime_context=_runtime(tmp_path),
        storage_root=tmp_path / "sessions",
    )
    session = application.new_session_for_command()
    try:
        imported = application.import_attachment(
            _PNG,
            display_name="screen.png",
            mime_type="image/png",
        )
        assert application.attachment_service is not None
        image = application.attachment_service.part(
            session.session_id,
            imported.ref,
            kind="image",
        )
        result = await application.create_run().start_turn(MessageInput((image,))).result()
        assert result.status is RunStatus.COMPLETED
        assert len(provider.requests) == 1
        request = provider.requests[0]
        accounting = request.metadata["image_accounting"]
        assert accounting["image_count"] == 1
        assert accounting["image_bytes"] == len(_PNG)
        assert accounting["image_tokens"] >= 1
        assert accounting["source"] == "attachment_store"
        request_accounting = request.metadata["request_accounting"]
        assert request_accounting["image_tokens"] == accounting["image_tokens"]
        assert request_accounting["image_estimate_available"] is True
        assert request_accounting["image_estimate_source"] == "attachment_store_dimensions"
        assert request.metadata["context_gate"]["hard_safe"] is True
        wire = client.calls[0]["input"]
        image_items = [
            item
            for value in wire
            for item in value.get("content", [])
            if item.get("type") == "input_image"
        ]
        assert image_items == [
            {
                "type": "input_image",
                "image_url": f"data:image/png;base64,{base64.b64encode(_PNG).decode('ascii')}",
                "detail": "auto",
            }
        ]
        assert application.attachment_service.reference(session.session_id, imported.ref).submitted is True
    finally:
        application.close()


def test_unsupported_image_model_preserves_model_and_attachment_draft(tmp_path: Path) -> None:
    application = _app_with_fake_provider(tmp_path)
    session = application.new_session_for_command()
    try:
        imported = application.import_attachment(
            _PNG,
            display_name="draft.png",
            mime_type="image/png",
        )
        history = application.import_attachment(
            _PNG,
            display_name="history.png",
            mime_type="image/png",
        )
        session.append_transcript(
            transcript_entries_from_message(
                session.session_id,
                "image-history",
                1,
                Message("user", (ImagePart(history.asset_ref, history.mime_type),)),
            )
        )
        with pytest.raises(ProviderConfigurationError):
            application.select_model("text/ref")
        assert application.current_model_ref == "vision/ref"
        assert application.attachment_service is not None
        assert application.attachment_service.reference(session.session_id, imported.ref).submitted is False
        assert application.attachment_service.read(session.session_id, imported.ref) == _PNG
        assert application.provider is not None
    finally:
        application.close()


@pytest.mark.asyncio
async def test_context_compaction_preserves_source_shrinks_request_and_allows_text_model(
    tmp_path: Path,
) -> None:
    class _CompactionProvider(FakeProvider):
        async def stream(
            self,
            request,
            *,
            cancellation: CancellationToken,
        ) -> AsyncIterator[object]:
            self.requests.append(request)
            cancellation.raise_if_cancelled()
            if request.metadata.get("context_compaction_request"):
                text = next(
                    part.text
                    for part in request.messages[0].parts
                    if isinstance(part, TextPart)
                )
                raw_coverage = text.split(
                    "Required coverage (copy only these Turn IDs):\n",
                    1,
                )[1]
                coverage = json.loads(raw_coverage)
                response = {
                    "entries": [
                        {
                            "turn_id": item["turn_id"],
                            "summary": "compressed image evidence",
                            "refs": item["refs"],
                        }
                        for item in coverage
                    ],
                    "coverage": [item["turn_id"] for item in coverage],
                }
                yield _completed(json.dumps(response, ensure_ascii=False))
                return
            yield _completed()

    vision = _CompactionProvider(
        model_limits=ModelLimits(max_input_tokens=256_000, source="test.compact")
    )
    text = FakeProvider(
        events=(_completed(),),
        model_limits=ModelLimits(max_input_tokens=256_000, source="test.text"),
    )
    application = _app_with_fake_provider(
        tmp_path,
        providers={"vision/ref": vision, "text/ref": text},
    )
    session = application.new_session_for_command()
    try:
        imported = application.import_attachment(
            _PNG,
            display_name="history.png",
            mime_type="image/png",
        )
        session.append_transcript(
            transcript_entries_from_message(
                session.session_id,
                "image-turn",
                1,
                Message("user", (ImagePart(imported.asset_ref, imported.mime_type),)),
            )
        )
        with pytest.raises(ProviderConfigurationError):
            application.select_model("text/ref")

        before_request, _ = application.context_service.compose_generation_request(
            (),
            run_id="before-compaction",
            session_id=session.session_id,
            transcript=session.transcript,
            timeline=Timeline(session.session_id),
            model="vision-model",
        )
        result = await application.compact_session()
        assert result.changed is True
        assert result.timeline is not None
        assert result.timeline.sequence_end == 1
        assert result.timeline.summary == "compressed image evidence"
        assert application.attachment_service is not None
        assert application.attachment_service.read(session.session_id, imported.ref) == _PNG

        after_request, _ = application.context_service.compose_generation_request(
            (),
            run_id="after-compaction",
            session_id=session.session_id,
            transcript=session.transcript,
            timeline=session.timeline,
            model="vision-model",
        )
        assert account_generation_request(after_request).input_tokens < account_generation_request(before_request).input_tokens

        application.select_model("text/ref")
        assert application.current_model_ref == "text/ref"
        text_result = await application.create_run().start_turn("continue in text").result()
        assert text_result.status is RunStatus.COMPLETED
        assert text.requests
        assert not any(
            isinstance(part, ImagePart)
            for message in text.requests[-1].messages
            for part in message.parts
        )
    finally:
        application.close()
