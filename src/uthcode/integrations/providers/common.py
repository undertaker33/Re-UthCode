"""Small vendor-neutral helpers shared by the native provider modules."""

from __future__ import annotations

import asyncio
import inspect
import math
from collections.abc import Mapping, Sequence
from enum import Enum
from typing import Callable

from uthcode.core.provider import CancellationToken, GenerationCancelled, JsonValue


def plain_json(value: object) -> JsonValue:
    """Convert a public SDK value into ordinary JSON-compatible containers."""

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise TypeError("JSON numbers must be finite")
        return value
    if isinstance(value, Enum):
        return plain_json(value.value)
    if isinstance(value, Mapping):
        result: dict[str, JsonValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("JSON object keys must be strings")
            result[key] = plain_json(item)
        return result
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [plain_json(item) for item in value]

    serialized = _public_serialized_value(value)
    if serialized is not None:
        return plain_json(serialized)
    raise TypeError(f"value of type {type(value).__name__} is not JSON-safe")


def _public_serialized_value(value: object) -> object | None:
    """Read one documented serialization method without inspecting internals."""

    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            return model_dump(mode="json")
        except TypeError:
            try:
                return model_dump()
            except Exception as exc:
                raise TypeError(
                    f"value of type {type(value).__name__} is not JSON-safe"
                ) from None
        except Exception:
            raise TypeError(
                f"value of type {type(value).__name__} is not JSON-safe"
            ) from None

    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        try:
            return to_dict()
        except Exception:
            raise TypeError(
                f"value of type {type(value).__name__} is not JSON-safe"
            ) from None
    return None


def require_json_object(value: object, label: str) -> dict[str, JsonValue]:
    """Convert and require a JSON object, using only a safe diagnostic label."""

    if not isinstance(label, str) or not label:
        raise TypeError("label must be a non-empty string")
    converted = plain_json(value)
    if not isinstance(converted, dict):
        raise TypeError(f"{label} must be a JSON object")
    return converted


def usage_int(value: object, label: str, *, default: int = 0) -> int:
    """Read a non-negative integer usage field without coercing loose values."""

    if not isinstance(default, int) or isinstance(default, bool) or default < 0:
        raise ValueError("default must be a non-negative integer")
    candidate = default if value is None else value
    if isinstance(candidate, bool) or not isinstance(candidate, int):
        raise TypeError(f"{label} must be a non-negative integer")
    if candidate < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return candidate


async def close_stream(stream: object) -> None:
    """Close an async stream through its documented async or sync close hook."""

    closer: Callable[[], object] | None = None
    aclose = getattr(stream, "aclose", None)
    if callable(aclose):
        closer = aclose
    else:
        close = getattr(stream, "close", None)
        if callable(close):
            closer = close
    if closer is None:
        return
    result = closer()
    if inspect.isawaitable(result):
        await result


async def next_stream_value(
    iterator: object,
    cancellation: CancellationToken,
) -> object:
    """Await one async-iterator value while observing Core cancellation."""

    next_value = getattr(iterator, "__anext__", None)
    if not callable(next_value):
        raise TypeError("stream iterator must provide __anext__")
    raise_if_cancelled(cancellation)
    pending = asyncio.ensure_future(next_value())
    cancel_task = asyncio.create_task(cancellation.wait())
    try:
        done, _ = await asyncio.wait(
            (pending, cancel_task), return_when=asyncio.FIRST_COMPLETED
        )
        if cancel_task in done:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
            raise GenerationCancelled()
        return pending.result()
    finally:
        if not pending.done():
            pending.cancel()
        if not cancel_task.done():
            cancel_task.cancel()
        await asyncio.gather(pending, cancel_task, return_exceptions=True)


def raise_if_cancelled(token: CancellationToken) -> None:
    """Apply the existing Core cancellation semantics at a stream boundary."""

    token.raise_if_cancelled()


__all__ = [
    "close_stream",
    "next_stream_value",
    "plain_json",
    "raise_if_cancelled",
    "require_json_object",
    "usage_int",
]
