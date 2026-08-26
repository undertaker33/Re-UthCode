"""Native OpenAI-compatible Chat Completions protocol integration."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError as SDKAuthenticationError,
    PermissionDeniedError,
    RateLimitError as SDKRateLimitError,
)

from uthcode.core.provider import (
    AuthenticationError,
    CancellationToken,
    ContextOverflowError,
    DEFAULT_OUTPUT_RESERVE,
    FinishReason,
    GenerationCancelled,
    GenerationCompleted,
    GenerationRequest,
    InvalidProviderResponseError,
    Message,
    NativeItem,
    NativeItemCompleted,
    NetworkError,
    ProviderError,
    ProviderConfigurationError,
    ProviderEvent,
    ProviderIdentity,
    ProviderPort,
    ProviderResponse,
    RateLimitError,
    ProviderTimeoutError,
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


@dataclass(slots=True)
class _ToolState:
    index: int
    tool_call_id: str = ""
    name: str = ""
    arguments: str = ""
    pending_argument_deltas: list[str] = field(default_factory=list)
    started: bool = False
    completed: bool = False


def _field(value: object, name: str, default: object = None) -> object:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _required_index(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise InvalidProviderResponseError(f"Chat {label} is invalid")
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
                "Chat message contains an unsupported part"
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


def _assistant_message(
    message: Message,
    identity: ProviderIdentity,
) -> dict[str, object]:
    text_values: list[str] = []
    reasoning_values: list[str] = []
    tool_calls: list[dict[str, object]] = []
    for index, part in enumerate(message.parts):
        native = _native_at(
            message,
            identity,
            index,
            {"assistant_text", "reasoning_carrier", "assistant_tool_call"},
        )
        if isinstance(part, TextPart):
            text_values.append(part.text)
        elif isinstance(part, ReasoningPart):
            if native is not None and native.kind == "reasoning_carrier":
                field_name = native.payload.get("field", "reasoning_content")
                if not isinstance(field_name, str) or not field_name:
                    raise InvalidProviderResponseError(
                        "Chat reasoning carrier field is invalid"
                    )
                reasoning_values.append(part.text)
            else:
                # A carrier owned by another Provider is intentionally ignored.
                text_values.append(part.text)
        elif isinstance(part, ToolCallPart):
            tool_call_id = part.tool_call_id
            name = part.name
            arguments: object = dict(part.arguments)
            if native is not None:
                raw_id = native.payload.get("id")
                raw_name = native.payload.get("name")
                raw_arguments = native.payload.get("arguments", arguments)
                if isinstance(raw_id, str) and raw_id:
                    tool_call_id = raw_id
                if isinstance(raw_name, str) and raw_name:
                    name = raw_name
                arguments = raw_arguments
            if isinstance(arguments, str):
                arguments_text = arguments
            else:
                arguments_text = json.dumps(
                    require_json_object(arguments, "Chat tool arguments"),
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            tool_calls.append(
                {
                    "id": tool_call_id,
                    "type": "function",
                    "function": {"name": name, "arguments": arguments_text},
                }
            )
        else:
            raise InvalidProviderResponseError("Chat assistant part is unsupported")
    result: dict[str, object] = {
        "role": "assistant",
        "content": "".join(text_values) if text_values else None,
    }
    if reasoning_values:
        result["reasoning_content"] = "".join(reasoning_values)
    if tool_calls:
        result["tool_calls"] = tool_calls
    return result


def _request_messages(
    request: GenerationRequest,
    identity: ProviderIdentity,
) -> list[dict[str, object]]:
    messages: list[dict[str, object]] = []
    if request.system_prompt is not None:
        messages.append({"role": "system", "content": request.system_prompt})
    for message in request.messages:
        if message.role == "user":
            messages.append(
                {"role": message.role, "content": _message_text(message)}
            )
        elif message.role == "assistant":
            messages.append(_assistant_message(message, identity))
        elif message.role == "tool":
            for part in message.parts:
                if not isinstance(part, ToolResultPart):
                    raise InvalidProviderResponseError(
                        "Chat tool message contains an unsupported part"
                    )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": part.tool_call_id,
                        "content": part.content,
                    }
                )
        else:
            raise InvalidProviderResponseError(f"Chat message role is unsupported: {message.role}")
    return messages


def _request_tools(tools: Sequence[ToolDefinition]) -> list[dict[str, object]]:
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description or "",
                "parameters": require_json_object(tool.parameters, "Chat parameters"),
            },
        }
        for tool in tools
    ]


def _parse_arguments(arguments: str) -> dict[str, object]:
    try:
        parsed = json.loads(arguments or "{}")
    except json.JSONDecodeError:
        raise InvalidProviderResponseError(
            "Chat tool arguments are invalid JSON"
        ) from None
    return require_json_object(parsed, "Chat tool arguments")


def _finish_reason(value: str) -> FinishReason:
    return {
        "stop": FinishReason.STOP,
        "length": FinishReason.LENGTH,
        "tool_calls": FinishReason.TOOL_CALLS,
        "function_call": FinishReason.TOOL_CALLS,
        "content_filter": FinishReason.ERROR,
    }.get(value, FinishReason.UNKNOWN)


def _map_error(error: BaseException) -> ProviderError:
    if isinstance(error, GenerationCancelled):
        return error
    if isinstance(error, InvalidProviderResponseError):
        return InvalidProviderResponseError()
    if isinstance(error, ProviderError):
        return error
    if isinstance(error, (SDKAuthenticationError, PermissionDeniedError)):
        return AuthenticationError()
    if isinstance(error, SDKRateLimitError):
        return RateLimitError()
    if isinstance(error, (APITimeoutError, TimeoutError)):
        return ProviderTimeoutError()
    if isinstance(error, (APIConnectionError, OSError)):
        return NetworkError()
    if isinstance(error, APIStatusError):
        if error.status_code in {401, 403}:
            return AuthenticationError()
        if error.status_code == 429:
            return RateLimitError()
        if error.status_code in {408, 504}:
            return ProviderTimeoutError()
        if error.status_code == 413:
            return ContextOverflowError()
        if error.status_code in {400, 422}:
            return ProviderConfigurationError()
        return ProviderError()
    return ProviderError()


def _usage(raw_usage: object) -> Usage:
    if raw_usage is None:
        return Usage()
    payload = plain_json(raw_usage)
    if not isinstance(payload, Mapping):
        raise InvalidProviderResponseError("Chat usage must be an object")
    prompt_details = payload.get("prompt_tokens_details") or {}
    if not isinstance(prompt_details, Mapping):
        raise InvalidProviderResponseError(
            "Chat prompt token details must be an object"
        )
    completion_details = payload.get("completion_tokens_details") or {}
    if not isinstance(completion_details, Mapping):
        raise InvalidProviderResponseError(
            "Chat completion token details must be an object"
        )
    total_tokens = payload.get("total_tokens")
    if total_tokens is not None:
        total_tokens = usage_int(total_tokens, "Chat total tokens")
    details = dict(payload)
    reasoning_tokens = completion_details.get("reasoning_tokens")
    details["reasoning_tokens"] = usage_int(
        reasoning_tokens, "Chat reasoning tokens"
    )
    return Usage(
        input_tokens=usage_int(payload.get("prompt_tokens"), "Chat prompt tokens"),
        output_tokens=usage_int(
            payload.get("completion_tokens"), "Chat completion tokens"
        ),
        total_tokens=total_tokens,
        cache_read_tokens=usage_int(
            prompt_details.get("cached_tokens"), "Chat cached tokens"
        ),
        cache_write_tokens=usage_int(
            prompt_details.get("cache_write_tokens"), "Chat cache write tokens"
        ),
        details=details,
    )


class OpenAICompatProvider:
    """Directly map public Chat Completion chunks to Core events."""

    def __init__(
        self,
        model_name: str,
        client: AsyncOpenAI,
        *,
        base_url: str,
        max_output_tokens: int | None = None,
    ) -> None:
        self._model_name = model_name
        self._client = client
        self._base_url = base_url
        self._max_output_tokens = max_output_tokens
        self._identity = ProviderIdentity("openai", "chat_completions", model_name)

    @property
    def identity(self) -> ProviderIdentity:
        return self._identity

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
        post_events: list[ProviderEvent] = []
        try:
            max_output_tokens = (
                request.max_output_tokens
                if request.max_output_tokens is not None
                else self._max_output_tokens
                if self._max_output_tokens is not None
                else DEFAULT_OUTPUT_RESERVE
            )
            kwargs: dict[str, object] = {
                "model": request.model or self._model_name,
                "messages": _request_messages(request, self._identity),
                "max_tokens": max_output_tokens,
                "stream": True,
                "stream_options": {"include_usage": True},
            }
            if request.tools:
                kwargs["tools"] = _request_tools(request.tools)
            if request.temperature is not None:
                kwargs["temperature"] = request.temperature
            if request.reasoning is not None and request.reasoning.enabled:
                kwargs["reasoning_effort"] = request.reasoning.effort or "medium"

            chat_api = getattr(self._client, "chat", None)
            completions_api = getattr(chat_api, "completions", None)
            create = getattr(completions_api, "create", None)
            if not callable(create):
                raise ProviderError()
            stream = await create(**kwargs)
            iterator = aiter(stream)
            tools: dict[int, _ToolState] = {}
            finish_reason: str | None = None
            usage: Usage | None = None
            text_value = ""
            reasoning_value = ""
            part_order: list[tuple[str, int]] = []
            seen_text = False
            seen_reasoning = False

            while True:
                try:
                    chunk = await next_stream_value(iterator, cancellation)
                except StopAsyncIteration:
                    break
                raw_usage = _field(chunk, "usage")
                if raw_usage is not None:
                    usage = _usage(raw_usage)
                choices = _field(chunk, "choices", ())
                if choices is None:
                    choices = ()
                if not isinstance(choices, Sequence) or isinstance(
                    choices, (str, bytes, bytearray)
                ):
                    raise InvalidProviderResponseError("Chat choices are invalid")
                for choice in choices:
                    raw_finish = _field(choice, "finish_reason")
                    if raw_finish is not None:
                        if not isinstance(raw_finish, str) or not raw_finish:
                            raise InvalidProviderResponseError(
                                "Chat finish reason is invalid"
                            )
                        if finish_reason is not None and finish_reason != raw_finish:
                            raise InvalidProviderResponseError(
                                "Chat finish reasons conflict"
                            )
                        finish_reason = raw_finish
                    delta = _field(choice, "delta")
                    content = _field(delta, "content")
                    if content is not None:
                        if not isinstance(content, str):
                            raise InvalidProviderResponseError("Chat text delta is invalid")
                        if content:
                            if not seen_text:
                                part_order.append(("text", 0))
                                seen_text = True
                            text_value += content
                            yield TextDelta(content)
                    reasoning_content = _field(delta, "reasoning_content")
                    if reasoning_content is not None:
                        if not isinstance(reasoning_content, str):
                            raise InvalidProviderResponseError(
                                "Chat reasoning content is invalid"
                            )
                        if reasoning_content:
                            if not seen_reasoning:
                                part_order.append(("reasoning", 0))
                                seen_reasoning = True
                            reasoning_value += reasoning_content
                            yield ReasoningDelta(reasoning_content)
                    tool_calls = _field(delta, "tool_calls") or ()
                    if not isinstance(tool_calls, Sequence) or isinstance(
                        tool_calls, (str, bytes, bytearray)
                    ):
                        raise InvalidProviderResponseError("Chat tool calls are invalid")
                    for raw_tool_call in tool_calls:
                        index = _required_index(
                            _field(raw_tool_call, "index"), "tool call index"
                        )
                        state = tools.setdefault(index, _ToolState(index=index))
                        if ("tool", index) not in part_order:
                            part_order.append(("tool", index))
                        raw_id = _field(raw_tool_call, "id")
                        if raw_id is not None:
                            if not isinstance(raw_id, str) or not raw_id:
                                raise InvalidProviderResponseError(
                                    "Chat tool call id is invalid"
                                )
                            if state.tool_call_id and state.tool_call_id != raw_id:
                                raise InvalidProviderResponseError(
                                    "Chat tool call ids conflict"
                                )
                            state.tool_call_id = raw_id
                        function = _field(raw_tool_call, "function")
                        raw_name = _field(function, "name")
                        if raw_name is not None:
                            if not isinstance(raw_name, str) or not raw_name:
                                raise InvalidProviderResponseError(
                                    "Chat tool name is invalid"
                                )
                            if state.name and state.name != raw_name:
                                raise InvalidProviderResponseError(
                                    "Chat tool names conflict"
                                )
                            state.name = raw_name
                        raw_arguments = _field(function, "arguments")
                        if raw_arguments is not None:
                            if not isinstance(raw_arguments, str):
                                raise InvalidProviderResponseError(
                                    "Chat tool arguments delta is invalid"
                                )
                            state.arguments += raw_arguments
                            if raw_arguments:
                                state.pending_argument_deltas.append(raw_arguments)

            if finish_reason is None:
                raise InvalidProviderResponseError(
                    "Chat stream ended without a finish reason"
                )
            if usage is None:
                usage = Usage()
            parts: list[TextPart | ReasoningPart | ToolCallPart] = []
            native_items: list[NativeItem] = []
            for sequence_index, (kind, key) in enumerate(part_order):
                if kind == "text":
                    parts.append(TextPart(text_value))
                    native_items.append(
                        NativeItem(
                            self._identity.provider,
                            self._identity.protocol,
                            self._identity.model,
                            sequence_index=sequence_index,
                            kind="assistant_text",
                            payload={
                                "type": "assistant_text",
                                "content": text_value,
                            },
                        )
                    )
                elif kind == "reasoning":
                    parts.append(ReasoningPart(reasoning_value))
                    native_items.append(
                        NativeItem(
                            self._identity.provider,
                            self._identity.protocol,
                            self._identity.model,
                            sequence_index=sequence_index,
                            kind="reasoning_carrier",
                            payload={
                                "type": "reasoning_carrier",
                                "field": "reasoning_content",
                                "content": reasoning_value,
                            },
                        )
                    )
                elif kind == "tool":
                    state = tools[key]
                    if not state.tool_call_id or not state.name:
                        raise InvalidProviderResponseError(
                            "Chat tool call identity is incomplete"
                        )
                    arguments = _parse_arguments(state.arguments)
                    parts.append(ToolCallPart(state.tool_call_id, state.name, arguments))
                    native_items.append(
                        NativeItem(
                            self._identity.provider,
                            self._identity.protocol,
                            self._identity.model,
                            sequence_index=sequence_index,
                            kind="assistant_tool_call",
                            payload={
                                "type": "assistant_tool_call",
                                "index": state.index,
                                "id": state.tool_call_id,
                                "name": state.name,
                                "arguments": state.arguments,
                            },
                        )
                    )
                    state.started = True
                    post_events.append(
                        ToolCallStarted(
                            state.tool_call_id,
                            state.name,
                            sequence_index=sequence_index,
                        )
                    )
                    post_events.extend(
                        ToolCallArgumentsDelta(
                            state.tool_call_id,
                            arguments_delta,
                            sequence_index=sequence_index,
                        )
                        for arguments_delta in state.pending_argument_deltas
                    )
                    post_events.append(
                        ToolCallCompleted(
                            state.tool_call_id,
                            state.name,
                            arguments,
                            sequence_index=sequence_index,
                        )
                    )
                    state.completed = True
            if tools and not all(state.completed for state in tools.values()):
                raise InvalidProviderResponseError("Chat tool call is unfinished")
            ordered_native = tuple(native_items)
            for item in ordered_native:
                post_events.append(NativeItemCompleted(item))
            completed = ProviderResponse(
                message=Message(
                    role="assistant",
                    parts=tuple(parts),
                    native_items=ordered_native,
                ),
                usage=usage,
                finish_reason=_finish_reason(finish_reason),
                native_items=ordered_native,
                details={"finish_reason": finish_reason},
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
        for event in post_events:
            yield event
        if completed is not None:
            yield GenerationCompleted(completed)


def build_openai_compat_provider(
    model_name: str,
    *,
    base_url: str,
    client: AsyncOpenAI | None = None,
    api_key: str | None = None,
    http_client: object | None = None,
    max_output_tokens: int | None = None,
) -> ProviderPort:
    """Build a Chat Completions Provider without making a model request."""

    resolved_client = client or AsyncOpenAI(
        base_url=base_url,
        api_key=api_key,
        http_client=http_client,
    )
    return OpenAICompatProvider(
        model_name,
        resolved_client,
        base_url=base_url,
        max_output_tokens=max_output_tokens,
    )


__all__ = ["OpenAICompatProvider", "build_openai_compat_provider"]
