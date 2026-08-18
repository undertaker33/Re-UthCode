"""Immutable raw configuration values owned by the configuration Integration."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from uthcode.core.secrets import SecretValue


def _freeze(value: Any, *, field: str) -> Any:
    if value is None or isinstance(value, (str, bool, int, SecretValue)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{field} must contain finite numbers")
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"{field} keys must be strings")
            frozen[key] = _freeze(item, field=f"{field}.{key}")
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item, field=f"{field}[]") for item in value)
    raise TypeError(f"{field} contains an unsupported value")


def _freeze_profiles(
    value: Mapping[str, Mapping[str, object]],
    *,
    field: str,
) -> Mapping[str, Mapping[str, object]]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field} must be a mapping")
    frozen: dict[str, Mapping[str, object]] = {}
    for key, profile in value.items():
        if not isinstance(key, str):
            raise TypeError(f"{field} keys must be strings")
        if not isinstance(profile, Mapping):
            raise TypeError(f"{field}.{key} must be a mapping")
        frozen[key] = _freeze(profile, field=f"{field}.{key}")
    return MappingProxyType(frozen)


@dataclass(frozen=True, slots=True)
class LoadedConfigSource:
    """Safe source evidence retained by the raw configuration loader."""

    kind: str
    path: Path | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, str) or not self.kind.strip():
            raise ValueError("configuration source kind must be a non-empty string")
        if self.path is not None:
            object.__setattr__(self, "path", Path(self.path))


@dataclass(frozen=True, slots=True)
class LoadedConfigData:
    """Deeply immutable values produced by the Integration loader."""

    default_model: str
    providers: Mapping[str, Mapping[str, object]]
    models: Mapping[str, Mapping[str, object]]
    sources: tuple[LoadedConfigSource, ...]
    default_permission_mode: str = "default"

    def __post_init__(self) -> None:
        if not isinstance(self.default_model, str) or not self.default_model.strip():
            raise ValueError("default_model must be a non-empty string")
        if self.default_permission_mode not in {"default", "auto"}:
            raise ValueError("default_permission_mode must be default or auto")
        object.__setattr__(
            self,
            "providers",
            _freeze_profiles(self.providers, field="providers"),
        )
        object.__setattr__(
            self,
            "models",
            _freeze_profiles(self.models, field="models"),
        )
        sources = tuple(self.sources)
        if not all(isinstance(source, LoadedConfigSource) for source in sources):
            raise TypeError("sources must contain LoadedConfigSource values")
        object.__setattr__(self, "sources", sources)


__all__ = ["LoadedConfigData", "LoadedConfigSource"]
