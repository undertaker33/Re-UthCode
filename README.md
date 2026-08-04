# UthCode

Re:UthCode is being rebuilt as a headless, embeddable coding-agent core.

This delivery provides the installable Python package, the UthCode-owned
Provider contract, a formal headless Application composition root, a
deterministic Fake Provider, and protocol integrations for Anthropic Messages,
OpenAI Responses, and OpenAI-compatible Chat Completions.

It deliberately does not provide a CLI, TUI, agent loop, tool execution,
permissions, persistence, or session management.

## Development environment

Use the project Conda environment:

```powershell
conda activate re-uthcode
python -m pip install -e . --group dev
pytest -q
```

The default test suite is offline. The three DeepSeek live smoke tests use
`deepseek-v4-flash`, make two requests per protocol (six requests total), and
may incur provider charges. Run them only after explicit confirmation of the
network and cost impact, and set the key yourself in the current PowerShell
session:

```powershell
$env:DEEPSEEK_API_KEY = '<用户自行填写>'
$env:UTHCODE_RUN_LIVE = '1'
conda run -n re-uthcode pytest -q -m live
Remove-Item Env:DEEPSEEK_API_KEY
Remove-Item Env:UTHCODE_RUN_LIVE
```

Without both the live flag and the key, live tests remain skipped. Test output
and errors are designed not to include the key.

If the managed environment cannot write its default user-site directory,
use a temporary writable user base for the editable install:

```powershell
$taskPythonUserBase = Join-Path $env:TEMP "re-uthcode-python-user"
$env:PYTHONUSERBASE = $taskPythonUserBase
python -m pip install -e . --group dev --user
```

The package uses a `src` layout and can be imported as `uthcode` after an
editable install. Root-package import does not construct a provider or make a
network request.

## Headless Application

The supported composition entry is `uthcode.application.create_application`.
It constructs the configured Provider through the Integration Factory and
returns a headless application; callers consume the Core events directly.

```python
import asyncio

from uthcode.application import ProviderConfig, ProviderKind, create_application
from uthcode.core import GenerationCompleted, GenerationRequest, Message, TextPart


async def main() -> None:
    application = create_application(
        ProviderConfig(kind=ProviderKind.FAKE, model="fake-model")
    )
    request = GenerationRequest(messages=(Message("user", (TextPart("hello"),)),))
    events = [event async for event in application.stream_generation(request)]
    assert isinstance(events[-1], GenerationCompleted)


asyncio.run(main())
```

Real Providers read their API key only from the named process environment
variable. Construction itself does not make a network request:

```python
real_application = create_application(
    ProviderConfig(
        kind=ProviderKind.ANTHROPIC,
        model="your-model",
        api_key_env="DEEPSEEK_API_KEY",
        base_url="https://your-anthropic-compatible-endpoint",
    )
)
```

An OpenAI-compatible Provider also requires an explicit `base_url` in its
configuration. Do not put a real key in `.env.example`, source code, or
configuration files.

## Scope

This delivery includes the installable skeleton, UthCode-owned Provider
contract, formal `create_application` headless entry, deterministic Fake
Provider, and the three protocol integrations listed above. The default test
suite is offline, with the six-request DeepSeek live smoke suite available
only through the explicitly authorized `live` marker.

CLI, TUI, agent loop, tool execution, permissions, persistence, and session
management are outside this delivery.
