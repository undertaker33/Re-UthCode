"""Application-owned access to the Core Tool runtime."""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Sequence
from os import PathLike
from pathlib import Path, PureWindowsPath

from uthcode.core.provider import (
    ProviderPort,
    ToolCallPart,
    ToolDefinition,
)
from uthcode.core.agent import AgentLoop
from uthcode.core.command_security import safe_bash_command_summary
from uthcode.core.interaction import ASK_USER_TOOL_DEFINITION
from uthcode.core.permission import PermissionAction, PermissionDecision
from uthcode.core.tool import Tool, ToolExecutor, ToolRegistry


_MAX_SUMMARY_CHARS = 240
_SUMMARY_UNAVAILABLE = "<tool summary unavailable>"
_UNKNOWN_TOOL = "<unknown tool>"
_REDACTED = "<redacted>"
_NON_SECRET_AMBIENT_VALUES = frozenset({"0", "1"})
_SENSITIVE_TOKEN = re.compile(
    r"(?i)(?<![A-Za-z0-9_])"
    r"(?:[A-Za-z0-9_]*(?:api[_-]?key|token|secret|password|passwd|authorization)"
    r"[A-Za-z0-9_-]*)"
    r"(?![A-Za-z0-9_])"
)
_SENSITIVE_ASSIGNMENT = re.compile(
    r"(?i)(?P<prefix>(?:[A-Za-z0-9_]*(?:api[_-]?key|token|secret|password|passwd|authorization)"
    r"[A-Za-z0-9_-]*)\s*[:=]\s*)"
    r"(?:\"[^\"]*\"|'[^']*'|[^\s]+)"
)
_SENSITIVE_OPTION_VALUE = re.compile(
    r"(?i)(?P<prefix>(?<![A-Za-z0-9_-])"
    r"(?:--?|/)?[A-Za-z0-9_-]*"
    r"(?:api[_-]?key|token|secret|password|passwd|authorization)"
    r"[A-Za-z0-9_-]*[ \t]+)"
    r"(?:\"[^\"\r\n]*\"|'[^'\r\n]*'|[^\s]+)"
)
_AUTHORIZATION_VALUE = re.compile(
    r"(?i)(?P<prefix>\bAuthorization\s*[:=]\s*)"
    r"(?P<scheme>[A-Za-z][A-Za-z0-9._-]*\s+)?[^\s,;\"']+"
)
_BEARER_CREDENTIAL = re.compile(
    r"(?i)(?<![A-Za-z0-9])Bearer\s+[^\s,;\"']+"
)
_BARE_API_KEY = re.compile(
    r"(?i)(?<![A-Za-z0-9_])sk-[A-Za-z0-9][A-Za-z0-9_.:/-]*"
)


class _SecretRedactor:
    """Redact current secret sources without retaining their values.

    Environment values are read only while a summary is being sanitized.  The
    redactor stores configured environment *names*, never their values, and
    never returns the values through an exception, event, or diagnostic.
    """

    __slots__ = ("_secret_env_names",)

    def __init__(self, secret_env_names: Sequence[str]) -> None:
        names: list[str] = []
        for name in secret_env_names:
            if not isinstance(name, str):
                raise TypeError("secret environment names must be strings")
            if name and name not in names:
                names.append(name)
        self._secret_env_names = tuple(names)

    def redact(self, value: str) -> str:
        if not isinstance(value, str):
            raise TypeError("summary values must be strings")

        # Shape-based credentials are removed first so an unrelated, shorter
        # environment value cannot split a credential into printable pieces.
        redacted = _AUTHORIZATION_VALUE.sub(_replace_authorization, value)
        redacted = _BEARER_CREDENTIAL.sub(f"Bearer {_REDACTED}", redacted)
        redacted = _SENSITIVE_ASSIGNMENT.sub(
            rf"\g<prefix>{_REDACTED}",
            redacted,
        )
        redacted = _SENSITIVE_OPTION_VALUE.sub(
            rf"\g<prefix>{_REDACTED}",
            redacted,
        )
        redacted = _BARE_API_KEY.sub(_REDACTED, redacted)
        redacted = _SENSITIVE_TOKEN.sub(_REDACTED, redacted)

        # Configured secret sources are authoritative even when their current
        # value is short. Ambient environment values use a conservative
        # token boundaries. The process commonly carries single-digit 0/1
        # feature flags; treating those as secrets would destroy unrelated
        # numeric commands, so they are the only explicit ambient exclusions.
        configured_values = [
            os.environ[name]
            for name in self._secret_env_names
            if os.environ.get(name)
        ]
        for secret in sorted(set(configured_values), key=len, reverse=True):
            redacted = redacted.replace(secret, _REDACTED)
        ambient_values = {
            value
            for value in os.environ.values()
            if _is_ambient_secret_candidate(value)
        }
        for secret in sorted(ambient_values, key=len, reverse=True):
            redacted = _replace_bounded_value(redacted, secret)
        return redacted


def _replace_authorization(match: re.Match[str]) -> str:
    scheme = match.group("scheme")
    return f"{match.group('prefix')}{scheme or ''}{_REDACTED}"


def _is_ambient_secret_candidate(value: str) -> bool:
    return bool(value.strip()) and value not in _NON_SECRET_AMBIENT_VALUES


def _replace_bounded_value(value: str, secret: str) -> str:
    left_boundary = (
        r"(?<![A-Za-z0-9_])" if re.match(r"[A-Za-z0-9_]", secret[0]) else ""
    )
    right_boundary = (
        r"(?![A-Za-z0-9_])" if re.match(r"[A-Za-z0-9_]", secret[-1]) else ""
    )
    return re.sub(
        f"{left_boundary}{re.escape(secret)}{right_boundary}",
        _REDACTED,
        value,
    )


class ApplicationToolService:
    """Hide Registry and Executor details behind the Application boundary."""

    __slots__ = ("_executor", "_redactor", "_registry", "_workdir")

    def __init__(
        self,
        tools: Sequence[Tool],
        *,
        workdir: str | PathLike[str] | Path | None = None,
        secret_env_names: Sequence[str] = (),
    ) -> None:
        tool_values = tuple(tools)
        if any(tool.definition.name == ASK_USER_TOOL_DEFINITION.name for tool in tool_values):
            raise ValueError("AskUserQuestion is reserved for the Application Agent path")
        self._registry = ToolRegistry(tool_values)
        self._executor = ToolExecutor(self._registry)
        self._redactor = _SecretRedactor(secret_env_names)
        self._workdir = (
            Path(workdir).expanduser().resolve(strict=False)
            if workdir is not None
            else None
        )

    def definitions(self) -> tuple[ToolDefinition, ...]:
        """Return the immutable, registration-ordered public definitions."""

        return self._registry.definitions()

    def describe_tool_call(self, call: ToolCallPart) -> str:
        """Return a bounded, display-safe summary for one registered call.

        This method deliberately understands only the stable semantics of the
        current Tool definitions.  It never serializes the full arguments and
        never includes a ToolResult.  Unknown or malformed calls receive a
        safe placeholder instead of exposing arbitrary input.
        """

        try:
            if not isinstance(call, ToolCallPart):
                return _SUMMARY_UNAVAILABLE
            tool = self._registry.get(call.name)
            if tool is None:
                return _UNKNOWN_TOOL

            arguments = call.arguments
            if call.name == "Bash":
                command = safe_bash_command_summary(_safe_command(arguments.get("command")))
                command = self._redactor.redact(command)
                summary = f"Bash {command}"
            elif call.name in {"ReadFile", "WriteFile", "EditFile"}:
                path = self._redactor.redact(
                    _safe_text(arguments.get("path"), "<path unavailable>")
                )
                summary = f"{call.name} {_safe_path(path, self._workdir)}"
            elif call.name == "Glob":
                pattern = self._redactor.redact(
                    _safe_text(arguments.get("pattern"), "<pattern unavailable>")
                )
                scope_value = self._redactor.redact(
                    _safe_text(arguments.get("path", "."), ".")
                )
                scope = _safe_path(scope_value, self._workdir)
                summary = f"Glob pattern={pattern} path={scope}"
            elif call.name == "Grep":
                scope_value = self._redactor.redact(
                    _safe_text(arguments.get("path", "."), ".")
                )
                scope = _safe_path(scope_value, self._workdir)
                # A search pattern is caller-supplied content and may itself
                # be a secret read from a sensitive file.  Keep it out of
                # ToolStarted/Pause summaries altogether.
                summary = f"Grep path={scope}"
                if arguments.get("include") not in (None, ""):
                    include = self._redactor.redact(
                        _safe_text(arguments.get("include"), "<include unavailable>")
                    )
                    summary += f" include={include}"
            else:
                # A custom Tool may have arbitrary argument names.  Its name
                # is useful, while its argument payload is not safe to echo.
                summary = call.name
            summary = self._redactor.redact(summary)
            return _truncate_summary(_single_line(summary))
        except Exception:
            return _SUMMARY_UNAVAILABLE

    def _create_agent_loop(
        self,
        provider: ProviderPort,
        request_preparer: Callable[..., object],
        *,
        permission_resolver: Callable[[PermissionAction], PermissionDecision],
        session_grant_sink: Callable[[PermissionAction], None] | None = None,
    ) -> AgentLoop:
        """Build a Core Loop over this service's one Registry/Executor.

        The method is intentionally private: Application composition may pass
        the existing runtime into Core, but callers cannot obtain either
        runtime object through the public Application API.
        """

        return AgentLoop(
            provider,
            self._registry,
            self._executor,
            request_preparer,
            tool_call_describer=self.describe_tool_call,
            permission_resolver=permission_resolver,
            session_grant_sink=session_grant_sink,
        )


def _safe_text(value: object, fallback: str) -> str:
    if not isinstance(value, str) or not value.strip():
        return fallback
    return value


def _safe_command(value: object) -> str:
    return _safe_text(value, "<command unavailable>")


def _safe_path(value: object, workdir: Path | None) -> str:
    raw = _safe_text(value, "<path unavailable>")
    if raw.startswith("<") and raw.endswith(">"):
        return raw
    if "\x00" in raw:
        return "<path unavailable>"

    normalized = raw.replace("\\", "/")
    if normalized.startswith("/") or PureWindowsPath(normalized).is_absolute():
        path = Path(raw).expanduser()
        if workdir is not None:
            try:
                return path.resolve(strict=False).relative_to(workdir).as_posix()
            except ValueError:
                pass
        return "<absolute path>"
    parts = tuple(part for part in normalized.split("/") if part not in ("", "."))
    if ".." in parts:
        return "<unsafe path>"
    return normalized or "."


def _single_line(value: str) -> str:
    return " ".join(value.replace("\r", " ").replace("\n", " ").split())


def _truncate_summary(value: str) -> str:
    if len(value) <= _MAX_SUMMARY_CHARS:
        return value
    return value[: _MAX_SUMMARY_CHARS - 1] + "…"


__all__ = ["ApplicationToolService"]
