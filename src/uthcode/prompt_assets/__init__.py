"""Versioned, editable Prompt assets owned by the package boundary.

The public coding prompt is deliberately kept out of Core's Python source.  A
wheel contains this module and its Markdown resource, so the same asset is
available from a source checkout and an installed package.
"""

from __future__ import annotations

from importlib import resources


_CODING_AGENT_ASSET = "coding_agent.md"


def read_public_coding_prompt() -> str:
    """Return the packaged public coding prompt as UTF-8 text."""

    content = resources.files(__package__).joinpath(_CODING_AGENT_ASSET).read_text(
        encoding="utf-8"
    )
    if not content.strip():  # pragma: no cover - protects a broken wheel.
        raise RuntimeError("public coding prompt asset is empty")
    return content.replace("\r\n", "\n").replace("\r", "\n").rstrip()


__all__ = ["read_public_coding_prompt"]
