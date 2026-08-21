"""Application-owned models for the Slash Command system.

The command layer deliberately contains no terminal or UI toolkit types.  It
describes user intent and the structured result that an interface can adapt
to its own presentation technology.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from enum import Enum

from uthcode.core.permission import PermissionMode
from uthcode.core.planning import BehaviorMode


class CommandKind(str, Enum):
    """The three command semantics understood by the Application layer."""

    LOCAL = "local"
    LOCAL_UI = "local_ui"
    PROMPT = "prompt"


class CommandAvailability(str, Enum):
    """Whether a command has an implementation in the current release."""

    IMPLEMENTED = "implemented"
    NOT_IMPLEMENTED = "not_implemented"


class InvocationStatus(str, Enum):
    """Parser result categories before a Dispatcher is involved."""

    TEXT = "text"
    SLASH = "slash"
    READY = "ready"
    UNKNOWN_COMMAND = "unknown_command"
    USAGE_ERROR = "usage_error"


class OutcomeStatus(str, Enum):
    """Stable status values returned by the Command Dispatcher."""

    SUCCESS = "success"
    USAGE_ERROR = "usage_error"
    UNKNOWN_COMMAND = "unknown_command"
    NOT_IMPLEMENTED = "not_implemented"
    EXECUTION_ERROR = "execution_error"


CandidateProvider = Callable[[object | None], Iterable[str]]
CommandHandler = Callable[[object], object | Awaitable[object]]


@dataclass(frozen=True, slots=True)
class ArgumentSpec:
    """One positional command argument and its completion metadata."""

    name: str
    required: bool = False
    multiple: bool = False
    description: str = ""
    choices: tuple[str, ...] = ()
    dynamic_candidates: CandidateProvider | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("argument name must be a non-empty string")
        if any(not isinstance(choice, str) or not choice for choice in self.choices):
            raise ValueError("argument choices must contain non-empty strings")
        object.__setattr__(self, "choices", tuple(self.choices))
        if self.dynamic_candidates is not None and not callable(
            self.dynamic_candidates
        ):
            raise TypeError("dynamic_candidates must be callable")

    def candidate_values(self, application: object | None = None) -> tuple[str, ...]:
        """Return static or application-backed candidates in definition order."""

        if self.dynamic_candidates is not None:
            values = self.dynamic_candidates(application)
            return tuple(str(value) for value in values)
        return self.choices

    @property
    def syntax(self) -> str:
        marker = f"<{self.name}>" if self.required else f"[{self.name}]"
        if self.multiple:
            marker += "..."
        return marker


@dataclass(frozen=True, slots=True)
class CommandDefinition:
    """One canonical command definition stored by :class:`CommandRegistry`."""

    canonical: str
    description: str
    kind: CommandKind
    aliases: tuple[str, ...] = ()
    availability: CommandAvailability = CommandAvailability.IMPLEMENTED
    arguments: tuple[ArgumentSpec, ...] = ()
    handler: CommandHandler | None = None
    hidden: bool = False
    query_required: bool = False
    accepts_query: bool | None = None
    usage: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.description, str):
            raise TypeError("command description must be a string")
        kind = self.kind
        if not isinstance(kind, CommandKind):
            kind = CommandKind(str(kind).strip().lower())
            object.__setattr__(self, "kind", kind)
        availability = self.availability
        if not isinstance(availability, CommandAvailability):
            availability = CommandAvailability(str(availability).strip().lower())
            object.__setattr__(self, "availability", availability)
        object.__setattr__(self, "aliases", tuple(self.aliases))
        object.__setattr__(self, "arguments", tuple(self.arguments))
        if self.accepts_query is None:
            object.__setattr__(self, "accepts_query", kind is CommandKind.PROMPT)

    @property
    def implemented(self) -> bool:
        return self.availability is CommandAvailability.IMPLEMENTED

    @property
    def usage_text(self) -> str:
        if self.usage is not None:
            return self.usage
        suffix = " ".join(argument.syntax for argument in self.arguments)
        return f"/{self.canonical}" + (f" {suffix}" if suffix else "")

    @property
    def argument_prompt(self) -> str:
        prompts = [
            f"{argument.name}: {argument.description}"
            if argument.description
            else argument.name
            for argument in self.arguments
        ]
        return ", ".join(prompts)


@dataclass(frozen=True, slots=True)
class CommandInvocation:
    """The lossless command interpretation produced by ``CommandParser``."""

    raw_input: str
    status: InvocationStatus
    is_slash: bool
    raw_name: str = ""
    canonical: str | None = None
    alias: str | None = None
    args: tuple[str, ...] = ()
    query: str = ""
    separator_seen: bool = False
    definition: CommandDefinition | None = None
    error: str | None = None

    @property
    def is_command(self) -> bool:
        return self.is_slash

    @property
    def is_executable(self) -> bool:
        return self.status is InvocationStatus.READY

    @property
    def is_bare_slash(self) -> bool:
        return self.status is InvocationStatus.SLASH

    @property
    def unknown(self) -> bool:
        return self.status is InvocationStatus.UNKNOWN_COMMAND

    @property
    def usage_error(self) -> bool:
        return self.status is InvocationStatus.USAGE_ERROR


@dataclass(frozen=True, slots=True)
class UiAction:
    """Marker base class for interface-neutral UI actions."""


@dataclass(frozen=True, slots=True)
class ClearTranscript(UiAction):
    """Request that the active interface clear its visible transcript."""


@dataclass(frozen=True, slots=True)
class OpenModelPicker(UiAction):
    """Request that the active interface show its model picker."""


@dataclass(frozen=True, slots=True)
class OpenPermissionPicker(UiAction):
    """Request that the active interface show the current Run mode picker."""


@dataclass(frozen=True, slots=True)
class OpenSessionPicker(UiAction):
    """Request that the active interface show the Application Session picker."""


@dataclass(frozen=True, slots=True)
class SessionChanged(UiAction):
    """Report that Application opened a new or restored Session."""

    session_id: str
    restored: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.session_id, str) or not self.session_id.strip():
            raise ValueError("session_id must be a non-empty string")
        if not isinstance(self.restored, bool):
            raise TypeError("restored must be a boolean")


@dataclass(frozen=True, slots=True)
class PermissionModeSelected(UiAction):
    """Report a user-selected permission mode to an interface."""

    mode: PermissionMode
    warning: str | None = None

    def __post_init__(self) -> None:
        mode = self.mode
        if not isinstance(mode, PermissionMode):
            mode = PermissionMode(mode)
            object.__setattr__(self, "mode", mode)


@dataclass(frozen=True, slots=True)
class BehaviorModeSelected(UiAction):
    """Request that an idle AgentRun select its next Turn behavior mode."""

    mode: BehaviorMode

    def __post_init__(self) -> None:
        mode = self.mode
        if not isinstance(mode, BehaviorMode):
            mode = BehaviorMode(mode)
            object.__setattr__(self, "mode", mode)


@dataclass(frozen=True, slots=True)
class QuitInterface(UiAction):
    """Request that the active interface exit."""


@dataclass(frozen=True, slots=True)
class ModelSelected(UiAction):
    """Report a successful direct model selection to an interface."""

    model_ref: str


@dataclass(frozen=True, slots=True)
class CommandOutcome:
    """One structured result from the Command Dispatcher."""

    status: OutcomeStatus
    output: str | None = None
    ui_action: UiAction | None = None
    prompt: str | None = None
    error: str | None = None
    invocation: CommandInvocation | None = None

    @classmethod
    def success_output(
        cls,
        output: str,
        *,
        invocation: CommandInvocation | None = None,
    ) -> CommandOutcome:
        return cls(OutcomeStatus.SUCCESS, output=output, invocation=invocation)

    @classmethod
    def success_ui(
        cls,
        action: UiAction,
        *,
        invocation: CommandInvocation | None = None,
    ) -> CommandOutcome:
        return cls(OutcomeStatus.SUCCESS, ui_action=action, invocation=invocation)

    @classmethod
    def success_prompt(
        cls,
        prompt: str,
        *,
        invocation: CommandInvocation | None = None,
    ) -> CommandOutcome:
        return cls(OutcomeStatus.SUCCESS, prompt=prompt, invocation=invocation)

    @property
    def message(self) -> str | None:
        """The user-facing text, when this outcome has one."""

        return self.output if self.output is not None else self.error


@dataclass(frozen=True, slots=True)
class CompletionCandidate:
    """One command completion item derived from a Registry definition."""

    canonical: str
    display: str
    description: str
    aliases: tuple[str, ...]
    availability: CommandAvailability
    usage: str
    argument_prompt: str
    matched_alias: str | None = None
    definition: CommandDefinition | None = None

    @property
    def value(self) -> str:
        return f"/{self.canonical}"

    @property
    def implemented(self) -> bool:
        return self.availability is CommandAvailability.IMPLEMENTED


__all__ = [
    "ArgumentSpec",
    "BehaviorModeSelected",
    "CandidateProvider",
    "ClearTranscript",
    "CommandAvailability",
    "CommandDefinition",
    "CommandHandler",
    "CommandInvocation",
    "CommandKind",
    "CommandOutcome",
    "CompletionCandidate",
    "InvocationStatus",
    "ModelSelected",
    "OpenPermissionPicker",
    "OpenModelPicker",
    "OpenSessionPicker",
    "OutcomeStatus",
    "PermissionModeSelected",
    "QuitInterface",
    "SessionChanged",
    "UiAction",
]
