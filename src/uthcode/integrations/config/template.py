"""Safe first-run configuration template and atomic creation helper."""

from __future__ import annotations

import os
import uuid
from pathlib import Path


USER_CONFIG_TEMPLATE = """# UthCode user configuration
#
# To configure an OpenAI-compatible Provider:
# 1. Replace the example values below for your Provider and model.
# 2. Uncomment the TOML configuration lines (leave these instructions commented).
# 3. Set the environment variable named by api_key_env, then run `uthcode` again.
#
# PowerShell example for the current terminal only:
# $env:DEEPSEEK_API_KEY = \"your-api-key\"
#
# Never put an API key value in this file. api_key_env is the environment
# variable name, not the key itself.
#
# Supported real Provider kinds: openai_compat, openai_responses, anthropic.
# Every real Provider requires api_key_env. openai_compat also requires base_url.
# The fake kind is only for explicit offline testing.
#
# default_permission_mode = \"default\" # allowed: default, auto
# model = \"deepseek/chat\"
#
# [providers.deepseek]
# kind = \"openai_compat\"
# base_url = \"https://api.deepseek.com\"
# api_key_env = \"DEEPSEEK_API_KEY\"
#
# [models.\"deepseek/chat\"]
# provider = \"deepseek\"
# model = \"deepseek-chat\"
# label = \"DeepSeek Chat\"
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
