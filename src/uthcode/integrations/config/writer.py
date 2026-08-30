"""TOMLKit-backed atomic writes for the supported user configuration schema."""

from __future__ import annotations

import os
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from tomlkit import dumps, parse
from tomlkit import table as toml_table

from .loader import (
    ConfigurationError,
    _plain,
    validate_user_config_mapping,
)
from .template import USER_CONFIG_TEMPLATE


_ROOT_FIELDS = frozenset(
    {"default_model", "default_permission_mode", "providers", "models"}
)
_PAYLOAD_FIELDS = _ROOT_FIELDS | {"provider_renames"}
_PROVIDER_FIELDS = frozenset({"kind", "base_url", "api_key"})
_MODEL_FIELDS = frozenset(
    {
        "provider_profile_id",
        "remote_id",
        "display_name",
        "context_window",
        "max_output_tokens",
        "reasoning_effort",
    }
)


def _chmod_private(path: Path) -> None:
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _atomic_write(path: Path, rendered: str) -> Path:
    """Replace one file through a same-filesystem, fsynced temporary file."""

    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(rendered)
            handle.flush()
            os.fsync(handle.fileno())
        _chmod_private(temporary)
        os.replace(temporary, path)
        _chmod_private(path)
    except Exception:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise
    return path


def _parse_document(path: Path) -> Any:
    try:
        return parse(path.read_text(encoding="utf-8"))
    except Exception:
        raise ConfigurationError("configuration cannot be parsed", path=path) from None


def _validate_existing_schema(mapping: Mapping[str, Any], *, path: Path) -> None:
    """Reject unknown fields before a requested rewrite can carry them forward."""

    for key in mapping:
        if key not in _ROOT_FIELDS:
            raise ConfigurationError(
                "unsupported configuration field",
                path=path,
                field=str(key),
            )
    providers = mapping.get("providers", {})
    if isinstance(providers, Mapping):
        for profile_id, profile in providers.items():
            if not isinstance(profile_id, str):
                raise ConfigurationError(
                    "Provider Profile IDs must be strings",
                    path=path,
                    field="providers",
                )
            if not isinstance(profile, Mapping):
                continue
            for key in profile:
                if key not in _PROVIDER_FIELDS:
                    raise ConfigurationError(
                        "unsupported configuration field",
                        path=path,
                        field=f"providers.{profile_id}.{key}",
                    )
    models = mapping.get("models", {})
    if isinstance(models, Mapping):
        for model_ref, profile in models.items():
            if not isinstance(model_ref, str):
                raise ConfigurationError(
                    "Model Refs must be strings",
                    path=path,
                    field="models",
                )
            if not isinstance(profile, Mapping):
                continue
            for key in profile:
                if key not in {
                    "provider",
                    "remote_id",
                    "display_name",
                    "context_window",
                    "max_output_tokens",
                    "reasoning_effort",
                }:
                    raise ConfigurationError(
                        "unsupported configuration field",
                        path=path,
                        field=f"models.{model_ref}.{key}",
                    )


def _validate_payload_shape(payload: Mapping[str, Any], *, path: Path) -> None:
    for key in payload:
        if key not in _PAYLOAD_FIELDS:
            raise ConfigurationError(
                "unsupported configuration field",
                path=path,
                field=str(key),
            )
    renames = payload.get("provider_renames")
    if renames is not None:
        if not isinstance(renames, Mapping):
            raise ConfigurationError(
                "value must be a mapping",
                path=path,
                field="provider_renames",
            )
        destinations: set[str] = set()
        for old_id, new_id in renames.items():
            if (
                not isinstance(old_id, str)
                or not old_id.strip()
                or not isinstance(new_id, str)
                or not new_id.strip()
            ):
                raise ConfigurationError(
                    "provider rename IDs must be non-empty strings",
                    path=path,
                    field="provider_renames",
                )
            if old_id == new_id:
                raise ConfigurationError(
                    "provider rename source and destination must differ",
                    path=path,
                    field=f"provider_renames.{old_id}",
                )
            if new_id in destinations:
                raise ConfigurationError(
                    "provider rename destinations must be unique",
                    path=path,
                    field=f"provider_renames.{old_id}",
                )
            destinations.add(new_id)
    for section_name, allowed in (
        ("providers", _PROVIDER_FIELDS),
        ("models", _MODEL_FIELDS),
    ):
        if section_name not in payload or payload[section_name] is None:
            continue
        section = payload[section_name]
        if not isinstance(section, Mapping):
            raise ConfigurationError(
                "value must be a table",
                path=path,
                field=section_name,
            )
        for profile_id, profile in section.items():
            if not isinstance(profile_id, str) or not profile_id.strip():
                raise ConfigurationError(
                    "profile IDs must be non-empty strings",
                    path=path,
                    field=section_name,
                )
            if not isinstance(profile, Mapping):
                raise ConfigurationError(
                    "value must be a table",
                    path=path,
                    field=f"{section_name}.{profile_id}",
                )
            for key in profile:
                if key not in allowed:
                    raise ConfigurationError(
                        "unsupported configuration field",
                        path=path,
                        field=f"{section_name}.{profile_id}.{key}",
                    )


def _replace_or_get_table(document: Any, name: str) -> Any:
    current = document.get(name)
    if not isinstance(current, Mapping):
        current = toml_table()
        document[name] = current
    return current


def _delete_missing_profiles(section: Any, requested: Mapping[str, Any]) -> None:
    for profile_id in tuple(section.keys()):
        if profile_id not in requested:
            del section[profile_id]


def _set_or_delete(table: Any, key: str, value: object) -> None:
    if value is None:
        if key in table:
            del table[key]
        return
    table[key] = value


def _apply_provider_renames(
    document: Any,
    renames: Mapping[str, str],
) -> None:
    if not renames:
        return
    section = _replace_or_get_table(document, "providers")
    existing_ids = set(section.keys())
    destinations = set(renames.values())
    for old_id, new_id in renames.items():
        if old_id not in existing_ids:
            raise ConfigurationError(
                "provider rename source does not exist",
                field=f"provider_renames.{old_id}",
            )
        # A destination may be another source in the same atomic rename
        # request (for example A->X, B->A): that source is released by the
        # same move.  Other existing destinations remain conflicts.
        if new_id in existing_ids and new_id not in renames:
            raise ConfigurationError(
                "provider rename destination already exists",
                field=f"provider_renames.{old_id}",
            )
    if len(destinations) != len(renames):
        # This is also validated by _validate_payload_shape, but keep the
        # mutation boundary defensive for direct internal callers.
        raise ConfigurationError("provider rename destinations must be unique")

    moved = {new_id: section[old_id] for old_id, new_id in renames.items()}
    for old_id in renames:
        del section[old_id]
    for new_id, profile in moved.items():
        section[new_id] = profile

    models = document.get("models")
    if not isinstance(models, Mapping):
        return
    for profile in models.values():
        if not isinstance(profile, Mapping):
            continue
        provider_id = profile.get("provider")
        if provider_id in renames:
            profile["provider"] = renames[provider_id]


def _apply_providers(document: Any, requested: Mapping[str, Any]) -> None:
    section = _replace_or_get_table(document, "providers")
    _delete_missing_profiles(section, requested)
    for profile_id, raw_profile in requested.items():
        profile = section.get(profile_id)
        if not isinstance(profile, Mapping):
            profile = toml_table()
            section[profile_id] = profile
        if "kind" not in raw_profile:
            if "kind" in profile:
                del profile["kind"]
        else:
            _set_or_delete(profile, "kind", raw_profile.get("kind"))
        # Omitted base_url means clear the old endpoint.  Omitted api_key is
        # intentionally different: it retains a literal/env expression.
        if "base_url" in raw_profile:
            _set_or_delete(profile, "base_url", raw_profile.get("base_url"))
        elif "base_url" in profile:
            del profile["base_url"]
        if "api_key" in raw_profile and raw_profile.get("api_key") is not None:
            _set_or_delete(profile, "api_key", raw_profile.get("api_key"))


def _apply_models(document: Any, requested: Mapping[str, Any]) -> None:
    section = _replace_or_get_table(document, "models")
    _delete_missing_profiles(section, requested)
    field_names = (
        "provider_profile_id",
        "remote_id",
        "display_name",
        "context_window",
        "max_output_tokens",
        "reasoning_effort",
    )
    toml_names = {"provider_profile_id": "provider"}
    for model_ref, raw_profile in requested.items():
        profile = section.get(model_ref)
        if not isinstance(profile, Mapping):
            profile = toml_table()
            section[model_ref] = profile
        for field_name in field_names:
            toml_name = toml_names.get(field_name, field_name)
            if field_name in raw_profile:
                _set_or_delete(profile, toml_name, raw_profile.get(field_name))
            elif toml_name in profile:
                del profile[toml_name]


def write_user_config(
    path: str | os.PathLike[str] | Path,
    payload: Mapping[str, Any],
) -> Path:
    """Atomically write a complete current-schema user configuration update.

    The payload uses Application-owned names.  In particular,
    provider_profile_id is translated to the TOML field provider.  An omitted
    Provider api_key retains the existing literal or env: expression; a
    supplied value is written once and is never returned.
    """

    target = Path(path).expanduser().resolve(strict=False)
    if not isinstance(payload, Mapping):
        raise TypeError("configuration payload must be a mapping")
    if not target.is_file():
        try:
            document = parse(USER_CONFIG_TEMPLATE)
        except Exception:  # pragma: no cover - package template is static
            raise ConfigurationError("configuration template cannot be parsed", path=target) from None
    else:
        document = _parse_document(target)
    current = _plain(document)
    if not isinstance(current, Mapping):
        raise ConfigurationError("configuration root must be a table", path=target)
    _validate_existing_schema(current, path=target)
    _validate_payload_shape(payload, path=target)

    for key in ("default_model", "default_permission_mode"):
        if key in payload:
            _set_or_delete(document, key, payload[key])
    renames = payload.get("provider_renames")
    if renames is not None:
        _apply_provider_renames(document, renames)
    if "providers" in payload and payload["providers"] is not None:
        _apply_providers(document, payload["providers"])
    if "models" in payload and payload["models"] is not None:
        _apply_models(document, payload["models"])

    candidate = _plain(document)
    if not isinstance(candidate, Mapping):
        raise ConfigurationError("configuration root must be a table", path=target)
    try:
        validate_user_config_mapping(
            candidate,
            path=target,
            resolve_secrets=False,
        )
    except ConfigurationError:
        raise
    except Exception as exc:
        # Public loader errors contain only path/field evidence, never
        # candidate values such as a new API key.
        raise ConfigurationError(str(exc), path=target) from None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ConfigurationError(
            "user configuration directory could not be created",
            path=target,
        ) from exc
    return _atomic_write(target, dumps(document))


def _write_user_preference(
    path: str | os.PathLike[str],
    field: str,
    value: str,
) -> Path:
    """Atomically update one validated root user preference."""

    if field == "default_model":
        if not isinstance(value, str) or not value.strip():
            raise ValueError("default_model must be a non-empty string")
    elif field == "default_permission_mode":
        if value not in {"default", "auto"}:
            raise ValueError("default_permission_mode must be default or auto")
    else:  # pragma: no cover
        raise ValueError("unsupported user preference")
    target = Path(path).expanduser().resolve(strict=False)
    original = target.read_text(encoding="utf-8")
    try:
        document = parse(original)
    except Exception:
        raise ValueError("user configuration is not valid TOML") from None
    if "model" in document:
        raise ValueError("unsupported configuration field: model")
    document[field] = value
    return _atomic_write(target, dumps(document))


def write_user_default_model(path: str | os.PathLike[str], model_ref: str) -> Path:
    """Atomically update only the root default_model value of a user file."""

    return _write_user_preference(path, "default_model", model_ref)


def write_user_default_permission_mode(
    path: str | os.PathLike[str],
    mode: str,
) -> Path:
    """Atomically update only the safe root permission default."""

    return _write_user_preference(path, "default_permission_mode", mode)


__all__ = [
    "write_user_config",
    "write_user_default_model",
    "write_user_default_permission_mode",
]
