"""The single, deterministic Slash Command Registry."""

from __future__ import annotations

import re

from .models import CommandDefinition


_CANONICAL_PATTERN = re.compile(r"^[a-z][a-z0-9_-]*$")
_ALIAS_PATTERN = re.compile(r"^[a-z][a-z0-9_-]*$|^\?$")


def _validate_identifier(value: object, *, alias: bool) -> str:
    if not isinstance(value, str) or not value:
        label = "alias" if alias else "canonical command name"
        raise ValueError(f"{label} must be a non-empty lowercase identifier")
    pattern = _ALIAS_PATTERN if alias else _CANONICAL_PATTERN
    if value != value.lower() or not pattern.fullmatch(value):
        label = "alias" if alias else "canonical command name"
        raise ValueError(f"invalid {label}: {value!r}")
    return value


class CommandRegistry:
    """Store command definitions in registration order and resolve aliases."""

    def __init__(self) -> None:
        self._commands: dict[str, CommandDefinition] = {}
        self._aliases: dict[str, str] = {}

    def register(self, definition: CommandDefinition) -> None:
        """Register one definition atomically.

        All identifiers and conflicts are checked before either internal map is
        changed.  This makes a failed registration observationally harmless.
        """

        if not isinstance(definition, CommandDefinition):
            raise TypeError("definition must be CommandDefinition")

        canonical = _validate_identifier(definition.canonical, alias=False)
        aliases = tuple(
            _validate_identifier(alias, alias=True) for alias in definition.aliases
        )
        if len(set(aliases)) != len(aliases):
            raise ValueError(f"duplicate aliases for command {canonical!r}")

        occupied = set(self._commands) | set(self._aliases)
        if canonical in occupied:
            raise ValueError(
                f"command name {canonical!r} conflicts with an existing command or alias"
            )
        if canonical in aliases:
            raise ValueError(
                f"command name {canonical!r} conflicts with one of its aliases"
            )
        conflicts = [alias for alias in aliases if alias in occupied or alias == canonical]
        if conflicts:
            raise ValueError(
                f"alias {conflicts[0]!r} conflicts with an existing command or alias"
            )

        self._commands[canonical] = definition
        for alias in aliases:
            self._aliases[alias] = canonical

    def resolve(self, name_or_alias: str) -> CommandDefinition | None:
        """Resolve a canonical name or alias case-insensitively.

        Definitions remain slash-free and lowercase; accepting one leading
        slash here is only input normalization for callers that already have a
        user-facing command token.
        """

        if not isinstance(name_or_alias, str):
            return None
        value = name_or_alias.strip()
        if value.startswith("/"):
            value = value[1:]
        if not value or "/" in value or any(character.isspace() for character in value):
            return None
        value = value.lower()
        canonical = value if value in self._commands else self._aliases.get(value)
        return self._commands.get(canonical) if canonical is not None else None

    def list_commands(
        self,
        *,
        include_hidden: bool = True,
    ) -> tuple[CommandDefinition, ...]:
        """Return definitions in stable registration order."""

        if include_hidden:
            return tuple(self._commands.values())
        return tuple(command for command in self._commands.values() if not command.hidden)


__all__ = ["CommandRegistry"]
