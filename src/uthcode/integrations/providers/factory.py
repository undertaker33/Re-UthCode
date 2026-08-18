"""The single Provider Integration construction boundary."""

from __future__ import annotations

from collections.abc import Callable

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
    if config.api_key is None:
        raise MissingSecretError("api_key")
    return config.api_key.reveal()


def _build_without_secret(
    builder: Callable[..., ProviderPort],
    secret: str,
    /,
    *args: object,
    **kwargs: object,
) -> ProviderPort:
    """Keep SDK construction failures from echoing the credential."""

    try:
        return builder(*args, **kwargs)
    except Exception as exc:
        if secret in str(exc) or secret in repr(exc):
            raise ProviderConfigurationError("Provider construction failed") from None
        raise


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

    if (
        config.reasoning_effort is not None
        and config.reasoning_effort != "none"
        and config.kind not in {ProviderKind.OPENAI_RESPONSES, ProviderKind.OPENAI_COMPAT}
    ):
        raise ProviderConfigurationError(
            f"{config.kind.value} Provider does not support reasoning_effort"
        )

    api_key = _secret_for(config)
    if config.kind is ProviderKind.ANTHROPIC:
        return _build_without_secret(
            build_anthropic_provider,
            api_key,
            config.model,
            api_key=api_key,
            base_url=config.base_url,
            max_output_tokens=config.max_output_tokens,
        )
    if config.kind is ProviderKind.OPENAI_RESPONSES:
        return _build_without_secret(
            build_openai_responses_provider,
            api_key,
            config.model,
            api_key=api_key,
            base_url=config.base_url,
            max_output_tokens=config.max_output_tokens,
        )
    if config.kind is ProviderKind.OPENAI_COMPAT:
        return _build_without_secret(
            build_openai_compat_provider,
            api_key,
            config.model,
            base_url=config.base_url,
            api_key=api_key,
            max_output_tokens=config.max_output_tokens,
        )
    raise ProviderConfigurationError(f"unsupported provider kind: {config.kind.value}")


__all__ = ["create_provider"]
