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
