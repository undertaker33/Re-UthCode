"""Composition helpers for the built-in Integration tools."""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path

from uthcode.core.tool import Tool

from .file_tools import EditFileTool, ReadFileTool, WriteFileTool
from .process_tools import BashTool
from .search_tools import GlobTool, GrepTool
from .workspace import FileReadTracker, WorkspacePathResolver


def create_default_tools(
    workdir: str | os.PathLike[str] | Path,
) -> tuple[Tool, ...]:
    """Create one isolated, ordered set of the six built-in tools.

    The resolver and tracker are deliberately local to this call.  The three
    file tools share both objects, while each new Application receives a new
    pair and therefore cannot observe another Application's read state.
    """

    resolver = WorkspacePathResolver(workdir)
    tracker = FileReadTracker()
    tools: Sequence[Tool] = (
        ReadFileTool(resolver, tracker),
        WriteFileTool(resolver, tracker),
        EditFileTool(resolver, tracker),
        GlobTool(resolver),
        GrepTool(resolver),
        BashTool(resolver.root),
    )
    return tuple(tools)


__all__ = ["create_default_tools"]
