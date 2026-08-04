"""OpenAI Responses protocol integration.

Responses output items are recorded and validated here because the shared
Direct bridge intentionally sees only normalized Pydantic AI parts. Chat
Completions never imports this module or its item shapes.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from pydantic_ai.messages import (
    TextPart as AITextPart,
    ThinkingPart as AIThinkingPart,
    ToolCallPart as AIToolCallPart,
)
from pydantic_ai.models.openai import OpenAIResponsesModel
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


def _dump(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    plain = _plain_json(value)
    if not isinstance(plain, dict):
        raise InvalidProviderResponseError("Responses item must be a JSON object")
    return plain


def _item_id(item: Any) -> str | None:
    value = getattr(item, "id", None)
    return value if isinstance(value, str) else None


def _call_id(item: Any) -> str | None:
    value = getattr(item, "call_id", None)
    return value if isinstance(value, str) else None


class OpenAIResponsesCodec(PydanticAICodec):
    """Encode Responses reasoning/output items and validate stream identity."""

    capture_provider_details = False

    def __init__(self) -> None:
        self._recorder = None
        self._handled_item_ids: set[str] = set()
        self._forwarded_frames: dict[tuple[Any, ...], str] = {}

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
            kinds={"reasoning", "message", "function_call"},
        )
        payload = native.payload if native is not None else {}

        if isinstance(part, ReasoningPart):
            signature = payload.get("encrypted_content")
            if signature is not None and not isinstance(signature, str):
                raise InvalidProviderResponseError(
                    "Responses encrypted reasoning content must be a string"
                )
            details = payload.get("content")
            raw_content = None
            if isinstance(details, list):
                raw_content = [
                    item["text"]
                    for item in details
                    if isinstance(item, dict) and isinstance(item.get("text"), str)
                ]
            return AIThinkingPart(
                part.text,
                id=payload.get("id") if isinstance(payload.get("id"), str) else None,
                signature=signature,
                provider_name=identity.provider if native is not None else None,
                provider_details={"raw_content": raw_content} if raw_content else None,
            )

        if isinstance(part, TextPart):
            return AITextPart(
                part.text,
                id=payload.get("id") if isinstance(payload.get("id"), str) else None,
                provider_name=identity.provider if native is not None else None,
            )

        if isinstance(part, ToolCallPart):
            details = payload.get("namespace")
            return AIToolCallPart(
                tool_name=part.name,
                args=dict(part.arguments),
                tool_call_id=part.tool_call_id,
                id=payload.get("id") if isinstance(payload.get("id"), str) else None,
                provider_name=identity.provider if native is not None else None,
                provider_details={"namespace": details} if isinstance(details, str) else None,
            )

        return super().encode_assistant_part(
            part,
            index=index,
            native_items=native_items,
            identity=identity,
        )

    def _raw_item_for_part(self, part: Any) -> tuple[dict[str, Any], int] | None:
        recorder = self._recorder
        if recorder is None:
            return None
        target_id = getattr(part, "id", None)
        target_call_id = getattr(part, "tool_call_id", None)
        candidates: list[tuple[dict[str, Any], int]] = []
        for event in recorder.events:
            if type(event).__name__ != "ResponseOutputItemDoneEvent":
                continue
            item = getattr(event, "item", None)
            if item is None:
                continue
            if target_id is not None and _item_id(item) == target_id:
                candidates.append((_dump(item), getattr(event, "output_index", 0)))
            elif target_call_id is not None and _call_id(item) == target_call_id:
                candidates.append((_dump(item), getattr(event, "output_index", 0)))
        if not candidates:
            return None
        return candidates[-1]

    def native_items_for_part(
        self,
        part: Any,
        *,
        index: int,
        identity: ProviderIdentity,
    ) -> tuple[NativeItem, ...]:
        raw = self._raw_item_for_part(part)
        if raw is not None:
            payload, output_index = raw
            item_id = payload.get("id")
            if isinstance(item_id, str):
                self._handled_item_ids.add(item_id)
            return (
                NativeItem(
                    identity.provider,
                    identity.protocol,
                    identity.model,
                    sequence_index=output_index,
                    kind=str(payload.get("type", "output_item")),
                    payload=payload,
                ),
            )

        # A streamed item can end before its terminal output_item.done frame
        # arrives. Do not publish a provisional added snapshot; the final
        # response pass will publish the completed item exactly once.
        if self._recorder is not None:
            return ()

        if isinstance(part, AIThinkingPart):
            payload = {
                "type": "reasoning",
                "id": part.id or f"reasoning-{index}",
                "summary": [{"type": "summary_text", "text": part.content}],
                "encrypted_content": part.signature,
            }
            return (
                NativeItem(
                    identity.provider,
                    identity.protocol,
                    identity.model,
                    sequence_index=index,
                    kind="reasoning",
                    payload=payload,
                ),
            )
        if isinstance(part, AITextPart):
            payload = {
                "type": "message",
                "id": part.id or f"message-{index}",
                "role": "assistant",
                "content": [{"type": "output_text", "text": part.content}],
                "output_index": index,
            }
            return (
                NativeItem(
                    identity.provider,
                    identity.protocol,
                    identity.model,
                    sequence_index=index,
                    kind="message",
                    payload=payload,
                ),
            )
        if isinstance(part, AIToolCallPart):
            payload = {
                "type": "function_call",
                "id": getattr(part, "id", None) or part.tool_call_id,
                "call_id": part.tool_call_id,
                "name": part.tool_name,
                "arguments": part.args_as_json_str(),
                "output_index": index,
            }
            return (
                NativeItem(
                    identity.provider,
                    identity.protocol,
                    identity.model,
                    sequence_index=index,
                    kind="function_call",
                    payload=payload,
                ),
            )
        return ()

    def native_items_for_response(
        self,
        response: Any,
        *,
        identity: ProviderIdentity,
    ) -> tuple[NativeItem, ...]:
        del response
        recorder = self._recorder
        if recorder is None:
            return ()
        result: list[NativeItem] = []
        for event in recorder.events:
            if type(event).__name__ != "ResponseOutputItemDoneEvent":
                continue
            item = getattr(event, "item", None)
            item_id = _item_id(item)
            if item_id is not None and item_id in self._handled_item_ids:
                continue
            payload = _dump(item)
            result.append(
                NativeItem(
                    identity.provider,
                    identity.protocol,
                    identity.model,
                    sequence_index=getattr(event, "output_index", len(result)),
                    kind=str(payload.get("type", "output_item")),
                    payload=payload,
                )
            )
            if item_id is not None:
                self._handled_item_ids.add(item_id)
        return tuple(result)

    def usage_from_model_response(self, response: Any) -> Usage | None:
        del response
        recorder = self._recorder
        if recorder is None:
            return None
        terminal = next(
            (
                event
                for event in reversed(recorder.events)
                if type(event).__name__
                in {
                    "ResponseCompletedEvent",
                    "ResponseIncompleteEvent",
                    "ResponseFailedEvent",
                }
            ),
            None,
        )
        raw_response = getattr(terminal, "response", None)
        raw_usage = getattr(raw_response, "usage", None)
        if raw_usage is None:
            return None
        usage_payload = _dump(raw_usage)
        input_details = usage_payload.get("input_tokens_details", {})
        if not isinstance(input_details, dict):
            raise InvalidProviderResponseError(
                "Responses input token details must be a JSON object"
            )
        cache_read = input_details.get("cached_tokens", 0)
        cache_write = input_details.get("cache_write_tokens", 0)
        if not isinstance(cache_read, int) or not isinstance(cache_write, int):
            raise InvalidProviderResponseError(
                "Responses cache usage values must be integers"
            )
        return Usage(
            input_tokens=usage_payload.get("input_tokens", 0),
            output_tokens=usage_payload.get("output_tokens", 0),
            total_tokens=usage_payload.get("total_tokens"),
            cache_read_tokens=cache_read,
            cache_write_tokens=cache_write,
            details=usage_payload,
        )

    def bind_stream(self, model_stream: Any) -> None:
        self._handled_item_ids.clear()
        self._forwarded_frames.clear()
        self._recorder = record_model_stream(model_stream, filter_event=self._filter_event)

    @staticmethod
    def _signature(value: Any) -> str:
        if hasattr(value, "model_dump"):
            value = value.model_dump(mode="json")
        return json.dumps(_plain_json(value), ensure_ascii=False, sort_keys=True)

    def validate_stream(self, model_stream: Any, response: Any) -> None:
        del model_stream, response
        recorder = self._recorder
        if recorder is None:
            return

        terminal_events = [
            event
            for event in recorder.events
            if type(event).__name__
            in {
                "ResponseCompletedEvent",
                "ResponseIncompleteEvent",
                "ResponseFailedEvent",
            }
        ]
        if not terminal_events:
            raise InvalidProviderResponseError(
                "Responses stream ended without a terminal response event"
            )
        terminal_signatures = {self._signature(getattr(event, "response", None)) for event in terminal_events}
        if len(terminal_signatures) > 1:
            raise InvalidProviderResponseError(
                "Responses terminal snapshots conflict"
            )
        if type(terminal_events[0]).__name__ != "ResponseCompletedEvent":
            raise InvalidProviderResponseError(
                "Responses stream did not complete successfully"
            )

        self._validate_duplicate_frames(recorder.events)
        self._validate_function_calls(recorder.events)

    def _validate_duplicate_frames(self, events: Sequence[Any]) -> None:
        seen: dict[tuple[Any, ...], str] = {}
        for event in events:
            key = self._frame_key(event)
            if key is None:
                continue
            signature = self._signature(event)
            previous = seen.get(key)
            if previous is not None and previous != signature:
                raise InvalidProviderResponseError(
                    "Responses stream contains conflicting duplicate frames"
                )
            seen[key] = signature

    @staticmethod
    def _frame_key(event: Any) -> tuple[Any, ...] | None:
        name = type(event).__name__
        if name in {
            "ResponseFunctionCallArgumentsDeltaEvent",
            "ResponseFunctionCallArgumentsDoneEvent",
            "ResponseReasoningSummaryTextDeltaEvent",
            "ResponseReasoningSummaryTextDoneEvent",
            "ResponseTextDeltaEvent",
            "ResponseTextDoneEvent",
        }:
            return (
                name,
                getattr(event, "item_id", None),
                getattr(event, "output_index", None),
                getattr(event, "content_index", None),
                getattr(event, "summary_index", None),
                getattr(event, "sequence_number", None),
            )
        if name in {"ResponseOutputItemAddedEvent", "ResponseOutputItemDoneEvent"}:
            item = getattr(event, "item", None)
            return (name, _item_id(item), getattr(event, "output_index", None))
        if name in {
            "ResponseCompletedEvent",
            "ResponseIncompleteEvent",
            "ResponseFailedEvent",
        }:
            response = getattr(event, "response", None)
            return ("terminal", getattr(response, "id", None))
        return None

    def _filter_event(self, event: Any) -> bool:
        key = self._frame_key(event)
        if key is None:
            return True
        signature = self._signature(event)
        previous = self._forwarded_frames.get(key)
        if previous is not None:
            if previous != signature:
                raise InvalidProviderResponseError(
                    "Responses stream contains conflicting duplicate frames"
                )
            return False
        self._forwarded_frames[key] = signature
        return True

    def _validate_function_calls(self, events: Sequence[Any]) -> None:
        added: dict[str, Any] = {}
        done: set[str] = set()
        for event in events:
            name = type(event).__name__
            if name == "ResponseOutputItemAddedEvent":
                item = getattr(event, "item", None)
                if getattr(item, "type", None) == "function_call":
                    item_id = _item_id(item)
                    if item_id:
                        added[item_id] = item
            elif name == "ResponseOutputItemDoneEvent":
                item = getattr(event, "item", None)
                if getattr(item, "type", None) == "function_call":
                    item_id = _item_id(item)
                    if item_id:
                        done.add(item_id)
                        self._require_json_arguments(getattr(item, "arguments", None))
        unfinished = set(added) - done
        if unfinished:
            raise InvalidProviderResponseError(
                "Responses stream ended with an unfinished function call"
            )

    @staticmethod
    def _require_json_arguments(arguments: Any) -> None:
        if not isinstance(arguments, str):
            raise InvalidProviderResponseError(
                "Responses function call arguments must be JSON text"
            )
        try:
            parsed = json.loads(arguments)
        except json.JSONDecodeError as exc:
            raise InvalidProviderResponseError(
                "Responses function call arguments are invalid JSON"
            ) from exc
        if not isinstance(parsed, dict):
            raise InvalidProviderResponseError(
                "Responses function call arguments must be a JSON object"
            )


def build_openai_responses_provider(
    model_name: str,
    *,
    client: Any | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    http_client: Any | None = None,
    profile: Any | None = None,
    settings: Any | None = None,
) -> PydanticAIProvider:
    """Build an OpenAI Responses ProviderPort without making a request."""

    if client is not None:
        sdk_provider = SDKOpenAIProvider(openai_client=client)
    else:
        sdk_provider = SDKOpenAIProvider(
            api_key=api_key,
            base_url=base_url,
            http_client=http_client,
        )
    resolved_profile = profile or {
        "openai_supports_encrypted_reasoning_content": True,
        "openai_supports_reasoning": True,
        "supports_thinking": True,
    }
    model = OpenAIResponsesModel(
        model_name,
        provider=sdk_provider,
        profile=resolved_profile,
        settings=settings,
    )
    identity = ProviderIdentity("openai", "responses", model_name)
    return PydanticAIProvider(model, identity, codec=OpenAIResponsesCodec())


__all__ = ["OpenAIResponsesCodec", "build_openai_responses_provider"]
