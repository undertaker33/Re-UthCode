"""The standard-library CLI and the non-interactive execution adapter."""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TextIO

from uthcode.application import (
    ConfigurationError,
    ConfigurationInitializationRequired,
    EffectiveConfig,
    GenerationCancelled,
    GenerationCompleted,
    GenerationRequest,
    LaunchOptions,
    Message,
    ProviderError,
    ReasoningDelta,
    TextDelta,
    TextPart,
    UthCodeApplication,
    create_application,
    load_effective_config,
)


ConfigLoader = Callable[[LaunchOptions], EffectiveConfig]
ApplicationFactory = Callable[[EffectiveConfig], UthCodeApplication]
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
    cwd: Path | None,
    model: str | None,
    config_loader: ConfigLoader,
    application_factory: ApplicationFactory,
) -> UthCodeApplication:
    configuration = config_loader(
        _launch_options(cwd=cwd, home=None, model=model)
    )
    return application_factory(configuration)


def _message_text(message: object) -> str:
    parts = getattr(message, "parts", ())
    return "".join(
        str(getattr(part, "text", ""))
        for part in parts
        if isinstance(getattr(part, "text", ""), str)
    )


def _write_diagnostic(stderr: TextIO, text: str) -> None:
    stderr.write(text.rstrip("\n") + "\n")
    stderr.flush()


async def _stream_exec(
    application: UthCodeApplication,
    prompt: str,
    *,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    request = GenerationRequest(
        messages=(Message("user", (TextPart(prompt),)),)
    )
    wrote_text = False
    wrote_newline = False
    try:
        async for event in application.stream_generation(request):
            if isinstance(event, TextDelta):
                stdout.write(event.text)
                stdout.flush()
                wrote_text = True
                wrote_newline = event.text.endswith("\n")
            elif isinstance(event, ReasoningDelta):
                _write_diagnostic(stderr, event.text)
            elif isinstance(event, GenerationCompleted) and not wrote_text:
                response_text = _message_text(event.response.message)
                if response_text:
                    stdout.write(response_text)
                    stdout.flush()
                    wrote_text = True
                    wrote_newline = response_text.endswith("\n")
    except GenerationCancelled:
        _write_diagnostic(stderr, "generation cancelled")
        return 130
    except asyncio.CancelledError:
        _write_diagnostic(stderr, "generation cancelled")
        return 130
    except ProviderError:
        _write_diagnostic(stderr, "provider error: request failed")
        return 1
    except Exception:
        _write_diagnostic(stderr, "provider error: generation failed")
        return 1

    if not wrote_text or not wrote_newline:
        stdout.write("\n")
        stdout.flush()
    return 0


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
    *,
    cwd: Path | None = None,
) -> object:
    from uthcode.interfaces.tui import run_tui

    return run_tui(application, cwd=Path.cwd() if cwd is None else cwd)


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
            application = _load_application(
                cwd=cwd,
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
        return _run_exec(
            application,
            prompt.strip(),
            stdout=output_stream,
            stderr=error_stream,
        )

    try:
        application = _load_application(
            cwd=arguments.global_cwd,
            model=arguments.global_model,
            config_loader=loader,
            application_factory=factory,
        )
        if tui_runner is None:
            result = _default_tui_runner(
                application,
                cwd=arguments.global_cwd,
            )
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


__all__ = ["main"]
