from __future__ import annotations

import asyncio
import json
import os
import stat
import subprocess
from collections.abc import AsyncIterator, Iterable
from pathlib import Path

import pytest

from eval.swebench import (
    EvalExecutionError,
    SWEbenchInstance,
    build_model_patch,
    run_swebench_instance,
    sanitize_trace,
)
from uthcode.application import EffectiveConfig, ProviderKind
from uthcode.core.provider import (
    CancellationToken,
    FinishReason,
    GenerationCompleted,
    Message,
    ModelLimits,
    ProviderEvent,
    ProviderIdentity,
    ProviderResponse,
    TextPart,
    ToolCallPart,
    Usage,
)


def _response(*parts: object, finish_reason: FinishReason = FinishReason.STOP) -> GenerationCompleted:
    return GenerationCompleted(
        ProviderResponse(
            Message("assistant", tuple(parts)),
            usage=Usage(input_tokens=3, output_tokens=2),
            finish_reason=finish_reason,
        )
    )


class _WriteProvider:
    def __init__(self, filename: str, secret: str) -> None:
        self.identity = ProviderIdentity("fake", "swebench-test", "test-model")
        self._scripts: tuple[tuple[ProviderEvent, ...], ...] = (
            (
                _response(
                    ToolCallPart(
                        "write-1",
                        "WriteFile",
                        {"path": filename, "content": f"new file {filename}\n"},
                    ),
                    finish_reason=FinishReason.TOOL_CALLS,
                ),
            ),
            (_response(TextPart(f"api_key={secret}")),),
        )
        self._index = 0

    def resolve_model_limits(self, _model: str) -> ModelLimits:
        return ModelLimits(max_input_tokens=1_000_000, source="test.swebench")

    async def stream(
        self,
        request: object,
        *,
        cancellation: CancellationToken,
    ) -> AsyncIterator[ProviderEvent]:
        del request
        cancellation.raise_if_cancelled()
        script = self._scripts[min(self._index, len(self._scripts) - 1)]
        self._index += 1
        for event in script:
            cancellation.raise_if_cancelled()
            yield event


def _config(*, api_key: str | None = None) -> EffectiveConfig:
    return EffectiveConfig.single_model(
        "fake/eval",
        provider_profile_id="swebench-fake",
        provider_kind=ProviderKind.FAKE,
        remote_id="test-model",
        api_key=api_key,
    )


def _git(
    repo: Path,
    *args: str,
    check: bool = True,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
        input=input_text,
    )


def _repo(tmp_path: Path, name: str = "instance") -> Path:
    repo = tmp_path / name
    repo.mkdir()
    (repo / "baseline.py").write_text("print('baseline')\n", encoding="utf-8")
    (repo / "delete.txt").write_text("delete me\n", encoding="utf-8")
    (repo / "rename.txt").write_text("rename me\n", encoding="utf-8")
    (repo / "binary.bin").write_bytes(b"\x00baseline\xff\n")
    subprocess.run(["git", "init", "--quiet", str(repo)], check=True, capture_output=True, text=True)
    _git(repo, "config", "user.email", "tests@example.invalid")
    _git(repo, "config", "user.name", "UthCode Tests")
    _git(repo, "add", "--all")
    _git(repo, "commit", "--quiet", "-m", "baseline")
    return repo


def _try_symlink(path: Path, target: str) -> bool:
    try:
        path.symlink_to(target)
    except (OSError, NotImplementedError):
        return False
    return path.is_symlink()


def test_model_patch_is_standard_git_patch_and_applies(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    head = _git(repo, "rev-parse", "HEAD").stdout.strip()
    _git(repo, "config", "core.autocrlf", "true")
    with (repo / "baseline.py").open("w", encoding="utf-8", newline="") as stream:
        stream.write("print('changed')\r\n")
    (repo / "new.txt").write_text("new file\n", encoding="utf-8")
    (repo / "delete.txt").unlink()
    (repo / "rename.txt").rename(repo / "renamed.txt")
    (repo / "binary.bin").write_bytes(b"\x00changed\xfe\x01")
    mode_supported = False
    try:
        mode_supported = _git(repo, "config", "--get", "core.filemode").stdout.strip().lower() == "true"
    except subprocess.CalledProcessError:
        mode_supported = False
    if mode_supported:
        (repo / "renamed.txt").chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    symlink_supported = _try_symlink(repo / "link-to-baseline", "baseline.py")
    runtime_permissions = repo / ".uthcode" / "permissions.toml"
    runtime_permissions.parent.mkdir()
    runtime_permissions.write_text("[policy]\n", encoding="utf-8")
    real_index = repo / ".git" / "index"
    index_before = real_index.read_bytes()

    patch = build_model_patch(
        repo,
        baseline_ref=head,
        exclude_paths=(".uthcode/permissions.toml",),
    )
    assert real_index.read_bytes() == index_before
    assert patch.startswith("diff --git ")
    assert ".uthcode/permissions.toml" not in patch
    assert "GIT binary patch" in patch
    assert "new file mode" in patch
    assert "deleted file mode" in patch
    assert "similarity index" in patch
    if mode_supported:
        assert "old mode" in patch or "new mode" in patch
    if symlink_supported:
        assert "120000" in patch

    applied = tmp_path / "applied"
    subprocess.run(["git", "clone", "--quiet", str(repo), str(applied)], check=True, capture_output=True, text=True)
    _git(applied, "config", "core.autocrlf", "true")
    if symlink_supported:
        _git(applied, "config", "core.symlinks", "true")
    _git(applied, "reset", "--hard", "HEAD")
    check_result = subprocess.run(
        ["git", "-C", str(applied), "apply", "--check", "--binary"],
        input=patch.encode("utf-8"),
        capture_output=True,
    )
    assert check_result.returncode == 0, check_result.stderr.decode("utf-8", errors="replace")
    apply_result = subprocess.run(
        ["git", "-C", str(applied), "apply", "--binary"],
        input=patch.encode("utf-8"),
        capture_output=True,
    )
    assert apply_result.returncode == 0, apply_result.stderr.decode("utf-8", errors="replace")
    assert (applied / "baseline.py").read_bytes() == (repo / "baseline.py").read_bytes()
    assert (applied / "new.txt").read_bytes() == (repo / "new.txt").read_bytes()
    assert not (applied / "delete.txt").exists()
    assert (applied / "renamed.txt").read_bytes() == (repo / "renamed.txt").read_bytes()
    assert (applied / "binary.bin").read_bytes() == (repo / "binary.bin").read_bytes()
    if mode_supported:
        assert bool((applied / "renamed.txt").stat().st_mode & stat.S_IXUSR) == bool(
            (repo / "renamed.txt").stat().st_mode & stat.S_IXUSR
        )
    if symlink_supported:
        if not (applied / "link-to-baseline").is_symlink():
            pytest.skip("Git checkout cannot materialize symlinks on this Windows host")
        assert (applied / "link-to-baseline").is_symlink()
        assert os.readlink(applied / "link-to-baseline") == os.readlink(repo / "link-to-baseline")


def test_tracked_permissions_file_is_not_silently_omitted(tmp_path: Path) -> None:
    repo = _repo(tmp_path, "tracked-permissions")
    permissions = repo / ".uthcode" / "permissions.toml"
    permissions.parent.mkdir()
    permissions.write_text("baseline\n", encoding="utf-8")
    _git(repo, "add", ".uthcode/permissions.toml")
    _git(repo, "commit", "--quiet", "-m", "tracked permissions")
    head = _git(repo, "rev-parse", "HEAD").stdout.strip()
    permissions.write_text("changed\n", encoding="utf-8")
    patch = build_model_patch(repo, baseline_ref=head)
    assert ".uthcode/permissions.toml" in patch


def test_trace_projection_removes_secret_and_native_media_fields() -> None:
    projected = sanitize_trace(
        {
            "text": "api_key=TOP-SECRET",
            "native_items": [{"payload": b"native-bytes"}],
            "image_bytes": b"image-bytes",
            "nested": {"authorization": "TOP-SECRET"},
        },
        ("TOP-SECRET",),
    )
    assert projected == {
        "text": "api_key=<redacted>",
        "nested": {"authorization": "<redacted>"},
    }


@pytest.mark.asyncio
async def test_external_instance_exports_three_fields_and_isolates_attempts(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    eval_root = tmp_path / "eval-root"
    secret = "TOP-SECRET"
    instance = SWEbenchInstance("demo__repo-1", repo, "Write the requested fix.", "org/model")

    first = await run_swebench_instance(
        instance,
        config=_config(api_key=secret),
        eval_root=eval_root,
        attempt_id="first",
        provider_builder=lambda _profile, _model: _WriteProvider("new.txt", secret),
    )
    payload = json.loads(first.prediction_path.read_text(encoding="utf-8"))
    assert set(payload) == {"instance_id", "model_name_or_path", "model_patch"}
    assert payload["instance_id"] == "demo__repo-1"
    assert payload["model_name_or_path"] == "org/model"
    assert "+++ b/new.txt" in payload["model_patch"]
    assert ".uthcode/permissions.toml" not in payload["model_patch"]
    assert (repo / "new.txt").read_text(encoding="utf-8") == "new file new.txt\n"
    trace_text = first.trace_path.read_text(encoding="utf-8")
    assert secret not in trace_text
    assert "native_items" not in trace_text
    assert first.attempt.workspace == repo

    second_repo = _repo(tmp_path, "instance-second")
    second_instance = SWEbenchInstance(
        "demo__repo-1-second",
        second_repo,
        "Write the requested fix.",
        "org/model",
    )
    second = await run_swebench_instance(
        second_instance,
        config=_config(api_key=secret),
        eval_root=tmp_path / "eval-root-second",
        attempt_id="second",
        provider_builder=lambda _profile, _model: _WriteProvider("second.txt", secret),
    )
    assert first.attempt.home != second.attempt.home
    assert first.attempt.artifacts != second.attempt.artifacts
    assert "+++ b/second.txt" in second.prediction.model_patch
    assert "+++ b/new.txt" not in second.prediction.model_patch


@pytest.mark.asyncio
async def test_dirty_external_instance_is_rejected_before_provider(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "baseline.py").write_text("dirty\n", encoding="utf-8")
    (repo / "staged.txt").write_text("staged\n", encoding="utf-8")
    _git(repo, "add", "staged.txt")
    (repo / "untracked.txt").write_text("untracked\n", encoding="utf-8")
    instance = SWEbenchInstance("dirty__repo-1", repo, "Do not run.", "org/model")
    provider_calls = 0

    def provider_builder(_profile: object, _model: str) -> _WriteProvider:
        nonlocal provider_calls
        provider_calls += 1
        return _WriteProvider("should-not-exist.txt", "secret")

    with pytest.raises(EvalExecutionError, match="must be clean"):
        await run_swebench_instance(
            instance,
            config=_config(),
            eval_root=tmp_path / "eval-root",
            provider_builder=provider_builder,
        )
    assert provider_calls == 0
