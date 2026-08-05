from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

import pytest
from anthropic.types.beta import BetaRawMessageStopEvent

from uthcode.core.provider import CancellationToken, GenerationCancelled
from uthcode.integrations.providers.common import (
    close_stream,
    plain_json,
    raise_if_cancelled,
    require_json_object,
    usage_int,
)


def test_plain_json_preserves_nested_values_and_public_sdk_serialization() -> None:
    payload = {"first": [1, True, None, {"last": "value"}]}
    assert plain_json(payload) == payload

    event = BetaRawMessageStopEvent(type="message_stop")
    serialized = plain_json(event)
    assert serialized == {"type": "message_stop"}


def test_plain_json_rejects_non_json_values_without_exposing_contents() -> None:
    class SecretValue:
        secret = "sk-common-test-secret"

    with pytest.raises(TypeError) as raised:
        plain_json(SecretValue())
    assert "sk-common-test-secret" not in str(raised.value)

    with pytest.raises(TypeError):
        plain_json({1: "not a string key"})
    with pytest.raises(TypeError):
        require_json_object(["not", "an", "object"], "payload")


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0, 0), (12, 12), (None, 7)],
)
def test_usage_int_accepts_non_negative_integers_and_default(
    value: object, expected: int
) -> None:
    assert usage_int(value, "tokens", default=7) == expected


@pytest.mark.parametrize("value", [True, False, -1, 1.5, "12"])
def test_usage_int_rejects_loose_token_values(value: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        usage_int(value, "tokens")


class _CloseOnly:
    def __init__(self) -> None:
        self.closed = 0

    async def close(self) -> None:
        self.closed += 1


class _AcloseOnly:
    def __init__(self) -> None:
        self.closed = 0

    async def aclose(self) -> None:
        self.closed += 1


class _BothCloseHooks:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def aclose(self) -> None:
        self.calls.append("aclose")

    async def close(self) -> None:
        self.calls.append("close")


class _NoCloseHooks:
    pass


@pytest.mark.asyncio
async def test_close_stream_supports_public_close_variants() -> None:
    close_only = _CloseOnly()
    aclose_only = _AcloseOnly()
    both = _BothCloseHooks()
    no_hooks = _NoCloseHooks()

    await close_stream(close_only)
    await close_stream(aclose_only)
    await close_stream(both)
    await close_stream(no_hooks)

    assert close_only.closed == 1
    assert aclose_only.closed == 1
    assert both.calls == ["aclose"]


@pytest.mark.asyncio
async def test_close_stream_does_not_hide_close_failures() -> None:
    class FailingClose:
        async def aclose(self) -> None:
            raise RuntimeError("close failure")

    with pytest.raises(RuntimeError, match="close failure"):
        await close_stream(FailingClose())


def test_raise_if_cancelled_preserves_core_semantics() -> None:
    token = CancellationToken()
    raise_if_cancelled(token)
    token.cancel()
    with pytest.raises(GenerationCancelled):
        raise_if_cancelled(token)
