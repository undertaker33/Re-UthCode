from __future__ import annotations

from pathlib import Path

import pytest

from uthcode.application.attachments import ArtifactError, ArtifactService


def test_artifact_service_describes_workspace_files_and_previews_images(tmp_path: Path) -> None:
    image = tmp_path / "preview.png"
    image.write_bytes(b"png-bytes")
    service = ArtifactService(tmp_path)

    descriptor = service.describe(str(image))
    assert descriptor.kind == "image"
    assert descriptor.default_action == "open"
    assert descriptor.preview_supported is True

    preview = service.preview(str(image))
    assert preview["name"] == "preview.png"
    assert str(preview["data_url"]).startswith("data:image/png;base64,")


def test_artifact_service_rejects_missing_uri_and_unauthorized_external_files(tmp_path: Path) -> None:
    service = ArtifactService(tmp_path)
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("outside", encoding="utf-8")

    with pytest.raises(ArtifactError) as outside_error:
        service.describe(str(outside))
    assert outside_error.value.code == "artifact_not_authorized"

    with pytest.raises(ArtifactError) as uri_error:
        service.describe("https://example.test/file.txt")
    assert uri_error.value.code == "artifact_invalid"

    with pytest.raises(ArtifactError) as missing_error:
        service.describe(str(tmp_path / "missing.txt"))
    assert missing_error.value.code == "artifact_not_found"


def test_artifact_service_defaults_executable_to_reveal(tmp_path: Path) -> None:
    executable = tmp_path / "tool.exe"
    executable.write_bytes(b"MZ")
    descriptor = ArtifactService(tmp_path).describe(str(executable))
    assert descriptor.kind == "executable"
    assert descriptor.default_action == "reveal"
    assert descriptor.preview_supported is False


def test_artifact_service_resolves_relative_paths_from_the_authorized_workdir(tmp_path: Path) -> None:
    artifact = tmp_path / "relative.txt"
    artifact.write_text("ok", encoding="utf-8")
    descriptor = ArtifactService(tmp_path).describe("relative.txt")
    assert descriptor.path == artifact.resolve()


def test_artifact_service_returns_bounded_text_preview_with_marker(tmp_path: Path) -> None:
    artifact = tmp_path / "notes.md"
    artifact.write_text("界" * 200, encoding="utf-8")
    service = ArtifactService(tmp_path, preview_limit_bytes=32)

    preview = service.preview(artifact)

    assert preview["kind"] == "text"
    assert preview["preview_kind"] == "text"
    assert preview["truncated"] is True
    assert str(preview["text"]).endswith("\n[truncated]")
    assert "�" not in str(preview["text"])


def test_artifact_service_rejects_unknown_text_encoding_without_replacement(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "unknown.txt"
    artifact.write_bytes(b"\xff\xff\xff\xff")

    with pytest.raises(ArtifactError) as error:
        ArtifactService(tmp_path).preview(artifact)

    assert error.value.code == "artifact_preview_unavailable"


def test_artifact_service_scales_large_images_for_thumbnail_and_keeps_full_bounded(
    tmp_path: Path,
) -> None:
    import random

    from PIL import Image

    raw = random.Random(12345).randbytes(700 * 500 * 3)
    image = tmp_path / "large.png"
    Image.frombytes("RGB", (700, 500), raw).save(image, optimize=False)
    service = ArtifactService(tmp_path)
    assert image.stat().st_size > service.preview_limit_bytes

    thumbnail = service.preview(image)
    full = service.preview(image, mode="full")

    assert thumbnail["preview_kind"] == "thumbnail"
    assert thumbnail["scaled"] is True
    assert int(thumbnail["preview_width"]) <= 160
    assert int(thumbnail["preview_height"]) <= 160
    assert len(str(thumbnail["data_url"])) < 400_000
    assert full["preview_kind"] == "full"
    assert int(full["preview_width"]) <= 2048
    assert len(str(full["data_url"])) < 6_000_000


def test_artifact_service_leaves_pdf_and_office_preview_to_system_open(
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "report.pdf"
    pdf.write_bytes(b"%PDF-1.7\n")
    office = tmp_path / "report.docx"
    office.write_bytes(b"not parsed here")
    service = ArtifactService(tmp_path)

    assert service.describe(pdf).preview_supported is False
    assert service.describe(office).preview_supported is False
    with pytest.raises(ArtifactError) as error:
        service.preview(pdf)
    assert error.value.code == "artifact_preview_unavailable"
