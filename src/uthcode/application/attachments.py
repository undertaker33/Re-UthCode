"""Application attachment import and Core-part projection."""

from __future__ import annotations

import mimetypes
from collections.abc import Iterable
from pathlib import Path

from uthcode.core.provider import ContentPart, FilePart, ImagePart
from uthcode.integrations.attachment_files import (
    AttachmentError,
    AttachmentFileStore,
    AttachmentPolicy,
    AttachmentReference,
)


class AttachmentService:
    """Own attachment import boundaries for one Session store.

    The service reads caller paths only during explicit import.  Once the
    bytes are copied, all subsequent operations use the opaque reference and
    the Session owner supplied by the caller.
    """

    def __init__(self, store: object, *, policy: AttachmentPolicy | None = None) -> None:
        self.files = AttachmentFileStore(store, policy=policy)

    def import_bytes(
        self,
        session_id: str,
        content: bytes | bytearray | memoryview,
        *,
        display_name: str,
        mime_type: str | None = None,
    ) -> AttachmentReference:
        return self.files.persist(
            session_id,
            content,
            display_name=display_name,
            mime_type=mime_type,
        )

    def import_path(
        self,
        session_id: str,
        path: str | Path,
        *,
        display_name: str | None = None,
        mime_type: str | None = None,
    ) -> AttachmentReference:
        source = Path(path).expanduser().resolve(strict=False)
        if not source.is_file():
            raise AttachmentError("attachment source is not a file")
        try:
            content = source.read_bytes()
        except OSError as exc:
            raise AttachmentError("attachment source could not be read") from exc
        name = display_name or source.name
        return self.import_bytes(
            session_id,
            content,
            display_name=name,
            mime_type=mime_type or mimetypes.guess_type(name)[0],
        )

    def read(self, session_id: str, ref: str) -> bytes:
        return self.files.read(session_id, ref)

    @property
    def policy(self) -> AttachmentPolicy:
        return self.files.policy

    def reference(self, session_id: str, ref: str) -> AttachmentReference:
        return self.files.reference(session_id, ref)

    def validate_image_dimensions(
        self,
        width: int | None,
        height: int | None,
    ) -> None:
        self.files.policy.validate_image_dimensions(width, height)

    def preview(self, session_id: str, ref: str) -> dict[str, object]:
        return self.files.preview(session_id, ref)

    def remove_draft(self, session_id: str, ref: str) -> None:
        self.files.remove_draft(session_id, ref)

    def mark_submitted(self, session_id: str, refs: Iterable[str]) -> tuple[AttachmentReference, ...]:
        return tuple(self.files.mark_submitted(session_id, ref) for ref in refs)

    def cleanup(self, session_id: str) -> dict[str, int]:
        return self.files.cleanup(session_id)

    def part(self, session_id: str, ref: str, *, kind: str | None = None) -> ContentPart:
        reference = self.reference(session_id, ref)
        selected = kind or ("image" if reference.mime_type.startswith("image/") else "file")
        if selected == "image":
            return ImagePart(
                reference.asset_ref,
                reference.mime_type,
                reference.width,
                reference.height,
            )
        if selected == "file":
            return FilePart(
                reference.asset_ref,
                reference.display_name,
                reference.mime_type,
                reference.size_bytes,
            )
        raise ValueError("kind must be image or file")


__all__ = ["AttachmentService"]
