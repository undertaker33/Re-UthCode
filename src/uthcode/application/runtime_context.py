"""Stable runtime facts owned by one Application instance."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from os import PathLike
from pathlib import Path
import platform


def _require_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


@dataclass(frozen=True, slots=True)
class ApplicationRuntimeContext:
    """Immutable environment facts captured when an Application is created."""

    workdir: Path
    platform_name: str
    platform_release: str
    current_date: str

    def __post_init__(self) -> None:
        workdir = Path(self.workdir).expanduser().resolve(strict=False)
        object.__setattr__(self, "workdir", workdir)
        _require_text(self.platform_name, "platform_name")
        _require_text(self.platform_release, "platform_release")
        _require_text(self.current_date, "current_date")

    @classmethod
    def from_system(
        cls,
        workdir: str | PathLike[str] | None = None,
        *,
        platform_name: str | None = None,
        platform_release: str | None = None,
        current_date: str | None = None,
    ) -> ApplicationRuntimeContext:
        """Capture one normalized workdir and a stable set of system values."""

        return cls(
            workdir=Path.cwd() if workdir is None else Path(workdir),
            platform_name=(
                platform.system() if platform_name is None else platform_name
            ),
            platform_release=(
                platform.release()
                if platform_release is None
                else platform_release
            ),
            current_date=(
                date.today().isoformat()
                if current_date is None
                else current_date
            ),
        )


__all__ = ["ApplicationRuntimeContext"]
