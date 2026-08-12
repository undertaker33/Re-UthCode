"""The Application package's single public composition root."""

from __future__ import annotations

from collections.abc import Sequence
from importlib import import_module
from os import PathLike
from pathlib import Path
from typing import Any

from uthcode.integrations.config.data import LoadedConfigData
from uthcode.integrations.config.loader import (
    ConfigurationError as IntegrationConfigurationError,
    ConfigurationInitializationRequired as IntegrationConfigurationInitializationRequired,
    load_config_data,
)
from uthcode.integrations.tools.factory import create_default_tools
from uthcode.integrations.permissions import load_permission_rules
from uthcode.core.tool import Tool

from .configuration import (
    ConfigurationModelError,
    ConfigSource,
    EffectiveConfig,
    LaunchOptions,
    ModelProfile,
    ProviderProfile,
)
from .generation import ModelWriter, ProviderBuilder, UthCodeApplication
from .runtime_context import ApplicationRuntimeContext
from .tools import ApplicationToolService


class ConfigurationError(ValueError):
    """A launch configuration could not be loaded safely."""

    def __init__(
        self,
        message: str,
        *,
        path: str | Path | None = None,
        field: str | None = None,
    ) -> None:
        self.message = message
        self.path = Path(path) if path is not None else None
        self.field = field
        parts = []
        if self.path is not None:
            parts.append(str(self.path))
        if field is not None:
            parts.append(field)
        prefix = ": ".join(parts)
        super().__init__(f"{prefix}: {message}" if prefix else message)


class ConfigurationInitializationRequired(ConfigurationError):
    """The user must enable and fill in the configuration template."""

    def __init__(self, template_path: str | Path) -> None:
        self.template_path = Path(template_path)
        super().__init__(
            "configuration is not initialized; edit and uncomment one complete "
            "Provider and Model example, then run again: "
            f"{self.template_path}",
        )
        self.path = self.template_path


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


def _default_permission_writer(configuration: EffectiveConfig):
    user_sources = tuple(
        source for source in configuration.sources
        if source.kind == "user" and source.path is not None
    )
    if not user_sources:
        return None
    path = user_sources[0].path
    assert path is not None
    writer_module = import_module("uthcode.integrations.config.writer")
    writer = writer_module.write_user_default_permission_mode
    return lambda mode: writer(path, mode.value)


def create_application(
    config: EffectiveConfig,
    *,
    provider_builder: ProviderBuilder | None = None,
    model_writer: ModelWriter | None = None,
    permission_writer=None,
    runtime_context: ApplicationRuntimeContext | None = None,
    tools: Sequence[Tool] | None = None,
) -> UthCodeApplication:
    """Build a Headless Application from one EffectiveConfig."""

    if not isinstance(config, EffectiveConfig):
        raise TypeError("config must be EffectiveConfig")
    if runtime_context is None:
        runtime_context = ApplicationRuntimeContext.from_system()
    elif not isinstance(runtime_context, ApplicationRuntimeContext):
        raise TypeError("runtime_context must be ApplicationRuntimeContext")
    builder = _default_builder() if provider_builder is None else provider_builder

    provider = builder(
        config.providers[config.current_model.provider_profile_id],
        config.current_model,
    )
    writer = model_writer if model_writer is not None else _default_writer(config)
    tool_values = (
        create_default_tools(runtime_context.workdir)
        if tools is None
        else tuple(tools)
    )
    secret_env_names = tuple(
        profile.api_key_env
        for profile in config.providers.values()
        if profile.api_key_env is not None
    )
    return UthCodeApplication(
        provider,
        configuration=config,
        provider_builder=builder,
        model_writer=writer,
        permission_writer=(permission_writer if permission_writer is not None else _default_permission_writer(config)),
        runtime_context=runtime_context,
        tool_service=ApplicationToolService(
            tool_values,
            workdir=runtime_context.workdir,
            secret_env_names=secret_env_names,
        ),
        permission_rules_loader=(
            lambda: load_permission_rules(cwd=runtime_context.workdir)
        ),
    )


def _effective_config_from_raw(data: LoadedConfigData) -> EffectiveConfig:
    sources = tuple(ConfigSource(source.kind, source.path) for source in data.sources)
    try:
        return EffectiveConfig.from_mapping(
            {
                "model": data.model,
                "providers": data.providers,
                "models": data.models,
                "default_permission_mode": data.default_permission_mode,
            },
            sources=sources,
        )
    except (ConfigurationModelError, TypeError, ValueError) as exc:
        source_path = data.sources[-1].path if data.sources else None
        raise ConfigurationError(str(exc), path=source_path) from None


def load_effective_config(
    options: LaunchOptions | None = None,
    *,
    cwd: str | PathLike[str] | None = None,
    home: str | PathLike[str] | None = None,
    model: str | None = None,
) -> EffectiveConfig:
    """Load configuration through the Integration boundary."""

    if options is None:
        launch = LaunchOptions(
            cwd=Path(cwd) if cwd is not None else None,
            home=Path(home) if home is not None else None,
            model=model,
        )
    else:
        if any(value is not None for value in (cwd, home, model)):
            raise TypeError("pass LaunchOptions or keyword launch overrides, not both")
        launch = options
    try:
        raw = load_config_data(
            cwd=launch.cwd,
            home=launch.home,
            model=launch.model,
        )
    except IntegrationConfigurationInitializationRequired as exc:
        raise ConfigurationInitializationRequired(exc.template_path) from None
    except IntegrationConfigurationError as exc:
        raise ConfigurationError(
            exc.message,
            path=exc.path,
            field=exc.field,
        ) from None
    return _effective_config_from_raw(raw)


__all__ = [
    "ConfigurationError",
    "ConfigurationInitializationRequired",
    "create_application",
    "load_effective_config",
]
