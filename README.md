# UthCode

Re:UthCode is a small, embeddable coding-agent application with a single
message Application API, a non-interactive CLI, and a default Textual TUI.
This delivery is offline-testable and uses the UthCode-owned Provider contract
with Fake, Anthropic, OpenAI Responses, and OpenAI-compatible integrations.

## Install

Use the project Conda environment:

```powershell
conda activate re-uthcode
python -m pip install -e . --group dev
python -m pip check
```

The default test suite is offline:

```powershell
pytest -q
```

The three protocol live tests are explicitly skipped unless both a live flag
and a user-supplied API key are present. They are not part of the default
verification flow.

## First configuration

UthCode reads the user configuration from `~/.uthcode/config.toml`. On the
first run, a comment-only template is created atomically and the process
stops. Fill in the template and run the command again.

A minimal offline configuration is:

```toml
model = "local/echo"

[providers.local]
kind = "fake"

[models."local/echo"]
provider = "local"
model = "echo"
label = "Offline Echo"
```

Real Provider keys are read only from the environment variable named by
`api_key_env`; key values never belong in TOML, logs, events, or output. A
project configuration may select models and adjust non-secret model fields,
but may not define or redirect Providers, endpoints, or secret sources.
Inside a Git repository, project files are loaded from the repository root to
the current directory. Outside Git, only the current directory's project file
is considered.

## Default TUI

Run without a subcommand to start the default interface:

```powershell
uthcode
```

The interface contains a top bar, transcript, activity line, composer,
command completion menu, and model picker. Ordinary input is one independent
request; visible transcript entries are not sent as history to the next
request. Enter sends, Shift+Enter inserts a newline, and a second Escape
within one second cancels the active request.

The implemented commands are `/help`, `/clear`, `/model` (also `/models` and
`/m`), `/status`, and `/quit` (also `/q` and `/exit`). Registered commands
that are not implemented remain discoverable and report a uniform
not-implemented result. `/clear` only clears the visible transcript.

## Headless execution

`exec` never starts Textual and treats a leading slash as ordinary prompt
text:

```powershell
uthcode exec "Explain this directory"
"Explain this directory" | uthcode exec
uthcode exec --cwd C:\work\project --model local/echo "hello"
```

Text deltas are written to stdout. Diagnostics are written to stderr. Exit
codes are `0` for success, `1` for Provider failure, `2` for configuration or
usage failure, and `130` for cancellation.

## Embedded Python API

The same Effective Config/Application composition is available without the
CLI or TUI:

```python
import asyncio

from uthcode.application import (
    EffectiveConfig,
    GenerationCompleted,
    GenerationRequest,
    Message,
    ProviderKind,
    TextPart,
    create_application,
)


async def main() -> None:
    application = create_application(
        EffectiveConfig.single_model(
            "local/echo",
            provider_profile_id="local",
            provider_kind=ProviderKind.FAKE,
            remote_model_id="echo",
        )
    )
    request = GenerationRequest(
        messages=(Message("user", (TextPart("hello"),)),)
    )
    events = [event async for event in application.stream_generation(request)]
    assert isinstance(events[-1], GenerationCompleted)


asyncio.run(main())
```

`start_generation()` returns an independently cancellable `GenerationHandle`;
`stream_generation()` is the convenient one-request form.
