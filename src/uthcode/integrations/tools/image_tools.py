"""Image and PDF-page observation Tool.

The Tool validates and bounds local image input, renders PDF pages through
PDFium, then stores the resulting PNG through the Session attachment path.
Only the opaque asset reference and source location cross into Core/provider
contracts; image bytes never enter an Agent event or result metadata.
"""

from __future__ import annotations

import base64
import binascii
import io
from collections.abc import Callable, Mapping
from pathlib import Path

from uthcode.core.permission import Effect, PermissionAction, ResourceScope
from uthcode.core.provider import (
    CancellationToken,
    ImagePart,
    JsonPayload,
    SourcePart,
    TextPart,
    ToolDefinition,
)
from uthcode.core.tool import (
    ToolExecutionResult,
    ToolFailure,
    ToolFailureKind,
    ToolPlanningAccess,
    ToolPreparation,
    ToolSideEffect,
)

from .workspace import WorkspacePathError, WorkspacePathResolver
from .document_workers import PdfWorkerError, run_pdf_worker


_CANCELLED = "Error: image read cancelled"
_DEFAULT_MAX_BYTES = 16 * 1024 * 1024
_DEFAULT_MAX_PIXELS = 100_000_000


class ImageReadError(RuntimeError):
    def __init__(self, message: str, kind: ToolFailureKind) -> None:
        self.kind = kind
        super().__init__(message)


class ViewImageTool:
    """Return a validated local image or one rendered PDF page."""

    _definition = ToolDefinition(
        "ViewImage",
        "Read a local image or render one PDF page as an image for the visual model.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "asset_ref": {"type": "string"},
                "page": {"type": "integer", "minimum": 1},
                "max_width": {"type": "integer", "minimum": 1, "maximum": 8192},
                "max_height": {"type": "integer", "minimum": 1, "maximum": 8192},
            },
            "additionalProperties": False,
        },
    )

    def __init__(
        self,
        resolver: WorkspacePathResolver,
        *,
        asset_reader: Callable[[str, str], bytes] | None = None,
        asset_reference: Callable[[str, str], Mapping[str, object]] | None = None,
        asset_writer: Callable[[str, bytes, str, str], Mapping[str, object]] | None = None,
        session_provider: Callable[[], object | None] | None = None,
        on_path_access: Callable[[Path], object] | None = None,
        max_bytes: int = _DEFAULT_MAX_BYTES,
        max_pixels: int = _DEFAULT_MAX_PIXELS,
    ) -> None:
        self._resolver = resolver
        self._asset_reader = asset_reader
        self._asset_reference = asset_reference
        self._asset_writer = asset_writer
        self._session_provider = session_provider
        self._on_path_access = on_path_access
        if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        if isinstance(max_pixels, bool) or not isinstance(max_pixels, int) or max_pixels <= 0:
            raise ValueError("max_pixels must be positive")
        self._max_bytes = max_bytes
        self._max_pixels = max_pixels

    @property
    def definition(self) -> ToolDefinition:
        return self._definition

    @property
    def planning_access(self) -> ToolPlanningAccess:
        return ToolPlanningAccess.READ_ONLY

    def preflight(self, arguments: JsonPayload) -> ToolPreparation:
        path = arguments.get("path")
        asset_ref = arguments.get("asset_ref")
        if (path is None) == (asset_ref is None):
            raise ValueError("exactly one of path or asset_ref is required")
        if isinstance(path, str):
            resolved, scope = self._resolver.resolve_with_scope(path)
            resource = self._resolver.display(resolved)
            bound = dict(arguments)
            bound["path"] = str(resolved)
        elif isinstance(asset_ref, str) and asset_ref.strip():
            scope = ResourceScope.INSIDE
            resource = asset_ref
            bound = dict(arguments)
        else:
            raise TypeError("path or asset_ref must be a non-empty string")
        return ToolPreparation(
            action=PermissionAction(
                tool="ViewImage",
                action="read",
                effect=Effect.READ,
                resource=resource,
                scope=scope,
            ),
            execution_arguments=JsonPayload(bound),
        )

    async def execute(
        self,
        arguments: JsonPayload,
        *,
        cancellation: CancellationToken,
    ) -> ToolExecutionResult:
        if cancellation.cancelled:
            return _failure(_CANCELLED, ToolFailureKind.CANCELLED)
        try:
            name, data, source_ref = self._read_source(arguments)
            if cancellation.cancelled:
                return _failure(_CANCELLED, ToolFailureKind.CANCELLED)
            page = arguments.get("page")
            if page is not None and (isinstance(page, bool) or not isinstance(page, int) or page < 1):
                raise ImageReadError("Error: page must be a positive integer", ToolFailureKind.INVALID_INPUT)
            suffix = Path(name).suffix.casefold()
            if suffix == ".pdf" or self._mime_for(name).casefold() == "application/pdf":
                if page is None:
                    raise ImageReadError("Error: page is required when viewing a PDF", ToolFailureKind.INVALID_INPUT)
                data, width, height = await self._render_pdf_page(data, page, cancellation, arguments)
                display_name = f"{Path(name).stem}-page-{page}.png"
                mime = "image/png"
                source = SourcePart(source_ref, page=page)
            else:
                width, height = self._validate_image(data, name)
                display_name = Path(name).name or "image"
                mime = self._mime_for(name)
                source = SourcePart(source_ref)
            existing_asset = source_ref if source_ref.startswith("attachment:") and suffix != ".pdf" else None
            if existing_asset is not None:
                asset_ref = existing_asset
            elif self._asset_writer is None:
                raise ImageReadError(
                    "Error: visual asset storage is unavailable; open a Session before viewing an image",
                    ToolFailureKind.UNAVAILABLE,
                )
            if cancellation.cancelled:
                raise ImageReadError(_CANCELLED, ToolFailureKind.CANCELLED)
            if existing_asset is None:
                try:
                    written = self._asset_writer(display_name, data, mime, source_ref)
                except Exception as exc:
                    raise ImageReadError("Error: rendered image could not be stored", ToolFailureKind.UNAVAILABLE) from exc
                asset_ref = written.get("asset_ref") if isinstance(written, Mapping) else None
                if not isinstance(asset_ref, str) or not asset_ref:
                    raise ImageReadError("Error: rendered image reference is unavailable", ToolFailureKind.UNAVAILABLE)
            return ToolExecutionResult(
                (
                    TextPart(f"Image ready: {display_name} ({width}x{height})"),
                    ImagePart(asset_ref, mime, width, height),
                    source,
                ),
            )
        except ImageReadError as exc:
            return _failure(str(exc), exc.kind, retryable=exc.kind is ToolFailureKind.RESOURCE_LIMIT)
        except (TypeError, ValueError) as exc:
            return _failure(f"Error: invalid ViewImage arguments: {exc}", ToolFailureKind.INVALID_INPUT)
        except OSError as exc:
            return _failure(f"Error: image could not be read: {exc}", ToolFailureKind.NOT_FOUND)
        except Exception:
            return _failure("Error: image could not be decoded", ToolFailureKind.UNAVAILABLE)

    def _read_source(self, arguments: Mapping[str, object]) -> tuple[str, bytes, str]:
        path = arguments.get("path")
        asset_ref = arguments.get("asset_ref")
        if isinstance(path, str) and path.strip():
            try:
                resolved = self._resolver.resolve(path)
            except (WorkspacePathError, TypeError, ValueError) as exc:
                raise ImageReadError(str(exc), ToolFailureKind.NOT_FOUND) from exc
            if not resolved.is_file():
                raise ImageReadError(
                    f"Error: path is not a file: {self._resolver.display(resolved)}",
                    ToolFailureKind.NOT_FOUND,
                )
            if self._on_path_access is not None:
                self._on_path_access(resolved)
            size = resolved.stat().st_size
            if size > self._max_bytes:
                raise ImageReadError(
                    f"Error: image exceeds the {self._max_bytes} byte limit",
                    ToolFailureKind.RESOURCE_LIMIT,
                )
            return resolved.name, resolved.read_bytes(), self._resolver.display(resolved)
        if isinstance(asset_ref, str) and asset_ref.startswith("attachment:") and self._asset_reader is not None:
            pieces = asset_ref.split(":", 2)
            if len(pieces) != 3 or not pieces[1] or not pieces[2]:
                raise ImageReadError("Error: image attachment reference is invalid", ToolFailureKind.INVALID_INPUT)
            active = self._session_provider() if self._session_provider is not None else None
            if getattr(active, "session_id", None) != pieces[1]:
                raise ImageReadError("Error: image attachment belongs to another Session", ToolFailureKind.PERMISSION_DENIED)
            try:
                data = self._asset_reader(pieces[1], pieces[2])
                if len(data) > self._max_bytes:
                    raise ImageReadError("Error: image exceeds the byte limit", ToolFailureKind.RESOURCE_LIMIT)
                metadata = self._asset_reference(pieces[1], pieces[2]) if self._asset_reference else {}
                name = metadata.get("display_name") if isinstance(metadata, Mapping) else None
                return str(name or pieces[2]), data, asset_ref
            except ImageReadError:
                raise
            except Exception as exc:
                raise ImageReadError("Error: image attachment is unavailable", ToolFailureKind.NOT_FOUND) from exc
        raise ImageReadError("Error: exactly one of path or asset_ref is required", ToolFailureKind.INVALID_INPUT)

    def _validate_image(self, data: bytes, name: str) -> tuple[int, int]:
        try:
            from PIL import Image
            with Image.open(io.BytesIO(data)) as image:
                width, height = image.size
                image.verify()
        except Exception as exc:
            raise ImageReadError("Error: image is damaged or unsupported", ToolFailureKind.INVALID_INPUT) from exc
        if width <= 0 or height <= 0 or width * height > self._max_pixels:
            raise ImageReadError("Error: image exceeds the pixel limit", ToolFailureKind.RESOURCE_LIMIT)
        mime = self._mime_for(name)
        if not mime.startswith("image/"):
            raise ImageReadError("Error: file is not an image", ToolFailureKind.UNSUPPORTED)
        return width, height

    async def _render_pdf_page(
        self,
        data: bytes,
        page_number: int,
        cancellation: CancellationToken,
        arguments: Mapping[str, object],
    ) -> tuple[bytes, int, int]:
        try:
            width_limit = int(arguments.get("max_width", 2048))
            height_limit = int(arguments.get("max_height", 2048))
        except (TypeError, ValueError) as exc:
            raise ImageReadError("Error: image dimensions are out of range", ToolFailureKind.INVALID_INPUT) from exc
        if not 1 <= width_limit <= 8192 or not 1 <= height_limit <= 8192:
            raise ImageReadError("Error: image dimensions are out of range", ToolFailureKind.INVALID_INPUT)
        request = {
            "operation": "image",
            "data_b64": base64.b64encode(data).decode("ascii"),
            "page": page_number,
            "max_width": width_limit,
            "max_height": height_limit,
            "max_pixels": self._max_pixels,
        }
        try:
            response = await run_pdf_worker(
                request,
                cancellation=cancellation,
                max_output_bytes=self._max_bytes,
            )
        except PdfWorkerError as exc:
            kind = next(
                (candidate for candidate in ToolFailureKind if candidate.value == exc.kind),
                ToolFailureKind.UNAVAILABLE,
            )
            raise ImageReadError(str(exc), kind) from exc
        encoded = response.get("png_b64")
        width = response.get("width")
        height = response.get("height")
        if not isinstance(encoded, str) or any(
            isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in (width, height)
        ):
            raise ImageReadError("Error: PDF renderer returned invalid output", ToolFailureKind.UNAVAILABLE)
        try:
            rendered = base64.b64decode(encoded.encode("ascii"), validate=True)
        except (UnicodeEncodeError, binascii.Error) as exc:
            raise ImageReadError("Error: PDF renderer returned invalid output", ToolFailureKind.UNAVAILABLE) from exc
        if len(rendered) > self._max_bytes:
            raise ImageReadError("Error: rendered image exceeds the byte limit", ToolFailureKind.RESOURCE_LIMIT)
        return rendered, width, height

    @staticmethod
    def _mime_for(name: str) -> str:
        suffix = Path(name).suffix.casefold()
        return {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".bmp": "image/bmp",
            ".pdf": "application/pdf",
        }.get(suffix, "application/octet-stream")


def _failure(message: str, kind: ToolFailureKind, *, retryable: bool = False) -> ToolExecutionResult:
    return ToolExecutionResult(
        message,
        is_error=True,
        failure=ToolFailure(kind.value, retryable),
        side_effect=ToolSideEffect.NONE,
    )


__all__ = ["ImageReadError", "ViewImageTool"]
