"""Application attachment import and Core-part projection."""

from __future__ import annotations

import mimetypes
import base64
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from uthcode.core.provider import ContentPart, FilePart, ImagePart
from uthcode.integrations.attachment_files import (
    AttachmentError,
    AttachmentFileStore,
    AttachmentPolicy,
    AttachmentReference,
    ImagePreviewLimitError,
    bounded_preview_text,
    decode_preview_text,
    read_bounded_preview,
    render_image_preview,
    TEXT_PREVIEW_EXTENSIONS,
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
    preview_kind: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "path": str(self.path),
            "name": self.name,
            "kind": self.kind,
            "mime_type": self.mime_type,
            "size_bytes": self.size_bytes,
            "default_action": self.default_action,
            "preview_supported": self.preview_supported,
            "preview_kind": self.preview_kind,
        }


class ArtifactService:
    """Validate local artifact references before a Desktop Main action."""

    _IMAGE_SOURCE_LIMIT_BYTES = 16 * 1024 * 1024

    _OFFICE_EXTENSIONS = frozenset(
        {".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".pdf"}
    )
    _EXECUTABLE_EXTENSIONS = frozenset(
        {".exe", ".com", ".bat", ".cmd", ".ps1", ".sh", ".msi", ".vbs"}
    )
    _UNSUPPORTED_EXTENSIONS = frozenset({".html", ".htm", ".svg"})
    _TEXT_EXTENSIONS = TEXT_PREVIEW_EXTENSIONS
    _SHELL_MARKERS = frozenset({";", "|", "&", "\r", "\n", "<", ">"})

    def __init__(
        self,
        workdir: str | Path,
        *,
        preview_limit_bytes: int = 256 * 1024,
        full_preview_limit_bytes: int = 4 * 1024 * 1024,
    ) -> None:
        self.workdir = Path(workdir).expanduser().resolve(strict=False)
        if isinstance(preview_limit_bytes, bool) or not isinstance(preview_limit_bytes, int) or preview_limit_bytes <= 0:
            raise ValueError("preview_limit_bytes must be positive")
        if (
            isinstance(full_preview_limit_bytes, bool)
            or not isinstance(full_preview_limit_bytes, int)
            or full_preview_limit_bytes <= 0
        ):
            raise ValueError("full_preview_limit_bytes must be positive")
        self.preview_limit_bytes = preview_limit_bytes
        self.full_preview_limit_bytes = full_preview_limit_bytes

    @classmethod
    def _classify(cls, name: str, mime_type: str) -> tuple[str, str, bool, str | None]:
        extension = Path(name).suffix.lower()
        if extension in cls._UNSUPPORTED_EXTENSIONS:
            kind = "unsupported"
            default_action = "reveal"
        elif extension in cls._EXECUTABLE_EXTENSIONS:
            kind = "executable"
            default_action = "reveal"
        elif mime_type.startswith("image/"):
            kind = "image"
            default_action = "open"
        elif extension in cls._OFFICE_EXTENSIONS:
            kind = "office"
            default_action = "open"
        elif mime_type.startswith("text/") or extension in cls._TEXT_EXTENSIONS:
            kind = "text"
            default_action = "open"
        else:
            kind = "file"
            default_action = "open"
        preview_kind = "image" if kind == "image" else "text" if kind == "text" else None
        return kind, default_action, kind in {"image", "text"}, preview_kind

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
        mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        kind, default_action, preview_supported, preview_kind = self._classify(
            path.name, mime_type
        )
        return ArtifactDescriptor(
            path=path,
            name=path.name,
            kind=kind,
            mime_type=mime_type,
            size_bytes=size,
            default_action=default_action,
            preview_supported=preview_supported,
            preview_kind=preview_kind,
        )

    def preview(
        self,
        value: str | Path,
        *,
        authorized_external: bool = False,
        mode: str = "thumbnail",
    ) -> dict[str, object]:
        descriptor = self.describe(value, authorized_external=authorized_external)
        if not descriptor.preview_supported:
            raise ArtifactError("artifact preview is unavailable", "artifact_preview_unavailable")
        if mode not in {"thumbnail", "full"}:
            raise ArtifactError("artifact preview mode is invalid", "artifact_invalid")
        try:
            if descriptor.kind == "image":
                if descriptor.size_bytes > self._IMAGE_SOURCE_LIMIT_BYTES:
                    raise ArtifactError(
                        "artifact image source exceeds the local limit",
                        "artifact_preview_unavailable",
                    )
                with descriptor.path.open("rb") as handle:
                    data = handle.read(self._IMAGE_SOURCE_LIMIT_BYTES + 1)
                if len(data) > self._IMAGE_SOURCE_LIMIT_BYTES:
                    raise ArtifactError(
                        "artifact image source exceeds the local limit",
                        "artifact_preview_unavailable",
                    )
                limit = self.preview_limit_bytes if mode == "thumbnail" else self.full_preview_limit_bytes
                rendered = render_image_preview(
                    data,
                    descriptor.mime_type,
                    mode=mode,
                    max_edge=160 if mode == "thumbnail" else 2048,
                    max_bytes=limit,
                )
                if rendered is None:
                    if len(data) > limit:
                        raise ArtifactError(
                            "artifact image preview exceeds the local limit",
                            "artifact_preview_unavailable",
                        )
                    return {
                        **descriptor.to_dict(),
                        "preview_kind": mode,
                        "preview_mime_type": descriptor.mime_type,
                        "preview_width": None,
                        "preview_height": None,
                        "scaled": False,
                        "truncated": False,
                        "data_url": f"data:{descriptor.mime_type};base64,{base64.b64encode(data).decode('ascii')}",
                    }
                preview_mime = str(rendered["mime_type"])
                return {
                    **descriptor.to_dict(),
                    "preview_kind": mode,
                    "preview_mime_type": preview_mime,
                    "preview_width": rendered["width"],
                    "preview_height": rendered["height"],
                    "scaled": rendered["scaled"],
                    "truncated": False,
                    "data_url": f"data:{preview_mime};base64,{base64.b64encode(rendered['data']).decode('ascii')}",
                }

            limit = self.preview_limit_bytes if mode == "thumbnail" else self.full_preview_limit_bytes
            data, source_truncated = read_bounded_preview(descriptor.path, limit)
            text, encoding = decode_preview_text(data)
            text, truncated = bounded_preview_text(
                text,
                limit,
                source_truncated=source_truncated,
            )
            return {
                **descriptor.to_dict(),
                "preview_kind": "text",
                "text": text,
                "encoding": encoding,
                "truncated": truncated,
            }
        except ArtifactError:
            raise
        except ImagePreviewLimitError:
            raise ArtifactError(
                "artifact image dimensions exceed the local limit",
                "artifact_preview_unavailable",
            ) from None
        except OSError:
            raise ArtifactError("artifact preview is unavailable", "artifact_preview_unavailable") from None
        except UnicodeError:
            raise ArtifactError(
                "artifact text encoding is unsupported",
                "artifact_preview_unavailable",
            ) from None

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

    def reference(
        self,
        session_id: str,
        ref: str,
        *,
        verify_content: bool = True,
    ) -> AttachmentReference:
        return self.files.reference(
            session_id,
            ref,
            verify_content=verify_content,
        )

    def validate_image_dimensions(
        self,
        width: int | None,
        height: int | None,
    ) -> None:
        self.files.policy.validate_image_dimensions(width, height)

    def resolve(self, session_id: str, ref: str) -> tuple[Path, AttachmentReference]:
        """Resolve a Session-owned ref for a later authorized Main action."""

        return self.files.resolve(session_id, ref)

    def resolve_for_system(self, session_id: str, ref: str) -> tuple[Path, AttachmentReference]:
        """Resolve a Session-owned ref to a safe, extension-bearing cache path."""

        return self.files.materialize_open_path(session_id, ref)

    def resolve_for_system_descriptor(self, session_id: str, ref: str) -> dict[str, object]:
        """Build the minimal trusted DTO consumed by Desktop Main.

        The caller supplies only the opaque ref and current Session identity.
        The returned path is a service-created derived copy whose suffix comes
        from the stored display name; it is never a renderer-supplied path.
        """

        path, reference = self.resolve_for_system(session_id, ref)
        mime_type = reference.mime_type or mimetypes.guess_type(reference.display_name)[0]
        if not mime_type:
            mime_type = "application/octet-stream"
        kind, default_action, _preview_supported, _preview_kind = ArtifactService._classify(
            reference.display_name, mime_type
        )
        return {
            "source": "session_attachment",
            "session_id": session_id,
            "ref": reference.ref,
            "asset_ref": reference.asset_ref,
            "path": str(path),
            # ``name``/``mime`` are the compact Main contract.  Keep the
            # descriptive aliases for existing Renderer projections while
            # both values continue to come from Session metadata.
            "name": reference.display_name,
            "mime": mime_type,
            "display_name": reference.display_name,
            "mime_type": mime_type,
            "size_bytes": reference.size_bytes,
            "kind": kind,
            "default_action": default_action,
        }

    def preview(
        self,
        session_id: str,
        ref: str,
        *,
        mode: str = "thumbnail",
        max_edge: int | None = None,
    ) -> dict[str, object]:
        return self.files.preview(session_id, ref, mode=mode, max_edge=max_edge)

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


def project_history_attachment(
    service: AttachmentService | None,
    session_id: str,
    attachment: Mapping[str, object],
) -> Mapping[str, object]:
    """Project one Core attachment fact into safe, Session-backed history DTO."""

    source = dict(attachment)
    source.pop("data_url", None)
    asset_ref = source.get("asset_ref")
    if not isinstance(asset_ref, str) or not asset_ref.startswith("attachment:"):
        # SourcePart may identify a non-Session source. It has no preview
        # authority in this projection and remains a ref-only Core fact.
        if source.get("type") == "source":
            return source
        return _unavailable_history_attachment(source, session_id)

    parts = asset_ref.split(":", 2)
    ref = (
        parts[2]
        if len(parts) == 3 and parts[1] == session_id and parts[2]
        else None
    )
    if ref is None or service is None:
        return _unavailable_history_attachment(source, session_id, ref=ref)
    try:
        reference = service.reference(session_id, ref, verify_content=False)
    except AttachmentError:
        return _unavailable_history_attachment(source, session_id, ref=ref)

    source.update(
        {
            "ref": reference.ref,
            "asset_ref": reference.asset_ref,
            "display_name": reference.display_name,
            "mime_type": reference.mime_type,
            "size_bytes": reference.size_bytes,
            "available": True,
        }
    )
    if reference.width is None:
        source.pop("width", None)
    else:
        source["width"] = reference.width
    if reference.height is None:
        source.pop("height", None)
    else:
        source["height"] = reference.height
    return source


def _unavailable_history_attachment(
    source: Mapping[str, object],
    session_id: str,
    *,
    ref: str | None = None,
) -> Mapping[str, object]:
    """Keep missing/corrupt attachments local without invented metadata."""

    value: dict[str, object] = {
        key: item
        for key, item in source.items()
        if key
        in {
            "type",
            "asset_ref",
            "mime_type",
            "width",
            "height",
            "page",
            "sheet",
            "range",
            "slide",
            "paragraph",
        }
    }
    asset_ref = value.get("asset_ref")
    if ref is None and isinstance(asset_ref, str):
        parts = asset_ref.split(":", 2)
        if len(parts) == 3 and parts[0] == "attachment" and parts[1] == session_id and parts[2]:
            ref = parts[2]
    if ref is not None:
        value["ref"] = ref
    value["available"] = False
    value["error_code"] = "attachment_unavailable"
    return value


__all__ = [
    "ArtifactDescriptor",
    "ArtifactError",
    "ArtifactService",
    "AttachmentService",
    "project_history_attachment",
]
