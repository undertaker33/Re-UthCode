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
    CompletionEngine,
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
    ModelLimits,
    ProviderIdentity,
    ProviderResponse,
    TextPart,
    Usage,
)
from uthcode.integrations.providers.fake import FakeProvider


TEST_LIMITS = ModelLimits(max_input_tokens=1_000_000, source="test.fake")


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
        default_model="one/ref",
        providers={"local": ProviderProfile("local", ProviderKind.FAKE)},
        models={
            "one/ref": {"provider_profile_id": "local", "remote_id": "one"},
            "two/ref": {"provider_profile_id": "local", "remote_id": "two"},
        },
    )
    writes: list[str] = []

    def builder(provider, model):  # type: ignore[no-untyped-def]
        return FakeProvider(
            identity=ProviderIdentity(provider.provider_profile_id, "fake", model.remote_id),
            events=(_completed(),),
            model_limits=TEST_LIMITS,
        )

    return create_application(
        config,
        provider_builder=builder,
        model_writer=writes.append,
    ), writes


@pytest.mark.asyncio
async def test_dispatcher_produces_distinct_local_and_ui_results() -> None:
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
    dispatcher = CommandDispatcher(registry)

    local = await dispatcher.dispatch_text_async("/local")
    ui = await dispatcher.dispatch_text_async("/ui")

    assert local is not None and local.status is OutcomeStatus.SUCCESS
    assert local.output == "local output"
    assert local.ui_action is None
    assert not hasattr(local, "prompt")
    assert ui is not None and isinstance(ui.ui_action, ClearTranscript)
    assert ui.output is None


@pytest.mark.asyncio
async def test_async_dispatch_awaits_handlers() -> None:
    async def handler(_context: object) -> str:
        return "awaited"

    registry = CommandRegistry()
    registry.register(
        CommandDefinition(
            canonical="async",
            description="async",
            kind=CommandKind.LOCAL,
            handler=handler,
        )
    )

    outcome = await CommandDispatcher(registry).dispatch_text_async("/async")

    assert outcome is not None
    assert outcome.status is OutcomeStatus.SUCCESS
    assert outcome.output == "awaited"


@pytest.mark.asyncio
async def test_plain_text_and_bare_slash_never_enter_dispatch() -> None:
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

    assert await dispatcher.dispatch_text_async("ordinary text") is None
    assert await dispatcher.dispatch_text_async("/") is None


@pytest.mark.asyncio
async def test_unknown_usage_and_execution_errors_are_structured() -> None:
    registry = CommandRegistry()
    registry.register(
        CommandDefinition(
            canonical="one",
            description="one",
            kind=CommandKind.LOCAL,
            handler=lambda _context: (_ for _ in ()).throw(RuntimeError("boom")),
        )
    )
    dispatcher = CommandDispatcher(registry)

    unknown = await dispatcher.dispatch_text_async("/missing")
    usage = await dispatcher.dispatch_text_async("/one extra")
    execution = await dispatcher.dispatch_text_async("/one")

    assert unknown is not None and unknown.status is OutcomeStatus.UNKNOWN_COMMAND
    assert usage is not None and usage.status is OutcomeStatus.USAGE_ERROR
    assert execution is not None and execution.status is OutcomeStatus.EXECUTION_ERROR
    assert execution.error == "命令执行失败"
    assert "boom" not in repr(execution)


@pytest.mark.asyncio
async def test_unknown_handler_exception_is_redacted_from_outcome_and_repr() -> None:
    secret = "sk-handler-secret-value"
    registry = CommandRegistry()

    def leaking_handler(_context: object) -> str:
        raise RuntimeError(f"provider failed with {secret}")

    registry.register(
        CommandDefinition(
            canonical="leak",
            description="leak",
            kind=CommandKind.LOCAL,
            handler=leaking_handler,
        )
    )

    outcome = await CommandDispatcher(registry).dispatch_text_async("/leak")

    assert outcome is not None
    assert outcome.status is OutcomeStatus.EXECUTION_ERROR
    assert outcome.error == "命令执行失败"
    assert secret not in outcome.error
    assert secret not in repr(outcome.error)
    assert secret not in repr(outcome)


@pytest.mark.asyncio
async def test_builtin_registry_contains_one_model_canonical_and_real_ui_actions() -> None:
    registry = create_builtin_registry()
    dispatcher = CommandDispatcher(registry)

    clear = await dispatcher.dispatch_text_async("/clear")
    picker = await dispatcher.dispatch_text_async("/model")
    quit_outcome = await dispatcher.dispatch_text_async("/quit")

    assert clear is not None and isinstance(clear.ui_action, ClearTranscript)
    assert picker is not None and isinstance(picker.ui_action, OpenModelPicker)
    assert quit_outcome is not None and isinstance(quit_outcome.ui_action, QuitInterface)
    assert registry.resolve("models") is registry.resolve("model")
    assert registry.resolve("m") is registry.resolve("model")
    assert all(command.canonical != "models" for command in registry.list_commands())


@pytest.mark.asyncio
async def test_permission_command_uses_the_same_registry_and_returns_run_action() -> None:
    registry = create_builtin_registry()
    dispatcher = CommandDispatcher(registry)

    picker = await dispatcher.dispatch_text_async("/permission")
    selected = await dispatcher.dispatch_text_async("/permission full_access")

    assert picker is not None and isinstance(picker.ui_action, OpenPermissionPicker)
    assert selected is not None and isinstance(selected.ui_action, PermissionModeSelected)
    assert selected.ui_action.mode is PermissionMode.FULL_ACCESS
    assert selected.ui_action.warning is not None
    assert registry.resolve("permission") is not None


@pytest.mark.asyncio
async def test_permission_command_persists_safe_default_and_keeps_failure_atomic() -> None:
    application, _writes = _application()
    persisted: list[PermissionMode] = []
    application._permission_writer = persisted.append
    dispatcher = CommandDispatcher(create_builtin_registry(), application)

    selected = await dispatcher.dispatch_text_async("/permission auto")

    assert selected is not None and selected.ui_action == PermissionModeSelected(PermissionMode.AUTO)
    assert persisted == [PermissionMode.AUTO]
    assert application.default_permission_mode is PermissionMode.AUTO
    assert application.create_run().permission_mode is PermissionMode.AUTO

    application._permission_writer = lambda _mode: (_ for _ in ()).throw(OSError("no"))
    failed = await dispatcher.dispatch_text_async("/permission default")
    assert failed is not None and failed.status is OutcomeStatus.EXECUTION_ERROR
    assert application.default_permission_mode is PermissionMode.AUTO


@pytest.mark.asyncio
async def test_behavior_mode_commands_return_actions_and_reject_extra_arguments() -> None:
    dispatcher = CommandDispatcher(create_builtin_registry())

    plan = await dispatcher.dispatch_text_async("/plan")
    execute = await dispatcher.dispatch_text_async("/do")
    build = await dispatcher.dispatch_text_async("/build")
    rejected = await dispatcher.dispatch_text_async("/plan extra")

    assert plan is not None and plan.ui_action == BehaviorModeSelected(BehaviorMode.PLAN)
    assert execute is not None and execute.ui_action == BehaviorModeSelected(BehaviorMode.DEFAULT)
    assert build is not None and build.ui_action == BehaviorModeSelected(BehaviorMode.DEFAULT)
    assert build.invocation is not None and build.invocation.canonical == "do"
    assert build.invocation.alias == "build"
    assert rejected is not None and rejected.status is OutcomeStatus.USAGE_ERROR


@pytest.mark.asyncio
async def test_removed_builtins_are_unknown_and_absent_from_help_and_completion() -> None:
    registry = create_builtin_registry()
    dispatcher = CommandDispatcher(registry)

    for canonical in ("config", "login", "memory", "dream", "review"):
        outcome = await dispatcher.dispatch_text_async(f"/{canonical}")
        assert outcome is not None and outcome.status is OutcomeStatus.UNKNOWN_COMMAND

    help_outcome = await dispatcher.dispatch_text_async("/help")
    assert help_outcome is not None and help_outcome.output is not None
    candidates = CompletionEngine(registry).complete("/")
    for canonical in ("config", "login", "memory", "dream", "review"):
        assert f"/{canonical}" not in help_outcome.output
        assert canonical not in {candidate.canonical for candidate in candidates}


@pytest.mark.asyncio
async def test_help_is_generated_from_the_same_registry_for_total_and_single_help() -> None:
    registry = create_builtin_registry()
    registry.register(
        CommandDefinition(
            canonical="custom",
            description="custom description",
            kind=CommandKind.LOCAL,
            handler=lambda _context: "custom",
        )
    )
    dispatcher = CommandDispatcher(registry)

    total = await dispatcher.dispatch_text_async("/help")
    single = await dispatcher.dispatch_text_async("/help custom")

    assert total is not None and total.output is not None
    assert "/custom" in total.output
    assert single is not None and single.output is not None
    assert "/custom" in single.output
    assert "custom description" in single.output
    assert "[已实现]" not in total.output


@pytest.mark.asyncio
async def test_builtin_help_reports_final_behavior_commands_and_only_build_alias() -> None:
    dispatcher = CommandDispatcher(create_builtin_registry())

    total = await dispatcher.dispatch_text_async("/help")
    plan = await dispatcher.dispatch_text_async("/help plan")
    execute = await dispatcher.dispatch_text_async("/help do")

    assert total is not None and total.output is not None
    assert plan is not None and plan.output is not None
    assert execute is not None and execute.output is not None
    assert "/plan — 进入规划模式" in total.output
    assert "/do — 进入默认执行模式；别名：/build" in total.output
    assert "别名：/p" not in total.output


@pytest.mark.asyncio
async def test_model_command_switches_application_and_returns_structured_action() -> None:
    application, writes = _application()
    dispatcher = CommandDispatcher(create_builtin_registry(), application)

    outcome = await dispatcher.dispatch_text_async("/model two/ref")

    assert outcome is not None and outcome.status is OutcomeStatus.SUCCESS
    assert outcome.ui_action == ModelSelected("two/ref")
    assert application.current_model_ref == "two/ref"
    assert writes == ["two/ref"]


@pytest.mark.asyncio
async def test_model_switch_exception_is_redacted_from_outcome_and_repr() -> None:
    secret = "sk-secret-value"

    class SecretFailingApplication:
        def model_catalog(self):  # type: ignore[no-untyped-def]
            return (type("Model", (), {"model_ref": "safe/ref"})(),)

        def select_model(self, _model_ref):  # type: ignore[no-untyped-def]
            raise RuntimeError(f"provider URL contains {secret}")

    outcome = await CommandDispatcher(
        create_builtin_registry(),
        SecretFailingApplication(),
    ).dispatch_text_async("/model safe/ref")

    assert outcome is not None
    assert outcome.status is OutcomeStatus.EXECUTION_ERROR
    assert outcome.error == "模型切换失败"
    assert secret not in outcome.error
    assert secret not in repr(outcome.error)
    assert secret not in repr(outcome)


@pytest.mark.asyncio
async def test_status_reports_safe_application_values() -> None:
    application, _writes = _application()
    dispatcher = CommandDispatcher(create_builtin_registry(), application)

    outcome = await dispatcher.dispatch_text_async("/status")

    assert outcome is not None and outcome.output is not None
    assert outcome.status is OutcomeStatus.SUCCESS
    assert "one/ref" in outcome.output
    assert "local" in outcome.output
