"""OpenAI-compatible Chat Completions protocol integration.

This module deliberately contains only Chat Completions mappings. Responses
output-item shapes live in ``openai_responses.py`` and are not used here.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from pydantic_ai.messages import (
    TextPart as AITextPart,
    ThinkingPart as AIThinkingPart,
    ToolCallPart as AIToolCallPart,
)
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider as SDKOpenAIProvider

from uthcode.core.provider import (
    InvalidProviderResponseError,
    NativeItem,
    ProviderIdentity,
    ReasoningPart,
    TextPart,
    ToolCallPart,
    Usage,
)

from .pydantic_ai import (
    PydanticAICodec,
    PydanticAIProvider,
    _plain_json,
    record_model_stream,
)


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


class OpenAICompatCodec(PydanticAICodec):
    """Encode Chat assistant history and capture bounded carrier snapshots."""

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
            kinds={"assistant_text", "reasoning_carrier", "assistant_tool_call"},
        )
        payload = native.payload if native is not None else {}

        if isinstance(part, ReasoningPart):
            field = payload.get("field", "reasoning_content")
            if not isinstance(field, str) or not field:
                raise InvalidProviderResponseError(
                    "Chat reasoning carrier field must be a non-empty string"
                )
            return AIThinkingPart(
                part.text,
                id=field,
                provider_name=identity.provider if native is not None else None,
            )
        if isinstance(part, TextPart):
            return AITextPart(part.text)
        if isinstance(part, ToolCallPart):
            return AIToolCallPart(
                tool_name=part.name,
                args=dict(part.arguments),
                tool_call_id=part.tool_call_id,
                id=payload.get("id") if isinstance(payload.get("id"), str) else None,
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
        if getattr(self, "_recorder", None) is not None:
            # Indexed tool calls can receive more argument deltas after a
            # different index starts. Publish their native snapshots only
            # from the final normalized response.
            return ()
        return self._native_items_for_part(part, index=index, identity=identity)

    def _native_items_for_part(
        self,
        part: Any,
        *,
        index: int,
        identity: ProviderIdentity,
    ) -> tuple[NativeItem, ...]:
        if isinstance(part, AIThinkingPart):
            return (
                NativeItem(
                    identity.provider,
                    identity.protocol,
                    identity.model,
                    sequence_index=index,
                    kind="reasoning_carrier",
                    payload={
                        "type": "reasoning_carrier",
                        "field": "reasoning_content",
                        "content": part.content,
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
                    kind="assistant_text",
                    payload={
                        "type": "assistant_text",
                        "content": part.content,
                    },
                ),
            )
        if isinstance(part, AIToolCallPart):
            stream_index = self._stream_index_for_tool(part.tool_call_id, index)
            return (
                NativeItem(
                    identity.provider,
                    identity.protocol,
                    identity.model,
                    sequence_index=index,
                    kind="assistant_tool_call",
                    payload={
                        "type": "assistant_tool_call",
                        "index": stream_index,
                        "id": part.tool_call_id,
                        "name": part.tool_name,
                        "arguments": part.args_as_json_str(),
                    },
                ),
            )
        return ()

    def native_items_for_response(
        self,
        response: Any,
        *,
        identity: ProviderIdentity,
    ) -> tuple[NativeItem, ...]:
        if getattr(self, "_recorder", None) is None:
            return ()
        return tuple(
            item
            for index, part in enumerate(response.parts)
            for item in self._native_items_for_part(part, index=index, identity=identity)
        )

    def bind_stream(self, model_stream: Any) -> None:
        self._recorder = record_model_stream(model_stream)

    def _stream_index_for_tool(self, tool_call_id: str, fallback: int) -> int:
        recorder = getattr(self, "_recorder", None)
        if recorder is None:
            return fallback
        for event in recorder.events:
            for choice in getattr(event, "choices", ()):
                for tool_call in getattr(getattr(choice, "delta", None), "tool_calls", ()) or ():
                    if getattr(tool_call, "id", None) == tool_call_id:
                        index = getattr(tool_call, "index", None)
                        if isinstance(index, int):
                            return index
        return fallback

    def validate_stream(self, model_stream: Any, response: Any) -> None:
        del model_stream, response
        recorder = getattr(self, "_recorder", None)
        if recorder is None:
            return
        finish_reasons = {
            getattr(choice, "finish_reason", None)
            for event in recorder.events
            if type(event).__name__ == "ChatCompletionChunk"
            for choice in getattr(event, "choices", ())
        }
        if not any(isinstance(reason, str) and reason for reason in finish_reasons):
            raise InvalidProviderResponseError(
                "Chat Completions stream ended without a finish reason"
            )

    def usage_from_model_response(self, response: Any) -> Usage | None:
        del response
        recorder = getattr(self, "_recorder", None)
        if recorder is None:
            return None
        raw_usage = next(
            (
                getattr(event, "usage", None)
                for event in reversed(recorder.events)
                if getattr(event, "usage", None) is not None
            ),
            None,
        )
        if raw_usage is None:
            return None
        payload = raw_usage.model_dump(mode="json") if hasattr(raw_usage, "model_dump") else raw_usage
        plain = _plain_json(payload)
        if not isinstance(plain, dict):
            raise InvalidProviderResponseError("Chat usage must be a JSON object")
        prompt_details = plain.get("prompt_tokens_details")
        if prompt_details is None:
            prompt_details = {}
        if not isinstance(prompt_details, dict):
            raise InvalidProviderResponseError("Chat prompt token details must be an object")
        completion_details = plain.get("completion_tokens_details")
        if completion_details is None:
            completion_details = {}
        if not isinstance(completion_details, dict):
            raise InvalidProviderResponseError("Chat completion token details must be an object")
        cache_read = prompt_details.get("cached_tokens", 0) or 0
        cache_write = prompt_details.get("cache_write_tokens", 0) or 0
        if not isinstance(cache_read, int) or not isinstance(cache_write, int):
            raise InvalidProviderResponseError("Chat cache usage values must be integers")
        details = dict(plain)
        details["reasoning_tokens"] = completion_details.get("reasoning_tokens", 0) or 0
        return Usage(
            input_tokens=plain.get("prompt_tokens", 0),
            output_tokens=plain.get("completion_tokens", 0),
            total_tokens=plain.get("total_tokens"),
            cache_read_tokens=cache_read,
            cache_write_tokens=cache_write,
            details=details,
        )


def build_openai_compat_provider(
    model_name: str,
    *,
    base_url: str,
    client: Any | None = None,
    api_key: str | None = None,
    http_client: Any | None = None,
    profile: Any | None = None,
    settings: Any | None = None,
) -> PydanticAIProvider:
    """Build a Chat Completions ProviderPort for a supplied base URL."""

    if client is not None:
        sdk_provider = SDKOpenAIProvider(openai_client=client)
    else:
        sdk_provider = SDKOpenAIProvider(
            base_url=base_url,
            api_key=api_key,
            http_client=http_client,
        )
    resolved_profile = profile or {
        "openai_chat_thinking_field": "reasoning_content",
        "openai_chat_send_back_thinking_parts": "field",
    }
    model = OpenAIChatModel(
        model_name,
        provider=sdk_provider,
        profile=resolved_profile,
        settings=settings,
    )
    identity = ProviderIdentity("openai", "chat_completions", model_name)
    return PydanticAIProvider(model, identity, codec=OpenAICompatCodec())


__all__ = ["OpenAICompatCodec", "build_openai_compat_provider"]
