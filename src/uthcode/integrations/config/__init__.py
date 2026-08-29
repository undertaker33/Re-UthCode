"""Configuration Integration boundary for Application composition."""

from .data import LoadedConfigData, LoadedConfigSource
from .loader import (
    ConfigurationError,
    ConfigurationInitializationRequired,
    discover_config_paths,
    discover_scoped_paths,
    load_config_data,
    physical_path,
    read_user_config_view_data,
    resolve_user_home,
    validate_user_config_mapping,
)
from .template import USER_CONFIG_TEMPLATE, create_user_template
from .writer import write_user_config, write_user_default_model

__all__ = [
    "ConfigurationError",
    "ConfigurationInitializationRequired",
    "LoadedConfigData",
    "LoadedConfigSource",
    "USER_CONFIG_TEMPLATE",
    "create_user_template",
    "discover_config_paths",
    "discover_scoped_paths",
    "load_config_data",
    "physical_path",
    "read_user_config_view_data",
    "resolve_user_home",
    "validate_user_config_mapping",
    "write_user_config",
    "write_user_default_model",
]
