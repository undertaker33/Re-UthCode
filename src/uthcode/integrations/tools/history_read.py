"""Bounded reads of the active Session's raw Transcript references."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass

from uthcode.core.history import TranscriptEntry, TranscriptRef
from uthcode.core.permission import Effect, PermissionAction, ResourceScope
from uthcode.core.provider import CancellationToken, JsonPayload, ToolDefinition
from uthcode.core.tool import ToolExecutionResult, ToolPlanningAccess, ToolPreparation


HISTORY_READ_SCHEMA_VERSION = 1
_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


class HistoryReadError(ValueError):
    """Base error for bounded raw Transcript reads."""

    code = "history_read_error"

    def __init__(self, message: str = "") -> None:
        super().__init__(f"{self.code}: {message}" if message else self.code)


class HistoryReadReferenceError(HistoryReadError):
    code = "invalid_history_ref"


class HistoryReadSessionError(HistoryReadError):
    code = "history_session_mismatch"


class HistoryReadBoundaryError(HistoryReadError):
    code = "invalid_history_boundary"


class HistoryReadOutputLimitError(HistoryReadError):
    code = "history_read_output_limit_exceeded"


def _positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")
    return value


@dataclass(frozen=True, slots=True)
class HistoryReadPolicy:
    """Bounded page limits for raw Transcript reads."""

    page_entry_limit: int = 32
    read_output_limit_bytes: int = 64 * 1024

    def __post_init__(self) -> None:
        _positive_int(self.page_entry_limit, "page_entry_limit")
        _positive_int(self.read_output_limit_bytes, "read_output_limit_bytes")

    @property
    def read_page_limit(self) -> int:
        return self.page_entry_limit

    @property
    def read_output_limit(self) -> int:
        return self.read_output_limit_bytes


@dataclass(frozen=True, slots=True)
class HistoryReadPage:
    """One bounded page inside one exact opaque Transcript reference."""

    ref: str
    entries: tuple[TranscriptEntry, ...]
    offset: int
    next_offset: int
    total_entries: int
    eof: bool

    def __post_init__(self) -> None:
        ref = decode_history_ref(self.ref)
        entries = tuple(self.entries)
        if not all(isinstance(entry, TranscriptEntry) for entry in entries):
            raise TypeError("entries must contain TranscriptEntry values")
        for field_name in ("offset", "next_offset", "total_entries"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")
        if self.next_offset < self.offset or self.next_offset > self.total_entries:
            raise ValueError("next_offset must be within the referenced Transcript range")
        if self.offset > self.total_entries:
            raise ValueError("offset must be within the referenced Transcript range")
        expected_total = ref.sequence_end - ref.sequence_start + 1
        if self.total_entries != expected_total:
            raise ValueError("total_entries does not match the referenced Transcript range")
        if self.next_offset != self.offset + len(entries):
            raise ValueError("next_offset does not match the page entries")
        expected_start = ref.sequence_start + self.offset
        if any(
            entry.session_id != ref.session_id
            or entry.sequence != expected_start + index
            for index, entry in enumerate(entries)
        ):
            raise HistoryReadBoundaryError("page entries escape the referenced Transcript range")
        if self.eof != (self.next_offset >= self.total_entries):
            raise ValueError("eof does not match the page boundary")
        if not isinstance(self.eof, bool):
            raise TypeError("eof must be a boolean")
        object.__setattr__(self, "entries", entries)


def decode_history_ref(token: object) -> TranscriptRef:
    """Decode only the canonical Core TranscriptRef token form."""

    if not isinstance(token, str) or not token or not _TOKEN_PATTERN.fullmatch(token):
        raise HistoryReadReferenceError("HistoryRead ref must be a canonical opaque token")
    try:
        ref = TranscriptRef.from_token(token)
    except (TypeError, ValueError):
        raise HistoryReadReferenceError("HistoryRead ref is malformed") from None
    if ref.to_token() != token:
        raise HistoryReadReferenceError("HistoryRead ref is not canonical")
    return ref


def format_history_read_page(page: HistoryReadPage) -> str:
    """Serialize a raw page without routing it through ToolResult storage."""

    if not isinstance(page, HistoryReadPage):
        raise TypeError("page must be a HistoryReadPage")
    return json.dumps(
        {
            "schema_version": HISTORY_READ_SCHEMA_VERSION,
            "ref": page.ref,
            "offset": page.offset,
            "next_offset": page.next_offset,
            "total_entries": page.total_entries,
            "eof": page.eof,
            "entries": [entry.to_dict() for entry in page.entries],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


Reader = Callable[[str, str, int, int], HistoryReadPage]
SessionProvider = Callable[[], object | None]


class HistoryReadTool:
    """Read a bounded page from the active Session's exact raw Transcript ref."""

    _definition = ToolDefinition(
        "HistoryRead",
        "Read a bounded page from the active Session using an opaque Transcript ref.",
        {
            "type": "object",
            "properties": {
                "ref": {"type": "string", "minLength": 1},
                "offset": {"type": "integer", "minimum": 0, "default": 0},
                "limit": {"type": "integer", "minimum": 1, "maximum": 32, "default": 32},
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
        policy: HistoryReadPolicy | None = None,
    ) -> None:
        if not callable(reader):
            raise TypeError("reader must be callable")
        if not callable(session_provider):
            raise TypeError("session_provider must be callable")
        self._reader = reader
        self._session_provider = session_provider
        self._policy = HistoryReadPolicy() if policy is None else policy
        if not isinstance(self._policy, HistoryReadPolicy):
            raise TypeError("policy must be a HistoryReadPolicy or None")

    @property
    def definition(self) -> ToolDefinition:
        return self._definition

    @property
    def planning_access(self) -> ToolPlanningAccess:
        return ToolPlanningAccess.READ_ONLY

    def preflight(self, arguments: JsonPayload) -> ToolPreparation:
        ref = decode_history_ref(arguments.get("ref"))
        session = self._session_provider()
        session_id = getattr(session, "session_id", None) if session is not None else None
        if not isinstance(session_id, str) or not session_id:
            raise HistoryReadSessionError("HistoryRead requires an active Session")
        if ref.session_id != session_id:
            raise HistoryReadSessionError("HistoryRead ref is not owned by the active Session")
        offset = arguments.get("offset", 0)
        limit = arguments.get("limit", self._policy.page_entry_limit)
        _validate_bounds(offset, limit, self._policy)
        return ToolPreparation(
            action=PermissionAction(
                tool=self._definition.name,
                action="read",
                effect=Effect.READ,
                resource=f"session-transcript:{ref.to_token()}",
                scope=ResourceScope.INSIDE,
            ),
            execution_arguments=JsonPayload(
                {"ref": ref.to_token(), "offset": offset, "limit": limit}
            ),
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
            return ToolExecutionResult("Error: HistoryRead requires an active Session", True)
        session_id = getattr(session, "session_id", None)
        if not isinstance(session_id, str) or not session_id:
            return ToolExecutionResult("Error: active Session identity is unavailable", True)
        try:
            ref = decode_history_ref(arguments.get("ref"))
            if ref.session_id != session_id:
                raise HistoryReadSessionError("HistoryRead ref is not owned by the active Session")
            offset = arguments.get("offset", 0)
            requested_limit = arguments.get("limit", self._policy.page_entry_limit)
            _validate_bounds(offset, requested_limit, self._policy)
            page = self._read_bounded_page(
                session_id,
                ref.to_token(),
                offset,
                requested_limit,
            )
        except HistoryReadError as exc:
            return ToolExecutionResult(f"Error: {exc.code}", True)
        except (TypeError, ValueError):
            return ToolExecutionResult(f"Error: {HistoryReadBoundaryError.code}", True)
        except Exception:
            return ToolExecutionResult(f"Error: {HistoryReadError.code}", True)
        if cancellation.cancelled:
            return ToolExecutionResult("Error: tool call cancelled", True)
        return ToolExecutionResult(format_history_read_page(page))

    def _read_bounded_page(
        self,
        session_id: str,
        ref: str,
        offset: int,
        requested_limit: int,
    ) -> HistoryReadPage:
        """Find a progressing entry page whose JSON envelope fits the budget."""

        decode_history_ref(ref)
        _validate_bounds(offset, requested_limit, self._policy)
        low = 1
        high = min(requested_limit, self._policy.page_entry_limit)
        best: HistoryReadPage | None = None
        while low <= high:
            candidate_limit = (low + high) // 2
            candidate = self._reader(session_id, ref, offset, candidate_limit)
            if not isinstance(candidate, HistoryReadPage):
                raise HistoryReadError("Session returned an invalid HistoryRead page")
            if candidate.ref != ref or len(candidate.entries) > candidate_limit:
                raise HistoryReadBoundaryError("Session returned a page outside the requested ref")
            serialized_size = len(format_history_read_page(candidate).encode("utf-8"))
            progresses = candidate.eof or candidate.next_offset > candidate.offset
            if not progresses:
                low = candidate_limit + 1
            elif serialized_size <= self._policy.read_output_limit_bytes:
                best = candidate
                low = candidate_limit + 1
            else:
                high = candidate_limit - 1
        if best is None:
            raise HistoryReadOutputLimitError(
                "HistoryRead envelope cannot fit the configured output budget"
            )
        return best


def _validate_bounds(offset: object, limit: object, policy: HistoryReadPolicy) -> None:
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise HistoryReadBoundaryError("HistoryRead offset is invalid")
    if (
        isinstance(limit, bool)
        or not isinstance(limit, int)
        or not 1 <= limit <= policy.page_entry_limit
    ):
        raise HistoryReadBoundaryError("HistoryRead limit is invalid")


__all__ = [
    "HISTORY_READ_SCHEMA_VERSION",
    "HistoryReadBoundaryError",
    "HistoryReadError",
    "HistoryReadOutputLimitError",
    "HistoryReadPage",
    "HistoryReadPolicy",
    "HistoryReadReferenceError",
    "HistoryReadSessionError",
    "HistoryReadTool",
    "decode_history_ref",
    "format_history_read_page",
]
