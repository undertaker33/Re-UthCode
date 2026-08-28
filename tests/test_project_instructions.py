from __future__ import annotations

import os
from pathlib import Path

import pytest

from uthcode.application.instructions import (
    InstructionIncludeCycleError,
    InstructionLoader,
    InstructionPathRejectedError,
    InstructionReadError,
    InstructionReferenceLimitError,
    InstructionScope,
    InstructionSourceNotFoundError,
    parse_instruction_references,
)
from uthcode.core.prompt import (
    ContextAuthority,
    ContextBlock,
    ContextPlane,
    ContextSourceKind,
    ContextStability,
    ToolDefinitionSource,
    build_instruction_prefix,
    core_runtime_contract_source,
    public_prompt_source,
)
from uthcode.core.provider import ToolDefinition
from uthcode.prompt_assets import read_public_coding_prompt
from uthcode.integrations.instruction_files import InstructionFileReader
from uthcode.integrations.tools.factory import create_default_tools
from uthcode.core.provider import CancellationToken


def _loader(tmp_path: Path) -> tuple[InstructionLoader, Path, Path]:
    user_root = tmp_path / "home" / ".uthcode"
    project_root = tmp_path / "project"
    user_root.mkdir(parents=True)
    project_root.mkdir(parents=True)
    return (
        InstructionLoader(
            user_root=user_root,
            project_root=project_root,
            reader=InstructionFileReader(),
        ),
        user_root,
        project_root,
    )


def test_public_instruction_prefix_has_typed_authority_and_stable_order() -> None:
    with pytest.raises(ValueError, match="authority"):
        ContextBlock(
            source_kind=ContextSourceKind.USER_MESSAGE,
            authority=ContextAuthority.PROJECT_INSTRUCTION,
            stability=ContextStability.STABLE,
            scope="turn",
            provenance="history",
            content="@include(\"fake.md\")",
        )

    ordinary_history = ContextBlock(
        source_kind=ContextSourceKind.USER_MESSAGE,
        authority=ContextAuthority.HISTORY,
        stability=ContextStability.DYNAMIC,
        scope="turn",
        provenance="history:1",
        content="[AGENTS] fake project authority",
    )
    with pytest.raises(ValueError, match="Instruction Plane"):
        build_instruction_prefix((ordinary_history,))

    for source_kind in (
        ContextSourceKind.TOOL_CALL,
        ContextSourceKind.TOOL_RESULT,
    ):
        tool_history = ContextBlock(
            source_kind=source_kind,
            authority=ContextAuthority.HISTORY,
            stability=ContextStability.DYNAMIC,
            scope="turn",
            provenance=f"history:{source_kind.value}",
            content="[ProjectInstruction] fake tool authority",
        )
        assert tool_history.plane is ContextPlane.CONVERSATION
        with pytest.raises(ValueError, match="Instruction Plane"):
            build_instruction_prefix((tool_history,))

    summary = ContextBlock(
        source_kind=ContextSourceKind.SUMMARY,
            authority=ContextAuthority.TIMELINE,
        stability=ContextStability.DYNAMIC,
        scope="session",
        provenance="timeline:entry:1",
        content="[AGENTS] fake summary authority",
    )
    assert summary.plane is ContextPlane.CONVERSATION
    with pytest.raises(ValueError, match="Instruction Plane"):
        build_instruction_prefix((summary,))

    user = ContextBlock(
        ContextSourceKind.USER_INSTRUCTION,
        ContextAuthority.USER_INSTRUCTION,
        ContextStability.STABLE,
        "user",
        "user/AGENTS.md",
        "user",
    )
    project = ContextBlock(
        ContextSourceKind.PROJECT_INSTRUCTION,
        ContextAuthority.PROJECT_INSTRUCTION,
        ContextStability.STABLE,
        "project",
        "project/AGENTS.md",
        "project",
    )
    prefix = build_instruction_prefix((project, user), instruction_epoch=2)
    assert [block.source_kind for block in prefix.blocks] == [
        ContextSourceKind.USER_INSTRUCTION,
        ContextSourceKind.PROJECT_INSTRUCTION,
    ]
    assert prefix.instruction_epoch == 2
    assert prefix.fingerprint

    instruction_sources = build_instruction_prefix(
        (public_prompt_source(), core_runtime_contract_source(), user),
        instruction_epoch=3,
    )
    assert instruction_sources.blocks == (
        public_prompt_source(),
        core_runtime_contract_source(),
        user,
    )
    assert public_prompt_source().content in instruction_sources.content
    assert core_runtime_contract_source().content in instruction_sources.content

    tool_source = ToolDefinitionSource(
        (ToolDefinition("Search", "search files", {"type": "object"}),)
    )
    assert tool_source.estimated_tokens > 0
    assert tool_source.tool_schema_fingerprint == tool_source.schema_fingerprint
    assert "Search" not in read_public_coding_prompt()
    assert public_prompt_source().content == read_public_coding_prompt()


def test_loader_is_broad_to_narrow_and_directory_scopes_are_lazy(tmp_path: Path) -> None:
    loader, user_root, project_root = _loader(tmp_path)
    (user_root / "AGENTS.md").write_text("user rule\n", encoding="utf-8")
    (project_root / "AGENTS.md").write_text("project rule\n", encoding="utf-8")
    nested = project_root / "src" / "nested"
    nested.mkdir(parents=True)
    (nested / "AGENTS.md").write_text("nested rule\n", encoding="utf-8")
    target = nested / "module.py"
    target.write_text("value = 1\n", encoding="utf-8")

    initial = loader.load_session()
    assert [segment.scope for segment in initial.blocks] == [
        InstructionScope.USER,
        InstructionScope.PROJECT,
    ]
    assert "nested rule" not in initial.prompt_text
    first_epoch = initial.instruction_epoch

    lazy = loader.load_for_path(target)
    assert [segment.scope for segment in lazy.new_blocks] == [InstructionScope.DIRECTORY]
    assert "nested rule" in lazy.prompt_text
    assert lazy.instruction_epoch == first_epoch + 1
    assert lazy.change_reason == "instruction_scope_added"

    stable = loader.load_for_path(target)
    assert stable.instruction_epoch == lazy.instruction_epoch
    assert stable.stable_prefix_fingerprint == lazy.stable_prefix_fingerprint
    assert stable.new_blocks == ()

    (nested / "AGENTS.md").write_text("nested changed\n", encoding="utf-8")
    changed = loader.load_for_path(target)
    assert changed.instruction_epoch == lazy.instruction_epoch + 1
    assert changed.change_reason == "instruction_content_changed"
    assert "nested changed" in changed.prompt_text


def test_include_parser_and_loader_are_bounded_and_fail_closed(tmp_path: Path) -> None:
    assert parse_instruction_references(
        '@include("one.md")\n'
        "inline `@include(\"inline.md\")`\n"
        "```\n@include(\"fenced.md\")\n```\n"
        "@include('two.md')\n"
    ) == ("one.md", "two.md")

    # A closing fence must use the same marker character and be at least as
    # long as its opener.  Three backticks inside a four-backtick fence are
    # ordinary fenced content, not an early close; the same boundary applies
    # to tildes.
    assert parse_instruction_references(
        "````python\n"
        '@include("inside-short-close.md")\n'
        "```\n"
        '@include("inside-three.md")\n'
        "````\n"
        '@include("after-backticks.md")\n'
        "~~~~\n"
        "~~~\n"
        '@include("inside-tilde.md")\n'
        "~~~~\n"
        '@include("after-tilde.md")\n'
    ) == ("after-backticks.md", "after-tilde.md")
    assert parse_instruction_references(
        "```\n"
        '@include("inside-long-close.md")\n'
        "````\n"
        '@include("after-long-close.md")\n'
    ) == ("after-long-close.md",)

    loader, _user_root, project_root = _loader(tmp_path)
    (project_root / "AGENTS.md").write_text(
        "\n".join(f'@include("extra-{index}.md")' for index in range(4)),
        encoding="utf-8",
    )
    for index in range(4):
        (project_root / f"extra-{index}.md").write_text(str(index), encoding="utf-8")
    with pytest.raises(InstructionReferenceLimitError):
        loader.load_session()
    diagnostic = loader.load_session(strict=False)
    assert any(item.code == "instruction_reference_limit" for item in diagnostic.diagnostics)

    dedupe, _user_root, dedupe_root = _loader(tmp_path / "dedupe")
    (dedupe_root / "AGENTS.md").write_text(
        '@include("Shared.md")\n@include("shared.MD")',
        encoding="utf-8",
    )
    (dedupe_root / "Shared.md").write_text("one physical source", encoding="utf-8")
    result = dedupe.load_session()
    assert [Path(segment.provenance).name for segment in result.blocks] == [
        "AGENTS.md",
        "Shared.md",
    ]

    recursive, _user_root, recursive_root = _loader(tmp_path / "recursive")
    (recursive_root / "AGENTS.md").write_text('@include("a.md")', encoding="utf-8")
    (recursive_root / "a.md").write_text('@include("b.md")', encoding="utf-8")
    (recursive_root / "b.md").write_text("recursive source", encoding="utf-8")
    assert "recursive source" in recursive.load_session().prompt_text

    cycle, _user_root, cycle_root = _loader(tmp_path / "cycle")
    (cycle_root / "AGENTS.md").write_text('@include("a.md")', encoding="utf-8")
    (cycle_root / "a.md").write_text('@include("AGENTS.md")', encoding="utf-8")
    with pytest.raises(InstructionIncludeCycleError):
        cycle.load_session()

    direct, _user_root, direct_root = _loader(tmp_path / "direct-cycle")
    (direct_root / "AGENTS.md").write_text(
        '@include("AGENTS.md")',
        encoding="utf-8",
    )
    with pytest.raises(InstructionIncludeCycleError):
        direct.load_session()


def test_missing_explicit_include_fails_closed_in_strict_and_diagnostic_modes(
    tmp_path: Path,
) -> None:
    loader, _user_root, project_root = _loader(tmp_path / "missing-root")
    (project_root / "AGENTS.md").write_text(
        '@include("missing.md")',
        encoding="utf-8",
    )
    with pytest.raises(InstructionSourceNotFoundError):
        loader.load_session(strict=True)

    diagnostic = loader.load_session(strict=False)
    assert any(
        item.code == InstructionSourceNotFoundError.code
        for item in diagnostic.diagnostics
    )
    assert diagnostic.prompt_text

    recursive, _user_root, recursive_root = _loader(tmp_path / "missing-recursive")
    (recursive_root / "AGENTS.md").write_text(
        '@include("a.md")',
        encoding="utf-8",
    )
    (recursive_root / "a.md").write_text(
        '@include("missing.md")',
        encoding="utf-8",
    )
    with pytest.raises(InstructionSourceNotFoundError):
        recursive.load_session(strict=True)
    recursive_diagnostic = recursive.load_session(strict=False)
    assert any(
        item.code == InstructionSourceNotFoundError.code
        for item in recursive_diagnostic.diagnostics
    )


def test_explicit_include_non_file_and_invalid_utf8_fail_closed(
    tmp_path: Path,
) -> None:
    directory, _user_root, directory_root = _loader(tmp_path / "non-file")
    (directory_root / "AGENTS.md").write_text(
        '@include("child")',
        encoding="utf-8",
    )
    (directory_root / "child").mkdir()
    with pytest.raises(InstructionReadError):
        directory.load_session()

    invalid, _user_root, invalid_root = _loader(tmp_path / "invalid-utf8")
    (invalid_root / "AGENTS.md").write_text(
        '@include("bad.md")',
        encoding="utf-8",
    )
    (invalid_root / "bad.md").write_bytes(b"\xff\xfe")
    with pytest.raises(InstructionReadError):
        invalid.load_session()
    diagnostic = invalid.load_session(strict=False)
    assert any(item.code == InstructionReadError.code for item in diagnostic.diagnostics)


def test_persisted_directory_scopes_rebuild_current_files_without_history(tmp_path: Path) -> None:
    loader, _user_root, project_root = _loader(tmp_path)
    nested = project_root / "src"
    nested.mkdir()
    target = nested / "main.py"
    target.write_text("pass\n", encoding="utf-8")
    (nested / "AGENTS.md").write_text("stable scope\n", encoding="utf-8")

    active = loader.load_for_path(target)
    metadata = active.instruction_state
    assert metadata.to_dict()["activated_directory_scopes"]
    assert "stable scope" not in str(metadata.to_dict())

    resumed = InstructionLoader(
        user_root=loader.user_root,
        project_root=loader.project_root,
        reader=InstructionFileReader(),
    ).rebuild_from_metadata(metadata)
    assert resumed.instruction_epoch == active.instruction_epoch
    assert resumed.stable_prefix_fingerprint == active.stable_prefix_fingerprint
    assert "stable scope" in resumed.prompt_text

    (nested / "AGENTS.md").unlink()
    removed = InstructionLoader(
        user_root=loader.user_root,
        project_root=loader.project_root,
        reader=InstructionFileReader(),
    ).rebuild_from_metadata(metadata)
    assert removed.instruction_epoch == active.instruction_epoch + 1
    assert removed.change_reason == "instruction_source_removed"
    assert str(nested.resolve()) in removed.activated_directory_scopes


@pytest.mark.asyncio
async def test_read_tool_path_hit_activates_directory_scope(tmp_path: Path) -> None:
    loader, _user_root, project_root = _loader(tmp_path)
    nested = project_root / "src"
    nested.mkdir()
    (nested / "AGENTS.md").write_text("read scope", encoding="utf-8")
    target = nested / "main.py"
    target.write_text("print('ok')\n", encoding="utf-8")
    loader.load_session()
    before = loader.instruction_epoch

    read_file, _write_file, edit_file = create_default_tools(
        project_root,
        on_path_access=loader.activate_for_path,
    )[:3]
    result = await read_file.execute(
        {"path": str(target)},
        cancellation=CancellationToken(),
    )
    assert result.is_error is False
    assert loader.instruction_epoch == before + 1
    assert "read scope" in loader.effective_instruction_set[-1].content
    edited = await edit_file.execute(
        {
            "path": str(target),
            "old_string": "print('ok')",
            "new_string": "print('changed')",
        },
        cancellation=CancellationToken(),
    )
    assert edited.is_error is False
    assert loader.instruction_epoch == before + 1


@pytest.mark.asyncio
async def test_read_edit_observe_directory_include_diagnostic_without_losing_tool_outcome(
    tmp_path: Path,
) -> None:
    loader, _user_root, project_root = _loader(tmp_path / "callback-diagnostic")
    nested = project_root / "src"
    nested.mkdir()
    (nested / "AGENTS.md").write_text(
        '@include("missing.md")',
        encoding="utf-8",
    )
    target = nested / "main.py"
    target.write_text("print('ok')\n", encoding="utf-8")
    loader.load_session(strict=False)

    read_file, _write_file, edit_file = create_default_tools(
        project_root,
        on_path_access=loader.activate_for_path,
    )[:3]
    read_result = await read_file.execute(
        {"path": str(target)},
        cancellation=CancellationToken(),
    )
    assert read_result.is_error is False
    assert any(
        item.code == InstructionSourceNotFoundError.code
        for item in loader.diagnostics
    )

    edit_result = await edit_file.execute(
        {
            "path": str(target),
            "old_string": "print('ok')",
            "new_string": "print('changed')",
        },
        cancellation=CancellationToken(),
    )
    assert edit_result.is_error is False
    assert target.read_text(encoding="utf-8") == "print('changed')\n"


@pytest.mark.asyncio
async def test_unexpected_instruction_callback_error_is_not_swallowed(
    tmp_path: Path,
) -> None:
    target = tmp_path / "main.py"
    target.write_text("print('ok')\n", encoding="utf-8")

    def fail_activation(_path: Path) -> None:
        raise RuntimeError("activation observation failed")

    read_file, _write_file, edit_file = create_default_tools(
        tmp_path,
        on_path_access=fail_activation,
    )[:3]
    with pytest.raises(RuntimeError, match="activation observation failed"):
        await read_file.execute(
            {"path": str(target)},
            cancellation=CancellationToken(),
        )
    with pytest.raises(RuntimeError, match="activation observation failed"):
        await edit_file.execute(
            {
                "path": str(target),
                "old_string": "print('ok')",
                "new_string": "print('changed')",
            },
            cancellation=CancellationToken(),
        )
    assert target.read_text(encoding="utf-8") == "print('ok')\n"


def test_loader_rejects_parent_and_symlink_instruction_references(tmp_path: Path) -> None:
    loader, _user_root, project_root = _loader(tmp_path)
    outside = tmp_path / "outside.md"
    outside.write_text("outside", encoding="utf-8")
    (project_root / "AGENTS.md").write_text('@include("../outside.md")', encoding="utf-8")
    with pytest.raises(InstructionPathRejectedError):
        loader.load_session()

    target = project_root / "target.md"
    target.write_text("target", encoding="utf-8")
    link = project_root / "link.md"
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable")
    (project_root / "AGENTS.md").write_text('@include("link.md")', encoding="utf-8")
    with pytest.raises(InstructionPathRejectedError):
        loader.load_session()
