"""Registry-driven command dispatch with interface-neutral outcomes."""

from __future__ import annotations

from dataclasses import dataclass, replace

from .models import (
    CommandDefinition,
    CommandInvocation,
    CommandKind,
    CommandOutcome,
    OutcomeStatus,
    UiAction,
)
from .parser import CommandParser
from .registry import CommandRegistry


class CommandExecutionError(RuntimeError):
    """A safe, user-facing failure raised by an Application command handler."""


@dataclass(frozen=True, slots=True)
class CommandContext:
    """Inputs available to a command handler."""

    registry: CommandRegistry
    invocation: CommandInvocation
    application: object | None


class CommandDispatcher:
    """Turn parsed invocations into exactly one structured outcome."""

    def __init__(
        self,
        registry: CommandRegistry,
        application: object | None = None,
    ) -> None:
        if not isinstance(registry, CommandRegistry):
            raise TypeError("registry must be CommandRegistry")
        self._registry = registry
        self._application = application
        self._parser = CommandParser(registry)

    def dispatch(
        self,
        invocation: CommandInvocation,
        *,
        application: object | None = None,
    ) -> CommandOutcome | None:
        """Dispatch a parsed command; ordinary text and bare ``/`` are ignored."""

        if not isinstance(invocation, CommandInvocation):
            raise TypeError("invocation must be CommandInvocation")
        if not invocation.is_slash or invocation.is_bare_slash:
            return None
        if invocation.unknown:
            return CommandOutcome(
                OutcomeStatus.UNKNOWN_COMMAND,
                error=invocation.error or f"未知命令：/{invocation.raw_name.lower()}",
                invocation=invocation,
            )
        if invocation.usage_error:
            return CommandOutcome(
                OutcomeStatus.USAGE_ERROR,
                error=invocation.error or "用法错误",
                invocation=invocation,
            )
        if not invocation.is_executable or invocation.definition is None:
            return CommandOutcome(
                OutcomeStatus.EXECUTION_ERROR,
                error="命令解析结果不可执行",
                invocation=invocation,
            )

        definition = invocation.definition
        if not definition.implemented:
            return CommandOutcome(
                OutcomeStatus.NOT_IMPLEMENTED,
                output=f"功能未实现：/{definition.canonical}",
                invocation=invocation,
            )

        selected_application = (
            self._application if application is None else application
        )
        context = CommandContext(
            registry=self._registry,
            invocation=invocation,
            application=selected_application,
        )
        try:
            result = self._run_handler(definition, context)
            return self._wrap_result(definition, invocation, result)
        except CommandExecutionError as exc:
            return CommandOutcome(
                OutcomeStatus.EXECUTION_ERROR,
                error=str(exc),
                invocation=invocation,
            )
        except Exception:  # unknown failures must not expose exception text
            return CommandOutcome(
                OutcomeStatus.EXECUTION_ERROR,
                error="命令执行失败",
                invocation=invocation,
            )

    def dispatch_text(
        self,
        text: str,
        *,
        application: object | None = None,
    ) -> CommandOutcome | None:
        """Parse and dispatch one input for small headless callers."""

        return self.dispatch(
            self._parser.parse(text),
            application=application,
        )

    @staticmethod
    def _run_handler(definition: CommandDefinition, context: CommandContext) -> object:
        if definition.handler is None:
            if definition.kind is CommandKind.PROMPT:
                return context.invocation.query
            raise CommandExecutionError(
                f"命令 /{definition.canonical} 缺少实现"
            )
        return definition.handler(context)

    @staticmethod
    def _wrap_result(
        definition: CommandDefinition,
        invocation: CommandInvocation,
        result: object,
    ) -> CommandOutcome:
        if isinstance(result, CommandOutcome):
            if result.invocation is None:
                return replace(result, invocation=invocation)
            return result

        if definition.kind is CommandKind.LOCAL:
            if result is None:
                result = ""
            if not isinstance(result, str):
                raise CommandExecutionError(
                    f"LOCAL 命令 /{definition.canonical} 必须返回文本"
                )
            return CommandOutcome.success_output(result, invocation=invocation)

        if definition.kind is CommandKind.LOCAL_UI:
            if not isinstance(result, UiAction):
                raise CommandExecutionError(
                    f"LOCAL_UI 命令 /{definition.canonical} 必须返回 UI Action"
                )
            return CommandOutcome.success_ui(result, invocation=invocation)

        if definition.kind is CommandKind.PROMPT:
            if result is None:
                result = invocation.query
            if not isinstance(result, str):
                raise CommandExecutionError(
                    f"PROMPT 命令 /{definition.canonical} 必须返回 Prompt"
                )
            return CommandOutcome.success_prompt(result, invocation=invocation)

        raise CommandExecutionError(f"未知命令类型：{definition.kind!r}")


__all__ = [
    "CommandContext",
    "CommandDispatcher",
    "CommandExecutionError",
]
