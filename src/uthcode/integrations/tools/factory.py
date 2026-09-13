"""Composition helpers for the built-in Integration tools."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from uthcode.core.tool import Tool, ToolPlanningMetadata
from .file_tools import EditFileTool, ReadFileTool, WriteFileTool
from .image_tools import ViewImageTool
from .document_tools import ReadDocumentTool
from .process_tools import BashTool, ProcessTool
from .process_sessions import ProcessSessionManager
from .search_tools import GlobTool, GrepTool
from .patch_tools import ApplyPatchTool
from .git_tools import GitWorkspace, GitWorkspaceTool
from .workspace import FileReadTracker, WorkspacePathResolver
from .web_tools import FetchWebTool, TavilySearchTool


def create_default_tools(
    workdir: str | os.PathLike[str] | Path,
    *,
    on_path_access: Callable[[Path], object] | None = None,
    attachment_service: object | None = None,
    session_provider: Callable[[], object | None] | None = None,
    process_manager: ProcessSessionManager | None = None,
    search_configuration: Mapping[str, object] | object | None = None,
    tool_limits: Mapping[str, object] | object | None = None,
    web_transport: object | None = None,
    redirect_authorizer: Callable[[str], object] | None = None,
) -> tuple[Tool, ...]:
    """Create one isolated, ordered set of the built-in tools.

    The resolver and tracker are deliberately local to this call.  The three
    file tools share both objects, while each new Application receives a new
    pair and therefore cannot observe another Application's read state.  A
    formal Application composition also supplies Session attachments and a
    shared process manager, which enables the document, image, and Process
    tools.  Each returned tool classifies its trusted Action without executing
    it.
    """

    resolver = WorkspacePathResolver(workdir)
    tracker = FileReadTracker()
    manager = process_manager or ProcessSessionManager()
    web_max_bytes = _search_value(search_configuration, "max_fetch_bytes", 2 * 1024 * 1024)
    web_timeout = _search_value(search_configuration, "timeout_seconds", 20.0)
    tool_timeout = _search_value(tool_limits, "timeout_seconds", None)
    output_limit = int(_search_value(tool_limits, "output_bytes", 2 * 1024 * 1024))
    attachment_limit = int(
        _search_value(tool_limits, "attachment_bytes", 16 * 1024 * 1024)
    )

    def read_asset(session_id: str, ref: str) -> bytes:
        reader = getattr(attachment_service, "read", None)
        if not callable(reader):
            raise RuntimeError("attachment reader unavailable")
        return reader(session_id, ref)

    def asset_reference(session_id: str, ref: str) -> dict[str, object]:
        reference = getattr(attachment_service, "reference", None)
        if not callable(reference):
            raise RuntimeError("attachment metadata unavailable")
        value = reference(session_id, ref)
        to_dict = getattr(value, "to_dict", None)
        return dict(to_dict()) if callable(to_dict) else {
            "display_name": getattr(value, "display_name", ref),
            "asset_ref": getattr(value, "asset_ref", f"attachment:{session_id}:{ref}"),
        }

    def write_asset(display_name: str, content: bytes, mime_type: str, _source_ref: str) -> dict[str, object]:
        active = session_provider() if session_provider is not None else None
        session_id = getattr(active, "session_id", None)
        writer = getattr(attachment_service, "import_bytes", None)
        if not isinstance(session_id, str) or not callable(writer):
            raise RuntimeError("attachment Session is unavailable")
        value = writer(session_id, content, display_name=display_name, mime_type=mime_type)
        to_dict = getattr(value, "to_dict", None)
        if callable(to_dict):
            return dict(to_dict())
        return {
            "asset_ref": getattr(value, "asset_ref", ""),
            "display_name": getattr(value, "display_name", display_name),
        }

    base_tools: list[Tool] = [
        ReadFileTool(resolver, tracker, on_path_access=on_path_access),
        WriteFileTool(resolver, tracker, on_path_access=on_path_access),
        EditFileTool(resolver, tracker, on_path_access=on_path_access),
        GlobTool(resolver),
        GrepTool(resolver),
        BashTool(
            resolver.root,
            process_manager=manager,
            session_provider=session_provider,
            default_timeout_seconds=tool_timeout,
        ),
    ]
    # Existing embedders that request the historical six-tool factory without
    # a Session keep that stable shape.  The formal Application composition
    # always supplies its AttachmentService and receives the extended set.
    if attachment_service is not None or process_manager is not None:
        base_tools.extend(
            (
                ReadDocumentTool(
                    resolver,
                    asset_reader=read_asset if attachment_service is not None else None,
                    asset_reference=asset_reference if attachment_service is not None else None,
                    session_provider=session_provider,
                    on_path_access=on_path_access,
                    max_bytes=min(16 * 1024 * 1024, attachment_limit),
                ),
                ViewImageTool(
                    resolver,
                    asset_reader=read_asset if attachment_service is not None else None,
                    asset_reference=asset_reference if attachment_service is not None else None,
                    asset_writer=write_asset if attachment_service is not None else None,
                    session_provider=session_provider,
                    on_path_access=on_path_access,
                    max_bytes=min(16 * 1024 * 1024, attachment_limit),
                ),
                ProcessTool(manager, session_provider=session_provider),
                ApplyPatchTool(resolver, tracker, on_path_access=on_path_access),
                GitWorkspaceTool(
                    resolver.root,
                    workspace=GitWorkspace(
                        resolver.root,
                        max_output_bytes=output_limit,
                    ),
                ),
                FetchWebTool(
                    max_bytes=web_max_bytes,
                    timeout_seconds=web_timeout,
                    transport=web_transport,
                    redirect_authorizer=redirect_authorizer,
                    asset_writer=write_asset if attachment_service is not None else None,
                ),
            )
        )
        if search_configuration is not None:
            enabled = (
                search_configuration.get("enabled", False)
                if isinstance(search_configuration, Mapping)
                else getattr(search_configuration, "enabled", False)
            )
            key = (
                search_configuration.get("api_key")
                if isinstance(search_configuration, Mapping)
                else getattr(search_configuration, "api_key", None)
            )
            if enabled and key is not None:
                base_tools.append(
                    TavilySearchTool(
                        search_configuration,
                        transport=web_transport,
                    )
                )
    tools: Sequence[Tool] = tuple(base_tools)
    if not all(isinstance(tool, ToolPlanningMetadata) for tool in tools):
        raise TypeError("all built-in tools must declare planning_access")
    return tuple(tools)


__all__ = ["create_default_tools"]


def _search_value(configuration: object | None, name: str, default: object) -> object:
    if isinstance(configuration, Mapping):
        return configuration.get(name, default)
    if configuration is None:
        return default
    return getattr(configuration, name, default)
