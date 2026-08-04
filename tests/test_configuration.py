from __future__ import annotations

import os
from pathlib import Path

import pytest

from uthcode.application import (
    ConfigSource,
    ConfigurationModelError,
    EffectiveConfig,
    ModelProfile,
    ProviderKind,
    ProviderProfile,
    LaunchOptions,
)
from uthcode.integrations.config import (
    ConfigurationError,
    ConfigurationInitializationRequired,
    discover_config_paths,
    load_effective_config,
    write_user_model,
)


def _mapping() -> dict[str, object]:
    return {
        "model": "profile/ref",
        "providers": {
            "profile": {
                "kind": "fake",
            }
        },
        "models": {
            "profile/ref": {
                "provider_profile_id": "profile",
                "remote_model_id": "remote-id",
                "label": "Readable label",
                "max_output_tokens": 128,
            }
        },
    }


def test_model_profile_keeps_provider_ref_model_ref_and_remote_id_distinct() -> None:
    config = EffectiveConfig.from_mapping(_mapping())

    provider = config.providers["profile"]
    model = config.models["profile/ref"]

    assert provider.provider_profile_id == "profile"
    assert model.model_ref == "profile/ref"
    assert model.provider_profile_id == "profile"
    assert model.remote_model_id == "remote-id"
    assert config.current_model is model


@pytest.mark.parametrize(
    ("mapping", "message"),
    [
        (
            {
                **_mapping(),
                "providers": {"profile": {"kind": "future-kind"}},
            },
            "unknown provider kind",
        ),
        (
            {
                **_mapping(),
                "models": {
                    "profile/ref": {
                        "provider_profile_id": "missing",
                        "remote_model_id": "remote-id",
                    }
                },
            },
            "unknown provider reference",
        ),
    ],
)
def test_model_references_and_provider_kind_are_validated(
    mapping: dict[str, object],
    message: str,
) -> None:
    with pytest.raises((ConfigurationModelError, ValueError), match=message):
        EffectiveConfig.from_mapping(mapping)

    with pytest.raises((ConfigurationModelError, ValueError), match="unknown selected model"):
        EffectiveConfig(
            model="missing/ref",
            providers={"profile": ProviderProfile("profile", ProviderKind.FAKE)},
            models={
                "profile/ref": ModelProfile(
                    "profile/ref", "profile", "remote-id"
                )
            },
        )


@pytest.mark.parametrize("value", [0, -1, True, "128", 1.5])
def test_invalid_output_token_configuration_is_rejected(value: object) -> None:
    with pytest.raises((ConfigurationModelError, TypeError, ValueError), match="max_output_tokens"):
        ModelProfile("profile/ref", "profile", "remote-id", max_output_tokens=value)  # type: ignore[arg-type]


def test_effective_config_is_deeply_immutable_and_copies_input_mapping() -> None:
    raw = _mapping()
    sources = [ConfigSource("user", Path("C:/user/config.toml"))]
    config = EffectiveConfig.from_mapping(raw, sources=sources)

    raw["model"] = "changed"
    raw["providers"] = {}
    sources.append(ConfigSource("project", Path("C:/project/config.toml")))

    assert config.model == "profile/ref"
    assert tuple(config.providers) == ("profile",)
    assert len(config.sources) == 1
    with pytest.raises(TypeError):
        config.providers["other"] = ProviderProfile("other", ProviderKind.FAKE)  # type: ignore[index]
    with pytest.raises(TypeError):
        config.models["profile/ref"] = config.current_model  # type: ignore[index]
    with pytest.raises(AttributeError):
        config.model = "changed"  # type: ignore[misc]


def test_single_model_headless_constructor_is_application_owned() -> None:
    config = EffectiveConfig.single_model(
        "local/ref",
        provider_profile_id="local",
        provider_kind=ProviderKind.FAKE,
        remote_model_id="remote-local",
        label="Local model",
        source=ConfigSource("embedded"),
    )

    assert config.model == "local/ref"
    assert config.current_model.remote_model_id == "remote-local"
    assert config.providers["local"].kind is ProviderKind.FAKE
    assert config.sources == (ConfigSource("embedded"),)


def test_application_exports_only_the_new_configuration_boundary() -> None:
    import uthcode.application as application

    assert "EffectiveConfig" in application.__all__
    assert "ProviderConfig" not in application.__dict__
    assert "ProviderConfig" not in application.__all__


def test_application_configuration_has_no_synonym_properties() -> None:
    config = EffectiveConfig.single_model("profile/ref")
    source = ConfigSource("user")
    provider = ProviderProfile("profile", ProviderKind.FAKE)
    model = ModelProfile("profile/ref", "default", "remote-id")

    assert not hasattr(LaunchOptions(model="profile/ref"), "model_override")
    assert not hasattr(source, "name")
    assert not hasattr(source, "location")
    assert not hasattr(provider, "id")
    assert not hasattr(provider, "profile_id")
    assert not hasattr(model, "ref")
    assert not hasattr(model, "model")
    assert not hasattr(model, "provider")
    assert not hasattr(model, "temperature")
    assert not hasattr(config, "selected_model")
    assert not hasattr(config, "selected_model_ref")
    assert not hasattr(config, "config_sources")
    with pytest.raises(ConfigurationModelError, match="unsupported EffectiveConfig field"):
        EffectiveConfig.from_mapping(
            {
                "model": "profile/ref",
                "selected_model": "profile/ref",
                "providers": {"default": {"kind": "fake"}},
                "models": {
                    "profile/ref": {
                        "provider_profile_id": "default",
                        "remote_model_id": "remote-id",
                    }
                },
            }
        )


def test_configuration_loader_has_one_model_override_parameter() -> None:
    with pytest.raises(TypeError):
        load_effective_config(model_override="profile/ref")  # type: ignore[call-arg]


def test_effective_config_mapping_uses_canonical_profile_fields_only() -> None:
    with pytest.raises(ConfigurationModelError):
        EffectiveConfig.from_mapping(
            {
                "model": "profile/ref",
                "providers": {"profile": {"kind": "fake"}},
                "models": {
                    "profile/ref": {
                        "provider": "profile",
                        "model": "remote-id",
                    }
                },
            }
        )


def test_effective_config_rejects_removed_temperature_field() -> None:
    mapping = _mapping()
    mapping["models"] = {
        "profile/ref": {
            "provider_profile_id": "profile",
            "remote_model_id": "remote-id",
            "temperature": 0.2,
        }
    }

    with pytest.raises(ConfigurationModelError, match="temperature"):
        EffectiveConfig.from_mapping(mapping)


def _write_user_config(home: Path, *, model: str = "base/ref") -> Path:
    path = home / ".uthcode" / "config.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f'''model = "{model}"

[providers.local]
kind = "fake"

[models."base/ref"]
provider = "local"
model = "base-remote"
label = "Base"
max_output_tokens = 128
''',
        encoding="utf-8",
    )
    return path


def test_user_temperature_field_fails_as_unsupported_configuration(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    user = _write_user_config(home)
    user.write_text(
        user.read_text(encoding="utf-8").replace(
            "max_output_tokens = 128\n",
            "max_output_tokens = 128\ntemperature = 0.2\n",
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError) as raised:
        load_effective_config(cwd=tmp_path, home=home)

    assert str(user.resolve()) in str(raised.value)
    assert "temperature" in str(raised.value)


def test_project_temperature_field_fails_as_unsupported_configuration(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    _write_user_config(home)
    root = tmp_path / "repo"
    cwd = root / "child"
    cwd.mkdir(parents=True)
    (root / ".git").mkdir()
    project = root / ".uthcode" / "config.toml"
    project.parent.mkdir()
    project.write_text(
        '''[models."base/ref"]
temperature = 0.2
''',
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError) as raised:
        load_effective_config(cwd=cwd, home=home)

    assert str(project.resolve()) in str(raised.value)
    assert "temperature" in str(raised.value)


def test_max_output_tokens_survives_user_and_project_configuration(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    _write_user_config(home)
    user_config = load_effective_config(cwd=tmp_path, home=home)
    assert user_config.models["base/ref"].max_output_tokens == 128

    root = tmp_path / "repo"
    cwd = root / "child"
    cwd.mkdir(parents=True)
    (root / ".git").mkdir()
    project = root / ".uthcode" / "config.toml"
    project.parent.mkdir()
    project.write_text(
        '''[models."base/ref"]
max_output_tokens = 256
''',
        encoding="utf-8",
    )

    merged_config = load_effective_config(cwd=cwd, home=home)
    assert merged_config.models["base/ref"].max_output_tokens == 256


def test_missing_user_config_creates_safe_template_and_stops(tmp_path: Path) -> None:
    home = tmp_path / "home"

    with pytest.raises(ConfigurationInitializationRequired) as raised:
        load_effective_config(cwd=tmp_path, home=home)

    template = home / ".uthcode" / "config.toml"
    assert raised.value.template_path == template.resolve()
    assert template.is_file()
    content = template.read_text(encoding="utf-8")
    assert "# model =" in content
    assert "# [providers." in content
    assert "# api_key_env" in content
    assert "sk-" not in content
    assert "YOUR_API_KEY_ENVIRONMENT_VARIABLE" in content


@pytest.mark.parametrize(
    "forbidden",
    ["providers", "kind", "base_url", "api_key_env", "api_key", "secret_env"],
)
def test_project_provider_and_credential_fields_hard_fail(
    tmp_path: Path,
    forbidden: str,
) -> None:
    home = tmp_path / "home"
    _write_user_config(home)
    cwd = tmp_path / "repo" / "nested"
    cwd.mkdir(parents=True)
    (tmp_path / "repo" / ".git").mkdir()
    project = tmp_path / "repo" / ".uthcode" / "config.toml"
    project.parent.mkdir()
    if forbidden == "providers":
        body = '[providers.evil]\nkind = "fake"\n'
    elif forbidden == "kind":
        body = '[models."base/ref"]\nkind = "fake"\n'
    else:
        body = f'[models."base/ref"]\n{forbidden} = "redirect"\n'
    project.write_text(body, encoding="utf-8")

    with pytest.raises(ConfigurationError) as raised:
        load_effective_config(cwd=cwd, home=home)

    assert str(project.resolve()) in str(raised.value)
    assert forbidden in str(raised.value)


def test_git_root_to_cwd_project_layers_merge_nearest_first(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_user_config(home)
    root = tmp_path / "repo"
    nested = root / "one" / "two"
    nested.mkdir(parents=True)
    (root / ".git").mkdir()

    root_config = root / ".uthcode" / "config.toml"
    root_config.parent.mkdir()
    root_config.write_text(
        '''[models."root/ref"]
provider = "local"
model = "root-remote"
label = "root"
''',
        encoding="utf-8",
    )
    one_config = root / "one" / ".uthcode" / "config.toml"
    one_config.parent.mkdir()
    one_config.write_text(
        '''[models."root/ref"]
label = "one"
''',
        encoding="utf-8",
    )
    two_config = nested / ".uthcode" / "config.toml"
    two_config.parent.mkdir()
    two_config.write_text(
        '''model = "root/ref"
[models."root/ref"]
label = "two"
''',
        encoding="utf-8",
    )

    config = load_effective_config(cwd=nested, home=home)

    assert config.model == "root/ref"
    assert config.models["root/ref"].label == "two"
    assert [source.path for source in config.sources] == [
        home.joinpath(".uthcode", "config.toml").resolve(),
        root_config.resolve(),
        one_config.resolve(),
        two_config.resolve(),
    ]


def test_git_worktree_dot_git_file_is_detected(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_user_config(home)
    root = tmp_path / "worktree"
    cwd = root / "child"
    cwd.mkdir(parents=True)
    (root / ".git").write_text("gitdir: C:/elsewhere/worktree", encoding="utf-8")
    config_path = root / ".uthcode" / "config.toml"
    config_path.parent.mkdir()
    config_path.write_text(
        '[models."base/ref"]\nlabel = "worktree"\n',
        encoding="utf-8",
    )

    config = load_effective_config(cwd=cwd, home=home)

    assert config.models["base/ref"].label == "worktree"
    assert config.sources[-1].path == config_path.resolve()


def test_non_git_directory_only_reads_cwd_project_config(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_user_config(home)
    parent = tmp_path / "parent"
    cwd = parent / "cwd"
    cwd.mkdir(parents=True)
    (parent / ".uthcode").mkdir()
    (parent / ".uthcode" / "config.toml").write_text(
        'model = "missing/ref"\n',
        encoding="utf-8",
    )
    cwd_config = cwd / ".uthcode" / "config.toml"
    cwd_config.parent.mkdir()
    cwd_config.write_text(
        'model = "base/ref"\n',
        encoding="utf-8",
    )

    config = load_effective_config(cwd=cwd, home=home)

    assert config.model == "base/ref"
    assert [source.path for source in config.sources] == [
        (home / ".uthcode" / "config.toml").resolve(),
        cwd_config.resolve(),
    ]


def test_physical_duplicate_project_config_is_loaded_once(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_user_config(home)
    root = tmp_path / "repo"
    cwd = root / "child"
    cwd.mkdir(parents=True)
    (root / ".git").mkdir()
    root_config = root / ".uthcode" / "config.toml"
    root_config.parent.mkdir()
    root_config.write_text(
        '[models."base/ref"]\nlabel = "same-file"\n',
        encoding="utf-8",
    )
    duplicate = cwd / ".uthcode" / "config.toml"
    duplicate.parent.mkdir()
    try:
        duplicate.symlink_to(root_config)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are unavailable")

    paths = discover_config_paths(cwd, home / ".uthcode" / "config.toml")
    project_paths = [path for kind, path in paths if kind == "project"]
    assert project_paths == [root_config.resolve()]

    config = load_effective_config(cwd=cwd, home=home)
    assert [
        source.path
        for source in config.sources
        if source.kind == "project"
    ] == [root_config.resolve()]


def test_relative_config_arguments_are_deduplicated_in_final_sources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "relative-repo"
    cwd = root / "child"
    cwd.mkdir(parents=True)
    (root / ".git").mkdir()
    user_config = _write_user_config(root)

    monkeypatch.chdir(tmp_path)
    config = load_effective_config(
        cwd=Path("relative-repo") / "child",
        home=Path("relative-repo"),
    )

    assert len(config.sources) == 1
    assert config.sources[0].kind == "user"
    assert config.sources[0].path == user_config.resolve()


@pytest.mark.skipif(os.name != "nt", reason="Windows case-insensitive paths required")
def test_windows_case_variant_is_deduplicated_in_final_sources(
    tmp_path: Path,
) -> None:
    root = tmp_path / "CaseRepo"
    cwd = root / "child"
    cwd.mkdir(parents=True)
    (root / ".git").mkdir()
    user_config = _write_user_config(root)
    case_root = Path(str(root).swapcase())
    case_cwd = Path(str(cwd).swapcase())

    config = load_effective_config(cwd=case_cwd, home=case_root)

    assert len(config.sources) == 1
    source_path = config.sources[0].path
    assert source_path is not None
    assert source_path.samefile(user_config)


def test_project_model_can_reference_user_provider_and_cli_model_has_priority(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    _write_user_config(home)
    cwd = tmp_path / "repo"
    cwd.mkdir()
    project = cwd / ".uthcode" / "config.toml"
    project.parent.mkdir()
    project.write_text(
        '''model = "project/ref"
[models."project/ref"]
provider = "local"
model = "project-remote"
''',
        encoding="utf-8",
    )

    config = load_effective_config(cwd=cwd, home=home, model="base/ref")

    assert config.model == "base/ref"
    assert config.models["project/ref"].provider_profile_id == "local"
    assert config.sources[-1].kind == "cli"


def test_invalid_project_model_provider_reference_reports_project_path(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_user_config(home)
    cwd = tmp_path / "repo"
    cwd.mkdir()
    project = cwd / ".uthcode" / "config.toml"
    project.parent.mkdir()
    project.write_text(
        '''model = "project/ref"
[models."project/ref"]
provider = "missing"
model = "remote"
''',
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError) as raised:
        load_effective_config(cwd=cwd, home=home)

    assert str(project.resolve()) in str(raised.value)
    assert "unknown provider reference" in str(raised.value)


def test_user_model_writeback_preserves_comments_tables_and_project_file(
    tmp_path: Path,
) -> None:
    user = tmp_path / "config.toml"
    original = '''# keep this comment
model = "old/ref"

[providers.local]
kind = "fake"

# keep model comment
[models."old/ref"]
provider = "local"
model = "old-remote"
label = "Old"
'''
    user.write_text(original, encoding="utf-8")
    project = tmp_path / "project.toml"
    project_text = 'model = "old/ref"\n'
    project.write_text(project_text, encoding="utf-8")

    write_user_model(user, "new/ref")
    updated = user.read_text(encoding="utf-8")

    assert 'model = "new/ref"' in updated
    assert "# keep this comment" in updated
    assert "# keep model comment" in updated
    assert updated.index("[providers.local]") < updated.index('[models."old/ref"]')
    assert 'kind = "fake"' in updated
    assert 'model = "old-remote"' in updated
    assert project.read_text(encoding="utf-8") == project_text


def test_user_model_writeback_keeps_original_bytes_when_replace_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = tmp_path / "config.toml"
    original = 'model = "old/ref"\n\n[providers.local]\nkind = "fake"\n'
    user.write_text(original, encoding="utf-8")

    import uthcode.integrations.config.writer as writer

    def fail_replace(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated atomic replace failure")

    monkeypatch.setattr(writer.os, "replace", fail_replace)
    with pytest.raises(OSError, match="simulated atomic replace failure"):
        writer.write_user_model(user, "new/ref")

    assert user.read_text(encoding="utf-8") == original
    assert not list(tmp_path.glob(".*.tmp"))


def test_loader_does_not_read_environment_secrets_or_make_provider_requests(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    _write_user_config(home)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-configuration-test-secret")

    config = load_effective_config(cwd=tmp_path, home=home)

    assert config.providers["local"].api_key_env is None
    assert "sk-configuration-test-secret" not in repr(config)
