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


def _registry() -> CommandRegistry:
    registry = CommandRegistry()
    registry.register(
        CommandDefinition(
            canonical="review",
            description="review",
            kind=CommandKind.PROMPT,
        )
    )
    registry.register(
        CommandDefinition(
            canonical="do",
            aliases=("run",),
            description="do",
            kind=CommandKind.PROMPT,
            arguments=(ArgumentSpec("target", required=True),),
        )
    )
    registry.register(
        CommandDefinition(
            canonical="clear",
            description="clear",
            kind=CommandKind.LOCAL,
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
    assert invocation.query == "value"
    assert invocation.error is not None


def test_canonical_and_alias_calls_normalize_name_but_keep_raw_call_name() -> None:
    parser = CommandParser(_registry())

    canonical = parser.parse("/REVIEW question")
    alias = parser.parse("/RUN target -- question")

    assert canonical.raw_name == "REVIEW"
    assert canonical.canonical == "review"
    assert canonical.alias is None
    assert canonical.query == "question"
    assert alias.raw_name == "RUN"
    assert alias.canonical == "do"
    assert alias.alias == "run"


def test_prompt_query_is_preserved_without_token_reconstruction() -> None:
    query = "关注并发安全 以及 -- 原始文本"
    invocation = CommandParser(_registry()).parse(f"/review {query}")

    assert invocation.status is InvocationStatus.READY
    assert invocation.args == ()
    assert invocation.query == query
    assert invocation.separator_seen is False


def test_arguments_use_shlex_and_query_after_separator_is_raw() -> None:
    invocation = CommandParser(_registry()).parse(
        '/do "target one" -- 请实现并测试 -- 保留引号 "原样"'
    )

    assert invocation.status is InvocationStatus.READY
    assert invocation.args == ("target one",)
    assert invocation.query == '请实现并测试 -- 保留引号 "原样"'
    assert invocation.separator_seen is True


@pytest.mark.parametrize(
    "text",
    [
        '/do "unclosed -- query',
        "/do -- query",
        "/do one two",
    ],
)
def test_unclosed_missing_and_extra_arguments_are_usage_errors(text: str) -> None:
    invocation = CommandParser(_registry()).parse(text)

    assert invocation.status is InvocationStatus.USAGE_ERROR
    assert invocation.definition is not None
    assert invocation.error is not None
    assert "用法" in invocation.error


def test_quoted_separator_is_an_argument_not_a_query_delimiter() -> None:
    invocation = CommandParser(_registry()).parse('/do "--" -- actual query')

    assert invocation.status is InvocationStatus.READY
    assert invocation.args == ("--",)
    assert invocation.query == "actual query"


def test_local_command_with_arguments_is_a_usage_error() -> None:
    invocation = CommandParser(_registry()).parse("/clear extra")

    assert invocation.status is InvocationStatus.USAGE_ERROR
