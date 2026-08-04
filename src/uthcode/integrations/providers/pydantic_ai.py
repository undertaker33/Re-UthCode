"""Shared Pydantic AI Direct Model bridge.

Protocol-specific request and response fields belong in the physical provider
modules added by later tasks. This module only handles the common Pydantic AI
message, stream, usage, error, cancellation, and resource lifecycle boundary.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from typing import Any

from pydantic_ai.direct import model_request_stream
from pydantic_ai.messages import (
    FinalResultEvent,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelResponseStreamEvent,
    PartDeltaEvent,
    PartEndEvent,
    PartStartEvent,
    SystemPromptPart,
    TextPart as AITextPart,
    TextPartDelta,
    ThinkingPart as AIThinkingPart,
    ThinkingPartDelta,
    ToolCallPart as AIToolCallPart,
    ToolCallPartDelta,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.tools import ToolDefinition as AIToolDefinition

from uthcode.core.provider import (
    AuthenticationError,
    CancellationToken,
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


class _RecordedSource:
    """Record one Direct Model source without changing its async-stream shape."""

    def __init__(self, source: Any, filter_event: Callable[[Any], bool] | None = None) -> None:
        self._source = source
        self._iterator: AsyncIterator[Any] | None = None
        self._filter_event = filter_event
        self.events: list[Any] = []

    def __aiter__(self) -> _RecordedSource:
        return self

    async def __anext__(self) -> Any:
        if self._iterator is None:
            self._iterator = aiter(self._source)
        while True:
            value = await anext(self._iterator)
            self.events.append(value)
            if self._filter_event is None or self._filter_event(value):
                return value

    async def close(self) -> None:
        close = getattr(self._source, "close", None)
        if close is not None:
            await close()
            return
        aclose = getattr(self._source, "aclose", None)
        if aclose is not None:
            await aclose()

    async def aclose(self) -> None:
        await self.close()


def record_model_stream(
    model_stream: Any,
    *,
    filter_event: Callable[[Any], bool] | None = None,
) -> _RecordedSource | None:
    """Install a protocol-owned recorder on a Pydantic AI streamed response.

    The shared bridge does not inspect recorded values. Protocol codecs may use
    this extension point when the vendor stream contains identity or terminal
    information that Pydantic AI intentionally normalizes away.
    """

    response_stream = getattr(model_stream, "_response", None)
    source = getattr(response_stream, "source", None)
    if source is None:
        return None
    if isinstance(source, _RecordedSource):
        return source
    # Direct Model implementations commonly peek once before yielding their
    # StreamedResponse. In that case PeekableAsyncStream already owns an
    # iterator, so replacing only ``source`` would miss every later chunk.
    # Wrap the active iterator when it exists and otherwise wrap the source
    # that PeekableAsyncStream will turn into an iterator.
    active_iterator = getattr(response_stream, "_source_iter", None)
    recorder = _RecordedSource(active_iterator or source, filter_event=filter_event)
    if active_iterator is not None:
        response_stream._source_iter = recorder
    response_stream.source = recorder
    return recorder


def _plain_json(value: Any) -> Any:
    """Return ordinary JSON containers after validating a provider value."""

    try:
        if isinstance(value, Mapping):
            value = {key: _plain_json(item) for key, item in value.items()}
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            value = [_plain_json(item) for item in value]
        return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise InvalidProviderResponseError(
            "Pydantic AI returned a non-JSON-safe value"
        ) from exc


def _tool_arguments(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise InvalidProviderResponseError(
                "Pydantic AI returned invalid tool arguments"
            ) from exc
    if not isinstance(value, Mapping):
        raise InvalidProviderResponseError("Tool arguments must be a JSON object")
    plain = _plain_json(value)
    if not isinstance(plain, dict):
        raise InvalidProviderResponseError("Tool arguments must be a JSON object")
    return plain


def _message_text(message: Message) -> str:
    values: list[str] = []
    for part in message.parts:
        if isinstance(part, (TextPart, ReasoningPart)):
            values.append(part.text)
        elif isinstance(part, ToolResultPart):
            values.append(part.content)
        else:
            raise InvalidProviderResponseError(
                "A user or system message contains an assistant-only part"
            )
    return "".join(values)


def _native_details(items: tuple[NativeItem, ...]) -> dict[str, Any] | None:
    if not items:
        return None
    return {
        "uthcode_native_items": [_plain_json(item.to_dict()) for item in items],
    }


class PydanticAICodec:
    """Protocol extension points for the shared Direct Model lifecycle.

    The default implementation retains the W01 generic bridge behavior. A
    protocol module can override only message-part replay, native snapshots,
    stream recording, and terminal validation; the provider lifecycle remains
    identical for every protocol.
    """

    capture_provider_details = True

    def encode_message(self, message: Message, identity: ProviderIdentity) -> ModelMessage:
        return _message_to_model(message, identity, self)

    def encode_assistant_part(
        self,
        part: TextPart | ReasoningPart | ToolCallPart,
        *,
        index: int,
        native_items: Sequence[NativeItem],
        identity: ProviderIdentity,
    ) -> Any:
        del index, native_items, identity
        if isinstance(part, TextPart):
            return AITextPart(part.text)
        if isinstance(part, ReasoningPart):
            return AIThinkingPart(part.text)
        if isinstance(part, ToolCallPart):
            return AIToolCallPart(
                tool_name=part.name,
                args=_plain_json(part.arguments),
                tool_call_id=part.tool_call_id,
            )
        raise InvalidProviderResponseError(
            f"Unsupported assistant message part: {type(part).__name__}"
        )

    def native_items_for_part(
        self,
        part: Any,
        *,
        index: int,
        identity: ProviderIdentity,
    ) -> tuple[NativeItem, ...]:
        del part, index, identity
        return ()

    def native_items_for_response(
        self,
        response: ModelResponse,
        *,
        identity: ProviderIdentity,
    ) -> tuple[NativeItem, ...]:
        del response, identity
        return ()

    def usage_from_model_response(self, response: ModelResponse) -> Usage | None:
        del response
        return None

    def bind_stream(self, model_stream: Any) -> None:
        del model_stream

    def validate_stream(self, model_stream: Any, response: ModelResponse) -> None:
        del model_stream, response


def _message_to_model(
    message: Message,
    identity: ProviderIdentity,
    codec: PydanticAICodec,
) -> ModelMessage:
    owned_items = message.native_items_for(identity)
    details = _native_details(owned_items)

    if message.role == "system":
        return ModelRequest([SystemPromptPart(_message_text(message))])
    if message.role == "user":
        return ModelRequest([UserPromptPart(_message_text(message))])
    if message.role == "tool":
        parts = [
            ToolReturnPart(
                tool_name="tool",
                content=part.content,
                tool_call_id=part.tool_call_id,
                outcome="failed" if part.is_error else "success",
            )
            for part in message.parts
            if isinstance(part, ToolResultPart)
        ]
        if len(parts) != len(message.parts):
            raise InvalidProviderResponseError(
                "A tool message contains a non-tool-result part"
            )
        return ModelRequest(parts)
    if message.role == "assistant":
        parts: list[Any] = []
        for index, part in enumerate(message.parts):
            if isinstance(part, ToolResultPart):
                raise InvalidProviderResponseError(
                    "An assistant message contains a tool result part"
                )
            parts.append(
                codec.encode_assistant_part(
                    part,
                    index=index,
                    native_items=owned_items,
                    identity=identity,
                )
            )
        return ModelResponse(
            parts,
            provider_name=identity.provider,
            provider_details=details,
            model_name=identity.model,
        )
    raise InvalidProviderResponseError(f"Unsupported message role: {message.role}")


def _request_messages(
    request: GenerationRequest,
    identity: ProviderIdentity,
    codec: PydanticAICodec,
) -> list[ModelMessage]:
    return [codec.encode_message(message, identity) for message in request.messages]


def _request_parameters(request: GenerationRequest) -> ModelRequestParameters:
    tools = [
        AIToolDefinition(
            name=tool.name,
            description=tool.description,
            parameters_json_schema=_plain_json(tool.parameters),
        )
        for tool in request.tools
    ]
    thinking: bool | str | None = None
    if request.reasoning is not None and request.reasoning.enabled:
        effort = request.reasoning.effort
        thinking = effort if effort in {"minimal", "low", "medium", "high", "xhigh"} else True
    return ModelRequestParameters(function_tools=tools, thinking=thinking)


def _model_settings(request: GenerationRequest) -> dict[str, Any] | None:
    settings: dict[str, Any] = {}
    if request.max_output_tokens is not None:
        settings["max_tokens"] = request.max_output_tokens
    if request.temperature is not None:
        settings["temperature"] = request.temperature
    if request.reasoning is not None and request.reasoning.enabled:
        settings["thinking"] = (
            request.reasoning.effort
            if request.reasoning.effort in {"minimal", "low", "medium", "high", "xhigh"}
            else True
        )
    return settings or None


def _finish_reason(value: Any) -> FinishReason:
    if value is None:
        return FinishReason.STOP
    raw = getattr(value, "value", value)
    return {
        "stop": FinishReason.STOP,
        "length": FinishReason.LENGTH,
        "tool_call": FinishReason.TOOL_CALLS,
        "tool_calls": FinishReason.TOOL_CALLS,
        "error": FinishReason.ERROR,
        "content_filter": FinishReason.ERROR,
    }.get(str(raw), FinishReason.UNKNOWN)


def _map_exception(error: BaseException) -> ProviderError:
    """Map SDK/Pydantic failures without copying exception text or secrets."""

    if isinstance(error, GenerationCancelled):
        return error
    if isinstance(error, AuthenticationError):
        return AuthenticationError()
    if isinstance(error, RateLimitError):
        return RateLimitError()
    if isinstance(error, NetworkError):
        return NetworkError()
    if isinstance(error, InvalidProviderResponseError):
        return error

    name = type(error).__name__.lower()
    status_code = getattr(error, "status_code", None)
    if status_code in (401, 403) or "auth" in name:
        return AuthenticationError()
    if status_code == 429 or "rate" in name or "limit" in name:
        return RateLimitError()
    if (
        isinstance(error, (TimeoutError, OSError))
        or "connect" in name
        or "network" in name
        or "transport" in name
        or "timeout" in name
    ):
        return NetworkError()
    if "validation" in name or "response" in name or "json" in name:
        return InvalidProviderResponseError()
    return ProviderError("Provider integration failed")


class _NativeTracker:
    def __init__(self, identity: ProviderIdentity) -> None:
        self.identity = identity
        self.items: list[NativeItem] = []
        self._signatures: set[str] = set()

    def add(self, details: Any) -> NativeItem | None:
        if details is None:
            return None
        if not isinstance(details, Mapping):
            raise InvalidProviderResponseError(
                "Pydantic AI provider details must be a JSON object"
            )
        plain = _plain_json(details)
        signature = json.dumps(plain, ensure_ascii=False, sort_keys=True)
        if signature in self._signatures:
            return None
        item = NativeItem(
            provider=self.identity.provider,
            protocol=self.identity.protocol,
            model=self.identity.model,
            sequence_index=len(self.items),
            kind="provider_details",
            payload=plain,
        )
        self._signatures.add(signature)
        self.items.append(item)
        return item

    def add_item(self, item: NativeItem) -> NativeItem | None:
        if not item.belongs_to(self.identity):
            raise InvalidProviderResponseError(
                "A codec returned a native item for a different provider identity"
            )
        plain = _plain_json(item.to_dict())
        signature = json.dumps(plain, ensure_ascii=False, sort_keys=True)
        if signature in self._signatures:
            return None
        self._signatures.add(signature)
        self.items.append(item)
        return item


def _tool_delta_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(_plain_json(value), ensure_ascii=False, separators=(",", ":"))


def _events_from_model_event(
    event: ModelResponseStreamEvent,
    *,
    started_tool_ids: set[str],
    native_tracker: _NativeTracker,
    codec: PydanticAICodec,
    identity: ProviderIdentity,
    completed_tool_ids: set[str],
) -> list[ProviderEvent]:
    result: list[ProviderEvent] = []

    if isinstance(event, PartStartEvent):
        part = event.part
        if isinstance(part, AITextPart):
            if part.content:
                result.append(TextDelta(part.content))
            if codec.capture_provider_details:
                native = native_tracker.add(part.provider_details)
                if native is not None:
                    result.append(NativeItemCompleted(native))
        elif isinstance(part, AIThinkingPart):
            if part.content:
                result.append(ReasoningDelta(part.content))
            if codec.capture_provider_details:
                native = native_tracker.add(part.provider_details)
                if native is not None:
                    result.append(NativeItemCompleted(native))
        elif isinstance(part, AIToolCallPart):
            tool_id = part.tool_call_id
            if tool_id not in started_tool_ids:
                started_tool_ids.add(tool_id)
                result.append(ToolCallStarted(tool_id, part.tool_name))
            if codec.capture_provider_details:
                native = native_tracker.add(part.provider_details)
                if native is not None:
                    result.append(NativeItemCompleted(native))
        return result

    if isinstance(event, PartDeltaEvent):
        delta = event.delta
        if isinstance(delta, TextPartDelta):
            if delta.content_delta:
                result.append(TextDelta(delta.content_delta))
        elif isinstance(delta, ThinkingPartDelta):
            if delta.content_delta:
                result.append(ReasoningDelta(delta.content_delta))
            if codec.capture_provider_details:
                native = native_tracker.add(delta.provider_details)
                if native is not None:
                    result.append(NativeItemCompleted(native))
        elif isinstance(delta, ToolCallPartDelta):
            tool_id = delta.tool_call_id
            if tool_id is not None and tool_id not in started_tool_ids:
                started_tool_ids.add(tool_id)
                result.append(
                    ToolCallStarted(tool_id, delta.tool_name_delta or "tool")
                )
            if tool_id is not None and delta.args_delta is not None:
                result.append(
                    ToolCallArgumentsDelta(
                        tool_id,
                        _tool_delta_text(delta.args_delta),
                    )
                )
            if codec.capture_provider_details:
                native = native_tracker.add(delta.provider_details)
                if native is not None:
                    result.append(NativeItemCompleted(native))
        return result

    if isinstance(event, PartEndEvent):
        part = event.part
        if isinstance(part, AIToolCallPart):
            # A provider may close a logical part when another indexed tool
            # starts, before all argument deltas have arrived. The final
            # response pass below emits completion once the accumulated JSON
            # is complete; an invalid final value still fails there.
            try:
                arguments = _tool_arguments(part.args)
            except InvalidProviderResponseError:
                arguments = None
            if arguments is not None and part.tool_call_id not in completed_tool_ids:
                completed_tool_ids.add(part.tool_call_id)
                result.append(
                    ToolCallCompleted(
                        tool_call_id=part.tool_call_id,
                        name=part.tool_name,
                        arguments=arguments,
                    )
                )
            if codec.capture_provider_details:
                native = native_tracker.add(part.provider_details)
                if native is not None:
                    result.append(NativeItemCompleted(native))
            for native_item in codec.native_items_for_part(
                part,
                index=event.index,
                identity=identity,
            ):
                native = native_tracker.add_item(native_item)
                if native is not None:
                    result.append(NativeItemCompleted(native))
        elif isinstance(part, (AITextPart, AIThinkingPart)):
            if codec.capture_provider_details:
                native = native_tracker.add(part.provider_details)
                if native is not None:
                    result.append(NativeItemCompleted(native))
            for native_item in codec.native_items_for_part(
                part,
                index=event.index,
                identity=identity,
            ):
                native = native_tracker.add_item(native_item)
                if native is not None:
                    result.append(NativeItemCompleted(native))
        return result

    if isinstance(event, FinalResultEvent):
        return result
    raise InvalidProviderResponseError(
        f"Unsupported Pydantic AI stream event: {type(event).__name__}"
    )


def _usage_from_model_response(response: ModelResponse) -> Usage:
    raw_usage = response.usage
    details = getattr(raw_usage, "details", None) or {}
    if not isinstance(details, Mapping):
        raise InvalidProviderResponseError("Pydantic AI usage details are not JSON-safe")
    plain_details = _plain_json(details)
    if not isinstance(plain_details, dict):
        raise InvalidProviderResponseError("Pydantic AI usage details are not an object")
    return Usage(
        input_tokens=getattr(raw_usage, "input_tokens", 0) or 0,
        output_tokens=getattr(raw_usage, "output_tokens", 0) or 0,
        cache_read_tokens=(
            plain_details.get("cache_read_tokens", plain_details.get("cache_read_input_tokens", 0))
            or 0
        ),
        cache_write_tokens=(
            plain_details.get(
                "cache_write_tokens",
                plain_details.get("cache_creation_input_tokens", 0),
            )
            or 0
        ),
        details=plain_details,
    )


def _response_to_core(
    response: ModelResponse,
    identity: ProviderIdentity,
    native_tracker: _NativeTracker,
    codec: PydanticAICodec,
) -> tuple[ProviderResponse, tuple[NativeItem, ...]]:
    parts: list[TextPart | ReasoningPart | ToolCallPart] = []
    for index, part in enumerate(response.parts):
        if isinstance(part, AITextPart):
            parts.append(TextPart(part.content))
        elif isinstance(part, AIThinkingPart):
            parts.append(ReasoningPart(part.content))
        elif isinstance(part, AIToolCallPart):
            parts.append(
                ToolCallPart(
                    tool_call_id=part.tool_call_id,
                    name=part.tool_name,
                    arguments=_tool_arguments(part.args),
                )
            )
        else:
            raise InvalidProviderResponseError(
                f"Unsupported Pydantic AI response part: {type(part).__name__}"
            )
        if codec.capture_provider_details:
            native_tracker.add(getattr(part, "provider_details", None))
        for native_item in codec.native_items_for_part(
            part,
            index=index,
            identity=identity,
        ):
            native_tracker.add_item(native_item)

    if codec.capture_provider_details:
        native_tracker.add(response.provider_details)
    for native_item in codec.native_items_for_response(response, identity=identity):
        native_tracker.add_item(native_item)
    native_tracker.items.sort(key=lambda item: item.sequence_index)
    message = Message(
        role="assistant",
        parts=tuple(parts),
        native_items=tuple(native_tracker.items),
    )
    provider_details = response.provider_details
    details: dict[str, Any] = {}
    if provider_details is not None:
        details["provider_details_present"] = True
    if response.provider_response_id is not None:
        details["provider_response_id"] = response.provider_response_id
    result = ProviderResponse(
        message=message,
        usage=codec.usage_from_model_response(response) or _usage_from_model_response(response),
        finish_reason=_finish_reason(response.finish_reason),
        native_items=tuple(native_tracker.items),
        details=details,
    )
    return result, tuple(native_tracker.items)


async def _iter_with_cancellation(
    stream: Any,
    cancellation: CancellationToken,
) -> AsyncIterator[ModelResponseStreamEvent]:
    iterator = stream.__aiter__()
    while True:
        cancellation.raise_if_cancelled()
        next_task = asyncio.create_task(anext(iterator))
        cancel_task = asyncio.create_task(cancellation.wait())
        try:
            done, _ = await asyncio.wait(
                (next_task, cancel_task),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if cancel_task in done:
                next_task.cancel()
                await asyncio.gather(next_task, return_exceptions=True)
                try:
                    await stream.cancel()
                except Exception:
                    pass
                raise GenerationCancelled()
            try:
                yield next_task.result()
            except StopAsyncIteration:
                return
        finally:
            if not cancel_task.done():
                cancel_task.cancel()
            await asyncio.gather(cancel_task, return_exceptions=True)


class PydanticAIProvider:
    """Adapt one Pydantic AI Direct Model to the UthCode ProviderPort."""

    def __init__(
        self,
        model: Any,
        identity: ProviderIdentity,
        *,
        codec: PydanticAICodec | None = None,
    ) -> None:
        if not isinstance(identity, ProviderIdentity):
            raise TypeError("identity must be ProviderIdentity")
        self._model = model
        self._identity = identity
        self._codec = codec or PydanticAICodec()

    @property
    def identity(self) -> ProviderIdentity:
        return self._identity

    async def stream(
        self,
        request: GenerationRequest,
        *,
        cancellation: CancellationToken,
    ) -> AsyncIterator[ProviderEvent]:
        cancellation.raise_if_cancelled()
        model_messages = _request_messages(request, self._identity, self._codec)
        request_parameters = _request_parameters(request)
        settings = _model_settings(request)
        native_tracker = _NativeTracker(self._identity)
        started_tool_ids: set[str] = set()
        completed_tool_ids: set[str] = set()

        mapped_error: ProviderError | None = None
        try:
            async with model_request_stream(
                self._model,
                model_messages,
                model_settings=settings,
                model_request_parameters=request_parameters,
            ) as model_stream:
                self._codec.bind_stream(model_stream)
                async for model_event in _iter_with_cancellation(
                    model_stream,
                    cancellation,
                ):
                    for event in _events_from_model_event(
                        model_event,
                        started_tool_ids=started_tool_ids,
                        native_tracker=native_tracker,
                        codec=self._codec,
                        identity=self._identity,
                        completed_tool_ids=completed_tool_ids,
                    ):
                        yield event

                response = model_stream.get()
                self._codec.validate_stream(model_stream, response)
                if model_stream.state != "complete":
                    raise InvalidProviderResponseError(
                        "Pydantic AI stream ended without a complete response"
                    )
                native_count_before_response = len(native_tracker.items)
                response, all_native_items = _response_to_core(
                    response,
                    self._identity,
                    native_tracker,
                    self._codec,
                )
                for part in response.message.parts:
                    if isinstance(part, ToolCallPart) and part.tool_call_id not in completed_tool_ids:
                        completed_tool_ids.add(part.tool_call_id)
                        yield ToolCallCompleted(
                            tool_call_id=part.tool_call_id,
                            name=part.name,
                            arguments=dict(part.arguments),
                        )
                for item in all_native_items[native_count_before_response:]:
                    yield NativeItemCompleted(item)
                yield GenerationCompleted(response)
        except asyncio.CancelledError:
            raise
        except ProviderError as exc:
            mapped_error = _map_exception(exc)
        except Exception as exc:
            mapped_error = _map_exception(exc)

        # Raise outside the handler so the third-party exception (which may
        # contain credentials or request data) is not retained as context.
        if mapped_error is not None:
            raise mapped_error


__all__ = ["PydanticAICodec", "PydanticAIProvider", "record_model_stream"]
