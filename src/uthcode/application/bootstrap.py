"""The Application package's single public composition root."""

from __future__ import annotations

from importlib import import_module
from os import PathLike
from pathlib import Path
from typing import Any

from .configuration import EffectiveConfig, LaunchOptions, ModelProfile, ProviderProfile
from .generation import ModelWriter, ProviderBuilder, UthCodeApplication
from .runtime_context import ApplicationRuntimeContext


class ConfigurationError(ValueError):
    """A launch configuration could not be loaded safely."""


class ConfigurationInitializationRequired(ConfigurationError):
    """The user must enable and fill in the configuration template."""

    def __init__(self, template_path: str | Path) -> None:
        self.template_path = Path(template_path)
        super().__init__(
            "configuration is not initialized; edit and uncomment one complete "
            "Provider and Model example, then run again: "
            f"{self.template_path}"
        )


def _provider_config(
    provider: ProviderProfile,
    model: ModelProfile,
) -> Any:
    from uthcode.integrations.providers.config import (
        ProviderConfig,
        ProviderKind,
    )

    return ProviderConfig(
        kind=ProviderKind(provider.kind.value),
        model=model.remote_model_id,
        api_key_env=provider.api_key_env,
        base_url=provider.base_url,
        max_output_tokens=model.max_output_tokens,
    )


def _default_builder() -> ProviderBuilder:
    from uthcode.integrations.providers.factory import create_provider

    def build(provider: ProviderProfile, model: ModelProfile) -> Any:
        return create_provider(_provider_config(provider, model))

    return build


def _default_writer(configuration: EffectiveConfig) -> ModelWriter | None:
    user_sources = tuple(
        source
        for source in configuration.sources
        if source.kind == "user" and source.path is not None
    )
    if not user_sources:
        return None
    path = user_sources[0].path
    assert path is not None
    writer_module = import_module("uthcode.integrations.config.writer")
    write_user_model = writer_module.write_user_model

    def write(model_ref: str) -> object:
        return write_user_model(path, model_ref)

    return write


def create_application(
    config: EffectiveConfig,
    *,
    provider_builder: ProviderBuilder | None = None,
    model_writer: ModelWriter | None = None,
    runtime_context: ApplicationRuntimeContext | None = None,
) -> UthCodeApplication:
    """Build a Headless Application from one EffectiveConfig."""

    if not isinstance(config, EffectiveConfig):
        raise TypeError("config must be EffectiveConfig")
    builder = _default_builder() if provider_builder is None else provider_builder

    provider = builder(
        config.providers[config.current_model.provider_profile_id],
        config.current_model,
    )
    writer = model_writer if model_writer is not None else _default_writer(config)
    return UthCodeApplication(
        provider,
        configuration=config,
        provider_builder=builder,
        model_writer=writer,
        runtime_context=runtime_context,
    )


def load_effective_config(
    options: LaunchOptions | None = None,
    *,
    cwd: str | PathLike[str] | None = None,
    home: str | PathLike[str] | None = None,
    model: str | None = None,
) -> EffectiveConfig:
    """Load configuration through the Integration boundary."""

    loader_module = import_module("uthcode.integrations.config.loader")
    load = loader_module.load_effective_config

    try:
        return load(options, cwd=cwd, home=home, model=model)
    except Exception as exc:
        initialization_error = getattr(
            loader_module,
            "ConfigurationInitializationRequired",
            None,
        )
        if initialization_error is not None and isinstance(exc, initialization_error):
            raise ConfigurationInitializationRequired(exc.template_path) from None
        configuration_error = getattr(loader_module, "ConfigurationError", None)
        if configuration_error is not None and isinstance(exc, configuration_error):
            raise ConfigurationError(str(exc)) from None
        raise


__all__ = [
    "ConfigurationError",
    "ConfigurationInitializationRequired",
    "create_application",
    "load_effective_config",
]
