"""Registry-aware Slash Command parsing with lossless prompt queries."""

from __future__ import annotations

import shlex

from .models import (
    CommandDefinition,
    CommandInvocation,
    CommandKind,
    InvocationStatus,
)
from .registry import CommandRegistry


def _shell_tokens(value: str) -> tuple[str, ...]:
    """Tokenize arguments with POSIX ``shlex`` rules and no comments."""

    lexer = shlex.shlex(value, posix=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    return tuple(lexer)


def _separator_span(value: str) -> tuple[int, int] | None:
    """Find the first unquoted, unescaped token whose raw spelling is ``--``."""

    length = len(value)
    index = 0
    while index < length:
        while index < length and value[index].isspace():
            index += 1
        if index >= length:
            return None

        start = index
        quote: str | None = None
        escaped = False
        while index < length:
            character = value[index]
            if escaped:
                escaped = False
                index += 1
                continue
            if character == "\\" and quote != "'":
                escaped = True
                index += 1
                continue
            if quote is None and character in ("'", '"'):
                quote = character
                index += 1
                continue
            if quote is not None and character == quote:
                quote = None
                index += 1
                continue
            if quote is None and character.isspace():
                break
            index += 1

        end = index
        if quote is None and value[start:end] == "--":
            return start, end
        while index < length and value[index].isspace():
            index += 1
    return None


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
                query=tail,
                error=f"未知命令：/{lookup_name}",
            )

        alias = lookup_name if lookup_name != definition.canonical else None
        # A prompt-only command has no argument region to separate; ``--`` is
        # then ordinary prompt text.  The delimiter is meaningful when the
        # definition declares structured positional arguments.
        separator = _separator_span(tail) if definition.arguments else None
        separator_seen = separator is not None
        if separator is None:
            argument_text = tail
            query = ""
        else:
            separator_start, separator_end = separator
            argument_text = tail[:separator_start].rstrip()
            query = tail[separator_end:].lstrip()

        try:
            if separator is not None and not definition.accepts_query and query:
                return self._usage_error(
                    text,
                    raw_name,
                    definition,
                    alias,
                    separator_seen,
                    "this command does not accept a query",
                )

            if definition.arguments:
                args = _shell_tokens(argument_text)
                self._validate_arguments(definition, args)
            else:
                if separator is None and definition.accepts_query:
                    args = ()
                    query = tail
                else:
                    args = _shell_tokens(argument_text) if argument_text else ()
                if args:
                    return self._usage_error(
                        text,
                        raw_name,
                        definition,
                        alias,
                        separator_seen,
                        "unexpected arguments",
                    )
                if not definition.accepts_query and query:
                    return self._usage_error(
                        text,
                        raw_name,
                        definition,
                        alias,
                        separator_seen,
                        "this command does not accept a query",
                    )

            if definition.query_required and not query:
                return self._usage_error(
                    text,
                    raw_name,
                    definition,
                    alias,
                    separator_seen,
                    "a query is required",
                )
        except (ValueError, TypeError) as exc:
            return self._usage_error(
                text,
                raw_name,
                definition,
                alias,
                separator_seen,
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
            query=query,
            separator_seen=separator_seen,
            definition=definition,
        )

    @staticmethod
    def _validate_arguments(
        definition: CommandDefinition,
        args: tuple[str, ...],
    ) -> None:
        specifications = definition.arguments
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
        separator_seen: bool,
        reason: str,
    ) -> CommandInvocation:
        return CommandInvocation(
            raw_input=raw_input,
            status=InvocationStatus.USAGE_ERROR,
            is_slash=True,
            raw_name=raw_name,
            canonical=definition.canonical,
            alias=alias,
            separator_seen=separator_seen,
            definition=definition,
            error=f"用法错误：{reason}；用法：{definition.usage_text}",
        )


def parse_command(registry: CommandRegistry, text: str) -> CommandInvocation:
    """Convenience entry point for callers that do not retain a parser object."""

    return CommandParser(registry).parse(text)


__all__ = ["CommandParser", "parse_command"]
