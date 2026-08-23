"""Registry-aware Slash Command parsing for implemented commands."""

from __future__ import annotations

import shlex

from .models import (
    CommandDefinition,
    CommandInvocation,
    InvocationStatus,
)
from .registry import CommandRegistry


def _shell_tokens(value: str) -> tuple[str, ...]:
    """Tokenize arguments with POSIX ``shlex`` rules and no comments."""

    lexer = shlex.shlex(value, posix=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    return tuple(lexer)


class CommandParser:
    """Parse user text without sending ordinary text to the command system."""

    def __init__(self, registry: CommandRegistry) -> None:
        if not isinstance(registry, CommandRegistry):
            raise TypeError("registry must be CommandRegistry")
        self._registry = registry

    def parse(self, text: str) -> CommandInvocation:
        if not isinstance(text, str):
            raise TypeError("command input must be a string")

        leading = text.lstrip()
        if not leading.startswith("/"):
            return CommandInvocation(
                raw_input=text,
                status=InvocationStatus.TEXT,
                is_slash=False,
            )

        body = leading[1:]
        if not body or body[0].isspace():
            return CommandInvocation(
                raw_input=text,
                status=InvocationStatus.SLASH,
                is_slash=True,
            )

        name_end = 0
        while name_end < len(body) and not body[name_end].isspace():
            name_end += 1
        raw_name = body[:name_end]
        tail = body[name_end:].lstrip()
        lookup_name = raw_name.lower()
        definition = self._registry.resolve(lookup_name)

        if definition is None:
            return CommandInvocation(
                raw_input=text,
                status=InvocationStatus.UNKNOWN_COMMAND,
                is_slash=True,
                raw_name=raw_name,
                error=f"未知命令：/{lookup_name}",
            )

        alias = lookup_name if lookup_name != definition.canonical else None
        try:
            args = _shell_tokens(tail) if tail else ()
            self._validate_arguments(definition, args)
        except (ValueError, TypeError) as exc:
            return self._usage_error(
                text,
                raw_name,
                definition,
                alias,
                str(exc),
            )

        return CommandInvocation(
            raw_input=text,
            status=InvocationStatus.READY,
            is_slash=True,
            raw_name=raw_name,
            canonical=definition.canonical,
            alias=alias,
            args=tuple(args),
            definition=definition,
        )

    @staticmethod
    def _validate_arguments(
        definition: CommandDefinition,
        args: tuple[str, ...],
    ) -> None:
        specifications = definition.arguments
        if not specifications:
            if args:
                raise ValueError(f"too many arguments for {definition.usage_text}")
            return
        minimum = sum(1 for specification in specifications if specification.required)
        if len(args) < minimum:
            raise ValueError(
                f"missing argument for {definition.usage_text}"
            )
        if not specifications[-1].multiple and len(args) > len(specifications):
            raise ValueError(f"too many arguments for {definition.usage_text}")

        for index, specification in enumerate(specifications):
            if specification.multiple:
                values = args[index:]
                if specification.required and not values:
                    raise ValueError(
                        f"missing argument for {definition.usage_text}"
                    )
                if specification.choices and any(
                    value not in specification.choices for value in values
                ):
                    raise ValueError(
                        f"invalid value for argument {specification.name!r}"
                    )
                return
            if index >= len(args):
                continue
            if specification.choices and args[index] not in specification.choices:
                raise ValueError(f"invalid value for argument {specification.name!r}")

    @staticmethod
    def _usage_error(
        raw_input: str,
        raw_name: str,
        definition: CommandDefinition,
        alias: str | None,
        reason: str,
    ) -> CommandInvocation:
        return CommandInvocation(
            raw_input=raw_input,
            status=InvocationStatus.USAGE_ERROR,
            is_slash=True,
            raw_name=raw_name,
            canonical=definition.canonical,
            alias=alias,
            definition=definition,
            error=f"用法错误：{reason}；用法：{definition.usage_text}",
        )


def parse_command(registry: CommandRegistry, text: str) -> CommandInvocation:
    """Convenience entry point for callers that do not retain a parser object."""

    return CommandParser(registry).parse(text)


__all__ = ["CommandParser", "parse_command"]
