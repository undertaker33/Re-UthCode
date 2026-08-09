from __future__ import annotations

import pytest

from uthcode.application.commands import (
    CommandAvailability,
    CommandDefinition,
    CommandKind,
    CommandRegistry,
    create_builtin_registry,
)


def _command(
    name: str,
    *,
    aliases: tuple[str, ...] = (),
    hidden: bool = False,
) -> CommandDefinition:
    return CommandDefinition(
        canonical=name,
        aliases=aliases,
        description=name,
        kind=CommandKind.LOCAL,
        hidden=hidden,
    )


def test_registry_resolves_canonical_and_alias_case_insensitively() -> None:
    registry = CommandRegistry()
    definition = _command("first", aliases=("f", "?"))
    registry.register(definition)

    assert registry.resolve("first") is definition
    assert registry.resolve("FIRST") is definition
    assert registry.resolve("/F") is definition
    assert registry.resolve("?") is definition
    assert registry.resolve("missing") is None


def test_registry_preserves_registration_order_and_hidden_state() -> None:
    registry = CommandRegistry()
    visible = _command("visible")
    hidden = _command("hidden", hidden=True)
    last = _command("last")
    registry.register(visible)
    registry.register(hidden)
    registry.register(last)

    assert [command.canonical for command in registry.list_commands()] == [
        "visible",
        "hidden",
        "last",
    ]
    assert [command.canonical for command in registry.list_commands(include_hidden=False)] == [
        "visible",
        "last",
    ]
    assert registry.resolve("hidden") is hidden
    assert hidden.hidden is True


@pytest.mark.parametrize(
    "conflicting_definition",
    [
        _command("first"),
        _command("second", aliases=("first",)),
        _command("first-alias", aliases=("first",)),
        _command("second-alias", aliases=("first-alias",)),
        _command("duplicate-alias", aliases=("same", "same")),
    ],
)
def test_registration_conflicts_are_rejected_atomically(
    conflicting_definition: CommandDefinition,
) -> None:
    registry = CommandRegistry()
    registry.register(_command("first", aliases=("first-alias",)))
    before = registry.list_commands()

    with pytest.raises(ValueError):
        registry.register(conflicting_definition)

    assert registry.list_commands() == before
    assert registry.resolve("first") is not None
    assert registry.resolve("first-alias") is not None


@pytest.mark.parametrize(
    "name",
    ["Upper", "has space", "has/slash", "bad!", "", "-starts-with-dash"],
)
def test_invalid_canonical_names_are_rejected(name: str) -> None:
    registry = CommandRegistry()
    with pytest.raises(ValueError):
        registry.register(_command(name))
    assert registry.list_commands() == ()


@pytest.mark.parametrize("alias", ["Alias", "has space", "has/slash", "bad!"])
def test_invalid_aliases_are_rejected_without_partial_registration(alias: str) -> None:
    registry = CommandRegistry()
    with pytest.raises(ValueError):
        registry.register(_command("valid", aliases=(alias,)))
    assert registry.list_commands() == ()


def test_definition_exposes_implementation_status_and_generated_usage() -> None:
    definition = CommandDefinition(
        canonical="future",
        description="future command",
        kind=CommandKind.LOCAL,
        availability=CommandAvailability.NOT_IMPLEMENTED,
    )

    assert definition.implemented is False
    assert definition.usage_text == "/future"


def test_builtin_registry_has_only_final_behavior_mode_command_names() -> None:
    registry = create_builtin_registry()
    plan = registry.resolve("plan")
    execute = registry.resolve("do")

    assert plan is not None and plan.implemented
    assert execute is not None and execute.implemented
    assert registry.resolve("build") is execute
    assert registry.resolve("p") is None
    assert "p" not in plan.aliases
    assert execute.aliases == ("build",)
    assert all(
        definition.canonical != "build"
        for definition in registry.list_commands()
    )
