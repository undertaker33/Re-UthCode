"""Immutable Application-owned configuration models.

This module deliberately contains no file, environment, TOML, or Provider
construction logic.  Integrations translate their external representation to
these value objects before the Application receives it.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from types import MappingProxyType
from typing import Any

from uthcode.core.permission import PermissionMode
from uthcode.core.secrets import SecretValue


class ConfigurationModelError(ValueError):
    """Raised when an Application configuration value is invalid."""


def _require_text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationModelError(f"{field_name} must be a non-empty string")
    return value


def _freeze_mapping(value: Mapping[str, Any], field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    frozen: dict[str, Any] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise TypeError(f"{field_name} keys must be strings")
        frozen[key] = _freeze_value(item, f"{field_name}.{key}")
    return MappingProxyType(frozen)


def _freeze_value(value: Any, field_name: str) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ConfigurationModelError(f"{field_name} must contain finite numbers")
        return value
    if isinstance(value, Mapping):
        return _freeze_mapping(value, field_name)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_value(item, f"{field_name}[]") for item in value)
    raise TypeError(f"{field_name} contains an unsupported value")


class ProviderKind(str, Enum):
    """Provider kinds supported by the current Integration boundary."""

    @staticmethod
    def _generate_next_value_(
        name: str,
        start: int,
        count: int,
        last_values: list[object],
    ) -> str:
        del start, count, last_values
        return name.lower()

    FAKE = auto()
    ANTHROPIC = auto()
    OPENAI_RESPONSES = auto()
    OPENAI_COMPAT = auto()

    @classmethod
    def coerce(cls, value: ProviderKind | str) -> ProviderKind:
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value).strip().lower())
        except (TypeError, ValueError) as exc:
            raise ConfigurationModelError(
                f"unknown provider kind: {value!r}"
            ) from exc


_PROVIDER_MAPPING_FIELDS = frozenset({"kind", "base_url", "api_key"})
_MODEL_MAPPING_FIELDS = frozenset(
    {
        "provider_profile_id",
        "remote_id",
        "display_name",
        "context_window",
        "max_output_tokens",
        "reasoning_effort",
    }
)
_REASONING_EFFORTS = frozenset(
    {"none", "minimal", "low", "medium", "high", "xhigh", "max"}
)


@dataclass(frozen=True, slots=True)
class LaunchOptions:
    """Startup selections passed from an outer interface."""

    cwd: Path | None = None
    model: str | None = None
    home: Path | None = None

    def __post_init__(self) -> None:
        if self.cwd is not None:
            object.__setattr__(self, "cwd", Path(self.cwd))
        if self.home is not None:
            object.__setattr__(self, "home", Path(self.home))
        if self.model is not None:
            _require_text(self.model, "model")


@dataclass(frozen=True, slots=True)
class ConfigSource:
    """A safe description of one configuration layer."""

    kind: str
    path: Path | None = None

    def __post_init__(self) -> None:
        _require_text(self.kind, "kind")
        if self.path is not None:
            object.__setattr__(self, "path", Path(self.path))


@dataclass(frozen=True, slots=True)
class ProviderProfile:
    """A trusted Provider identity and opaque construction inputs."""

    provider_profile_id: str
    kind: ProviderKind | str
    base_url: str | None = None
    api_key: SecretValue | str | None = None

    def __post_init__(self) -> None:
        _require_text(self.provider_profile_id, "provider_profile_id")
        kind = ProviderKind.coerce(self.kind)
        object.__setattr__(self, "kind", kind)
        if self.base_url is not None:
            _require_text(self.base_url, "base_url")
        if isinstance(self.api_key, str) and not self.api_key.strip():
            object.__setattr__(self, "api_key", None)
        elif self.api_key is not None and not isinstance(self.api_key, SecretValue):
            object.__setattr__(self, "api_key", SecretValue(self.api_key))
        if kind is not ProviderKind.FAKE and self.api_key is None:
            raise ConfigurationModelError(
                "non-fake Provider profiles require a non-empty api_key"
            )
        if kind is ProviderKind.OPENAI_COMPAT and self.base_url is None:
            raise ConfigurationModelError(
                "OpenAI-compatible Provider profiles require base_url"
            )


@dataclass(frozen=True, slots=True)
class ModelProfile:
    """A model reference separated from its Provider and remote model ID."""

    model_ref: str
    provider_profile_id: str
    remote_id: str
    display_name: str | None = None
    context_window: int | None = None
    max_output_tokens: int | None = None
    reasoning_effort: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.model_ref, "model_ref")
        _require_text(self.provider_profile_id, "provider_profile_id")
        _require_text(self.remote_id, "remote_id")
        if self.display_name is not None:
            _require_text(self.display_name, "display_name")
        if self.context_window is not None and (
            isinstance(self.context_window, bool)
            or not isinstance(self.context_window, int)
            or self.context_window <= 0
        ):
            raise ConfigurationModelError(
                "context_window must be a positive integer or None"
            )
        if self.max_output_tokens is not None and (
            isinstance(self.max_output_tokens, bool)
            or not isinstance(self.max_output_tokens, int)
            or self.max_output_tokens <= 0
        ):
            raise ConfigurationModelError(
                "max_output_tokens must be a positive integer or None"
            )
        if self.reasoning_effort is not None:
            if (
                not isinstance(self.reasoning_effort, str)
                or self.reasoning_effort not in _REASONING_EFFORTS
            ):
                raise ConfigurationModelError(
                    "reasoning_effort must be one of: none, minimal, low, medium, high, xhigh, max"
                )
        if self.display_name is None:
            object.__setattr__(self, "display_name", self.remote_id)


def _coerce_source(value: ConfigSource | str | Path) -> ConfigSource:
    if isinstance(value, ConfigSource):
        return value
    if isinstance(value, Path):
        return ConfigSource("file", value)
    return ConfigSource(str(value))


@dataclass(frozen=True, slots=True)
class EffectiveConfig:
    """Validated, deeply immutable configuration consumed by Application."""

    default_model: str
    providers: Mapping[str, ProviderProfile]
    models: Mapping[str, ModelProfile]
    sources: tuple[ConfigSource, ...] = ()
    default_permission_mode: PermissionMode = PermissionMode.DEFAULT

    def __post_init__(self) -> None:
        _require_text(self.default_model, "default_model")
        mode = self.default_permission_mode
        if not isinstance(mode, PermissionMode):
            try:
                mode = PermissionMode(mode)
            except (TypeError, ValueError) as exc:
                raise ConfigurationModelError("unknown default_permission_mode") from exc
        if mode is PermissionMode.FULL_ACCESS:
            raise ConfigurationModelError("default_permission_mode cannot be full_access")
        object.__setattr__(self, "default_permission_mode", mode)
        if not isinstance(self.providers, Mapping):
            raise TypeError("providers must be a mapping")
        if not isinstance(self.models, Mapping):
            raise TypeError("models must be a mapping")

        providers: dict[str, ProviderProfile] = {}
        for provider_profile_id, value in self.providers.items():
            _require_text(provider_profile_id, "provider profile id")
            if isinstance(value, ProviderProfile):
                profile = value
                if profile.provider_profile_id != provider_profile_id:
                    raise ConfigurationModelError(
                        "Provider Profile ID does not match its mapping key"
                    )
            elif isinstance(value, Mapping):
                unsupported = [
                    key for key in value if key not in _PROVIDER_MAPPING_FIELDS
                ]
                if unsupported:
                    raise ConfigurationModelError(
                        f"unsupported Provider Profile field: {unsupported[0]!r}"
                    )
                profile = ProviderProfile(
                    provider_profile_id=provider_profile_id,
                    kind=value.get("kind"),
                    base_url=value.get("base_url"),
                    api_key=value.get("api_key"),
                )
            else:
                raise TypeError("providers must contain ProviderProfile values")
            providers[provider_profile_id] = profile

        models: dict[str, ModelProfile] = {}
        for model_ref, value in self.models.items():
            _require_text(model_ref, "model ref")
            if isinstance(value, ModelProfile):
                profile = value
                if profile.model_ref != model_ref:
                    raise ConfigurationModelError(
                        "Model Ref does not match its mapping key"
                    )
            elif isinstance(value, Mapping):
                unsupported = [
                    key for key in value if key not in _MODEL_MAPPING_FIELDS
                ]
                if unsupported:
                    raise ConfigurationModelError(
                        f"unsupported Model Profile field: {unsupported[0]!r}"
                    )
                profile = ModelProfile(
                    model_ref=model_ref,
                    provider_profile_id=value.get("provider_profile_id"),
                    remote_id=value.get("remote_id"),
                    display_name=value.get("display_name"),
                    context_window=value.get("context_window"),
                    max_output_tokens=value.get("max_output_tokens"),
                    reasoning_effort=value.get("reasoning_effort"),
                )
            else:
                raise TypeError("models must contain ModelProfile values")
            models[model_ref] = profile

        if self.default_model not in models:
            raise ConfigurationModelError(f"unknown selected model: {self.default_model!r}")
        for profile in models.values():
            if profile.provider_profile_id not in providers:
                raise ConfigurationModelError(
                    f"unknown provider reference: {profile.provider_profile_id!r}"
                )
            provider = providers[profile.provider_profile_id]
            if (
                profile.reasoning_effort is not None
                and profile.reasoning_effort != "none"
                and provider.kind not in {
                    ProviderKind.FAKE,
                    ProviderKind.OPENAI_RESPONSES,
                    ProviderKind.OPENAI_COMPAT,
                }
            ):
                raise ConfigurationModelError(
                    f"Provider {provider.provider_profile_id!r} does not support reasoning_effort"
                )

        source_values = tuple(_coerce_source(value) for value in self.sources)
        object.__setattr__(self, "providers", MappingProxyType(providers))
        object.__setattr__(self, "models", MappingProxyType(models))
        object.__setattr__(self, "sources", source_values)

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, Any],
        *,
        sources: Sequence[ConfigSource | str | Path] = (),
    ) -> EffectiveConfig:
        if not isinstance(value, Mapping):
            raise TypeError("EffectiveConfig requires a mapping")
        unsupported = [
            key
            for key in value
            if key not in {"default_model", "providers", "models", "default_permission_mode"}
        ]
        if unsupported:
            raise ConfigurationModelError(
                f"unsupported EffectiveConfig field: {unsupported[0]!r}"
            )
        selected = value.get("default_model")
        if selected is None:
            raise ConfigurationModelError("configuration requires a default_model")
        return cls(
            default_model=selected,
            providers=value.get("providers", {}),
            models=value.get("models", {}),
            sources=tuple(sources),
            default_permission_mode=value.get("default_permission_mode", "default"),
        )

    @classmethod
    def single_model(
        cls,
        model_ref: str,
        *,
        provider_profile_id: str = "default",
        provider_kind: ProviderKind | str = ProviderKind.FAKE,
        remote_id: str | None = None,
        display_name: str | None = None,
        api_key: SecretValue | str | None = None,
        base_url: str | None = None,
        max_output_tokens: int | None = None,
        context_window: int | None = None,
        reasoning_effort: str | None = None,
        source: ConfigSource | str | Path | None = None,
    ) -> EffectiveConfig:
        """Build a minimal valid configuration for an embedded caller."""

        if remote_id is None:
            remote_id = model_ref
        config_source = () if source is None else (_coerce_source(source),)
        if source is None:
            config_source = (ConfigSource("embedded"),)
        return cls(
            default_model=model_ref,
            providers={
                provider_profile_id: ProviderProfile(
                    provider_profile_id=provider_profile_id,
                    kind=provider_kind,
                    base_url=base_url,
                    api_key=api_key,
                )
            },
            models={
                model_ref: ModelProfile(
                    model_ref=model_ref,
                    provider_profile_id=provider_profile_id,
                    remote_id=remote_id,
                    display_name=display_name,
                    context_window=context_window,
                    max_output_tokens=max_output_tokens,
                    reasoning_effort=reasoning_effort,
                )
            },
            sources=config_source,
        )

    @property
    def current_model(self) -> ModelProfile:
        return self.models[self.default_model]

    def provider_for(self, model_ref: str | None = None) -> ProviderProfile:
        ref = self.default_model if model_ref is None else model_ref
        return self.providers[self.models[ref].provider_profile_id]

    def model_catalog(self) -> tuple[ModelProfile, ...]:
        return tuple(self.models.values())


__all__ = [
    "ConfigSource",
    "ConfigurationModelError",
    "EffectiveConfig",
    "LaunchOptions",
    "ModelProfile",
    "ProviderKind",
    "ProviderProfile",
]
