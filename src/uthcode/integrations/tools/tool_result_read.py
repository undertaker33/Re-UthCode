"""Durable, bounded Tool Result materialization for one active Session.

The Integration owns bytes and integrity checks.  It accepts only an opaque
reference plus bounded pagination facts; it never turns a caller-provided path
into a read capability.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from uthcode.core.permission import Effect, PermissionAction, ResourceScope
from uthcode.core.provider import CancellationToken, JsonPayload, ToolDefinition
from uthcode.core.tool import ToolExecutionResult, ToolPlanningAccess, ToolPreparation


TOOL_RESULT_SCHEMA_VERSION = 1
_REF_PATTERN = re.compile(r"^[A-Za-z0-9_-]{16,128}$")


class ToolResultError(RuntimeError):
    """Base error for bounded Tool Result persistence and reads."""

    code = "tool_result_error"


class ToolResultQuotaExceeded(ToolResultError):
    code = "session_result_quota_exceeded"


class ToolResultTooLarge(ToolResultError):
    code = "single_result_hard_cap_exceeded"


class ToolResultPersistenceError(ToolResultError):
    code = "result_persistence_failed"


class ToolResultOutputLimitError(ToolResultError):
    code = "tool_result_output_limit_exceeded"


class ToolResultReferenceError(ToolResultError):
    code = "invalid_tool_result_reference"


class ToolResultIntegrityError(ToolResultError):
    code = "tool_result_integrity_failed"


def _positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")
    return value


@dataclass(frozen=True, slots=True)
class ToolResultPolicy:
    """Evidence-backed local resource limits, measured in UTF-8 bytes."""

    inline_threshold_bytes: int = 8 * 1024
    preview_limit_bytes: int = 2 * 1024
    single_result_hard_cap_bytes: int = 1 * 1024 * 1024
    session_quota_bytes: int = 8 * 1024 * 1024
    read_page_limit_bytes: int = 64 * 1024
    read_output_limit_bytes: int = 64 * 1024

    def __post_init__(self) -> None:
        for field_name in (
            "inline_threshold_bytes",
            "preview_limit_bytes",
            "single_result_hard_cap_bytes",
            "session_quota_bytes",
            "read_page_limit_bytes",
            "read_output_limit_bytes",
        ):
            _positive_int(getattr(self, field_name), field_name)
        if self.inline_threshold_bytes > self.single_result_hard_cap_bytes:
            raise ValueError("inline threshold cannot exceed the single-result hard cap")
        if self.preview_limit_bytes > self.single_result_hard_cap_bytes:
            raise ValueError("preview limit cannot exceed the single-result hard cap")

    @property
    def inline_threshold(self) -> int:
        return self.inline_threshold_bytes

    @property
    def preview_limit(self) -> int:
        return self.preview_limit_bytes

    @property
    def single_result_hard_cap(self) -> int:
        return self.single_result_hard_cap_bytes

    @property
    def session_quota(self) -> int:
        return self.session_quota_bytes

    @property
    def read_page_limit(self) -> int:
        return self.read_page_limit_bytes

    @property
    def read_output_limit(self) -> int:
        return self.read_output_limit_bytes

    @property
    def effective_read_output_limit(self) -> int:
        """Final model-visible budget after both operational caps apply."""

        return min(self.read_page_limit_bytes, self.read_output_limit_bytes)


@dataclass(frozen=True, slots=True)
class ToolResultReference:
    """Opaque Session-scoped identity returned after durable externalization."""

    ref: str
    session_id: str
    size_bytes: int
    sha256: str

    def __post_init__(self) -> None:
        _validate_ref(self.ref)
        if not isinstance(self.session_id, str) or not self.session_id:
            raise ValueError("session_id must be a non-empty string")
        if isinstance(self.size_bytes, bool) or not isinstance(self.size_bytes, int):
            raise TypeError("size_bytes must be an integer")
        if self.size_bytes < 0:
            raise ValueError("size_bytes must be non-negative")
        if not isinstance(self.sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", self.sha256):
            raise ValueError("sha256 must be a lowercase SHA-256 digest")

    def to_dict(self) -> dict[str, object]:
        return {
            "ref": self.ref,
            "session_id": self.session_id,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
        }


@dataclass(frozen=True, slots=True)
class ToolResultPage:
    ref: str
    content: str
    offset: int
    next_offset: int
    total_bytes: int
    sha256: str
    eof: bool

    def __post_init__(self) -> None:
        _validate_ref(self.ref)
        if not isinstance(self.content, str):
            raise TypeError("content must be a string")
        for field_name in ("offset", "next_offset", "total_bytes"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")
        if self.next_offset < self.offset or self.next_offset > self.total_bytes:
            raise ValueError("next_offset must be within the result")
        if not isinstance(self.eof, bool):
            raise TypeError("eof must be a boolean")


def _validate_ref(value: object) -> str:
    if not isinstance(value, str) or not _REF_PATTERN.fullmatch(value):
        raise ToolResultReferenceError("Tool Result ref must be an opaque identifier")
    return value


def _safe_session_path(store: object, session_id: str) -> Path:
    if not isinstance(session_id, str) or not session_id or session_id in {".", ".."}:
        raise ToolResultReferenceError("invalid Session ownership")
    if "/" in session_id or "\\" in session_id or "\x00" in session_id:
        raise ToolResultReferenceError("invalid Session ownership")
    session_path = getattr(store, "session_path", None)
    if not callable(session_path):
        raise TypeError("store must provide session_path(session_id)")
    path = Path(session_path(session_id)).resolve(strict=False)
    if not path.is_dir():
        raise ToolResultReferenceError("unknown Session ownership")
    return path


def _fsync_directory(path: Path) -> None:
    """Best-effort directory durability across Windows and POSIX."""

    try:
        descriptor = os.open(str(path), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def _atomic_json(path: Path, value: Mapping[str, object]) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


class ToolResultFileStore:
    """Atomic byte store rooted inside the versioned Session layout."""

    def __init__(self, store: object) -> None:
        self._store = store

    def _results_path(self, session_id: str) -> Path:
        path = _safe_session_path(self._store, session_id) / "tool-results"
        path.mkdir(exist_ok=True)
        return path

    def _used_bytes(self, results_path: Path) -> int:
        total = 0
        for content_path in results_path.glob("*/content.bin"):
            try:
                total += content_path.stat().st_size
            except OSError as exc:
                raise ToolResultPersistenceError("could not inspect Session result quota") from exc
        return total

    def persist(
        self,
        session_id: str,
        content: str,
        *,
        policy: ToolResultPolicy | None = None,
    ) -> ToolResultReference:
        if not isinstance(content, str):
            raise TypeError("content must be a string")
        policy = ToolResultPolicy() if policy is None else policy
        if not isinstance(policy, ToolResultPolicy):
            raise TypeError("policy must be a ToolResultPolicy or None")
        results_path = self._results_path(session_id)
        encoded = content.encode("utf-8")
        size_bytes = len(encoded)
        if size_bytes > policy.single_result_hard_cap_bytes:
            raise ToolResultTooLarge(
                f"Tool Result exceeds the {policy.single_result_hard_cap_bytes}-byte hard cap"
            )
        if self._used_bytes(results_path) + size_bytes > policy.session_quota_bytes:
            raise ToolResultQuotaExceeded(
                f"Session Tool Result quota is {policy.session_quota_bytes} bytes"
            )

        reference = uuid.uuid4().hex
        final_path = results_path / reference
        temporary_path = results_path / f".{reference}.{uuid.uuid4().hex}.tmp"
        digest = hashlib.sha256(encoded).hexdigest()
        metadata = {
            "schema_version": TOOL_RESULT_SCHEMA_VERSION,
            "session_id": session_id,
            "ref": reference,
            "size_bytes": size_bytes,
            "sha256": digest,
        }
        try:
            temporary_path.mkdir()
            content_path = temporary_path / "content.bin"
            with content_path.open("wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            _atomic_json(temporary_path / "metadata.json", metadata)
            _fsync_directory(temporary_path)
            os.replace(temporary_path, final_path)
            _fsync_directory(results_path)
        except Exception as exc:
            shutil.rmtree(temporary_path, ignore_errors=True)
            # The final directory is created only by this call.  Removing it
            # after a post-rename durability failure prevents dangling refs.
            if final_path.exists():
                shutil.rmtree(final_path, ignore_errors=True)
            if isinstance(exc, ToolResultError):
                raise
            raise ToolResultPersistenceError("could not durably persist Tool Result") from exc
        return ToolResultReference(reference, session_id, size_bytes, digest)

    def read_page(
        self,
        session_id: str,
        ref: str,
        *,
        offset: int = 0,
        limit: int | None = None,
        policy: ToolResultPolicy | None = None,
    ) -> ToolResultPage:
        policy = ToolResultPolicy() if policy is None else policy
        if not isinstance(policy, ToolResultPolicy):
            raise TypeError("policy must be a ToolResultPolicy or None")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ToolResultReferenceError("offset must be a non-negative integer")
        page_limit = policy.read_page_limit_bytes if limit is None else limit
        if isinstance(page_limit, bool) or not isinstance(page_limit, int) or page_limit <= 0:
            raise ToolResultReferenceError("limit must be a positive integer")
        if page_limit > policy.read_page_limit_bytes:
            raise ToolResultReferenceError("limit exceeds the bounded read page limit")
        _validate_ref(ref)
        session_path = _safe_session_path(self._store, session_id)
        result_path = (session_path / "tool-results" / ref).resolve(strict=False)
        results_root = (session_path / "tool-results").resolve(strict=False)
        if results_root not in result_path.parents:
            raise ToolResultReferenceError("Tool Result ref escaped its Session")
        metadata_path = result_path / "metadata.json"
        content_path = result_path / "content.bin"
        if not result_path.is_dir():
            raise ToolResultReferenceError("Tool Result ref is not present in this Session")
        try:
            value = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ToolResultIntegrityError("Tool Result metadata is unreadable") from exc
        metadata = _validate_metadata(value, session_id, ref)
        try:
            encoded = content_path.read_bytes()
        except OSError as exc:
            raise ToolResultIntegrityError("Tool Result content is unreadable") from exc
        actual_digest = hashlib.sha256(encoded).hexdigest()
        if len(encoded) != metadata["size_bytes"] or actual_digest != metadata["sha256"]:
            raise ToolResultIntegrityError("Tool Result size or hash does not match metadata")
        total_bytes = len(encoded)
        if offset > total_bytes:
            raise ToolResultReferenceError("offset is beyond the Tool Result")
        requested_end = min(total_bytes, offset + page_limit)
        start, end = _utf8_page_bounds(encoded, offset, requested_end)
        try:
            content = encoded[start:end].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ToolResultIntegrityError("Tool Result page is not valid UTF-8") from exc
        return ToolResultPage(
            ref=ref,
            content=content,
            offset=start,
            next_offset=end,
            total_bytes=total_bytes,
            sha256=actual_digest,
            eof=end >= total_bytes,
        )


def _validate_metadata(value: object, session_id: str, ref: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ToolResultIntegrityError("Tool Result metadata is not an object")
    required = {"schema_version", "session_id", "ref", "size_bytes", "sha256"}
    if set(value) != required:
        raise ToolResultIntegrityError("Tool Result metadata fields are invalid")
    if value["schema_version"] != TOOL_RESULT_SCHEMA_VERSION:
        raise ToolResultIntegrityError("unsupported Tool Result metadata schema")
    if value["session_id"] != session_id or value["ref"] != ref:
        raise ToolResultReferenceError("Tool Result belongs to another Session")
    size = value["size_bytes"]
    digest = value["sha256"]
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise ToolResultIntegrityError("Tool Result metadata size is invalid")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ToolResultIntegrityError("Tool Result metadata hash is invalid")
    return {"size_bytes": size, "sha256": digest}


def _utf8_page_bounds(encoded: bytes, start: int, end: int) -> tuple[int, int]:
    while start < end and (encoded[start] & 0xC0) == 0x80:
        start += 1
    while end > start:
        try:
            encoded[start:end].decode("utf-8")
            return start, end
        except UnicodeDecodeError:
            end -= 1
    return start, start


def bounded_utf8_prefix(value: str, limit_bytes: int) -> str:
    """Return at most ``limit_bytes`` of UTF-8 text without splitting a codepoint."""

    if not isinstance(value, str):
        raise TypeError("value must be a string")
    limit_bytes = _positive_int(limit_bytes, "limit_bytes")
    encoded = value.encode("utf-8")[:limit_bytes]
    while encoded:
        try:
            return encoded.decode("utf-8")
        except UnicodeDecodeError:
            encoded = encoded[:-1]
    return ""


def format_externalized_preview(
    content: str,
    reference: ToolResultReference,
    *,
    preview_limit_bytes: int,
) -> str:
    preview = bounded_utf8_prefix(content, preview_limit_bytes)
    suffix = "" if len(preview.encode("utf-8")) >= reference.size_bytes else "\n[preview truncated]"
    return (
        f"[Tool Result externalized; ref={reference.ref}; size_bytes={reference.size_bytes}; "
        f"sha256={reference.sha256}]\n{preview}{suffix}\n"
        "Use ToolResultRead with this ref and a bounded offset/limit to read more."
    )


def format_tool_result_page(page: ToolResultPage) -> str:
    """Serialize one bounded page with the exact continuation metadata."""

    if not isinstance(page, ToolResultPage):
        raise TypeError("page must be a ToolResultPage")
    return json.dumps(
        {
            "ref": page.ref,
            "offset": page.offset,
            "next_offset": page.next_offset,
            "total_bytes": page.total_bytes,
            "sha256": page.sha256,
            "eof": page.eof,
            "content": page.content,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


Reader = Callable[[str, str, int, int], ToolResultPage]
SessionProvider = Callable[[], object | None]


class ToolResultReadTool:
    """Read only the current Application Session's opaque Tool Result ref."""

    _definition = ToolDefinition(
        "ToolResultRead",
        "Read a bounded page from a large Tool Result using its current-Session opaque ref.",
        {
            "type": "object",
            "properties": {
                "ref": {"type": "string", "minLength": 16},
                "offset": {"type": "integer", "minimum": 0, "default": 0},
                "limit": {"type": "integer", "minimum": 1, "maximum": 64 * 1024, "default": 64 * 1024},
            },
            "required": ["ref"],
            "additionalProperties": False,
        },
    )

    def __init__(
        self,
        reader: Reader,
        session_provider: SessionProvider,
        *,
        policy: ToolResultPolicy | None = None,
    ) -> None:
        if not callable(reader):
            raise TypeError("reader must be callable")
        if not callable(session_provider):
            raise TypeError("session_provider must be callable")
        self._reader = reader
        self._session_provider = session_provider
        self._policy = ToolResultPolicy() if policy is None else policy
        if not isinstance(self._policy, ToolResultPolicy):
            raise TypeError("policy must be a ToolResultPolicy or None")

    @property
    def definition(self) -> ToolDefinition:
        return self._definition

    @property
    def planning_access(self) -> ToolPlanningAccess:
        return ToolPlanningAccess.READ_ONLY

    def preflight(self, arguments: JsonPayload) -> ToolPreparation:
        ref = arguments.get("ref")
        try:
            _validate_ref(ref)
        except ToolResultReferenceError as exc:
            raise ValueError("Error: invalid ToolResultRead ref") from exc
        offset = arguments.get("offset", 0)
        limit = arguments.get("limit", self._policy.read_page_limit_bytes)
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError("Error: invalid ToolResultRead offset")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= self._policy.read_page_limit_bytes:
            raise ValueError("Error: invalid ToolResultRead limit")
        return ToolPreparation(
            action=PermissionAction(
                tool=self._definition.name,
                action="read",
                effect=Effect.READ,
                resource=f"session-result:{ref}",
                scope=ResourceScope.INSIDE,
            ),
            execution_arguments=arguments,
        )

    async def execute(
        self,
        arguments: JsonPayload,
        *,
        cancellation: CancellationToken,
    ) -> ToolExecutionResult:
        if cancellation.cancelled:
            return ToolExecutionResult("Error: tool call cancelled", True)
        session = self._session_provider()
        if session is None:
            return ToolExecutionResult("Error: ToolResultRead requires an active Session", True)
        session_id = getattr(session, "session_id", None)
        if not isinstance(session_id, str) or not session_id:
            return ToolExecutionResult("Error: active Session identity is unavailable", True)
        try:
            page = self._read_bounded_page(
                session_id,
                arguments["ref"],
                int(arguments.get("offset", 0)),
                int(arguments.get("limit", self._policy.read_page_limit_bytes)),
            )
        except ToolResultError as exc:
            return ToolExecutionResult(f"Error: {exc.code}", True)
        except Exception:
            return ToolExecutionResult("Error: ToolResultRead failed", True)
        if cancellation.cancelled:
            return ToolExecutionResult("Error: tool call cancelled", True)
        return ToolExecutionResult(format_tool_result_page(page))

    def _read_bounded_page(
        self,
        session_id: str,
        ref: str,
        offset: int,
        requested_limit: int,
    ) -> ToolResultPage:
        """Find a progressing UTF-8 page whose final JSON fits the budget."""

        if isinstance(requested_limit, bool) or not isinstance(requested_limit, int):
            raise ToolResultReferenceError("limit must be a positive integer")
        raw_limit = min(requested_limit, self._policy.read_page_limit_bytes)
        if raw_limit <= 0:
            raise ToolResultReferenceError("limit must be a positive integer")

        output_limit = self._policy.effective_read_output_limit
        low = 1
        high = raw_limit
        best: ToolResultPage | None = None
        while low <= high:
            candidate_limit = (low + high) // 2
            candidate = self._reader(session_id, ref, offset, candidate_limit)
            if not isinstance(candidate, ToolResultPage):
                raise ToolResultError("Session returned an invalid Tool Result page")
            serialized_size = len(format_tool_result_page(candidate).encode("utf-8"))
            progresses = candidate.eof or candidate.next_offset > candidate.offset
            if not progresses:
                # A raw byte limit can be smaller than the next UTF-8 code
                # point.  That candidate is too small; do not let it make a
                # binary search discard the larger limit that can progress.
                low = candidate_limit + 1
            elif serialized_size <= output_limit:
                best = candidate
                low = candidate_limit + 1
            else:
                high = candidate_limit - 1
        if best is None:
            raise ToolResultOutputLimitError(
                "Tool Result envelope cannot fit the configured output budget"
            )
        return best


__all__ = [
    "TOOL_RESULT_SCHEMA_VERSION",
    "ToolResultError",
    "ToolResultFileStore",
    "ToolResultIntegrityError",
    "ToolResultPage",
    "ToolResultPersistenceError",
    "ToolResultPolicy",
    "ToolResultQuotaExceeded",
    "ToolResultReference",
    "ToolResultReferenceError",
    "ToolResultReadTool",
    "ToolResultTooLarge",
    "ToolResultOutputLimitError",
    "bounded_utf8_prefix",
    "format_externalized_preview",
    "format_tool_result_page",
]
