from __future__ import annotations

from pathlib import Path

import pytest

from uthcode.integrations.config.data import LoadedConfigData, LoadedConfigSource
from uthcode.integrations.config.loader import (
    ConfigurationError,
    ConfigurationInitializationRequired,
    discover_config_paths,
    load_config_data,
)
from uthcode.integrations.config.writer import (
    write_user_default_permission_mode,
    write_user_default_model,
)


def test_user_permission_default_loads_writes_and_rejects_unsafe_values(tmp_path: Path) -> None:
    home = tmp_path / "home"
    user = home / ".uthcode" / "config.toml"
    user.parent.mkdir(parents=True)
    user.write_text(
        '# keep\ndefault_permission_mode = "auto"\ndefault_model = "local/ref"\n'
        '[providers.local]\nkind = "fake"\n'
        '[models."local/ref"]\nprovider = "local"\nremote_id = "fake"\n',
        encoding="utf-8",
    )

    assert load_config_data(cwd=tmp_path, home=home).default_permission_mode == "auto"
    write_user_default_permission_mode(user, "default")
    rendered = user.read_text(encoding="utf-8")
    assert '# keep' in rendered
    assert 'default_permission_mode = "default"' in rendered
    with pytest.raises(ValueError):
        write_user_default_permission_mode(user, "full_access")


def test_project_permission_default_is_rejected(tmp_path: Path) -> None:
    home = tmp_path / "home"
    user = home / ".uthcode" / "config.toml"
    user.parent.mkdir(parents=True)
    user.write_text(
        'default_model = "local/ref"\n[providers.local]\nkind = "fake"\n'
        '[models."local/ref"]\nprovider = "local"\nremote_id = "fake"\n',
        encoding="utf-8",
    )
    project = tmp_path / ".uthcode" / "config.toml"
    project.parent.mkdir()
    project.write_text('default_permission_mode = "auto"\n', encoding="utf-8")

    with pytest.raises(ConfigurationError, match="default_permission_mode"):
        load_config_data(cwd=tmp_path, home=home)


def _write_user_config(home: Path, *, model: str = "base/ref") -> Path:
    path = home / ".uthcode" / "config.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f'''default_model = "{model}"

[providers.local]
kind = "fake"

[models."base/ref"]
provider = "local"
remote_id = "base-remote"
display_name = "Base"
max_output_tokens = 128
''',
        encoding="utf-8",
    )
    return path


def test_loader_returns_immutable_canonical_raw_data(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_user_config(home)
    data = load_config_data(cwd=tmp_path, home=home)

    assert isinstance(data, LoadedConfigData)
    assert data.default_model == "base/ref"
    assert data.providers["local"] == {"kind": "fake"}
    assert data.models["base/ref"] == {
        "provider_profile_id": "local",
        "remote_id": "base-remote",
        "display_name": "Base",
        "max_output_tokens": 128,
    }
    assert data.sources == (LoadedConfigSource("user", (home / ".uthcode" / "config.toml").resolve()),)

    with pytest.raises(TypeError):
        data.providers["other"] = {"kind": "fake"}  # type: ignore[index]
    with pytest.raises(TypeError):
        data.models["base/ref"]["remote_id"] = "changed"  # type: ignore[index]


def test_loader_returns_raw_data_with_sources_and_cli_precedence(tmp_path: Path) -> None:
    home = tmp_path / "home"
    user = _write_user_config(home)
    root = tmp_path / "repo"
    cwd = root / "child"
    cwd.mkdir(parents=True)
    (root / ".git").mkdir()
    project = root / ".uthcode" / "config.toml"
    project.parent.mkdir()
    project.write_text(
        '''default_model = "project/ref"
[models."project/ref"]
provider = "local"
remote_id = "project-remote"
''',
        encoding="utf-8",
    )

    data = load_config_data(cwd=cwd, home=home, model="base/ref")

    assert data.default_model == "base/ref"
    assert data.models["project/ref"] == {
        "provider_profile_id": "local",
        "remote_id": "project-remote",
    }
    assert data.sources == (
        LoadedConfigSource("user", user.resolve()),
        LoadedConfigSource("project", project.resolve()),
        LoadedConfigSource("cli"),
    )


def test_loader_preserves_initialization_and_field_evidence(tmp_path: Path) -> None:
    home = tmp_path / "home"

    with pytest.raises(ConfigurationInitializationRequired) as initialization:
        load_config_data(cwd=tmp_path, home=home)
    assert initialization.value.template_path == (
        home / ".uthcode" / "config.toml"
    ).resolve()

    user = home / ".uthcode" / "config.toml"
    user.write_text('[providers.local]\nkind = "fake"\n', encoding="utf-8")
    with pytest.raises(ConfigurationError) as missing_model:
        load_config_data(cwd=tmp_path, home=home)
    assert missing_model.value.path == user.resolve()
    assert missing_model.value.field == "default_model"


def test_discover_config_paths_deduplicates_physical_files(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_user_config(home)
    root = tmp_path / "repo"
    cwd = root / "child"
    cwd.mkdir(parents=True)
    (root / ".git").mkdir()
    root_config = root / ".uthcode" / "config.toml"
    root_config.parent.mkdir()
    root_config.write_text('[models."base/ref"]\ndisplay_name = "same"\n', encoding="utf-8")
    duplicate = cwd / ".uthcode" / "config.toml"
    duplicate.parent.mkdir()
    try:
        duplicate.symlink_to(root_config)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are unavailable")

    paths = discover_config_paths(cwd, home / ".uthcode" / "config.toml")

    assert [path for kind, path in paths if kind == "project"] == [
        root_config.resolve()
    ]


def test_user_model_writeback_preserves_comments_and_project_file(
    tmp_path: Path,
) -> None:
    user = tmp_path / "config.toml"
    original = '''# keep this comment
default_model = "old/ref"

[providers.local]
kind = "fake"

# keep model comment
[models."old/ref"]
provider = "local"
remote_id = "old-remote"
display_name = "Old"
'''
    user.write_text(original, encoding="utf-8")
    project = tmp_path / "project.toml"
    project_text = 'default_model = "old/ref"\n'
    project.write_text(project_text, encoding="utf-8")

    write_user_default_model(user, "new/ref")
    updated = user.read_text(encoding="utf-8")

    assert 'default_model = "new/ref"' in updated
    assert "# keep this comment" in updated
    assert "# keep model comment" in updated
    assert updated.index("[providers.local]") < updated.index('[models."old/ref"]')
    assert 'kind = "fake"' in updated
    assert 'remote_id = "old-remote"' in updated
    assert project.read_text(encoding="utf-8") == project_text


def test_user_model_writeback_keeps_bytes_when_replace_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = tmp_path / "config.toml"
    original = 'default_model = "old/ref"\n\n[providers.local]\nkind = "fake"\n'
    user.write_text(original, encoding="utf-8")

    import uthcode.integrations.config.writer as writer

    def fail_replace(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated atomic replace failure")

    monkeypatch.setattr(writer.os, "replace", fail_replace)
    with pytest.raises(OSError, match="simulated atomic replace failure"):
        writer.write_user_default_model(user, "new/ref")

    assert user.read_text(encoding="utf-8") == original
    assert not list(tmp_path.glob(".*.tmp"))
