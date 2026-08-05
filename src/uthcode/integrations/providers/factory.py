"""The single Provider Integration construction boundary."""

from __future__ import annotations

import os

from uthcode.core.provider import (
    FinishReason,
    GenerationCompleted,
    Message,
    MissingSecretError,
    ProviderResponse,
    ProviderConfigurationError,
    ProviderIdentity,
    ProviderPort,
    TextPart,
    Usage,
)

from .anthropic import build_anthropic_provider
from .config import ProviderConfig, ProviderKind
from .fake import FakeProvider
from .openai_compat import build_openai_compat_provider
from .openai_responses import build_openai_responses_provider


def _secret_for(config: ProviderConfig) -> str:
    if config.api_key_env is None:
        raise ProviderConfigurationError(
            f"{config.kind.value} Provider requires api_key_env"
        )
    secret = os.environ.get(config.api_key_env)
    if not secret:
        raise MissingSecretError(config.api_key_env)
    return secret


def create_provider(config: ProviderConfig) -> ProviderPort:
    """Construct one Provider without performing a model request."""

    if not isinstance(config, ProviderConfig):
        raise TypeError("config must be ProviderConfig")

    if config.kind is ProviderKind.FAKE:
        return FakeProvider(
            identity=ProviderIdentity("fake", "script", config.model),
            events=(
                GenerationCompleted(
                    ProviderResponse(
                        message=Message(
                            "assistant",
                            (TextPart("fake response"),),
                        ),
                        usage=Usage(),
                        finish_reason=FinishReason.STOP,
                    )
                ),
            ),
        )

    if config.kind is ProviderKind.OPENAI_COMPAT and not config.base_url:
        raise ProviderConfigurationError(
            "OpenAI-compatible Provider requires an explicit base URL"
        )

    api_key = _secret_for(config)
    if config.kind is ProviderKind.ANTHROPIC:
        return build_anthropic_provider(
            config.model,
            api_key=api_key,
            base_url=config.base_url,
            max_output_tokens=config.max_output_tokens,
        )
    if config.kind is ProviderKind.OPENAI_RESPONSES:
        return build_openai_responses_provider(
            config.model,
            api_key=api_key,
            base_url=config.base_url,
            max_output_tokens=config.max_output_tokens,
        )
    if config.kind is ProviderKind.OPENAI_COMPAT:
        return build_openai_compat_provider(
            config.model,
            base_url=config.base_url,
            api_key=api_key,
            max_output_tokens=config.max_output_tokens,
        )
    raise ProviderConfigurationError(f"unsupported provider kind: {config.kind.value}")


__all__ = ["create_provider"]
