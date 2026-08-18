"""Minimal Provider construction configuration.

Configuration loading resolves credentials into :class:`SecretValue` before
this boundary.  The construction DTO keeps that value opaque until the
factory hands it to a concrete SDK client.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from uthcode.core.secrets import SecretValue


_REASONING_EFFORTS = frozenset(
    {"none", "minimal", "low", "medium", "high", "xhigh", "max"}
)


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
    api_key: SecretValue | str | None = None
    base_url: str | None = None
    max_output_tokens: int | None = None
    reasoning_effort: str | None = None

    def __post_init__(self) -> None:
        try:
            kind = self.kind if isinstance(self.kind, ProviderKind) else ProviderKind(self.kind)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"unknown provider kind: {self.kind!r}") from exc
        _require_text(self.model, "model")
        if isinstance(self.api_key, str) and not self.api_key.strip():
            object.__setattr__(self, "api_key", None)
        elif self.api_key is not None and not isinstance(self.api_key, SecretValue):
            object.__setattr__(self, "api_key", SecretValue(self.api_key))
        if self.base_url is not None:
            _require_text(self.base_url, "base_url")
        if self.max_output_tokens is not None and (
            isinstance(self.max_output_tokens, bool)
            or not isinstance(self.max_output_tokens, int)
            or self.max_output_tokens < 0
        ):
            raise ValueError("max_output_tokens must be a non-negative integer or None")
        if self.reasoning_effort is not None:
            _require_text(self.reasoning_effort, "reasoning_effort")
            if self.reasoning_effort not in _REASONING_EFFORTS:
                raise ValueError(
                    "reasoning_effort must be one of: none, minimal, low, medium, high, xhigh, max"
                )
        object.__setattr__(self, "kind", kind)


__all__ = ["ProviderConfig", "ProviderKind"]
