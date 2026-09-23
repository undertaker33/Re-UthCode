"""Durable, Session-owned attachment bytes and bounded previews.

Attachments are imported once into the owning Session before a Turn starts.
The Core only carries the opaque reference returned here; bytes are read at an
Integration boundary when a provider request is built.  The store deliberately
does not expose arbitrary filesystem reads or delete submitted originals.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import io
import json
import locale
import mimetypes
import os
import re
import shutil
import struct
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


ATTACHMENT_SCHEMA_VERSION = 1
_REF_PATTERN = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
TEXT_PREVIEW_EXTENSIONS = frozenset(
    {
        ".c",
        ".cc",
        ".cpp",
        ".cs",
        ".css",
        ".dart",
        ".diff",
        ".env",
        ".go",
        ".h",
        ".hpp",
        ".ini",
        ".ipynb",
        ".java",
        ".js",
        ".jsx",
        ".json",
        ".kt",
        ".log",
        ".lua",
        ".m",
        ".markdown",
        ".md",
        ".mm",
        ".php",
        ".pl",
        ".py",
        ".rb",
        ".rs",
        ".rst",
        ".svelte",
        ".sql",
        ".swift",
        ".toml",
        ".ts",
        ".tsx",
        ".txt",
        ".vue",
        ".xml",
        ".yaml",
        ".yml",
    }
)


class AttachmentError(RuntimeError):
    """Base error for Session attachment operations."""

    code = "attachment_error"


class AttachmentReferenceError(AttachmentError):
    code = "invalid_attachment_reference"


class AttachmentTooLarge(AttachmentError):
    code = "attachment_too_large"


class AttachmentImageTooLarge(AttachmentError):
    code = "attachment_image_too_large"


class AttachmentQuotaExceeded(AttachmentError):
    code = "attachment_quota_exceeded"


class AttachmentPersistenceError(AttachmentError):
    code = "attachment_persistence_failed"


class AttachmentIntegrityError(AttachmentError):
    code = "attachment_integrity_failed"


class ImagePreviewLimitError(ValueError):
    """Image dimensions would exceed the bounded preview decode policy."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _validate_ref(value: object) -> str:
    if not isinstance(value, str) or not _REF_PATTERN.fullmatch(value):
        raise AttachmentReferenceError("attachment ref must be an opaque identifier")
    return value


def _safe_session_path(store: object, session_id: str) -> Path:
    if not isinstance(session_id, str) or not session_id or session_id in {".", ".."}:
        raise AttachmentReferenceError("invalid Session ownership")
    if "/" in session_id or "\\" in session_id or "\x00" in session_id:
        raise AttachmentReferenceError("invalid Session ownership")
    session_path = getattr(store, "session_path", None)
    if not callable(session_path):
        raise TypeError("store must provide session_path(session_id)")
    path = Path(session_path(session_id)).resolve(strict=False)
    if not path.is_dir():
        raise AttachmentReferenceError("unknown Session ownership")
    return path


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(str(path), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def _atomic_json(path: Path, value: Mapping[str, object]) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _atomic_copy(source: Path, target: Path) -> None:
    """Copy one immutable attachment to a derived path atomically."""

    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        with source.open("rb") as source_handle, temporary.open("xb") as target_handle:
            shutil.copyfileobj(source_handle, target_handle, length=1024 * 1024)
            target_handle.flush()
            os.fsync(target_handle.fileno())
        os.replace(temporary, target)
        _fsync_directory(target.parent)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _safe_name(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("display_name must be a non-empty string")
    name = Path(value).name.strip()
    if not name or name in {".", ".."} or "\x00" in name:
        raise ValueError("display_name is invalid")
    return name[:255]


def _positive_optional(value: object, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field} must be a positive integer or None")
    return value


@dataclass(frozen=True, slots=True)
class AttachmentPolicy:
    """Local byte and decoded-image limits for import and Session ownership."""

    single_attachment_hard_cap_bytes: int = 16 * 1024 * 1024
    session_quota_bytes: int = 64 * 1024 * 1024
    preview_limit_bytes: int = 256 * 1024
    derived_quota_bytes: int = 16 * 1024 * 1024
    max_image_width: int = 8192
    max_image_height: int = 8192
    max_image_pixels: int = 50_000_000

    def __post_init__(self) -> None:
        for name in (
            "single_attachment_hard_cap_bytes",
            "session_quota_bytes",
            "preview_limit_bytes",
            "derived_quota_bytes",
            "max_image_width",
            "max_image_height",
            "max_image_pixels",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if self.preview_limit_bytes > self.single_attachment_hard_cap_bytes:
            raise ValueError("preview_limit_bytes cannot exceed attachment hard cap")

    def validate_image_dimensions(
        self,
        width: int | None,
        height: int | None,
    ) -> None:
        if width is None or height is None:
            return
        if width > self.max_image_width or height > self.max_image_height:
            raise AttachmentImageTooLarge("image dimensions exceed the import policy")
        if width * height > self.max_image_pixels:
            raise AttachmentImageTooLarge("image pixel count exceeds the import policy")


@dataclass(frozen=True, slots=True)
class AttachmentReference:
    """Opaque, Session-scoped identity for one imported original."""

    ref: str
    session_id: str
    display_name: str
    mime_type: str
    size_bytes: int
    sha256: str
    width: int | None = None
    height: int | None = None
    created_at: str = ""
    submitted: bool = False

    def __post_init__(self) -> None:
        _validate_ref(self.ref)
        if not isinstance(self.session_id, str) or not self.session_id.strip():
            raise ValueError("session_id must be a non-empty string")
        object.__setattr__(self, "display_name", _safe_name(self.display_name))
        if not isinstance(self.mime_type, str) or not self.mime_type.strip():
            raise ValueError("mime_type must be a non-empty string")
        if isinstance(self.size_bytes, bool) or not isinstance(self.size_bytes, int) or self.size_bytes < 0:
            raise ValueError("size_bytes must be a non-negative integer")
        if not isinstance(self.sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", self.sha256):
            raise ValueError("sha256 must be a lowercase SHA-256 digest")
        object.__setattr__(self, "width", _positive_optional(self.width, "width"))
        object.__setattr__(self, "height", _positive_optional(self.height, "height"))
        if not isinstance(self.created_at, str) or not self.created_at.strip():
            object.__setattr__(self, "created_at", _now())
        if not isinstance(self.submitted, bool):
            raise TypeError("submitted must be a boolean")

    @property
    def asset_ref(self) -> str:
        return f"attachment:{self.session_id}:{self.ref}"

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": ATTACHMENT_SCHEMA_VERSION,
            "ref": self.ref,
            "session_id": self.session_id,
            "display_name": self.display_name,
            "mime_type": self.mime_type,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "width": self.width,
            "height": self.height,
            "created_at": self.created_at,
            "submitted": self.submitted,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "AttachmentReference":
        if not isinstance(value, Mapping):
            raise AttachmentIntegrityError("attachment metadata is not an object")
        if value.get("schema_version") != ATTACHMENT_SCHEMA_VERSION:
            raise AttachmentIntegrityError("unsupported attachment metadata version")
        try:
            return cls(
                ref=value["ref"],  # type: ignore[arg-type]
                session_id=value["session_id"],  # type: ignore[arg-type]
                display_name=value["display_name"],  # type: ignore[arg-type]
                mime_type=value["mime_type"],  # type: ignore[arg-type]
                size_bytes=value["size_bytes"],  # type: ignore[arg-type]
                sha256=value["sha256"],  # type: ignore[arg-type]
                width=value.get("width"),  # type: ignore[arg-type]
                height=value.get("height"),  # type: ignore[arg-type]
                created_at=value.get("created_at", ""),  # type: ignore[arg-type]
                submitted=value.get("submitted", False),  # type: ignore[arg-type]
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise AttachmentIntegrityError("attachment metadata is invalid") from exc


def _image_dimensions(data: bytes, mime_type: str) -> tuple[int | None, int | None]:
    """Read dimensions from common image headers without a binary dependency."""

    try:
        if mime_type == "image/png" and data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
            width, height = struct.unpack(">II", data[16:24])
            return (width or None, height or None)
        if mime_type == "image/gif" and data[:6] in {b"GIF87a", b"GIF89a"} and len(data) >= 10:
            width, height = struct.unpack("<HH", data[6:10])
            return (width or None, height or None)
        if mime_type == "image/webp" and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            if data[12:16] == b"VP8X" and len(data) >= 30:
                width = 1 + int.from_bytes(data[24:27], "little")
                height = 1 + int.from_bytes(data[27:30], "little")
                return width, height
        if mime_type in {"image/jpeg", "image/jpg"} and data[:2] == b"\xff\xd8":
            index = 2
            while index + 9 < len(data):
                if data[index] != 0xFF:
                    index += 1
                    continue
                marker = data[index + 1]
                index += 2
                if marker in {0xD8, 0xD9} or 0xD0 <= marker <= 0xD7:
                    continue
                if index + 2 > len(data):
                    break
                block_size = int.from_bytes(data[index:index + 2], "big")
                if block_size < 2 or index + block_size > len(data):
                    break
                if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
                    height = int.from_bytes(data[index + 3:index + 5], "big")
                    width = int.from_bytes(data[index + 5:index + 7], "big")
                    return (width or None, height or None)
                index += block_size
    except (IndexError, struct.error, ValueError):
        return None, None
    return None, None


def read_bounded_preview(path: Path, limit_bytes: int) -> tuple[bytes, bool]:
    """Read a bounded prefix and report whether the source exceeds the limit."""

    if isinstance(limit_bytes, bool) or not isinstance(limit_bytes, int) or limit_bytes <= 0:
        raise ValueError("limit_bytes must be a positive integer")
    size = path.stat().st_size
    # A few extra bytes let strict decoders finish a UTF-8 code point at the
    # boundary without reading the rest of a large attachment.
    with path.open("rb") as handle:
        data = handle.read(limit_bytes + 16)
    return data, size > limit_bytes or size > len(data)


def decode_preview_text(data: bytes) -> tuple[str, str]:
    """Decode a text preview strictly, never replacing undecodable bytes."""

    encodings = ["utf-8-sig"]
    if data.startswith((b"\xff\xfe", b"\xfe\xff", b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")):
        encodings.extend(("utf-16", "utf-32"))
    preferred = locale.getpreferredencoding(False)
    if preferred:
        encodings.append(preferred)
    try:
        current = locale.getencoding()
    except AttributeError:  # pragma: no cover - Python 3.11 fallback
        current = preferred
    if current:
        encodings.append(current)
    if os.name == "nt":
        # Windows attachments commonly come from the active Chinese code
        # page; keep this fallback platform-scoped so binary bytes are not
        # silently accepted as text on POSIX hosts.
        encodings.append("cp936")
    seen: set[str] = set()
    for encoding in encodings:
        normalized = encoding.casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        try:
            value = data.decode(encoding, errors="strict")
        except (LookupError, UnicodeDecodeError):
            continue
        if "\x00" in value:
            continue
        return value, encoding
    raise UnicodeError("unsupported text encoding")


def bounded_preview_text(
    value: str,
    limit_bytes: int,
    *,
    source_truncated: bool,
) -> tuple[str, bool]:
    if isinstance(limit_bytes, bool) or not isinstance(limit_bytes, int) or limit_bytes <= 0:
        raise ValueError("limit_bytes must be a positive integer")
    encoded = value.encode("utf-8")
    if len(encoded) <= limit_bytes and not source_truncated:
        return value, False
    marker = "\n[truncated]"
    marker_bytes = marker.encode("utf-8")
    if limit_bytes <= len(marker_bytes):
        return marker_bytes[:limit_bytes].decode("utf-8", errors="ignore"), True
    clipped = encoded[: limit_bytes - len(marker_bytes)]
    while clipped:
        try:
            return clipped.decode("utf-8") + marker, True
        except UnicodeDecodeError:
            clipped = clipped[:-1]
    return marker[:limit_bytes], True


def _is_text_attachment(reference: "AttachmentReference") -> bool:
    return (
        reference.mime_type.startswith("text/")
        or Path(reference.display_name).suffix.lower() in TEXT_PREVIEW_EXTENSIONS
    )


def render_image_preview(
    data: bytes,
    mime_type: str,
    *,
    mode: str = "thumbnail",
    max_edge: int | None = None,
    max_bytes: int = 256 * 1024,
    max_width: int = 8192,
    max_height: int = 8192,
    max_pixels: int = 50_000_000,
) -> dict[str, object] | None:
    """Encode a bounded image preview without changing the stored original.

    ``thumbnail`` is capped at a 160px long edge for cards. ``full`` is a
    separately requested, still bounded view capped at 2048px and 4 MiB by
    default. Pillow is loaded lazily so attachment metadata and provider
    resolution do not require image decoding.
    """

    if mode not in {"thumbnail", "full"}:
        raise ValueError("image preview mode must be thumbnail or full")
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0:
        raise ValueError("max_bytes must be a positive integer")
    if (
        isinstance(max_width, bool)
        or not isinstance(max_width, int)
        or max_width <= 0
        or isinstance(max_height, bool)
        or not isinstance(max_height, int)
        or max_height <= 0
        or isinstance(max_pixels, bool)
        or not isinstance(max_pixels, int)
        or max_pixels <= 0
    ):
        raise ValueError("image decode limits must be positive integers")
    default_edge = 160 if mode == "thumbnail" else 2048
    hard_edge = default_edge
    if max_edge is not None:
        if isinstance(max_edge, bool) or not isinstance(max_edge, int) or max_edge <= 0:
            raise ValueError("max_edge must be a positive integer or None")
        hard_edge = min(default_edge, max_edge)
    hard_bytes = min(max_bytes, 256 * 1024 if mode == "thumbnail" else 4 * 1024 * 1024)
    try:
        from PIL import Image, ImageOps
    except ImportError:
        return None
    try:
        with Image.open(io.BytesIO(data)) as opened:
            original_width, original_height = opened.size
            if (
                original_width <= 0
                or original_height <= 0
                or original_width > max_width
                or original_height > max_height
                or original_width * original_height > max_pixels
            ):
                raise ImagePreviewLimitError("image dimensions exceed the preview decode policy")
            opened.load()
            image = ImageOps.exif_transpose(opened).copy()
            original_width, original_height = image.size
            if (
                original_width <= 0
                or original_height <= 0
                or original_width > max_width
                or original_height > max_height
                or original_width * original_height > max_pixels
            ):
                raise ImagePreviewLimitError("image dimensions exceed the preview decode policy")
    except ImagePreviewLimitError:
        raise
    except Exception:
        return None
    if original_width <= 0 or original_height <= 0:
        return None

    image.thumbnail((hard_edge, hard_edge), Image.Resampling.LANCZOS)
    has_alpha = "A" in image.getbands() or image.mode in {"P", "LA"}
    output_mime = "image/png" if has_alpha else "image/jpeg"

    def encode(current: object, *, quality: int = 85) -> bytes:
        output = io.BytesIO()
        if output_mime == "image/png":
            png = current
            if getattr(png, "mode", None) not in {"1", "L", "LA", "P", "RGB", "RGBA"}:
                png = png.convert("RGBA")
            png.save(output, format="PNG", optimize=True)
        else:
            rgb = current.convert("RGB") if getattr(current, "mode", None) != "RGB" else current
            rgb.save(output, format="JPEG", quality=quality, optimize=True)
        return output.getvalue()

    payload = encode(image)
    # High-noise PNGs can exceed the thumbnail budget even after scaling. Keep
    # shrinking the derived image until the wire payload is bounded. A final
    # opaque JPEG fallback handles pathological transparent PNGs without ever
    # returning an unbounded data URL.
    for _ in range(8):
        if len(payload) <= hard_bytes or max(image.size) <= 1:
            break
        next_edge = max(1, int(max(image.size) * 0.8))
        image.thumbnail((next_edge, next_edge), Image.Resampling.LANCZOS)
        payload = encode(image)
    if len(payload) > hard_bytes:
        output_mime = "image/jpeg"
        rgb = Image.new("RGB", image.size, "white")
        if "A" in image.getbands():
            rgb.paste(image.convert("RGBA"), mask=image.getchannel("A"))
        else:
            rgb.paste(image.convert("RGB"))
        image = rgb
        for quality in (80, 65, 50, 35):
            payload = encode(image, quality=quality)
            if len(payload) <= hard_bytes:
                break
    if len(payload) > hard_bytes:
        return None
    return {
        "data": payload,
        "mime_type": output_mime,
        "width": int(image.width),
        "height": int(image.height),
        "original_width": original_width,
        "original_height": original_height,
        "scaled": image.size != (original_width, original_height),
        "truncated": False,
    }


class AttachmentFileStore:
    """Atomic attachment file store rooted inside a Session directory."""

    def __init__(self, store: object, *, policy: AttachmentPolicy | None = None) -> None:
        self._store = store
        self.policy = AttachmentPolicy() if policy is None else policy
        if not isinstance(self.policy, AttachmentPolicy):
            raise TypeError("policy must be an AttachmentPolicy or None")

    def _attachments_path(self, session_id: str) -> Path:
        path = _safe_session_path(self._store, session_id) / "attachments"
        path.mkdir(exist_ok=True)
        return path

    def _used_bytes(self, root: Path) -> int:
        total = 0
        for content in root.glob("*/content.bin"):
            try:
                total += content.stat().st_size
            except OSError as exc:
                raise AttachmentPersistenceError("could not inspect attachment quota") from exc
        return total

    def persist(
        self,
        session_id: str,
        content: bytes | bytearray | memoryview,
        *,
        display_name: str,
        mime_type: str | None = None,
    ) -> AttachmentReference:
        if isinstance(content, memoryview):
            content = content.tobytes()
        if not isinstance(content, (bytes, bytearray)):
            raise TypeError("content must be bytes")
        data = bytes(content)
        if len(data) > self.policy.single_attachment_hard_cap_bytes:
            raise AttachmentTooLarge("attachment exceeds the single-file hard cap")
        root = self._attachments_path(session_id)
        if self._used_bytes(root) + len(data) > self.policy.session_quota_bytes:
            raise AttachmentQuotaExceeded("Session attachment quota exceeded")
        name = _safe_name(display_name)
        guessed = mimetypes.guess_type(name)[0]
        resolved_mime = mime_type or guessed or "application/octet-stream"
        if not isinstance(resolved_mime, str) or not resolved_mime.strip() or "/" not in resolved_mime:
            raise ValueError("mime_type must be a media type")
        reference = uuid.uuid4().hex
        final_path = root / reference
        temporary_path = root / f".{reference}.{uuid.uuid4().hex}.tmp"
        digest = hashlib.sha256(data).hexdigest()
        width, height = _image_dimensions(data, resolved_mime) if resolved_mime.startswith("image/") else (None, None)
        self.policy.validate_image_dimensions(width, height)
        metadata = AttachmentReference(
            reference,
            session_id,
            name,
            resolved_mime,
            len(data),
            digest,
            width,
            height,
            _now(),
            False,
        )
        try:
            temporary_path.mkdir()
            content_path = temporary_path / "content.bin"
            with content_path.open("wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            _atomic_json(temporary_path / "metadata.json", metadata.to_dict())
            _fsync_directory(temporary_path)
            os.replace(temporary_path, final_path)
            _fsync_directory(root)
        except Exception as exc:
            shutil.rmtree(temporary_path, ignore_errors=True)
            if final_path.exists():
                shutil.rmtree(final_path, ignore_errors=True)
            if isinstance(exc, AttachmentError):
                raise
            raise AttachmentPersistenceError("could not durably persist attachment") from exc
        return metadata

    def _resolve(
        self,
        session_id: str,
        ref: str,
        *,
        verify_content: bool = True,
    ) -> tuple[Path, AttachmentReference]:
        _validate_ref(ref)
        session_path = _safe_session_path(self._store, session_id)
        root = (session_path / "attachments").resolve(strict=False)
        result_path = (root / ref).resolve(strict=False)
        if root not in result_path.parents:
            raise AttachmentReferenceError("attachment ref escaped its Session")
        if not result_path.is_dir():
            raise AttachmentReferenceError("attachment ref is not present in this Session")
        content_path = result_path / "content.bin"
        try:
            value = json.loads((result_path / "metadata.json").read_text(encoding="utf-8"))
            reference = AttachmentReference.from_dict(value)
            if not content_path.is_file():
                raise OSError("attachment content is not a file")
            content_size = content_path.stat().st_size
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise AttachmentIntegrityError("attachment files are unreadable") from exc
        if reference.session_id != session_id or reference.ref != ref:
            raise AttachmentIntegrityError("attachment ownership metadata is invalid")
        if content_size != reference.size_bytes:
            raise AttachmentIntegrityError("attachment size or hash does not match metadata")
        if verify_content:
            try:
                data = content_path.read_bytes()
            except OSError as exc:
                raise AttachmentIntegrityError("attachment content is unreadable") from exc
            if hashlib.sha256(data).hexdigest() != reference.sha256:
                raise AttachmentIntegrityError("attachment size or hash does not match metadata")
        if reference.mime_type.startswith("image/"):
            self.policy.validate_image_dimensions(reference.width, reference.height)
        return result_path, reference

    def resolve(self, session_id: str, ref: str) -> tuple[Path, AttachmentReference]:
        """Resolve one Session-owned ref to its stored path and metadata.

        The caller must already have a Session identity. This method never
        accepts a filesystem path or a provider/model URI, so it is suitable
        for the Application boundary that prepares a later Main open/reveal.
        """

        return self._resolve(session_id, ref)

    def _derived_bytes(self, root: Path) -> int:
        total = 0
        for path in root.glob("*/derived/**/*"):
            if not path.is_file():
                continue
            try:
                total += path.stat().st_size
            except OSError as exc:
                raise AttachmentPersistenceError(
                    "could not inspect derived attachment quota"
                ) from exc
        return total

    def _ensure_derived_capacity(self, target: Path, size_bytes: int) -> None:
        root = target.parents[3]
        try:
            existing = target.stat().st_size if target.is_file() else 0
        except OSError as exc:
            raise AttachmentPersistenceError(
                "could not inspect derived attachment quota"
            ) from exc
        projected = self._derived_bytes(root) - existing + size_bytes
        if projected > self.policy.derived_quota_bytes:
            raise AttachmentQuotaExceeded("derived attachment quota exceeded")

    def materialize_open_path(self, session_id: str, ref: str) -> tuple[Path, AttachmentReference]:
        """Return a derived path with a safe extension for system open/reveal.

        The durable original remains ``content.bin``. The derived copy exists
        only to give the operating system the submitted display-name suffix
        when Main asks it to open or reveal an attachment.
        """

        source, reference = self.resolve(session_id, ref)
        derived_root = source / "derived" / "open"
        target = derived_root / reference.display_name
        try:
            # Rebuild on every request so a user-edited derived copy can never
            # become the source for a later system open. If Windows still has
            # the previous path open, use a fresh same-suffix path instead of
            # reusing potentially modified bytes.
            try:
                self._ensure_derived_capacity(target, reference.size_bytes)
                _atomic_copy(source / "content.bin", target)
            except PermissionError:
                original_name = Path(reference.display_name)
                fallback_name = (
                    f"{original_name.stem}.{uuid.uuid4().hex}"
                    f"{original_name.suffix}"
                )
                target = derived_root / fallback_name
                self._ensure_derived_capacity(target, reference.size_bytes)
                _atomic_copy(source / "content.bin", target)
        except OSError as exc:
            raise AttachmentPersistenceError(
                "could not materialize attachment for system open"
            ) from exc
        return target, reference

    def read(self, session_id: str, ref: str) -> bytes:
        _path, _reference = self.resolve(session_id, ref)
        try:
            return (_path / "content.bin").read_bytes()
        except OSError as exc:
            raise AttachmentIntegrityError("attachment content is unreadable") from exc

    def reference(
        self,
        session_id: str,
        ref: str,
        *,
        verify_content: bool = True,
    ) -> AttachmentReference:
        """Return trusted Session metadata for one opaque attachment ref.

        ``verify_content=False`` still requires readable metadata, a present
        content file, and an exact size match, but avoids hashing the complete
        attachment when a caller only needs its bounded descriptive metadata.
        """

        return self._resolve(
            session_id,
            ref,
            verify_content=verify_content,
        )[1]

    def mark_submitted(self, session_id: str, ref: str) -> AttachmentReference:
        path, reference = self._resolve(session_id, ref)
        if reference.submitted:
            return reference
        updated = AttachmentReference(
            reference.ref,
            reference.session_id,
            reference.display_name,
            reference.mime_type,
            reference.size_bytes,
            reference.sha256,
            reference.width,
            reference.height,
            reference.created_at,
            True,
        )
        try:
            _atomic_json(path / "metadata.json", updated.to_dict())
        except AttachmentError:
            raise
        except Exception as exc:
            raise AttachmentPersistenceError(
                "could not persist submitted attachment metadata"
            ) from exc
        return updated

    def remove_draft(self, session_id: str, ref: str) -> None:
        path, reference = self._resolve(session_id, ref)
        if reference.submitted:
            raise AttachmentReferenceError("submitted attachment originals cannot be deleted")
        is_durable = getattr(self._store, "attachment_is_durable", None)
        if callable(is_durable):
            try:
                durable = is_durable(session_id, ref)
            except Exception as exc:
                raise AttachmentReferenceError(
                    "could not determine whether the attachment is durable"
                ) from exc
            if durable:
                raise AttachmentReferenceError(
                    "attachment is referenced by durable Session history"
                )
        shutil.rmtree(path)

    def cleanup(self, session_id: str) -> dict[str, int]:
        """Remove abandoned temporary/derived artifacts, retaining originals."""

        root = self._attachments_path(session_id)
        removed_temp = 0
        removed_derived = 0
        for item in tuple(root.iterdir()):
            if item.name.startswith(".") and item.name.endswith(".tmp"):
                shutil.rmtree(item, ignore_errors=True)
                removed_temp += 1
            elif item.name == "derived" and item.is_dir():
                # Remove the legacy Session-level cache location as well.
                shutil.rmtree(item, ignore_errors=True)
                removed_derived += 1
            elif item.is_dir():
                derived = item / "derived"
                if derived.is_dir():
                    shutil.rmtree(derived, ignore_errors=True)
                    removed_derived += 1
        return {"temporary": removed_temp, "derived": removed_derived}

    def list_references(self, session_id: str) -> tuple[AttachmentReference, ...]:
        root = self._attachments_path(session_id)
        values: list[AttachmentReference] = []
        for item in root.iterdir():
            if not item.is_dir() or item.name.startswith(".") or item.name == "derived":
                continue
            try:
                values.append(self.reference(session_id, item.name))
            except AttachmentError:
                continue
        values.sort(key=lambda item: (item.created_at, item.ref))
        return tuple(values)

    def preview(
        self,
        session_id: str,
        ref: str,
        *,
        mode: str = "thumbnail",
        max_edge: int | None = None,
    ) -> dict[str, object]:
        """Return bounded metadata and an optional image data URL preview."""

        if mode not in {"thumbnail", "full"}:
            raise ValueError("image preview mode must be thumbnail or full")

        # Preview only needs trusted metadata and a bounded prefix.  A full
        # content hash/read here would defeat the preview limit for large
        # images and text files; read() and system-open resolution keep the
        # complete integrity check.
        attachment_path, reference = self._resolve(
            session_id,
            ref,
            verify_content=False,
        )
        result: dict[str, object] = {
            "ref": reference.ref,
            "asset_ref": reference.asset_ref,
            "display_name": reference.display_name,
            "mime_type": reference.mime_type,
            "size_bytes": reference.size_bytes,
            "width": reference.width,
            "height": reference.height,
            "preview_supported": reference.mime_type.startswith("image/")
            or _is_text_attachment(reference),
            "preview_kind": None,
            "truncated": False,
        }
        if reference.mime_type.startswith("image/"):
            image_limit = self.policy.single_attachment_hard_cap_bytes
            data, source_truncated = read_bounded_preview(
                attachment_path / "content.bin",
                image_limit,
            )
            if source_truncated:
                raise AttachmentTooLarge("attachment image source exceeds the preview limit")
            preview_limit = (
                self.policy.preview_limit_bytes
                if mode == "thumbnail"
                else min(self.policy.single_attachment_hard_cap_bytes, 4 * 1024 * 1024)
            )
            try:
                rendered = render_image_preview(
                    data,
                    reference.mime_type,
                    mode=mode,
                    max_edge=max_edge,
                    max_width=self.policy.max_image_width,
                    max_height=self.policy.max_image_height,
                    max_pixels=self.policy.max_image_pixels,
                    max_bytes=preview_limit,
                )
            except ImagePreviewLimitError as exc:
                raise AttachmentImageTooLarge(
                    "image dimensions exceed the preview policy"
                ) from exc
            if rendered is not None:
                preview_mime = str(rendered["mime_type"])
                result.update(
                    {
                        "data_url": f"data:{preview_mime};base64,{base64.b64encode(rendered['data']).decode('ascii')}",
                        "preview_kind": mode,
                        "preview_mime_type": preview_mime,
                        "preview_width": rendered["width"],
                        "preview_height": rendered["height"],
                        "scaled": rendered["scaled"],
                    }
                )
            elif len(data) <= preview_limit:
                # Keep the old behavior for a small unsupported image payload;
                # a malformed large original is never returned to the UI.
                encoded = base64.b64encode(data).decode("ascii")
                result.update(
                    {
                        "data_url": f"data:{reference.mime_type};base64,{encoded}",
                        "preview_kind": mode,
                        "preview_mime_type": reference.mime_type,
                        "scaled": False,
                    }
                )
            else:
                result["preview_supported"] = False
            return result

        if _is_text_attachment(reference):
            preview_limit = (
                self.policy.preview_limit_bytes
                if mode == "thumbnail"
                else min(self.policy.single_attachment_hard_cap_bytes, 4 * 1024 * 1024)
            )
            try:
                data, source_truncated = read_bounded_preview(
                    attachment_path / "content.bin",
                    preview_limit,
                )
                text, encoding = decode_preview_text(data)
            except UnicodeError as exc:
                raise AttachmentError("attachment text encoding is unsupported") from exc
            text, truncated = bounded_preview_text(
                text,
                preview_limit,
                source_truncated=source_truncated,
            )
            result.update(
                {
                    "preview_kind": "text",
                    "text": text,
                    "encoding": encoding,
                    "truncated": truncated,
                }
            )
        return result


__all__ = [
    "ATTACHMENT_SCHEMA_VERSION",
    "AttachmentError",
    "AttachmentReferenceError",
    "AttachmentTooLarge",
    "AttachmentImageTooLarge",
    "AttachmentQuotaExceeded",
    "AttachmentPersistenceError",
    "AttachmentIntegrityError",
    "TEXT_PREVIEW_EXTENSIONS",
    "bounded_preview_text",
    "decode_preview_text",
    "read_bounded_preview",
    "ImagePreviewLimitError",
    "AttachmentPolicy",
    "AttachmentReference",
    "AttachmentFileStore",
    "render_image_preview",
]
