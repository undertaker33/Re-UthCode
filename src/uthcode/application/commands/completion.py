"""Command and argument completion derived entirely from the Registry."""

from __future__ import annotations

from .models import (
    CommandDefinition,
    CommandInvocation,
    CompletionCandidate,
)
from .parser import CommandParser
from .registry import CommandRegistry


class CompletionEngine:
    """Produce command, usage, and argument candidates without UI coupling."""

    def __init__(self, registry: CommandRegistry, application: object | None = None) -> None:
        if not isinstance(registry, CommandRegistry):
            raise TypeError("registry must be CommandRegistry")
        self._registry = registry
        self._application = application

    def complete(
        self,
        prefix: str,
        *,
        application: object | None = None,
    ) -> tuple[CompletionCandidate, ...]:
        """Return matching visible commands, with help always last."""

        if not isinstance(prefix, str):
            raise TypeError("completion prefix must be a string")
        text = prefix.lstrip()
        if not text.startswith("/"):
            return ()
        command_prefix = text[1:]
        if any(character.isspace() for character in command_prefix):
            return ()
        query = command_prefix.lower()

        definitions = self._registry.list_commands(include_hidden=False)
        help_definition = next(
            (
                definition
                for definition in definitions
                if definition.canonical == "help"
            ),
            None,
        )
        matches: list[CompletionCandidate] = []
        for definition in definitions:
            if help_definition is not None and definition is help_definition:
                continue
            matched_alias = self._matching_alias(definition, query)
            if query and not (
                definition.canonical.startswith(query) or matched_alias is not None
            ):
                continue
            matches.append(self._candidate(definition, matched_alias))

        if help_definition is not None:
            matches.append(self._candidate(help_definition, self._matching_alias(help_definition, query)))
        return tuple(matches)

    def argument_candidates(
        self,
        invocation_or_definition: CommandInvocation | CommandDefinition | str,
        *,
        argument_index: int | None = None,
        application: object | None = None,
    ) -> tuple[str, ...]:
        """Return static or dynamic candidates for the next argument."""

        definition: CommandDefinition | None
        used_index = argument_index
        if isinstance(invocation_or_definition, CommandInvocation):
            definition = invocation_or_definition.definition
            if used_index is None:
                used_index = len(invocation_or_definition.args)
        elif isinstance(invocation_or_definition, CommandDefinition):
            definition = invocation_or_definition
        elif isinstance(invocation_or_definition, str):
            invocation = CommandParser(self._registry).parse(invocation_or_definition)
            definition = invocation.definition
            if used_index is None:
                used_index = len(invocation.args)
        else:
            raise TypeError("completion target must be a CommandInvocation or definition")

        if definition is None:
            return ()
        index = 0 if used_index is None else used_index
        if index < 0 or index >= len(definition.arguments):
            return ()
        selected_application = (
            self._application if application is None else application
        )
        return definition.arguments[index].candidate_values(selected_application)

    def usage_for(
        self,
        invocation_or_definition: CommandInvocation | CommandDefinition,
    ) -> str | None:
        definition = (
            invocation_or_definition.definition
            if isinstance(invocation_or_definition, CommandInvocation)
            else invocation_or_definition
        )
        return None if definition is None else definition.usage_text

    def argument_prompt_for(
        self,
        invocation_or_definition: CommandInvocation | CommandDefinition,
    ) -> str | None:
        definition = (
            invocation_or_definition.definition
            if isinstance(invocation_or_definition, CommandInvocation)
            else invocation_or_definition
        )
        return None if definition is None else definition.argument_prompt

    @staticmethod
    def _matching_alias(
        definition: CommandDefinition,
        query: str,
    ) -> str | None:
        if not query:
            return None
        for alias in definition.aliases:
            if alias.startswith(query):
                return alias
        return None

    @staticmethod
    def _candidate(
        definition: CommandDefinition,
        matched_alias: str | None,
    ) -> CompletionCandidate:
        marker = "（未实现）" if not definition.implemented else ""
        display = f"/{definition.canonical} — {definition.description}"
        if marker:
            display = f"{display} {marker}"
        return CompletionCandidate(
            canonical=definition.canonical,
            display=display,
            description=definition.description,
            aliases=definition.aliases,
            availability=definition.availability,
            usage=definition.usage_text,
            argument_prompt=definition.argument_prompt,
            matched_alias=matched_alias,
            definition=definition,
        )


def complete_commands(
    registry: CommandRegistry,
    prefix: str,
    *,
    application: object | None = None,
) -> tuple[CompletionCandidate, ...]:
    """Functional completion entry point for lightweight callers."""

    return CompletionEngine(registry, application).complete(prefix)


__all__ = ["CompletionEngine", "complete_commands"]
