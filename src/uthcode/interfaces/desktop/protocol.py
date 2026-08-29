"""Small, strict JSONL envelopes for the private Desktop child process.

The protocol is deliberately narrower than a general RPC framework.  It only
validates transport envelopes; method semantics remain in ``bridge.py`` and
the Application public API remains the source of all Agent facts.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, TextIO


_MISSING = object()


class ProtocolError(ValueError):
    """A malformed or unsupported JSONL protocol message.

    ``message`` is intentionally stable and does not contain parser or
    application exception details.  ``request_id`` is retained only when it
    was safely available for response correlation.
    """

    def __init__(
        self,
        kind: str,
        message: str,
        *,
        request_id: str | None = None,
    ) -> None:
        if not isinstance(kind, str) or not kind.strip():
            raise ValueError("protocol error kind must be a non-empty string")
        if not isinstance(message, str) or not message.strip():
            raise ValueError("protocol error message must be a non-empty string")
        if request_id is not None and (
            not isinstance(request_id, str) or not request_id.strip()
        ):
            raise ValueError("protocol error request_id must be a non-empty string or None")
        self.kind = kind
        self.message = message
        self.request_id = request_id
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class ErrorPayload:
    """Stable public error payload carried by a failed response."""

    kind: str
    message: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, str) or not self.kind.strip():
            raise ValueError("error kind must be a non-empty string")
        if not isinstance(self.message, str) or not self.message.strip():
            raise ValueError("error message must be a non-empty string")

    def to_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "message": self.message}


def _json_safe(value: object, *, path: str = "value") -> object:
    """Validate and normalize the small JSON value subset used on the wire."""

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise TypeError(f"{path} must contain finite numbers")
        return value
    if isinstance(value, Mapping):
        normalized: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"{path} object keys must be strings")
            normalized[key] = _json_safe(item, path=f"{path}.{key}")
        return normalized
    if isinstance(value, (list, tuple)):
        return [
            _json_safe(item, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        ]
    raise TypeError(f"{path} is not JSON-safe")


def _require_keys(
    value: Mapping[str, object],
    expected: set[str],
    *,
    label: str,
) -> None:
    actual = set(value)
    missing = expected - actual
    if missing:
        raise ProtocolError(
            "invalid_request",
            f"{label} is missing fields: {sorted(missing)!r}",
        )
    extra = actual - expected
    if extra:
        raise ProtocolError(
            "invalid_request",
            f"{label} has unknown fields: {sorted(extra)!r}",
        )


def _require_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProtocolError("invalid_request", f"{field} must be a non-empty string")
    return value


@dataclass(frozen=True, slots=True)
class RequestEnvelope:
    """One strict request from Electron Main to the Python Bridge."""

    id: str
    method: str
    params: Mapping[str, object]

    def __post_init__(self) -> None:
        _require_text(self.id, "id")
        method = _require_text(self.method, "method")
        if any(character.isspace() for character in method):
            raise ProtocolError("invalid_request", "method must not contain whitespace")
        if not isinstance(self.params, Mapping):
            raise ProtocolError("invalid_request", "params must be an object")
        normalized = _json_safe(self.params, path="params")
        if not isinstance(normalized, dict):  # pragma: no cover - Mapping invariant
            raise TypeError("normalized params must be an object")
        object.__setattr__(self, "method", method)
        object.__setattr__(self, "params", MappingProxyType(normalized))

    @property
    def type(self) -> str:
        return "request"

    def to_dict(self) -> dict[str, object]:
        return {
            "type": self.type,
            "id": self.id,
            "method": self.method,
            "params": dict(self.params),
        }


@dataclass(frozen=True, slots=True)
class ResponseEnvelope:
    """One correlated response; exactly one success/error branch is present."""

    id: str | None
    ok: bool
    result: object = _MISSING
    error: ErrorPayload | Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        if self.id is not None and (
            not isinstance(self.id, str) or not self.id.strip()
        ):
            raise ValueError("response id must be a non-empty string or None")
        if not isinstance(self.ok, bool):
            raise TypeError("response ok must be a boolean")
        if self.ok:
            if self.error is not None:
                raise ValueError("successful response must not contain error")
            if self.result is _MISSING:
                raise ValueError("successful response requires result")
            object.__setattr__(self, "result", _json_safe(self.result, path="result"))
            return
        if self.error is None:
            raise ValueError("failed response requires error")
        if self.result is not _MISSING:
            raise ValueError("failed response must not contain result")
        error = self.error
        if isinstance(error, ErrorPayload):
            normalized = error
        elif isinstance(error, Mapping):
            _require_keys(error, {"kind", "message"}, label="error")
            normalized = ErrorPayload(
                _require_text(error.get("kind"), "error.kind"),
                _require_text(error.get("message"), "error.message"),
            )
        else:
            raise TypeError("error must be ErrorPayload or an object")
        object.__setattr__(self, "error", normalized)

    @property
    def type(self) -> str:
        return "response"

    def to_dict(self) -> dict[str, object]:
        value: dict[str, object] = {
            "type": self.type,
            "id": self.id,
            "ok": self.ok,
        }
        if self.ok:
            value["result"] = self.result
        else:
            assert isinstance(self.error, ErrorPayload)
            value["error"] = self.error.to_dict()
        return value


@dataclass(frozen=True, slots=True)
class AgentEventEnvelope:
    """Transport wrapper for one Application ``AgentEvent.to_dict()`` value."""

    event: Mapping[str, object]

    def __post_init__(self) -> None:
        if not isinstance(self.event, Mapping):
            raise TypeError("agent event must be an object")
        normalized = _json_safe(self.event, path="event")
        if not isinstance(normalized, dict):  # pragma: no cover - Mapping invariant
            raise TypeError("normalized event must be an object")
        if not isinstance(normalized.get("type"), str) or not normalized["type"].strip():
            raise ValueError("agent event must contain a non-empty type")
        object.__setattr__(self, "event", MappingProxyType(normalized))

    @property
    def type(self) -> str:
        return "agent_event"

    def to_dict(self) -> dict[str, object]:
        return {"type": self.type, "event": dict(self.event)}


@dataclass(frozen=True, slots=True)
class RuntimeStateEnvelope:
    """Transport lifecycle projection, separate from Agent/Provider failures."""

    state: str
    error: ErrorPayload | Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        _require_text(self.state, "state")
        if self.error is not None:
            error = self.error
            if not isinstance(error, ErrorPayload):
                if not isinstance(error, Mapping):
                    raise TypeError("runtime state error must be an object")
                _require_keys(error, {"kind", "message"}, label="runtime state error")
                error = ErrorPayload(
                    _require_text(error.get("kind"), "error.kind"),
                    _require_text(error.get("message"), "error.message"),
                )
            object.__setattr__(self, "error", error)

    @property
    def type(self) -> str:
        return "runtime_state"

    def to_dict(self) -> dict[str, object]:
        value: dict[str, object] = {"type": self.type, "state": self.state}
        if self.error is not None:
            assert isinstance(self.error, ErrorPayload)
            value["error"] = self.error.to_dict()
        return value


Envelope = RequestEnvelope | ResponseEnvelope | AgentEventEnvelope | RuntimeStateEnvelope


def _object_no_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ProtocolError("invalid_request", f"duplicate JSON field: {key}")
        value[key] = item
    return value


def _parse_json_object(line: str) -> Mapping[str, object]:
    if not isinstance(line, str):
        raise TypeError("JSONL input must be a string")
    if not line.strip():
        raise ProtocolError("invalid_json", "JSONL line is empty")
    try:
        value = json.loads(
            line,
            object_pairs_hook=_object_no_duplicates,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                ProtocolError("invalid_json", "JSON constants must be finite values")
            ),
        )
    except ProtocolError:
        raise
    except (TypeError, ValueError, json.JSONDecodeError):
        raise ProtocolError("invalid_json", "invalid JSONL message") from None
    if not isinstance(value, Mapping):
        raise ProtocolError("invalid_request", "JSONL message must be an object")
    return value


def request_from_dict(value: Mapping[str, object]) -> RequestEnvelope:
    if not isinstance(value, Mapping):
        raise ProtocolError("invalid_request", "request must be an object")
    _require_keys(value, {"type", "id", "method", "params"}, label="request")
    if value.get("type") != "request":
        raise ProtocolError("invalid_request", "request type must be 'request'")
    try:
        return RequestEnvelope(
            _require_text(value.get("id"), "id"),
            _require_text(value.get("method"), "method"),
            value.get("params"),  # type: ignore[arg-type]
        )
    except ProtocolError:
        raise
    except (TypeError, ValueError):
        raise ProtocolError("invalid_request", "request envelope is invalid") from None


def parse_request_line(line: str) -> RequestEnvelope:
    """Parse one complete JSONL request with duplicate/unknown-field checks."""

    value = _parse_json_object(line)
    try:
        return request_from_dict(value)
    except ProtocolError as exc:
        # Preserve correlation only when the id itself is already a valid
        # non-empty string.  Malformed/duplicate ids stay uncorrelated.
        request_id = value.get("id")
        if exc.request_id is None and isinstance(request_id, str) and request_id.strip():
            raise ProtocolError(
                exc.kind,
                exc.message,
                request_id=request_id,
            ) from None
        raise


def encode_envelope(envelope: Envelope) -> str:
    """Serialize one envelope without ever writing a non-protocol line."""

    if not isinstance(
        envelope,
        (RequestEnvelope, ResponseEnvelope, AgentEventEnvelope, RuntimeStateEnvelope),
    ):
        raise TypeError("unsupported protocol envelope")
    try:
        value = envelope.to_dict()
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError):
        raise ProtocolError("invalid_response", "protocol envelope is not JSON-safe") from None


def write_envelope(stream: TextIO, envelope: Envelope) -> None:
    """Write and flush exactly one JSONL protocol line to ``stream``."""

    stream.write(encode_envelope(envelope) + "\n")
    stream.flush()


def error_response(
    request_id: str | None,
    kind: str,
    message: str,
) -> ResponseEnvelope:
    """Build a safe failed response for a request or an uncorrelated line."""

    return ResponseEnvelope(request_id, False, error=ErrorPayload(kind, message))


__all__ = [
    "AgentEventEnvelope",
    "Envelope",
    "ErrorPayload",
    "ProtocolError",
    "RequestEnvelope",
    "ResponseEnvelope",
    "RuntimeStateEnvelope",
    "encode_envelope",
    "error_response",
    "parse_request_line",
    "request_from_dict",
    "write_envelope",
]
