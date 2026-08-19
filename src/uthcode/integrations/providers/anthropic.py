"""Native Anthropic Messages Provider integration."""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass

from anthropic import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncAnthropic,
    AuthenticationError as SDKAuthenticationError,
    PermissionDeniedError,
    RateLimitError as SDKRateLimitError,
)

from uthcode.core.provider import (
    AuthenticationError,
    CancellationToken,
    ContextCountEstimate,
    ContextOverflowError,
    FinishReason,
    GenerationCancelled,
    GenerationCompleted,
    GenerationRequest,
    InvalidProviderResponseError,
    Message,
    ModelLimits,
    NativeItem,
    NativeItemCompleted,
    NetworkError,
    ProviderError,
    ProviderEvent,
    ProviderIdentity,
    ProviderPort,
    ProviderResponse,
    RateLimitError,
    ReasoningDelta,
    ReasoningPart,
    TextDelta,
    TextPart,
    ToolCallArgumentsDelta,
    ToolCallCompleted,
    ToolCallPart,
    ToolCallStarted,
    ToolDefinition,
    ToolResultPart,
    Usage,
)

from .common import (
    close_stream,
    next_stream_value,
    plain_json,
    raise_if_cancelled,
    require_json_object,
    usage_int,
)


_DEFAULT_MAX_OUTPUT_TOKENS = 4096


@dataclass(slots=True)
class _ContentBlockState:
    index: int
    kind: str
    text: str = ""
    signature: str = ""
    redacted_data: str = ""
    tool_call_id: str = ""
    tool_name: str = ""
    arguments: str = ""
    closed: bool = False


def _field(value: object, name: str, default: object = None) -> object:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _positive_optional_int(value: object, *, allow_zero: bool = False) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value < 0 or (value == 0 and not allow_zero):
        return None
    return value


def _text(value: object, label: str, *, allow_empty: bool = True) -> str:
    if not isinstance(value, str) or (not allow_empty and not value):
        raise InvalidProviderResponseError(f"Anthropic {label} is invalid")
    return value


def _message_text(message: Message) -> str:
    values: list[str] = []
    for part in message.parts:
        if isinstance(part, (TextPart, ReasoningPart)):
            values.append(part.text)
        elif isinstance(part, ToolResultPart):
            values.append(part.content)
        else:
            raise InvalidProviderResponseError(
                "Anthropic message contains an unsupported part"
            )
    return "".join(values)


def _native_at(
    message: Message,
    identity: ProviderIdentity,
    index: int,
    kinds: set[str],
) -> NativeItem | None:
    for item in message.native_items_for(identity):
        if item.sequence_index == index and item.kind in kinds:
            return item
    return None


def _assistant_content(
    message: Message,
    identity: ProviderIdentity,
) -> list[dict[str, object]]:
    content: list[dict[str, object]] = []
    for index, part in enumerate(message.parts):
        if isinstance(part, ReasoningPart):
            native = _native_at(message, identity, index, {"thinking", "redacted_thinking"})
            if native is None:
                # Reasoning without this protocol's signed native item is a
                # standard Core part and is sent as ordinary assistant text.
                content.append({"type": "text", "text": part.text})
                continue
            if native.kind == "redacted_thinking":
                data = native.payload.get("data")
                if not isinstance(data, str):
                    raise InvalidProviderResponseError(
                        "Anthropic redacted thinking data is invalid"
                    )
                content.append({"type": "redacted_thinking", "data": data})
                continue
            signature = native.payload.get("signature")
            if not isinstance(signature, str) or not signature:
                raise InvalidProviderResponseError(
                    "Anthropic thinking signature is invalid"
                )
            content.append(
                {
                    "type": "thinking",
                    "thinking": part.text,
                    "signature": signature,
                }
            )
        elif isinstance(part, TextPart):
            content.append({"type": "text", "text": part.text})
        elif isinstance(part, ToolCallPart):
            native = _native_at(message, identity, index, {"tool_use"})
            tool_call_id = part.tool_call_id
            name = part.name
            arguments = dict(part.arguments)
            if native is not None:
                raw_id = native.payload.get("id")
                raw_name = native.payload.get("name")
                if isinstance(raw_id, str) and raw_id:
                    tool_call_id = raw_id
                if isinstance(raw_name, str) and raw_name:
                    name = raw_name
                arguments = require_json_object(
                    native.payload.get("input", arguments),
                    "Anthropic tool input",
                )
            content.append(
                {
                    "type": "tool_use",
                    "id": tool_call_id,
                    "name": name,
                    "input": arguments,
                }
            )
        else:
            raise InvalidProviderResponseError("Anthropic assistant part is unsupported")
    return content


def _message_blocks(message: Message, identity: ProviderIdentity) -> list[dict[str, object]]:
    if message.role == "assistant":
        return _assistant_content(message, identity)
    if message.role == "user":
        return [{"type": "text", "text": _message_text(message)}]
    if message.role == "tool":
        blocks: list[dict[str, object]] = []
        for part in message.parts:
            if not isinstance(part, ToolResultPart):
                raise InvalidProviderResponseError(
                    "Anthropic tool message contains an unsupported part"
                )
            blocks.append(
                {
                    "type": "tool_result",
                    "tool_use_id": part.tool_call_id,
                    "content": part.content,
                    "is_error": part.is_error,
                }
            )
        return blocks
    raise InvalidProviderResponseError(f"Anthropic message role is unsupported: {message.role}")


def _request_messages(
    request: GenerationRequest,
    identity: ProviderIdentity,
) -> list[dict[str, object]]:
    messages: list[dict[str, object]] = []
    for message in request.messages:
        role = "assistant" if message.role == "assistant" else "user"
        messages.append(
            {
                "role": role,
                "content": _message_blocks(message, identity),
            }
        )
    return messages


def _request_tools(tools: Sequence[ToolDefinition]) -> list[dict[str, object]]:
    return [
        {
            "name": tool.name,
            "description": tool.description or "",
            "input_schema": require_json_object(tool.parameters, "Anthropic input schema"),
        }
        for tool in tools
    ]


def _finish_reason(value: str) -> FinishReason:
    return {
        "end_turn": FinishReason.STOP,
        "stop_sequence": FinishReason.STOP,
        "tool_use": FinishReason.TOOL_CALLS,
        "max_tokens": FinishReason.LENGTH,
        "pause_turn": FinishReason.STOP,
    }.get(value, FinishReason.UNKNOWN)


def _map_error(error: BaseException) -> ProviderError:
    if isinstance(error, GenerationCancelled):
        return error
    if isinstance(error, InvalidProviderResponseError):
        return InvalidProviderResponseError()
    if isinstance(error, (SDKAuthenticationError, PermissionDeniedError)):
        return AuthenticationError()
    if isinstance(error, SDKRateLimitError):
        return RateLimitError()
    if isinstance(error, (APIConnectionError, APITimeoutError, TimeoutError, OSError)):
        return NetworkError()
    if isinstance(error, APIStatusError):
        if error.status_code in {401, 403}:
            return AuthenticationError()
        if error.status_code == 429:
            return RateLimitError()
        if error.status_code == 413:
            return ContextOverflowError()
        return ProviderError()
    return ProviderError()


class AnthropicProvider:
    """Directly map the public Anthropic Messages API to Core events."""

    def __init__(
        self,
        model_name: str,
        client: AsyncAnthropic,
        *,
        max_output_tokens: int | None = None,
    ) -> None:
        self._model_name = model_name
        self._client = client
        self._max_output_tokens = max_output_tokens
        self._identity = ProviderIdentity("anthropic", "messages", model_name)

    @property
    def identity(self) -> ProviderIdentity:
        return self._identity

    async def resolve_model_limits(self, model: str) -> ModelLimits | None:
        """Read reliable runtime limits when the configured client exposes them."""

        if not isinstance(model, str) or not model:
            raise ValueError("model must be a non-empty string")
        models_api = getattr(self._client, "models", None)
        retrieve = getattr(models_api, "retrieve", None)
        if not callable(retrieve):
            return None
        value = retrieve(model)
        if inspect.isawaitable(value):
            value = await value
        max_input = _positive_optional_int(
            _field(value, "max_input_tokens"),
        )
        max_output = _positive_optional_int(
            _field(value, "max_tokens"),
        )
        if max_input is None and max_output is None:
            return None
        return ModelLimits(
            max_input_tokens=max_input,
            max_output_tokens=max_output,
            source="anthropic.models",
        )

    async def count_input_tokens(
        self,
        request: GenerationRequest,
    ) -> ContextCountEstimate | None:
        """Use Anthropic's structured count endpoint without exposing SDK DTOs."""

        if not isinstance(request, GenerationRequest):
            raise TypeError("request must be a GenerationRequest")
        messages_api = getattr(self._client, "messages", None)
        count_tokens = getattr(messages_api, "count_tokens", None)
        if not callable(count_tokens):
            return None
        kwargs: dict[str, object] = {
            "model": request.model or self._model_name,
            "messages": _request_messages(request, self._identity),
        }
        if request.system_prompt is not None:
            kwargs["system"] = request.system_prompt
        if request.tools:
            kwargs["tools"] = _request_tools(request.tools)
        value = count_tokens(**kwargs)
        if inspect.isawaitable(value):
            value = await value
        input_tokens = _positive_optional_int(_field(value, "input_tokens"), allow_zero=True)
        if input_tokens is None:
            return None
        return ContextCountEstimate(
            input_tokens=input_tokens,
            source="anthropic.messages.count_tokens",
            kind="preflight_provider_count",
        )

    async def stream(
        self,
        request: GenerationRequest,
        *,
        cancellation: CancellationToken,
    ) -> AsyncIterator[ProviderEvent]:
        raise_if_cancelled(cancellation)
        stream: object | None = None
        mapped_error: ProviderError | None = None
        completed: ProviderResponse | None = None
        try:
            messages = _request_messages(request, self._identity)
            max_output_tokens = (
                request.max_output_tokens
                if request.max_output_tokens is not None
                else self._max_output_tokens
                if self._max_output_tokens is not None
                else _DEFAULT_MAX_OUTPUT_TOKENS
            )
            kwargs: dict[str, object] = {
                "model": request.model or self._model_name,
                "messages": messages,
                "max_tokens": max_output_tokens,
                "stream": True,
            }
            if request.system_prompt is not None:
                kwargs["system"] = request.system_prompt
            if request.tools:
                kwargs["tools"] = _request_tools(request.tools)
            if request.temperature is not None:
                kwargs["temperature"] = request.temperature
            if request.reasoning is not None and request.reasoning.enabled:
                budget = request.reasoning.budget_tokens
                if budget is None:
                    budget = min(4096, max(1, max_output_tokens - 1))
                kwargs["thinking"] = {"type": "enabled", "budget_tokens": budget}

            messages_api = getattr(self._client, "messages", None)
            create = getattr(messages_api, "create", None)
            if not callable(create):
                raise ProviderError()
            stream = await create(**kwargs)
            iterator = aiter(stream)
            blocks: dict[int, _ContentBlockState] = {}
            native_items: list[NativeItem] = []
            parts_by_index: dict[int, TextPart | ReasoningPart | ToolCallPart] = {}
            message_start_seen = False
            message_stop_seen = False
            stop_reason: str | None = None
            input_tokens = 0
            output_tokens = 0
            cache_read_tokens = 0
            cache_write_tokens = 0
            cache_read_reported = False
            cache_write_reported = False

            while True:
                try:
                    event = await next_stream_value(iterator, cancellation)
                except StopAsyncIteration:
                    break
                event_type = _field(event, "type")
                if not isinstance(event_type, str):
                    raise InvalidProviderResponseError("Anthropic event type is invalid")
                if message_stop_seen:
                    raise InvalidProviderResponseError(
                        "Anthropic stream produced data after message_stop"
                    )

                if event_type == "message_start":
                    if message_start_seen:
                        raise InvalidProviderResponseError(
                            "Anthropic stream repeated message_start"
                        )
                    message_start_seen = True
                    usage = _field(_field(event, "message"), "usage")
                    input_tokens = usage_int(
                        _field(usage, "input_tokens"), "Anthropic input tokens"
                    )
                    cache_read_tokens = usage_int(
                        _field(usage, "cache_read_input_tokens"),
                        "Anthropic cache read tokens",
                        default=cache_read_tokens,
                    )
                    if _field(usage, "cache_read_input_tokens") is not None:
                        cache_read_reported = True
                    cache_write_tokens = usage_int(
                        _field(usage, "cache_creation_input_tokens"),
                        "Anthropic cache write tokens",
                        default=cache_write_tokens,
                    )
                    if _field(usage, "cache_creation_input_tokens") is not None:
                        cache_write_reported = True
                elif event_type == "content_block_start":
                    index = _field(event, "index")
                    if isinstance(index, bool) or not isinstance(index, int) or index < 0:
                        raise InvalidProviderResponseError(
                            "Anthropic content block index is invalid"
                        )
                    if index in blocks:
                        raise InvalidProviderResponseError(
                            "Anthropic content block index repeated"
                        )
                    block = _field(event, "content_block")
                    kind = _text(_field(block, "type"), "content block type", allow_empty=False)
                    state = _ContentBlockState(index=index, kind=kind)
                    if kind == "text":
                        state.text = _text(_field(block, "text", ""), "text block")
                    elif kind == "thinking":
                        state.text = _text(_field(block, "thinking", ""), "thinking block")
                        state.signature = _text(
                            _field(block, "signature", ""), "thinking signature"
                        )
                    elif kind == "redacted_thinking":
                        state.redacted_data = _text(
                            _field(block, "data", ""), "redacted thinking data"
                        )
                    elif kind == "tool_use":
                        state.tool_call_id = _text(
                            _field(block, "id"), "tool call id", allow_empty=False
                        )
                        state.tool_name = _text(
                            _field(block, "name"), "tool name", allow_empty=False
                        )
                        initial_input = require_json_object(
                            _field(block, "input", {}), "Anthropic tool input"
                        )
                        if initial_input:
                            state.arguments = json.dumps(
                                initial_input,
                                ensure_ascii=False,
                                separators=(",", ":"),
                            )
                        yield ToolCallStarted(
                            state.tool_call_id,
                            state.tool_name,
                            sequence_index=index,
                        )
                    else:
                        raise InvalidProviderResponseError(
                            "Anthropic content block type is unsupported"
                        )
                    blocks[index] = state
                elif event_type == "content_block_delta":
                    index = _field(event, "index")
                    if (
                        isinstance(index, bool)
                        or not isinstance(index, int)
                        or index not in blocks
                    ):
                        raise InvalidProviderResponseError(
                            "Anthropic content block delta index is invalid"
                        )
                    state = blocks[index]
                    if state.closed:
                        raise InvalidProviderResponseError(
                            "Anthropic content block delta arrived after stop"
                        )
                    delta = _field(event, "delta")
                    delta_type = _text(
                        _field(delta, "type"), "content delta type", allow_empty=False
                    )
                    if delta_type == "text_delta":
                        text = _text(_field(delta, "text"), "text delta")
                        state.text += text
                        if text:
                            yield TextDelta(text)
                    elif delta_type == "thinking_delta":
                        text = _text(_field(delta, "thinking"), "thinking delta")
                        state.text += text
                        if text:
                            yield ReasoningDelta(text)
                    elif delta_type == "signature_delta":
                        signature = _text(
                            _field(delta, "signature"), "thinking signature delta"
                        )
                        state.signature += signature
                    elif delta_type == "input_json_delta":
                        partial = _text(
                            _field(delta, "partial_json"), "tool arguments delta"
                        )
                        state.arguments += partial
                        if partial:
                            yield ToolCallArgumentsDelta(
                                state.tool_call_id,
                                partial,
                                sequence_index=index,
                            )
                    else:
                        raise InvalidProviderResponseError(
                            "Anthropic content delta type is unsupported"
                        )
                elif event_type == "content_block_stop":
                    index = _field(event, "index")
                    if (
                        isinstance(index, bool)
                        or not isinstance(index, int)
                        or index not in blocks
                    ):
                        raise InvalidProviderResponseError(
                            "Anthropic content block stop index is invalid"
                        )
                    state = blocks[index]
                    if state.closed:
                        raise InvalidProviderResponseError(
                            "Anthropic content block stopped twice"
                        )
                    state.closed = True
                    if state.kind == "thinking":
                        if not state.signature:
                            raise InvalidProviderResponseError(
                                "Anthropic thinking block has no signature"
                            )
                        part: TextPart | ReasoningPart | ToolCallPart = ReasoningPart(state.text)
                        item = NativeItem(
                            self._identity.provider,
                            self._identity.protocol,
                            self._identity.model,
                            sequence_index=index,
                            kind="thinking",
                            payload={
                                "type": "thinking",
                                "thinking": state.text,
                                "signature": state.signature,
                            },
                        )
                    elif state.kind == "redacted_thinking":
                        part = ReasoningPart("")
                        item = NativeItem(
                            self._identity.provider,
                            self._identity.protocol,
                            self._identity.model,
                            sequence_index=index,
                            kind="redacted_thinking",
                            payload={
                                "type": "redacted_thinking",
                                "data": state.redacted_data,
                            },
                        )
                    elif state.kind == "text":
                        part = TextPart(state.text)
                        item = NativeItem(
                            self._identity.provider,
                            self._identity.protocol,
                            self._identity.model,
                            sequence_index=index,
                            kind="text",
                            payload={"type": "text", "text": state.text},
                        )
                    elif state.kind == "tool_use":
                        raw_arguments = state.arguments or "{}"
                        try:
                            parsed_arguments = json.loads(raw_arguments)
                        except json.JSONDecodeError:
                            raise InvalidProviderResponseError(
                                "Anthropic tool arguments are invalid JSON"
                            ) from None
                        arguments = require_json_object(
                            parsed_arguments, "Anthropic tool input"
                        )
                        part = ToolCallPart(
                            state.tool_call_id,
                            state.tool_name,
                            arguments,
                        )
                        item = NativeItem(
                            self._identity.provider,
                            self._identity.protocol,
                            self._identity.model,
                            sequence_index=index,
                            kind="tool_use",
                            payload={
                                "type": "tool_use",
                                "id": state.tool_call_id,
                                "name": state.tool_name,
                                "input": arguments,
                            },
                        )
                        yield ToolCallCompleted(
                            state.tool_call_id,
                            state.tool_name,
                            arguments,
                            sequence_index=index,
                        )
                    else:  # pragma: no cover - guarded at block start
                        raise InvalidProviderResponseError(
                            "Anthropic content block type is unsupported"
                        )
                    parts_by_index[index] = part
                    native_items.append(item)
                    yield NativeItemCompleted(item)
                elif event_type == "message_delta":
                    delta = _field(event, "delta")
                    raw_stop_reason = _field(delta, "stop_reason")
                    if raw_stop_reason is not None:
                        stop_reason = _text(
                            raw_stop_reason, "stop reason", allow_empty=False
                        )
                    usage = _field(event, "usage")
                    output_tokens = usage_int(
                        _field(usage, "output_tokens"),
                        "Anthropic output tokens",
                        default=output_tokens,
                    )
                    cache_read_tokens = usage_int(
                        _field(usage, "cache_read_input_tokens"),
                        "Anthropic cache read tokens",
                        default=cache_read_tokens,
                    )
                    if _field(usage, "cache_read_input_tokens") is not None:
                        cache_read_reported = True
                    cache_write_tokens = usage_int(
                        _field(usage, "cache_creation_input_tokens"),
                        "Anthropic cache write tokens",
                        default=cache_write_tokens,
                    )
                    if _field(usage, "cache_creation_input_tokens") is not None:
                        cache_write_reported = True
                elif event_type == "message_stop":
                    message_stop_seen = True
                elif event_type == "ping":
                    continue
                elif event_type == "error":
                    raise ProviderError()
                else:
                    raise InvalidProviderResponseError(
                        "Anthropic stream event is unsupported"
                    )

            if not message_start_seen:
                raise InvalidProviderResponseError("Anthropic stream has no message_start")
            if not message_stop_seen:
                raise InvalidProviderResponseError(
                    "Anthropic stream ended without message_stop"
                )
            if any(not state.closed for state in blocks.values()):
                raise InvalidProviderResponseError(
                    "Anthropic stream has an open content block"
                )
            if stop_reason is None:
                raise InvalidProviderResponseError(
                    "Anthropic stream ended without a stop reason"
                )
            ordered_items = tuple(sorted(native_items, key=lambda item: item.sequence_index))
            usage_details = {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            }
            if cache_read_reported:
                usage_details["cache_read_input_tokens"] = cache_read_tokens
            if cache_write_reported:
                usage_details["cache_creation_input_tokens"] = cache_write_tokens
            completed = ProviderResponse(
                message=Message(
                    role="assistant",
                    parts=tuple(
                        parts_by_index[index]
                        for index in sorted(parts_by_index)
                    ),
                    native_items=ordered_items,
                ),
                usage=Usage(
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cache_read_tokens=cache_read_tokens,
                    cache_write_tokens=cache_write_tokens,
                    details=usage_details,
                ),
                finish_reason=_finish_reason(stop_reason),
                native_items=ordered_items,
                details={"stop_reason": stop_reason},
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            mapped_error = _map_error(exc)
        finally:
            if stream is not None:
                try:
                    await close_stream(stream)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    if mapped_error is None:
                        mapped_error = _map_error(exc)
        if mapped_error is not None:
            raise mapped_error from None
        if completed is not None:
            yield GenerationCompleted(completed)


def build_anthropic_provider(
    model_name: str,
    *,
    client: AsyncAnthropic | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    http_client: object | None = None,
    max_output_tokens: int | None = None,
) -> ProviderPort:
    """Build an Anthropic Provider without making a model request."""

    resolved_client = client or AsyncAnthropic(
        api_key=api_key,
        base_url=base_url,
        http_client=http_client,
    )
    return AnthropicProvider(
        model_name,
        resolved_client,
        max_output_tokens=max_output_tokens,
    )


__all__ = ["AnthropicProvider", "build_anthropic_provider"]
