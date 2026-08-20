"""Provider-independent contracts for bounded semantic compaction.

The Core owns the shape and validation rules of an L4 result.  Provider and
Application code only supply the bounded raw epoch and the model response;
they do not get to choose Transcript coverage or durable record references.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .history import SemanticUnit, TranscriptRef


class CompactionValidationError(ValueError):
    """A model-produced compaction result is not a valid L4 candidate."""


@dataclass(frozen=True, slots=True)
class CompactionEpoch:
    """One bounded group of complete raw semantic units.

    The epoch is process-local.  It is deliberately not a durable cursor or
    job record; after a restart it is derived again from Transcript and the
    latest committed Timeline checkpoint.
    """

    session_id: str
    units: tuple[SemanticUnit, ...]
    input_text: str
    input_tokens: int
    input_budget: int
    output_reserve: int
    sequence_start: int
    sequence_end: int

    def __post_init__(self) -> None:
        if not isinstance(self.session_id, str) or not self.session_id:
            raise ValueError("session_id must be a non-empty string")
        units = tuple(self.units)
        if not units:
            raise ValueError("CompactionEpoch must contain at least one unit")
        if not all(isinstance(unit, SemanticUnit) and unit.complete for unit in units):
            raise CompactionValidationError("CompactionEpoch contains an incomplete unit")
        if len({unit.unit_id for unit in units}) != len(units):
            raise CompactionValidationError("CompactionEpoch unit IDs must be unique")
        if len({unit.turn_id for unit in units}) != len(units):
            raise CompactionValidationError("CompactionEpoch turn IDs must be unique")
        if any(
            entry.session_id != self.session_id
            for unit in units
            for entry in unit.entries
        ):
            raise CompactionValidationError("CompactionEpoch unit ownership is invalid")
        if not isinstance(self.input_text, str) or not self.input_text:
            raise ValueError("input_text must be a non-empty string")
        for field_name in (
            "input_tokens",
            "input_budget",
            "output_reserve",
            "sequence_start",
            "sequence_end",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")
        if self.input_budget <= 0 or self.output_reserve <= 0:
            raise ValueError("CompactionEpoch budgets must be positive")
        if self.output_reserve >= self.input_budget:
            raise ValueError("output_reserve must be smaller than input_budget")
        if self.sequence_start != units[0].sequence_start:
            raise ValueError("sequence_start does not match the first unit")
        if self.sequence_end != units[-1].sequence_end:
            raise ValueError("sequence_end does not match the last unit")
        if self.sequence_start < 1 or self.sequence_end < self.sequence_start:
            raise ValueError("CompactionEpoch sequence range is invalid")
        object.__setattr__(self, "units", units)

    @property
    def unit_ids(self) -> tuple[str, ...]:
        return tuple(unit.unit_id for unit in self.units)

    @property
    def turn_ids(self) -> tuple[str, ...]:
        return tuple(unit.turn_id for unit in self.units)

    @property
    def refs(self) -> tuple[TranscriptRef, ...]:
        return tuple(
            TranscriptRef(self.session_id, unit.sequence_start, unit.sequence_end)
            for unit in self.units
        )


@dataclass(frozen=True, slots=True)
class CompactionEntry:
    """One validated Fine Timeline entry returned for one complete Turn."""

    turn_id: str
    summary: str
    refs: tuple[TranscriptRef, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.turn_id, str) or not self.turn_id:
            raise ValueError("turn_id must be a non-empty string")
        if not isinstance(self.summary, str) or not self.summary.strip():
            raise CompactionValidationError("summary must be non-empty text")
        refs = tuple(self.refs)
        if not refs or not all(isinstance(ref, TranscriptRef) for ref in refs):
            raise CompactionValidationError("each compaction entry needs a Transcript ref")
        object.__setattr__(self, "refs", refs)


@dataclass(frozen=True, slots=True)
class CompactionStructuredResult:
    """The validated, provider-neutral shape of one L4 model response."""

    entries: tuple[CompactionEntry, ...]
    coverage: tuple[str, ...]
    summary: str | None = None

    def __post_init__(self) -> None:
        entries = tuple(self.entries)
        coverage = tuple(self.coverage)
        if not entries:
            raise CompactionValidationError("compaction result has no entries")
        if coverage != tuple(entry.turn_id for entry in entries):
            raise CompactionValidationError("compaction coverage does not match entries")
        if len(set(coverage)) != len(coverage):
            raise CompactionValidationError("compaction coverage contains duplicate Turns")
        if self.summary is not None and (
            not isinstance(self.summary, str) or not self.summary.strip()
        ):
            raise CompactionValidationError("compaction summary must be non-empty text")
        object.__setattr__(self, "entries", entries)
        object.__setattr__(self, "coverage", coverage)


def parse_compaction_result(
    value: object,
    epoch: CompactionEpoch,
    *,
    summary_hard_cap: int,
    token_estimator: Callable[[str], int],
) -> CompactionStructuredResult:
    """Parse and validate one model response against the selected epoch.

    The normal protocol is a JSON object with ``entries`` and optional
    ``coverage``/``summary`` fields.  A plain text response is accepted only
    as a bounded compatibility form and is expanded to one identical Fine
    entry per selected Turn; it can never change refs or coverage.
    """

    if not isinstance(epoch, CompactionEpoch):
        raise TypeError("epoch must be a CompactionEpoch")
    if (
        isinstance(summary_hard_cap, bool)
        or not isinstance(summary_hard_cap, int)
        or summary_hard_cap <= 0
    ):
        raise ValueError("summary_hard_cap must be a positive integer")

    payload: Mapping[str, Any]
    if isinstance(value, CompactionStructuredResult):
        result = value
        _validate_entries_against_epoch(result.entries, result.coverage, epoch)
        _validate_summary_limits(result, summary_hard_cap, token_estimator)
        return result
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise CompactionValidationError("compaction response is empty")
        try:
            decoded = json.loads(text)
        except json.JSONDecodeError:
            # This fallback is intentionally bounded and cannot invent a
            # reference.  Structured multi-Turn output remains the preferred
            # production contract.
            entries = tuple(
                CompactionEntry(turn_id=unit.turn_id, summary=text, refs=(ref,))
                for unit, ref in zip(epoch.units, epoch.refs, strict=True)
            )
            result = CompactionStructuredResult(
                entries=entries,
                coverage=epoch.turn_ids,
                summary=text,
            )
            _validate_summary_limits(result, summary_hard_cap, token_estimator)
            return result
        if not isinstance(decoded, Mapping):
            raise CompactionValidationError("compaction JSON must be an object")
        payload = decoded
    elif isinstance(value, Mapping):
        payload = value
    else:
        raise CompactionValidationError("compaction response must be text or an object")

    raw_entries = payload.get("entries", payload.get("fine_entries"))
    if raw_entries is None:
        raw_summary = payload.get("summary")
        if isinstance(raw_summary, str):
            raw_entries = [{"turn_id": turn_id, "summary": raw_summary} for turn_id in epoch.turn_ids]
        else:
            raise CompactionValidationError("compaction response has no entries")
    if isinstance(raw_entries, (str, bytes, bytearray)) or not isinstance(raw_entries, Sequence):
        raise CompactionValidationError("compaction entries must be a sequence")
    if len(raw_entries) != len(epoch.units):
        raise CompactionValidationError("compaction must return one entry per covered Turn")

    entries: list[CompactionEntry] = []
    for raw, unit, expected_ref in zip(raw_entries, epoch.units, epoch.refs, strict=True):
        if isinstance(raw, str):
            raw = {"turn_id": unit.turn_id, "summary": raw}
        if not isinstance(raw, Mapping):
            raise CompactionValidationError("each compaction entry must be an object")
        turn_id = raw.get("turn_id")
        if turn_id != unit.turn_id:
            raise CompactionValidationError("compaction coverage is not contiguous")
        summary = raw.get("summary")
        if not isinstance(summary, str) or not summary.strip():
            raise CompactionValidationError("each compaction entry needs a summary")
        refs = _parse_refs(raw.get("refs"), expected_ref)
        entries.append(CompactionEntry(turn_id=turn_id, summary=summary, refs=refs))

    raw_coverage = payload.get("coverage")
    if raw_coverage is None:
        coverage = epoch.turn_ids
    else:
        if isinstance(raw_coverage, (str, bytes, bytearray)) or not isinstance(raw_coverage, Sequence):
            raise CompactionValidationError("compaction coverage must be a sequence")
        coverage_values: list[str] = []
        for item in raw_coverage:
            if isinstance(item, str):
                coverage_values.append(item)
            elif isinstance(item, Mapping) and isinstance(item.get("turn_id"), str):
                coverage_values.append(item["turn_id"])
            else:
                raise CompactionValidationError("compaction coverage contains an invalid Turn")
        coverage = tuple(coverage_values)

    result = CompactionStructuredResult(
        entries=tuple(entries),
        coverage=tuple(coverage),
        summary=payload.get("summary") if "summary" in payload else None,
    )
    if result.coverage != epoch.turn_ids:
        raise CompactionValidationError("compaction coverage does not match the raw epoch")
    _validate_entries_against_epoch(result.entries, result.coverage, epoch)
    _validate_summary_limits(result, summary_hard_cap, token_estimator)
    return result


def _parse_refs(raw: object, expected: TranscriptRef) -> tuple[TranscriptRef, ...]:
    if raw is None:
        return (expected,)
    if isinstance(raw, (str, bytes, bytearray)) or not isinstance(raw, Sequence):
        raise CompactionValidationError("compaction refs must be a sequence")
    parsed: list[TranscriptRef] = []
    for item in raw:
        try:
            if isinstance(item, TranscriptRef):
                ref = item
            elif isinstance(item, str):
                ref = TranscriptRef.from_token(item)
            elif isinstance(item, Mapping):
                ref = TranscriptRef.from_dict(item)
            else:
                raise ValueError
        except (KeyError, TypeError, ValueError):
            raise CompactionValidationError("compaction ref is malformed") from None
        parsed.append(ref)
    refs = tuple(parsed)
    if refs != (expected,):
        raise CompactionValidationError("compaction ref does not match the covered raw Turn")
    return refs


def _validate_entries_against_epoch(
    entries: Sequence[CompactionEntry],
    coverage: Sequence[str],
    epoch: CompactionEpoch,
) -> None:
    if tuple(coverage) != epoch.turn_ids:
        raise CompactionValidationError("compaction coverage does not match the raw epoch")
    if len(entries) != len(epoch.units):
        raise CompactionValidationError("compaction entry count does not match coverage")
    for entry, unit, expected_ref in zip(entries, epoch.units, epoch.refs, strict=True):
        if entry.turn_id != unit.turn_id or entry.refs != (expected_ref,):
            raise CompactionValidationError("compaction entry does not match raw evidence")


def _validate_summary_limits(
    result: CompactionStructuredResult,
    summary_hard_cap: int,
    token_estimator: Callable[[str], int],
) -> None:
    for entry in result.entries:
        estimate = token_estimator(entry.summary)
        if isinstance(estimate, bool) or not isinstance(estimate, int) or estimate < 0:
            raise ValueError("token estimator must return a non-negative integer")
        if estimate > summary_hard_cap:
            raise CompactionValidationError("summary_hard_cap_exceeded")
    if result.summary is not None:
        estimate = token_estimator(result.summary)
        if isinstance(estimate, bool) or not isinstance(estimate, int) or estimate < 0:
            raise ValueError("token estimator must return a non-negative integer")
        if estimate > summary_hard_cap:
            raise CompactionValidationError("summary_hard_cap_exceeded")


__all__ = [
    "CompactionEntry",
    "CompactionEpoch",
    "CompactionStructuredResult",
    "CompactionValidationError",
    "parse_compaction_result",
]
