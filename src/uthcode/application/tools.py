"""Application-owned access to the Core Tool runtime."""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Mapping, Sequence
from os import PathLike
from pathlib import Path, PureWindowsPath

from uthcode.core.provider import (
    CancellationToken,
    ContentSequence,
    JsonPayload,
    TextPart,
    ProviderPort,
    ToolCallPart,
    ToolDefinition,
    ToolResultPart,
)
from uthcode.core.secrets import SecretValue
from uthcode.core.agent import AgentLoop
from uthcode.core.agent_events import ToolProgress as ToolProgressEvent
from uthcode.core.command_security import safe_bash_command_summary
from uthcode.core.interaction import ASK_USER_TOOL_DEFINITION
from uthcode.core.planning import PROPOSE_PLAN_TOOL_DEFINITION, TODO_WRITE_TOOL_DEFINITION
from uthcode.core.permission import PermissionAction, PermissionDecision
from uthcode.core.tool import (
    PreparedToolCall,
    Tool,
    ToolExecutor,
    ToolRegistry,
    ToolProgress as CoreToolProgress,
)
from uthcode.core.tool import (
    ToolExecutionOutcome,
    ToolResultMaterialization,
    ToolResultPersistenceStatus,
)
from uthcode.integrations.tools.tool_result_read import (
    ToolResultError,
    ToolResultPage,
    ToolResultPolicy,
    ToolResultReadTool,
    ToolResultReference,
    ToolResultTooLarge,
    format_externalized_preview,
)
from uthcode.integrations.tools.history_read import (
    HistoryReadBoundaryError,
    HistoryReadPage,
    HistoryReadPolicy,
    HistoryReadSessionError,
    HistoryReadTool,
    decode_history_ref,
)


_MAX_SUMMARY_CHARS = 240
_SUMMARY_UNAVAILABLE = "<tool summary unavailable>"
_UNKNOWN_TOOL = "<unknown tool>"
_CUSTOM_ARGUMENTS_HIDDEN = "<arguments hidden>"
_REDACTED = "<redacted>"
_NON_SECRET_AMBIENT_VALUES = frozenset({"0", "1"})
_SENSITIVE_NAME = (
    r"(?:[A-Za-z0-9_-]*(?:api[_-]?key|token|secret|password|passwd|authorization|credential)"
    r"[A-Za-z0-9_-]*|(?:key|auth)|[A-Za-z0-9]+(?:[_-](?:key|auth))"
    r"(?:[_-][A-Za-z0-9]+)*|(?:key|auth)(?:[_-][A-Za-z0-9]+)+)"
)
_SENSITIVE_TOKEN = re.compile(
    r"(?i)(?<![A-Za-z0-9_])"
    rf"{_SENSITIVE_NAME}"
    r"(?![A-Za-z0-9_])"
)
_SENSITIVE_ASSIGNMENT = re.compile(
    rf"(?i)(?P<prefix>(?<![A-Za-z0-9_-]){_SENSITIVE_NAME}\s*[:=]\s*)"
    r"(?:\"[^\"]*\"|'[^']*'|[^\s]+)"
)
_SENSITIVE_OPTION_VALUE = re.compile(
    r"(?i)(?P<prefix>(?<![A-Za-z0-9_-])"
    r"(?:--?|/)?[A-Za-z0-9_-]*"
    rf"{_SENSITIVE_NAME}[ \t]+)"
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
    """Redact current secret sources without exposing their values.

    Environment names are resolved only while a summary is being sanitized;
    user-level literal/env credentials arrive as opaque ``SecretValue``
    objects. The redactor never returns values through an exception, event, or
    diagnostic.
    """

    __slots__ = ("_secret_env_names", "_secret_values")

    def __init__(
        self,
        secret_env_names: Sequence[str] = (),
        secret_values: Sequence[SecretValue] = (),
    ) -> None:
        names: list[str] = []
        for name in secret_env_names:
            if not isinstance(name, str):
                raise TypeError("secret environment names must be strings")
            if name and name not in names:
                names.append(name)
        self._secret_env_names = tuple(names)
        values: list[SecretValue] = []
        for value in secret_values:
            if not isinstance(value, SecretValue):
                raise TypeError("secret_values must contain SecretValue values")
            if value not in values:
                values.append(value)
        self._secret_values = tuple(values)

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
        configured_values.extend(secret.reveal() for secret in self._secret_values)
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

    def progress_tail_length(self, value: str) -> int:
        """Return the short raw suffix that may still complete a secret."""

        if not value:
            return 0
        configured_values = [
            os.environ[name]
            for name in self._secret_env_names
            if os.environ.get(name)
        ]
        configured_values.extend(secret.reveal() for secret in self._secret_values)
        configured_values.extend(
            value
            for value in os.environ.values()
            if _is_ambient_secret_candidate(value) and len(value) > 2
        )
        completed_end = 0
        for secret in set(configured_values):
            if secret:
                position = value.rfind(secret)
                if position >= 0:
                    completed_end = max(completed_end, position + len(secret))
        candidate = value[completed_end:]
        longest = 0
        for secret in set(configured_values):
            if not secret:
                continue
            upper = min(len(secret) - 1, len(candidate))
            for length in range(upper, 0, -1):
                if candidate.endswith(secret[:length]):
                    longest = max(longest, length)
                    break
        # Keep common credential-shaped prefixes bounded even when their
        # concrete value is supplied only by an ambient environment source.
        lowered = candidate.lower()
        for prefix in ("sk-", "bearer ", "token=", "api_key=", "authorization:"):
            index = lowered.rfind(prefix)
            if index >= 0 and index + len(prefix) <= len(candidate):
                # Shape-only credentials have no configured full length.  A
                # single ToolProgress report is bounded at 512 characters;
                # keep that existing observation bound for this conservative
                # fallback while configured Secret values use their real size.
                longest = max(longest, min(len(candidate) - index, 512))
        return longest


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

    __slots__ = (
        "_executor",
        "_redactor",
        "_registry",
        "_session_provider",
        "_tool_result_policy",
        "_history_read_policy",
        "_workdir",
        "_externalization_stats",
        "_progress_buffers",
        "_process_progress_buffers",
    )

    def __init__(
        self,
        tools: Sequence[Tool],
        *,
        workdir: str | PathLike[str] | Path | None = None,
        secret_env_names: Sequence[str] = (),
        secret_values: Sequence[SecretValue] = (),
        session_provider: Callable[[], object | None] | None = None,
        tool_result_policy: ToolResultPolicy | None = None,
        history_read_policy: HistoryReadPolicy | None = None,
    ) -> None:
        tool_values = tuple(tools)
        reserved_names = {
            ASK_USER_TOOL_DEFINITION.name,
            TODO_WRITE_TOOL_DEFINITION.name,
            PROPOSE_PLAN_TOOL_DEFINITION.name,
            "ToolResultRead",
            "HistoryRead",
        }
        if any(tool.definition.name in reserved_names for tool in tool_values):
            raise ValueError(
                "AskUserQuestion is reserved for the Application Agent path; "
                "TodoWrite and ProposePlan are reserved for the Core Agent path"
            )
        if session_provider is not None and not callable(session_provider):
            raise TypeError("session_provider must be callable or None")
        self._session_provider = session_provider
        self._tool_result_policy = (
            ToolResultPolicy() if tool_result_policy is None else tool_result_policy
        )
        if not isinstance(self._tool_result_policy, ToolResultPolicy):
            raise TypeError("tool_result_policy must be a ToolResultPolicy or None")
        self._history_read_policy = (
            HistoryReadPolicy() if history_read_policy is None else history_read_policy
        )
        if not isinstance(self._history_read_policy, HistoryReadPolicy):
            raise TypeError("history_read_policy must be a HistoryReadPolicy or None")
        if session_provider is not None:
            tool_values = (
                *tool_values,
                ToolResultReadTool(
                    self._read_tool_result_page,
                    session_provider,
                    policy=self._tool_result_policy,
                ),
                HistoryReadTool(
                    self._read_history_page,
                    session_provider,
                    policy=self._history_read_policy,
                ),
            )
        self._registry = ToolRegistry(tool_values)
        self._executor = ToolExecutor(self._registry)
        self._redactor = _SecretRedactor(secret_env_names, secret_values)
        self._workdir = (
            Path(workdir).expanduser().resolve(strict=False)
            if workdir is not None
            else None
        )
        self._externalization_stats: dict[str, object] = {
            "attempts": 0,
            "inline": 0,
            "externalized": 0,
            "failed": 0,
            "externalized_bytes": 0,
            "failed_bytes": 0,
            "last": None,
        }
        self._progress_buffers: dict[
            tuple[str, str, int, str, str, str],
            tuple[str, CoreToolProgress],
        ] = {}
        self._process_progress_buffers: dict[tuple[str, str], str] = {}

    def definitions(self) -> tuple[ToolDefinition, ...]:
        """Return the immutable, registration-ordered public definitions."""

        return self._registry.definitions()

    def ensure_tool(self, tool: Tool) -> None:
        """Add one Application-composed Tool to the existing registry.

        Formal bootstrap normally supplies Process with the other built-ins.
        The small composition seam also lets embedders that supplied a custom
        Tool tuple use the same Application authorization path without a
        second executor or a manager call from an Interface.
        """

        if not isinstance(tool, Tool):
            raise TypeError("tool must implement the Tool protocol")
        if self._registry.get(tool.definition.name) is None:
            self._registry.register(tool)

    def tool(self, name: str) -> Tool | None:
        """Return one registered Tool for Application-owned orchestration."""

        return self._registry.get(name)

    def prepare_tool_call(
        self,
        call: ToolCallPart,
        *,
        cancellation: CancellationToken | None = None,
    ) -> PreparedToolCall | ToolResultPart:
        """Prepare a registered call through the one Core ToolExecutor."""

        return self._executor.prepare_call(call, cancellation=cancellation)

    async def execute_prepared_tool(
        self,
        prepared: PreparedToolCall,
        *,
        cancellation: CancellationToken,
    ) -> ToolExecutionOutcome:
        """Execute an already-authorized call through the same executor."""

        return await self._executor.execute_prepared_outcome(
            prepared,
            cancellation=cancellation,
        )

    def public_diagnostics(self) -> dict[str, object]:
        """Return aggregate Tool-result persistence facts without payloads."""

        stats = dict(self._externalization_stats)
        last = stats.get("last")
        stats["last"] = dict(last) if isinstance(last, Mapping) else None
        return {"schema_version": 1, "externalization": stats}

    def describe_tool_call(self, call: ToolCallPart) -> str:
        """Return a bounded, display-safe summary for one registered call.

        This method deliberately understands only the stable semantics of the
        current Tool definitions.  It owns the safe argument summary, while
        the AgentEvent ``tool_name`` field owns the displayed Tool name.  It
        never serializes the full arguments and never includes a ToolResult.
        Unknown or malformed calls receive a safe placeholder instead of
        exposing arbitrary input.
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
                summary = command
            elif call.name in {"ReadFile", "WriteFile", "EditFile"}:
                path = self._redactor.redact(
                    _safe_text(arguments.get("path"), "<path unavailable>")
                )
                summary = _safe_path(path, self._workdir)
            elif call.name == "Glob":
                pattern = self._redactor.redact(
                    _safe_text(arguments.get("pattern"), "<pattern unavailable>")
                )
                scope_value = self._redactor.redact(
                    _safe_text(arguments.get("path", "."), ".")
                )
                scope = _safe_path(scope_value, self._workdir)
                summary = f"pattern={pattern} path={scope}"
            elif call.name == "Grep":
                scope_value = self._redactor.redact(
                    _safe_text(arguments.get("path", "."), ".")
                )
                scope = _safe_path(scope_value, self._workdir)
                # A search pattern is caller-supplied content and may itself
                # be a secret read from a sensitive file.  Keep it out of
                # ToolStarted/Pause summaries altogether.
                summary = f"path={scope}"
                if arguments.get("include") not in (None, ""):
                    include = self._redactor.redact(
                        _safe_text(arguments.get("include"), "<include unavailable>")
                    )
                    summary += f" include={include}"
            elif call.name == "ToolResultRead":
                ref = _safe_text(arguments.get("ref"), "<ref unavailable>")
                offset = arguments.get("offset", 0)
                limit = arguments.get("limit", self._tool_result_policy.read_page_limit_bytes)
                summary = f"ref={ref} offset={offset} limit={limit}"
            elif call.name == "HistoryRead":
                ref = _safe_text(arguments.get("ref"), "<ref unavailable>")
                offset = arguments.get("offset", 0)
                limit = arguments.get("limit", self._history_read_policy.page_entry_limit)
                summary = f"ref={ref} offset={offset} limit={limit}"
            else:
                # A custom Tool may have arbitrary argument names.  Its name
                # is carried separately by AgentEvent, while its argument
                # payload is not safe to echo.
                summary = _CUSTOM_ARGUMENTS_HIDDEN
            summary = self._redactor.redact(summary)
            return _truncate_summary(_single_line(summary))
        except Exception:
            return _SUMMARY_UNAVAILABLE

    def redact_progress(self, progress: CoreToolProgress) -> CoreToolProgress:
        """Apply the Application's bounded, secret-aware progress projection."""

        if not isinstance(progress, CoreToolProgress):
            raise TypeError("progress must be a ToolProgress")
        text = self._redactor.redact(_progress_text(progress.text))
        return CoreToolProgress(
            stage=progress.stage,
            text=_truncate_summary(text, limit=512),
            current=progress.current,
            total=progress.total,
            stream=progress.stream,
        )

    def redact_progress_chunks(
        self,
        progress: Sequence[CoreToolProgress],
    ) -> tuple[CoreToolProgress, ...]:
        """Sanitize a bounded chunk window as one value before publishing.

        Joining the short window lets the existing SecretValue-aware redactor
        catch a credential split across two chunks.  The window is bounded and
        the emitted values remain ordinary progress observations, never Tool
        results or RunState messages.
        """

        values = tuple(progress)
        if len(values) > 256:
            raise ValueError("progress chunk window is too large")
        if not all(isinstance(item, CoreToolProgress) for item in values):
            raise TypeError("progress must contain ToolProgress values")
        if not values:
            return ()
        joined = _truncate_summary(
            self._redactor.redact(_progress_text("".join(item.text for item in values))),
            limit=512 * 256,
        )
        first = values[0]
        if not joined:
            last = values[-1]
            return (
                CoreToolProgress(
                    stage=first.stage,
                    text="",
                    current=last.current,
                    total=last.total,
                    stream=last.stream,
                ),
            )
        return tuple(
            CoreToolProgress(
                stage=first.stage,
                text=joined[index : index + 512],
                current=values[-1].current,
                total=values[-1].total,
                stream=values[-1].stream,
            )
            for index in range(0, len(joined), 512)
        )

    def project_process_output(
        self,
        observation: Mapping[str, object],
    ) -> dict[str, object]:
        """Redact one live process observation with cross-chunk state.

        Process output is an Application event stream, not a Tool result or
        RunState message.  The short retained suffix is still necessary: a
        credential can be split at any pump boundary, including after the
        ToolCall and Turn have already completed.
        """

        if not isinstance(observation, Mapping):
            raise TypeError("process observation must be a mapping")
        session_id = observation.get("session_id")
        process_id = observation.get("process_id")
        if not isinstance(session_id, str) or not session_id or not isinstance(process_id, str) or not process_id:
            raise ValueError("process observation identity is invalid")
        key = (session_id, process_id)
        incoming = observation.get("text")
        incoming_text = incoming if isinstance(incoming, str) else ""
        raw = self._process_progress_buffers.get(key, "") + incoming_text
        state = observation.get("state")
        terminal = observation.get("type") == "process_state" or state in {"exited", "unknown"}
        if not raw and not terminal:
            return dict(observation)
        if terminal:
            self._process_progress_buffers.pop(key, None)
            safe_text = self._redactor.redact(raw)
        else:
            hold = min(self._redactor.progress_tail_length(raw), len(raw))
            safe_raw = raw[:-hold] if hold else raw
            safe_text = self._redactor.redact(safe_raw)
            self._process_progress_buffers[key] = raw[-hold:] if hold else ""
        projected = dict(observation)
        # The process ring owns the byte bound.  Do not truncate a chunk here:
        # doing so would make process.read disagree with the same sanitized
        # cursor stream used by live events and Tool results.
        projected["text"] = safe_text
        return projected

    def project_process_command(self, command: str) -> str:
        """Project Process.list command metadata through the same redactor."""

        if not isinstance(command, str):
            return "<command unavailable>"
        return _truncate_summary(self._redactor.redact(command), limit=512)

    def project_tool_progress(
        self,
        progress: CoreToolProgress,
        *,
        run_id: str,
        turn_id: str,
        iteration: int,
        batch_id: str,
        tool_call_id: str,
        tool_name: str,
    ) -> ToolProgressEvent:
        """Attach ownership after sanitizing one Tool progress observation."""

        projected = self.redact_progress(progress)
        return ToolProgressEvent(
            run_id,
            turn_id,
            iteration,
            batch_id,
            tool_call_id,
            tool_name,
            projected.stage,
            projected.text,
            projected.current,
            projected.total,
            projected.stream,
        )

    def project_tool_progress_chunks(
        self,
        progress: Sequence[CoreToolProgress],
        *,
        run_id: str,
        turn_id: str,
        iteration: int,
        batch_id: str,
        tool_call_id: str,
        tool_name: str,
        flush: bool = False,
    ) -> tuple[ToolProgressEvent, ...]:
        """Publish safe progress text while retaining only a short raw tail.

        A report is redacted together with the suffix retained from the
        previous report.  Text that cannot be part of a credential prefix is
        emitted immediately; only that bounded suffix remains in memory until
        the next report or the end-of-execution flush.
        """

        values = tuple(progress)
        if not all(isinstance(item, CoreToolProgress) for item in values):
            raise TypeError("progress must contain ToolProgress values")
        key = (run_id, turn_id, iteration, batch_id, tool_call_id, tool_name)
        emitted: list[ToolProgressEvent] = []

        def redact_window(item: CoreToolProgress, text: str) -> str:
            chunks = tuple(
                CoreToolProgress(
                    stage=item.stage,
                    text=text[index : index + 512],
                    current=item.current,
                    total=item.total,
                    stream=item.stream,
                )
                for index in range(0, len(text), 512)
            )
            return "".join(
                chunk.text for chunk in self.redact_progress_chunks(chunks)
            )

        def project_text(item: CoreToolProgress, text: str) -> None:
            if not text:
                projected = CoreToolProgress(
                    stage=item.stage,
                    current=item.current,
                    total=item.total,
                    stream=item.stream,
                )
                emitted.append(
                    self.project_tool_progress(
                        projected,
                        run_id=run_id,
                        turn_id=turn_id,
                        iteration=iteration,
                        batch_id=batch_id,
                        tool_call_id=tool_call_id,
                        tool_name=tool_name,
                    )
                )
                return
            for index in range(0, len(text), 512):
                projected = CoreToolProgress(
                    stage=item.stage,
                    text=text[index : index + 512],
                    current=item.current,
                    total=item.total,
                    stream=item.stream,
                )
                emitted.append(
                    self.project_tool_progress(
                        projected,
                        run_id=run_id,
                        turn_id=turn_id,
                        iteration=iteration,
                        batch_id=batch_id,
                        tool_call_id=tool_call_id,
                        tool_name=tool_name,
                    )
                )

        for item in values:
            previous = self._progress_buffers.get(key)
            previous_text = previous[0] if previous is not None else ""
            incoming = _progress_text(item.text)
            raw = previous_text + incoming
            if not raw:
                project_text(item, "")
                continue

            hold = 0
            if not flush:
                hold = min(self._redactor.progress_tail_length(raw), len(raw))
                # A completed secret can overlap a still-open suffix.  Keep
                # enough context that the prefix released now cannot become
                # part of a credential after a later report arrives.
                while hold < len(raw):
                    prefix = raw[:-hold] if hold else raw
                    additional = self._redactor.progress_tail_length(prefix)
                    if additional <= 0:
                        break
                    next_hold = min(
                        len(raw),
                        hold + additional,
                    )
                    if next_hold <= hold:
                        break
                    hold = next_hold

            safe_raw = raw[:-hold] if hold else raw
            safe_text = redact_window(item, raw if flush else safe_raw)
            if hold and not flush:
                self._progress_buffers[key] = (raw[-hold:], item)
            else:
                self._progress_buffers.pop(key, None)
            project_text(item, safe_text)

        if flush and not values:
            previous = self._progress_buffers.pop(key, None)
            if previous is not None:
                raw, item = previous
                project_text(item, redact_window(item, raw))
        return tuple(emitted)

    def _create_agent_loop(
        self,
        provider: ProviderPort,
        request_preparer: Callable[..., object],
        *,
        permission_resolver: Callable[[PermissionAction], PermissionDecision],
        session_grant_sink: Callable[[PermissionAction], None] | None = None,
        overflow_handler: Callable[[], object] | None = None,
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
            result_materializer=self.materialize_tool_result,
            tool_progress_projector=self.project_tool_progress_chunks,
            overflow_handler=overflow_handler,
        )

    def materialize_tool_result(
        self,
        outcome: ToolExecutionOutcome,
    ) -> ToolResultMaterialization:
        """Apply Application resource policy after Core has executed a Tool."""

        if not isinstance(outcome, ToolExecutionOutcome):
            raise TypeError("outcome must be a ToolExecutionOutcome")
        text_content = str(outcome.content)
        size_bytes = len(text_content.encode("utf-8"))
        execution_metadata = _execution_metadata(outcome)

        # ToolResultRead is already a bounded page.  Never recursively
        # externalize the only reader for an externalized result.
        if outcome.tool_name in {"ToolResultRead", "HistoryRead"} or size_bytes <= self._tool_result_policy.inline_threshold_bytes:
            self._record_materialization("inline", size_bytes)
            return ToolResultMaterialization(
                execution=outcome,
                result=outcome.result,
                persistence_status=ToolResultPersistenceStatus.INLINE,
                size_bytes=size_bytes,
            )

        if size_bytes > self._tool_result_policy.single_result_hard_cap_bytes:
            self._record_materialization("failed", size_bytes, ToolResultTooLarge.code)
            metadata = {
                **execution_metadata,
                "persistence_status": ToolResultPersistenceStatus.FAILED.value,
                "error_code": ToolResultTooLarge.code,
                "size_bytes": size_bytes,
            }
            result = ToolResultPart(
                outcome.tool_call_id,
                _content_with_text(
                    outcome.content,
                    "Error: Tool execution completed, but the result exceeded the "
                    f"{self._tool_result_policy.single_result_hard_cap_bytes}-byte hard cap; "
                    "the Tool already ran and will not be retried",
                ),
                outcome.is_error,
                metadata,
            )
            return ToolResultMaterialization(
                execution=outcome,
                result=result,
                persistence_status=ToolResultPersistenceStatus.FAILED,
                size_bytes=size_bytes,
                error_code=ToolResultTooLarge.code,
            )

        session = self._session_provider() if self._session_provider is not None else None
        if session is None or not callable(getattr(session, "persist_tool_result", None)):
            return self._persistence_failure(
                outcome,
                size_bytes=size_bytes,
                error_code="active_session_required",
                message=(
                    "Error: Tool execution completed, but this large result requires an "
                    "active Session for durable persistence; the Tool already ran and "
                    "will not be retried"
                ),
            )

        try:
            reference = session.persist_tool_result(
                text_content,
                policy=self._tool_result_policy,
            )
            if not isinstance(reference, ToolResultReference):
                raise TypeError("Session returned an invalid Tool Result reference")
        except ToolResultError as exc:
            return self._persistence_failure(
                outcome,
                size_bytes=size_bytes,
                error_code=exc.code,
                message=(
                    f"Error: Tool execution completed, but result persistence failed "
                    f"({exc.code}); the Tool already ran and will not be retried"
                ),
            )
        except Exception:
            return self._persistence_failure(
                outcome,
                size_bytes=size_bytes,
                error_code="result_persistence_failed",
                message=(
                    "Error: Tool execution completed, but result persistence failed; "
                    "the Tool already ran and will not be retried"
                ),
            )

        metadata = {
            **execution_metadata,
            "persistence_status": ToolResultPersistenceStatus.EXTERNALIZED.value,
            "ref": reference.ref,
            "size_bytes": reference.size_bytes,
            "sha256": reference.sha256,
        }
        visible = format_externalized_preview(
            text_content,
            reference,
            preview_limit_bytes=self._tool_result_policy.preview_limit_bytes,
        )
        result = ToolResultPart(
            outcome.tool_call_id,
            _content_with_text(outcome.content, visible),
            outcome.is_error,
            metadata,
        )
        self._record_materialization("externalized", reference.size_bytes)
        return ToolResultMaterialization(
            execution=outcome,
            result=result,
            persistence_status=ToolResultPersistenceStatus.EXTERNALIZED,
            reference=reference.ref,
            size_bytes=reference.size_bytes,
            sha256=reference.sha256,
        )

    def _persistence_failure(
        self,
        outcome: ToolExecutionOutcome,
        *,
        size_bytes: int,
        error_code: str,
        message: str,
    ) -> ToolResultMaterialization:
        self._record_materialization("failed", size_bytes, error_code)
        metadata: Mapping[str, object] = {
            **_execution_metadata(outcome),
            "persistence_status": ToolResultPersistenceStatus.FAILED.value,
            "error_code": error_code,
            "size_bytes": size_bytes,
        }
        return ToolResultMaterialization(
            execution=outcome,
            result=ToolResultPart(
                outcome.tool_call_id,
                _content_with_text(outcome.content, message),
                outcome.is_error,
                metadata,
            ),
            persistence_status=ToolResultPersistenceStatus.FAILED,
            size_bytes=size_bytes,
            error_code=error_code,
        )

    def _record_materialization(
        self,
        status: str,
        size_bytes: int,
        error_code: str | None = None,
    ) -> None:
        stats = self._externalization_stats
        stats["attempts"] = int(stats["attempts"]) + 1
        stats[status] = int(stats[status]) + 1
        if status == "externalized":
            stats["externalized_bytes"] = int(stats["externalized_bytes"]) + size_bytes
        if status == "failed":
            stats["failed_bytes"] = int(stats["failed_bytes"]) + size_bytes
        last: dict[str, object] = {"status": status, "size_bytes": size_bytes}
        if error_code is not None:
            last["error_code"] = error_code
        stats["last"] = last

    def _read_tool_result_page(
        self,
        session_id: str,
        ref: str,
        offset: int,
        limit: int,
    ) -> ToolResultPage:
        session = self._session_provider() if self._session_provider is not None else None
        if session is None or getattr(session, "session_id", None) != session_id:
            raise ToolResultError("Tool Result ref is not owned by the active Session")
        page = session.read_tool_result(
            ref,
            offset=offset,
            limit=limit,
            policy=self._tool_result_policy,
        )
        if not isinstance(page, ToolResultPage):
            raise ToolResultError("Session returned an invalid Tool Result page")
        return page

    def _read_history_page(
        self,
        session_id: str,
        ref_token: str,
        offset: int,
        limit: int,
    ) -> HistoryReadPage:
        session = self._session_provider() if self._session_provider is not None else None
        if session is None or getattr(session, "session_id", None) != session_id:
            raise HistoryReadSessionError(
                "HistoryRead ref is not owned by the active Session"
            )
        ref = decode_history_ref(ref_token)
        if ref.session_id != session_id:
            raise HistoryReadSessionError(
                "HistoryRead ref is not owned by the active Session"
            )
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise HistoryReadBoundaryError("HistoryRead offset is invalid")
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= self._history_read_policy.page_entry_limit
        ):
            raise HistoryReadBoundaryError("HistoryRead limit is invalid")
        try:
            entries = tuple(session.read_transcript(ref))
        except HistoryReadBoundaryError:
            raise
        except (TypeError, ValueError) as exc:
            raise HistoryReadBoundaryError("HistoryRead ref is not a complete boundary") from exc
        total_entries = len(entries)
        if offset > total_entries:
            raise HistoryReadBoundaryError("HistoryRead offset is outside the ref")
        page_entries = entries[offset : offset + limit]
        next_offset = offset + len(page_entries)
        return HistoryReadPage(
            ref=ref.to_token(),
            entries=page_entries,
            offset=offset,
            next_offset=next_offset,
            total_entries=total_entries,
            eof=next_offset >= total_entries,
        )


def _execution_metadata(outcome: ToolExecutionOutcome) -> dict[str, object]:
    """Preserve known execution facts when Application adds persistence facts."""

    metadata: dict[str, object] = {"execution_status": outcome.status.value}
    if outcome.side_effect.value != "none":
        metadata["side_effect"] = outcome.side_effect.value
    if outcome.failure is not None:
        metadata["failure"] = outcome.failure.to_dict()
    for field_name in ("resource", "process_id", "process_state", "stream", "next_cursor"):
        value = getattr(outcome, field_name)
        if value is not None:
            metadata[field_name] = value
    if outcome.exit_code is not None:
        metadata["exit_code"] = outcome.exit_code
    metadata.update(outcome.details)
    return metadata


def _content_with_text(content: ContentSequence, replacement: str) -> ContentSequence:
    """Replace only textual slots while retaining every reference in order."""

    if not isinstance(content, ContentSequence):
        content = ContentSequence(content)
    parts = list(content.parts)
    replaced = False
    projected: list[object] = []
    for part in parts:
        if isinstance(part, TextPart):
            if not replaced:
                projected.append(TextPart(replacement))
                replaced = True
            else:
                projected.append(TextPart(""))
        else:
            projected.append(part)
    if not replaced:
        projected.insert(0, TextPart(replacement))
    return ContentSequence(tuple(projected))


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


def _progress_text(value: str) -> str:
    """Normalize line breaks while preserving ordinary progress whitespace."""

    return value.replace("\r", " ").replace("\n", " ")


def _truncate_summary(value: str, *, limit: int = _MAX_SUMMARY_CHARS) -> str:
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 2:
        raise ValueError("limit must be an integer >= 2")
    if len(value) <= limit:
        return value
    return value[: limit - 1] + "…"


__all__ = ["ApplicationToolService"]
