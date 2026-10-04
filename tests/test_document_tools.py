from __future__ import annotations

import sys
from pathlib import Path

import pytest

from uthcode.core.provider import CancellationToken, ContentSequence, SourcePart
from uthcode.integrations.tools.document_tools import ReadDocumentTool
from uthcode.integrations.tools.document_workers import PDF_WORKER_FLAG, pdf_worker_command
from uthcode.integrations.tools.workspace import WorkspacePathResolver


def _pdf_bytes() -> bytes:
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length 42 >>\nstream\nBT /F1 18 Tf 72 100 Td (PDF hello) Tj ET\nendstream",
    ]
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, value in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{number} 0 obj\n".encode())
        output.extend(value)
        output.extend(b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(output)


def _text(result: object) -> str:
    return str(getattr(result, "content"))


def test_pdf_worker_command_keeps_headless_and_frozen_entrypoints(monkeypatch: pytest.MonkeyPatch) -> None:
    development = pdf_worker_command()
    assert development[1:] == ("-m", "uthcode.integrations.pdf_worker", PDF_WORKER_FLAG)

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert pdf_worker_command() == (sys.executable, PDF_WORKER_FLAG)


@pytest.mark.asyncio
async def test_read_document_locates_pdf_docx_xlsx_and_pptx(tmp_path: Path) -> None:
    from docx import Document
    from openpyxl import Workbook
    from pptx import Presentation

    (tmp_path / "sample.pdf").write_bytes(_pdf_bytes())
    document = Document()
    document.add_paragraph("DOCX paragraph")
    document.save(tmp_path / "sample.docx")
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Inputs"
    sheet["A1"] = "cell value"
    sheet["B1"] = "=1+1"
    workbook.save(tmp_path / "sample.xlsx")
    presentation = Presentation()
    presentation.slides.add_slide(presentation.slide_layouts[5]).shapes.title.text = "PPTX slide"
    presentation.save(tmp_path / "sample.pptx")

    tool = ReadDocumentTool(WorkspacePathResolver(tmp_path))
    token = CancellationToken()
    pdf = await tool.execute({"path": "sample.pdf", "page": 1}, cancellation=token)
    docx = await tool.execute({"path": "sample.docx", "paragraph": 1}, cancellation=token)
    xlsx = await tool.execute({"path": "sample.xlsx", "sheet": "Inputs", "range": "A1:B1"}, cancellation=token)
    pptx = await tool.execute({"path": "sample.pptx", "slide": 1}, cancellation=token)

    assert "PDF hello" in _text(pdf)
    assert "DOCX paragraph" in _text(docx)
    assert "formula='=1+1'; cached=None" in _text(xlsx)
    assert "PPTX slide" in _text(pptx)
    assert isinstance(getattr(pdf.content, "parts")[1], SourcePart)
    assert getattr(pdf.content.parts[1], "page") == 1
    assert isinstance(pdf.content, ContentSequence)


@pytest.mark.asyncio
async def test_read_document_rejects_damage_limit_and_cancel(tmp_path: Path) -> None:
    (tmp_path / "broken.docx").write_bytes(b"not a docx")
    (tmp_path / "large.txt").write_bytes(b"x" * 32)
    tool = ReadDocumentTool(WorkspacePathResolver(tmp_path), max_bytes=16)

    broken = await tool.execute({"path": "broken.docx"}, cancellation=CancellationToken())
    oversized = await tool.execute({"path": "large.txt"}, cancellation=CancellationToken())
    cancelled_token = CancellationToken()
    cancelled_token.cancel()
    cancelled = await tool.execute({"path": "broken.docx"}, cancellation=cancelled_token)

    assert broken.is_error and broken.failure is not None
    assert "damaged or encrypted" in str(broken.content)
    assert oversized.is_error and oversized.failure is not None
    assert cancelled.failure is not None and cancelled.failure.kind == "cancelled"


@pytest.mark.asyncio
async def test_factory_reads_submitted_excel_attachment_after_source_file_is_changed_and_deleted(
    tmp_path: Path,
) -> None:
    from types import SimpleNamespace

    from openpyxl import Workbook

    from uthcode.application.attachments import AttachmentService
    from uthcode.integrations.session_files import SessionFileStore
    from uthcode.integrations.tools.factory import create_default_tools

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = tmp_path / "source.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Inputs"
    sheet["A1"] = "submitted snapshot"
    workbook.save(source)

    store = SessionFileStore(tmp_path / "sessions")
    session = store.create_session(project_key=str(workspace.resolve()))
    attachments = AttachmentService(store)
    imported = attachments.import_path(session.session_id, source)
    attachments.mark_submitted(session.session_id, (imported.ref,))

    source.write_bytes(b"source changed after import")
    source.unlink()

    tools = create_default_tools(
        workspace,
        attachment_service=attachments,
        session_provider=lambda: SimpleNamespace(session_id=session.session_id),
    )
    reader = next(tool for tool in tools if tool.definition.name == "ReadDocument")
    result = await reader.execute(
        {"asset_ref": imported.asset_ref, "sheet": "Inputs", "range": "A1"},
        cancellation=CancellationToken(),
    )
    foreign_session = store.create_session(project_key=str(workspace.resolve()))
    foreign = await reader.execute(
        {
            "asset_ref": f"attachment:{foreign_session.session_id}:{imported.ref}",
            "sheet": "Inputs",
            "range": "A1",
        },
        cancellation=CancellationToken(),
    )

    assert imported.asset_ref.startswith(f"attachment:{session.session_id}:")
    assert result.is_error is False
    assert "submitted snapshot" in _text(result)
    assert isinstance(result.content, ContentSequence)
    source_part = next(part for part in result.content.parts if isinstance(part, SourcePart))
    assert source_part.source == imported.asset_ref
    assert attachments.reference(session.session_id, imported.ref).submitted is True
    assert foreign.failure is not None
    assert foreign.failure.kind == "permission_denied"
