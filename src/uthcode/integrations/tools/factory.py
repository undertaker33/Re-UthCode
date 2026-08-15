"""Composition helpers for the built-in Integration tools."""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from pathlib import Path

from uthcode.core.tool import Tool, ToolPlanningMetadata

from .file_tools import EditFileTool, ReadFileTool, WriteFileTool
from .process_tools import BashTool
from .search_tools import GlobTool, GrepTool
from .workspace import FileReadTracker, WorkspacePathResolver


def create_default_tools(
    workdir: str | os.PathLike[str] | Path,
    *,
    on_path_access: Callable[[Path], object] | None = None,
) -> tuple[Tool, ...]:
    """Create one isolated, ordered set of the six preflightable built-in tools.

    The resolver and tracker are deliberately local to this call.  The three
    file tools share both objects, while each new Application receives a new
    pair and therefore cannot observe another Application's read state.  Each
    returned tool classifies its trusted Action without executing it.
    """

    resolver = WorkspacePathResolver(workdir)
    tracker = FileReadTracker()
    tools: Sequence[Tool] = (
        ReadFileTool(resolver, tracker, on_path_access=on_path_access),
        WriteFileTool(resolver, tracker, on_path_access=on_path_access),
        EditFileTool(resolver, tracker, on_path_access=on_path_access),
        GlobTool(resolver),
        GrepTool(resolver),
        BashTool(resolver.root),
    )
    if not all(isinstance(tool, ToolPlanningMetadata) for tool in tools):
        raise TypeError("all built-in tools must declare planning_access")
    return tuple(tools)


__all__ = ["create_default_tools"]
