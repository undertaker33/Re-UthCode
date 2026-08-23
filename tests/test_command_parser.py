from __future__ import annotations

import pytest

from uthcode.application.commands import (
    ArgumentSpec,
    CommandDefinition,
    CommandKind,
    CommandParser,
    CommandRegistry,
    InvocationStatus,
)


def _handler(_context: object) -> str:
    return "ok"


def _registry() -> CommandRegistry:
    registry = CommandRegistry()
    registry.register(
        CommandDefinition(
            canonical="review",
            description="review",
            kind=CommandKind.LOCAL,
            handler=_handler,
        )
    )
    registry.register(
        CommandDefinition(
            canonical="do",
            aliases=("run",),
            description="do",
            kind=CommandKind.LOCAL,
            arguments=(ArgumentSpec("target", required=True),),
            handler=_handler,
        )
    )
    registry.register(
        CommandDefinition(
            canonical="clear",
            description="clear",
            kind=CommandKind.LOCAL,
            handler=_handler,
        )
    )
    return registry


def test_plain_text_is_not_a_slash_command() -> None:
    invocation = CommandParser(_registry()).parse("ordinary text")

    assert invocation.status is InvocationStatus.TEXT
    assert invocation.is_slash is False
    assert invocation.is_executable is False


def test_bare_slash_is_marked_but_not_executable() -> None:
    invocation = CommandParser(_registry()).parse("/")

    assert invocation.status is InvocationStatus.SLASH
    assert invocation.is_slash is True
    assert invocation.is_bare_slash is True
    assert invocation.canonical is None
    assert invocation.is_executable is False


def test_unknown_command_is_structured_and_keeps_raw_name() -> None:
    invocation = CommandParser(_registry()).parse("/Missing value")

    assert invocation.status is InvocationStatus.UNKNOWN_COMMAND
    assert invocation.raw_name == "Missing"
    assert invocation.canonical is None
    assert invocation.args == ()
    assert invocation.error is not None


def test_canonical_and_alias_calls_normalize_name_but_keep_raw_call_name() -> None:
    parser = CommandParser(_registry())

    canonical = parser.parse("/REVIEW")
    alias = parser.parse("/RUN target")

    assert canonical.raw_name == "REVIEW"
    assert canonical.canonical == "review"
    assert canonical.alias is None
    assert alias.raw_name == "RUN"
    assert alias.canonical == "do"
    assert alias.alias == "run"
    assert alias.args == ("target",)


def test_arguments_use_shlex_without_a_second_input_channel() -> None:
    invocation = CommandParser(_registry()).parse('/do "target one"')

    assert invocation.status is InvocationStatus.READY
    assert invocation.args == ("target one",)


@pytest.mark.parametrize(
    "text",
    [
        '/do "unclosed',
        "/do",
        "/do one two",
        "/clear extra",
        "/do -- focus",
    ],
)
def test_malformed_missing_and_extra_arguments_are_usage_errors(text: str) -> None:
    invocation = CommandParser(_registry()).parse(text)

    assert invocation.status is InvocationStatus.USAGE_ERROR
    assert invocation.definition is not None
    assert invocation.error is not None
    assert "用法" in invocation.error
