"""Configuration Integration boundary for Application composition."""

from .data import LoadedConfigData, LoadedConfigSource
from .loader import (
    ConfigurationError,
    ConfigurationInitializationRequired,
    discover_config_paths,
    load_config_data,
)
from .template import USER_CONFIG_TEMPLATE, create_user_template
from .writer import write_user_model

__all__ = [
    "ConfigurationError",
    "ConfigurationInitializationRequired",
    "LoadedConfigData",
    "LoadedConfigSource",
    "USER_CONFIG_TEMPLATE",
    "create_user_template",
    "discover_config_paths",
    "load_config_data",
    "write_user_model",
]
