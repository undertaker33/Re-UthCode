"""Public Application Command System API."""

from .builtins import create_builtin_registry
from .completion import CompletionEngine, complete_commands
from .dispatcher import CommandContext, CommandDispatcher, CommandExecutionError
from .models import (
    ArgumentSpec,
    BehaviorModeSelected,
    CandidateProvider,
    ClearTranscript,
    CommandDefinition,
    CommandHandler,
    CommandInvocation,
    CommandKind,
    CommandOutcome,
    CompletionCandidate,
    InvocationStatus,
    ModelSelected,
    OpenPermissionPicker,
    OpenModelPicker,
    OpenSessionPicker,
    OutcomeStatus,
    PermissionModeSelected,
    QuitInterface,
    SessionChanged,
    SessionReplayRecord,
    UiAction,
)
from .parser import CommandParser, parse_command
from .registry import CommandRegistry

__all__ = [
    "ArgumentSpec",
    "BehaviorModeSelected",
    "CandidateProvider",
    "ClearTranscript",
    "CommandContext",
    "CommandDefinition",
    "CommandDispatcher",
    "CommandExecutionError",
    "CommandHandler",
    "CommandInvocation",
    "CommandKind",
    "CommandOutcome",
    "CommandParser",
    "CommandRegistry",
    "CompletionCandidate",
    "CompletionEngine",
    "InvocationStatus",
    "ModelSelected",
    "OpenPermissionPicker",
    "OpenModelPicker",
    "OpenSessionPicker",
    "OutcomeStatus",
    "PermissionModeSelected",
    "QuitInterface",
    "SessionChanged",
    "SessionReplayRecord",
    "UiAction",
    "complete_commands",
    "create_builtin_registry",
    "parse_command",
]
