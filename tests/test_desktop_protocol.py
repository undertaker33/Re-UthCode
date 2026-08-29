from __future__ import annotations

import json

import pytest

from uthcode.interfaces.desktop.protocol import (
    AgentEventEnvelope,
    ProtocolError,
    RequestEnvelope,
    ResponseEnvelope,
    RuntimeStateEnvelope,
    encode_envelope,
    error_response,
    parse_request_line,
)


def test_request_envelope_round_trips_and_rejects_unknown_fields() -> None:
    request = parse_request_line(
        '{"type":"request","id":"req-1","method":"status.get","params":{}}'
    )

    assert request == RequestEnvelope("req-1", "status.get", {})
    assert json.loads(encode_envelope(request)) == {
        "type": "request",
        "id": "req-1",
        "method": "status.get",
        "params": {},
    }

    with pytest.raises(ProtocolError, match="unknown fields") as error:
        parse_request_line(
            '{"type":"request","id":"req-1","method":"status.get",'
            '"params":{},"extra":true}'
        )
    assert error.value.request_id == "req-1"


@pytest.mark.parametrize(
    "line",
    [
        "not-json",
        "[]",
        '{"type":"request","id":"req-1","method":"status.get",'
        '"params":[],"extra":true}',
        '{"type":"request","id":"req-1","method":"status.get"}',
        '{"type":"request","id":"","method":"status.get","params":{}}',
        '{"type":"request","id":7,"method":"status.get","params":{}}',
        '{"type":"response","id":"req-1","method":"status.get","params":{}}',
        '{"type":"request","id":"req-1","method":"status.get",'
        '"params":{},"id":"req-2"}',
    ],
)
def test_request_parser_rejects_invalid_jsonl_envelopes(line: str) -> None:
    with pytest.raises(ProtocolError):
        parse_request_line(line)


def test_duplicate_json_keys_are_not_silently_accepted() -> None:
    with pytest.raises(ProtocolError, match="duplicate"):
        parse_request_line(
            '{"type":"request","id":"req-1","method":"status.get",'
            '"params":{},"params":{}}'
        )


def test_response_error_and_event_envelopes_are_jsonl_safe() -> None:
    response = ResponseEnvelope("req-1", True, {"run_id": "run-1"})
    error = error_response("req-2", "invalid_request", "bad request")
    event = AgentEventEnvelope({"type": "turn_completed", "run_id": "r", "turn_id": "t", "final_text": "ok"})
    state = RuntimeStateEnvelope("ready")

    assert json.loads(encode_envelope(response))["ok"] is True
    assert json.loads(encode_envelope(error)) == {
        "type": "response",
        "id": "req-2",
        "ok": False,
        "error": {"kind": "invalid_request", "message": "bad request"},
    }
    assert json.loads(encode_envelope(event))["event"]["type"] == "turn_completed"
    assert json.loads(encode_envelope(state)) == {
        "type": "runtime_state",
        "state": "ready",
    }


def test_response_requires_exactly_one_success_or_error_payload() -> None:
    with pytest.raises(ValueError):
        ResponseEnvelope("req-1", True, {}, {"kind": "bad", "message": "bad"})
    with pytest.raises(ValueError):
        ResponseEnvelope("req-1", False, {})
