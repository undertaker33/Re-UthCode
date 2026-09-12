"""Bounded, location-preserving readers for common office documents.

The readers intentionally return UthCode content parts instead of provider SDK
objects.  Bytes are read at this Integration boundary; the Core only receives
bounded text and source locations.  Formula cells are reported with both the
stored formula and the last cached value when one is available.  No reader
recalculates a workbook.
"""

from __future__ import annotations

import base64
import io
import zipfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from uthcode.core.permission import Effect, PermissionAction, ResourceScope
from uthcode.core.provider import (
    CancellationToken,
    ContentPart,
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


_CANCELLED = "Error: document read cancelled"
_DEFAULT_MAX_BYTES = 16 * 1024 * 1024
_DEFAULT_MAX_CHARS = 64 * 1024
_DEFAULT_MAX_ROWS = 200
_DEFAULT_MAX_CELLS = 2000
class DocumentReadError(RuntimeError):
    """A controlled document reader failure with a stable public category."""

    def __init__(self, message: str, kind: ToolFailureKind = ToolFailureKind.INVALID_INPUT) -> None:
        self.kind = kind
        super().__init__(message)


def _text(arguments: Mapping[str, object], name: str, *, required: bool = True) -> str | None:
    value = arguments.get(name)
    if value is None and not required:
        return None
    if not isinstance(value, str) or (required and not value.strip()):
        raise TypeError(f"{name} must be a non-empty string")
    return value


def _positive(arguments: Mapping[str, object], name: str, default: int, maximum: int) -> int:
    value = arguments.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0 or value > maximum:
        raise ValueError(f"{name} must be between 1 and {maximum}")
    return value


def _bounded_text(value: str, limit: int) -> tuple[str, bool]:
    encoded = value.encode("utf-8")
    if len(encoded) <= limit:
        return value, False
    data = encoded[:limit]
    while True:
        try:
            return data.decode("utf-8"), True
        except UnicodeDecodeError:
            data = data[:-1]


def _failure(
    message: str,
    kind: ToolFailureKind,
    *,
    retryable: bool = False,
) -> ToolExecutionResult:
    return ToolExecutionResult(
        message,
        is_error=True,
        failure=ToolFailure(kind.value, retryable),
        side_effect=ToolSideEffect.NONE,
    )


class ReadDocumentTool:
    """Read a bounded region of PDF, DOCX, XLSX, or PPTX content."""

    _definition = ToolDefinition(
        "ReadDocument",
        "Read bounded text and structure from a PDF, DOCX, XLSX, or PPTX with source locations.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "asset_ref": {"type": "string"},
                "page": {"type": "integer", "minimum": 1},
                "sheet": {"type": "string"},
                "range": {"type": "string"},
                "slide": {"type": "integer", "minimum": 1},
                "paragraph": {"type": "integer", "minimum": 1},
                "max_chars": {"type": "integer", "minimum": 1, "maximum": 262144},
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
        session_provider: Callable[[], object | None] | None = None,
        on_path_access: Callable[[Path], object] | None = None,
        max_bytes: int = _DEFAULT_MAX_BYTES,
    ) -> None:
        self._resolver = resolver
        self._asset_reader = asset_reader
        self._asset_reference = asset_reference
        self._session_provider = session_provider
        self._on_path_access = on_path_access
        if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        self._max_bytes = max_bytes

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
                tool="ReadDocument",
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
            source_name, data, source_ref = self._read_source(arguments)
            max_chars = _positive(arguments, "max_chars", _DEFAULT_MAX_CHARS, 262144)
            if cancellation.cancelled:
                return _failure(_CANCELLED, ToolFailureKind.CANCELLED)
            suffix = Path(source_name).suffix.casefold()
            if suffix == ".pdf":
                parts = await self._read_pdf(data, source_ref, arguments, cancellation, max_chars)
            elif suffix == ".docx":
                parts = self._read_docx(data, source_ref, arguments, cancellation, max_chars)
            elif suffix == ".xlsx":
                parts = self._read_xlsx(data, source_ref, arguments, cancellation, max_chars)
            elif suffix == ".pptx":
                parts = self._read_pptx(data, source_ref, arguments, cancellation, max_chars)
            else:
                raise DocumentReadError(
                    f"Error: unsupported document format: {suffix or '<none>'}",
                    ToolFailureKind.UNSUPPORTED,
                )
            return ToolExecutionResult(tuple(parts))
        except DocumentReadError as exc:
            return _failure(str(exc), exc.kind, retryable=exc.kind is ToolFailureKind.RESOURCE_LIMIT)
        except (TypeError, ValueError) as exc:
            return _failure(f"Error: invalid ReadDocument arguments: {exc}", ToolFailureKind.INVALID_INPUT)
        except (OSError, zipfile.BadZipFile) as exc:
            return _failure(f"Error: document could not be read: {exc}", ToolFailureKind.NOT_FOUND)
        except Exception:
            # Parser exceptions can contain file paths or native payloads.
            return _failure("Error: document could not be parsed", ToolFailureKind.UNAVAILABLE)

    def _read_source(self, arguments: Mapping[str, object]) -> tuple[str, bytes, str]:
        path = arguments.get("path")
        asset_ref = arguments.get("asset_ref")
        if isinstance(path, str) and path.strip():
            try:
                resolved = self._resolver.resolve(path)
            except (WorkspacePathError, TypeError, ValueError) as exc:
                raise DocumentReadError(str(exc), ToolFailureKind.NOT_FOUND) from exc
            if not resolved.is_file():
                raise DocumentReadError(
                    f"Error: path is not a file: {self._resolver.display(resolved)}",
                    ToolFailureKind.NOT_FOUND,
                )
            if self._on_path_access is not None:
                self._on_path_access(resolved)
            try:
                size = resolved.stat().st_size
                if size > self._max_bytes:
                    raise DocumentReadError(
                        f"Error: document exceeds the {_format_bytes(self._max_bytes)} byte limit",
                        ToolFailureKind.RESOURCE_LIMIT,
                    )
                return resolved.name, resolved.read_bytes(), self._resolver.display(resolved)
            except DocumentReadError:
                raise
            except OSError as exc:
                raise DocumentReadError(f"Error: document could not be read: {exc}", ToolFailureKind.NOT_FOUND) from exc
        if isinstance(asset_ref, str) and asset_ref.strip():
            if not asset_ref.startswith("attachment:") or self._asset_reader is None:
                raise DocumentReadError("Error: document attachment is unavailable", ToolFailureKind.UNAVAILABLE)
            pieces = asset_ref.split(":", 2)
            if len(pieces) != 3 or not pieces[1] or not pieces[2]:
                raise DocumentReadError("Error: document attachment reference is invalid", ToolFailureKind.INVALID_INPUT)
            active = self._session_provider() if self._session_provider is not None else None
            if getattr(active, "session_id", None) != pieces[1]:
                raise DocumentReadError("Error: document attachment belongs to another Session", ToolFailureKind.PERMISSION_DENIED)
            try:
                data = self._asset_reader(pieces[1], pieces[2])
                if len(data) > self._max_bytes:
                    raise DocumentReadError(
                        f"Error: document exceeds the {_format_bytes(self._max_bytes)} byte limit",
                        ToolFailureKind.RESOURCE_LIMIT,
                    )
                metadata = self._asset_reference(pieces[1], pieces[2]) if self._asset_reference else {}
                name = metadata.get("display_name") if isinstance(metadata, Mapping) else None
                return str(name or pieces[2]), data, asset_ref
            except DocumentReadError:
                raise
            except Exception as exc:
                raise DocumentReadError("Error: document attachment is unavailable", ToolFailureKind.NOT_FOUND) from exc
        raise DocumentReadError("Error: exactly one of path or asset_ref is required", ToolFailureKind.INVALID_INPUT)

    async def _read_pdf(
        self,
        data: bytes,
        source_ref: str,
        arguments: Mapping[str, object],
        cancellation: CancellationToken,
        max_chars: int,
    ) -> Sequence[ContentPart]:
        request = {
            "operation": "text",
            "data_b64": base64.b64encode(data).decode("ascii"),
            "page": arguments.get("page"),
            "max_chars": max_chars,
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
            raise DocumentReadError(str(exc), kind) from exc
        text = response.get("text")
        page = response.get("page")
        if not isinstance(text, str) or (page is not None and (isinstance(page, bool) or not isinstance(page, int))):
            raise DocumentReadError("Error: PDF reader worker returned invalid output", ToolFailureKind.UNAVAILABLE)
        return (TextPart(text), SourcePart(source_ref, page=page))

    def _read_docx(
        self,
        data: bytes,
        source_ref: str,
        arguments: Mapping[str, object],
        cancellation: CancellationToken,
        max_chars: int,
    ) -> Sequence[ContentPart]:
        try:
            from docx import Document
        except ImportError as exc:
            raise DocumentReadError("Error: DOCX reader dependency is unavailable", ToolFailureKind.UNAVAILABLE) from exc
        try:
            document = Document(io.BytesIO(data))
        except Exception as exc:
            raise DocumentReadError("Error: DOCX is damaged or encrypted", ToolFailureKind.INVALID_INPUT) from exc
        paragraph_number = arguments.get("paragraph")
        if paragraph_number is not None and (isinstance(paragraph_number, bool) or not isinstance(paragraph_number, int) or paragraph_number < 1):
            raise DocumentReadError("Error: paragraph must be a positive integer", ToolFailureKind.INVALID_INPUT)
        rows: list[str] = []
        paragraphs = tuple(document.paragraphs)
        selected = (paragraph_number,) if paragraph_number is not None else range(1, len(paragraphs) + 1)
        for index in selected:
            if cancellation.cancelled:
                raise DocumentReadError(_CANCELLED, ToolFailureKind.CANCELLED)
            if index > len(paragraphs):
                raise DocumentReadError(f"Error: DOCX paragraph {index} does not exist", ToolFailureKind.NOT_FOUND)
            rows.append(f"[paragraph {index}] {paragraphs[index - 1].text}")
        for table_number, table in enumerate(document.tables, start=1):
            for row_number, row in enumerate(table.rows, start=1):
                if cancellation.cancelled:
                    raise DocumentReadError(_CANCELLED, ToolFailureKind.CANCELLED)
                cells = " | ".join(cell.text for cell in row.cells)
                rows.append(f"[table {table_number}, row {row_number}] {cells}")
        value, truncated = _bounded_text("\n".join(rows), max_chars)
        if truncated:
            value += "\n[truncated]"
        return (TextPart(value), SourcePart(source_ref, paragraph=str(paragraph_number) if paragraph_number else None))

    def _read_xlsx(
        self,
        data: bytes,
        source_ref: str,
        arguments: Mapping[str, object],
        cancellation: CancellationToken,
        max_chars: int,
    ) -> Sequence[ContentPart]:
        try:
            import openpyxl
        except ImportError as exc:
            raise DocumentReadError("Error: XLSX reader dependency is unavailable", ToolFailureKind.UNAVAILABLE) from exc
        sheet_name = arguments.get("sheet")
        if sheet_name is not None and (not isinstance(sheet_name, str) or not sheet_name.strip()):
            raise DocumentReadError("Error: sheet must be a non-empty string", ToolFailureKind.INVALID_INPUT)
        range_ref = arguments.get("range")
        if range_ref is not None and (not isinstance(range_ref, str) or not range_ref.strip()):
            raise DocumentReadError("Error: range must be a non-empty string", ToolFailureKind.INVALID_INPUT)
        try:
            formulas = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=False)
            cached = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        except Exception as exc:
            raise DocumentReadError("Error: XLSX is damaged or encrypted", ToolFailureKind.INVALID_INPUT) from exc
        try:
            if sheet_name is not None and sheet_name not in formulas.sheetnames:
                raise DocumentReadError(f"Error: worksheet not found: {sheet_name}", ToolFailureKind.NOT_FOUND)
            sheets = [str(sheet_name)] if sheet_name else list(formulas.sheetnames)
            rows: list[str] = []
            cell_count = 0
            for name in sheets:
                formula_sheet = formulas[name]
                cached_sheet = cached[name]
                iterator = formula_sheet[range_ref] if range_ref else formula_sheet.iter_rows(max_row=_DEFAULT_MAX_ROWS)
                cached_iterator = cached_sheet[range_ref] if range_ref else cached_sheet.iter_rows(max_row=_DEFAULT_MAX_ROWS)
                for formula_row, cached_row in zip(iterator, cached_iterator):
                    for formula_cell, cached_cell in zip(formula_row, cached_row):
                        if cancellation.cancelled:
                            raise DocumentReadError(_CANCELLED, ToolFailureKind.CANCELLED)
                        if cell_count >= _DEFAULT_MAX_CELLS:
                            raise DocumentReadError("Error: worksheet cell limit exceeded", ToolFailureKind.RESOURCE_LIMIT)
                        formula_value = formula_cell.value
                        cached_value = cached_cell.value
                        if formula_value is None and cached_value is None:
                            continue
                        text = _cell_value_text(formula_value, cached_value)
                        rows.append(f"[sheet {name}, cell {formula_cell.coordinate}] {text}")
                        cell_count += 1
            value, truncated = _bounded_text("\n".join(rows), max_chars)
            if truncated:
                value += "\n[truncated]"
            return (TextPart(value), SourcePart(source_ref, sheet=str(sheet_name) if sheet_name else None, range=str(range_ref) if range_ref else None))
        finally:
            formulas.close()
            cached.close()

    def _read_pptx(
        self,
        data: bytes,
        source_ref: str,
        arguments: Mapping[str, object],
        cancellation: CancellationToken,
        max_chars: int,
    ) -> Sequence[ContentPart]:
        try:
            from pptx import Presentation
        except ImportError as exc:
            raise DocumentReadError("Error: PPTX reader dependency is unavailable", ToolFailureKind.UNAVAILABLE) from exc
        try:
            presentation = Presentation(io.BytesIO(data))
        except Exception as exc:
            raise DocumentReadError("Error: PPTX is damaged or encrypted", ToolFailureKind.INVALID_INPUT) from exc
        slide_number = arguments.get("slide")
        if slide_number is not None and (isinstance(slide_number, bool) or not isinstance(slide_number, int) or slide_number < 1):
            raise DocumentReadError("Error: slide must be a positive integer", ToolFailureKind.INVALID_INPUT)
        slides = [slide_number] if slide_number is not None else list(range(1, min(len(presentation.slides), 200) + 1))
        rows: list[str] = []
        for number in slides:
            if cancellation.cancelled:
                raise DocumentReadError(_CANCELLED, ToolFailureKind.CANCELLED)
            if number > len(presentation.slides):
                raise DocumentReadError(f"Error: PPTX slide {number} does not exist", ToolFailureKind.NOT_FOUND)
            slide = presentation.slides[number - 1]
            for shape_number, shape in enumerate(slide.shapes, start=1):
                if hasattr(shape, "text") and shape.text:
                    rows.append(f"[slide {number}, shape {shape_number}] {shape.text}")
                if getattr(shape, "has_table", False):
                    for row_number, row in enumerate(shape.table.rows, start=1):
                        rows.append(
                            f"[slide {number}, table {shape_number}, row {row_number}] "
                            + " | ".join(cell.text for cell in row.cells)
                        )
        value, truncated = _bounded_text("\n".join(rows), max_chars)
        if truncated:
            value += "\n[truncated]"
        return (TextPart(value), SourcePart(source_ref, slide=slides[0] if len(slides) == 1 else None))


def _cell_value_text(formula_value: object, cached_value: object) -> str:
    if isinstance(formula_value, str) and formula_value.startswith("="):
        return f"formula={formula_value!r}; cached={cached_value!r}"
    return repr(formula_value)


def _format_bytes(value: int) -> str:
    if value < 1024 * 1024:
        return f"{value // 1024} KiB"
    return f"{value // (1024 * 1024)} MiB"


__all__ = ["DocumentReadError", "ReadDocumentTool"]
