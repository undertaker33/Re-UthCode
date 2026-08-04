"""Minimal Provider construction configuration.

The configuration stores the name of the environment variable that contains a
secret, never the secret itself. Loading, validation, and construction remain
inside the Provider Integration boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ProviderKind(str, Enum):
    FAKE = "fake"
    ANTHROPIC = "anthropic"
    OPENAI_RESPONSES = "openai_responses"
    OPENAI_COMPAT = "openai_compat"


def _require_text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    """The construction parameters needed by this Provider batch."""

    kind: ProviderKind | str
    model: str
    api_key_env: str | None = None
    base_url: str | None = None
    max_output_tokens: int | None = None

    def __post_init__(self) -> None:
        try:
            kind = self.kind if isinstance(self.kind, ProviderKind) else ProviderKind(self.kind)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"unknown provider kind: {self.kind!r}") from exc
        _require_text(self.model, "model")
        if self.api_key_env is not None:
            _require_text(self.api_key_env, "api_key_env")
        if self.base_url is not None:
            _require_text(self.base_url, "base_url")
        if self.max_output_tokens is not None and (
            isinstance(self.max_output_tokens, bool)
            or not isinstance(self.max_output_tokens, int)
            or self.max_output_tokens < 0
        ):
            raise ValueError("max_output_tokens must be a non-negative integer or None")
        object.__setattr__(self, "kind", kind)


__all__ = ["ProviderConfig", "ProviderKind"]
