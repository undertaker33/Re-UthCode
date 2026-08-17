"""The standard-library CLI and the non-interactive execution adapter."""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TextIO

from uthcode.application import (
    AgentEvent,
    AgentRun,
    ApplicationRuntimeContext,
    ConfigurationError,
    ConfigurationInitializationRequired,
    EffectiveConfig,
    LaunchOptions,
    PauseKind,
    ProviderError,
    TextPart,
    TurnHandle,
    UthCodeApplication,
    create_application,
    load_effective_config,
)


ConfigLoader = Callable[[LaunchOptions], EffectiveConfig]
ApplicationFactory = Callable[..., UthCodeApplication]
TuiRunner = Callable[[UthCodeApplication], object]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="uthcode",
        description="UthCode single-message coding assistant",
    )
    parser.add_argument("--cwd", dest="global_cwd", type=Path)
    parser.add_argument("--model", dest="global_model")

    subparsers = parser.add_subparsers(dest="command")
    exec_parser = subparsers.add_parser(
        "exec",
        help="run one prompt without starting the TUI",
    )
    exec_parser.add_argument("--cwd", dest="exec_cwd", type=Path)
    exec_parser.add_argument("--model", dest="exec_model")
    exec_parser.add_argument("prompt", nargs="?")
    return parser


def _launch_options(
    *,
    cwd: Path | None,
    home: Path | None,
    model: str | None,
) -> LaunchOptions:
    return LaunchOptions(cwd=cwd, home=home, model=model)


def _load_application(
    *,
    runtime_context: ApplicationRuntimeContext,
    model: str | None,
    config_loader: ConfigLoader,
    application_factory: ApplicationFactory,
) -> UthCodeApplication:
    configuration = config_loader(
        _launch_options(
            cwd=runtime_context.workdir,
            home=None,
            model=model,
        )
    )
    return application_factory(configuration, runtime_context=runtime_context)


def _write_diagnostic(stderr: TextIO, text: str) -> None:
    stderr.write(text.rstrip("\n") + "\n")
    stderr.flush()


def _message_text(message: object) -> str:
    parts = getattr(message, "parts", ())
    return "".join(
        part.text
        for part in parts
        if isinstance(part, TextPart)
    )


def _event_value(event: AgentEvent, name: str, default: object = None) -> object:
    return getattr(event, name, default)


def _enum_value(value: object) -> str:
    candidate = getattr(value, "value", value)
    return candidate if isinstance(candidate, str) else str(candidate)


def _tool_diagnostic(event: AgentEvent) -> str:
    status = "running" if event.event_type == "tool_started" else _enum_value(
        _event_value(event, "status", "finished")
    )
    name = _event_value(event, "tool_name", "unknown tool")
    command = _event_value(event, "command", "<tool summary unavailable>")
    return f"tool {status}: {name} ({command})"


class _ExecProjection:
    """Project one AgentEvent stream into the CLI's two output channels."""

    __slots__ = ("_pending_assistant", "_final_text", "_suppress_terminal")

    def __init__(self) -> None:
        self._pending_assistant: dict[str, str] = {}
        self._final_text: str | None = None
        self._suppress_terminal = False

    def suppress_terminal(self) -> None:
        """Prevent a paused non-interactive turn from projecting a final."""

        self._suppress_terminal = True

    def consume(self, event: AgentEvent, *, stdout: TextIO, stderr: TextIO) -> int | None:
        event_type = event.event_type
        if event_type == "assistant_message_delta":
            message_id = _event_value(event, "message_id")
            text = _event_value(event, "text", "")
            if isinstance(message_id, str) and isinstance(text, str):
                self._pending_assistant[message_id] = (
                    self._pending_assistant.get(message_id, "") + text
                )
            return None

        if event_type == "assistant_message_completed":
            message_id = _event_value(event, "message_id")
            text = _message_text(_event_value(event, "message"))
            if isinstance(message_id, str):
                self._pending_assistant[message_id] = text
            kind = _enum_value(_event_value(event, "kind", "incomplete"))
            if kind == "final":
                self._final_text = text
            else:
                if text:
                    _write_diagnostic(stderr, text)
            return None

        if event_type == "reasoning_delta":
            text = _event_value(event, "text", "")
            if isinstance(text, str) and text:
                _write_diagnostic(stderr, text)
            return None

        if event_type in {"tool_started", "tool_finished"}:
            _write_diagnostic(stderr, _tool_diagnostic(event))
            return None

        if event_type == "turn_completed":
            if self._suppress_terminal:
                return None
            final_text = _event_value(event, "final_text", self._final_text or "")
            if not isinstance(final_text, str):
                final_text = self._final_text or ""
            stdout.write(final_text)
            if not final_text.endswith("\n"):
                stdout.write("\n")
            stdout.flush()
            return 0

        if event_type == "turn_cancelled":
            if self._suppress_terminal:
                return None
            _write_diagnostic(stderr, "generation cancelled")
            return 130

        if event_type == "turn_failed":
            reason = _enum_value(_event_value(event, "termination_reason", "internal_error"))
            _write_diagnostic(stderr, f"generation failed: {reason}")
            return 1

        return None


def _pause_diagnostic(event: AgentEvent) -> str:
    pause = _event_value(event, "pause")
    kind = _enum_value(_event_value(pause, "kind", ""))
    if kind == PauseKind.USER_INPUT_REQUIRED.value:
        return "generation requires interactive input"
    if kind == PauseKind.PROVIDER_UNAVAILABLE.value:
        return "provider temporarily unavailable"
    if kind == PauseKind.PERMISSION_REQUIRED.value:
        return "permission approval required; non-interactive execution was cancelled"
    return "generation paused and cannot continue non-interactively"


async def _stream_exec(
    application: UthCodeApplication,
    prompt: str,
    *,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    try:
        ensure_session = getattr(application, "ensure_session", None)
        if callable(ensure_session):
            ensure_session()
        run: AgentRun = application.create_run()
        turn: TurnHandle = run.start_turn(prompt)
        projection = _ExecProjection()
        terminal_code: int | None = None
        paused_for_noninteractive = False
        async for event in turn.events():
            if event.event_type == "turn_paused":
                if not paused_for_noninteractive:
                    paused_for_noninteractive = True
                    projection.suppress_terminal()
                    _write_diagnostic(stderr, _pause_diagnostic(event))
                    # ``exec`` has no response channel.  Cancel exactly once
                    # and keep consuming the same public event stream until
                    # Application closes the Turn.
                    turn.cancel()
                continue
            result = projection.consume(event, stdout=stdout, stderr=stderr)
            if result is not None:
                terminal_code = result
    except asyncio.CancelledError:
        _write_diagnostic(stderr, "generation cancelled")
        return 130
    except ProviderError:
        _write_diagnostic(stderr, "provider error: request failed")
        return 1
    except Exception:
        _write_diagnostic(stderr, "provider error: generation failed")
        return 1
    if paused_for_noninteractive:
        return 1
    if terminal_code is None:
        _write_diagnostic(stderr, "provider error: turn ended without a terminal event")
        return 1
    return terminal_code


def _run_exec(
    application: UthCodeApplication,
    prompt: str,
    *,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    try:
        return asyncio.run(
            _stream_exec(
                application,
                prompt,
                stdout=stdout,
                stderr=stderr,
            )
        )
    except KeyboardInterrupt:
        _write_diagnostic(stderr, "generation cancelled")
        return 130


def _default_tui_runner(
    application: UthCodeApplication,
) -> object:
    from uthcode.interfaces.tui import run_tui

    return run_tui(application)


def main(
    argv: Sequence[str] | None = None,
    *,
    tui_runner: TuiRunner | None = None,
    config_loader: ConfigLoader | None = None,
    application_factory: ApplicationFactory | None = None,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Run the default TUI or one headless ``exec`` request.

    The loader, factory and TUI runner are injectable so the full dispatch
    logic can be verified without a terminal, a network, or a process-global
    configuration directory.
    """

    input_stream = sys.stdin if stdin is None else stdin
    output_stream = sys.stdout if stdout is None else stdout
    error_stream = sys.stderr if stderr is None else stderr
    parser = _build_parser()
    try:
        arguments = parser.parse_args(list(argv) if argv is not None else None)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 2

    loader = load_effective_config if config_loader is None else config_loader
    factory = create_application if application_factory is None else application_factory

    if arguments.command == "exec":
        cwd = arguments.exec_cwd or arguments.global_cwd
        model = arguments.exec_model or arguments.global_model
        prompt = arguments.prompt
        if prompt is None:
            prompt = input_stream.read()
        if not isinstance(prompt, str) or not prompt.strip():
            _write_diagnostic(error_stream, "usage error: a non-empty prompt is required")
            return 2
        try:
            runtime_context = ApplicationRuntimeContext.from_system(workdir=cwd)
            application = _load_application(
                runtime_context=runtime_context,
                model=model,
                config_loader=loader,
                application_factory=factory,
            )
        except ConfigurationInitializationRequired as exc:
            _write_diagnostic(error_stream, str(exc))
            return 2
        except ConfigurationError as exc:
            _write_diagnostic(error_stream, str(exc))
            return 2
        except ProviderError:
            _write_diagnostic(error_stream, "provider error: application startup failed")
            return 1
        except Exception:
            _write_diagnostic(error_stream, "application configuration failed")
            return 2
        try:
            return _run_exec(
                application,
                prompt.strip(),
                stdout=output_stream,
                stderr=error_stream,
            )
        finally:
            close = getattr(application, "close", None)
            if callable(close):
                close()

    try:
        runtime_context = ApplicationRuntimeContext.from_system(
            workdir=arguments.global_cwd
        )
        application = _load_application(
            runtime_context=runtime_context,
            model=arguments.global_model,
            config_loader=loader,
            application_factory=factory,
        )
        application.ensure_session()
        if tui_runner is None:
            result = _default_tui_runner(application)
        else:
            result = tui_runner(application)
        return result if isinstance(result, int) else 0
    except KeyboardInterrupt:
        _write_diagnostic(error_stream, "interface cancelled")
        return 130
    except ConfigurationInitializationRequired as exc:
        _write_diagnostic(error_stream, str(exc))
        return 2
    except ConfigurationError as exc:
        _write_diagnostic(error_stream, str(exc))
        return 2
    except ProviderError:
        _write_diagnostic(error_stream, "provider error: application startup failed")
        return 1
    except Exception:
        _write_diagnostic(error_stream, "interface failed")
        return 1
    finally:
        if "application" in locals() and isinstance(application, UthCodeApplication):
            application.close()


__all__ = ["main"]
