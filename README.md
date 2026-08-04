# UthCode

Re:UthCode is being rebuilt as a headless, embeddable coding-agent core.

This work package starts with the installable Python package and the provider
boundary. It deliberately does not provide a CLI, TUI, agent loop, tool
execution, permissions, persistence, or session management.

## Development environment

Use the project Conda environment:

```powershell
conda activate re-uthcode
python -m pip install -e . --group dev
pytest -q
```

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

## Scope

The current Foundation Worker batch builds the installable skeleton, the
UthCode-owned provider contract, a headless application boundary with a fake
provider, and the shared Pydantic AI Direct integration boundary. Protocol
specific provider adapters and later agent capabilities are separate tasks.
