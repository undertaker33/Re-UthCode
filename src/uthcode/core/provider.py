"""UthCode-owned provider request, response, event, and cancellation types.

This module intentionally depends only on the Python standard library. Any
provider SDK or model-library value must be converted to these types before it
crosses the integration boundary.
"""

from __future__ import annotations

import asyncio
import json
import math
import threading
from collections.abc import AsyncIterator, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, fields, is_dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Awaitable, ClassVar, Protocol, TypeAlias, runtime_checkable


JsonValue: TypeAlias = Any


class FrozenList(Sequence[Any]):
    """An immutable JSON array representation backed by a private tuple.

    This deliberately does not inherit from ``list``: inheriting from a mutable
    builtin lets callers bypass overridden methods with ``list.__setitem__``.
    """

    __slots__ = ("_values",)

    def __init__(self, values: Sequence[Any] = ()) -> None:
        self._values = tuple(values)

    def __getitem__(self, index: int | slice) -> Any:
        return self._values[index]

    def __len__(self) -> int:
        return len(self._values)

    def __iter__(self) -> Iterator[Any]:
        return iter(self._values)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Sequence) and not isinstance(other, (str, bytes, bytearray)):
            return tuple(self) == tuple(other)
        return NotImplemented

    def __repr__(self) -> str:
        return repr(list(self._values))

    @staticmethod
    def _immutable(*_: Any, **__: Any) -> None:
        raise TypeError("JSON values are immutable")

    append = _immutable
    clear = _immutable
    extend = _immutable
    insert = _immutable
    pop = _immutable
    remove = _immutable
    reverse = _immutable
    sort = _immutable


class JsonPayload(Mapping[str, JsonValue]):
    """A deeply immutable, JSON-object payload owned by UthCode.

    Only JSON primitives, object keys that are strings, arrays, and nested
    objects are accepted. Input collections are copied and frozen
    recursively, so later mutation of a caller-owned value cannot alter a
    provider request or response.
    """

    __slots__ = ("_values",)

    def __init__(self, value: Mapping[str, Any] | None = None, /, **kwargs: Any) -> None:
        if value is not None and not isinstance(value, Mapping):
            raise TypeError("JsonPayload requires a mapping")
        source: dict[str, Any] = {}
        if value is not None:
            source.update(value)
        source.update(kwargs)

        frozen: dict[str, Any] = {}
        for key, item in source.items():
            if not isinstance(key, str):
                raise TypeError("JSON object keys must be strings")
            frozen[key] = _freeze_json(item)
        self._values = MappingProxyType(frozen)

    def __getitem__(self, key: str) -> JsonValue:
        return self._values[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Mapping):
            return dict(self.items()) == dict(other.items())
        return NotImplemented

    def __repr__(self) -> str:
        return repr(dict(self.items()))

    @staticmethod
    def _immutable(*_: Any, **__: Any) -> None:
        raise TypeError("JSON values are immutable")

    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable

    def copy(self) -> JsonPayload:
        return JsonPayload(self)


def _freeze_json(value: Any) -> Any:
    """Validate and recursively freeze one JSON value."""

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise TypeError("JSON numbers must be finite")
        return value
    if isinstance(value, Mapping):
        return JsonPayload(value)
    if isinstance(value, (FrozenList, list, tuple)):
        return FrozenList(_freeze_json(item) for item in value)
    raise TypeError(f"value of type {type(value).__name__} is not JSON-safe")


def _json_value(value: Any) -> Any:
    """Convert a contract value into ordinary dict/list JSON data."""

    if isinstance(value, Enum):
        return value.value
    if isinstance(value, _JsonModel):
        return value.to_dict()
    if isinstance(value, JsonPayload):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (FrozenList, list, tuple)):
        return [_json_value(item) for item in value]
    if is_dataclass(value):
        return {
            item.name: _json_value(getattr(value, item.name))
            for item in fields(value)
        }
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    raise TypeError(f"value of type {type(value).__name__} is not JSON-safe")


def _require_text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


_MESSAGE_ROLES = frozenset({"user", "assistant", "tool"})


def _require_non_negative_int(value: int | None, field_name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer or None")
    return value


def _as_tuple(value: Sequence[Any], field_name: str) -> tuple[Any, ...]:
    if isinstance(value, (str, bytes, bytearray)):
        raise TypeError(f"{field_name} must be a sequence of values")
    try:
        return tuple(value)
    except TypeError as exc:
        raise TypeError(f"{field_name} must be a sequence of values") from exc


class _JsonModel:
    """Small serialization helpers shared by immutable contract models."""

    def to_dict(self) -> dict[str, Any]:
        if not is_dataclass(self):
            raise TypeError("contract models serialize to JSON objects")
        return {
            item.name: _json_value(getattr(self, item.name))
            for item in fields(self)
        }

    def model_dump(self, *, mode: str = "python") -> dict[str, Any]:
        del mode
        return self.to_dict()

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)


class _ProviderEventModel(_JsonModel):
    """Type-tagged base for the unified Provider event JSON contract."""

    event_type: ClassVar[str]

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.event_type, **_JsonModel.to_dict(self)}


@dataclass(frozen=True, slots=True)
class ProviderIdentity(_JsonModel):
    provider: str
    protocol: str
    model: str

    def __post_init__(self) -> None:
        _require_text(self.provider, "provider")
        _require_text(self.protocol, "protocol")
        _require_text(self.model, "model")


@dataclass(frozen=True, slots=True)
class TextPart(_JsonModel):
    text: str

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise TypeError("text must be a string")

    def to_dict(self) -> dict[str, Any]:
        return {"type": "text", "text": self.text}


@dataclass(frozen=True, slots=True)
class ReasoningPart(_JsonModel):
    text: str

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise TypeError("text must be a string")

    def to_dict(self) -> dict[str, Any]:
        return {"type": "reasoning", "text": self.text}


@dataclass(frozen=True, slots=True)
class ToolCallPart(_JsonModel):
    tool_call_id: str
    name: str
    arguments: JsonPayload = field(default_factory=JsonPayload)

    def __post_init__(self) -> None:
        _require_text(self.tool_call_id, "tool_call_id")
        _require_text(self.name, "name")
        object.__setattr__(self, "arguments", JsonPayload(self.arguments))

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "tool_call",
            "tool_call_id": self.tool_call_id,
            "name": self.name,
            "arguments": _json_value(self.arguments),
        }


@dataclass(frozen=True, slots=True)
class ToolResultPart(_JsonModel):
    tool_call_id: str
    content: str
    is_error: bool = False
    metadata: JsonPayload = field(default_factory=JsonPayload)

    def __post_init__(self) -> None:
        _require_text(self.tool_call_id, "tool_call_id")
        if not isinstance(self.content, str):
            raise TypeError("content must be a string")
        if not isinstance(self.is_error, bool):
            raise TypeError("is_error must be a boolean")
        object.__setattr__(self, "metadata", JsonPayload(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        value = {
            "type": "tool_result",
            "tool_call_id": self.tool_call_id,
            "content": self.content,
            "is_error": self.is_error,
        }
        if self.metadata:
            value["metadata"] = _json_value(self.metadata)
        return value


MessagePart: TypeAlias = TextPart | ReasoningPart | ToolCallPart | ToolResultPart


@dataclass(frozen=True, slots=True)
class NativeItem(_JsonModel):
    provider: str
    protocol: str
    model: str
    schema_version: int = 1
    sequence_index: int = 0
    kind: str = "unknown"
    payload: JsonPayload = field(default_factory=JsonPayload)

    def __post_init__(self) -> None:
        _require_text(self.provider, "provider")
        _require_text(self.protocol, "protocol")
        _require_text(self.model, "model")
        if isinstance(self.schema_version, bool) or not isinstance(self.schema_version, int):
            raise TypeError("schema_version must be an integer")
        if self.schema_version < 1:
            raise ValueError("schema_version must be positive")
        if isinstance(self.sequence_index, bool) or not isinstance(self.sequence_index, int):
            raise TypeError("sequence_index must be an integer")
        if self.sequence_index < 0:
            raise ValueError("sequence_index must be non-negative")
        _require_text(self.kind, "kind")
        object.__setattr__(self, "payload", JsonPayload(self.payload))

    @property
    def identity(self) -> ProviderIdentity:
        return ProviderIdentity(self.provider, self.protocol, self.model)

    def belongs_to(self, identity: ProviderIdentity) -> bool:
        return (
            self.provider == identity.provider
            and self.protocol == identity.protocol
            and self.model == identity.model
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> NativeItem:
        return cls(
            provider=value["provider"],
            protocol=value["protocol"],
            model=value["model"],
            schema_version=value.get("schema_version", 1),
            sequence_index=value.get("sequence_index", 0),
            kind=value.get("kind", "unknown"),
            payload=value.get("payload", {}),
        )


def _part_from_dict(value: Mapping[str, Any]) -> MessagePart:
    part_type = value.get("type")
    if part_type == "text":
        return TextPart(text=value["text"])
    if part_type == "reasoning":
        return ReasoningPart(text=value["text"])
    if part_type == "tool_call":
        return ToolCallPart(
            tool_call_id=value["tool_call_id"],
            name=value["name"],
            arguments=value.get("arguments", {}),
        )
    if part_type == "tool_result":
        return ToolResultPart(
            tool_call_id=value["tool_call_id"],
            content=value["content"],
            is_error=value.get("is_error", False),
            metadata=value.get("metadata", {}),
        )
    raise ValueError(f"unknown message part type: {part_type!r}")


@dataclass(frozen=True, slots=True)
class Message(_JsonModel):
    role: str
    parts: tuple[MessagePart, ...] = ()
    native_items: tuple[NativeItem, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.role, "role")
        if self.role not in _MESSAGE_ROLES:
            raise ValueError("role must be one of: user, assistant, tool")
        parts = _as_tuple(self.parts, "parts")
        if not all(
            isinstance(part, (TextPart, ReasoningPart, ToolCallPart, ToolResultPart))
            for part in parts
        ):
            raise TypeError("parts must contain UthCode message parts")
        native_items = _as_tuple(self.native_items, "native_items")
        if not all(isinstance(item, NativeItem) for item in native_items):
            raise TypeError("native_items must contain NativeItem values")
        object.__setattr__(self, "parts", parts)
        object.__setattr__(self, "native_items", native_items)

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "parts": [part.to_dict() for part in self.parts],
            "native_items": [item.to_dict() for item in self.native_items],
        }

    def native_items_for(self, identity: ProviderIdentity) -> tuple[NativeItem, ...]:
        """Return only native snapshots owned by the requested provider."""

        return tuple(item for item in self.native_items if item.belongs_to(identity))

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Message:
        return cls(
            role=value["role"],
            parts=tuple(_part_from_dict(part) for part in value.get("parts", ())),
            native_items=tuple(
                NativeItem.from_dict(item) for item in value.get("native_items", ())
            ),
        )


@dataclass(frozen=True, slots=True)
class ToolDefinition(_JsonModel):
    name: str
    description: str | None = None
    parameters: JsonPayload = field(default_factory=JsonPayload)

    def __post_init__(self) -> None:
        _require_text(self.name, "name")
        if self.description is not None and not isinstance(self.description, str):
            raise TypeError("description must be a string or None")
        object.__setattr__(self, "parameters", JsonPayload(self.parameters))

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": _json_value(self.parameters),
        }


@dataclass(frozen=True, slots=True)
class ReasoningOptions(_JsonModel):
    enabled: bool = False
    budget_tokens: int | None = None
    effort: str | None = None
    details: JsonPayload = field(default_factory=JsonPayload)

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise TypeError("enabled must be a boolean")
        object.__setattr__(
            self,
            "budget_tokens",
            _require_non_negative_int(self.budget_tokens, "budget_tokens"),
        )
        if self.effort is not None and not isinstance(self.effort, str):
            raise TypeError("effort must be a string or None")
        object.__setattr__(self, "details", JsonPayload(self.details))


@dataclass(frozen=True, slots=True)
class GenerationRequest(_JsonModel):
    messages: tuple[Message, ...]
    system_prompt: str | None = None
    model: str | None = None
    tools: tuple[ToolDefinition, ...] = ()
    reasoning: ReasoningOptions | None = None
    max_output_tokens: int | None = None
    temperature: float | None = None
    metadata: JsonPayload = field(default_factory=JsonPayload)

    def __post_init__(self) -> None:
        messages = _as_tuple(self.messages, "messages")
        if not all(isinstance(message, Message) for message in messages):
            raise TypeError("messages must contain Message values")
        if self.system_prompt is not None:
            _require_text(self.system_prompt, "system_prompt")
            if not self.system_prompt.strip():
                raise ValueError("system_prompt must be a non-empty string or None")
        tools = _as_tuple(self.tools, "tools")
        if not all(isinstance(tool, ToolDefinition) for tool in tools):
            raise TypeError("tools must contain ToolDefinition values")
        if self.model is not None:
            _require_text(self.model, "model")
        if self.reasoning is not None and not isinstance(self.reasoning, ReasoningOptions):
            raise TypeError("reasoning must be ReasoningOptions or None")
        object.__setattr__(
            self,
            "max_output_tokens",
            _require_non_negative_int(self.max_output_tokens, "max_output_tokens"),
        )
        if self.temperature is not None:
            if not isinstance(self.temperature, (int, float)) or isinstance(self.temperature, bool):
                raise TypeError("temperature must be a number or None")
            if not math.isfinite(float(self.temperature)):
                raise ValueError("temperature must be finite")
            object.__setattr__(self, "temperature", float(self.temperature))
        object.__setattr__(self, "messages", messages)
        object.__setattr__(self, "tools", tools)
        object.__setattr__(self, "metadata", JsonPayload(self.metadata))

    @property
    def instruction_plane(self) -> str | None:
        """The provider-independent Instruction Plane carried by this DTO.

        ``system_prompt`` remains the serialized compatibility name because
        the three provider integrations already map it to their native
        instruction channel.  The property makes the two-plane contract
        explicit without duplicating the payload or introducing a second
        source of truth.
        """

        return self.system_prompt

    @property
    def conversation_plane(self) -> tuple[Message, ...]:
        """The provider-independent Conversation Plane carried by this DTO."""

        return self.messages

    @property
    def tool_system(self) -> tuple[ToolDefinition, ...]:
        """The structured Tool System; schemas never belong in prompt text."""

        return self.tools

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> GenerationRequest:
        reasoning_value = value.get("reasoning")
        reasoning = None
        if reasoning_value is not None:
            reasoning = ReasoningOptions(
                enabled=reasoning_value.get("enabled", False),
                budget_tokens=reasoning_value.get("budget_tokens"),
                effort=reasoning_value.get("effort"),
                details=reasoning_value.get("details", {}),
            )
        return cls(
            messages=tuple(Message.from_dict(item) for item in value.get("messages", ())),
            system_prompt=value.get("system_prompt"),
            model=value.get("model"),
            tools=tuple(
                ToolDefinition(
                    name=item["name"],
                    description=item.get("description"),
                    parameters=item.get("parameters", {}),
                )
                for item in value.get("tools", ())
            ),
            reasoning=reasoning,
            max_output_tokens=value.get("max_output_tokens"),
            temperature=value.get("temperature"),
            metadata=value.get("metadata", {}),
        )

    @classmethod
    def from_json(cls, value: str) -> GenerationRequest:
        parsed = json.loads(value)
        if not isinstance(parsed, Mapping):
            raise TypeError("GenerationRequest JSON must contain an object")
        return cls.from_dict(parsed)


def _require_positive_optional_int(value: int | None, field_name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer or None")
    return value


@dataclass(frozen=True, slots=True)
class ModelLimits(_JsonModel):
    """Provider-reported physical limits for one remote model.

    The three dimensions intentionally remain independent.  An adapter that
    cannot prove a dimension leaves it as ``None`` instead of deriving it from
    a model name or from another dimension.
    """

    max_input_tokens: int | None = None
    max_output_tokens: int | None = None
    max_combined_tokens: int | None = None
    source: str = "provider_runtime"

    def __post_init__(self) -> None:
        for field_name in (
            "max_input_tokens",
            "max_output_tokens",
            "max_combined_tokens",
        ):
            object.__setattr__(
                self,
                field_name,
                _require_positive_optional_int(getattr(self, field_name), field_name),
            )
        _require_text(self.source, "source")


@dataclass(frozen=True, slots=True)
class ContextCountEstimate(_JsonModel):
    """A sourced, explicitly approximate input count for a request."""

    input_tokens: int
    source: str
    kind: str = "preflight_local_estimate"
    safety_allowance: int = 0

    def __post_init__(self) -> None:
        if isinstance(self.input_tokens, bool) or not isinstance(self.input_tokens, int):
            raise TypeError("input_tokens must be a non-negative integer")
        if self.input_tokens < 0:
            raise ValueError("input_tokens must be a non-negative integer")
        _require_text(self.source, "source")
        if self.kind not in {
            "pressure_estimate",
            "preflight_provider_count",
            "preflight_local_estimate",
        }:
            raise ValueError("unsupported ContextCountEstimate kind")
        if (
            isinstance(self.safety_allowance, bool)
            or not isinstance(self.safety_allowance, int)
            or self.safety_allowance < 0
        ):
            raise ValueError("safety_allowance must be a non-negative integer")

    @property
    def safety_adjusted_tokens(self) -> int:
        return self.input_tokens + self.safety_allowance


@runtime_checkable
class SupportsModelLimits(Protocol):
    """Optional Provider capability for reliable runtime model limits."""

    def resolve_model_limits(
        self,
        model: str,
    ) -> ModelLimits | None | Awaitable[ModelLimits | None]:
        ...


@runtime_checkable
class SupportsInputTokenCount(Protocol):
    """Optional Provider capability for final-request input estimates."""

    def count_input_tokens(
        self,
        request: GenerationRequest,
    ) -> ContextCountEstimate | int | None | Awaitable[ContextCountEstimate | int | None]:
        ...


@dataclass(frozen=True, slots=True)
class Usage(_JsonModel):
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int | None = None
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    details: JsonPayload = field(default_factory=JsonPayload)

    def __post_init__(self) -> None:
        input_tokens = _require_non_negative_int(self.input_tokens, "input_tokens")
        output_tokens = _require_non_negative_int(self.output_tokens, "output_tokens")
        total_tokens = _require_non_negative_int(self.total_tokens, "total_tokens")
        cache_read = _require_non_negative_int(self.cache_read_tokens, "cache_read_tokens")
        cache_write = _require_non_negative_int(self.cache_write_tokens, "cache_write_tokens")
        if total_tokens is None:
            total_tokens = (input_tokens or 0) + (output_tokens or 0)
        object.__setattr__(self, "input_tokens", input_tokens or 0)
        object.__setattr__(self, "output_tokens", output_tokens or 0)
        object.__setattr__(self, "total_tokens", total_tokens)
        object.__setattr__(self, "cache_read_tokens", cache_read or 0)
        object.__setattr__(self, "cache_write_tokens", cache_write or 0)
        object.__setattr__(self, "details", JsonPayload(self.details))

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Usage:
        return cls(
            input_tokens=value.get("input_tokens", 0),
            output_tokens=value.get("output_tokens", 0),
            total_tokens=value.get("total_tokens"),
            cache_read_tokens=value.get("cache_read_tokens", 0),
            cache_write_tokens=value.get("cache_write_tokens", 0),
            details=value.get("details", {}),
        )


class FinishReason(str, Enum):
    STOP = "stop"
    TOOL_CALLS = "tool_calls"
    LENGTH = "length"
    INCOMPLETE = "incomplete"
    ERROR = "error"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ProviderResponse(_JsonModel):
    message: Message
    usage: Usage = field(default_factory=Usage)
    finish_reason: FinishReason = FinishReason.STOP
    native_items: tuple[NativeItem, ...] = ()
    details: JsonPayload = field(default_factory=JsonPayload)

    def __post_init__(self) -> None:
        if not isinstance(self.message, Message):
            raise TypeError("message must be a Message")
        if not isinstance(self.usage, Usage):
            raise TypeError("usage must be Usage")
        reason = self.finish_reason
        if not isinstance(reason, FinishReason):
            try:
                reason = FinishReason(reason)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"unknown finish reason: {reason!r}") from exc
        native_items = _as_tuple(self.native_items, "native_items")
        if not all(isinstance(item, NativeItem) for item in native_items):
            raise TypeError("native_items must contain NativeItem values")
        object.__setattr__(self, "finish_reason", reason)
        object.__setattr__(self, "native_items", native_items)
        object.__setattr__(self, "details", JsonPayload(self.details))

    def to_dict(self) -> dict[str, Any]:
        return {
            "message": self.message.to_dict(),
            "usage": self.usage.to_dict(),
            "finish_reason": self.finish_reason.value,
            "native_items": [item.to_dict() for item in self.native_items],
            "details": _json_value(self.details),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ProviderResponse:
        return cls(
            message=Message.from_dict(value["message"]),
            usage=Usage.from_dict(value.get("usage", {})),
            finish_reason=value.get("finish_reason", FinishReason.STOP.value),
            native_items=tuple(
                NativeItem.from_dict(item) for item in value.get("native_items", ())
            ),
            details=value.get("details", {}),
        )


@dataclass(frozen=True, slots=True)
class TextDelta(_ProviderEventModel):
    event_type: ClassVar[str] = "text_delta"
    text: str

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise TypeError("text must be a string")

    @property
    def delta(self) -> str:
        return self.text


@dataclass(frozen=True, slots=True)
class ReasoningDelta(_ProviderEventModel):
    event_type: ClassVar[str] = "reasoning_delta"
    text: str

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise TypeError("text must be a string")

    @property
    def delta(self) -> str:
        return self.text


@dataclass(frozen=True, slots=True)
class ToolCallStarted(_ProviderEventModel):
    event_type: ClassVar[str] = "tool_call_started"
    tool_call_id: str
    name: str
    sequence_index: int | None = None

    def __post_init__(self) -> None:
        _require_text(self.tool_call_id, "tool_call_id")
        _require_text(self.name, "name")
        object.__setattr__(
            self,
            "sequence_index",
            _require_non_negative_int(self.sequence_index, "sequence_index"),
        )


@dataclass(frozen=True, slots=True)
class ToolCallArgumentsDelta(_ProviderEventModel):
    event_type: ClassVar[str] = "tool_call_arguments_delta"
    tool_call_id: str
    arguments_delta: str
    sequence_index: int | None = None

    def __post_init__(self) -> None:
        _require_text(self.tool_call_id, "tool_call_id")
        if not isinstance(self.arguments_delta, str):
            raise TypeError("arguments_delta must be a string")
        object.__setattr__(
            self,
            "sequence_index",
            _require_non_negative_int(self.sequence_index, "sequence_index"),
        )

    @property
    def delta(self) -> str:
        return self.arguments_delta


@dataclass(frozen=True, slots=True)
class ToolCallCompleted(_ProviderEventModel):
    event_type: ClassVar[str] = "tool_call_completed"
    tool_call_id: str
    name: str
    arguments: JsonPayload = field(default_factory=JsonPayload)
    sequence_index: int | None = None

    def __post_init__(self) -> None:
        _require_text(self.tool_call_id, "tool_call_id")
        _require_text(self.name, "name")
        object.__setattr__(self, "arguments", JsonPayload(self.arguments))
        object.__setattr__(
            self,
            "sequence_index",
            _require_non_negative_int(self.sequence_index, "sequence_index"),
        )


@dataclass(frozen=True, slots=True)
class NativeItemCompleted(_ProviderEventModel):
    event_type: ClassVar[str] = "native_item_completed"
    item: NativeItem

    def __post_init__(self) -> None:
        if not isinstance(self.item, NativeItem):
            raise TypeError("item must be NativeItem")


@dataclass(frozen=True, slots=True)
class GenerationCompleted(_ProviderEventModel):
    event_type: ClassVar[str] = "generation_completed"
    response: ProviderResponse

    def __post_init__(self) -> None:
        if not isinstance(self.response, ProviderResponse):
            raise TypeError("response must be ProviderResponse")


ProviderEvent: TypeAlias = (
    TextDelta
    | ReasoningDelta
    | ToolCallStarted
    | ToolCallArgumentsDelta
    | ToolCallCompleted
    | NativeItemCompleted
    | GenerationCompleted
)


def provider_event_from_dict(value: Mapping[str, Any]) -> ProviderEvent:
    """Restore any current Provider event from its type-tagged JSON object."""

    event_type = value.get("type")
    if event_type == TextDelta.event_type:
        return TextDelta(text=value["text"])
    if event_type == ReasoningDelta.event_type:
        return ReasoningDelta(text=value["text"])
    if event_type == ToolCallStarted.event_type:
        return ToolCallStarted(
            tool_call_id=value["tool_call_id"],
            name=value["name"],
            sequence_index=value.get("sequence_index"),
        )
    if event_type == ToolCallArgumentsDelta.event_type:
        return ToolCallArgumentsDelta(
            tool_call_id=value["tool_call_id"],
            arguments_delta=value["arguments_delta"],
            sequence_index=value.get("sequence_index"),
        )
    if event_type == ToolCallCompleted.event_type:
        return ToolCallCompleted(
            tool_call_id=value["tool_call_id"],
            name=value["name"],
            arguments=value.get("arguments", {}),
            sequence_index=value.get("sequence_index"),
        )
    if event_type == NativeItemCompleted.event_type:
        return NativeItemCompleted(item=NativeItem.from_dict(value["item"]))
    if event_type == GenerationCompleted.event_type:
        return GenerationCompleted(response=ProviderResponse.from_dict(value["response"]))
    raise ValueError(f"unknown provider event type: {event_type!r}")


def provider_event_from_json(value: str) -> ProviderEvent:
    parsed = json.loads(value)
    if not isinstance(parsed, Mapping):
        raise TypeError("Provider event JSON must contain an object")
    return provider_event_from_dict(parsed)


class ProviderError(Exception):
    """Base error crossing the provider boundary."""

    code: ClassVar[str] = "provider_error"

    def __init__(self, message: str = "Provider operation failed") -> None:
        if not isinstance(message, str):
            raise TypeError("message must be a string")
        self.message = message
        super().__init__(message)


class ContextOverflowError(ProviderError):
    """A Provider rejected one request for exceeding its context capacity.

    This is a typed last-protection signal only.  It is not a model-window
    discovery API; the Application may use it for one bounded recompile.
    """

    code = "context_overflow"


class ProviderConfigurationError(ProviderError):
    code = "provider_configuration_error"


class MissingSecretError(ProviderConfigurationError):
    code = "missing_secret"

    def __init__(self, environment_variable: str) -> None:
        _require_text(environment_variable, "environment_variable")
        self.environment_variable = environment_variable
        super().__init__(f"Provider credential is missing: {environment_variable}")


class AuthenticationError(ProviderError):
    code = "authentication_error"


class RateLimitError(ProviderError):
    code = "rate_limit_error"


class NetworkError(ProviderError):
    code = "network_error"


class InvalidProviderResponseError(ProviderError):
    code = "invalid_provider_response"


class GenerationCancelled(ProviderError):
    code = "generation_cancelled"


class CancellationToken:
    """An idempotent cancellation signal for multiple async waiters."""

    def __init__(self) -> None:
        self._cancelled = False
        self._lock = threading.Lock()
        self._waiters: set[asyncio.Future[None]] = set()

    @property
    def cancelled(self) -> bool:
        with self._lock:
            return self._cancelled

    @property
    def is_cancelled(self) -> bool:
        return self.cancelled

    def cancel(self) -> bool:
        """Cancel once and wake every current waiter; return transition status."""

        with self._lock:
            if self._cancelled:
                return False
            self._cancelled = True
            waiters = tuple(self._waiters)

        for waiter in waiters:
            loop = waiter.get_loop()
            if not loop.is_closed():
                loop.call_soon_threadsafe(self._resolve_waiter, waiter)
        return True

    @staticmethod
    def _resolve_waiter(waiter: asyncio.Future[None]) -> None:
        if not waiter.done():
            waiter.set_result(None)

    async def wait(self) -> None:
        if self.cancelled:
            return
        loop = asyncio.get_running_loop()
        waiter = loop.create_future()
        with self._lock:
            if self._cancelled:
                waiter.set_result(None)
            else:
                self._waiters.add(waiter)
        try:
            await waiter
        finally:
            with self._lock:
                self._waiters.discard(waiter)

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise GenerationCancelled()


async def validated_provider_stream(
    provider: ProviderPort,
    request: GenerationRequest,
    *,
    cancellation: CancellationToken,
) -> AsyncIterator[ProviderEvent]:
    """Yield one provider stream with its terminal held until EOF.

    A ``GenerationCompleted`` event is only authoritative after the provider
    iterator reaches normal EOF.  This keeps low-level Generation and the Core
    Agent Loop from committing a response that is later invalidated by a
    trailing event or an iterator error.  The underlying stream is closed on
    every exit path.
    """

    terminal: GenerationCompleted | None = None
    stream = provider.stream(request, cancellation=cancellation)
    provider_event_types = (
        TextDelta,
        ReasoningDelta,
        ToolCallStarted,
        ToolCallArgumentsDelta,
        ToolCallCompleted,
        NativeItemCompleted,
        GenerationCompleted,
    )
    try:
        async for event in stream:
            if terminal is not None:
                raise InvalidProviderResponseError(
                    "Provider emitted an event after GenerationCompleted"
                )
            if not isinstance(event, provider_event_types):
                raise InvalidProviderResponseError("Provider emitted an unsupported event")
            if isinstance(event, GenerationCompleted):
                terminal = event
                continue
            yield event
    finally:
        close = getattr(stream, "aclose", None)
        if close is not None:
            await close()

    if terminal is None:
        raise InvalidProviderResponseError(
            "Provider stream ended without GenerationCompleted"
        )
    yield terminal


@runtime_checkable
class ProviderPort(Protocol):
    @property
    def identity(self) -> ProviderIdentity:
        ...

    async def stream(
        self,
        request: GenerationRequest,
        *,
        cancellation: CancellationToken,
    ) -> AsyncIterator[ProviderEvent]:
        ...
        if False:
            yield  # pragma: no cover


__all__ = [
    "AuthenticationError",
    "CancellationToken",
    "ContextCountEstimate",
    "ContextOverflowError",
    "FinishReason",
    "GenerationCancelled",
    "GenerationCompleted",
    "GenerationRequest",
    "InvalidProviderResponseError",
    "JsonPayload",
    "JsonValue",
    "Message",
    "MessagePart",
    "ModelLimits",
    "MissingSecretError",
    "NativeItem",
    "NativeItemCompleted",
    "NetworkError",
    "ProviderConfigurationError",
    "ProviderError",
    "ProviderEvent",
    "ProviderIdentity",
    "ProviderPort",
    "ProviderResponse",
    "SupportsInputTokenCount",
    "SupportsModelLimits",
    "provider_event_from_dict",
    "provider_event_from_json",
    "RateLimitError",
    "ReasoningDelta",
    "ReasoningOptions",
    "ReasoningPart",
    "TextDelta",
    "TextPart",
    "ToolCallArgumentsDelta",
    "ToolCallCompleted",
    "ToolCallPart",
    "ToolCallStarted",
    "ToolDefinition",
    "ToolResultPart",
    "Usage",
    "validated_provider_stream",
]
