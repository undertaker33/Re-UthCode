"""Headless generation use cases built on the Core Provider Port."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass, replace
from typing import Any

from uthcode.core.agent import (
    AgentLoop,
    AgentTurnExecution,
    PermissionResolver,
    RunState,
    SessionGrantSink,
)
from uthcode.core.interaction import ASK_USER_TOOL_DEFINITION
from uthcode.core.planning import (
    BehaviorMode,
    PROPOSE_PLAN_TOOL_DEFINITION,
    TODO_WRITE_TOOL_DEFINITION,
)
from uthcode.core.provider import (
    CancellationToken,
    GenerationRequest,
    ProviderEvent,
    ProviderIdentity,
    ProviderPort,
    ToolCallPart,
    ToolDefinition,
    ToolResultPart,
    validated_provider_stream,
)
from uthcode.core.prompt import (
    RuntimePromptContext,
    SystemPromptContext,
    build_system_prompt,
)
from uthcode.core.permission import PermissionEvaluator, PermissionMode, RuleSet

from .configuration import ConfigSource, EffectiveConfig, ModelProfile, ProviderProfile
from .context import ApplicationContextService
from .instructions import InstructionLoader
from .runtime_context import ApplicationRuntimeContext
from .sessions import ApplicationSession, ApplicationSessionService
from .tools import ApplicationToolService


ProviderBuilder = Callable[[ProviderProfile, ModelProfile], ProviderPort]
ModelWriter = Callable[[str], object]
PermissionWriter = Callable[[PermissionMode], object]
PermissionRulesLoader = Callable[[], RuleSet]


@dataclass(frozen=True, slots=True)
class ApplicationStatus:
    """Safe read-only runtime status for interfaces and headless callers."""

    current_model: str
    provider_profile: str
    provider_identity: ProviderIdentity
    configuration_sources: tuple[ConfigSource, ...]
    state: str = "ready"

    def to_dict(self) -> dict[str, Any]:
        return {
            "current_model": self.current_model,
            "provider_profile": self.provider_profile,
            "provider_identity": self.provider_identity.to_dict(),
            "configuration_sources": [
                {
                    "kind": source.kind,
                    "path": str(source.path) if source.path is not None else None,
                }
                for source in self.configuration_sources
            ],
            "state": self.state,
        }


class GenerationHandle:
    """One independently cancellable Application generation."""

    __slots__ = (
        "_application",
        "_provider",
        "_request",
        "_cancellation",
        "_started",
    )

    def __init__(
        self,
        application: UthCodeApplication,
        provider: ProviderPort,
        request: GenerationRequest,
        cancellation: CancellationToken,
    ) -> None:
        self._application = application
        self._provider = provider
        self._request = request
        self._cancellation = cancellation
        self._started = False

    @property
    def cancelled(self) -> bool:
        return self._cancellation.cancelled

    def cancel(self) -> bool:
        """Cancel this handle once; repeated calls are harmless."""

        return self._cancellation.cancel()

    async def events(self) -> AsyncIterator[ProviderEvent]:
        if self._started:
            raise RuntimeError("GenerationHandle.events() can only be consumed once")
        self._started = True
        async for event in self._application._stream_with_token(
            self._provider,
            self._request,
            self._cancellation,
        ):
            yield event


class UthCodeApplication:
    """Application boundary for configuration-backed provider generation."""

    def __init__(
        self,
        provider: ProviderPort,
        *,
        configuration: EffectiveConfig | None = None,
        provider_builder: ProviderBuilder | None = None,
        model_writer: ModelWriter | None = None,
        permission_writer: PermissionWriter | None = None,
        runtime_context: ApplicationRuntimeContext | None = None,
        tool_service: ApplicationToolService | None = None,
        permission_rules_loader: PermissionRulesLoader | None = None,
        instruction_loader: InstructionLoader | None = None,
        context_service: ApplicationContextService | None = None,
        session_service: ApplicationSessionService | None = None,
    ) -> None:
        self._provider = provider
        self._configuration = configuration
        self._provider_builder = provider_builder
        self._model_writer = model_writer
        self._permission_writer = permission_writer
        self._default_permission_mode = (
            configuration.default_permission_mode
            if configuration is not None
            else PermissionMode.DEFAULT
        )
        if runtime_context is None:
            runtime_context = ApplicationRuntimeContext.from_system()
        if not isinstance(runtime_context, ApplicationRuntimeContext):
            raise TypeError("runtime_context must be ApplicationRuntimeContext")
        self._runtime_context = runtime_context
        if tool_service is None:
            tool_service = ApplicationToolService(())
        if not isinstance(tool_service, ApplicationToolService):
            raise TypeError("tool_service must be an ApplicationToolService")
        if permission_rules_loader is not None and not callable(permission_rules_loader):
            raise TypeError("permission_rules_loader must be callable or None")
        if instruction_loader is not None and not isinstance(instruction_loader, InstructionLoader):
            raise TypeError("instruction_loader must be InstructionLoader or None")
        if context_service is not None and not isinstance(context_service, ApplicationContextService):
            raise TypeError("context_service must be ApplicationContextService or None")
        if session_service is not None and not isinstance(session_service, ApplicationSessionService):
            raise TypeError("session_service must be ApplicationSessionService or None")
        self._tool_service = tool_service
        self._permission_rules_loader = permission_rules_loader
        self._instruction_loader = instruction_loader
        self._context_service = context_service or ApplicationContextService()
        self._session_service = session_service
        if self._instruction_loader is not None:
            # Session-start loading is Application-owned; the loader itself
            # keeps filesystem policy in its Integration adapter.
            self._instruction_loader.load_session(strict=False)
        self._current_model_ref = (
            configuration.model if configuration is not None else provider.identity.model
        )

    @property
    def provider(self) -> ProviderPort:
        return self._provider

    @property
    def configuration(self) -> EffectiveConfig | None:
        return self._configuration

    @property
    def runtime_context(self) -> ApplicationRuntimeContext:
        return self._runtime_context

    @property
    def instruction_loader(self) -> InstructionLoader | None:
        """Return the Application-owned current instruction state service."""

        return self._instruction_loader

    @property
    def context_service(self) -> ApplicationContextService:
        """Return the Application-owned Context composition service."""

        return self._context_service

    @property
    def session_service(self) -> ApplicationSessionService | None:
        """Return the optional durable Session lifecycle service."""

        return self._session_service

    @property
    def current_model_ref(self) -> str:
        return self._current_model_ref

    @property
    def current_model(self) -> ModelProfile | None:
        if self._configuration is None:
            return None
        return self._configuration.models[self._current_model_ref]

    @property
    def current_provider_profile(self) -> ProviderProfile | None:
        model = self.current_model
        if model is None or self._configuration is None:
            return None
        return self._configuration.providers[model.provider_profile_id]

    def model_catalog(self) -> tuple[ModelProfile, ...]:
        if self._configuration is None:
            return ()
        return self._configuration.model_catalog()

    def tool_definitions(self) -> tuple[ToolDefinition, ...]:
        """Return the Application's immutable, ordered Tool definitions."""

        return self._tool_service.definitions()

    def compile_context(self, **kwargs: Any):
        """Compile a fixed-budget Context Snapshot from current sources."""

        if "instruction_loader" not in kwargs:
            kwargs["instruction_loader"] = self._instruction_loader
        if "tool_definitions" not in kwargs:
            kwargs["tool_definitions"] = self.tool_definitions()
        return self._context_service.compile(**kwargs)

    def context_usage(self, snapshot=None):
        """Return the same fixed-budget usage projection for headless callers."""

        return self._context_service.usage(snapshot)

    def create_session(self, session_id: str | None = None) -> ApplicationSession:
        if self._session_service is None:
            raise RuntimeError("durable Session storage is not configured")
        return self._session_service.create_session(session_id)

    def resume_session(self, session_id: str) -> ApplicationSession:
        if self._session_service is None:
            raise RuntimeError("durable Session storage is not configured")
        return self._session_service.resume_session(session_id)

    def list_sessions(self):
        if self._session_service is None:
            return ()
        return self._session_service.list_sessions()

    def close(self) -> None:
        """Release any Application-held Session writer lock."""

        if self._session_service is not None:
            self._session_service.close()

    def create_run(self, *, run_id: str | None = None) -> AgentRun:
        """Create one isolated in-memory Agent Run."""

        from .runs import AgentRun

        return AgentRun(
            self,
            run_id=run_id,
            permission_evaluator=self._permission_evaluator_for_run(),
            permission_mode=self._default_permission_mode,
        )

    @property
    def default_permission_mode(self) -> PermissionMode:
        return self._default_permission_mode

    def set_default_permission_mode(self, mode: PermissionMode | str) -> PermissionMode:
        if not isinstance(mode, PermissionMode):
            mode = PermissionMode(mode)
        if mode is PermissionMode.FULL_ACCESS:
            raise ValueError("full_access cannot be an Application default")
        if self._permission_writer is None:
            raise RuntimeError("permission selection has no user configuration writer")
        self._permission_writer(mode)
        self._default_permission_mode = mode
        return mode

    def _permission_evaluator_for_run(self) -> PermissionEvaluator:
        """Load exactly one immutable permission snapshot for a new Run."""

        if self._permission_rules_loader is None:
            return PermissionEvaluator()
        rules = self._permission_rules_loader()
        if not isinstance(rules, RuleSet):
            raise TypeError("permission_rules_loader must return a RuleSet")
        return PermissionEvaluator(rules)

    async def execute_tool_calls(
        self,
        calls: Sequence[ToolCallPart],
        *,
        cancellation: CancellationToken | None = None,
    ) -> tuple[ToolResultPart, ...]:
        """Reject the manual Tool path at the Application boundary.

        Ordinary Tool execution needs a Run-local mode, RuleSet snapshot and
        T06 pause/resume channel.  This API has none of those contracts, so
        accepting a call here would create a permission bypass.  Callers must
        use ``create_run().start_turn()`` instead.
        """

        del calls, cancellation
        raise ValueError(
            "manual Tool execution is disabled; use AgentRun.start_turn"
        )

    def status(self) -> ApplicationStatus:
        profile = self.current_provider_profile
        provider_profile_id = (
            profile.provider_profile_id
            if profile is not None
            else self._provider.identity.provider
        )
        sources = self._configuration.sources if self._configuration is not None else ()
        return ApplicationStatus(
            current_model=self._current_model_ref,
            provider_profile=provider_profile_id,
            provider_identity=self._provider.identity,
            configuration_sources=sources,
        )

    def select_model(self, model_ref: str) -> ModelProfile:
        """Switch Provider and model only after candidate and persistence succeed."""

        if self._configuration is None:
            raise ValueError("model selection requires an EffectiveConfig")
        if not isinstance(model_ref, str) or not model_ref.strip():
            raise ValueError("model_ref must be a non-empty string")
        candidate_model = self._configuration.models.get(model_ref)
        if candidate_model is None:
            raise ValueError(f"unknown model reference: {model_ref!r}")
        if self._provider_builder is None:
            raise RuntimeError("model selection has no Provider builder")
        candidate_provider = self._provider_builder(
            self._configuration.providers[candidate_model.provider_profile_id],
            candidate_model,
        )
        if not isinstance(candidate_provider, ProviderPort):
            raise TypeError("Provider builder must return a ProviderPort")
        if self._model_writer is not None:
            self._model_writer(model_ref)
        self._provider = candidate_provider
        self._current_model_ref = model_ref
        return candidate_model

    def start_generation(
        self,
        request: GenerationRequest,
    ) -> GenerationHandle:
        """Create one request handle with an independently owned token."""

        provider = self._provider
        prepared_request = self._prepare_request(request, provider)
        return GenerationHandle(
            self,
            provider,
            prepared_request,
            CancellationToken(),
        )

    def _start_agent_turn(
        self,
        state: RunState,
        user_input: str,
        *,
        turn_id: str,
        cancellation: CancellationToken,
        behavior_mode: BehaviorMode,
        permission_resolver: PermissionResolver,
        session_grant_sink: SessionGrantSink,
    ) -> AgentTurnExecution:
        """Start a Core Turn with Application-owned snapshots.

        This is an internal composition boundary used by ``AgentRun``.  The
        Provider object, model reference, ordered definitions, and summary
        callable are captured before Core receives the Turn, so a later model
        switch cannot alter an active Turn.
        """

        provider = self._provider
        model_ref = self._current_model_ref
        ordinary_tool_definitions = self._tool_service.definitions()
        tool_definitions = ordinary_tool_definitions + (ASK_USER_TOOL_DEFINITION,)
        tool_definitions += (TODO_WRITE_TOOL_DEFINITION,)
        tool_definitions += (PROPOSE_PLAN_TOOL_DEFINITION,)

        def prepare(
            messages: tuple[Message, ...],
            visible_definitions: tuple[ToolDefinition, ...],
            runtime_context: RuntimePromptContext,
        ) -> GenerationRequest:
            request = GenerationRequest(messages=messages, tools=visible_definitions)
            return self._prepare_request(
                request,
                provider,
                model_ref=model_ref,
                runtime_context=runtime_context,
            )

        loop = self._tool_service._create_agent_loop(
            provider,
            prepare,
            permission_resolver=permission_resolver,
            session_grant_sink=session_grant_sink,
        )
        execution = loop.start_turn(
            state,
            user_input,
            turn_id=turn_id,
            cancellation=cancellation,
            behavior_mode=behavior_mode,
            tool_definitions=tool_definitions,
        )
        if execution.state.messages[-1].role != "user":  # pragma: no cover
            raise RuntimeError("Agent Loop did not append the user message")
        return execution

    def _prepare_request(
        self,
        request: GenerationRequest,
        provider: ProviderPort,
        *,
        model_ref: str | None = None,
        runtime_context: RuntimePromptContext | None = None,
    ) -> GenerationRequest:
        if not isinstance(request, GenerationRequest):
            raise TypeError("request must be GenerationRequest")
        if request.system_prompt is not None:
            raise ValueError(
                "Application owns system_prompt; caller must leave it unset"
            )
        if request.model is not None:
            raise ValueError("Application owns model; caller must leave it unset")

        identity = provider.identity
        selected_model_ref = (
            self._current_model_ref if model_ref is None else model_ref
        )
        prompt_context = SystemPromptContext(
            workdir=str(self._runtime_context.workdir),
            platform_name=self._runtime_context.platform_name,
            platform_release=self._runtime_context.platform_release,
            current_date=self._runtime_context.current_date,
            model_ref=selected_model_ref,
            provider_protocol=identity.protocol,
            remote_model_id=identity.model,
        )
        if self._instruction_loader is None and runtime_context is None:
            # Keep the established no-argument Core call shape for embedded
            # callers and its precise error boundary.
            system_prompt = build_system_prompt(prompt_context)
        else:
            system_prompt = build_system_prompt(
                prompt_context,
                runtime_context=runtime_context,
                instruction_blocks=self._instruction_loader.effective_instruction_set,
            ) if self._instruction_loader is not None else build_system_prompt(
                prompt_context,
                runtime_context=runtime_context,
            )
        return replace(request, system_prompt=system_prompt)

    async def stream_generation(
        self,
        request: GenerationRequest,
    ) -> AsyncIterator[ProviderEvent]:
        """Convenience stream implemented by the formal GenerationHandle."""

        handle = self.start_generation(request)
        async for event in handle.events():
            yield event

    async def _stream_with_token(
        self,
        provider: ProviderPort,
        request: GenerationRequest,
        token: CancellationToken,
    ) -> AsyncIterator[ProviderEvent]:
        """Yield one provider stream through the shared Core validator."""

        async for event in validated_provider_stream(
            provider,
            request,
            cancellation=token,
        ):
            yield event


__all__ = [
    "ApplicationStatus",
    "GenerationHandle",
    "UthCodeApplication",
]
