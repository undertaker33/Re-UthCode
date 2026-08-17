"""Application policy for user, project, and lazy directory instructions."""

from __future__ import annotations

import hashlib
import importlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

from uthcode.core.prompt import (
    ContextAuthority,
    ContextBlock,
    ContextScope,
    ContextSourceKind,
    ContextStability,
    ProjectInstructionSource,
    build_instruction_prefix,
    core_runtime_contract_source,
    public_prompt_source,
)


class InstructionScope(str, Enum):
    USER = "user"
    PROJECT = "project"
    DIRECTORY = "directory"


class InstructionError(RuntimeError):
    """Base error for strict instruction loading."""

    code = "instruction_error"

    def __init__(self, message: str = "") -> None:
        self.detail = message
        suffix = f": {message}" if message else ""
        super().__init__(f"{self.code}{suffix}")


class InstructionPathRejectedError(InstructionError):
    code = "instruction_path_rejected"


class InstructionReferenceLimitError(InstructionError):
    code = "instruction_reference_limit"


class InstructionIncludeCycleError(InstructionError):
    code = "instruction_include_cycle"


class InstructionReadError(InstructionError):
    code = "instruction_read_failed"


class InstructionSourceNotFoundError(InstructionError):
    code = "instruction_source_not_found"


class InstructionAuthorizationError(PermissionError, InstructionError):
    code = "instruction_authorization_required"

    def __init__(self, message: str = "") -> None:
        self.detail = message
        suffix = f": {message}" if message else ""
        PermissionError.__init__(self, f"{self.code}{suffix}")


class InstructionFileReader(Protocol):
    """Minimal Integration adapter required by the Application policy."""

    def canonical_path(
        self,
        path: str | Path,
        *,
        trusted_root: str | Path | None = None,
        base_dir: str | Path | None = None,
        relative_only: bool = False,
    ) -> Path:
        ...

    def identity(self, path: str | Path) -> str:
        ...

    def read(self, path: str | Path, *, trusted_root: str | Path | None = None) -> Any:
        ...

    def exists(self, path: str | Path, *, trusted_root: str | Path | None = None) -> bool:
        ...


_INCLUDE_RE = re.compile(
    r'^\s*@include\(\s*(?:"(?P<double>[^"\r\n]+)"|\'(?P<single>[^\'\r\n]+)\')\s*\)\s*$'
)
_FENCE_RE = re.compile(r"^\s*(?P<marker>`{3,}|~{3,})")


def parse_instruction_references(content: str) -> tuple[str, ...]:
    """Parse only full-line, quoted ``@include`` directives.

    Inline code and fenced Markdown examples are ordinary instruction text.
    The parser intentionally does not recognize a bare ``@file`` syntax.
    """

    if not isinstance(content, str):
        raise TypeError("instruction content must be a string")
    references: list[str] = []
    in_fence = False
    fence_character = ""
    for line in content.splitlines():
        fence = _FENCE_RE.match(line)
        if fence is not None:
            marker = fence.group("marker")
            if not in_fence:
                in_fence = True
                fence_character = marker[0]
            elif marker[0] == fence_character:
                in_fence = False
                fence_character = ""
            continue
        if in_fence:
            continue
        match = _INCLUDE_RE.match(line)
        if match is not None:
            references.append(match.group("double") or match.group("single"))
    return tuple(references)


@dataclass(frozen=True, slots=True)
class InstructionBlock:
    """One source block with inspection and provenance fields."""

    source_path: Path
    scope: InstructionScope | str
    load_order: int
    reason: str
    content: str
    identity: str
    content_fingerprint: str

    def __post_init__(self) -> None:
        if not isinstance(self.source_path, Path):
            object.__setattr__(self, "source_path", Path(self.source_path))
        scope = self.scope
        if not isinstance(scope, InstructionScope):
            try:
                scope = InstructionScope(scope)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"unknown instruction scope: {self.scope!r}") from exc
            object.__setattr__(self, "scope", scope)
        if isinstance(self.load_order, bool) or not isinstance(self.load_order, int) or self.load_order < 1:
            raise ValueError("load_order must be a positive integer")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("reason must be a non-empty string")
        if not isinstance(self.content, str):
            raise TypeError("content must be a string")
        for name in ("identity", "content_fingerprint"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name):
                raise ValueError(f"{name} must be a non-empty string")

    @property
    def source_kind(self) -> ContextSourceKind:
        return {
            InstructionScope.USER: ContextSourceKind.USER_INSTRUCTION,
            InstructionScope.PROJECT: ContextSourceKind.PROJECT_INSTRUCTION,
            InstructionScope.DIRECTORY: ContextSourceKind.DIRECTORY_INSTRUCTION,
        }[InstructionScope(self.scope)]

    @property
    def authority(self) -> ContextAuthority:
        return {
            InstructionScope.USER: ContextAuthority.USER_INSTRUCTION,
            InstructionScope.PROJECT: ContextAuthority.PROJECT_INSTRUCTION,
            InstructionScope.DIRECTORY: ContextAuthority.DIRECTORY_INSTRUCTION,
        }[InstructionScope(self.scope)]

    def to_context_block(self) -> ContextBlock:
        return ContextBlock(
            source_kind=self.source_kind,
            authority=self.authority,
            stability=ContextStability.STABLE,
            scope=self.scope,
            provenance=str(self.source_path),
            content=self.content,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "source_path": str(self.source_path),
            "scope": InstructionScope(self.scope).value,
            "load_order": self.load_order,
            "reason": self.reason,
            "content": self.content,
            "identity": self.identity,
            "content_fingerprint": self.content_fingerprint,
        }

@dataclass(frozen=True, slots=True)
class InstructionDiagnostic:
    code: str
    source_path: Path
    scope: InstructionScope | str
    message: str

    def __post_init__(self) -> None:
        if not isinstance(self.source_path, Path):
            object.__setattr__(self, "source_path", Path(self.source_path))
        if not isinstance(self.scope, InstructionScope):
            object.__setattr__(self, "scope", InstructionScope(self.scope))
        if not isinstance(self.code, str) or not self.code.strip():
            raise ValueError("diagnostic code must be a non-empty string")
        if not isinstance(self.message, str) or not self.message.strip():
            raise ValueError("diagnostic message must be a non-empty string")

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "source_path": str(self.source_path),
            "scope": InstructionScope(self.scope).value,
            "message": self.message,
        }


@dataclass(frozen=True, slots=True)
class InstructionStateMetadata:
    """Persistable Instruction State; it never contains AGENTS正文."""

    activated_directory_scopes: tuple[str, ...] = ()
    instruction_epoch: int = 0
    stable_prefix_fingerprint: str = ""
    source_fingerprints: tuple[tuple[str, str, str, str], ...] = ()
    change_reason: str = "initial"

    def __post_init__(self) -> None:
        scopes = tuple(str(Path(scope).resolve(strict=False)) for scope in self.activated_directory_scopes)
        fingerprints = tuple(tuple(str(value) for value in item) for item in self.source_fingerprints)
        if isinstance(self.instruction_epoch, bool) or not isinstance(self.instruction_epoch, int) or self.instruction_epoch < 0:
            raise ValueError("instruction_epoch must be a non-negative integer")
        if not isinstance(self.stable_prefix_fingerprint, str):
            raise TypeError("stable_prefix_fingerprint must be a string")
        if not isinstance(self.change_reason, str) or not self.change_reason.strip():
            raise ValueError("change_reason must be a non-empty string")
        object.__setattr__(self, "activated_directory_scopes", scopes)
        object.__setattr__(self, "source_fingerprints", fingerprints)

    def to_dict(self) -> dict[str, object]:
        return {
            "activated_directory_scopes": list(self.activated_directory_scopes),
            "instruction_epoch": self.instruction_epoch,
            "stable_prefix_fingerprint": self.stable_prefix_fingerprint,
            "source_fingerprints": [list(item) for item in self.source_fingerprints],
            "change_reason": self.change_reason,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "InstructionStateMetadata":
        if not isinstance(value, Mapping):
            raise TypeError("instruction state metadata must be a mapping")
        raw_sources = value.get("source_fingerprints", ())
        if not isinstance(raw_sources, Sequence) or isinstance(raw_sources, (str, bytes, bytearray)):
            raise TypeError("source_fingerprints must be a sequence")
        sources: list[tuple[str, str, str, str]] = []
        for item in raw_sources:
            if not isinstance(item, Sequence) or isinstance(item, (str, bytes, bytearray)) or len(item) != 4:
                raise ValueError("each source fingerprint must contain four values")
            sources.append(tuple(str(part) for part in item))  # type: ignore[arg-type]
        raw_scopes = value.get("activated_directory_scopes", ())
        if not isinstance(raw_scopes, Sequence) or isinstance(raw_scopes, (str, bytes, bytearray)):
            raise TypeError("activated_directory_scopes must be a sequence")
        return cls(
            activated_directory_scopes=tuple(str(item) for item in raw_scopes),
            instruction_epoch=value.get("instruction_epoch", 0),  # type: ignore[arg-type]
            stable_prefix_fingerprint=str(value.get("stable_prefix_fingerprint", "")),
            source_fingerprints=tuple(sources),
            change_reason=str(value.get("change_reason", "resume")),
        )


@dataclass(frozen=True, slots=True)
class InstructionLoadResult:
    blocks: tuple[ContextBlock, ...]
    new_blocks: tuple[ContextBlock, ...]
    diagnostics: tuple[InstructionDiagnostic, ...]
    new_diagnostics: tuple[InstructionDiagnostic, ...]
    instruction_state: InstructionStateMetadata
    effective_instruction_set: tuple[ContextBlock, ...]
    instruction_epoch: int
    stable_prefix_fingerprint: str
    change_reason: str
    prompt_text: str
    new_prompt_text: str

    @property
    def activated_directory_scopes(self) -> tuple[str, ...]:
        return self.instruction_state.activated_directory_scopes

    @property
    def project_instruction_source(self) -> ProjectInstructionSource:
        """Expose the loader result through the named Context Source contract."""

        return ProjectInstructionSource(
            effective_instruction_set=self.effective_instruction_set,
            instruction_epoch=self.instruction_epoch,
            stable_prefix_fingerprint=self.stable_prefix_fingerprint,
            change_reason=self.change_reason,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "blocks": [block.to_dict() for block in self.blocks],
            "diagnostics": [item.to_dict() for item in self.diagnostics],
            "instruction_state": self.instruction_state.to_dict(),
            "instruction_epoch": self.instruction_epoch,
            "stable_prefix_fingerprint": self.stable_prefix_fingerprint,
            "change_reason": self.change_reason,
        }


@dataclass(slots=True)
class _LoadGraph:
    loaded: dict[str, InstructionBlock] = field(default_factory=dict)
    diagnostics: list[InstructionDiagnostic] = field(default_factory=list)
    references: set[str] = field(default_factory=set)
    reference_count: int = 0


class InstructionLoader:
    """Load the current effective instruction set with lazy directory scopes."""

    def __init__(
        self,
        *,
        user_root: str | Path | None = None,
        project_root: str | Path | None = None,
        reader: InstructionFileReader | None = None,
        max_reference_files: int = 3,
        agents_filename: str = "AGENTS.md",
    ) -> None:
        if isinstance(max_reference_files, bool) or not isinstance(max_reference_files, int) or max_reference_files <= 0:
            raise ValueError("max_reference_files must be positive")
        if not isinstance(agents_filename, str) or not agents_filename.strip():
            raise ValueError("agents_filename must be a non-empty string")
        if user_root is None:
            raise TypeError("user_root is required")
        if project_root is None:
            raise TypeError("project_root is required")
        self.user_root = Path(user_root).expanduser().resolve(strict=False)
        self.project_root = Path(project_root).expanduser().resolve(strict=False)
        self.max_reference_files = max_reference_files
        self.agents_filename = agents_filename
        self._reader = reader or _default_reader()
        self._session_loaded = False
        self._activated_directories: set[Path] = set()
        self._blocks: tuple[ContextBlock, ...] = ()
        self._diagnostics: tuple[InstructionDiagnostic, ...] = ()
        self._source_fingerprints: tuple[tuple[str, str, str, str], ...] = ()
        self._instruction_epoch = 0
        self._stable_prefix_fingerprint = ""
        self._change_reason = "initial"

    def fork_for_session(self) -> "InstructionLoader":
        """Create an independent loader for a staged Session transition.

        Session switching must be able to rebuild the target Instruction State
        while the current Session is still active.  A fork shares only the
        read-only file reader and configuration roots; all loaded state belongs
        to the returned loader.
        """

        return type(self)(
            user_root=self.user_root,
            project_root=self.project_root,
            reader=self._reader,
            max_reference_files=self.max_reference_files,
            agents_filename=self.agents_filename,
        )

    def adopt_session_state(self, other: "InstructionLoader") -> None:
        """Commit another loader's already-validated state into this loader."""

        if not isinstance(other, InstructionLoader):
            raise TypeError("other must be an InstructionLoader")
        if self.user_root != other.user_root or self.project_root != other.project_root:
            raise ValueError("InstructionLoader roots must match")
        self._session_loaded = other._session_loaded
        self._activated_directories = set(other._activated_directories)
        self._blocks = other._blocks
        self._diagnostics = other._diagnostics
        self._source_fingerprints = other._source_fingerprints
        self._instruction_epoch = other._instruction_epoch
        self._stable_prefix_fingerprint = other._stable_prefix_fingerprint
        self._change_reason = other._change_reason

    @property
    def blocks(self) -> tuple[ContextBlock, ...]:
        return self._blocks

    @property
    def effective_instruction_set(self) -> tuple[ContextBlock, ...]:
        return self._blocks

    @property
    def diagnostics(self) -> tuple[InstructionDiagnostic, ...]:
        return self._diagnostics

    @property
    def instruction_epoch(self) -> int:
        return self._instruction_epoch

    @property
    def stable_prefix_fingerprint(self) -> str:
        return self._stable_prefix_fingerprint

    @property
    def change_reason(self) -> str:
        return self._change_reason

    @property
    def activated_directory_scopes(self) -> tuple[str, ...]:
        return tuple(str(path) for path in sorted(self._activated_directories, key=str))

    @property
    def instruction_state(self) -> InstructionStateMetadata:
        return InstructionStateMetadata(
            activated_directory_scopes=self.activated_directory_scopes,
            instruction_epoch=self._instruction_epoch,
            stable_prefix_fingerprint=self._stable_prefix_fingerprint,
            source_fingerprints=self._source_fingerprints,
            change_reason=self._change_reason,
        )

    def load_session(self, *, strict: bool = True) -> InstructionLoadResult:
        """Load user and project roots; directory scopes remain lazy."""

        self._session_loaded = True
        return self._rebuild(strict=strict, new_scope=False)

    def reset_for_new_session(self) -> None:
        """Clear only per-Session activated directory Instruction State.

        User/project files remain the current filesystem sources and are loaded
        again by ``load_session``.  This is used by Application ``/new``
        composition so a new Session does not inherit directory scopes from a
        previous Session in the same process.
        """

        self._session_loaded = False
        self._activated_directories = set()
        self._blocks = ()
        self._diagnostics = ()
        self._source_fingerprints = ()
        self._instruction_epoch = 0
        self._stable_prefix_fingerprint = ""
        self._change_reason = "initial"

    def load_for_path(
        self,
        target_path: str | Path,
        *,
        strict: bool = True,
    ) -> InstructionLoadResult:
        """Activate the project-root-to-target directory scope chain."""

        if not self._session_loaded:
            self.load_session(strict=strict)
        target = self._project_target(target_path, strict=strict)
        directory = target if target.is_dir() else target.parent
        relative = self._relative_to_project(directory, strict=strict)
        previous = set(self._activated_directories)
        current = self.project_root
        for part in relative.parts:
            current = current / part
            self._activated_directories.add(current)
        added = self._activated_directories != previous
        return self._rebuild(strict=strict, new_scope=added)

    def activate_for_path(
        self,
        target_path: str | Path,
        *,
        strict: bool = False,
    ) -> InstructionLoadResult:
        """Tool callback spelling for lazy Read/Edit directory activation."""

        return self.load_for_path(target_path, strict=strict)

    def rebuild_from_metadata(
        self,
        metadata: InstructionStateMetadata | Mapping[str, object],
        *,
        strict: bool = False,
    ) -> InstructionLoadResult:
        """Re-read persisted scopes from the current filesystem.

        This method only consumes persisted directory identities.  It never
        scans History, ToolCall payloads, or ordinary read/edit records.
        """

        state = (
            metadata
            if isinstance(metadata, InstructionStateMetadata)
            else InstructionStateMetadata.from_dict(metadata)
        )
        self._instruction_epoch = state.instruction_epoch
        self._stable_prefix_fingerprint = state.stable_prefix_fingerprint
        self._source_fingerprints = state.source_fingerprints
        restored: set[Path] = set()
        for raw_scope in state.activated_directory_scopes:
            path = self._project_target(raw_scope, strict=strict)
            if path.is_file():
                path = path.parent
            self._relative_to_project(path, strict=strict)
            restored.add(path)
        self._activated_directories = restored
        self._session_loaded = True
        result = self._rebuild(strict=strict, new_scope=False, previous_state=state)
        return result

    def render_prompt(
        self,
        blocks: Sequence[ContextBlock] | None = None,
        diagnostics: Sequence[InstructionDiagnostic] | None = None,
    ) -> str:
        selected = self._blocks if blocks is None else tuple(blocks)
        selected_diagnostics = self._diagnostics if diagnostics is None else tuple(diagnostics)
        rendered: list[str] = []
        for block in selected:
            rendered.append(
                "[Instruction "
                f"source={block.provenance} authority={block.authority.value} "
                f"scope={block.scope.value if isinstance(block.scope, Enum) else block.scope}]\n"
                f"{block.content}\n[/Instruction]"
            )
        for diagnostic in selected_diagnostics:
            rendered.append(
                "[Instruction diagnostic "
                f"code={diagnostic.code} source={diagnostic.source_path} "
                f"scope={InstructionScope(diagnostic.scope).value}]\n"
                f"{diagnostic.message}\n[/Instruction diagnostic]"
            )
        return "\n\n".join(rendered)

    def apply_authorized_change(
        self,
        target_path: str | Path,
        content: str,
        *,
        authorization: "InstructionAuthorization | None" = None,
    ) -> None:
        if authorization is None or not authorization.explicit:
            raise InstructionAuthorizationError()
        if authorization.scope is not InstructionScope.USER:
            raise InstructionAuthorizationError("user scope authorization is required")
        if not isinstance(content, str):
            raise TypeError("instruction content must be text")
        target = self._reader.canonical_path(target_path, trusted_root=self.user_root)
        authorized = self._reader.canonical_path(
            authorization.target_path,
            trusted_root=self.user_root,
        )
        if target != authorized or target.name != self.agents_filename:
            raise InstructionAuthorizationError("authorization target does not match")
        try:
            target.write_text(content, encoding="utf-8")
        except OSError as exc:
            raise InstructionAuthorizationError(f"write failed: {exc}") from exc
        self._session_loaded = False

    def _rebuild(
        self,
        *,
        strict: bool,
        new_scope: bool,
        previous_state: InstructionStateMetadata | None = None,
    ) -> InstructionLoadResult:
        before_blocks = self._blocks
        before_diagnostics = self._diagnostics
        graph = _LoadGraph()
        roots = (
            (self.user_root / self.agents_filename, InstructionScope.USER, self.user_root, "session:user"),
            (self.project_root / self.agents_filename, InstructionScope.PROJECT, self.project_root, "session:project"),
        )
        for path, scope, trusted_root, reason in roots:
            self._load_file(
                path,
                scope=scope,
                trusted_root=trusted_root,
                reason=reason,
                graph=graph,
                stack=(),
                is_reference=False,
                path_is_canonical=False,
                strict=strict,
            )
        for directory in self._directory_chain():
            path = directory / self.agents_filename
            self._load_file(
                path,
                scope=InstructionScope.DIRECTORY,
                trusted_root=self.project_root,
                reason=f"scope:{directory}",
                graph=graph,
                stack=(),
                is_reference=False,
                path_is_canonical=False,
                strict=strict,
            )

        segments = tuple(graph.loaded.values())
        blocks = tuple(segment.to_context_block() for segment in segments)
        prefix = build_instruction_prefix(
            (public_prompt_source(), core_runtime_contract_source(), *blocks),
            instruction_epoch=max(1, self._instruction_epoch),
        )
        source_fingerprints = tuple(
            (
                segment.identity,
                str(segment.source_path),
                InstructionScope(segment.scope).value,
                segment.content_fingerprint,
            )
            for segment in segments
        )
        old_fingerprints = previous_state.source_fingerprints if previous_state is not None else self._source_fingerprints
        old_prefix = previous_state.stable_prefix_fingerprint if previous_state is not None else self._stable_prefix_fingerprint
        changed = bool(old_prefix) and prefix.fingerprint != old_prefix
        if not old_prefix:
            epoch = max(1, self._instruction_epoch)
            reason = "initial"
        elif changed:
            epoch = max(1, self._instruction_epoch) + 1
            reason = _change_reason(
                old_fingerprints,
                source_fingerprints,
                new_scope=new_scope,
            )
        else:
            epoch = max(1, self._instruction_epoch)
            reason = "stable"
        if changed or not old_prefix:
            prefix = build_instruction_prefix(
                (public_prompt_source(), core_runtime_contract_source(), *blocks),
                instruction_epoch=epoch,
                reason=reason,
                changed=changed,
            )
        self._blocks = blocks
        self._diagnostics = tuple(graph.diagnostics)
        self._source_fingerprints = source_fingerprints
        self._instruction_epoch = epoch
        self._stable_prefix_fingerprint = prefix.fingerprint
        self._change_reason = reason
        state = self.instruction_state
        new_block_values = _new_items(before_blocks, blocks, key=lambda item: item.provenance)
        new_diagnostic_values = tuple(self._diagnostics[len(before_diagnostics) :])
        return InstructionLoadResult(
            blocks=blocks,
            new_blocks=new_block_values,
            diagnostics=self._diagnostics,
            new_diagnostics=new_diagnostic_values,
            instruction_state=state,
            effective_instruction_set=blocks,
            instruction_epoch=epoch,
            stable_prefix_fingerprint=prefix.fingerprint,
            change_reason=reason,
            prompt_text=self.render_prompt(),
            new_prompt_text=self.render_prompt(new_block_values, new_diagnostic_values),
        )

    def _load_file(
        self,
        path: Path,
        *,
        scope: InstructionScope,
        trusted_root: Path,
        reason: str,
        graph: _LoadGraph,
        stack: tuple[str, ...],
        is_reference: bool,
        path_is_canonical: bool,
        strict: bool,
    ) -> None:
        try:
            normalized = self._reader.canonical_path(
                path,
                trusted_root=trusted_root,
                base_dir=(path.parent if is_reference else None)
                if not path_is_canonical
                else None,
                relative_only=is_reference and not path_is_canonical,
            )
        except Exception as exc:
            self._failure(
                graph,
                code=InstructionPathRejectedError.code,
                path=path,
                scope=scope,
                message=str(exc),
                strict=strict,
            )
            return
        try:
            identity = self._reader.identity(normalized)
        except Exception as exc:
            self._failure(graph, code=InstructionReadError.code, path=normalized, scope=scope, message=str(exc), strict=strict)
            return
        if identity in stack:
            chain = " -> ".join((*stack, identity))
            self._failure(graph, code=InstructionIncludeCycleError.code, path=normalized, scope=scope, message=chain, strict=strict)
            return
        if identity in graph.loaded:
            return
        if not normalized.exists():
            if is_reference:
                self._failure(
                    graph,
                    code=InstructionSourceNotFoundError.code,
                    path=normalized,
                    scope=scope,
                    message="instruction source does not exist",
                    strict=strict,
                )
            return
        try:
            file_value = self._reader.read(normalized, trusted_root=trusted_root)
            content = file_value.content
            identity = file_value.identity
            content_fingerprint = file_value.content_fingerprint
            normalized = file_value.path
        except Exception as exc:
            self._failure(
                graph,
                code=InstructionReadError.code,
                path=normalized,
                scope=scope,
                message=str(exc),
                strict=strict,
            )
            return
        segment = InstructionBlock(
            source_path=normalized,
            scope=scope,
            load_order=len(graph.loaded) + 1,
            reason=reason,
            content=content,
            identity=identity,
            content_fingerprint=content_fingerprint,
        )
        graph.loaded[identity] = segment
        next_stack = (*stack, identity)
        for reference in parse_instruction_references(content):
            try:
                reference_path = self._reader.canonical_path(
                    reference,
                    trusted_root=trusted_root,
                    base_dir=normalized.parent,
                    relative_only=True,
                )
                reference_identity = self._reader.identity(reference_path)
            except Exception as exc:
                self._failure(
                    graph,
                    code=InstructionPathRejectedError.code,
                    path=normalized,
                    scope=scope,
                    message=str(exc),
                    strict=strict,
                )
                continue
            if reference_identity in graph.loaded or reference_identity in graph.references:
                if reference_identity in next_stack:
                    chain = " -> ".join((*next_stack, reference_identity))
                    self._failure(graph, code=InstructionIncludeCycleError.code, path=reference_path, scope=scope, message=chain, strict=strict)
                continue
            if graph.reference_count >= self.max_reference_files:
                self._failure(
                    graph,
                    code=InstructionReferenceLimitError.code,
                    path=reference_path,
                    scope=scope,
                    message=f"more than {self.max_reference_files} additional files",
                    strict=strict,
                )
                continue
            graph.references.add(reference_identity)
            graph.reference_count += 1
            self._load_file(
                reference_path,
                scope=scope,
                trusted_root=trusted_root,
                reason=f"include:{normalized}",
                graph=graph,
                stack=next_stack,
                is_reference=True,
                path_is_canonical=True,
                strict=strict,
            )

    def _failure(
        self,
        graph: _LoadGraph,
        *,
        code: str,
        path: Path,
        scope: InstructionScope,
        message: str,
        strict: bool,
    ) -> None:
        error_type: type[InstructionError] = {
            InstructionPathRejectedError.code: InstructionPathRejectedError,
            InstructionReferenceLimitError.code: InstructionReferenceLimitError,
            InstructionIncludeCycleError.code: InstructionIncludeCycleError,
            InstructionReadError.code: InstructionReadError,
            InstructionSourceNotFoundError.code: InstructionSourceNotFoundError,
        }.get(code, InstructionError)
        if strict:
            raise error_type(message)
        graph.diagnostics.append(InstructionDiagnostic(code, path, scope, message))

    def _project_target(self, target_path: str | Path, *, strict: bool) -> Path:
        try:
            return self._reader.canonical_path(target_path, trusted_root=self.project_root)
        except Exception as exc:
            if strict:
                raise InstructionPathRejectedError(str(exc)) from exc
            raise InstructionPathRejectedError(str(exc)) from exc

    def _relative_to_project(self, path: Path, *, strict: bool) -> Path:
        try:
            return path.relative_to(self.project_root)
        except ValueError as exc:
            raise InstructionPathRejectedError(str(path)) from exc

    def _directory_chain(self) -> tuple[Path, ...]:
        return tuple(
            sorted(
                self._activated_directories,
                key=lambda path: (len(path.relative_to(self.project_root).parts), str(path)),
            )
        )


@dataclass(frozen=True, slots=True)
class InstructionAuthorization:
    explicit: bool
    target_path: Path
    scope: InstructionScope | str

    def __post_init__(self) -> None:
        if not isinstance(self.target_path, Path):
            object.__setattr__(self, "target_path", Path(self.target_path))
        if not isinstance(self.scope, InstructionScope):
            object.__setattr__(self, "scope", InstructionScope(self.scope))
        if not isinstance(self.explicit, bool):
            raise TypeError("explicit must be a boolean")


def _default_reader() -> InstructionFileReader:
    module = importlib.import_module("uthcode.integrations.instruction_files")
    return module.InstructionFileReader()


def _new_items(
    before: Sequence[Any],
    after: Sequence[Any],
    *,
    key: Any,
) -> tuple[Any, ...]:
    previous = {key(item) for item in before}
    return tuple(item for item in after if key(item) not in previous)


def _change_reason(
    before: Sequence[tuple[str, str, str, str]],
    after: Sequence[tuple[str, str, str, str]],
    *,
    new_scope: bool,
) -> str:
    old_map = {item[0]: item for item in before}
    new_map = {item[0]: item for item in after}
    if new_scope and set(new_map) - set(old_map):
        return "instruction_scope_added"
    if any(old_map.get(identity) != item for identity, item in new_map.items() if identity in old_map):
        return "instruction_content_changed"
    if set(new_map) - set(old_map):
        return "instruction_source_added"
    if set(old_map) - set(new_map):
        return "instruction_source_removed"
    return "instruction_content_changed"


__all__ = [
    "InstructionAuthorization",
    "InstructionBlock",
    "InstructionDiagnostic",
    "InstructionError",
    "InstructionIncludeCycleError",
    "InstructionLoadResult",
    "InstructionLoader",
    "InstructionPathRejectedError",
    "InstructionReadError",
    "InstructionReferenceLimitError",
    "InstructionScope",
    "InstructionSourceNotFoundError",
    "InstructionStateMetadata",
    "parse_instruction_references",
]
