"""Discover, validate, and merge configuration files."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from tomlkit import parse

from .data import LoadedConfigData, LoadedConfigSource
from .template import create_user_template
from uthcode.core.secrets import SecretValue


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
            "configuration is not initialized; fill one complete Provider and "
            "Model slot, set default_model, then run again",
            path=path,
        )


_ROOT_FIELDS = frozenset({"default_model", "providers", "models", "default_permission_mode"})
_PROVIDER_FIELDS = frozenset({"kind", "base_url", "api_key", "display_name"})
_MODEL_FIELDS = frozenset(
    {
        "provider",
        "remote_id",
        "display_name",
        "context_window",
        "max_output_tokens",
        "reasoning_effort",
    }
)
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
_REASONING_EFFORTS = frozenset(
    {"none", "minimal", "low", "medium", "high", "xhigh", "max"}
)
_ENVIRONMENT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


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


def physical_path(path: str | os.PathLike[str] | Path) -> Path:
    """Return the shared lexical-normalized physical path representation."""

    return _physical_path(path)


def resolve_user_home(explicit: Path | None = None) -> Path:
    """Resolve the user home using the same configuration discovery rules."""

    return _user_home(explicit)


def discover_scoped_paths(
    cwd: str | os.PathLike[str] | Path,
    user_path: str | os.PathLike[str] | Path,
    project_relative_path: str | os.PathLike[str] | Path,
) -> tuple[tuple[str, Path], ...]:
    """Discover one user file and recursive project files in stable order.

    The helper is shared by ordinary configuration and permission rules.  It
    intentionally owns the only Git-root-to-cwd traversal in the Integration
    layer; callers supply only the file name that lives below each project.
    Results are ordered from the least-specific user source to the
    root-to-cwd project sources and are deduplicated by physical path.
    """

    relative = Path(project_relative_path)
    if relative.is_absolute():
        raise ValueError("project_relative_path must be relative")

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

    add("user", _physical_path(user_path))
    for directory in _project_directories(cwd_path):
        add("project", directory / relative)
    return tuple(candidates)


def discover_config_paths(
    cwd: str | os.PathLike[str] | Path,
    user_config: str | os.PathLike[str] | Path,
) -> tuple[tuple[str, Path], ...]:
    """Return unique existing files in user-to-cwd precedence order."""

    return discover_scoped_paths(cwd, user_config, ".uthcode/config.toml")


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
    if project and "default_permission_mode" in mapping:
        raise ConfigurationError(
            "project configuration cannot define default_permission_mode",
            path=path,
            field="default_permission_mode",
        )
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


def _safe_user_mapping(mapping: Mapping[str, Any]) -> dict[str, Any]:
    """Project a parsed user config to current fields without credentials."""

    result: dict[str, Any] = {}
    for key in ("default_model", "default_permission_mode"):
        if key in mapping:
            result[key] = mapping[key]

    raw_providers = mapping.get("providers", {})
    safe_providers: dict[str, dict[str, Any]] = {}
    if isinstance(raw_providers, Mapping):
        for profile_id, raw_profile in raw_providers.items():
            if not isinstance(profile_id, str):
                continue
            profile = raw_profile if isinstance(raw_profile, Mapping) else {}
            safe: dict[str, Any] = {
                "provider_profile_id": profile_id,
                "kind": profile.get("kind"),
                "base_url": profile.get("base_url"),
                "display_name": profile.get("display_name"),
                "api_key_configured": (
                    isinstance(profile.get("api_key"), str)
                    and bool(profile.get("api_key", "").strip())
                ),
            }
            safe_providers[profile_id] = safe
    result["providers"] = safe_providers

    raw_models = mapping.get("models", {})
    safe_models: dict[str, dict[str, Any]] = {}
    if isinstance(raw_models, Mapping):
        for model_ref, raw_profile in raw_models.items():
            if not isinstance(model_ref, str):
                continue
            profile = raw_profile if isinstance(raw_profile, Mapping) else {}
            safe_models[model_ref] = {
                "model_ref": model_ref,
                # provider is the TOML spelling.  The Application DTO
                # performs the explicit translation to provider_profile_id.
                "provider_profile_id": profile.get("provider"),
                "remote_id": profile.get("remote_id"),
                "display_name": profile.get("display_name"),
                "context_window": profile.get("context_window"),
                "max_output_tokens": profile.get("max_output_tokens"),
                "reasoning_effort": profile.get("reasoning_effort"),
            }
    result["models"] = safe_models
    return result


def read_user_config_view_data(
    path: str | os.PathLike[str] | Path,
    *,
    create_if_missing: bool = False,
) -> Mapping[str, Any]:
    """Read only display-safe current-schema user configuration fields.

    This function intentionally never resolves or returns an API key.  A
    missing file is created only when explicitly requested by the Application
    bootstrap use case.
    """

    target = _physical_path(path)
    if not target.is_file():
        if not create_if_missing:
            raise ConfigurationError("user configuration was not found", path=target)
        try:
            create_user_template(target)
        except Exception:
            raise ConfigurationError(
                "user configuration is missing and its template could not be created",
                path=target,
            ) from None
    return _safe_user_mapping(_read_mapping(target))


def read_user_config_api_key(
    path: str | os.PathLike[str] | Path,
    provider_profile_id: str,
) -> str | None:
    """Read one saved user-level API key expression without resolving it.

    This is intentionally separate from the display-safe configuration view
    and from normal Provider loading.  A literal is returned as written;
    ``env:NAME`` is returned as the configured reference and is never looked
    up in the process environment.  Callers must provide the Provider
    identity explicitly so this helper cannot enumerate or return other
    profiles.
    """

    target = _physical_path(path)
    if not isinstance(provider_profile_id, str) or not provider_profile_id.strip():
        raise ConfigurationError(
            "provider profile id must be a non-empty string",
            path=target,
            field="provider_profile_id",
        )
    if not target.is_file():
        raise ConfigurationError("user configuration was not found", path=target)
    mapping = _read_mapping(target)
    raw_providers = _require_table(mapping.get("providers", {}), path=target, field="providers")
    raw_profile = raw_providers.get(provider_profile_id)
    if raw_profile is None:
        raise ConfigurationError(
            "Provider profile was not found",
            path=target,
            field=f"providers.{provider_profile_id}",
        )
    profile = _require_table(
        raw_profile,
        path=target,
        field=f"providers.{provider_profile_id}",
    )
    value = profile.get("api_key")
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    # Reuse syntax validation only; unlike normal config loading this does not
    # read an environment variable or construct SecretValue.
    _validate_api_key_expression(
        value,
        path=target,
        field=f"providers.{provider_profile_id}.api_key",
    )
    assert isinstance(value, str)
    return value


def _blank(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def validate_user_config_mapping(
    mapping: Mapping[str, Any],
    *,
    path: str | os.PathLike[str] | Path,
    resolve_secrets: bool = True,
) -> LoadedConfigData:
    """Validate one complete user mapping without reading project config.

    Normal loading resolves configured credentials.  The atomic writer can
    pass ``resolve_secrets=False`` to validate a candidate's credential
    expression without requiring an ``env:`` variable to exist during an
    edit.
    """

    target = _physical_path(path)
    if not isinstance(mapping, Mapping):
        raise ConfigurationError("configuration root must be a table", path=target)
    if not mapping:
        raise ConfigurationInitializationRequired(target)
    _validate_user_mapping(mapping, path=target)
    default_permission_mode = mapping.get("default_permission_mode", "default")
    if default_permission_mode not in {"default", "auto"}:
        raise ConfigurationError(
            "default_permission_mode must be default or auto",
            path=target,
            field="default_permission_mode",
        )
    providers = _provider_profiles(
        mapping,
        path=target,
        resolve_secrets=resolve_secrets,
    )
    models = _model_tables(mapping, path=target)
    selected_ref = mapping.get("default_model")
    if not providers and not models and _blank(selected_ref):
        raise ConfigurationInitializationRequired(target)
    if not isinstance(selected_ref, str) or not selected_ref.strip():
        raise ConfigurationError(
            "configuration requires a default_model",
            path=target,
            field="default_model",
        )
    canonical_models = _model_profiles(models, path=target)
    if selected_ref not in canonical_models:
        raise ConfigurationError(
            "default_model must reference an enabled Model profile",
            path=target,
            field="default_model",
        )
    for model_ref, profile in canonical_models.items():
        provider_profile_id = profile["provider_profile_id"]
        if provider_profile_id not in providers:
            raise ConfigurationError(
                "unknown provider reference",
                path=target,
                field=f"models.{model_ref}.provider",
            )
        reasoning_effort = profile.get("reasoning_effort")
        provider = providers[provider_profile_id]
        provider_kind = provider.get("kind")
        if (
            reasoning_effort is not None
            and reasoning_effort != "none"
            and provider_kind
            not in {"fake", "openai_responses", "openai_compat"}
        ):
            raise ConfigurationError(
                f"Provider {provider_profile_id!r} does not support reasoning_effort",
                path=target,
                field=f"models.{model_ref}.reasoning_effort",
            )
    return LoadedConfigData(
        default_model=selected_ref,
        providers=providers,
        models=canonical_models,
        sources=(LoadedConfigSource("user", target),),
        default_permission_mode=default_permission_mode,
    )


def _resolve_api_key(value: object, *, path: Path, field: str) -> SecretValue | None:
    """Parse one user-only credential expression without exposing its value."""

    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if not isinstance(value, str):
        raise ConfigurationError("api_key must be a string", path=path, field=field)
    if value.startswith("env:"):
        name = value[4:]
        if _ENVIRONMENT_NAME.fullmatch(name) is None:
            raise ConfigurationError(
                "api_key environment variable name is invalid",
                path=path,
                field=field,
            )
        secret = os.environ.get(name)
        if not secret or not secret.strip():
            raise ConfigurationError(
                "api_key environment variable is missing or empty",
                path=path,
                field=field,
            )
        return SecretValue(secret)
    return SecretValue(value)


def _validate_api_key_expression(
    value: object,
    *,
    path: Path,
    field: str,
) -> bool:
    """Validate key syntax without reading a literal or environment value."""

    if value is None or (isinstance(value, str) and not value.strip()):
        return False
    if not isinstance(value, str):
        raise ConfigurationError("api_key must be a string", path=path, field=field)
    if value.startswith("env:") and _ENVIRONMENT_NAME.fullmatch(value[4:]) is None:
        raise ConfigurationError(
            "api_key environment variable name is invalid",
            path=path,
            field=field,
        )
    return True


def _provider_profiles(
    mapping: Mapping[str, Any],
    *,
    path: Path,
    resolve_secrets: bool = True,
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
        display_name = profile.get("display_name")
        api_key_value = profile.get("api_key")
        if _blank(kind) and _blank(api_key_value) and _blank(base_url):
            continue
        if (
            not isinstance(kind, str)
            or not kind.strip()
            or kind.strip().lower() not in _SUPPORTED_PROVIDER_KINDS
            or (base_url is not None and (not isinstance(base_url, str) or not base_url.strip()))
            or (
                display_name is not None
                and (not isinstance(display_name, str) or not display_name.strip())
            )
        ):
            raise ConfigurationError(
                "invalid Provider profile",
                path=path,
                field=f"providers.{profile_id}",
            )
        if resolve_secrets:
            api_key = _resolve_api_key(
                api_key_value,
                path=path,
                field=f"providers.{profile_id}.api_key",
            )
            api_key_configured = api_key is not None
        else:
            api_key = None
            api_key_configured = _validate_api_key_expression(
                api_key_value,
                path=path,
                field=f"providers.{profile_id}.api_key",
            )
        if kind.strip().lower() != "fake" and not api_key_configured:
            raise ConfigurationError(
                "real Provider requires a non-empty api_key",
                path=path,
                field=f"providers.{profile_id}.api_key",
            )
        if kind.strip().lower() == "openai_compat" and not isinstance(base_url, str):
            raise ConfigurationError(
                "OpenAI-compatible Provider requires base_url",
                path=path,
                field=f"providers.{profile_id}.base_url",
            )
        raw: dict[str, object] = {"kind": kind}
        if "display_name" in profile:
            raw["display_name"] = display_name
        if "base_url" in profile:
            raw["base_url"] = base_url
        if api_key is not None:
            raw["api_key"] = api_key
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
        if all(
            _blank(profile.get(key))
            for key in (
                "provider",
                "remote_id",
                "display_name",
                "context_window",
                "max_output_tokens",
                "reasoning_effort",
            )
        ):
            continue
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
        remote_id = raw_profile.get("remote_id")
        display_name = raw_profile.get("display_name")
        context_window = raw_profile.get("context_window")
        max_output_tokens = raw_profile.get("max_output_tokens")
        reasoning_effort = raw_profile.get("reasoning_effort")
        if (
            not isinstance(model_ref, str)
            or not model_ref.strip()
            or not isinstance(provider_profile_id, str)
            or not provider_profile_id.strip()
            or not isinstance(remote_id, str)
            or not remote_id.strip()
            or (
                display_name is not None
                and (not isinstance(display_name, str) or not display_name.strip())
            )
            or (
                max_output_tokens is not None
                and (
                    isinstance(max_output_tokens, bool)
                    or not isinstance(max_output_tokens, int)
                    or max_output_tokens <= 0
                )
            )
            or (
                context_window is not None
                and (
                    isinstance(context_window, bool)
                    or not isinstance(context_window, int)
                    or context_window <= 0
                )
            )
            or (
                reasoning_effort is not None
                and (
                    not isinstance(reasoning_effort, str)
                    or reasoning_effort not in _REASONING_EFFORTS
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
            "remote_id": remote_id,
        }
        if "display_name" in raw_profile:
            raw["display_name"] = display_name
        if "context_window" in raw_profile:
            raw["context_window"] = context_window
        if "max_output_tokens" in raw_profile:
            raw["max_output_tokens"] = max_output_tokens
        if "reasoning_effort" in raw_profile:
            raw["reasoning_effort"] = reasoning_effort
        result[model_ref] = raw
    return result


def _merge_models(
    target: dict[str, dict[str, Any]],
    overlay: Mapping[str, Any],
    *,
    path: Path,
    user_models: Mapping[str, Mapping[str, Any]] | None = None,
) -> None:
    project = user_models is not None
    for model_ref, raw_profile in _model_tables(overlay, path=path).items():
        if project and "context_window" in raw_profile:
            user_profile = user_models.get(model_ref, {})
            user_limit = user_profile.get("context_window")
            project_limit = raw_profile.get("context_window")
            if user_limit is None:
                raise ConfigurationError(
                    "project context_window cannot create a missing user limit",
                    path=path,
                    field=f"models.{model_ref}.context_window",
                )
            if (
                isinstance(user_limit, bool)
                or not isinstance(user_limit, int)
                or user_limit <= 0
            ):
                raise ConfigurationError(
                    "user context_window is invalid",
                    path=path,
                    field=f"models.{model_ref}.context_window",
                )
            if (
                isinstance(project_limit, bool)
                or not isinstance(project_limit, int)
                or project_limit <= 0
            ):
                raise ConfigurationError(
                    "context_window must be a positive integer",
                    path=path,
                    field=f"models.{model_ref}.context_window",
                )
            if project_limit > user_limit:
                raise ConfigurationError(
                    "project context_window cannot expand the user limit",
                    path=path,
                    field=f"models.{model_ref}.context_window",
                )
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
    default_permission_mode = user_mapping.get("default_permission_mode", "default")
    if default_permission_mode not in {"default", "auto"}:
        raise ConfigurationError(
            "default_permission_mode must be default or auto",
            path=user_path,
            field="default_permission_mode",
        )
    providers = _provider_profiles(user_mapping, path=user_path)
    models = _model_tables(user_mapping, path=user_path)
    user_models = {key: dict(value) for key, value in models.items()}
    selected_ref = user_mapping.get("default_model")
    if not providers and not models and _blank(selected_ref):
        raise ConfigurationInitializationRequired(user_path)
    sources = [LoadedConfigSource("user", user_path)]

    for kind, path in paths[1:]:
        project_mapping = _read_mapping(path)
        _validate_project_mapping(project_mapping, path=path)
        _merge_models(models, project_mapping, path=path, user_models=user_models)
        if "default_model" in project_mapping:
            selected_ref = project_mapping["default_model"]
        sources.append(LoadedConfigSource(kind, path))

    if model is not None:
        selected_ref = model
        sources.append(LoadedConfigSource("cli"))
    if not isinstance(selected_ref, str) or not selected_ref.strip():
        raise ConfigurationError(
            "configuration requires a default_model",
            path=user_path,
            field="default_model",
        )

    canonical_models = _model_profiles(models, path=user_path)
    if selected_ref not in canonical_models:
        raise ConfigurationError(
            "default_model must reference an enabled Model profile",
            path=user_path,
            field="default_model",
        )

    return LoadedConfigData(
        default_model=selected_ref,
        providers=providers,
        models=canonical_models,
        sources=tuple(sources),
        default_permission_mode=default_permission_mode,
    )


__all__ = [
    "ConfigurationError",
    "ConfigurationInitializationRequired",
    "discover_config_paths",
    "discover_scoped_paths",
    "load_config_data",
    "physical_path",
    "read_user_config_api_key",
    "read_user_config_view_data",
    "resolve_user_home",
    "validate_user_config_mapping",
]
