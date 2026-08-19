"""Safe first-run configuration template and atomic creation helper."""

from __future__ import annotations

import os
import uuid
from pathlib import Path


USER_CONFIG_TEMPLATE = """# UthCode user configuration
#
# Fill one complete provider slot and one complete model slot, then set
# default_model to the model slot ID. Delete unused slots when convenient.
# api_key accepts a direct value or an environment reference using the env:
# prefix. Configure provider kind, endpoint, and environment variable names
# only in this user-level file; project configuration cannot contain them.
# reasoning_effort is optional: none, minimal, low, medium, high, xhigh, max.
# The first run creates this empty template and stops with an initialization
# message; it is not a runnable configuration until a complete pair is filled.
#
default_model = \"\"
default_permission_mode = \"default\"

[providers.slot-1]
kind = \"\"
api_key = \"\"
# base_url = \"\"

[providers.slot-2]
kind = \"\"
api_key = \"\"
# base_url = \"\"

[providers.slot-3]
kind = \"\"
api_key = \"\"
# base_url = \"\"

[models.\"slot-1\"]
provider = \"\"
remote_id = \"\"
# display_name = \"\"
# context_window = 〈正整数〉
# max_output_tokens = 4096
# reasoning_effort = \"\"

[models.\"slot-2\"]
provider = \"\"
remote_id = \"\"
# display_name = \"\"
# context_window = 〈正整数〉
# max_output_tokens = 4096
# reasoning_effort = \"\"

[models.\"slot-3\"]
provider = \"\"
remote_id = \"\"
# display_name = \"\"
# context_window = 〈正整数〉
# max_output_tokens = 4096
# reasoning_effort = \"\"
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
