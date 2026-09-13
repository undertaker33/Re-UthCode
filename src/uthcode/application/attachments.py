"""Application attachment import and Core-part projection."""

from __future__ import annotations

import mimetypes
import base64
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from uthcode.core.provider import ContentPart, FilePart, ImagePart
from uthcode.integrations.attachment_files import (
    AttachmentError,
    AttachmentFileStore,
    AttachmentPolicy,
    AttachmentReference,
)


class ArtifactError(RuntimeError):
    """A requested Desktop artifact is not a permitted local file."""

    def __init__(self, message: str, code: str = "artifact_unavailable") -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class ArtifactDescriptor:
    """Safe metadata for a local file that Main may open or reveal."""

    path: Path
    name: str
    kind: str
    mime_type: str
    size_bytes: int
    default_action: str
    preview_supported: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "path": str(self.path),
            "name": self.name,
            "kind": self.kind,
            "mime_type": self.mime_type,
            "size_bytes": self.size_bytes,
            "default_action": self.default_action,
            "preview_supported": self.preview_supported,
        }


class ArtifactService:
    """Validate local artifact references before a Desktop Main action."""

    _OFFICE_EXTENSIONS = frozenset(
        {".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".pdf"}
    )
    _EXECUTABLE_EXTENSIONS = frozenset(
        {".exe", ".com", ".bat", ".cmd", ".ps1", ".sh", ".msi", ".vbs"}
    )
    _UNSUPPORTED_EXTENSIONS = frozenset({".html", ".htm", ".svg"})
    _SHELL_MARKERS = frozenset({";", "|", "&", "\r", "\n", "<", ">"})

    def __init__(self, workdir: str | Path, *, preview_limit_bytes: int = 256 * 1024) -> None:
        self.workdir = Path(workdir).expanduser().resolve(strict=False)
        if isinstance(preview_limit_bytes, bool) or not isinstance(preview_limit_bytes, int) or preview_limit_bytes <= 0:
            raise ValueError("preview_limit_bytes must be positive")
        self.preview_limit_bytes = preview_limit_bytes

    def describe(
        self,
        value: str | Path,
        *,
        authorized_external: bool = False,
    ) -> ArtifactDescriptor:
        path = self._resolve(value)
        if not path.is_file():
            raise ArtifactError("artifact file is missing", "artifact_not_found")
        inside = self._inside_workdir(path)
        if not inside and not authorized_external:
            raise ArtifactError("artifact is outside the authorized workdir", "artifact_not_authorized")
        try:
            size = path.stat().st_size
        except OSError:
            raise ArtifactError("artifact metadata is unavailable") from None
        extension = path.suffix.lower()
        mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if extension in self._UNSUPPORTED_EXTENSIONS:
            kind = "unsupported"
            default_action = "reveal"
        elif extension in self._EXECUTABLE_EXTENSIONS:
            kind = "executable"
            default_action = "reveal"
        elif mime_type.startswith("image/"):
            kind = "image"
            default_action = "open"
        elif extension in self._OFFICE_EXTENSIONS:
            kind = "office"
            default_action = "open"
        else:
            kind = "file"
            default_action = "open"
        return ArtifactDescriptor(
            path=path,
            name=path.name,
            kind=kind,
            mime_type=mime_type,
            size_bytes=size,
            default_action=default_action,
            preview_supported=kind == "image" and size <= self.preview_limit_bytes,
        )

    def preview(
        self,
        value: str | Path,
        *,
        authorized_external: bool = False,
    ) -> dict[str, object]:
        descriptor = self.describe(value, authorized_external=authorized_external)
        if not descriptor.preview_supported:
            raise ArtifactError("artifact preview is unavailable", "artifact_preview_unavailable")
        try:
            data = descriptor.path.read_bytes()
        except OSError:
            raise ArtifactError("artifact preview is unavailable", "artifact_preview_unavailable") from None
        if len(data) > self.preview_limit_bytes:
            raise ArtifactError("artifact preview exceeds the local limit", "artifact_preview_unavailable")
        return {
            **descriptor.to_dict(),
            "data_url": f"data:{descriptor.mime_type};base64,{base64.b64encode(data).decode('ascii')}",
        }

    def _resolve(self, value: str | Path) -> Path:
        if isinstance(value, Path):
            raw = str(value)
        elif isinstance(value, str):
            raw = value
        else:
            raise ArtifactError("artifact path is invalid", "artifact_invalid")
        if not raw.strip() or "\x00" in raw or any(marker in raw for marker in self._SHELL_MARKERS):
            raise ArtifactError("artifact path is invalid", "artifact_invalid")
        if raw.lstrip().startswith("<") or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", raw):
            raise ArtifactError("artifact URI is not executable", "artifact_invalid")
        if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", raw) and not re.match(r"^[A-Za-z]:[\\/]", raw):
            raise ArtifactError("artifact URI is not executable", "artifact_invalid")
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = self.workdir / candidate
        return candidate.resolve(strict=False)

    def _inside_workdir(self, path: Path) -> bool:
        try:
            path.relative_to(self.workdir)
            return True
        except ValueError:
            return False


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


__all__ = ["ArtifactDescriptor", "ArtifactError", "ArtifactService", "AttachmentService"]
