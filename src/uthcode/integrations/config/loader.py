"""Discover, validate, and merge configuration files."""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from tomlkit import parse

from .data import LoadedConfigData, LoadedConfigSource
from .template import create_user_template


class ConfigurationError(ValueError):
    """A configuration file cannot be safely used."""

    def __init__(
        self,
        message: str,
        *,
        path: Path | None = None,
        field: str | None = None,
    ) -> None:
        self.message = message
        self.path = path
        self.field = field
        parts = []
        if path is not None:
            parts.append(str(path))
        if field is not None:
            parts.append(field)
        prefix = ": ".join(parts)
        super().__init__(f"{prefix}: {message}" if prefix else message)


class ConfigurationInitializationRequired(ConfigurationError):
    """The user configuration template must be enabled and filled in."""

    def __init__(self, path: Path) -> None:
        self.template_path = path
        super().__init__(
            "configuration is not initialized; edit and uncomment one complete "
            "Provider and Model example, then run again",
            path=path,
        )


_ROOT_FIELDS = frozenset({"model", "providers", "models"})
_PROVIDER_FIELDS = frozenset({"kind", "base_url", "api_key_env"})
_MODEL_FIELDS = frozenset({"provider", "model", "label", "max_output_tokens"})
_SUPPORTED_PROVIDER_KINDS = frozenset(
    {"fake", "anthropic", "openai_responses", "openai_compat"}
)
_PROJECT_FORBIDDEN_FIELDS = frozenset(
    {
        "providers",
        "provider",
        "kind",
        "base_url",
        "url",
        "endpoint",
        "api_key",
        "api_key_env",
        "secret",
        "secret_env",
        "secret_source",
        "credential",
        "credentials",
        "credential_env",
        "credential_source",
        "auth",
        "authorization",
        "headers",
    }
)


def _physical_path(path: str | os.PathLike[str] | Path) -> Path:
    resolved = Path(path).expanduser().resolve(strict=False)
    return Path(os.path.normpath(str(resolved)))


def _path_key(path: Path) -> str:
    return os.path.normcase(os.path.normpath(str(path)))


def _user_home(explicit: Path | None) -> Path:
    if explicit is not None:
        return _physical_path(explicit)
    for name in ("HOME", "USERPROFILE"):
        value = os.getenv(name)
        if value:
            return _physical_path(value)
    drive = os.getenv("HOMEDRIVE", "")
    tail = os.getenv("HOMEPATH", "")
    if drive and tail:
        return _physical_path(drive + tail)
    return _physical_path(Path.home())


def _git_root(cwd: Path) -> Path | None:
    for directory in (cwd, *cwd.parents):
        marker = directory / ".git"
        if marker.is_dir() or marker.is_file():
            return directory
    return None


def _project_directories(cwd: Path) -> tuple[Path, ...]:
    root = _git_root(cwd)
    if root is None:
        return (cwd,)
    chain: list[Path] = []
    directory = cwd
    while True:
        chain.append(directory)
        if directory == root:
            break
        parent = directory.parent
        if parent == directory:
            break
        directory = parent
    chain.reverse()
    return tuple(chain)


def discover_config_paths(
    cwd: str | os.PathLike[str] | Path,
    user_config: str | os.PathLike[str] | Path,
) -> tuple[tuple[str, Path], ...]:
    """Return unique existing files in user-to-cwd precedence order."""

    cwd_path = _physical_path(cwd)
    candidates: list[tuple[str, Path]] = []
    seen: set[str] = set()

    def add(kind: str, candidate: Path) -> None:
        physical = _physical_path(candidate)
        if not physical.is_file():
            return
        key = _path_key(physical)
        if key in seen:
            return
        seen.add(key)
        candidates.append((kind, physical))

    add("user", _physical_path(user_config))
    for directory in _project_directories(cwd_path):
        add("project", directory / ".uthcode" / "config.toml")
    return tuple(candidates)


def _plain(value: Any) -> Any:
    unwrap = getattr(value, "unwrap", None)
    if callable(unwrap):
        value = unwrap()
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_plain(item) for item in value]
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    return value


def _read_mapping(path: Path) -> dict[str, Any]:
    try:
        document = parse(path.read_text(encoding="utf-8"))
        plain = _plain(document)
    except Exception:
        raise ConfigurationError("configuration cannot be parsed", path=path) from None
    if not isinstance(plain, dict):
        raise ConfigurationError("configuration root must be a table", path=path)
    return plain


def _require_table(value: Any, *, path: Path, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ConfigurationError("value must be a table", path=path, field=field)
    return value


def _credential_like(field: str) -> bool:
    normalized = field.casefold()
    if normalized in _PROJECT_FORBIDDEN_FIELDS:
        return True
    return normalized.endswith(
        (
            "_key",
            "_key_env",
            "_secret",
            "_secret_env",
            "_secret_source",
            "_credential",
            "_credential_env",
            "_credential_source",
            "_token",
            "_token_env",
        )
    )


def _check_fields(
    mapping: Mapping[str, Any],
    *,
    allowed: frozenset[str],
    path: Path,
    prefix: str,
    project: bool = False,
) -> None:
    for key in mapping:
        if not isinstance(key, str):
            raise ConfigurationError("field names must be strings", path=path, field=prefix)
        if key in allowed:
            continue
        if project and _credential_like(key):
            raise ConfigurationError(
                "project configuration cannot define Provider or credential data",
                path=path,
                field=f"{prefix}.{key}",
            )
        raise ConfigurationError(
            "unsupported configuration field",
            path=path,
            field=f"{prefix}.{key}",
        )


def _validate_root(mapping: Mapping[str, Any], *, path: Path, project: bool) -> None:
    for key in mapping:
        if key in _ROOT_FIELDS:
            continue
        if project and _credential_like(str(key)):
            raise ConfigurationError(
                "project configuration cannot define Provider or credential data",
                path=path,
                field=str(key),
            )
        raise ConfigurationError(
            "unsupported configuration field",
            path=path,
            field=str(key),
        )
    if project and "providers" in mapping:
        raise ConfigurationError(
            "project configuration cannot define providers",
            path=path,
            field="providers",
        )


def _validate_provider_tables(mapping: Mapping[str, Any], *, path: Path) -> None:
    raw_providers = _require_table(mapping.get("providers", {}), path=path, field="providers")
    for profile_id, raw_profile in raw_providers.items():
        field = f"providers.{profile_id}"
        profile = _require_table(raw_profile, path=path, field=field)
        _check_fields(
            profile,
            allowed=_PROVIDER_FIELDS,
            path=path,
            prefix=field,
        )


def _validate_model_tables(
    mapping: Mapping[str, Any],
    *,
    path: Path,
    project: bool,
) -> None:
    raw_models = _require_table(mapping.get("models", {}), path=path, field="models")
    for model_ref, raw_profile in raw_models.items():
        field = f"models.{model_ref}"
        profile = _require_table(raw_profile, path=path, field=field)
        _check_fields(
            profile,
            allowed=_MODEL_FIELDS,
            path=path,
            prefix=field,
            project=project,
        )
        if project:
            for key in profile:
                if key in _MODEL_FIELDS:
                    continue
                if _credential_like(key) or key == "kind":
                    raise ConfigurationError(
                        "project configuration cannot define Provider or credential data",
                        path=path,
                        field=f"{field}.{key}",
                    )


def _validate_user_mapping(mapping: Mapping[str, Any], *, path: Path) -> None:
    _validate_root(mapping, path=path, project=False)
    _validate_provider_tables(mapping, path=path)
    _validate_model_tables(mapping, path=path, project=False)


def _validate_project_mapping(mapping: Mapping[str, Any], *, path: Path) -> None:
    _validate_root(mapping, path=path, project=True)
    _validate_model_tables(mapping, path=path, project=True)


def _provider_profiles(
    mapping: Mapping[str, Any],
    *,
    path: Path,
) -> dict[str, dict[str, object]]:
    raw_providers = _require_table(mapping.get("providers", {}), path=path, field="providers")
    result: dict[str, dict[str, object]] = {}
    for profile_id, raw_profile in raw_providers.items():
        if not isinstance(profile_id, str):
            raise ConfigurationError("Provider Profile IDs must be strings", path=path, field="providers")
        profile = _require_table(
            raw_profile,
            path=path,
            field=f"providers.{profile_id}",
        )
        kind = profile.get("kind")
        base_url = profile.get("base_url")
        api_key_env = profile.get("api_key_env")
        if (
            not isinstance(kind, str)
            or not kind.strip()
            or kind.strip().lower() not in _SUPPORTED_PROVIDER_KINDS
            or (base_url is not None and (not isinstance(base_url, str) or not base_url.strip()))
            or (
                api_key_env is not None
                and (not isinstance(api_key_env, str) or not api_key_env.strip())
            )
            or (
                kind.strip().lower() != "fake"
                and (not isinstance(api_key_env, str) or not api_key_env.strip())
            )
            or (
                kind.strip().lower() == "openai_compat"
                and (not isinstance(base_url, str) or not base_url.strip())
            )
        ):
            raise ConfigurationError(
                "invalid Provider profile",
                path=path,
                field=f"providers.{profile_id}",
            )
        raw: dict[str, object] = {"kind": kind}
        if "base_url" in profile:
            raw["base_url"] = base_url
        if "api_key_env" in profile:
            raw["api_key_env"] = api_key_env
        result[profile_id] = raw
    return result


def _model_tables(mapping: Mapping[str, Any], *, path: Path) -> dict[str, dict[str, Any]]:
    raw_models = _require_table(mapping.get("models", {}), path=path, field="models")
    result: dict[str, dict[str, Any]] = {}
    for model_ref, raw_profile in raw_models.items():
        if not isinstance(model_ref, str):
            raise ConfigurationError("Model Refs must be strings", path=path, field="models")
        profile = _require_table(
            raw_profile,
            path=path,
            field=f"models.{model_ref}",
        )
        result[model_ref] = dict(profile)
    return result


def _model_profiles(
    raw_models: Mapping[str, Mapping[str, Any]],
    *,
    path: Path,
) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for model_ref, raw_profile in raw_models.items():
        provider_profile_id = raw_profile.get("provider")
        remote_model_id = raw_profile.get("model")
        label = raw_profile.get("label")
        max_output_tokens = raw_profile.get("max_output_tokens")
        if (
            not isinstance(model_ref, str)
            or not model_ref.strip()
            or not isinstance(provider_profile_id, str)
            or not provider_profile_id.strip()
            or not isinstance(remote_model_id, str)
            or not remote_model_id.strip()
            or (label is not None and (not isinstance(label, str) or not label.strip()))
            or (
                max_output_tokens is not None
                and (
                    isinstance(max_output_tokens, bool)
                    or not isinstance(max_output_tokens, int)
                    or max_output_tokens <= 0
                )
            )
        ):
            raise ConfigurationError(
                "invalid Model profile",
                path=path,
                field=f"models.{model_ref}",
            )
        raw: dict[str, object] = {
            "provider_profile_id": provider_profile_id,
            "remote_model_id": remote_model_id,
        }
        if "label" in raw_profile:
            raw["label"] = label
        if "max_output_tokens" in raw_profile:
            raw["max_output_tokens"] = max_output_tokens
        result[model_ref] = raw
    return result


def _merge_models(
    target: dict[str, dict[str, Any]],
    overlay: Mapping[str, Any],
    *,
    path: Path,
) -> None:
    for model_ref, raw_profile in _model_tables(overlay, path=path).items():
        current = target.setdefault(model_ref, {})
        current.update(raw_profile)


def load_config_data(
    *,
    cwd: str | os.PathLike[str] | Path | None = None,
    home: str | os.PathLike[str] | Path | None = None,
    model: str | None = None,
) -> LoadedConfigData:
    """Load immutable raw configuration data without constructing Application objects."""

    cwd_path = _physical_path(cwd or Path.cwd())
    home_path = _user_home(_physical_path(home) if home is not None else None)
    user_config = _physical_path(home_path / ".uthcode" / "config.toml")
    if not user_config.is_file():
        try:
            created = create_user_template(user_config)
        except Exception:
            raise ConfigurationError(
                "user configuration is missing and its template could not be created",
                path=user_config,
            ) from None
        raise ConfigurationInitializationRequired(created)

    paths = discover_config_paths(cwd_path, user_config)
    if not paths or paths[0][0] != "user":
        raise ConfigurationError("user configuration was not discovered", path=user_config)

    user_kind, user_path = paths[0]
    del user_kind
    user_mapping = _read_mapping(user_path)
    if not user_mapping:
        raise ConfigurationInitializationRequired(user_path)
    _validate_user_mapping(user_mapping, path=user_path)
    providers = _provider_profiles(user_mapping, path=user_path)
    models = _model_tables(user_mapping, path=user_path)
    selected_ref = user_mapping.get("model")
    sources = [LoadedConfigSource("user", user_path)]

    for kind, path in paths[1:]:
        project_mapping = _read_mapping(path)
        _validate_project_mapping(project_mapping, path=path)
        _merge_models(models, project_mapping, path=path)
        if "model" in project_mapping:
            selected_ref = project_mapping["model"]
        sources.append(LoadedConfigSource(kind, path))

    if model is not None:
        selected_ref = model
        sources.append(LoadedConfigSource("cli"))
    if not isinstance(selected_ref, str) or not selected_ref.strip():
        raise ConfigurationError(
            "configuration requires a selected model",
            path=user_path,
            field="model",
        )

    return LoadedConfigData(
        model=selected_ref,
        providers=providers,
        models=_model_profiles(models, path=user_path),
        sources=tuple(sources),
    )


__all__ = [
    "ConfigurationError",
    "ConfigurationInitializationRequired",
    "discover_config_paths",
    "load_config_data",
]
