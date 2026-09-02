from __future__ import annotations

import os
from pathlib import Path

import pytest

from uthcode.application import (
    ConfigSource,
    ConfigurationError,
    ConfigurationInitializationRequired,
    ConfigurationModelError,
    EffectiveConfig,
    LaunchOptions,
    ModelProfile,
    ProviderKind,
    ProviderProfile,
    UserConfigurationView,
    UserConfigurationWriteRequest,
    create_application,
    read_user_api_key,
    read_user_configuration,
    write_user_configuration,
    load_effective_config,
)


def _mapping() -> dict[str, object]:
    return {
        "default_model": "profile/ref",
        "providers": {
            "profile": {
                "kind": "fake",
            }
        },
        "models": {
            "profile/ref": {
                "provider_profile_id": "profile",
                "remote_id": "remote-id",
                "display_name": "Readable label",
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
    assert model.remote_id == "remote-id"
    assert config.current_model is model


def test_provider_display_name_round_trips_without_changing_stable_references(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    user = home / ".uthcode" / "config.toml"
    user.parent.mkdir(parents=True)
    user.write_text(
        '''default_model = "protocol/model"

[providers.protocol]
kind = "fake"
display_name = "Local gateway"

[providers.protocol_1]
kind = "fake"

[models."protocol/model"]
provider = "protocol"
remote_id = "served-model"
''',
        encoding="utf-8",
    )

    initial = read_user_configuration(home=home)
    assert initial.providers["protocol"].display_name == "Local gateway"
    assert initial.providers["protocol_1"].display_name is None

    written = write_user_configuration(
        UserConfigurationWriteRequest(
            default_model="protocol/model",
            providers={
                "protocol": {"kind": "fake", "display_name": "Company DeepSeek"},
                "protocol_1": {"kind": "fake", "display_name": None},
            },
            models={
                "protocol/model": {
                    "provider_profile_id": "protocol",
                    "remote_id": "served-model",
                }
            },
        ),
        home=home,
    )

    assert written.providers["protocol"].display_name == "Company DeepSeek"
    assert written.providers["protocol_1"].display_name is None
    assert written.models["protocol/model"].provider_profile_id == "protocol"
    reloaded = load_effective_config(cwd=tmp_path, home=home)
    assert reloaded.providers["protocol"].display_name == "Company DeepSeek"
    assert reloaded.providers["protocol_1"].display_name is None
    assert reloaded.models["protocol/model"].provider_profile_id == "protocol"
    rendered = user.read_text(encoding="utf-8")
    assert 'display_name = "Company DeepSeek"' in rendered
    assert "[providers.protocol_1]" in rendered


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
                        "remote_id": "remote-id",
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
            default_model="missing/ref",
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

    raw["default_model"] = "changed"
    raw["providers"] = {}
    sources.append(ConfigSource("project", Path("C:/project/config.toml")))

    assert config.default_model == "profile/ref"
    assert tuple(config.providers) == ("profile",)
    assert len(config.sources) == 1
    with pytest.raises(TypeError):
        config.providers["other"] = ProviderProfile("other", ProviderKind.FAKE)  # type: ignore[index]
    with pytest.raises(TypeError):
        config.models["profile/ref"] = config.current_model  # type: ignore[index]
    with pytest.raises(AttributeError):
        config.default_model = "changed"  # type: ignore[misc]


def test_single_model_headless_constructor_is_application_owned() -> None:
    config = EffectiveConfig.single_model(
        "local/ref",
        provider_profile_id="local",
        provider_kind=ProviderKind.FAKE,
        remote_id="remote-local",
        display_name="Local model",
        source=ConfigSource("embedded"),
    )

    assert config.default_model == "local/ref"
    assert config.current_model.remote_id == "remote-local"
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
                        "remote_id": "remote-id",
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
            "remote_id": "remote-id",
            "temperature": 0.2,
        }
    }

    with pytest.raises(ConfigurationModelError, match="temperature"):
        EffectiveConfig.from_mapping(mapping)


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
    assert 'default_model = ""' in content
    assert 'default_permission_mode = "default"' in content
    assert "[providers.slot-1]" in content
    assert '[models."slot-1"]' in content
    assert 'api_key = ""' in content
    assert "env:" in content
    assert content.count('# reasoning_effort = ""') == 3
    assert '# reasoning_effort = "medium"' not in content
    for forbidden in (
        "fake",
        "anthropic",
        "openai_responses",
        "openai_compat",
        "literal-secret",
        "VARIABLE_NAME",
        "your-key",
        "https://",
        "sk-",
    ):
        assert forbidden not in content
    assert "delete" in content.lower()


def test_comment_only_user_template_reports_initialization_guidance(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"

    with pytest.raises(ConfigurationInitializationRequired):
        load_effective_config(cwd=tmp_path, home=home)

    with pytest.raises(ConfigurationInitializationRequired) as raised:
        load_effective_config(cwd=tmp_path, home=home)

    assert raised.value.template_path == (home / ".uthcode" / "config.toml").resolve()
    assert "configuration is not initialized" in str(raised.value)
    assert "fill one complete" in str(raised.value)


def test_partially_enabled_user_config_without_model_keeps_field_error(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    user_config = home / ".uthcode" / "config.toml"
    user_config.parent.mkdir(parents=True)
    user_config.write_text('[providers.local]\nkind = "fake"\n', encoding="utf-8")

    with pytest.raises(ConfigurationError) as raised:
        load_effective_config(cwd=tmp_path, home=home)

    assert not isinstance(raised.value, ConfigurationInitializationRequired)
    assert raised.value.field == "default_model"
    assert "configuration requires a default_model" in str(raised.value)


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
remote_id = "root-remote"
display_name = "root"
''',
        encoding="utf-8",
    )
    one_config = root / "one" / ".uthcode" / "config.toml"
    one_config.parent.mkdir()
    one_config.write_text(
        '''[models."root/ref"]
display_name = "one"
''',
        encoding="utf-8",
    )
    two_config = nested / ".uthcode" / "config.toml"
    two_config.parent.mkdir()
    two_config.write_text(
        '''default_model = "root/ref"
[models."root/ref"]
display_name = "two"
''',
        encoding="utf-8",
    )

    config = load_effective_config(cwd=nested, home=home)

    assert config.default_model == "root/ref"
    assert config.models["root/ref"].display_name == "two"
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
        '[models."base/ref"]\ndisplay_name = "worktree"\n',
        encoding="utf-8",
    )

    config = load_effective_config(cwd=cwd, home=home)

    assert config.models["base/ref"].display_name == "worktree"
    assert config.sources[-1].path == config_path.resolve()


def test_non_git_directory_only_reads_cwd_project_config(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _write_user_config(home)
    parent = tmp_path / "parent"
    cwd = parent / "cwd"
    cwd.mkdir(parents=True)
    (parent / ".uthcode").mkdir()
    (parent / ".uthcode" / "config.toml").write_text(
        'default_model = "missing/ref"\n',
        encoding="utf-8",
    )
    cwd_config = cwd / ".uthcode" / "config.toml"
    cwd_config.parent.mkdir()
    cwd_config.write_text(
        'default_model = "base/ref"\n',
        encoding="utf-8",
    )

    config = load_effective_config(cwd=cwd, home=home)

    assert config.default_model == "base/ref"
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
        '[models."base/ref"]\ndisplay_name = "same-file"\n',
        encoding="utf-8",
    )
    duplicate = cwd / ".uthcode" / "config.toml"
    duplicate.parent.mkdir()
    try:
        duplicate.symlink_to(root_config)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are unavailable")

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
        '''default_model = "project/ref"
[models."project/ref"]
provider = "local"
remote_id = "project-remote"
''',
        encoding="utf-8",
    )

    config = load_effective_config(cwd=cwd, home=home, model="base/ref")

    assert config.default_model == "base/ref"
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
        '''default_model = "project/ref"
[models."project/ref"]
provider = "missing"
remote_id = "remote"
''',
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError) as raised:
        load_effective_config(cwd=cwd, home=home)

    assert str(project.resolve()) in str(raised.value)
    assert "unknown provider reference" in str(raised.value)


def test_loader_does_not_read_environment_secrets_or_make_provider_requests(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    _write_user_config(home)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-configuration-test-secret")

    config = load_effective_config(cwd=tmp_path, home=home)

    assert config.providers["local"].api_key is None
    assert "sk-configuration-test-secret" not in repr(config)


def test_user_configuration_view_is_available_before_application_bootstrap(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"

    view = read_user_configuration(home=home)

    assert isinstance(view, UserConfigurationView)
    assert view.default_model == ""
    assert view.default_permission_mode == "default"
    assert set(view.providers) == {"slot-1", "slot-2", "slot-3"}
    assert set(view.models) == {"slot-1", "slot-2", "slot-3"}
    assert all(not provider.api_key_configured for provider in view.providers.values())
    assert "slot-1-secret" not in repr(view)


@pytest.mark.parametrize(
    ("expression", "environment_name", "environment_value"),
    [
        ("literal-configured-key", None, None),
        ("env:W04_CONFIGURED_KEY", "W04_CONFIGURED_KEY", "resolved-secret-must-not-return"),
    ],
)
def test_user_api_key_reveal_reads_only_the_saved_expression(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    expression: str,
    environment_name: str | None,
    environment_value: str | None,
) -> None:
    home = tmp_path / "home"
    user = home / ".uthcode" / "config.toml"
    user.parent.mkdir(parents=True)
    if environment_name is None:
        monkeypatch.delenv("W04_CONFIGURED_KEY", raising=False)
    else:
        monkeypatch.setenv(environment_name, environment_value or "")
    user.write_text(
        f'''default_model = "remote/ref"

[providers.remote]
kind = "openai_responses"
api_key = "{expression}"

[models."remote/ref"]
provider = "remote"
remote_id = "remote"
''',
        encoding="utf-8",
    )

    revealed = read_user_api_key("remote", home=home)

    assert revealed == expression
    assert revealed != environment_value


def test_user_api_key_reveal_unknown_provider_is_safe_configuration_error(tmp_path: Path) -> None:
    home = tmp_path / "home"
    user = home / ".uthcode" / "config.toml"
    user.parent.mkdir(parents=True)
    user.write_text(
        '''default_model = "remote/ref"

[providers.remote]
kind = "fake"

[models."remote/ref"]
provider = "remote"
remote_id = "remote"
''',
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="Provider profile was not found"):
        read_user_api_key("missing", home=home)


def test_semantically_invalid_toml_still_returns_editable_safe_view(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    user = home / ".uthcode" / "config.toml"
    user.parent.mkdir(parents=True)
    user.write_text(
        '''default_model = "missing/ref"
default_permission_mode = "full_access"

[providers.local]
kind = "not-a-provider"
api_key = "safe-view-secret"

[models."broken/ref"]
provider = "missing"
remote_id = ""
context_window = -1
''',
        encoding="utf-8",
    )

    view = read_user_configuration(home=home)

    assert view.default_model == "missing/ref"
    assert view.default_permission_mode == "full_access"
    assert view.providers["local"].kind == "not-a-provider"
    assert view.providers["local"].api_key_configured is True
    assert view.models["broken/ref"].provider_profile_id == "missing"
    assert view.models["broken/ref"].context_window == -1
    assert "safe-view-secret" not in repr(view)


def test_invalid_toml_read_is_stable_and_preserves_original_file(tmp_path: Path) -> None:
    home = tmp_path / "home"
    user = home / ".uthcode" / "config.toml"
    user.parent.mkdir(parents=True)
    original = 'default_model = "unterminated\n'
    user.write_text(original, encoding="utf-8")

    with pytest.raises(ConfigurationError, match="configuration cannot be parsed") as raised:
        read_user_configuration(home=home)

    assert raised.value.path == user.resolve()
    assert user.read_text(encoding="utf-8") == original


def test_user_configuration_write_preserves_or_replaces_keys_without_exposing_them(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    user = home / ".uthcode" / "config.toml"
    user.parent.mkdir(parents=True)
    old_key = "literal-old-user-config-secret"
    new_key = "literal-new-user-config-secret"
    user.write_text(
        f'''# retain this comment
default_model = "local/ref"
default_permission_mode = "auto"

[providers.local]
kind = "openai_responses"
api_key = "{old_key}"

[models."local/ref"]
provider = "local"
remote_id = "remote"
''',
        encoding="utf-8",
    )

    original_view = read_user_configuration(home=home)
    request = UserConfigurationWriteRequest(
        default_model="local/ref",
        default_permission_mode="default",
        providers={
            "local": {
                "kind": "openai_responses",
                # An explicit None means retain the existing literal/env
                # expression, as a form submission may send null for an
                # unchanged field.
                "api_key": None,
            }
        },
        models={
            "local/ref": {
                "provider_profile_id": "local",
                "remote_id": "remote-updated",
            }
        },
    )
    retained = write_user_configuration(request, home=home)

    assert retained.providers["local"].api_key_configured is True
    assert old_key in user.read_text(encoding="utf-8")
    assert new_key not in repr(retained)
    assert "# retain this comment" in user.read_text(encoding="utf-8")

    replaced = write_user_configuration(
        UserConfigurationWriteRequest(
            default_model="local/ref",
            providers={
                "local": {
                    "kind": "openai_responses",
                    "api_key": new_key,
                }
            },
            models={
                "local/ref": {
                    "provider_profile_id": "local",
                    "remote_id": "remote-updated",
                }
            },
        ),
        home=home,
    )

    rendered = user.read_text(encoding="utf-8")
    assert new_key in rendered
    assert old_key not in rendered
    assert new_key not in repr(replaced)
    assert original_view.models["local/ref"].remote_id == "remote"


@pytest.mark.parametrize("environment_value", [None, "env-retained-secret"])
def test_user_configuration_write_retains_env_key_without_resolving_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    environment_value: str | None,
) -> None:
    home = tmp_path / "home"
    user = home / ".uthcode" / "config.toml"
    user.parent.mkdir(parents=True)
    environment_name = "W01_RETAINED_CONFIG_KEY"
    if environment_value is None:
        monkeypatch.delenv(environment_name, raising=False)
    else:
        monkeypatch.setenv(environment_name, environment_value)
    expression = f"env:{environment_name}"
    user.write_text(
        f'''default_model = "remote/ref"

[providers.remote]
kind = "openai_responses"
api_key = "{expression}"

[models."remote/ref"]
provider = "remote"
remote_id = "remote"
''',
        encoding="utf-8",
    )

    retained = write_user_configuration(
        UserConfigurationWriteRequest(
            default_model="remote/ref",
            providers={
                "remote": {
                    "kind": "openai_responses",
                    "api_key": None,
                }
            },
            models={
                "remote/ref": {
                    "provider_profile_id": "remote",
                    "remote_id": "remote-updated",
                }
            },
        ),
        home=home,
    )

    assert retained.providers["remote"].api_key_configured is True
    assert f'api_key = "{expression}"' in user.read_text(encoding="utf-8")
    if environment_value is None:
        with pytest.raises(ConfigurationError, match="missing or empty"):
            load_effective_config(cwd=tmp_path, home=home)
    else:
        config = load_effective_config(cwd=tmp_path, home=home)
        assert config.providers["remote"].api_key is not None
        assert config.providers["remote"].api_key.reveal() == environment_value


@pytest.mark.parametrize(
    ("key_expression", "environment_name", "environment_value", "replacement"),
    [
        ("literal-old-provider-key", None, None, None),
        ("env:W06_PROVIDER_RENAME_KEY", "W06_PROVIDER_RENAME_KEY", "env-retained-secret", None),
        ("literal-old-provider-key", None, None, "literal-new-provider-key"),
    ],
)
def test_user_configuration_write_renames_provider_without_exposing_or_losing_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    key_expression: str,
    environment_name: str | None,
    environment_value: str | None,
    replacement: str | None,
) -> None:
    home = tmp_path / "home"
    user = home / ".uthcode" / "config.toml"
    user.parent.mkdir(parents=True)
    if environment_name is None:
        monkeypatch.delenv("W06_PROVIDER_RENAME_KEY", raising=False)
    elif environment_value is None:
        monkeypatch.delenv(environment_name, raising=False)
    else:
        monkeypatch.setenv(environment_name, environment_value)
    user.write_text(
        f'''default_model = "remote/ref"

[providers.remote]
kind = "openai_responses"
api_key = "{key_expression}"

[models."remote/ref"]
provider = "remote"
remote_id = "remote"
''',
        encoding="utf-8",
    )
    request_profile: dict[str, object] = {"kind": "openai_responses"}
    if replacement is not None:
        request_profile["api_key"] = replacement
    request = UserConfigurationWriteRequest(
        default_model="remote/ref",
        provider_renames={"remote": "renamed"},
        providers={"renamed": request_profile},
        models={
            "remote/ref": {
                "provider_profile_id": "renamed",
                "remote_id": "remote",
            }
        },
    )

    written = write_user_configuration(request, home=home)
    rendered = user.read_text(encoding="utf-8")
    assert set(written.providers) == {"renamed"}
    assert written.models["remote/ref"].provider_profile_id == "renamed"
    assert written.default_model == "remote/ref"
    assert written.providers["renamed"].api_key_configured is True
    assert "remote]" not in rendered
    assert 'provider = "renamed"' in rendered
    if replacement is None:
        assert f'api_key = "{key_expression}"' in rendered
    else:
        assert f'api_key = "{replacement}"' in rendered
        assert key_expression not in rendered
    assert key_expression not in repr(request)
    assert key_expression not in repr(written)
    assert replacement is None or replacement not in repr(written)
    safe_request = request.to_dict()
    assert safe_request["provider_renames"] == {"remote": "renamed"}
    expected_provider = {"kind": "openai_responses"}
    if replacement is not None:
        expected_provider["api_key_configured"] = True
    assert safe_request["providers"] == {"renamed": expected_provider}


def test_user_configuration_write_rejects_provider_rename_conflict_or_invalid_source_atomically(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    user = home / ".uthcode" / "config.toml"
    user.parent.mkdir(parents=True)
    original = '''default_model = "remote/ref"

[providers.remote]
kind = "fake"

[providers.existing]
kind = "fake"

[models."remote/ref"]
provider = "remote"
remote_id = "remote"
'''
    user.write_text(original, encoding="utf-8")
    original_bytes = user.read_bytes()

    for renames in ({"remote": "existing"}, {"missing": "renamed"}):
        with pytest.raises(ConfigurationError, match="provider rename"):
            write_user_configuration(
                UserConfigurationWriteRequest(provider_renames=renames),
                home=home,
            )
        assert user.read_bytes() == original_bytes

    with pytest.raises(ConfigurationModelError, match="destination IDs"):
        UserConfigurationWriteRequest(provider_renames={"remote": ""})
    assert user.read_bytes() == original_bytes


def test_user_configuration_write_allows_batch_provider_rename_into_released_source(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    user = home / ".uthcode" / "config.toml"
    user.parent.mkdir(parents=True)
    user.write_text(
        '''default_model = "a/ref"

[providers.a]
kind = "fake"

[providers.b]
kind = "fake"

[models."a/ref"]
provider = "a"
remote_id = "a"

[models."b/ref"]
provider = "b"
remote_id = "b"
''',
        encoding="utf-8",
    )

    result = write_user_configuration(
        UserConfigurationWriteRequest(
            default_model="a/ref",
            provider_renames={"a": "x", "b": "a"},
            providers={"x": {"kind": "fake"}, "a": {"kind": "fake"}},
            models={
                "a/ref": {"provider_profile_id": "x", "remote_id": "a"},
                "b/ref": {"provider_profile_id": "a", "remote_id": "b"},
            },
        ),
        home=home,
    )

    rendered = user.read_text(encoding="utf-8")
    assert set(result.providers) == {"a", "x"}
    assert result.models["a/ref"].provider_profile_id == "x"
    assert result.models["b/ref"].provider_profile_id == "a"
    assert result.default_model == "a/ref"
    assert "[providers.b]" not in rendered
    assert "[providers.x]" in rendered
    assert 'provider = "x"' in rendered
    assert 'provider = "a"' in rendered


def test_user_configuration_write_adds_modifies_and_deletes_unreferenced_profiles(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    user = home / ".uthcode" / "config.toml"
    user.parent.mkdir(parents=True)
    user.write_text(
        '''default_model = "keep/ref"
default_permission_mode = "default"

[providers.keep]
kind = "fake"

[providers.remove]
kind = "fake"

[models."keep/ref"]
provider = "keep"
remote_id = "keep-old"
display_name = "Keep old"

[models."remove/ref"]
provider = "remove"
remote_id = "remove"
''',
        encoding="utf-8",
    )

    result = write_user_configuration(
        UserConfigurationWriteRequest(
            default_model="new/ref",
            providers={
                "keep": {"kind": ProviderKind.FAKE},
                "new": {"kind": "fake"},
            },
            models={
                "keep/ref": {
                    "provider_profile_id": "keep",
                    "remote_id": "keep-new",
                    "display_name": "Keep new",
                },
                "new/ref": {
                    "provider_profile_id": "new",
                    "remote_id": "new-remote",
                },
            },
        ),
        home=home,
    )

    assert set(result.providers) == {"keep", "new"}
    assert set(result.models) == {"keep/ref", "new/ref"}
    assert result.default_model == "new/ref"
    assert result.models["keep/ref"].remote_id == "keep-new"
    assert result.models["new/ref"].provider_profile_id == "new"
    rendered = user.read_text(encoding="utf-8")
    assert "remove" not in rendered
    assert 'provider = "new"' in rendered
    assert 'remote_id = "keep-new"' in rendered


def test_user_configuration_write_rejects_deleting_default_model_atomically(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    user = home / ".uthcode" / "config.toml"
    user.parent.mkdir(parents=True)
    user.write_text(
        '''default_model = "keep/ref"
[providers.keep]
kind = "fake"
[models."keep/ref"]
provider = "keep"
remote_id = "keep"
[models."other/ref"]
provider = "keep"
remote_id = "other"
''',
        encoding="utf-8",
    )
    original = user.read_bytes()

    with pytest.raises(ConfigurationError, match="default_model must reference"):
        write_user_configuration(
            UserConfigurationWriteRequest(
                default_model="keep/ref",
                providers={"keep": {"kind": "fake"}},
                models={
                    "other/ref": {
                        "provider_profile_id": "keep",
                        "remote_id": "other",
                    }
                },
            ),
            home=home,
        )

    assert user.read_bytes() == original


def test_user_configuration_write_rejects_invalid_provider_and_model_updates(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    user = home / ".uthcode" / "config.toml"
    user.parent.mkdir(parents=True)
    user.write_text(
        '''default_model = "keep/ref"
[providers.keep]
kind = "fake"
[models."keep/ref"]
provider = "keep"
remote_id = "keep"
''',
        encoding="utf-8",
    )
    original = user.read_bytes()

    with pytest.raises(ConfigurationError, match="invalid Provider profile"):
        write_user_configuration(
            UserConfigurationWriteRequest(
                default_model="keep/ref",
                providers={"keep": {"kind": "not-a-provider"}},
                models={
                    "keep/ref": {
                        "provider_profile_id": "keep",
                        "remote_id": "keep",
                    }
                },
            ),
            home=home,
        )
    assert user.read_bytes() == original

    with pytest.raises(ConfigurationError, match="unknown provider reference"):
        write_user_configuration(
            UserConfigurationWriteRequest(
                default_model="broken/ref",
                providers={"keep": {"kind": "fake"}},
                models={
                    "keep/ref": {
                        "provider_profile_id": "keep",
                        "remote_id": "keep",
                    },
                    "broken/ref": {
                        "provider_profile_id": "missing",
                        "remote_id": "broken",
                    },
                },
            ),
            home=home,
        )
    assert user.read_bytes() == original


def test_user_configuration_write_validates_references_and_full_access(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    user = home / ".uthcode" / "config.toml"
    user.parent.mkdir(parents=True)
    user.write_text(
        '''default_model = "local/ref"
[providers.local]
kind = "fake"
[models."local/ref"]
provider = "local"
remote_id = "remote"
''',
        encoding="utf-8",
    )
    original = user.read_bytes()

    with pytest.raises(ConfigurationError, match="provider reference"):
        write_user_configuration(
            UserConfigurationWriteRequest(
                default_model="local/ref",
                providers={"local": {"kind": "fake"}},
                models={
                    "local/ref": {
                        "provider_profile_id": "missing",
                        "remote_id": "remote",
                    }
                },
            ),
            home=home,
        )
    assert user.read_bytes() == original

    with pytest.raises(ConfigurationError, match="default or auto"):
        write_user_configuration(
            UserConfigurationWriteRequest(
                default_model="local/ref",
                default_permission_mode="full_access",
                providers={"local": {"kind": "fake"}},
                models={
                    "local/ref": {
                        "provider_profile_id": "local",
                        "remote_id": "remote",
                    }
                },
            ),
            home=home,
        )
    assert user.read_bytes() == original


def test_user_configuration_write_rejects_deleting_referenced_provider(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    user = home / ".uthcode" / "config.toml"
    user.parent.mkdir(parents=True)
    user.write_text(
        '''default_model = "local/ref"
[providers.local]
kind = "fake"
[models."local/ref"]
provider = "local"
remote_id = "remote"
''',
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationError, match="provider reference"):
        write_user_configuration(
            UserConfigurationWriteRequest(
                default_model="local/ref",
                providers={},
                models={
                    "local/ref": {
                        "provider_profile_id": "local",
                        "remote_id": "remote",
                    }
                },
            ),
            home=home,
        )


def test_user_configuration_write_failure_is_atomic_and_secret_safe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    user = home / ".uthcode" / "config.toml"
    user.parent.mkdir(parents=True)
    original = '''default_model = "local/ref"
[providers.local]
kind = "fake"
[models."local/ref"]
provider = "local"
remote_id = "remote"
'''
    user.write_text(original, encoding="utf-8")
    secret = "atomic-secret-that-must-not-appear"

    import uthcode.integrations.config.writer as writer

    def fail_replace(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated atomic replace failure")

    monkeypatch.setattr(writer.os, "replace", fail_replace)
    with pytest.raises(OSError, match="simulated atomic replace failure") as raised:
        write_user_configuration(
            UserConfigurationWriteRequest(
                default_model="local/ref",
                providers={
                    "local": {"kind": "fake", "api_key": secret},
                },
                models={
                    "local/ref": {
                        "provider_profile_id": "local",
                        "remote_id": "remote",
                    }
                },
            ),
            home=home,
        )

    assert secret not in str(raised.value)
    assert user.read_text(encoding="utf-8") == original
    assert not list(user.parent.glob(".*.tmp"))


def test_user_configuration_write_rejects_unknown_request_fields(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"

    with pytest.raises(ConfigurationError, match="unsupported configuration field"):
        write_user_configuration(
            {
                "default_model": "local/ref",
                "future_setting": "must-not-be-ignored",
            },
            home=home,
        )

    assert not (home / ".uthcode" / "config.toml").exists()


def test_invalid_first_write_does_not_create_a_partial_config(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"

    with pytest.raises(ConfigurationError, match="default_model"):
        write_user_configuration(
            UserConfigurationWriteRequest(
                default_model="missing/ref",
                providers={"local": {"kind": "fake"}},
                models={
                    "local/ref": {
                        "provider_profile_id": "local",
                        "remote_id": "remote",
                    }
                },
            ),
            home=home,
        )

    assert not (home / ".uthcode" / "config.toml").exists()


def test_valid_first_write_reloads_and_constructs_application(tmp_path: Path) -> None:
    home = tmp_path / "home"

    written = write_user_configuration(
        UserConfigurationWriteRequest(
            default_model="local/ref",
            default_permission_mode="auto",
            providers={"local": {"kind": ProviderKind.FAKE}},
            models={
                "local/ref": {
                    "provider_profile_id": "local",
                    "remote_id": "remote",
                    "display_name": "Local",
                }
            },
        ),
        home=home,
    )

    assert written.default_model == "local/ref"
    config = load_effective_config(cwd=tmp_path, home=home)
    assert isinstance(config, EffectiveConfig)
    assert config.default_model == "local/ref"
    assert config.default_permission_mode.value == "auto"

    application = create_application(
        config,
        storage_root=tmp_path / "sessions",
    )
    try:
        assert application.configuration is config
    finally:
        application.close()
