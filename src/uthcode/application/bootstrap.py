"""The Application package's single public composition root."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from importlib import import_module
from os import PathLike
from pathlib import Path
from typing import Any

from uthcode.integrations.config.data import LoadedConfigData
from uthcode.integrations.config.loader import (
    ConfigurationError as IntegrationConfigurationError,
    ConfigurationInitializationRequired as IntegrationConfigurationInitializationRequired,
    load_config_data,
    read_user_config_api_key,
    read_user_config_view_data,
    resolve_user_home,
)
from uthcode.integrations.tools.factory import create_default_tools
from uthcode.integrations.permissions import load_permission_rules
from uthcode.integrations.instruction_files import (
    InstructionFileReader,
    discover_project_root,
)
from uthcode.integrations.session_files import SessionFileStore
from uthcode.core.tool import Tool
from uthcode.core.permission import PermissionMode
from uthcode.core.secrets import SecretValue

from .configuration import (
    ConfigurationModelError,
    ConfigSource,
    EffectiveConfig,
    LaunchOptions,
    ModelProfile,
    ProviderKind,
    ProviderProfile,
    UserConfigurationView,
    UserConfigurationWriteRequest,
    UserModelView,
    UserProviderView,
)
from .generation import ModelWriter, ProviderBuilder, UthCodeApplication
from .sessions import ApplicationSessionService
from .instructions import InstructionLoader
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
            "configuration is not initialized; fill one complete Provider and "
            "Model slot, set default_model, then run again: "
            f"{self.template_path}",
        )
        self.path = self.template_path


def _user_config_path(home: str | PathLike[str] | None = None) -> Path:
    explicit_home = Path(home) if home is not None else None
    return (resolve_user_home(explicit_home) / ".uthcode" / "config.toml").resolve(
        strict=False
    )


def _map_integration_configuration_error(
    exc: IntegrationConfigurationError,
) -> ConfigurationError:
    if isinstance(exc, IntegrationConfigurationInitializationRequired):
        return ConfigurationInitializationRequired(exc.template_path)
    return ConfigurationError(exc.message, path=exc.path, field=exc.field)


def read_user_configuration(
    *,
    home: str | PathLike[str] | None = None,
) -> UserConfigurationView:
    """Read the current user config as a display-safe Application DTO."""

    path = _user_config_path(home)
    try:
        raw = read_user_config_view_data(path, create_if_missing=True)
    except IntegrationConfigurationError as exc:
        raise _map_integration_configuration_error(exc) from None
    providers_raw = raw.get("providers", {})
    models_raw = raw.get("models", {})
    return UserConfigurationView(
        default_model=raw.get("default_model", ""),
        default_permission_mode=raw.get("default_permission_mode", "default"),
        providers=(
            providers_raw
            if isinstance(providers_raw, Mapping)
            else {}
        ),
        models=models_raw if isinstance(models_raw, Mapping) else {},
        path=path,
    )


def read_user_api_key(
    provider_profile_id: str,
    *,
    home: str | PathLike[str] | None = None,
) -> str | None:
    """Read one saved API key expression for the explicit Provider identity.

    The Integration reader returns literals and ``env:NAME`` references as
    configured.  It deliberately does not resolve environment variables or
    read the Runtime Provider's ``SecretValue``.
    """

    path = _user_config_path(home)
    try:
        return read_user_config_api_key(path, provider_profile_id)
    except IntegrationConfigurationError as exc:
        raise _map_integration_configuration_error(exc) from None


def _user_write_payload(
    request: UserConfigurationWriteRequest,
) -> dict[str, object]:
    payload: dict[str, object] = {}
    if request.default_model is not None:
        payload["default_model"] = request.default_model
    if request.default_permission_mode is not None:
        mode = request.default_permission_mode
        payload["default_permission_mode"] = (
            mode.value if isinstance(mode, PermissionMode) else mode
        )
    if request.providers is not None:
        providers: dict[str, dict[str, object]] = {}
        for profile_id, raw_profile in request.providers.items():
            if not isinstance(raw_profile, Mapping):
                raise TypeError(f"providers.{profile_id} must be a mapping")
            providers[profile_id] = {}
            for key, value in raw_profile.items():
                # A null key from a form means "unchanged".  An empty string
                # remains the explicit request to clear the configured key.
                if key == "api_key" and value is None:
                    continue
                if key == "kind" and isinstance(value, ProviderKind):
                    value = value.value
                providers[profile_id][key] = (
                    value.reveal()
                    if key == "api_key" and isinstance(value, SecretValue)
                    else value
                )
        payload["providers"] = providers
    if request.models is not None:
        models: dict[str, dict[str, object]] = {}
        for model_ref, raw_profile in request.models.items():
            if not isinstance(raw_profile, Mapping):
                raise TypeError(f"models.{model_ref} must be a mapping")
            profile = dict(raw_profile)
            profile.pop("model_ref", None)
            models[model_ref] = profile
        payload["models"] = models
    if request.provider_renames is not None:
        payload["provider_renames"] = dict(request.provider_renames)
    return payload


def write_user_configuration(
    request: UserConfigurationWriteRequest | Mapping[str, object],
    *,
    home: str | PathLike[str] | None = None,
) -> UserConfigurationView:
    """Validate and atomically write a current-schema user config update."""

    if not isinstance(request, UserConfigurationWriteRequest):
        if not isinstance(request, Mapping):
            raise TypeError("request must be UserConfigurationWriteRequest or mapping")
        unsupported = [
            key
            for key in request
            if key not in {
                "default_model",
                "default_permission_mode",
                "providers",
                "models",
                "provider_renames",
            }
        ]
        if unsupported:
            raise ConfigurationError(
                "unsupported configuration field",
                path=_user_config_path(home),
                field=str(unsupported[0]),
            )
        request = UserConfigurationWriteRequest(
            default_model=request.get("default_model"),
            default_permission_mode=request.get("default_permission_mode"),
            providers=request.get("providers"),
            models=request.get("models"),
            provider_renames=request.get("provider_renames"),
        )
    path = _user_config_path(home)
    try:
        writer_module = import_module("uthcode.integrations.config.writer")
        writer = writer_module.write_user_config
        writer(path, _user_write_payload(request))
    except IntegrationConfigurationError as exc:
        raise _map_integration_configuration_error(exc) from None
    return read_user_configuration(home=home)


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
        model=model.remote_id,
        api_key=provider.api_key,
        base_url=provider.base_url,
        max_output_tokens=model.max_output_tokens,
        reasoning_effort=model.reasoning_effort,
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
    write_user_default_model = writer_module.write_user_default_model

    def write(model_ref: str) -> object:
        return write_user_default_model(path, model_ref)

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
    instruction_loader: InstructionLoader | None = None,
    storage_root: str | Path | None = None,
    session_store: SessionFileStore | None = None,
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
    if instruction_loader is not None and not isinstance(instruction_loader, InstructionLoader):
        raise TypeError("instruction_loader must be InstructionLoader or None")
    loader = instruction_loader
    if loader is None:
        loader = InstructionLoader(
            user_root=_instruction_user_root(config),
            project_root=discover_project_root(runtime_context.workdir),
            reader=InstructionFileReader(),
        )
    if session_store is not None and not isinstance(session_store, SessionFileStore):
        raise TypeError("session_store must be SessionFileStore or None")
    if session_store is not None and storage_root is not None:
        raise TypeError("pass storage_root or session_store, not both")
    session_service = ApplicationSessionService(
        storage_root=(
            Path(storage_root)
            if storage_root is not None
            else Path.home() / ".uthcode" / "sessions"
        ),
        project_key=str(loader.project_root),
        instruction_loader=loader,
        store=session_store,
    )
    tool_values = (
        create_default_tools(
            runtime_context.workdir,
            on_path_access=loader.activate_for_path,
        )
        if tools is None
        else tuple(tools)
    )
    secret_values = tuple(
        profile.api_key
        for profile in config.providers.values()
        if profile.api_key is not None
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
            secret_values=secret_values,
            session_provider=lambda: session_service.active_session,
        ),
        permission_rules_loader=(
            lambda: load_permission_rules(cwd=runtime_context.workdir)
        ),
        instruction_loader=loader,
        session_service=session_service,
    )


def _instruction_user_root(config: EffectiveConfig) -> Path:
    """Derive the user instruction root from the user config source."""

    for source in config.sources:
        if source.kind == "user" and source.path is not None:
            return source.path.expanduser().resolve(strict=False).parent
    return (Path.home() / ".uthcode").expanduser().resolve(strict=False)


def _effective_config_from_raw(data: LoadedConfigData) -> EffectiveConfig:
    sources = tuple(ConfigSource(source.kind, source.path) for source in data.sources)
    try:
        return EffectiveConfig.from_mapping(
            {
                "default_model": data.default_model,
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
    "read_user_api_key",
    "read_user_configuration",
    "write_user_configuration",
]
