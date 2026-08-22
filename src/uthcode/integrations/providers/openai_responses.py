"""Native OpenAI Responses protocol integration."""

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


_NATIVE_ITEM_TYPES = {
    "reasoning",
    "message",
    "function_call",
    "function_call_output",
}
_PUBLIC_FIELDS = (
    "type",
    "id",
    "role",
    "status",
    "phase",
    "content",
    "summary",
    "encrypted_content",
    "call_id",
    "name",
    "arguments",
    "namespace",
    "output",
    "text",
    "annotations",
    "logprobs",
    "sequence_number",
    "output_index",
    "item_id",
    "content_index",
    "summary_index",
    "delta",
    "response",
    "item",
    "usage",
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "input_tokens_details",
    "output_tokens_details",
    "cached_tokens",
    "cache_write_tokens",
    "reasoning_tokens",
    "incomplete_details",
)
_MISSING = object()


@dataclass(slots=True)
class _OutputState:
    output_index: int
    item_id: str | None = None
    kind: str = ""
    call_id: str | None = None
    name: str | None = None
    arguments: str = ""
    text_by_index: dict[int, str] = field(default_factory=dict)
    summary_by_index: dict[int, str] = field(default_factory=dict)
    added: bool = False
    done: bool = False
    native_payload: dict[str, object] | None = None
    start_emitted: bool = False
    complete_emitted: bool = False


def _field(value: object, name: str, default: object = None) -> object:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _required_index(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise InvalidProviderResponseError(f"Responses {label} is invalid")
    return value


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    return value if isinstance(value, str) and value else None


def _required_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise InvalidProviderResponseError(f"Responses {label} is invalid")
    return value


def _public_json(value: object) -> object:
    try:
        return plain_json(value)
    except TypeError:
        if isinstance(value, Mapping):
            return {
                key: _public_json(item)
                for key, item in value.items()
                if isinstance(key, str)
            }
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            return [_public_json(item) for item in value]
        result: dict[str, object] = {}
        for name in _PUBLIC_FIELDS:
            raw = _field(value, name, _MISSING)
            if raw is not _MISSING:
                result[name] = _public_json(raw)
        if result:
            return result
        raise InvalidProviderResponseError("Responses public value is not JSON-safe") from None


def _object_payload(value: object, label: str) -> dict[str, object]:
    converted = _public_json(value)
    if not isinstance(converted, dict):
        raise InvalidProviderResponseError(f"Responses {label} must be an object")
    return converted


def _signature(value: object) -> str:
    return json.dumps(_public_json(value), ensure_ascii=False, sort_keys=True)


def _event_key(event: object, event_type: str) -> tuple[object, ...]:
    sequence_number = _field(event, "sequence_number")
    if isinstance(sequence_number, int) and not isinstance(sequence_number, bool):
        return (event_type, "sequence", sequence_number)
    return (
        event_type,
        _field(event, "item_id"),
        _field(event, "output_index"),
        _field(event, "content_index"),
        _field(event, "summary_index"),
        _field(event, "call_id"),
    )


def _remember_frame(
    seen: dict[tuple[object, ...], str],
    event: object,
    event_type: str,
) -> bool:
    key = _event_key(event, event_type)
    value = _signature(event)
    previous = seen.get(key)
    if previous is not None:
        if previous != value:
            raise InvalidProviderResponseError(
                "Responses stream contains conflicting duplicate frames"
            )
        return False
    seen[key] = value
    return True


def _state_for(
    states_by_index: dict[int, _OutputState],
    states_by_id: dict[str, _OutputState],
    states_by_call: dict[str, _OutputState],
    *,
    output_index: object,
    item_id: object = None,
    call_id: object = None,
    kind: object = None,
) -> _OutputState:
    index = _required_index(output_index, "output index")
    item_id_text = _optional_text(item_id)
    call_id_text = _optional_text(call_id)
    candidates: list[_OutputState] = []
    existing_index = states_by_index.get(index)
    if existing_index is not None:
        candidates.append(existing_index)
    if item_id_text is not None and item_id_text in states_by_id:
        candidates.append(states_by_id[item_id_text])
    if call_id_text is not None and call_id_text in states_by_call:
        candidates.append(states_by_call[call_id_text])
    unique = {id(state): state for state in candidates}
    if len(unique) > 1:
        raise InvalidProviderResponseError("Responses item identity conflicts")
    state = next(iter(unique.values()), None)
    if state is None:
        state = _OutputState(output_index=index)
    if state.output_index != index:
        raise InvalidProviderResponseError("Responses output index conflicts")
    if item_id_text is not None:
        if state.item_id is not None and state.item_id != item_id_text:
            raise InvalidProviderResponseError("Responses item id conflicts")
        state.item_id = item_id_text
        previous = states_by_id.get(item_id_text)
        if previous is not None and previous is not state:
            raise InvalidProviderResponseError("Responses item id conflicts")
        states_by_id[item_id_text] = state
    if call_id_text is not None:
        if state.call_id is not None and state.call_id != call_id_text:
            raise InvalidProviderResponseError("Responses call id conflicts")
        state.call_id = call_id_text
        previous = states_by_call.get(call_id_text)
        if previous is not None and previous is not state:
            raise InvalidProviderResponseError("Responses call id conflicts")
        states_by_call[call_id_text] = state
    if kind is not None:
        kind_text = _required_text(kind, "item type")
        if state.kind and state.kind != kind_text:
            raise InvalidProviderResponseError("Responses item type conflicts")
        state.kind = kind_text
    previous = states_by_index.get(index)
    if previous is not None and previous is not state:
        raise InvalidProviderResponseError("Responses output index conflicts")
    states_by_index[index] = state
    return state


def _item_payload(item: object) -> dict[str, object]:
    payload = _object_payload(item, "output item")
    item_type = payload.get("type")
    if not isinstance(item_type, str) or not item_type:
        raise InvalidProviderResponseError("Responses output item type is invalid")
    return payload


def _content_text(value: object) -> str:
    if isinstance(value, Mapping):
        raw_type = value.get("type")
        raw_text = value.get("text")
    else:
        raw_type = _field(value, "type")
        raw_text = _field(value, "text")
    if raw_type in {"output_text", "summary_text", "reasoning_text", "text"}:
        if not isinstance(raw_text, str):
            raise InvalidProviderResponseError("Responses item text is invalid")
        return raw_text
    return ""


def _summary_part_text(value: object) -> str:
    if _field(value, "type") != "summary_text":
        raise InvalidProviderResponseError("Responses reasoning summary part is invalid")
    text = _field(value, "text")
    if not isinstance(text, str):
        raise InvalidProviderResponseError("Responses reasoning summary part text is invalid")
    return text


def _item_text(payload: Mapping[str, object], field_name: str) -> str:
    raw = payload.get(field_name)
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
        return ""
    return "".join(_content_text(item) for item in raw)


def _parse_arguments(arguments: object) -> dict[str, object]:
    if not isinstance(arguments, str):
        raise InvalidProviderResponseError(
            "Responses function call arguments must be JSON text"
        )
    try:
        parsed = json.loads(arguments)
    except json.JSONDecodeError:
        raise InvalidProviderResponseError(
            "Responses function call arguments are invalid JSON"
        ) from None
    return require_json_object(parsed, "Responses function call arguments")


def _request_text(message: Message) -> str:
    text: list[str] = []
    for part in message.parts:
        if isinstance(part, (TextPart, ReasoningPart)):
            text.append(part.text)
        elif isinstance(part, ToolResultPart):
            text.append(part.content)
        else:
            raise InvalidProviderResponseError(
                "Responses user message contains an unsupported part"
            )
    return "".join(text)


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


def _request_input(
    request: GenerationRequest,
    identity: ProviderIdentity,
) -> list[dict[str, object]]:
    values: list[dict[str, object]] = []
    for message in request.messages:
        if message.role == "user":
            values.append(
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": _request_text(message)}],
                }
            )
            continue
        if message.role == "tool":
            for part in message.parts:
                if not isinstance(part, ToolResultPart):
                    raise InvalidProviderResponseError(
                        "Responses tool message contains an unsupported part"
                    )
                values.append(
                    {
                        "type": "function_call_output",
                        "call_id": part.tool_call_id,
                        "output": part.content,
                    }
                )
            continue
        if message.role != "assistant":
            raise InvalidProviderResponseError(
                f"Responses message role is unsupported: {message.role}"
            )
        for index, part in enumerate(message.parts):
            native = _native_at(
                message,
                identity,
                index,
                {"reasoning", "message", "function_call"},
            )
            if native is not None:
                values.append(dict(native.payload))
            elif isinstance(part, TextPart):
                values.append(
                    {
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": part.text}],
                    }
                )
            elif isinstance(part, ReasoningPart):
                values.append(
                    {
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": part.text}],
                    }
                )
            elif isinstance(part, ToolCallPart):
                values.append(
                    {
                        "type": "function_call",
                        "call_id": part.tool_call_id,
                        "name": part.name,
                        "arguments": json.dumps(
                            dict(part.arguments),
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                    }
                )
            else:  # pragma: no cover - Core Message validates part types
                raise InvalidProviderResponseError("Responses assistant part is unsupported")
    return values


def _request_tools(tools: Sequence[ToolDefinition]) -> list[dict[str, object]]:
    return [
        {
            "type": "function",
            "name": tool.name,
            "description": tool.description or "",
            "parameters": require_json_object(tool.parameters, "Responses parameters"),
        }
        for tool in tools
    ]


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


def _usage(response: object) -> Usage:
    raw_usage = _field(response, "usage")
    if raw_usage is None:
        return Usage()
    payload = _object_payload(raw_usage, "usage")
    input_details = payload.get("input_tokens_details") or {}
    if not isinstance(input_details, Mapping):
        raise InvalidProviderResponseError(
            "Responses input token details must be an object"
        )
    input_tokens = usage_int(payload.get("input_tokens"), "Responses input tokens")
    output_tokens = usage_int(payload.get("output_tokens"), "Responses output tokens")
    total_tokens = payload.get("total_tokens")
    if total_tokens is not None:
        total_tokens = usage_int(total_tokens, "Responses total tokens")
    cache_read = usage_int(
        input_details.get("cached_tokens"), "Responses cached tokens"
    )
    cache_write = usage_int(
        input_details.get("cache_write_tokens"), "Responses cache write tokens"
    )
    return Usage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        cache_read_tokens=cache_read,
        cache_write_tokens=cache_write,
        details=payload,
    )


class OpenAIResponsesProvider:
    """Directly map public OpenAI Responses stream events to Core events."""

    def __init__(
        self,
        model_name: str,
        client: AsyncOpenAI,
        *,
        max_output_tokens: int | None = None,
    ) -> None:
        self._model_name = model_name
        self._client = client
        self._max_output_tokens = max_output_tokens
        self._identity = ProviderIdentity("openai", "responses", model_name)

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
        try:
            input_values = _request_input(request, self._identity)
            max_output_tokens = (
                request.max_output_tokens
                if request.max_output_tokens is not None
                else self._max_output_tokens
                if self._max_output_tokens is not None
                else DEFAULT_OUTPUT_RESERVE
            )
            kwargs: dict[str, object] = {
                "model": request.model or self._model_name,
                "input": input_values,
                "max_output_tokens": max_output_tokens,
                "stream": True,
            }
            if request.system_prompt is not None:
                kwargs["instructions"] = request.system_prompt
            if request.tools:
                kwargs["tools"] = _request_tools(request.tools)
            if request.temperature is not None:
                kwargs["temperature"] = request.temperature
            if request.reasoning is not None and request.reasoning.enabled:
                kwargs["reasoning"] = {
                    "effort": request.reasoning.effort or "medium",
                }

            responses_api = getattr(self._client, "responses", None)
            create = getattr(responses_api, "create", None)
            if not callable(create):
                raise ProviderError()
            stream = await create(**kwargs)
            iterator = aiter(stream)
            states_by_index: dict[int, _OutputState] = {}
            states_by_id: dict[str, _OutputState] = {}
            states_by_call: dict[str, _OutputState] = {}
            seen_frames: dict[tuple[object, ...], str] = {}
            terminal_signature: str | None = None
            terminal_value: object | None = None
            terminal_kind: str | None = None
            terminal_seen = False

            while True:
                try:
                    event = await next_stream_value(iterator, cancellation)
                except StopAsyncIteration:
                    break
                event_type = _field(event, "type")
                if not isinstance(event_type, str):
                    raise InvalidProviderResponseError("Responses event type is invalid")
                if not _remember_frame(seen_frames, event, event_type):
                    continue
                if terminal_seen and event_type in {
                    "response.completed",
                    "response.incomplete",
                    "response.failed",
                }:
                    if terminal_signature != _signature(_field(event, "response")):
                        raise InvalidProviderResponseError(
                            "Responses terminal snapshots conflict"
                        )
                    continue
                if terminal_seen:
                    raise InvalidProviderResponseError(
                        "Responses stream produced data after terminal event"
                    )

                if event_type == "response.output_item.added":
                    item = _field(event, "item")
                    payload = _item_payload(item)
                    item_type = _required_text(payload.get("type"), "item type")
                    output_index = _required_index(
                        _field(event, "output_index"), "output index"
                    )
                    state = _state_for(
                        states_by_index,
                        states_by_id,
                        states_by_call,
                        output_index=output_index,
                        item_id=payload.get("id"),
                        call_id=payload.get("call_id"),
                        kind=item_type,
                    )
                    state.added = True
                    if item_type == "function_call":
                        state.name = _optional_text(payload.get("name")) or state.name
                        state.arguments = _optional_text(payload.get("arguments")) or state.arguments
                        if state.item_id is None and payload.get("id") is not None:
                            raise InvalidProviderResponseError("Responses function call id is invalid")
                        if state.call_id is None:
                            raise InvalidProviderResponseError("Responses function call call id is invalid")
                        if state.name and not state.start_emitted:
                            state.start_emitted = True
                            yield ToolCallStarted(
                                state.call_id,
                                state.name,
                                sequence_index=state.output_index,
                            )
                elif event_type == "response.output_item.done":
                    item = _field(event, "item")
                    payload = _item_payload(item)
                    item_type = _required_text(payload.get("type"), "item type")
                    output_index = _required_index(
                        _field(event, "output_index"), "output index"
                    )
                    state = _state_for(
                        states_by_index,
                        states_by_id,
                        states_by_call,
                        output_index=output_index,
                        item_id=payload.get("id"),
                        call_id=payload.get("call_id"),
                        kind=item_type,
                    )
                    snapshot = _item_payload(item)
                    if state.native_payload is not None and state.native_payload != snapshot:
                        raise InvalidProviderResponseError(
                            "Responses output item snapshots conflict"
                        )
                    was_done = state.done
                    state.native_payload = snapshot
                    state.done = True
                    if was_done:
                        continue
                    if item_type == "function_call":
                        state.name = _optional_text(snapshot.get("name")) or state.name
                        item_arguments = snapshot.get("arguments")
                        if item_arguments is not None:
                            item_arguments = _required_text(
                                item_arguments, "function call arguments"
                            )
                            if state.arguments and state.arguments != item_arguments:
                                raise InvalidProviderResponseError(
                                    "Responses function call arguments conflict"
                                )
                            state.arguments = item_arguments
                        if state.call_id is None:
                            raise InvalidProviderResponseError(
                                "Responses function call call id is missing"
                            )
                        if state.name is None:
                            raise InvalidProviderResponseError(
                                "Responses function call name is missing"
                            )
                        if not state.start_emitted:
                            state.start_emitted = True
                            yield ToolCallStarted(
                                state.call_id,
                                state.name,
                                sequence_index=state.output_index,
                            )
                        _parse_arguments(state.arguments)
                        if not state.complete_emitted:
                            state.complete_emitted = True
                            yield ToolCallCompleted(
                                state.call_id,
                                state.name,
                                _parse_arguments(state.arguments),
                                sequence_index=state.output_index,
                            )
                    if item_type in _NATIVE_ITEM_TYPES:
                        item = NativeItem(
                            self._identity.provider,
                            self._identity.protocol,
                            self._identity.model,
                            sequence_index=state.output_index,
                            kind=item_type,
                            payload=snapshot,
                        )
                        yield NativeItemCompleted(item)
                elif event_type == "response.output_text.delta":
                    item_id = _field(event, "item_id")
                    output_index = _required_index(
                        _field(event, "output_index"), "output index"
                    )
                    content_index = _required_index(
                        _field(event, "content_index"), "content index"
                    )
                    delta = _field(event, "delta")
                    if not isinstance(delta, str):
                        raise InvalidProviderResponseError("Responses text delta is invalid")
                    state = _state_for(
                        states_by_index,
                        states_by_id,
                        states_by_call,
                        output_index=output_index,
                        item_id=item_id,
                        kind="message",
                    )
                    state.text_by_index[content_index] = (
                        state.text_by_index.get(content_index, "") + delta
                    )
                    if delta:
                        yield TextDelta(delta)
                elif event_type == "response.output_text.done":
                    item_id = _field(event, "item_id")
                    output_index = _required_index(
                        _field(event, "output_index"), "output index"
                    )
                    content_index = _required_index(
                        _field(event, "content_index"), "content index"
                    )
                    text = _field(event, "text")
                    if not isinstance(text, str):
                        raise InvalidProviderResponseError("Responses completed text is invalid")
                    state = _state_for(
                        states_by_index,
                        states_by_id,
                        states_by_call,
                        output_index=output_index,
                        item_id=item_id,
                        kind="message",
                    )
                    accumulated = state.text_by_index.get(content_index, "")
                    if accumulated and accumulated != text:
                        raise InvalidProviderResponseError(
                            "Responses completed text conflicts with deltas"
                        )
                    state.text_by_index[content_index] = text
                elif event_type in {
                    "response.reasoning_summary_part.added",
                    "response.reasoning_summary_part.done",
                }:
                    item_id = _field(event, "item_id")
                    output_index = _required_index(
                        _field(event, "output_index"), "output index"
                    )
                    summary_index = _required_index(
                        _field(event, "summary_index"), "summary index"
                    )
                    text = _summary_part_text(_field(event, "part"))
                    state = _state_for(
                        states_by_index,
                        states_by_id,
                        states_by_call,
                        output_index=output_index,
                        item_id=item_id,
                        kind="reasoning",
                    )
                    accumulated = state.summary_by_index.get(summary_index, "")
                    if accumulated and text and accumulated != text:
                        raise InvalidProviderResponseError(
                            "Responses reasoning summary part conflicts with deltas"
                        )
                    if text:
                        state.summary_by_index[summary_index] = text
                elif event_type == "response.reasoning_summary_text.delta":
                    item_id = _field(event, "item_id")
                    output_index = _required_index(
                        _field(event, "output_index"), "output index"
                    )
                    summary_index = _required_index(
                        _field(event, "summary_index"), "summary index"
                    )
                    delta = _field(event, "delta")
                    if not isinstance(delta, str):
                        raise InvalidProviderResponseError(
                            "Responses reasoning delta is invalid"
                        )
                    state = _state_for(
                        states_by_index,
                        states_by_id,
                        states_by_call,
                        output_index=output_index,
                        item_id=item_id,
                        kind="reasoning",
                    )
                    state.summary_by_index[summary_index] = (
                        state.summary_by_index.get(summary_index, "") + delta
                    )
                    if delta:
                        yield ReasoningDelta(delta)
                elif event_type == "response.reasoning_summary_text.done":
                    item_id = _field(event, "item_id")
                    output_index = _required_index(
                        _field(event, "output_index"), "output index"
                    )
                    summary_index = _required_index(
                        _field(event, "summary_index"), "summary index"
                    )
                    text = _field(event, "text")
                    if not isinstance(text, str):
                        raise InvalidProviderResponseError(
                            "Responses completed reasoning text is invalid"
                        )
                    state = _state_for(
                        states_by_index,
                        states_by_id,
                        states_by_call,
                        output_index=output_index,
                        item_id=item_id,
                        kind="reasoning",
                    )
                    accumulated = state.summary_by_index.get(summary_index, "")
                    if accumulated and accumulated != text:
                        raise InvalidProviderResponseError(
                            "Responses completed reasoning text conflicts with deltas"
                        )
                    state.summary_by_index[summary_index] = text
                elif event_type == "response.function_call_arguments.delta":
                    item_id = _field(event, "item_id")
                    output_index = _required_index(
                        _field(event, "output_index"), "output index"
                    )
                    delta = _field(event, "delta")
                    if not isinstance(delta, str):
                        raise InvalidProviderResponseError(
                            "Responses function arguments delta is invalid"
                        )
                    state = _state_for(
                        states_by_index,
                        states_by_id,
                        states_by_call,
                        output_index=output_index,
                        item_id=item_id,
                        kind="function_call",
                    )
                    state.arguments += delta
                    if state.call_id is None:
                        call_id = _field(event, "call_id")
                        if isinstance(call_id, str) and call_id:
                            state.call_id = call_id
                            states_by_call[call_id] = state
                    if state.name and state.call_id and not state.start_emitted:
                        state.start_emitted = True
                        yield ToolCallStarted(
                            state.call_id,
                            state.name,
                            sequence_index=state.output_index,
                        )
                    if delta:
                        yield ToolCallArgumentsDelta(
                            state.call_id or _required_text(item_id, "item id"),
                            delta,
                            sequence_index=state.output_index,
                        )
                elif event_type == "response.function_call_arguments.done":
                    item_id = _field(event, "item_id")
                    output_index = _required_index(
                        _field(event, "output_index"), "output index"
                    )
                    arguments = _required_text(
                        _field(event, "arguments"), "function call arguments"
                    )
                    state = _state_for(
                        states_by_index,
                        states_by_id,
                        states_by_call,
                        output_index=output_index,
                        item_id=item_id,
                        kind="function_call",
                    )
                    if state.arguments and state.arguments != arguments:
                        raise InvalidProviderResponseError(
                            "Responses function call arguments conflict"
                        )
                    state.arguments = arguments
                    name = _field(event, "name")
                    if isinstance(name, str) and name:
                        state.name = name
                    _parse_arguments(arguments)
                elif event_type in {
                    "response.completed",
                    "response.incomplete",
                    "response.failed",
                }:
                    response = _field(event, "response")
                    signature = _signature(response)
                    if terminal_signature is not None and terminal_signature != signature:
                        raise InvalidProviderResponseError(
                            "Responses terminal snapshots conflict"
                        )
                    terminal_signature = signature
                    terminal_value = response
                    terminal_kind = event_type
                    terminal_seen = True
                    if event_type != "response.completed":
                        raise InvalidProviderResponseError(
                            "Responses stream did not complete successfully"
                        )
                    status = _field(response, "status")
                    if status is not None and status != "completed":
                        raise InvalidProviderResponseError(
                            "Responses completed event has an invalid status"
                        )
                    output = _field(response, "output")
                    if isinstance(output, Sequence) and not isinstance(
                        output, (str, bytes, bytearray)
                    ):
                        for output_index, item in enumerate(output):
                            payload = _item_payload(item)
                            item_type = _required_text(payload.get("type"), "item type")
                            state = _state_for(
                                states_by_index,
                                states_by_id,
                                states_by_call,
                                output_index=output_index,
                                item_id=payload.get("id"),
                                call_id=payload.get("call_id"),
                                kind=item_type,
                            )
                            if state.native_payload is not None and state.native_payload != payload:
                                raise InvalidProviderResponseError(
                                    "Responses terminal output conflicts with item"
                                )
                            state.native_payload = payload
                            state.done = True
                elif event_type == "error":
                    raise ProviderError()
                elif event_type in {
                    "response.created",
                    "response.in_progress",
                    "response.queued",
                    "response.content_part.added",
                    "response.content_part.done",
                    "response.output_text.annotation.added",
                }:
                    continue
                else:
                    raise InvalidProviderResponseError("Responses stream event is unsupported")

            if not terminal_seen or terminal_kind != "response.completed":
                raise InvalidProviderResponseError(
                    "Responses stream ended without a completed response"
                )
            if terminal_value is None:
                raise InvalidProviderResponseError("Responses completed response is missing")
            states = tuple(sorted(states_by_index.values(), key=lambda state: state.output_index))
            if any(state.added and not state.done for state in states):
                raise InvalidProviderResponseError(
                    "Responses stream has an unfinished output item"
                )
            parts: list[TextPart | ReasoningPart | ToolCallPart | ToolResultPart] = []
            native_items: list[NativeItem] = []
            for state in states:
                if state.kind not in _NATIVE_ITEM_TYPES:
                    continue
                if state.native_payload is None:
                    raise InvalidProviderResponseError(
                        "Responses output item has no terminal snapshot"
                    )
                payload = state.native_payload
                item = NativeItem(
                    self._identity.provider,
                    self._identity.protocol,
                    self._identity.model,
                    sequence_index=state.output_index,
                    kind=state.kind,
                    payload=payload,
                )
                native_items.append(item)
                if state.kind == "message":
                    text = _item_text(payload, "content")
                    if not text:
                        text = "".join(
                            state.text_by_index[index]
                            for index in sorted(state.text_by_index)
                        )
                    parts.append(TextPart(text))
                elif state.kind == "reasoning":
                    text = _item_text(payload, "summary")
                    if not text:
                        text = "".join(
                            state.summary_by_index[index]
                            for index in sorted(state.summary_by_index)
                        )
                    parts.append(ReasoningPart(text))
                elif state.kind == "function_call":
                    call_id = state.call_id or _optional_text(payload.get("call_id"))
                    name = state.name or _optional_text(payload.get("name"))
                    if call_id is None or name is None:
                        raise InvalidProviderResponseError(
                            "Responses function call identity is incomplete"
                        )
                    arguments = state.arguments or payload.get("arguments")
                    parts.append(ToolCallPart(call_id, name, _parse_arguments(arguments)))
                elif state.kind == "function_call_output":
                    call_id = _optional_text(payload.get("call_id"))
                    output = payload.get("output")
                    if call_id is not None and isinstance(output, str):
                        parts.append(ToolResultPart(call_id, output))
            ordered_native = tuple(native_items)
            completed = ProviderResponse(
                message=Message(
                    role="assistant",
                    parts=tuple(parts),
                    native_items=ordered_native,
                ),
                usage=_usage(terminal_value),
                finish_reason=(
                    FinishReason.TOOL_CALLS
                    if any(state.kind == "function_call" for state in states)
                    else FinishReason.STOP
                ),
                native_items=ordered_native,
                details={
                    "response_id": _field(terminal_value, "id"),
                    "status": _field(terminal_value, "status"),
                },
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


def build_openai_responses_provider(
    model_name: str,
    *,
    client: AsyncOpenAI | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    http_client: object | None = None,
    max_output_tokens: int | None = None,
) -> ProviderPort:
    """Build an OpenAI Responses Provider without making a model request."""

    resolved_client = client or AsyncOpenAI(
        api_key=api_key,
        base_url=base_url,
        http_client=http_client,
    )
    return OpenAIResponsesProvider(
        model_name,
        resolved_client,
        max_output_tokens=max_output_tokens,
    )


__all__ = ["OpenAIResponsesProvider", "build_openai_responses_provider"]
