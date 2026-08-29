"""Desktop Interface entry points backed by the Application public API."""

from .bridge import BridgeError, DesktopBridge
from .protocol import (
    AgentEventEnvelope,
    ErrorPayload,
    ProtocolError,
    RequestEnvelope,
    ResponseEnvelope,
    RuntimeStateEnvelope,
)

__all__ = [
    "AgentEventEnvelope",
    "BridgeError",
    "DesktopBridge",
    "ErrorPayload",
    "ProtocolError",
    "RequestEnvelope",
    "ResponseEnvelope",
    "RuntimeStateEnvelope",
]
