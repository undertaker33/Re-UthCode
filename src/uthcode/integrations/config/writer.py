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


def _write_user_preference(
    path: str | os.PathLike[str],
    field: str,
    value: str,
) -> Path:
    """Atomically update one validated root user preference.

    TOMLKit retains comments, table order, and unrelated values.  The
    temporary file is created beside the target so ``os.replace`` remains an
    atomic same-filesystem operation.
    """

    if field == "model":
        if not isinstance(value, str) or not value.strip():
            raise ValueError("model_ref must be a non-empty string")
    elif field == "default_permission_mode":
        if value not in {"default", "auto"}:
            raise ValueError("default_permission_mode must be default or auto")
    else:  # pragma: no cover
        raise ValueError("unsupported user preference")
    target = Path(path).expanduser().resolve(strict=False)
    original = target.read_text(encoding="utf-8")
    try:
        document = parse(original)
    except Exception:
        raise ValueError("user configuration is not valid TOML") from None

    document[field] = value
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


def write_user_model(path: str | os.PathLike[str], model_ref: str) -> Path:
    """Atomically update only the root ``model`` value of a user file."""

    return _write_user_preference(path, "model", model_ref)


def write_user_default_permission_mode(
    path: str | os.PathLike[str], mode: str
) -> Path:
    """Atomically update only the safe root permission default."""

    return _write_user_preference(path, "default_permission_mode", mode)


__all__ = ["write_user_default_permission_mode", "write_user_model"]
