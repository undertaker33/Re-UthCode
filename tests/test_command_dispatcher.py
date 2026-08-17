from __future__ import annotations

import pytest

from uthcode.application import (
    BehaviorMode,
    BehaviorModeSelected,
    ClearTranscript,
    CommandDefinition,
    CommandDispatcher,
    CommandKind,
    CommandRegistry,
    EffectiveConfig,
    ModelSelected,
    OpenPermissionPicker,
    OpenModelPicker,
    OutcomeStatus,
    PermissionMode,
    PermissionModeSelected,
    ProviderKind,
    ProviderProfile,
    QuitInterface,
    UthCodeApplication,
    create_application,
    create_builtin_registry,
)
from uthcode.core.provider import (
    FinishReason,
    GenerationCompleted,
    Message,
    ProviderIdentity,
    ProviderResponse,
    TextPart,
    Usage,
)
from uthcode.integrations.providers.fake import FakeProvider


def _completed() -> GenerationCompleted:
    return GenerationCompleted(
        ProviderResponse(
            message=Message("assistant", (TextPart("done"),)),
            usage=Usage(),
            finish_reason=FinishReason.STOP,
        )
    )


def _application() -> tuple[UthCodeApplication, list[str]]:
    config = EffectiveConfig(
        model="one/ref",
        providers={"local": ProviderProfile("local", ProviderKind.FAKE)},
        models={
            "one/ref": {"provider_profile_id": "local", "remote_model_id": "one"},
            "two/ref": {"provider_profile_id": "local", "remote_model_id": "two"},
        },
    )
    writes: list[str] = []

    def builder(provider, model):  # type: ignore[no-untyped-def]
        return FakeProvider(
            identity=ProviderIdentity(provider.provider_profile_id, "fake", model.remote_model_id),
            events=(_completed(),),
        )

    return create_application(
        config,
        provider_builder=builder,
        model_writer=writes.append,
    ), writes


def test_dispatcher_produces_distinct_local_ui_and_prompt_results() -> None:
    registry = CommandRegistry()
    registry.register(
        CommandDefinition(
            canonical="local",
            description="local",
            kind=CommandKind.LOCAL,
            handler=lambda _context: "local output",
        )
    )
    registry.register(
        CommandDefinition(
            canonical="ui",
            description="ui",
            kind=CommandKind.LOCAL_UI,
            handler=lambda _context: ClearTranscript(),
        )
    )
    registry.register(
        CommandDefinition(
            canonical="prompt",
            description="prompt",
            kind=CommandKind.PROMPT,
        )
    )
    dispatcher = CommandDispatcher(registry)

    local = dispatcher.dispatch_text("/local")
    ui = dispatcher.dispatch_text("/ui")
    prompt = dispatcher.dispatch_text("/prompt keep this query")

    assert local is not None and local.status is OutcomeStatus.SUCCESS
    assert local.output == "local output"
    assert local.ui_action is None and local.prompt is None
    assert ui is not None and isinstance(ui.ui_action, ClearTranscript)
    assert ui.output is None and ui.prompt is None
    assert prompt is not None and prompt.prompt == "keep this query"
    assert prompt.output is None and prompt.ui_action is None


def test_plain_text_and_bare_slash_never_enter_dispatch() -> None:
    registry = CommandRegistry()
    registry.register(
        CommandDefinition(
            canonical="local",
            description="local",
            kind=CommandKind.LOCAL,
            handler=lambda _context: "output",
        )
    )
    dispatcher = CommandDispatcher(registry)

    assert dispatcher.dispatch_text("ordinary text") is None
    assert dispatcher.dispatch_text("/") is None


def test_unknown_usage_and_execution_errors_are_structured() -> None:
    registry = CommandRegistry()
    registry.register(
        CommandDefinition(
            canonical="one",
            description="one",
            kind=CommandKind.LOCAL,
            arguments=(),
            handler=lambda _context: (_ for _ in ()).throw(RuntimeError("boom")),
        )
    )
    dispatcher = CommandDispatcher(registry)

    unknown = dispatcher.dispatch_text("/missing")
    usage = dispatcher.dispatch_text("/one extra")
    execution = dispatcher.dispatch_text("/one")

    assert unknown is not None and unknown.status is OutcomeStatus.UNKNOWN_COMMAND
    assert usage is not None and usage.status is OutcomeStatus.USAGE_ERROR
    assert execution is not None and execution.status is OutcomeStatus.EXECUTION_ERROR
    assert execution.error == "命令执行失败"
    assert "boom" not in repr(execution)


def test_unknown_handler_exception_is_redacted_from_outcome_and_repr() -> None:
    secret = "sk-handler-secret-value"
    registry = CommandRegistry()

    def leaking_handler(_context):  # type: ignore[no-untyped-def]
        raise RuntimeError(f"provider failed with {secret}")

    registry.register(
        CommandDefinition(
            canonical="leak",
            description="leak",
            kind=CommandKind.LOCAL,
            handler=leaking_handler,
        )
    )

    outcome = CommandDispatcher(registry).dispatch_text("/leak")

    assert outcome is not None
    assert outcome.status is OutcomeStatus.EXECUTION_ERROR
    assert outcome.error == "命令执行失败"
    assert secret not in outcome.error
    assert secret not in repr(outcome.error)
    assert secret not in repr(outcome)


def test_builtin_registry_contains_one_model_canonical_and_real_ui_actions() -> None:
    registry = create_builtin_registry()
    dispatcher = CommandDispatcher(registry)

    clear = dispatcher.dispatch_text("/clear")
    picker = dispatcher.dispatch_text("/model")
    quit_outcome = dispatcher.dispatch_text("/quit")

    assert clear is not None and isinstance(clear.ui_action, ClearTranscript)
    assert picker is not None and isinstance(picker.ui_action, OpenModelPicker)
    assert quit_outcome is not None and isinstance(quit_outcome.ui_action, QuitInterface)
    assert registry.resolve("models") is registry.resolve("model")
    assert registry.resolve("m") is registry.resolve("model")
    assert all(command.canonical != "models" for command in registry.list_commands())


def test_permission_command_uses_the_same_registry_and_returns_session_action() -> None:
    registry = create_builtin_registry()
    dispatcher = CommandDispatcher(registry)

    picker = dispatcher.dispatch_text("/permission")
    assert picker is not None and isinstance(picker.ui_action, OpenPermissionPicker)

    selected = dispatcher.dispatch_text("/permission full_access")
    assert selected is not None and isinstance(selected.ui_action, PermissionModeSelected)
    assert selected.ui_action.mode is PermissionMode.FULL_ACCESS
    assert selected.ui_action.warning is not None

    assert registry.resolve("permission") is not None


def test_permission_command_persists_safe_default_before_returning_run_action() -> None:
    application, _writes = _application()
    persisted: list[PermissionMode] = []
    application._permission_writer = persisted.append
    dispatcher = CommandDispatcher(create_builtin_registry(), application)

    selected = dispatcher.dispatch_text("/permission auto")

    assert selected is not None and selected.ui_action == PermissionModeSelected(PermissionMode.AUTO)
    assert persisted == [PermissionMode.AUTO]
    assert application.default_permission_mode is PermissionMode.AUTO
    assert application.create_run().permission_mode is PermissionMode.AUTO


def test_permission_command_write_failure_leaves_application_default_unchanged() -> None:
    application, _writes = _application()
    application._permission_writer = lambda _mode: (_ for _ in ()).throw(OSError("no"))
    dispatcher = CommandDispatcher(create_builtin_registry(), application)

    outcome = dispatcher.dispatch_text("/permission auto")

    assert outcome is not None and outcome.status is OutcomeStatus.EXECUTION_ERROR
    assert application.default_permission_mode is PermissionMode.DEFAULT
    assert application.create_run().permission_mode is PermissionMode.DEFAULT


def test_behavior_mode_commands_return_interface_neutral_actions_and_build_is_alias() -> None:
    registry = create_builtin_registry()
    dispatcher = CommandDispatcher(registry)

    plan = dispatcher.dispatch_text("/plan")
    execute = dispatcher.dispatch_text("/do")
    build = dispatcher.dispatch_text("/build")

    assert plan is not None and plan.status is OutcomeStatus.SUCCESS
    assert plan.ui_action == BehaviorModeSelected(BehaviorMode.PLAN)
    assert execute is not None and execute.ui_action == BehaviorModeSelected(
        BehaviorMode.DEFAULT
    )
    assert build is not None and build.ui_action == BehaviorModeSelected(
        BehaviorMode.DEFAULT
    )
    assert build.invocation is not None
    assert build.invocation.canonical == "do"
    assert build.invocation.alias == "build"
    assert plan.prompt is None and execute.prompt is None and build.prompt is None


@pytest.mark.parametrize("text", ["/plan extra", "/do extra", "/build extra"])
def test_behavior_mode_commands_reject_arguments_without_producing_prompt(
    text: str,
) -> None:
    outcome = CommandDispatcher(create_builtin_registry()).dispatch_text(text)

    assert outcome is not None
    assert outcome.status is OutcomeStatus.USAGE_ERROR
    assert outcome.prompt is None


@pytest.mark.parametrize(
    "canonical",
    [
        "config",
        "login",
        "memory",
        "dream",
        "review",
    ],
)
def test_unimplemented_builtin_commands_have_one_uniform_outcome(canonical: str) -> None:
    registry = create_builtin_registry()
    dispatcher = CommandDispatcher(registry)

    outcome = dispatcher.dispatch_text(f"/{canonical}")

    assert outcome is not None
    assert outcome.status is OutcomeStatus.NOT_IMPLEMENTED
    assert outcome.output == f"功能未实现：/{canonical}"


def test_help_is_generated_from_the_same_registry_for_total_and_single_help() -> None:
    registry = create_builtin_registry()
    registry.register(
        CommandDefinition(
            canonical="custom",
            description="custom description",
            kind=CommandKind.LOCAL,
        )
    )
    dispatcher = CommandDispatcher(registry)

    total = dispatcher.dispatch_text("/help")
    single = dispatcher.dispatch_text("/help custom")

    assert total is not None and total.output is not None
    assert "/custom" in total.output
    assert single is not None and single.output is not None
    assert "/custom" in single.output
    assert "custom description" in single.output


def test_builtin_help_reports_final_behavior_commands_and_only_build_alias() -> None:
    dispatcher = CommandDispatcher(create_builtin_registry())

    total = dispatcher.dispatch_text("/help")
    plan = dispatcher.dispatch_text("/help plan")
    execute = dispatcher.dispatch_text("/help do")

    assert total is not None and total.output is not None
    assert plan is not None and plan.output is not None
    assert execute is not None and execute.output is not None
    assert "/plan — 进入规划模式 [已实现]" in total.output
    assert "/do — 进入默认执行模式 [已实现]；别名：/build" in total.output
    assert "别名：/p" not in total.output
    assert "[未实现]" not in plan.output
    assert "[未实现]" not in execute.output


def test_model_command_switches_application_and_returns_structured_action() -> None:
    application, writes = _application()
    dispatcher = CommandDispatcher(create_builtin_registry(), application)

    outcome = dispatcher.dispatch_text("/model two/ref")

    assert outcome is not None and outcome.status is OutcomeStatus.SUCCESS
    assert outcome.ui_action == ModelSelected("two/ref")
    assert application.current_model_ref == "two/ref"
    assert writes == ["two/ref"]


def test_model_switch_exception_is_redacted_from_outcome_and_repr() -> None:
    secret = "sk-secret-value"

    class SecretFailingApplication:
        def model_catalog(self):  # type: ignore[no-untyped-def]
            return (type("Model", (), {"model_ref": "safe/ref"})(),)

        def select_model(self, _model_ref):  # type: ignore[no-untyped-def]
            raise RuntimeError(f"provider URL contains {secret}")

    outcome = CommandDispatcher(
        create_builtin_registry(),
        SecretFailingApplication(),
    ).dispatch_text("/model safe/ref")

    assert outcome is not None
    assert outcome.status is OutcomeStatus.EXECUTION_ERROR
    assert outcome.error == "模型切换失败"
    assert secret not in outcome.error
    assert secret not in repr(outcome.error)
    assert secret not in repr(outcome)


def test_status_reports_safe_application_values() -> None:
    application, _writes = _application()
    dispatcher = CommandDispatcher(create_builtin_registry(), application)

    outcome = dispatcher.dispatch_text("/status")

    assert outcome is not None and outcome.output is not None
    assert outcome.status is OutcomeStatus.SUCCESS
    assert "one/ref" in outcome.output
    assert "local" in outcome.output
