"""Anthropic Messages protocol integration.

Only this module knows Anthropic content-block names and the Thinking
signature/redacted-thinking replay rules. The Direct Model lifecycle is kept
in :mod:`pydantic_ai`.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from pydantic_ai.messages import (
    TextPart as AITextPart,
    ThinkingPart as AIThinkingPart,
    ToolCallPart as AIToolCallPart,
)
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.providers.anthropic import AnthropicProvider as SDKAnthropicProvider

from uthcode.core.provider import (
    InvalidProviderResponseError,
    NativeItem,
    ProviderIdentity,
    ReasoningPart,
    TextPart,
    ToolCallPart,
)

from .pydantic_ai import PydanticAICodec, PydanticAIProvider, record_model_stream


def _native_at(
    native_items: Sequence[NativeItem],
    *,
    index: int,
    kinds: set[str],
) -> NativeItem | None:
    for item in native_items:
        if item.sequence_index == index and item.kind in kinds:
            return item
    return None


class AnthropicCodec(PydanticAICodec):
    """Encode and restore Anthropic Messages content blocks."""

    capture_provider_details = False

    def encode_assistant_part(
        self,
        part: TextPart | ReasoningPart | ToolCallPart,
        *,
        index: int,
        native_items: Sequence[NativeItem],
        identity: ProviderIdentity,
    ) -> Any:
        native = _native_at(
            native_items,
            index=index,
            kinds={"thinking", "redacted_thinking", "text", "tool_use"},
        )
        payload = native.payload if native is not None else {}

        if isinstance(part, ReasoningPart):
            if native is not None and native.kind == "redacted_thinking":
                data = payload.get("data")
                if not isinstance(data, str) or not data:
                    raise InvalidProviderResponseError(
                        "Anthropic redacted thinking requires a signature value"
                    )
                return AIThinkingPart(
                    "",
                    id="redacted_thinking",
                    signature=data,
                    provider_name=identity.provider,
                )
            signature = payload.get("signature")
            if signature is not None and not isinstance(signature, str):
                raise InvalidProviderResponseError(
                    "Anthropic thinking signature must be a string"
                )
            return AIThinkingPart(
                part.text,
                signature=signature,
                provider_name=identity.provider if native is not None else None,
            )

        if isinstance(part, TextPart):
            return AITextPart(part.text)

        if isinstance(part, ToolCallPart):
            return AIToolCallPart(
                tool_name=part.name,
                args=dict(part.arguments),
                tool_call_id=part.tool_call_id,
                provider_name=identity.provider if native is not None else None,
            )

        return super().encode_assistant_part(
            part,
            index=index,
            native_items=native_items,
            identity=identity,
        )

    def native_items_for_part(
        self,
        part: Any,
        *,
        index: int,
        identity: ProviderIdentity,
    ) -> tuple[NativeItem, ...]:
        if isinstance(part, AIThinkingPart):
            if part.id == "redacted_thinking":
                if not part.signature:
                    raise InvalidProviderResponseError(
                        "Anthropic redacted thinking is missing its signature"
                    )
                return (
                    NativeItem(
                        identity.provider,
                        identity.protocol,
                        identity.model,
                        sequence_index=index,
                        kind="redacted_thinking",
                        payload={
                            "type": "redacted_thinking",
                            "data": part.signature,
                        },
                    ),
                )
            return (
                NativeItem(
                    identity.provider,
                    identity.protocol,
                    identity.model,
                    sequence_index=index,
                    kind="thinking",
                    payload={
                        "type": "thinking",
                        "thinking": part.content,
                        "signature": part.signature,
                    },
                ),
            )

        if isinstance(part, AITextPart):
            return (
                NativeItem(
                    identity.provider,
                    identity.protocol,
                    identity.model,
                    sequence_index=index,
                    kind="text",
                    payload={"type": "text", "text": part.content},
                ),
            )

        if isinstance(part, AIToolCallPart):
            return (
                NativeItem(
                    identity.provider,
                    identity.protocol,
                    identity.model,
                    sequence_index=index,
                    kind="tool_use",
                    payload={
                        "type": "tool_use",
                        "id": part.tool_call_id,
                        "name": part.tool_name,
                        "input": dict(part.args_as_dict() or {}),
                    },
                ),
            )
        return ()

    def bind_stream(self, model_stream: Any) -> None:
        self._recorder = record_model_stream(model_stream)

    def validate_stream(self, model_stream: Any, response: Any) -> None:
        del model_stream, response
        recorder = getattr(self, "_recorder", None)
        if recorder is None:
            return
        names = {type(event).__name__ for event in recorder.events}
        if "BetaRawMessageStopEvent" not in names:
            raise InvalidProviderResponseError(
                "Anthropic stream ended without a message_stop event"
            )
        stop_reasons = {
            getattr(getattr(event, "delta", None), "stop_reason", None)
            for event in recorder.events
            if type(event).__name__ == "BetaRawMessageDeltaEvent"
        }
        if not any(isinstance(reason, str) and reason for reason in stop_reasons):
            raise InvalidProviderResponseError(
                "Anthropic stream ended without a stop reason"
            )


def build_anthropic_provider(
    model_name: str,
    *,
    client: Any | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    http_client: Any | None = None,
    profile: Any | None = None,
    settings: Any | None = None,
) -> PydanticAIProvider:
    """Build an Anthropic Messages ProviderPort without making a request."""

    if client is not None:
        sdk_provider = SDKAnthropicProvider(anthropic_client=client)
    else:
        sdk_provider = SDKAnthropicProvider(
            api_key=api_key,
            base_url=base_url,
            http_client=http_client,
        )
    model = AnthropicModel(
        model_name,
        provider=sdk_provider,
        profile=profile,
        settings=settings,
    )
    identity = ProviderIdentity("anthropic", "messages", model_name)
    return PydanticAIProvider(model, identity, codec=AnthropicCodec())


__all__ = ["AnthropicCodec", "build_anthropic_provider"]
