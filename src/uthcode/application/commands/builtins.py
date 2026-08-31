"""The T02 built-in command definitions and their small Application handlers."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Iterable, Mapping

from uthcode.core.permission import PermissionMode
from uthcode.core.planning import BehaviorMode

from .dispatcher import CommandContext, CommandExecutionError
from .models import (
    ArgumentSpec,
    BehaviorModeSelected,
    ClearTranscript,
    CommandDefinition,
    CommandKind,
    ModelSelected,
    OpenPermissionPicker,
    OpenModelPicker,
    OpenSessionPicker,
    PermissionModeSelected,
    QuitInterface,
    SessionChanged,
)
from .registry import CommandRegistry
from ..sessions import SessionOperationError


_MODEL_SWITCH_FAILURE = "模型切换失败"
_FULL_ACCESS_WARNING = (
    "高风险提示：full_access 跳过内置普通 Guard、Policy 和 Strategy；"
    "显式 Guard 与灾难性断路器仍然生效；"
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
    return f"{definition.usage_text} — {definition.description}{aliases}"


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


async def _model(context: CommandContext) -> OpenModelPicker | ModelSelected:
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

    select_model = getattr(application, "select_model_async", None)
    if not callable(select_model):
        select_model = getattr(application, "select_model", None)
    if not callable(select_model):
        raise CommandExecutionError("Application 不支持模型切换")
    try:
        result = select_model(model_ref)
        if inspect.isawaitable(result):
            await result
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

    setter = getattr(context.application, "set_default_permission_mode", None)
    if mode is not PermissionMode.FULL_ACCESS and callable(setter):
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
    usage = getattr(status, "context_usage", None)
    available = bool(getattr(usage, "available", False))
    used = getattr(usage, "used_tokens", None)
    budget = getattr(usage, "budget_tokens", None)
    budget_label = (
        f"{budget // 1000}K" if isinstance(budget, int) and budget >= 1000 else
        str(budget) if isinstance(budget, int) else "?"
    )
    usage_text = (
        f"{used}/{budget_label}"
        if available and isinstance(used, int) and isinstance(budget, int)
        else f"unavailable/{budget_label}"
    )
    if available and isinstance(used, int) and isinstance(budget, int) and budget > 0:
        filled = min(12, max(0, int(round((used / budget) * 12))))
        usage_bar = "█" * filled + "░" * (12 - filled)
        usage_line = f"context: [{usage_bar}] {usage_text}"
    else:
        usage_line = f"context: {usage_text}"
    prefix = getattr(status, "stable_prefix_fingerprint", None) or "unavailable"
    prefix_reason = getattr(status, "prefix_change_reason", None) or "unavailable"
    cache_text = (
        f"prefix={prefix}; changed={getattr(status, 'prefix_changed', None)}; "
        f"reason={prefix_reason}; tool_schema="
        f"{getattr(status, 'tool_schema_fingerprint', None) or 'unavailable'}"
    )
    diagnostics = getattr(status, "diagnostics", {})
    if not isinstance(diagnostics, Mapping):
        diagnostics = {}
    context_budget = diagnostics.get("context_budget")
    if not isinstance(context_budget, Mapping):
        context_budget = {}
    context_gate = diagnostics.get("context_gate")
    if not isinstance(context_gate, Mapping):
        context_gate = {}
    context_pressure = diagnostics.get("context_pressure")
    if not isinstance(context_pressure, Mapping):
        context_pressure = {}
    limits_text = (
        "configured={configured}; provider_input={provider_input}; default={default}; "
        "effective={effective}; source={source}; observed={observed}; "
        "tightened={tightened}; provider_output={provider_output}; combined={combined}"
    ).format(
        configured=context_budget.get("configured_input_limit", "?"),
        provider_input=context_budget.get("provider_max_input", "?"),
        default=context_budget.get("default_input_limit", "?"),
        effective=context_budget.get("effective_input_limit", "?"),
        source=context_budget.get("effective_input_source", "?"),
        observed=context_budget.get("observed_input_sources", "?"),
        tightened=context_budget.get("tightened_input_sources", "?"),
        provider_output=context_budget.get("provider_max_output", "?"),
        combined=context_budget.get("provider_combined_limit", "?"),
    )
    gate_text = (
        f"hard_safe={context_gate.get('hard_safe', '?')}; "
        f"auto_pressure={context_gate.get('auto_pressure', '?')}; "
        f"count_source={context_gate.get('count_source', '?')}; "
        f"reason={context_gate.get('reason', '?')}"
    )
    pressure_text = (
        f"input={context_pressure.get('input_tokens', '?')}; "
        f"source={context_pressure.get('source', '?')}"
    )
    compaction = diagnostics.get("compaction")
    last_compaction = (
        compaction.get("last")
        if isinstance(compaction, Mapping)
        and isinstance(compaction.get("last"), Mapping)
        else {}
    )
    outcome_text = (
        f"status={last_compaction.get('status', '?')}; "
        f"changed={last_compaction.get('changed', '?')}; "
        f"failure={last_compaction.get('failure', '?')}"
    )
    return "\n".join(
        (
            f"model: {getattr(status, 'current_model', 'unknown')}",
            f"provider: {getattr(status, 'provider_profile', 'unknown')} ({provider_name})",
            f"remote model: {provider_model}",
            f"config sources: {source_text}",
            f"state: {getattr(status, 'state', 'unknown')}",
            f"{usage_line} dynamic input operating limit",
            f"Timeline checkpoint: {getattr(status, 'timeline_checkpoint_id', None)}",
            f"instruction epoch: {getattr(status, 'instruction_epoch', 0)}",
            f"compact count: {getattr(status, 'compact_count', 0)}",
            f"context limits: {limits_text}",
            f"context gate: {gate_text}",
            f"context pressure: {pressure_text}",
            f"context outcome: {outcome_text}",
            f"cache diagnostics: {cache_text}",
        )
    )


def _session_error(
    exc: SessionOperationError,
    *,
    session_id: str | None = None,
) -> CommandExecutionError:
    if exc.kind == "busy":
        return CommandExecutionError("Session busy; close the other writer and retry")
    if exc.kind == "corrupt":
        return CommandExecutionError("Session corrupt; resume stopped for safety")
    if exc.kind == "unknown":
        value = session_id or exc.session_id or "requested"
        return CommandExecutionError(f"unknown Session: {value}")
    return CommandExecutionError("Session storage error")


async def _compact(context: CommandContext) -> str:
    application = context.application
    compact = getattr(application, "compact_session", None)
    if not callable(compact):
        raise CommandExecutionError("/compact 需要 Application Session")
    try:
        result = compact()
        if inspect.isawaitable(result):
            result = await result
    except SessionOperationError as exc:
        raise _session_error(exc) from None
    except Exception:
        raise CommandExecutionError("上下文压缩失败") from None
    if not bool(getattr(result, "changed", False)):
        failure = getattr(result, "failure", None)
        if failure is None:
            return "上下文无需压缩；Transcript 未改写；Timeline 未变化"
        raise CommandExecutionError(f"上下文压缩失败：{failure}")
    timeline = getattr(result, "timeline", None)
    checkpoint = getattr(timeline, "active_checkpoint", None)
    checkpoint_id = getattr(checkpoint, "turn_id", None)
    return (
        "上下文已压缩；Transcript 未改写；"
        f"Timeline checkpoint: {checkpoint_id if checkpoint_id is not None else 'unknown'}"
    )


async def _new_session(context: CommandContext) -> SessionChanged:
    application = context.application
    create = getattr(application, "new_session_for_command_async", None)
    if not callable(create):
        create = getattr(application, "new_session_for_command", None)
    if not callable(create):
        raise CommandExecutionError("/new 需要 Application Session")
    try:
        session = create()
        if inspect.isawaitable(session):
            session = await session
    except SessionOperationError as exc:
        raise _session_error(exc) from None
    except Exception:
        raise CommandExecutionError("无法创建新 Session") from None
    return SessionChanged(str(session.session_id), restored=False)


async def _resume_session(context: CommandContext) -> OpenSessionPicker | SessionChanged:
    application = context.application
    session_id = context.invocation.args[0] if context.invocation.args else None
    if session_id is None:
        return OpenSessionPicker()
    resume = getattr(application, "resume_session_for_command_async", None)
    if not callable(resume):
        resume = getattr(application, "resume_session_for_command", None)
    if not callable(resume):
        raise CommandExecutionError("/resume 需要 Application Session")
    try:
        session = resume(session_id)
        if inspect.isawaitable(session):
            session = await session
    except SessionOperationError as exc:
        raise _session_error(exc, session_id=session_id) from None
    except Exception:
        raise CommandExecutionError("无法恢复 Session") from None
    replay = getattr(session, "replay", ())
    return SessionChanged(
        str(session.session_id),
        restored=True,
        replay=tuple(replay),
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
            canonical="compact",
            aliases=("c",),
            description="压缩上下文",
            kind=CommandKind.LOCAL,
            handler=_compact,
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
            kind=CommandKind.LOCAL_UI,
            handler=_new_session,
        ),
        CommandDefinition(
            canonical="resume",
            description="恢复会话",
            kind=CommandKind.LOCAL_UI,
            arguments=(ArgumentSpec("session-id", required=False),),
            handler=_resume_session,
        ),
        CommandDefinition(
            canonical="do",
            aliases=("build",),
            description="进入默认执行模式",
            kind=CommandKind.LOCAL_UI,
            handler=_select_behavior_mode(BehaviorMode.DEFAULT),
        ),
    )
    for definition in definitions:
        registry.register(definition)
    return registry


__all__ = ["create_builtin_registry"]
