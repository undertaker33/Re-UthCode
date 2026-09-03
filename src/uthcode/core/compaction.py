"""Provider-independent contracts for bounded semantic compaction.

The Core owns the shape and validation rules of an L4 result.  Provider and
Application code only supply the bounded raw epoch and the model response;
they do not get to choose Transcript coverage or durable record references.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .history import (
    ActiveCheckpoint,
    EpochMacroSummary,
    SemanticEntry,
    SemanticUnit,
    Timeline,
    Transcript,
    TranscriptEntry,
    TranscriptRef,
)
from .provider import CancellationToken


class CompactionValidationError(ValueError):
    """A model-produced compaction result is not a valid L4 candidate."""


class CompactionError(ValueError):
    """A bounded Compaction request could not produce a safe Timeline."""


class CompactionInProgress(CompactionError):
    """A second Compaction for the same Session was rejected by single-flight."""


@dataclass(frozen=True, slots=True)
class CompactionPolicy:
    """Provider-independent hard limits for one Compactor invocation."""

    input_budget: int = 64_000
    output_reserve: int = 4_096
    summary_hard_cap: int = 2_048

    def __post_init__(self) -> None:
        for field_name in ("input_budget", "output_reserve", "summary_hard_cap"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{field_name} must be a positive integer")
        if self.output_reserve >= self.input_budget:
            raise ValueError("output_reserve must be smaller than input_budget")
        if self.summary_hard_cap > self.input_budget - self.output_reserve:
            raise ValueError("summary_hard_cap must fit inside the Compaction input budget")

    @property
    def compaction_input_budget(self) -> int:
        return self.input_budget

    @property
    def compaction_output_reserve(self) -> int:
        return self.output_reserve

    @property
    def available_input_budget(self) -> int:
        return self.input_budget - self.output_reserve


@dataclass(frozen=True, slots=True)
class CompactionBatch:
    """One complete-semantic-unit batch sent to a tool-free summarizer."""

    unit_ids: tuple[str, ...]
    sequence_start: int
    sequence_end: int
    input_text: str
    input_tokens: int
    output_summary: str


@dataclass(frozen=True, slots=True)
class CompactionResult:
    """A bounded Timeline candidate; failed candidates retain old records."""

    timeline: Timeline | None
    summary: str | None
    batches: tuple[CompactionBatch, ...] = ()
    changed: bool = False
    failure: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0

    def __post_init__(self) -> None:
        if self.timeline is not None and not isinstance(self.timeline, Timeline):
            raise TypeError("timeline must be a Timeline or None")
        if self.summary is not None and not isinstance(self.summary, str):
            raise TypeError("summary must be a string or None")
        if not isinstance(self.changed, bool):
            raise TypeError("changed must be a boolean")
        if self.failure is not None and not isinstance(self.failure, str):
            raise TypeError("failure must be a string or None")
        for field_name in ("input_tokens", "output_tokens"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")
        object.__setattr__(self, "batches", tuple(self.batches))


@dataclass(frozen=True, slots=True)
class DeterministicTokenEstimator:
    """Stable fallback estimator used when no tokenizer is injected."""

    bytes_per_token: int = 4

    def __post_init__(self) -> None:
        if (
            isinstance(self.bytes_per_token, bool)
            or not isinstance(self.bytes_per_token, int)
            or self.bytes_per_token <= 0
        ):
            raise ValueError("bytes_per_token must be a positive integer")

    def __call__(self, text: str) -> int:
        if not isinstance(text, str):
            raise TypeError("token estimator input must be a string")
        if not text:
            return 0
        return max(
            1,
            (len(text.encode("utf-8")) + self.bytes_per_token - 1)
            // self.bytes_per_token,
        )


def _resolve_token_estimator(
    value: Callable[[str], int] | None,
) -> Callable[[str], int]:
    estimator = DeterministicTokenEstimator() if value is None else value
    if not callable(estimator):
        raise TypeError("token_estimator must be callable")
    return estimator


def _estimate_tokens(estimator: Callable[[str], int], text: str) -> int:
    value = estimator(text)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("token estimator must return a non-negative integer")
    return value


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
class CompactionSubpass:
    """One process-local input slice for an oversized complete Turn.

    A subpass deliberately has no generated identity.  Its source sequence
    numbers point back to the immutable Transcript only; the slice itself is
    discarded after the enclosing invocation succeeds or stops.
    """

    turn_id: str
    source_sequences: tuple[int, ...]
    input_text: str
    input_tokens: int
    input_budget: int
    output_reserve: int

    def __post_init__(self) -> None:
        if not isinstance(self.turn_id, str) or not self.turn_id:
            raise ValueError("turn_id must be a non-empty string")
        source_sequences = tuple(self.source_sequences)
        if not source_sequences or any(
            isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1
            for sequence in source_sequences
        ):
            raise CompactionValidationError("oversized subpass source coverage is invalid")
        if tuple(sorted(source_sequences)) != source_sequences:
            raise CompactionValidationError("oversized subpass source coverage is not ordered")
        if source_sequences != tuple(range(source_sequences[0], source_sequences[-1] + 1)):
            raise CompactionValidationError("oversized subpass source coverage is not contiguous")
        if not isinstance(self.input_text, str) or not self.input_text:
            raise ValueError("input_text must be a non-empty string")
        for field_name in ("input_tokens", "input_budget", "output_reserve"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")
        if self.input_budget <= 0 or self.output_reserve <= 0:
            raise ValueError("oversized subpass budgets must be positive")
        if self.output_reserve >= self.input_budget:
            raise ValueError("output_reserve must be smaller than input_budget")
        if self.input_tokens > self.input_budget - self.output_reserve:
            raise CompactionValidationError("oversized subpass exceeds available input budget")
        object.__setattr__(self, "source_sequences", source_sequences)

    @property
    def sequence_start(self) -> int:
        return self.source_sequences[0]

    @property
    def sequence_end(self) -> int:
        return self.source_sequences[-1]


@dataclass(frozen=True, slots=True)
class OversizedCompactionPlan:
    """A bounded, process-local plan for one oversized complete Turn."""

    session_id: str
    turn_id: str
    sequence_start: int
    sequence_end: int
    subpasses: tuple[CompactionSubpass, ...]
    input_budget: int
    output_reserve: int

    def __post_init__(self) -> None:
        if not isinstance(self.session_id, str) or not self.session_id:
            raise ValueError("session_id must be a non-empty string")
        if not isinstance(self.turn_id, str) or not self.turn_id:
            raise ValueError("turn_id must be a non-empty string")
        subpasses = tuple(self.subpasses)
        if not subpasses or not all(isinstance(item, CompactionSubpass) for item in subpasses):
            raise CompactionValidationError("oversized compaction plan has no valid subpasses")
        for field_name in ("sequence_start", "sequence_end", "input_budget", "output_reserve"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")
        if self.sequence_start < 1 or self.sequence_end < self.sequence_start:
            raise ValueError("oversized compaction sequence range is invalid")
        if self.input_budget <= 0 or self.output_reserve <= 0:
            raise ValueError("oversized compaction budgets must be positive")
        if self.output_reserve >= self.input_budget:
            raise ValueError("output_reserve must be smaller than input_budget")
        if any(
            item.turn_id != self.turn_id
            or item.input_budget != self.input_budget
            or item.output_reserve != self.output_reserve
            for item in subpasses
        ):
            raise CompactionValidationError("oversized subpass does not match plan")
        if subpasses[0].sequence_start < self.sequence_start:
            raise CompactionValidationError("oversized plan starts outside the source Turn")
        if subpasses[-1].sequence_end > self.sequence_end:
            raise CompactionValidationError("oversized plan ends outside the source Turn")
        if any(
            current.sequence_start < previous.sequence_start
            for previous, current in zip(subpasses, subpasses[1:], strict=False)
        ):
            raise CompactionValidationError("oversized plan subpasses are not ordered")
        covered = {
            sequence
            for item in subpasses
            for sequence in item.source_sequences
        }
        expected = set(range(self.sequence_start, self.sequence_end + 1))
        if covered != expected:
            raise CompactionValidationError("oversized plan does not cover the complete Turn")
        object.__setattr__(self, "subpasses", subpasses)

    @property
    def subpass_count(self) -> int:
        return len(self.subpasses)

    @property
    def refs(self) -> tuple[TranscriptRef, ...]:
        return (TranscriptRef(self.session_id, self.sequence_start, self.sequence_end),)


@dataclass(frozen=True, slots=True)
class OversizedSubpassResult:
    """Validated provider-independent output for one process-local subpass."""

    summary: str | None = None
    failure: str | None = None
    cancelled: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.cancelled, bool):
            raise TypeError("oversized subpass cancelled must be a boolean")
        if self.failure is not None and (
            not isinstance(self.failure, str) or not self.failure.strip()
        ):
            raise CompactionValidationError("oversized subpass failure is invalid")
        if self.failure is not None and self.cancelled:
            raise CompactionValidationError("oversized subpass cannot fail and cancel")
        if self.cancelled or self.failure is not None:
            if self.summary is not None:
                raise CompactionValidationError(
                    "failed oversized subpass cannot contain a summary"
                )
            return
        if not isinstance(self.summary, str) or not self.summary.strip():
            raise CompactionValidationError("oversized subpass summary is empty")


@dataclass(frozen=True, slots=True)
class OversizedFold:
    """One process-local bounded fold over successful summary outputs."""

    source_indices: tuple[int, ...]
    input_summaries: tuple[str, ...]
    input_text: str
    input_tokens: int
    input_budget: int
    output_reserve: int
    summary_hard_cap: int

    def __post_init__(self) -> None:
        source_indices = tuple(self.source_indices)
        input_summaries = tuple(self.input_summaries)
        if not source_indices or source_indices != tuple(
            range(source_indices[0], source_indices[-1] + 1)
        ):
            raise CompactionValidationError("oversized fold source range is invalid")
        if len(source_indices) != len(input_summaries) or any(
            not isinstance(summary, str) or not summary.strip()
            for summary in input_summaries
        ):
            raise CompactionValidationError("oversized fold summaries are invalid")
        if not isinstance(self.input_text, str) or not self.input_text:
            raise ValueError("oversized fold input_text must be non-empty")
        for field_name in (
            "input_tokens",
            "input_budget",
            "output_reserve",
            "summary_hard_cap",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")
        if self.input_budget <= 0 or self.output_reserve <= 0:
            raise ValueError("oversized fold budgets must be positive")
        if self.output_reserve >= self.input_budget:
            raise ValueError("oversized fold output_reserve must be smaller than input_budget")
        if self.summary_hard_cap <= 0:
            raise ValueError("oversized fold summary_hard_cap must be positive")
        if self.summary_hard_cap > self.input_budget - self.output_reserve:
            raise ValueError("oversized fold summary_hard_cap exceeds available input budget")
        if self.input_tokens > self.input_budget - self.output_reserve:
            raise CompactionValidationError("oversized fold exceeds available input budget")
        object.__setattr__(self, "source_indices", source_indices)
        object.__setattr__(self, "input_summaries", input_summaries)


@dataclass(frozen=True, slots=True)
class OversizedFoldPlan:
    """A process-local bounded fold round for an oversized Turn."""

    source_summaries: tuple[str, ...]
    folds: tuple[OversizedFold, ...]
    aggregate_input_text: str
    aggregate_input_tokens: int
    input_budget: int
    output_reserve: int
    summary_hard_cap: int

    def __post_init__(self) -> None:
        source_summaries = tuple(self.source_summaries)
        folds = tuple(self.folds)
        if not source_summaries or any(
            not isinstance(summary, str) or not summary.strip()
            for summary in source_summaries
        ):
            raise CompactionValidationError("oversized fold plan source summaries are invalid")
        if not folds or not all(isinstance(fold, OversizedFold) for fold in folds):
            raise CompactionValidationError("oversized fold plan has no valid folds")
        if not isinstance(self.aggregate_input_text, str) or not self.aggregate_input_text:
            raise ValueError("oversized fold aggregate input_text must be non-empty")
        for field_name in (
            "aggregate_input_tokens",
            "input_budget",
            "output_reserve",
            "summary_hard_cap",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")
        if self.input_budget <= 0 or self.output_reserve <= 0:
            raise ValueError("oversized fold plan budgets must be positive")
        if self.output_reserve >= self.input_budget:
            raise ValueError("oversized fold plan output_reserve must be smaller than input_budget")
        if self.summary_hard_cap <= 0:
            raise ValueError("oversized fold plan summary_hard_cap must be positive")
        if self.summary_hard_cap > self.input_budget - self.output_reserve:
            raise ValueError("oversized fold plan summary_hard_cap exceeds available input budget")
        if any(
            fold.input_budget != self.input_budget
            or fold.output_reserve != self.output_reserve
            or fold.summary_hard_cap != self.summary_hard_cap
            for fold in folds
        ):
            raise CompactionValidationError("oversized fold does not match plan budgets")
        flattened = tuple(index for fold in folds for index in fold.source_indices)
        if flattened != tuple(range(len(source_summaries))):
            raise CompactionValidationError("oversized fold plan does not cover source summaries")
        for fold in folds:
            expected = tuple(source_summaries[index] for index in fold.source_indices)
            if fold.input_summaries != expected:
                raise CompactionValidationError("oversized fold input does not match source summaries")
        object.__setattr__(self, "source_summaries", source_summaries)
        object.__setattr__(self, "folds", folds)

    @property
    def fold_count(self) -> int:
        return len(self.folds)


@dataclass(frozen=True, slots=True)
class OversizedFoldResult:
    """Validated provider-independent output for one process-local fold."""

    summary: str | None = None
    failure: str | None = None
    cancelled: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.cancelled, bool):
            raise TypeError("oversized fold cancelled must be a boolean")
        if self.failure is not None and (
            not isinstance(self.failure, str) or not self.failure.strip()
        ):
            raise CompactionValidationError("oversized fold failure is invalid")
        if self.failure is not None and self.cancelled:
            raise CompactionValidationError("oversized fold cannot fail and cancel")
        if self.cancelled or self.failure is not None:
            if self.summary is not None:
                raise CompactionValidationError("failed oversized fold cannot contain a summary")
            return
        if not isinstance(self.summary, str) or not self.summary.strip():
            raise CompactionValidationError("oversized fold summary is empty")


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


@dataclass(frozen=True, slots=True)
class TimelineAgingEpoch:
    """One bounded raw-evidence epoch selected for L5 Timeline aging.

    The Fine records are selection metadata only.  ``input_text`` is built
    exclusively from the corresponding complete raw Transcript units; it must
    never contain a Fine or Macro summary as model evidence.
    """

    session_id: str
    fine_entries: tuple[SemanticEntry, ...]
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
        fine_entries = tuple(self.fine_entries)
        units = tuple(self.units)
        if not units or len(fine_entries) != len(units):
            raise CompactionValidationError("TimelineAgingEpoch coverage is invalid")
        if not all(isinstance(entry, SemanticEntry) for entry in fine_entries):
            raise CompactionValidationError("TimelineAgingEpoch contains an invalid Fine record")
        if not all(isinstance(unit, SemanticUnit) and unit.complete for unit in units):
            raise CompactionValidationError("TimelineAgingEpoch contains an incomplete unit")
        if len({unit.unit_id for unit in units}) != len(units):
            raise CompactionValidationError("TimelineAgingEpoch unit IDs must be unique")
        if len({unit.turn_id for unit in units}) != len(units):
            raise CompactionValidationError("TimelineAgingEpoch Turn IDs must be unique")
        for entry, unit in zip(fine_entries, units, strict=True):
            expected = TranscriptRef(self.session_id, unit.sequence_start, unit.sequence_end)
            if (
                entry.session_id not in (None, self.session_id)
                or entry.turn_id != unit.turn_id
                or entry.refs != (expected,)
            ):
                raise CompactionValidationError("TimelineAgingEpoch Fine ownership is invalid")
        if any(
            transcript_entry.session_id != self.session_id
            for unit in units
            for transcript_entry in unit.entries
        ):
            raise CompactionValidationError("TimelineAgingEpoch raw ownership is invalid")
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
            raise ValueError("TimelineAgingEpoch budgets must be positive")
        if self.output_reserve >= self.input_budget:
            raise ValueError("output_reserve must be smaller than input_budget")
        if self.sequence_start != units[0].sequence_start:
            raise ValueError("sequence_start does not match the first unit")
        if self.sequence_end != units[-1].sequence_end:
            raise ValueError("sequence_end does not match the last unit")
        if self.sequence_start < 1 or self.sequence_end < self.sequence_start:
            raise ValueError("TimelineAgingEpoch sequence range is invalid")
        object.__setattr__(self, "fine_entries", fine_entries)
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
class TimelineAgingResult:
    """One Macro-only result returned by the L5 summarizer."""

    summary: str
    coverage: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.summary, str) or not self.summary.strip():
            raise CompactionValidationError("Timeline aging summary is empty")
        coverage = tuple(self.coverage)
        if not coverage or any(not isinstance(turn_id, str) or not turn_id for turn_id in coverage):
            raise CompactionValidationError("Timeline aging coverage is invalid")
        if len(set(coverage)) != len(coverage):
            raise CompactionValidationError("Timeline aging coverage contains duplicate Turns")
        object.__setattr__(self, "coverage", coverage)


def parse_timeline_aging_result(
    value: object,
    epoch: TimelineAgingEpoch,
    *,
    summary_hard_cap: int,
    token_estimator: Callable[[str], int],
) -> TimelineAgingResult:
    """Parse a Macro-only L5 response against one raw Fine epoch."""

    if not isinstance(epoch, TimelineAgingEpoch):
        raise TypeError("epoch must be a TimelineAgingEpoch")
    if (
        isinstance(summary_hard_cap, bool)
        or not isinstance(summary_hard_cap, int)
        or summary_hard_cap <= 0
    ):
        raise ValueError("summary_hard_cap must be a positive integer")
    if not callable(token_estimator):
        raise TypeError("token_estimator must be callable")

    payload: Mapping[str, Any]
    if isinstance(value, TimelineAgingResult):
        result = value
        if result.coverage != epoch.turn_ids:
            raise CompactionValidationError("Timeline aging coverage does not match raw evidence")
        _validate_timeline_aging_summary(result, summary_hard_cap, token_estimator)
        return result
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise CompactionValidationError("Timeline aging response is empty")
        try:
            decoded = json.loads(text)
        except json.JSONDecodeError:
            result = TimelineAgingResult(text, epoch.turn_ids)
            _validate_timeline_aging_summary(result, summary_hard_cap, token_estimator)
            return result
        if not isinstance(decoded, Mapping):
            raise CompactionValidationError("Timeline aging JSON must be an object")
        payload = decoded
    elif isinstance(value, Mapping):
        payload = value
    else:
        raise CompactionValidationError("Timeline aging response must be text or an object")

    if "entries" in payload or "fine_entries" in payload:
        raise CompactionValidationError("Timeline aging accepts one Macro summary only")
    summary = payload.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise CompactionValidationError("Timeline aging response has no summary")
    raw_coverage = payload.get("coverage")
    if raw_coverage is None:
        coverage = epoch.turn_ids
    elif isinstance(raw_coverage, Sequence) and not isinstance(raw_coverage, (str, bytes, bytearray)):
        values: list[str] = []
        for item in raw_coverage:
            if isinstance(item, str):
                values.append(item)
            elif isinstance(item, Mapping) and isinstance(item.get("turn_id"), str):
                values.append(item["turn_id"])
            else:
                raise CompactionValidationError("Timeline aging coverage contains an invalid Turn")
        coverage = tuple(values)
    else:
        raise CompactionValidationError("Timeline aging coverage must be a sequence")
    result = TimelineAgingResult(summary, tuple(coverage))
    if result.coverage != epoch.turn_ids:
        raise CompactionValidationError("Timeline aging coverage does not match raw evidence")
    _validate_timeline_aging_summary(result, summary_hard_cap, token_estimator)
    return result


def _validate_timeline_aging_summary(
    result: TimelineAgingResult,
    summary_hard_cap: int,
    token_estimator: Callable[[str], int],
) -> None:
    estimate = token_estimator(result.summary)
    if isinstance(estimate, bool) or not isinstance(estimate, int) or estimate < 0:
        raise ValueError("token estimator must return a non-negative integer")
    if estimate > summary_hard_cap:
        raise CompactionValidationError("summary_hard_cap_exceeded")


def parse_compaction_result(
    value: object,
    epoch: CompactionEpoch,
    *,
    summary_hard_cap: int,
    token_estimator: Callable[[str], int],
) -> CompactionStructuredResult:
    """Parse and validate one model response against the selected epoch.

    The normal protocol is a JSON object with explicit ``entries`` and
    ``coverage`` fields.  Multi-Turn responses must also carry one explicit
    ``refs`` sequence per entry.  Plain text, top-level ``summary`` and string
    entries remain only as bounded compatibility forms for a single Turn.
    """

    if not isinstance(epoch, CompactionEpoch):
        raise TypeError("epoch must be a CompactionEpoch")
    if (
        isinstance(summary_hard_cap, bool)
        or not isinstance(summary_hard_cap, int)
        or summary_hard_cap <= 0
    ):
        raise ValueError("summary_hard_cap must be a positive integer")

    multi_turn = len(epoch.units) > 1
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
            if multi_turn:
                raise CompactionValidationError(
                    "multi-Turn compaction response must be structured"
                )
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
        if isinstance(raw_summary, str) and not multi_turn:
            raw_entries = [{"turn_id": turn_id, "summary": raw_summary} for turn_id in epoch.turn_ids]
        else:
            raise CompactionValidationError(
                "multi-Turn compaction response requires explicit entries"
                if multi_turn
                else "compaction response has no entries"
            )
    if isinstance(raw_entries, (str, bytes, bytearray)) or not isinstance(raw_entries, Sequence):
        raise CompactionValidationError("compaction entries must be a sequence")
    if len(raw_entries) != len(epoch.units):
        raise CompactionValidationError("compaction must return one entry per covered Turn")

    entries: list[CompactionEntry] = []
    for raw, unit, expected_ref in zip(raw_entries, epoch.units, epoch.refs, strict=True):
        if isinstance(raw, str):
            if multi_turn:
                raise CompactionValidationError(
                    "multi-Turn compaction entries must be objects"
                )
            raw = {"turn_id": unit.turn_id, "summary": raw}
        if not isinstance(raw, Mapping):
            raise CompactionValidationError("each compaction entry must be an object")
        turn_id = raw.get("turn_id")
        if turn_id != unit.turn_id:
            raise CompactionValidationError("compaction coverage is not contiguous")
        summary = raw.get("summary")
        if not isinstance(summary, str) or not summary.strip():
            raise CompactionValidationError("each compaction entry needs a summary")
        if multi_turn and ("refs" not in raw or raw.get("refs") is None):
            raise CompactionValidationError(
                "multi-Turn compaction entries require explicit refs"
            )
        refs = _parse_refs(raw.get("refs"), expected_ref)
        entries.append(CompactionEntry(turn_id=turn_id, summary=summary, refs=refs))

    raw_coverage = payload.get("coverage")
    if raw_coverage is None:
        if multi_turn:
            raise CompactionValidationError(
                "multi-Turn compaction response requires explicit coverage"
            )
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


def parse_oversized_subpass_result(
    value: object,
    subpass: CompactionSubpass,
    *,
    summary_hard_cap: int,
    token_estimator: Callable[[str], int],
) -> OversizedSubpassResult:
    """Validate one process-local oversized subpass response.

    Subpass output is intentionally a summary-only contract.  It cannot carry
    refs, Turn identity, or a Timeline record because those belong to the
    enclosing complete Turn and are synthesized only after every subpass has
    succeeded.
    """

    if not isinstance(subpass, CompactionSubpass):
        raise TypeError("subpass must be a CompactionSubpass")
    if (
        isinstance(summary_hard_cap, bool)
        or not isinstance(summary_hard_cap, int)
        or summary_hard_cap <= 0
    ):
        raise ValueError("summary_hard_cap must be a positive integer")
    if not callable(token_estimator):
        raise TypeError("token_estimator must be callable")

    if isinstance(value, OversizedSubpassResult):
        result = value
    elif isinstance(value, str):
        result = OversizedSubpassResult(value.strip())
    elif isinstance(value, Mapping):
        if any(key in value for key in ("entries", "fine_entries", "refs", "coverage")):
            raise CompactionValidationError(
                "oversized subpass response cannot contain durable coverage"
            )
        if value.get("cancelled") is True:
            result = OversizedSubpassResult(cancelled=True)
        elif value.get("failure") is not None:
            failure = value.get("failure")
            if not isinstance(failure, str):
                raise CompactionValidationError("oversized subpass failure is invalid")
            result = OversizedSubpassResult(failure=failure.strip())
        else:
            summary = value.get("summary")
            if not isinstance(summary, str):
                raise CompactionValidationError("oversized subpass response has no summary")
            result = OversizedSubpassResult(summary.strip())
    else:
        raise CompactionValidationError("oversized subpass response must be text or an object")

    if result.summary is not None:
        estimate = token_estimator(result.summary)
        if isinstance(estimate, bool) or not isinstance(estimate, int) or estimate < 0:
            raise ValueError("token estimator must return a non-negative integer")
        if estimate > summary_hard_cap:
            raise CompactionValidationError("summary_hard_cap_exceeded")
    return result


def parse_oversized_fold_result(
    value: object,
    fold: OversizedFold,
    *,
    summary_hard_cap: int,
    token_estimator: Callable[[str], int],
) -> OversizedFoldResult:
    """Validate one process-local fold response without durable coverage."""

    if not isinstance(fold, OversizedFold):
        raise TypeError("fold must be an OversizedFold")
    if (
        isinstance(summary_hard_cap, bool)
        or not isinstance(summary_hard_cap, int)
        or summary_hard_cap <= 0
    ):
        raise ValueError("summary_hard_cap must be a positive integer")
    if not callable(token_estimator):
        raise TypeError("token_estimator must be callable")

    if isinstance(value, OversizedFoldResult):
        result = value
    elif isinstance(value, str):
        result = OversizedFoldResult(value.strip())
    elif isinstance(value, Mapping):
        if any(key in value for key in ("entries", "fine_entries", "refs", "coverage")):
            raise CompactionValidationError(
                "oversized fold response cannot contain durable coverage"
            )
        if value.get("cancelled") is True:
            result = OversizedFoldResult(cancelled=True)
        elif value.get("failure") is not None:
            failure = value.get("failure")
            if not isinstance(failure, str):
                raise CompactionValidationError("oversized fold failure is invalid")
            result = OversizedFoldResult(failure=failure.strip())
        else:
            summary = value.get("summary")
            if not isinstance(summary, str):
                raise CompactionValidationError("oversized fold response has no summary")
            result = OversizedFoldResult(summary.strip())
    else:
        raise CompactionValidationError("oversized fold response must be text or an object")

    if result.summary is not None:
        estimate = token_estimator(result.summary)
        if isinstance(estimate, bool) or not isinstance(estimate, int) or estimate < 0:
            raise ValueError("token estimator must return a non-negative integer")
        if estimate > summary_hard_cap:
            raise CompactionValidationError("summary_hard_cap_exceeded")
    return result


class ContextCompactor:
    """Create bounded Timeline candidates without Provider or Tool access."""

    def __init__(
        self,
        policy: CompactionPolicy | None = None,
        *,
        token_estimator: Callable[[str], int] | None = None,
    ) -> None:
        self.policy = policy or CompactionPolicy()
        if not isinstance(self.policy, CompactionPolicy):
            raise TypeError("policy must be a CompactionPolicy or None")
        self.token_estimator = _resolve_token_estimator(token_estimator)
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def _validate_transcript_and_timeline(
        self,
        transcript: Transcript,
        timeline: Timeline | None,
        session_id: str | None,
    ) -> str:
        if not isinstance(transcript, Transcript):
            raise TypeError("transcript must be a Transcript")
        if timeline is not None and not isinstance(timeline, Timeline):
            raise TypeError("timeline must be a Timeline or None")
        if timeline is not None and timeline.session_id != transcript.session_id:
            raise CompactionError("transcript and timeline belong to different Sessions")
        owner = transcript.session_id if session_id is None else session_id
        if not isinstance(owner, str) or not owner:
            raise ValueError("session_id must be a non-empty string")
        if owner != transcript.session_id:
            raise CompactionError("Compaction Session does not own the supplied Transcript")
        return owner

    def _budgets(
        self,
        input_budget: int | None,
        output_reserve: int | None,
    ) -> tuple[int, int]:
        selected_input_budget = self.policy.input_budget if input_budget is None else input_budget
        selected_output_reserve = (
            self.policy.output_reserve if output_reserve is None else output_reserve
        )
        if (
            isinstance(selected_input_budget, bool)
            or not isinstance(selected_input_budget, int)
            or selected_input_budget <= 0
            or isinstance(selected_output_reserve, bool)
            or not isinstance(selected_output_reserve, int)
            or selected_output_reserve <= 0
            or selected_output_reserve >= selected_input_budget
        ):
            raise ValueError("compaction budgets are invalid")
        return selected_input_budget, selected_output_reserve

    def _pending_units(
        self,
        transcript: Transcript,
        timeline: Timeline | None,
    ) -> tuple[SemanticUnit, ...]:
        covered_end = timeline.sequence_end if timeline is not None else 0
        pending: list[SemanticUnit] = []
        for unit in transcript.semantic_units():
            if unit.sequence_end <= covered_end:
                continue
            # A later complete unit must not leap over an open unit: doing so
            # would advance the Timeline checkpoint past uncovered evidence.
            if not unit.complete:
                break
            pending.append(unit)
        return tuple(pending)

    def plan_epoch(
        self,
        transcript: Transcript,
        *,
        timeline: Timeline | None = None,
        session_id: str | None = None,
        input_budget: int | None = None,
        output_reserve: int | None = None,
    ) -> CompactionEpoch | None:
        """Derive the next bounded complete raw epoch.

        Oversized units are deliberately excluded from this ordinary epoch
        shape.  Callers that receive no ordinary epoch may ask
        :meth:`plan_oversized_turn` for the oldest complete unit.
        """

        self._validate_transcript_and_timeline(transcript, timeline, session_id)
        selected_input_budget, selected_output_reserve = self._budgets(
            input_budget, output_reserve
        )
        units = self._pending_units(transcript, timeline)
        if not units:
            return None
        available = selected_input_budget - selected_output_reserve
        selected: list[SemanticUnit] = []
        for unit in units:
            candidate = (*selected, unit)
            candidate_text = _compaction_input_text("", candidate)
            candidate_tokens = self._estimate(candidate_text)
            if not selected and candidate_tokens > available:
                return None
            if candidate_tokens > available:
                break
            selected.append(unit)
        if not selected:
            return None
        input_text = _compaction_input_text("", selected)
        input_tokens = self._estimate(input_text)
        return CompactionEpoch(
            session_id=transcript.session_id,
            units=tuple(selected),
            input_text=input_text,
            input_tokens=input_tokens,
            input_budget=selected_input_budget,
            output_reserve=selected_output_reserve,
            sequence_start=selected[0].sequence_start,
            sequence_end=selected[-1].sequence_end,
        )

    def plan_oversized_turn(
        self,
        transcript: Transcript,
        *,
        timeline: Timeline | None = None,
        session_id: str | None = None,
        input_budget: int | None = None,
        output_reserve: int | None = None,
    ) -> OversizedCompactionPlan | None:
        """Plan process-local slices for the oldest oversized complete Turn."""

        self._validate_transcript_and_timeline(transcript, timeline, session_id)
        selected_input_budget, selected_output_reserve = self._budgets(
            input_budget, output_reserve
        )
        units = self._pending_units(transcript, timeline)
        if not units:
            return None
        unit = units[0]
        available = selected_input_budget - selected_output_reserve
        if self._estimate(_compaction_input_text("", (unit,))) <= available:
            return None
        return self._build_oversized_plan(
            transcript,
            unit,
            input_budget=selected_input_budget,
            output_reserve=selected_output_reserve,
        )

    def _build_oversized_plan(
        self,
        transcript: Transcript,
        unit: SemanticUnit,
        *,
        input_budget: int,
        output_reserve: int,
    ) -> OversizedCompactionPlan | None:
        available = input_budget - output_reserve
        encoded_chunks: list[tuple[str, tuple[int, ...]]] = []
        pending_text: list[str] = []
        pending_sequences: list[int] = []

        def frame(parts: Sequence[str]) -> str:
            return "Complete raw semantic unit parts:\n" + "\n".join(parts)

        def flush() -> None:
            nonlocal pending_text, pending_sequences
            if pending_text:
                encoded_chunks.append((frame(pending_text), tuple(pending_sequences)))
                pending_text = []
                pending_sequences = []

        for entry in unit.entries:
            encoded = _encode_transcript_entry(entry)
            candidate = frame((*pending_text, encoded))
            if self._estimate(candidate) <= available:
                pending_text.append(encoded)
                pending_sequences.append(entry.sequence)
                continue
            flush()
            if self._estimate(frame((encoded,))) <= available:
                pending_text.append(encoded)
                pending_sequences.append(entry.sequence)
                continue

            text = _entry_text_value(entry)
            if text is None:
                return None
            segments = self._split_oversized_entry(entry, text, frame, available)
            if segments is None:
                return None
            for segment in segments:
                flush()
                encoded_segment = _encode_transcript_entry(entry, text_override=segment)
                encoded_chunks.append((frame((encoded_segment,)), (entry.sequence,)))
        flush()
        if not encoded_chunks:
            return None
        try:
            subpasses = tuple(
                CompactionSubpass(
                    turn_id=unit.turn_id,
                    source_sequences=sequences,
                    input_text=input_text,
                    input_tokens=self._estimate(input_text),
                    input_budget=input_budget,
                    output_reserve=output_reserve,
                )
                for input_text, sequences in encoded_chunks
            )
            return OversizedCompactionPlan(
                session_id=transcript.session_id,
                turn_id=unit.turn_id,
                sequence_start=unit.sequence_start,
                sequence_end=unit.sequence_end,
                subpasses=subpasses,
                input_budget=input_budget,
                output_reserve=output_reserve,
            )
        except (TypeError, ValueError, CompactionValidationError):
            return None

    def _split_oversized_entry(
        self,
        entry: TranscriptEntry,
        text: str,
        frame: Callable[[Sequence[str]], str],
        available: int,
    ) -> tuple[str, ...] | None:
        if not text:
            return None
        segments: list[str] = []
        offset = 0
        while offset < len(text):
            low = 1
            high = len(text) - offset
            best: str | None = None
            while low <= high:
                size = (low + high) // 2
                candidate = text[offset : offset + size]
                encoded = _encode_transcript_entry(entry, text_override=candidate)
                if self._estimate(frame((encoded,))) <= available:
                    best = candidate
                    low = size + 1
                else:
                    high = size - 1
            if best is None:
                return None
            segments.append(best)
            offset += len(best)
        return tuple(segments)

    def parse_oversized_subpass_result(
        self,
        value: object,
        *,
        subpass: CompactionSubpass,
        summary_hard_cap: int | None = None,
    ) -> OversizedSubpassResult:
        return parse_oversized_subpass_result(
            value,
            subpass,
            summary_hard_cap=(
                self.policy.summary_hard_cap
                if summary_hard_cap is None
                else summary_hard_cap
            ),
            token_estimator=self._estimate,
        )

    def _normalize_fold_summaries(
        self,
        summaries: Sequence[object],
        *,
        summary_hard_cap: int,
    ) -> tuple[str, ...]:
        if isinstance(summaries, (str, bytes, bytearray)) or not isinstance(summaries, Sequence):
            raise TypeError("fold summaries must be a sequence")
        normalized: list[str] = []
        for value in summaries:
            if isinstance(value, OversizedSubpassResult):
                if value.cancelled or value.failure is not None or value.summary is None:
                    raise CompactionValidationError(
                        "oversized fold requires successful subpass summaries"
                    )
                summary = value.summary
            elif isinstance(value, OversizedFoldResult):
                if value.cancelled or value.failure is not None or value.summary is None:
                    raise CompactionValidationError(
                        "oversized fold requires successful fold summaries"
                    )
                summary = value.summary
            elif isinstance(value, str):
                summary = value.strip()
            else:
                raise CompactionValidationError(
                    "oversized fold source must be a successful summary"
                )
            if not summary:
                raise CompactionValidationError("oversized fold source summary is empty")
            if self._estimate(summary) > summary_hard_cap:
                raise CompactionValidationError("summary_hard_cap_exceeded")
            normalized.append(summary)
        if not normalized:
            raise CompactionValidationError("oversized fold has no source summaries")
        return tuple(normalized)

    def plan_oversized_fold_round(
        self,
        summaries: Sequence[object],
        *,
        input_budget: int | None = None,
        output_reserve: int | None = None,
        summary_hard_cap: int | None = None,
    ) -> OversizedFoldPlan | None:
        """Plan one bounded process-local fold round over summary outputs.

        A ``None`` result means the current summaries already form one bounded
        final summary.  Otherwise every returned fold input is within the
        available input budget.  Callers may feed the successful fold outputs
        back into this method for another round; no round state is persisted.
        """

        selected_input_budget, selected_output_reserve = self._budgets(
            input_budget, output_reserve
        )
        available = selected_input_budget - selected_output_reserve
        cap = self.policy.summary_hard_cap if summary_hard_cap is None else summary_hard_cap
        if (
            isinstance(cap, bool)
            or not isinstance(cap, int)
            or cap <= 0
            or cap > available
        ):
            raise ValueError("oversized fold summary_hard_cap is invalid")
        normalized = self._normalize_fold_summaries(
            summaries,
            summary_hard_cap=cap,
        )
        aggregate_input_text = _oversized_fold_input_text(normalized)
        aggregate_input_tokens = self._estimate(aggregate_input_text)
        aggregate_summary_tokens = self._estimate("\n".join(normalized))
        if aggregate_input_tokens <= available and aggregate_summary_tokens <= cap:
            return None

        folds: list[OversizedFold] = []
        current_indices: list[int] = []
        current_summaries: list[str] = []

        def append_fold() -> None:
            if not current_indices:
                return
            input_summaries = tuple(current_summaries)
            input_text = _oversized_fold_input_text(input_summaries)
            input_tokens = self._estimate(input_text)
            folds.append(
                OversizedFold(
                    source_indices=tuple(current_indices),
                    input_summaries=input_summaries,
                    input_text=input_text,
                    input_tokens=input_tokens,
                    input_budget=selected_input_budget,
                    output_reserve=selected_output_reserve,
                    summary_hard_cap=cap,
                )
            )

        for index, summary in enumerate(normalized):
            candidate = (*current_summaries, summary)
            if self._estimate(_oversized_fold_input_text(candidate)) <= available:
                current_indices.append(index)
                current_summaries.append(summary)
                continue
            append_fold()
            current_indices = [index]
            current_summaries = [summary]
            if self._estimate(_oversized_fold_input_text(current_summaries)) > available:
                raise CompactionValidationError(
                    "oversized fold source summary cannot fit available input budget"
                )
        append_fold()
        return OversizedFoldPlan(
            source_summaries=normalized,
            folds=tuple(folds),
            aggregate_input_text=aggregate_input_text,
            aggregate_input_tokens=aggregate_input_tokens,
            input_budget=selected_input_budget,
            output_reserve=selected_output_reserve,
            summary_hard_cap=cap,
        )

    def parse_oversized_fold_result(
        self,
        value: object,
        *,
        fold: OversizedFold,
        summary_hard_cap: int | None = None,
    ) -> OversizedFoldResult:
        if not isinstance(fold, OversizedFold):
            raise TypeError("fold must be an OversizedFold")
        return parse_oversized_fold_result(
            value,
            fold,
            summary_hard_cap=(
                self.policy.summary_hard_cap
                if summary_hard_cap is None
                else summary_hard_cap
            ),
            token_estimator=self._estimate,
        )

    def build_oversized_candidate(
        self,
        transcript: Transcript,
        *,
        plan: OversizedCompactionPlan,
        subpass_results: Sequence[object],
        timeline: Timeline | None = None,
        fold_results: Sequence[Sequence[object]] = (),
        summary_hard_cap: int | None = None,
        cancellation: CancellationToken | None = None,
    ) -> CompactionResult:
        """Synthesize one complete-Turn Fine after every bounded fold succeeds."""

        self._validate_transcript_and_timeline(transcript, timeline, None)
        if not isinstance(plan, OversizedCompactionPlan):
            raise TypeError("plan must be an OversizedCompactionPlan")
        if plan.session_id != transcript.session_id:
            raise CompactionError("oversized plan belongs to another Session")
        if timeline is not None and timeline.sequence_end >= plan.sequence_end:
            raise CompactionValidationError("oversized Turn is already covered")
        units = transcript.semantic_units(complete_only=True)
        unit = next(
            (candidate for candidate in units if candidate.turn_id == plan.turn_id),
            None,
        )
        if unit is None or unit.sequence_start != plan.sequence_start or unit.sequence_end != plan.sequence_end:
            raise CompactionValidationError("oversized plan does not match the complete Turn")
        if cancellation is not None and not isinstance(cancellation, CancellationToken):
            raise TypeError("cancellation must be a CancellationToken or None")
        if cancellation is not None and cancellation.cancelled:
            return CompactionResult(
                timeline=timeline,
                summary=timeline.summary if timeline is not None else None,
                changed=False,
                failure="compaction_cancelled",
            )
        cap = self.policy.summary_hard_cap if summary_hard_cap is None else summary_hard_cap
        if (
            isinstance(cap, bool)
            or not isinstance(cap, int)
            or cap <= 0
        ):
            raise ValueError("summary_hard_cap must be a positive integer")
        values = tuple(subpass_results)
        if len(values) != plan.subpass_count:
            raise CompactionValidationError("oversized subpass result count does not match plan")
        parsed = tuple(
            self.parse_oversized_subpass_result(
                value,
                subpass=subpass,
                summary_hard_cap=summary_hard_cap,
            )
            for value, subpass in zip(values, plan.subpasses, strict=True)
        )
        if any(item.cancelled for item in parsed):
            return CompactionResult(
                timeline=timeline,
                summary=timeline.summary if timeline is not None else None,
                changed=False,
                failure="compaction_cancelled",
            )
        failed = next((item for item in parsed if item.failure is not None), None)
        if failed is not None:
            return CompactionResult(
                timeline=timeline,
                summary=timeline.summary if timeline is not None else None,
                changed=False,
                failure=failed.failure or "oversized_subpass_failed",
            )
        if cancellation is not None and cancellation.cancelled:
            return CompactionResult(
                timeline=timeline,
                summary=timeline.summary if timeline is not None else None,
                changed=False,
                failure="compaction_cancelled",
            )
        if isinstance(fold_results, (str, bytes, bytearray)) or not isinstance(
            fold_results, Sequence
        ):
            raise TypeError("fold_results must be a sequence of result rounds")
        fold_rounds = tuple(fold_results)
        for round_values in fold_rounds:
            if isinstance(round_values, (str, bytes, bytearray)) or not isinstance(
                round_values, Sequence
            ):
                raise TypeError("each oversized fold result round must be a sequence")

        current: tuple[object, ...] = parsed
        fold_round_index = 0
        fold_input_tokens = 0
        for _ in range(8):
            try:
                fold_plan = self.plan_oversized_fold_round(
                    current,
                    input_budget=plan.input_budget,
                    output_reserve=plan.output_reserve,
                    summary_hard_cap=cap,
                )
            except CompactionValidationError:
                return CompactionResult(
                    timeline=timeline,
                    summary=timeline.summary if timeline is not None else None,
                    changed=False,
                    failure="oversized_fold_unplannable",
                )
            if fold_plan is None:
                break
            if fold_round_index >= len(fold_rounds):
                return CompactionResult(
                    timeline=timeline,
                    summary=timeline.summary if timeline is not None else None,
                    changed=False,
                    failure="oversized_fold_required",
                )
            raw_results = tuple(fold_rounds[fold_round_index])
            if len(raw_results) != fold_plan.fold_count:
                raise CompactionValidationError(
                    "oversized fold result count does not match plan"
                )
            fold_parsed = tuple(
                self.parse_oversized_fold_result(
                    value,
                    fold=fold,
                    summary_hard_cap=cap,
                )
                for value, fold in zip(raw_results, fold_plan.folds, strict=True)
            )
            if any(item.cancelled for item in fold_parsed):
                return CompactionResult(
                    timeline=timeline,
                    summary=timeline.summary if timeline is not None else None,
                    changed=False,
                    failure="compaction_cancelled",
                )
            fold_failed = next((item for item in fold_parsed if item.failure is not None), None)
            if fold_failed is not None:
                return CompactionResult(
                    timeline=timeline,
                    summary=timeline.summary if timeline is not None else None,
                    changed=False,
                    failure=fold_failed.failure or "oversized_fold_failed",
                )
            if cancellation is not None and cancellation.cancelled:
                return CompactionResult(
                    timeline=timeline,
                    summary=timeline.summary if timeline is not None else None,
                    changed=False,
                    failure="compaction_cancelled",
                )
            fold_input_tokens += sum(fold.input_tokens for fold in fold_plan.folds)
            current = fold_parsed
            fold_round_index += 1
        else:
            return CompactionResult(
                timeline=timeline,
                summary=timeline.summary if timeline is not None else None,
                changed=False,
                failure="oversized_fold_limit_reached",
            )

        if fold_round_index != len(fold_rounds):
            raise CompactionValidationError("oversized fold result has extra rounds")
        summary_parts = self._normalize_fold_summaries(
            current,
            summary_hard_cap=cap,
        )
        summary = "\n".join(summary_parts).strip()
        if not summary:
            raise CompactionValidationError("oversized final summary is empty")
        if self._estimate(summary) > cap:
            raise CompactionValidationError("summary_hard_cap_exceeded")
        ref = TranscriptRef(transcript.session_id, plan.sequence_start, plan.sequence_end)
        entry = SemanticEntry(
            turn_id=plan.turn_id,
            summary=summary,
            refs=(ref,),
            session_id=transcript.session_id,
        )
        checkpoint = ActiveCheckpoint(
            turn_id=plan.turn_id,
            active_turns=(plan.turn_id,),
            session_id=transcript.session_id,
        )
        candidate_timeline = (timeline or Timeline(transcript.session_id)).append_transaction(
            (entry,), checkpoint
        )
        batches = tuple(
            CompactionBatch(
                unit_ids=(unit.unit_id,),
                sequence_start=subpass.sequence_start,
                sequence_end=subpass.sequence_end,
                input_text=subpass.input_text,
                input_tokens=subpass.input_tokens,
                output_summary=result.summary,
            )
            for subpass, result in zip(plan.subpasses, parsed, strict=True)
        )
        return CompactionResult(
            timeline=candidate_timeline,
            summary=summary,
            batches=batches,
            changed=True,
            input_tokens=sum(item.input_tokens for item in plan.subpasses) + fold_input_tokens,
            output_tokens=self._estimate(summary),
        )

    def build_epoch_candidate(
        self,
        transcript: Transcript,
        *,
        epoch: CompactionEpoch,
        result: CompactionStructuredResult,
        timeline: Timeline | None = None,
    ) -> CompactionResult:
        """Validate one structured L4 result and build a checkpoint candidate."""

        if not isinstance(transcript, Transcript):
            raise TypeError("transcript must be a Transcript")
        if not isinstance(epoch, CompactionEpoch):
            raise TypeError("epoch must be a CompactionEpoch")
        if epoch.session_id != transcript.session_id:
            raise CompactionError("Compaction epoch belongs to another Session")
        if timeline is not None and (
            not isinstance(timeline, Timeline) or timeline.session_id != transcript.session_id
        ):
            raise CompactionError("transcript and timeline belong to different Sessions")
        if not isinstance(result, CompactionStructuredResult):
            raise TypeError("result must be a CompactionStructuredResult")
        if tuple(result.coverage) != epoch.turn_ids:
            raise CompactionValidationError("compaction coverage does not match the raw epoch")

        derived: list[SemanticEntry] = []
        batches: list[CompactionBatch] = []
        for entry, unit, expected_ref in zip(result.entries, epoch.units, epoch.refs, strict=True):
            if (
                not isinstance(entry, CompactionEntry)
                or entry.turn_id != unit.turn_id
                or entry.refs != (expected_ref,)
            ):
                raise CompactionValidationError("compaction entry does not match raw evidence")
            derived.append(
                SemanticEntry(
                    turn_id=entry.turn_id,
                    summary=entry.summary,
                    refs=entry.refs,
                    session_id=transcript.session_id,
                )
            )
            batches.append(
                CompactionBatch(
                    unit_ids=(unit.unit_id,),
                    sequence_start=unit.sequence_start,
                    sequence_end=unit.sequence_end,
                    input_text=epoch.input_text,
                    input_tokens=epoch.input_tokens,
                    output_summary=entry.summary,
                )
            )
        checkpoint = ActiveCheckpoint(
            turn_id=derived[-1].turn_id,
            active_turns=tuple(entry.turn_id for entry in derived),
            session_id=transcript.session_id,
        )
        candidate_timeline = (timeline or Timeline(transcript.session_id)).append_transaction(
            tuple(derived), checkpoint
        )
        output_tokens = sum(self._estimate(entry.summary) for entry in result.entries)
        return CompactionResult(
            timeline=candidate_timeline,
            summary=result.summary or result.entries[-1].summary,
            batches=tuple(batches),
            changed=True,
            input_tokens=epoch.input_tokens,
            output_tokens=output_tokens,
        )

    def plan_timeline_aging_epoch(
        self,
        transcript: Transcript,
        *,
        timeline: Timeline | None = None,
        session_id: str | None = None,
        input_budget: int | None = None,
        output_reserve: int | None = None,
    ) -> TimelineAgingEpoch | None:
        """Select the oldest safe committed Fine epoch for L5 aging."""

        if not isinstance(transcript, Transcript):
            raise TypeError("transcript must be a Transcript")
        if timeline is None:
            return None
        if not isinstance(timeline, Timeline) or timeline.session_id != transcript.session_id:
            raise CompactionError("transcript and timeline belong to different Sessions")
        owner = transcript.session_id if session_id is None else session_id
        if not isinstance(owner, str) or not owner:
            raise ValueError("session_id must be a non-empty string")
        if owner != transcript.session_id:
            raise CompactionError("Timeline aging Session does not own the supplied Transcript")
        selected_input_budget, selected_output_reserve = self._budgets(
            input_budget, output_reserve
        )

        active_fine = timeline.fine_entries
        active_by_turn = {entry.turn_id: entry for entry in active_fine}
        if not active_by_turn or len(active_by_turn) != len(active_fine):
            return None
        units_by_range = {
            (unit.sequence_start, unit.sequence_end): unit
            for unit in transcript.semantic_units(complete_only=True)
        }
        available = selected_input_budget - selected_output_reserve

        for group in timeline.transaction_groups():
            if not group or not isinstance(group[-1], ActiveCheckpoint):
                continue
            derived = tuple(
                record
                for record in group[:-1]
                if isinstance(record, (SemanticEntry, EpochMacroSummary))
            )
            if not derived:
                continue
            if any(isinstance(record, EpochMacroSummary) for record in derived):
                continue
            fine_records = tuple(record for record in derived if isinstance(record, SemanticEntry))
            if len(fine_records) != len(derived):
                return None
            if len({record.turn_id for record in fine_records}) != len(fine_records):
                return None
            active_flags = tuple(
                record.turn_id in active_by_turn and active_by_turn[record.turn_id] == record
                for record in fine_records
            )
            if not any(active_flags):
                continue
            if not all(active_flags):
                return None

            units: list[SemanticUnit] = []
            for fine in fine_records:
                if len(fine.refs) != 1:
                    return None
                ref = fine.refs[0]
                if ref.session_id != transcript.session_id or fine.session_id not in (None, owner):
                    return None
                unit = units_by_range.get((ref.sequence_start, ref.sequence_end))
                if unit is None or unit.turn_id != fine.turn_id:
                    return None
                try:
                    transcript.select(ref.sequence_start, ref.sequence_end, complete_only=True)
                except (TypeError, ValueError):
                    return None
                units.append(unit)
            if not units:
                continue
            if tuple(unit.sequence_start for unit in units) != tuple(
                sorted(unit.sequence_start for unit in units)
            ):
                return None
            if any(
                current.sequence_start != previous.sequence_end + 1
                for previous, current in zip(units, units[1:], strict=False)
            ):
                return None
            raw_units = tuple(units)
            input_text = _timeline_aging_input_text(raw_units)
            input_tokens = self._estimate(input_text)
            if input_tokens > available:
                return None
            try:
                return TimelineAgingEpoch(
                    session_id=owner,
                    fine_entries=fine_records,
                    units=raw_units,
                    input_text=input_text,
                    input_tokens=input_tokens,
                    input_budget=selected_input_budget,
                    output_reserve=selected_output_reserve,
                    sequence_start=raw_units[0].sequence_start,
                    sequence_end=raw_units[-1].sequence_end,
                )
            except (TypeError, ValueError):
                return None
        return None

    def parse_timeline_aging_result(
        self,
        value: object,
        *,
        epoch: TimelineAgingEpoch,
        summary_hard_cap: int | None = None,
    ) -> TimelineAgingResult:
        if not isinstance(epoch, TimelineAgingEpoch):
            raise TypeError("epoch must be a TimelineAgingEpoch")
        return parse_timeline_aging_result(
            value,
            epoch,
            summary_hard_cap=(
                self.policy.summary_hard_cap
                if summary_hard_cap is None
                else summary_hard_cap
            ),
            token_estimator=self._estimate,
        )

    def build_timeline_aging_candidate(
        self,
        transcript: Transcript,
        *,
        epoch: TimelineAgingEpoch,
        result: TimelineAgingResult,
        timeline: Timeline,
    ) -> CompactionResult:
        if not isinstance(transcript, Transcript):
            raise TypeError("transcript must be a Transcript")
        if not isinstance(epoch, TimelineAgingEpoch):
            raise TypeError("epoch must be a TimelineAgingEpoch")
        if not isinstance(result, TimelineAgingResult):
            raise TypeError("result must be a TimelineAgingResult")
        if not isinstance(timeline, Timeline) or timeline.session_id != transcript.session_id:
            raise CompactionError("transcript and timeline belong to different Sessions")
        if epoch.session_id != transcript.session_id or result.coverage != epoch.turn_ids:
            raise CompactionValidationError("Timeline aging result does not match raw evidence")
        active_fine = timeline.fine_entries
        if any(entry not in active_fine for entry in epoch.fine_entries):
            raise CompactionValidationError("Timeline aging Fine evidence is no longer active")
        for fine, unit, ref in zip(epoch.fine_entries, epoch.units, epoch.refs, strict=True):
            if fine.turn_id != unit.turn_id or fine.refs != (ref,):
                raise CompactionValidationError("Timeline aging Fine evidence is not exact")
            try:
                transcript.select(ref.sequence_start, ref.sequence_end, complete_only=True)
            except (TypeError, ValueError) as exc:
                raise CompactionValidationError("Timeline aging raw evidence is invalid") from exc

        macro = EpochMacroSummary(
            turn_id=epoch.turn_ids[-1],
            summary=result.summary,
            refs=epoch.refs,
            coverage=result.coverage,
            session_id=transcript.session_id,
        )
        checkpoint = ActiveCheckpoint(
            turn_id=epoch.turn_ids[-1],
            active_turns=epoch.turn_ids,
            session_id=transcript.session_id,
        )
        candidate_timeline = timeline.append_transaction((macro,), checkpoint)
        batch = CompactionBatch(
            unit_ids=epoch.unit_ids,
            sequence_start=epoch.sequence_start,
            sequence_end=epoch.sequence_end,
            input_text=epoch.input_text,
            input_tokens=epoch.input_tokens,
            output_summary=result.summary,
        )
        return CompactionResult(
            timeline=candidate_timeline,
            summary=result.summary,
            batches=(batch,),
            changed=True,
            input_tokens=epoch.input_tokens,
            output_tokens=self._estimate(result.summary),
        )

    def parse_epoch_result(
        self,
        value: object,
        *,
        epoch: CompactionEpoch,
        summary_hard_cap: int | None = None,
    ) -> CompactionStructuredResult:
        if not isinstance(epoch, CompactionEpoch):
            raise TypeError("epoch must be a CompactionEpoch")
        return parse_compaction_result(
            value,
            epoch,
            summary_hard_cap=(
                self.policy.summary_hard_cap
                if summary_hard_cap is None
                else summary_hard_cap
            ),
            token_estimator=self._estimate,
        )

    def _acquire_single_flight(self, session_id: str) -> threading.Lock:
        with self._locks_guard:
            lock = self._locks.setdefault(session_id, threading.Lock())
        if not lock.acquire(blocking=False):
            raise CompactionInProgress(f"Compaction already running for Session {session_id}")
        return lock

    def _estimate(self, text: str) -> int:
        return _estimate_tokens(self.token_estimator, text)


def _encode_transcript_entry(
    entry: TranscriptEntry,
    *,
    text_override: str | None = None,
) -> str:
    payload = dict(entry.to_dict())
    if text_override is not None:
        entry_payload = dict(payload.get("payload", {}))
        part = entry_payload.get("part")
        if isinstance(part, Mapping) and isinstance(part.get("text"), str):
            updated_part = dict(part)
            updated_part["text"] = text_override
            entry_payload["part"] = updated_part
        elif isinstance(entry_payload.get("text"), str):
            entry_payload["text"] = text_override
        else:
            raise CompactionValidationError("oversized entry has no splittable text part")
        payload["payload"] = entry_payload
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _entry_text_value(entry: TranscriptEntry) -> str | None:
    payload = entry.payload
    part = payload.get("part")
    if isinstance(part, Mapping) and isinstance(part.get("text"), str):
        return part["text"]
    value = payload.get("text")
    return value if isinstance(value, str) else None


def _timeline_aging_input_text(units: Sequence[SemanticUnit]) -> str:
    """Serialize only raw complete Transcript units for an L5 request."""

    encoded_units = "\n".join(
        json.dumps(unit.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        for unit in units
    )
    return f"Complete raw semantic units:\n{encoded_units}"


def fine_timeline_usage(
    timeline: Timeline,
    token_estimator: Callable[[str], int] | None = None,
) -> int:
    """Estimate the current logical Fine Timeline payload in tokens."""

    if not isinstance(timeline, Timeline):
        raise TypeError("timeline must be a Timeline")
    estimator = _resolve_token_estimator(token_estimator)
    text = "\n".join(
        json.dumps(entry.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        for entry in timeline.fine_entries
    )
    return _estimate_tokens(estimator, text)


def _oversized_fold_input_text(summaries: Sequence[str]) -> str:
    """Serialize only successful process-local summaries for one fold."""

    encoded = "\n".join(
        json.dumps({"summary": summary}, ensure_ascii=False, separators=(",", ":"))
        for summary in summaries
    )
    return f"Successful oversized summaries:\n{encoded}"


def _compaction_input_text(summary: str, units: Sequence[SemanticUnit]) -> str:
    previous = summary or "(no prior summary)"
    encoded_units = "\n".join(
        json.dumps(unit.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        for unit in units
    )
    return f"Summary so far:\n{previous}\nComplete semantic units:\n{encoded_units}"


__all__ = [
    "CompactionBatch",
    "CompactionError",
    "CompactionEntry",
    "CompactionEpoch",
    "CompactionInProgress",
    "CompactionPolicy",
    "CompactionResult",
    "CompactionStructuredResult",
    "CompactionValidationError",
    "CompactionSubpass",
    "ContextCompactor",
    "DeterministicTokenEstimator",
    "OversizedCompactionPlan",
    "OversizedFold",
    "OversizedFoldPlan",
    "OversizedFoldResult",
    "OversizedSubpassResult",
    "TimelineAgingEpoch",
    "TimelineAgingResult",
    "parse_compaction_result",
    "parse_oversized_fold_result",
    "parse_oversized_subpass_result",
    "parse_timeline_aging_result",
    "fine_timeline_usage",
]
