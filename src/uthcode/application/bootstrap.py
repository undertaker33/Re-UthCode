"""The Application package's single public composition root."""

from __future__ import annotations

from .generation import UthCodeApplication
from uthcode.integrations.providers.config import ProviderConfig


def create_application(config: ProviderConfig) -> UthCodeApplication:
    """Build a Headless Application from the Integration Provider factory."""

    from uthcode.integrations.providers.factory import create_provider

    return UthCodeApplication(create_provider(config))


__all__ = ["create_application"]
