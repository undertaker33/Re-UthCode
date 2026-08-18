"""Opaque credential values shared across the Core configuration boundary."""

from __future__ import annotations


class SecretValue:
    """A non-serializable credential whose display form is always redacted.

    The value is deliberately only revealed at the Provider SDK construction
    boundary.  It has no JSON projection and its representation never
    includes the underlying text, so configuration, diagnostics, and event
    projections cannot accidentally publish a credential.
    """

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("secret value must be a non-empty string")
        self._value = value

    @classmethod
    def from_text(cls, value: str) -> "SecretValue":
        return cls(value)

    def reveal(self) -> str:
        """Return the credential only for the Provider construction edge."""

        return self._value

    def __repr__(self) -> str:
        return "<SecretValue redacted>"

    def __str__(self) -> str:
        return "<redacted>"

    def __format__(self, _format_spec: str) -> str:
        return "<redacted>"

    def __bool__(self) -> bool:
        return True

    def __reduce__(self):  # pragma: no cover - defensive serialization guard
        raise TypeError("SecretValue is not serializable")

    def __getstate__(self):  # pragma: no cover - defensive serialization guard
        raise TypeError("SecretValue is not serializable")


__all__ = ["SecretValue"]
