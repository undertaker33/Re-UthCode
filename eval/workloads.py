"""Deterministic offline workload used by T09-3 Context profile tuning."""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator, Mapping, Sequence
from pathlib import Path
from typing import Any

from uthcode.application import (
    GenerationCompleted,
    Message,
    ProviderIdentity,
    ProviderResponse,
    TextPart,
    ToolCallPart,
    ToolResultPart,
    Usage,
)
from uthcode.application.context import ApplicationContextService
from uthcode.application.instructions import InstructionLoader
from uthcode.core.provider import ModelLimits
from uthcode.core.context import account_generation_request
from uthcode.core.history import transcript_entries_from_message
from uthcode.integrations.instruction_files import InstructionFileReader


PROFILE_WORKLOAD_ID = "t09-3-long-context-v1"
PROFILE_EVIDENCE_PATH = "docs/profile-evidence.txt"
PROFILE_EVIDENCE_LINES = 1_400
PROFILE_EVIDENCE_LINE_WIDTH = 700
PROFILE_SEED_TURNS = 300
PROFILE_SEED_FACT_WIDTH = 2_000
PROFILE_REQUIRED_EVIDENCE_PATHS = frozenset(
    {
        "src/public_api.py",
        "src/implementation.py",
        "tests/test_public_api.py",
        "docs/early-constraint.md",
    }
)
_PROFILE_READ_BATCH_SIZES = (2, 3, 1, 4)
_PROFILE_PAGE_LIMITS = (64 * 1024, 60 * 1024, 64 * 1024, 48 * 1024)
PROFILE_WORKLOAD_INSTRUCTION = """

T09-3 offline profile workload requirements:

1. Read the required evidence before changing anything.
2. Inspect `docs/profile-evidence.txt` and use `ToolResultRead` with its
   returned reference until the page metadata reports EOF.  This is a
   controlled long result; do not retry the original large `ReadFile`.
3. Preserve the public signature in `src/public_api.py`, correct
   `src/implementation.py` so the non-compact result ends with a period, and
   keep the compact result without punctuation.
4. After the change, re-read the regression test and implementation before
   answering.  The private Eval verifier runs the regression test subprocess
   after the Turn so this workload keeps the normal `auto` permission boundary.
""".strip()


def prepare_profile_workspace(workspace: Path) -> int:
    """Materialize a deterministic, external-attempt-only long input file."""

    path = workspace / PROFILE_EVIDENCE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    line = "profile-evidence " + ("0123456789abcdef" * 44)
    line = line[:PROFILE_EVIDENCE_LINE_WIDTH]
    content = "\n".join(
        f"{index:04d} {line}" for index in range(PROFILE_EVIDENCE_LINES)
    ) + "\n"
    path.write_text(content, encoding="utf-8", newline="\n")
    return len(content.encode("utf-8"))


def seed_profile_history(application: object) -> int:
    """Seed one identical, durable stable history for every profile attempt.

    The seed is an Eval-only setup fixture.  It gives the real Application L4
    path complete prior Turns to compact before the measured long workload;
    the current measured Turn remains the active suffix and is not fabricated
    as a compactable historical fact.
    """

    session_service = getattr(application, "_session_service", None)
    session = getattr(session_service, "active_session", None)
    if session is None:
        raise RuntimeError("profile workload requires an active Session")
    if session.transcript.entries:
        raise RuntimeError("profile workload seed Session must start empty")
    for index in range(1, PROFILE_SEED_TURNS + 1):
        message = Message(
            "user",
            (TextPart(f"offline stable context fact {index} " + "x" * PROFILE_SEED_FACT_WIDTH),),
        )
        entries = transcript_entries_from_message(
            session.session_id,
            f"eval-seed-turn-{index}",
            session.transcript.last_sequence + 1,
            message,
        )
        outcome = session.append_transcript(entries)
        if getattr(outcome, "durability", None) != "durable":
            raise RuntimeError("profile workload seed history was not durable")
    return PROFILE_SEED_TURNS


def _completed(*parts: object, finish_reason: str = "stop") -> GenerationCompleted:
    normalized = tuple(TextPart(part) if isinstance(part, str) else part for part in parts)
    return GenerationCompleted(
        ProviderResponse(
            message=Message("assistant", normalized),  # type: ignore[arg-type]
            usage=Usage(input_tokens=24, output_tokens=8),
            finish_reason=finish_reason,
        )
    )


def _json_mapping(text: str) -> Mapping[str, object] | None:
    try:
        value = json.loads(text)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, Mapping) else None


def _stable_route_rank(seed: int, path: str) -> tuple[int, str]:
    digest = hashlib.sha256(f"{seed}:{path}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big"), path


def _decode_numbered_file(content: str) -> str:
    """Recover source text from the bounded, line-numbered ReadFile result."""

    lines: list[str] = []
    for line in content.splitlines():
        prefix, separator, value = line.partition("\t")
        if separator and prefix.isdigit():
            lines.append(value)
        else:
            lines.append(line)
    suffix = "\n" if content.endswith("\n") else ""
    return "\n".join(lines) + suffix


def _derive_implementation_edit(content: str) -> tuple[str, str] | None:
    """Derive one minimal edit from the implementation returned by ReadFile.

    The workload does not carry the expected source file.  It only turns the
    observed non-compact return line into an EditFile replacement, so the
    verifier remains the authority for the final behavior.
    """

    source = _decode_numbered_file(content)
    for line in source.splitlines():
        stripped = line.rstrip()
        punctuation_index = stripped.rfind("!")
        if "return" not in stripped or "compact" not in stripped or punctuation_index < 0:
            continue
        if stripped[punctuation_index + 1 :].strip() not in {"\"", "'"}:
            continue
        return line, line[:punctuation_index] + "." + line[punctuation_index + 1 :]
    return None


class ProfileWorkloadProvider:
    """Offline Provider that advances from observed Tool and context facts."""

    def __init__(self, *, model_id: str = "eval-model", route_seed: int = 0) -> None:
        if isinstance(route_seed, bool) or not isinstance(route_seed, int):
            raise TypeError("route_seed must be an integer")
        self.identity = ProviderIdentity("fake", "eval-profile", model_id)
        self._model_id = model_id
        self._route_seed = route_seed
        self._regular_requests = 0
        self._compaction_requests = 0
        self._compaction_levels: list[str] = []
        self._request_index = 0
        self._call_index = 0
        self._pending_calls: dict[str, tuple[str, str | None]] = {}
        self._seen_tool_results: set[str] = set()
        self._read_paths: set[str] = set()
        self._read_failures: set[str] = set()
        self._read_contents: dict[str, str] = {}
        self._large_read_requested = False
        self._profile_ref: str | None = None
        self._profile_total_bytes: int | None = None
        self._next_offset = 0
        self._last_page_request_offset: int | None = None
        self._pages_finished = False
        self._tool_result_read_calls = 0
        self._history_read_calls = 0
        self._last_compaction_regular_request: int | None = None
        self._post_compact_work_requests = 0
        self._seeded_history_turns = 0
        self._pre_compact_usage: list[int] = []
        self._post_compact_usage: list[int] = []
        self._post_compact_headroom: list[int] = []
        self._prefix_changes: list[str] = []
        self._edit_attempted = False
        self._edit_succeeded = False
        self._post_change_reads: set[str] = set()
        self._application: Any | None = None
        self._prefix_probe_root: Path | None = None
        self._request_prefix_observations: list[dict[str, object]] = []
        self._route_trace: list[dict[str, object]] = []

    def attach_application(self, application: object, prefix_probe_root: Path) -> None:
        """Attach the real Application used by this Eval attempt.

        The reference is used only to read production request/context facts
        after the measured Turn.  The prefix probe writes its temporary source
        under the manifest-owned artifacts directory, never into the measured
        workspace or repository.
        """

        if application is None:
            raise TypeError("application must not be None")
        self._application = application
        self._prefix_probe_root = Path(prefix_probe_root)

    def resolve_model_limits(self, _model: str) -> ModelLimits:
        return ModelLimits(max_input_tokens=1_000_000, source="eval.profile_fake")

    def count_input_tokens(self, request: Any) -> int:
        """Expose a controlled offline Provider count to exercise Hard Gate."""

        if (
            request.metadata.get("context_compaction_request") is not True
            and not any(
                item.get("phase") == "pre_compact"
                for item in self._request_prefix_observations
            )
        ):
            # The first counted request is the real Application request that
            # crossed the High Water boundary.  It may never reach stream()
            # because Application performs L4 before sending it.
            self._capture_request_prefix(request)
        if request.metadata.get("context_compaction_request") is True:
            return account_generation_request(request).input_tokens
        if self._compaction_requests == 0:
            # The shared seed history makes this a recoverable exact-count
            # pressure event.  Keep the count above the common 256K operating
            # window so every candidate exercises the real Application L4
            # path; the candidate allowance remains visible in the final Hard
            # Gate and profile diagnostics.
            return 260_000
        return account_generation_request(request).input_tokens

    def record_seeded_history(self, turns: int) -> None:
        if isinstance(turns, bool) or not isinstance(turns, int) or turns < 0:
            raise ValueError("seeded history turns must be a non-negative integer")
        self._seeded_history_turns = turns

    async def stream(
        self,
        request: Any,
        *,
        cancellation: Any,
    ) -> AsyncIterator[GenerationCompleted]:
        cancellation.raise_if_cancelled()
        self._capture_request_prefix(request)
        if request.metadata.get("context_compaction_request") is True:
            self._observe_request(request)
            self._compaction_requests += 1
            level = request.metadata.get("context_compaction_level", "L4")
            self._compaction_levels.append(str(level))
            if level == "L5":
                turns = [
                    value
                    for value in request.metadata.get(
                        "context_timeline_aging_epoch_turns", ()
                    )
                    if isinstance(value, str)
                ]
                yield _completed(
                    json.dumps(
                        {"summary": "offline timeline aging summary", "coverage": turns},
                        ensure_ascii=False,
                    )
                )
            else:
                turns = [
                    value
                    for value in request.metadata.get(
                        "context_compaction_epoch_turns", ()
                    )
                    if isinstance(value, str)
                ]
                yield _completed(
                    json.dumps(
                        {
                            "entries": [
                                {"turn_id": turn_id, "summary": "offline bounded summary"}
                                for turn_id in turns
                            ],
                            "coverage": turns,
                        },
                        ensure_ascii=False,
                    )
                )
            self._last_compaction_regular_request = self._regular_requests
            cancellation.raise_if_cancelled()
            return

        self._regular_requests += 1
        self._observe_request(request)
        calls = self._plan_calls(request)
        cancellation.raise_if_cancelled()
        if calls:
            yield _completed(*calls, finish_reason="tool_calls")
        else:
            yield _completed(
                TextPart(
                    "Offline profile workload completed after evidence review, "
                    "bounded compaction, modification, and regression verification."
                )
            )

    def _capture_request_prefix(self, request: Any) -> None:
        metadata = getattr(request, "metadata", {})
        if not isinstance(metadata, Mapping):
            return
        fingerprint = metadata.get("stable_prefix_fingerprint")
        service = getattr(self._application, "context_service", None)
        snapshot = getattr(service, "last_snapshot", None)
        snapshot_fingerprint = getattr(snapshot, "stable_prefix_fingerprint", None)
        if isinstance(snapshot_fingerprint, str) and snapshot_fingerprint:
            fingerprint = snapshot_fingerprint
        if not isinstance(fingerprint, str) or not fingerprint:
            return
        epoch = getattr(snapshot, "instruction_epoch", metadata.get("instruction_epoch"))
        changed = getattr(snapshot, "prefix_changed", None)
        reason = getattr(snapshot, "prefix_change_reason", metadata.get("prefix_change_reason"))
        tool_fingerprint = getattr(
            snapshot,
            "tool_schema_fingerprint",
            metadata.get("tool_schema_fingerprint"),
        )
        compaction_request = metadata.get("context_compaction_request") is True
        compaction_note = metadata.get("context_compaction")
        attempted = (
            isinstance(compaction_note, Mapping)
            and compaction_note.get("attempted") is True
        )
        phase = (
            "compaction_request"
            if compaction_request
            else ("post_compact" if attempted else "pre_compact")
        )
        self._request_prefix_observations.append(
            {
                "source": "ApplicationContextService.last_snapshot+GenerationRequest.metadata",
                "phase": phase,
                "stable_prefix_fingerprint": fingerprint,
                "instruction_epoch": epoch if isinstance(epoch, int) and not isinstance(epoch, bool) else None,
                "prefix_changed": changed if isinstance(changed, bool) else None,
                "prefix_change_reason": reason if isinstance(reason, str) else None,
                "tool_schema_fingerprint": tool_fingerprint if isinstance(tool_fingerprint, str) else None,
                "message_count": len(getattr(request, "messages", ())),
            }
        )

    @staticmethod
    def _prefix_reuse_pair(
        before: Mapping[str, object] | None,
        after: Mapping[str, object] | None,
        *,
        label: str,
    ) -> dict[str, object]:
        if before is None or after is None:
            return {
                "status": "not_available",
                "reason": f"{label} requires two observed Application request facts",
            }
        before_fingerprint = before.get("stable_prefix_fingerprint")
        after_fingerprint = after.get("stable_prefix_fingerprint")
        fingerprint_same = (
            isinstance(before_fingerprint, str)
            and bool(before_fingerprint)
            and before_fingerprint == after_fingerprint
        )
        stable_reuse = (
            fingerprint_same
            and before.get("prefix_changed") is False
            and after.get("prefix_changed") is False
        )
        return {
            "status": "available",
            "before": dict(before),
            "after": dict(after),
            "stable_reuse": stable_reuse,
            "fingerprint_same": fingerprint_same,
            "expected_invalidation": False,
            "change_reason": after.get("prefix_change_reason"),
        }

    def _application_prefix_probe(self) -> dict[str, object]:
        """Collect reuse/invalidation from production request composition.

        The probe uses the production InstructionLoader,
        ApplicationContextService.compose_generation_request, and the real
        ContextCompiler behind that service.  Only their returned facts are
        projected into Eval diagnostics.
        """

        application = self._application
        root = self._prefix_probe_root
        if application is None or root is None:
            return {
                "status": "not_available",
                "reason": "profile Application was not attached to the workload",
            }
        try:
            user_root = root / "user"
            project_root = root / "project"
            user_root.mkdir(parents=True, exist_ok=True)
            project_root.mkdir(parents=True, exist_ok=True)
            loader = InstructionLoader(
                user_root=user_root,
                project_root=project_root,
                reader=InstructionFileReader(),
            )
            loader.load_session(strict=True)
            service = ApplicationContextService()
            tool_definitions = tuple(application.tool_definitions())
            model_profile = getattr(application, "current_model", None)
            model = getattr(model_profile, "remote_id", None) or self._model_id
            max_output_tokens = getattr(model_profile, "max_output_tokens", None)
            common = {
                "instruction_loader": loader,
                "tool_definitions": tool_definitions,
                "model": model,
                "max_output_tokens": max_output_tokens,
            }
            base_messages = (
                Message("user", (TextPart("prefix probe base conversation"),)),
            )
            grown_messages = (
                *base_messages,
                Message("user", (TextPart("prefix probe conversation growth"),)),
            )
            base_request, base_snapshot = service.compose_generation_request(
                base_messages,
                run_id="eval-prefix-base",
                **common,
            )
            grown_request, grown_snapshot = service.compose_generation_request(
                grown_messages,
                run_id="eval-prefix-growth",
                previous_snapshot=base_snapshot,
                **common,
            )
            growth_before = self._request_fact_from_snapshot(
                base_request,
                base_snapshot,
                "conversation_growth_before",
            )
            growth_after = self._request_fact_from_snapshot(
                grown_request,
                grown_snapshot,
                "conversation_growth_after",
            )

            instruction_source = project_root / "AGENTS.md"
            instruction_source.write_text(
                "# Eval prefix probe\n\nThis source is intentionally added by the offline Eval probe.\n",
                encoding="utf-8",
                newline="\n",
            )
            load_result = loader.load_session(strict=True)
            invalidated_request, invalidated_snapshot = service.compose_generation_request(
                grown_messages,
                run_id="eval-prefix-invalidation",
                previous_snapshot=grown_snapshot,
                **common,
            )
            invalidation_before = growth_after
            invalidation_after = self._request_fact_from_snapshot(
                invalidated_request,
                invalidated_snapshot,
                "instruction_source_added",
            )
            invalidation_fingerprint_changed = (
                invalidation_before["stable_prefix_fingerprint"]
                != invalidation_after["stable_prefix_fingerprint"]
            )
            invalidation_epoch_changed = (
                invalidation_before["instruction_epoch"]
                != invalidation_after["instruction_epoch"]
            )
            invalidation_reason = invalidated_snapshot.prefix_change_reason
            invalidation = {
                "status": "available",
                "expected": True,
                "before": invalidation_before,
                "after": invalidation_after,
                "fingerprint_changed": invalidation_fingerprint_changed,
                "instruction_epoch_changed": invalidation_epoch_changed,
                "change_reason": invalidation_reason,
                "loader_change_reason": load_result.change_reason,
                "instruction_source": {
                    "kind": "project",
                    "change": "source_added",
                    "path": "project/AGENTS.md",
                },
                "tool_schema_fingerprint_same": (
                    invalidation_before.get("tool_schema_fingerprint")
                    == invalidation_after.get("tool_schema_fingerprint")
                ),
            }
            compact_before = next(
                (
                    item
                    for item in self._request_prefix_observations
                    if item.get("phase") == "pre_compact"
                ),
                None,
            )
            compact_after = next(
                (
                    item
                    for item in self._request_prefix_observations
                    if item.get("phase") == "post_compact"
                ),
                None,
            )
            compact = self._prefix_reuse_pair(
                compact_before,
                compact_after,
                label="compact",
            )
            stable = (
                growth_before["stable_prefix_fingerprint"]
                == growth_after["stable_prefix_fingerprint"]
                and growth_after["prefix_changed"] is False
                and compact.get("stable_reuse") is True
            )
            return {
                "status": "available",
                "source": (
                    "ApplicationContextService.compose_generation_request"
                    "+ContextCompiler+InstructionLoader"
                ),
                "stable": stable,
                "change_count": 1,
                "change_reasons": [invalidation_reason],
                "fingerprint": invalidation_after["stable_prefix_fingerprint"],
                "instruction_epoch": invalidation_after["instruction_epoch"],
                "change_reason": growth_after["prefix_change_reason"],
                "conversation_growth": self._prefix_reuse_pair(
                    growth_before,
                    growth_after,
                    label="conversation_growth",
                ),
                "compact": compact,
                "expected_invalidation": invalidation,
                "application_request_observation_count": len(
                    self._request_prefix_observations
                ),
            }
        except Exception as exc:
            return {
                "status": "not_available",
                "reason": f"production prefix probe failed: {type(exc).__name__}",
            }

    @staticmethod
    def _request_fact_from_snapshot(
        request: Any,
        snapshot: Any,
        phase: str,
    ) -> dict[str, object]:
        metadata = getattr(request, "metadata", {})
        return {
            "source": "ApplicationContextService.compose_generation_request",
            "phase": phase,
            "stable_prefix_fingerprint": snapshot.stable_prefix_fingerprint,
            "instruction_epoch": snapshot.instruction_epoch,
            "prefix_changed": snapshot.prefix_changed,
            "prefix_change_reason": snapshot.prefix_change_reason,
            "tool_schema_fingerprint": snapshot.tool_schema_fingerprint,
            "request_metadata_fingerprint": (
                metadata.get("stable_prefix_fingerprint")
                if isinstance(metadata, Mapping)
                else None
            ),
            "request_metadata_reason": (
                metadata.get("prefix_change_reason")
                if isinstance(metadata, Mapping)
                else None
            ),
            "message_count": len(getattr(request, "messages", ())),
        }

    def _observe_request(self, request: Any) -> None:
        def append_sample(target: list[int], value: object) -> None:
            if isinstance(value, int) and not isinstance(value, bool):
                if not target or target[-1] != value:
                    target.append(value)

        gate = request.metadata.get("context_gate")
        if isinstance(gate, Mapping):
            usage = gate.get("preflight_input_usage")
            if isinstance(usage, int) and (
                gate.get("auto_pressure") is True or gate.get("hard_safe") is False
            ):
                append_sample(self._pre_compact_usage, usage)
        note = request.metadata.get("context_compaction")
        if isinstance(note, Mapping) and note.get("attempted") is True:
            previous = note.get("previous_estimate")
            headroom = note.get("headroom")
            post_usage = note.get("post_epoch_input_usage")
            append_sample(self._pre_compact_usage, previous)
            append_sample(self._post_compact_usage, post_usage)
            append_sample(self._post_compact_headroom, headroom)
        if self._last_compaction_regular_request is not None:
            self._post_compact_work_requests = max(
                self._post_compact_work_requests,
                self._regular_requests - self._last_compaction_regular_request,
            )
        prefix_changed = request.metadata.get("context_prefix_changed")
        if prefix_changed is True:
            reason = request.metadata.get("context_prefix_change_reason")
            self._prefix_changes.append(str(reason or "unknown"))

    def _new_call(
        self,
        kind: str,
        tool_name: str,
        arguments: Mapping[str, object],
        *,
        path: str | None = None,
    ) -> ToolCallPart:
        self._call_index += 1
        call_id = f"profile-{kind}-{self._call_index}"
        self._pending_calls[call_id] = (kind, path)
        trace: dict[str, object] = {
            "index": self._call_index,
            "kind": kind,
            "tool": tool_name,
        }
        for key in ("path", "ref", "offset", "limit"):
            if key in arguments:
                trace[key] = arguments[key]
        self._route_trace.append(trace)
        return ToolCallPart(call_id, tool_name, arguments)

    def _observe_tool_results(self, request: Any) -> None:
        observed_page = False
        for message in request.messages:
            for part in message.parts:
                if not isinstance(part, ToolResultPart) or part.tool_call_id in self._seen_tool_results:
                    continue
                self._seen_tool_results.add(part.tool_call_id)
                kind, path = self._pending_calls.pop(part.tool_call_id, ("", None))
                if kind in {"read", "post-read", "large-read"} and path is not None:
                    if part.is_error:
                        self._read_failures.add(path)
                    else:
                        self._read_paths.add(path)
                        if kind == "post-read":
                            self._post_change_reads.add(path)
                        if path != PROFILE_EVIDENCE_PATH:
                            self._read_contents[path] = _decode_numbered_file(part.content)
                    metadata = part.metadata
                    ref = metadata.get("ref")
                    if (
                        path == PROFILE_EVIDENCE_PATH
                        and metadata.get("persistence_status") == "externalized"
                        and isinstance(ref, str)
                    ):
                        self._profile_ref = ref
                        size_bytes = metadata.get("size_bytes")
                        if isinstance(size_bytes, int):
                            self._profile_total_bytes = size_bytes
                        self._next_offset = 0
                elif kind == "page" and not part.is_error:
                    page = _json_mapping(part.content)
                    if page is None:
                        continue
                    next_offset = page.get("next_offset")
                    eof = page.get("eof")
                    if isinstance(next_offset, int) and next_offset > self._next_offset:
                        self._next_offset = next_offset
                        observed_page = True
                    if eof is True:
                        self._pages_finished = True
                elif kind == "edit":
                    self._edit_succeeded = not part.is_error
        if (
            not observed_page
            and self._profile_ref is not None
            and not self._pages_finished
            and self._last_page_request_offset is not None
            and self._next_offset == self._last_page_request_offset
        ):
            # Context compilation may omit an older page.  Continue from the
            # known externalized byte boundary without replaying the ReadFile.
            total = self._profile_total_bytes
            step = _PROFILE_PAGE_LIMITS[
                (self._route_seed + self._tool_result_read_calls) % len(_PROFILE_PAGE_LIMITS)
            ]
            next_offset = self._next_offset + step
            if total is not None:
                next_offset = min(next_offset, total)
            self._next_offset = next_offset
            if total is not None and next_offset >= total:
                self._pages_finished = True

    def _ordered_paths(self, paths: Sequence[str]) -> tuple[str, ...]:
        return tuple(sorted(paths, key=lambda path: _stable_route_rank(self._route_seed, path)))

    def _read_calls(
        self,
        paths: Sequence[str],
        *,
        post_change: bool = False,
    ) -> tuple[ToolCallPart, ...]:
        calls: list[ToolCallPart] = []
        kind = "post-read" if post_change else "read"
        for path in paths:
            arguments: dict[str, object] = {"path": path}
            if path == PROFILE_EVIDENCE_PATH:
                arguments.update({"offset": 1, "limit": 2_000})
                kind = "large-read"
                self._large_read_requested = True
            calls.append(self._new_call(kind, "ReadFile", arguments, path=path))
        return tuple(calls)

    def _plan_calls(self, request: Any) -> tuple[ToolCallPart, ...]:
        self._observe_tool_results(request)
        self._request_index += 1

        if self._profile_ref is not None and not self._pages_finished:
            self._tool_result_read_calls += 1
            self._last_page_request_offset = self._next_offset
            limit = _PROFILE_PAGE_LIMITS[
                (self._route_seed + self._tool_result_read_calls - 1) % len(_PROFILE_PAGE_LIMITS)
            ]
            return (
                self._new_call(
                    "page",
                    "ToolResultRead",
                    {"ref": self._profile_ref, "offset": self._next_offset, "limit": limit},
                ),
            )

        missing = self._ordered_paths(
            tuple(
                path
                for path in PROFILE_REQUIRED_EVIDENCE_PATHS
                if path not in self._read_paths and path not in self._read_failures
            )
        )
        if missing:
            batch_size = _PROFILE_READ_BATCH_SIZES[
                (self._route_seed + self._request_index - 1) % len(_PROFILE_READ_BATCH_SIZES)
            ]
            return self._read_calls(missing[:batch_size])

        if not self._large_read_requested:
            return self._read_calls((PROFILE_EVIDENCE_PATH,))

        if self._edit_succeeded:
            post_missing = self._ordered_paths(
                tuple(
                    path
                    for path in ("tests/test_public_api.py", "src/implementation.py")
                    if path not in self._post_change_reads and path not in self._read_failures
                )
            )
            if post_missing:
                return self._read_calls(post_missing, post_change=True)
            return ()

        if self._edit_attempted:
            # EditFile has already run; do not repeat a possibly side-effecting
            # operation when its result cannot be confirmed.
            return ()

        implementation = self._read_contents.get("src/implementation.py")
        edit = _derive_implementation_edit(implementation) if implementation is not None else None
        self._edit_attempted = True
        if edit is None:
            return ()
        old_string, new_string = edit
        return (
            self._new_call(
                "edit",
                "EditFile",
                {
                    "path": "src/implementation.py",
                    "old_string": old_string,
                    "new_string": new_string,
                },
                path="src/implementation.py",
            ),
        )

    def public_diagnostics(self, *, evidence_bytes: int | None = None) -> dict[str, object]:
        post_compact_distance = {
            "provider_requests_after_compaction": self._post_compact_work_requests,
            "tool_result_read_calls": self._tool_result_read_calls,
        }
        required_paths = set(PROFILE_REQUIRED_EVIDENCE_PATHS)
        route_complete = (
            required_paths.issubset(self._read_paths)
            and self._profile_ref is not None
            and self._pages_finished
            and self._edit_succeeded
            and {"tests/test_public_api.py", "src/implementation.py"}.issubset(
                self._post_change_reads
            )
        )
        return {
            "schema_version": 1,
            "workload_id": PROFILE_WORKLOAD_ID,
            "evidence_bytes": evidence_bytes,
            "regular_provider_requests": self._regular_requests,
            "compaction_requests": self._compaction_requests,
            "compaction_levels": list(self._compaction_levels),
            "seeded_history_turns": self._seeded_history_turns,
            "pre_compact_usage": list(self._pre_compact_usage),
            "post_compact_usage": list(self._post_compact_usage),
            "post_compact_headroom": list(self._post_compact_headroom),
            "work_distance": post_compact_distance,
            "route": {
                "status": "available" if self._route_trace else "not_available",
                "route_seed": self._route_seed,
                "trace": list(self._route_trace),
                "required_paths": sorted(required_paths),
                "read_paths": sorted(self._read_paths),
                "read_failures": sorted(self._read_failures),
                "large_read_requested": self._large_read_requested,
                "profile_ref_available": self._profile_ref is not None,
                "pages_finished": self._pages_finished,
                "edit_attempted": self._edit_attempted,
                "edit_succeeded": self._edit_succeeded,
                "post_change_reads": sorted(self._post_change_reads),
                "complete": route_complete,
            },
            "history_read": {
                "status": "not_available",
                "calls": self._history_read_calls,
                "reason": "the offline profile workload has no valid HistoryRead ref",
            },
            "cache": {
                "status": "not_available",
                "reason": "offline Fake Provider has no provider cache telemetry",
            },
            "prefix": {
                **self._application_prefix_probe(),
            },
            "failure_correctness": {
                "status": "not_applicable",
                "reason": "successful workload; failure matrix is verified separately",
            },
        }


__all__ = [
    "PROFILE_EVIDENCE_PATH",
    "PROFILE_REQUIRED_EVIDENCE_PATHS",
    "PROFILE_WORKLOAD_ID",
    "PROFILE_WORKLOAD_INSTRUCTION",
    "ProfileWorkloadProvider",
    "prepare_profile_workspace",
]
