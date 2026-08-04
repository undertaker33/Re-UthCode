"""Configuration Integration boundary for Application composition."""

from .loader import (
    ConfigurationError,
    ConfigurationInitializationRequired,
    discover_config_paths,
    load_effective_config,
)
from .template import USER_CONFIG_TEMPLATE, create_user_template
from .writer import write_user_model

__all__ = [
    "ConfigurationError",
    "ConfigurationInitializationRequired",
    "USER_CONFIG_TEMPLATE",
    "create_user_template",
    "discover_config_paths",
    "load_effective_config",
    "write_user_model",
]
