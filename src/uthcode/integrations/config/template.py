"""Safe first-run configuration template and atomic creation helper."""

from __future__ import annotations

import os
import uuid
from pathlib import Path


USER_CONFIG_TEMPLATE = """# UthCode configuration template
# Fill in a Provider and a Model, then run UthCode again.
# The values below are commented placeholders and are not usable credentials.
#
# model = \"example/example-model\"
#
# [providers.example]
# kind = \"fake\"
# api_key_env = \"YOUR_API_KEY_ENVIRONMENT_VARIABLE\"
# base_url = \"https://example.invalid/v1\"
#
# [models.\"example/example-model\"]
# provider = \"example\"
# model = \"remote-model-id\"
# label = \"Example model\"
# max_output_tokens = 4096
"""


def _chmod_private(path: Path) -> None:
    try:
        os.chmod(path, 0o600)
    except OSError:
        # Windows ACLs and some network filesystems do not implement POSIX
        # modes.  The file was created in the user's configuration directory.
        pass


def create_user_template(path: str | os.PathLike[str]) -> Path:
    """Create *path* with an atomic replace and return its absolute path."""

    target = Path(path).expanduser().resolve(strict=False)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(USER_CONFIG_TEMPLATE)
            handle.flush()
            os.fsync(handle.fileno())
        _chmod_private(temporary)
        os.replace(temporary, target)
        _chmod_private(target)
    except Exception:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise
    return target


__all__ = ["USER_CONFIG_TEMPLATE", "create_user_template"]
