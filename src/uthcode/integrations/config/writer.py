"""TOMLKit-backed atomic user model selection write-back."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

from tomlkit import dumps, parse


def _chmod_private(path: Path) -> None:
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def write_user_model(
    path: str | os.PathLike[str],
    model_ref: str,
) -> Path:
    """Atomically update only the root ``model`` value of a user file.

    TOMLKit retains comments, table order, and unrelated values.  The
    temporary file is created beside the target so ``os.replace`` remains an
    atomic same-filesystem operation.
    """

    if not isinstance(model_ref, str) or not model_ref.strip():
        raise ValueError("model_ref must be a non-empty string")
    target = Path(path).expanduser().resolve(strict=False)
    original = target.read_text(encoding="utf-8")
    try:
        document = parse(original)
    except Exception:
        raise ValueError("user configuration is not valid TOML") from None

    document["model"] = model_ref
    rendered = dumps(document)
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(rendered)
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


__all__ = ["write_user_model"]
