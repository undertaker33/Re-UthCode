"""The T02 built-in command definitions and their small Application handlers."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from uthcode.core.permission import PermissionMode
from uthcode.core.planning import BehaviorMode

from .dispatcher import CommandContext, CommandExecutionError
from .models import (
    ArgumentSpec,
    BehaviorModeSelected,
    ClearTranscript,
    CommandAvailability,
    CommandDefinition,
    CommandKind,
    ModelSelected,
    OpenPermissionPicker,
    OpenModelPicker,
    PermissionModeSelected,
    QuitInterface,
)
from .registry import CommandRegistry


_MODEL_SWITCH_FAILURE = "模型切换失败"
_FULL_ACCESS_WARNING = (
    "高风险提示：full_access 仅跳过普通 Policy/Strategy，Guard 仍然生效；"
    "当前 Run 的普通 Tool 将减少人工确认。"
)


def _help_text(context: CommandContext) -> str:
    invocation = context.invocation
    if invocation.args:
        definition = context.registry.resolve(invocation.args[0])
        if definition is None:
            return f"未知命令：/{invocation.args[0].lower()}"
        return _format_definition(definition)

    return "\n".join(
        _format_definition(definition)
        for definition in context.registry.list_commands(include_hidden=False)
    )


def _format_definition(definition: CommandDefinition) -> str:
    aliases = ""
    if definition.aliases:
        aliases = "；别名：" + ", ".join(f"/{alias}" for alias in definition.aliases)
    state = "已实现" if definition.implemented else "未实现"
    return f"{definition.usage_text} — {definition.description} [{state}]{aliases}"


def _clear(_context: CommandContext) -> ClearTranscript:
    return ClearTranscript()


def _model_candidates(application: object | None) -> Iterable[str]:
    if application is None:
        return ()
    catalog = getattr(application, "model_catalog", None)
    if not callable(catalog):
        return ()
    return tuple(
        str(getattr(model, "model_ref", model))
        for model in catalog()
    )


def _model(context: CommandContext) -> OpenModelPicker | ModelSelected:
    application = context.application
    if not context.invocation.args:
        return OpenModelPicker()
    if application is None:
        raise CommandExecutionError("/model 需要 Application 模型目录")

    model_ref = context.invocation.args[0]
    catalog = getattr(application, "model_catalog", None)
    available = () if not callable(catalog) else tuple(
        str(getattr(model, "model_ref", model)) for model in catalog()
    )
    if model_ref not in available:
        choices = ", ".join(available) if available else "无"
        raise CommandExecutionError(
            f"未知模型：{model_ref}；可用模型：{choices}"
        )

    select_model = getattr(application, "select_model", None)
    if not callable(select_model):
        raise CommandExecutionError("Application 不支持模型切换")
    try:
        select_model(model_ref)
    except Exception:
        raise CommandExecutionError(_MODEL_SWITCH_FAILURE) from None
    return ModelSelected(model_ref)


def _permission(context: CommandContext) -> OpenPermissionPicker | PermissionModeSelected:
    if not context.invocation.args:
        return OpenPermissionPicker()
    try:
        mode = PermissionMode(context.invocation.args[0])
    except (TypeError, ValueError):
        raise CommandExecutionError(
            "未知权限模式；可选：default、auto、full_access"
        ) from None

    setter = getattr(context.application, "set_permission_mode", None)
    if callable(setter):
        try:
            setter(mode)
        except Exception:
            raise CommandExecutionError("当前 Application 不支持权限模式切换") from None
    return PermissionModeSelected(
        mode,
        warning=_FULL_ACCESS_WARNING if mode is PermissionMode.FULL_ACCESS else None,
    )


def _select_behavior_mode(
    mode: BehaviorMode,
) -> Callable[[CommandContext], BehaviorModeSelected]:
    def _handler(_context: CommandContext) -> BehaviorModeSelected:
        return BehaviorModeSelected(mode)

    return _handler


def _status(context: CommandContext) -> str:
    application = context.application
    if application is None:
        raise CommandExecutionError("/status 需要 Application")
    status_method = getattr(application, "status", None)
    if not callable(status_method):
        raise CommandExecutionError("Application 不支持状态查询")
    status = status_method()
    identity = getattr(status, "provider_identity", None)
    provider_name = getattr(identity, "provider", "unknown")
    provider_model = getattr(identity, "model", "unknown")
    sources = getattr(status, "configuration_sources", ())
    source_text = ", ".join(
        str(getattr(source, "path", None) or getattr(source, "kind", "unknown"))
        for source in sources
    ) or "none"
    return "\n".join(
        (
            f"model: {getattr(status, 'current_model', 'unknown')}",
            f"provider: {getattr(status, 'provider_profile', 'unknown')} ({provider_name})",
            f"remote model: {provider_model}",
            f"config sources: {source_text}",
            f"state: {getattr(status, 'state', 'unknown')}",
        )
    )


def create_builtin_registry() -> CommandRegistry:
    """Create the one T02 built-in command registry from one definition source."""

    registry = CommandRegistry()
    definitions = (
        CommandDefinition(
            canonical="help",
            aliases=("h", "?"),
            description="显示命令帮助",
            kind=CommandKind.LOCAL,
            arguments=(ArgumentSpec("command", required=False),),
            handler=_help_text,
        ),
        CommandDefinition(
            canonical="clear",
            description="清空当前界面 Transcript",
            kind=CommandKind.LOCAL_UI,
            handler=_clear,
        ),
        CommandDefinition(
            canonical="model",
            aliases=("models", "m"),
            description="查看或切换当前模型",
            kind=CommandKind.LOCAL_UI,
            arguments=(
                ArgumentSpec(
                    "model-ref",
                    required=False,
                    description="Model Ref",
                    dynamic_candidates=_model_candidates,
                ),
            ),
            handler=_model,
        ),
        CommandDefinition(
            canonical="permission",
            description="查看或切换当前 Run 权限模式",
            kind=CommandKind.LOCAL_UI,
            arguments=(
                ArgumentSpec(
                    "mode",
                    required=False,
                    description="Permission mode",
                    choices=tuple(mode.value for mode in PermissionMode),
                ),
            ),
            handler=_permission,
        ),
        CommandDefinition(
            canonical="status",
            aliases=("s",),
            description="显示当前 Application 状态",
            kind=CommandKind.LOCAL,
            handler=_status,
        ),
        CommandDefinition(
            canonical="quit",
            aliases=("q", "exit"),
            description="退出当前 Interface",
            kind=CommandKind.LOCAL_UI,
            handler=lambda _context: QuitInterface(),
        ),
        CommandDefinition(
            canonical="config",
            description="查看或编辑配置",
            kind=CommandKind.LOCAL,
            availability=CommandAvailability.NOT_IMPLEMENTED,
        ),
        CommandDefinition(
            canonical="compact",
            aliases=("c",),
            description="压缩上下文",
            kind=CommandKind.LOCAL,
            availability=CommandAvailability.NOT_IMPLEMENTED,
        ),
        CommandDefinition(
            canonical="plan",
            description="进入规划模式",
            kind=CommandKind.LOCAL_UI,
            handler=_select_behavior_mode(BehaviorMode.PLAN),
        ),
        CommandDefinition(
            canonical="new",
            description="创建新会话",
            kind=CommandKind.LOCAL,
            availability=CommandAvailability.NOT_IMPLEMENTED,
        ),
        CommandDefinition(
            canonical="resume",
            description="恢复会话",
            kind=CommandKind.LOCAL_UI,
            availability=CommandAvailability.NOT_IMPLEMENTED,
        ),
        CommandDefinition(
            canonical="login",
            description="登录 Provider",
            kind=CommandKind.LOCAL,
            availability=CommandAvailability.NOT_IMPLEMENTED,
        ),
        CommandDefinition(
            canonical="memory",
            description="管理记忆",
            kind=CommandKind.LOCAL,
            availability=CommandAvailability.NOT_IMPLEMENTED,
        ),
        CommandDefinition(
            canonical="dream",
            description="执行 Dream Prompt",
            kind=CommandKind.PROMPT,
            availability=CommandAvailability.NOT_IMPLEMENTED,
        ),
        CommandDefinition(
            canonical="do",
            aliases=("build",),
            description="进入默认执行模式",
            kind=CommandKind.LOCAL_UI,
            handler=_select_behavior_mode(BehaviorMode.DEFAULT),
        ),
        CommandDefinition(
            canonical="review",
            description="执行 Review Prompt",
            kind=CommandKind.PROMPT,
            availability=CommandAvailability.NOT_IMPLEMENTED,
        ),
    )
    for definition in definitions:
        registry.register(definition)
    return registry


__all__ = ["create_builtin_registry"]
