from __future__ import annotations

from pathlib import Path

import pytest

from uthcode.core.provider import CancellationToken, ImagePart, SourcePart
from uthcode.integrations.tools.image_tools import ViewImageTool
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


@pytest.mark.asyncio
async def test_view_image_and_pdf_page_use_session_asset_writer(tmp_path: Path) -> None:
    from PIL import Image

    image_path = tmp_path / "sample.png"
    Image.new("RGB", (32, 18), (12, 34, 56)).save(image_path)
    (tmp_path / "sample.pdf").write_bytes(_pdf_bytes())
    written: list[tuple[str, bytes, str, str]] = []

    def write_asset(name: str, data: bytes, mime: str, source: str) -> dict[str, object]:
        written.append((name, data, mime, source))
        return {"asset_ref": f"attachment:s:{len(written)}"}

    tool = ViewImageTool(WorkspacePathResolver(tmp_path), asset_writer=write_asset)
    image = await tool.execute({"path": "sample.png"}, cancellation=CancellationToken())
    page = await tool.execute({"path": "sample.pdf", "page": 1}, cancellation=CancellationToken())

    image_part = next(part for part in image.content.parts if isinstance(part, ImagePart))
    source_part = next(part for part in page.content.parts if isinstance(part, SourcePart))
    page_part = next(part for part in page.content.parts if isinstance(part, ImagePart))
    assert image_part.width == 32 and image_part.height == 18
    assert page_part.mime_type == "image/png"
    assert source_part.page == 1
    assert written[0][2] == "image/png"
    assert written[1][2] == "image/png"


@pytest.mark.asyncio
async def test_view_image_controls_damage_limit_and_cancel(tmp_path: Path) -> None:
    (tmp_path / "broken.png").write_bytes(b"not an image")
    tool = ViewImageTool(WorkspacePathResolver(tmp_path), max_bytes=4)
    token = CancellationToken()
    token.cancel()

    cancelled = await tool.execute({"path": "broken.png"}, cancellation=token)
    oversized = await tool.execute({"path": "broken.png"}, cancellation=CancellationToken())
    assert cancelled.failure is not None and cancelled.failure.kind == "cancelled"
    assert oversized.failure is not None
