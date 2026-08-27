"""Private, replaceable Context profile seam for offline Eval tuning.

The profiles are an Eval variant axis.  They reuse the production
``ContextBudget`` resolver and ``ApplicationContextService.compact_async``
path for one bounded run, then restore the imported Application bindings.
They are deliberately not configuration fields and are not part of the
public ``create_application`` API.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from typing import Any

import uthcode.application.context as application_context
import uthcode.application.generation as application_generation


class ProfileContractError(ValueError):
    """Raised when an Eval profile cannot be applied to the production budget."""


@dataclass(frozen=True, slots=True)
class ContextProfile:
    """One controlled tuning candidate over existing production parameters."""

    profile_id: str
    effective_input_limit: int
    auto_gate_limit: int
    retained_target: int
    fine_timeline_budget: int
    compaction_input_budget: int
    compaction_output_reserve: int
    max_epochs: int
    count_allowance: int

    def __post_init__(self) -> None:
        if not isinstance(self.profile_id, str) or not self.profile_id.strip():
            raise ProfileContractError("profile_id must be a non-empty string")
        positive_fields = (
            "effective_input_limit",
            "auto_gate_limit",
            "retained_target",
            "fine_timeline_budget",
            "compaction_input_budget",
            "compaction_output_reserve",
            "max_epochs",
        )
        for field_name in positive_fields:
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ProfileContractError(f"{field_name} must be a positive integer")
        if (
            isinstance(self.count_allowance, bool)
            or not isinstance(self.count_allowance, int)
            or self.count_allowance < 0
        ):
            raise ProfileContractError("count_allowance must be a non-negative integer")
        if not 0 < self.retained_target < self.auto_gate_limit < self.effective_input_limit:
            raise ProfileContractError("profile must satisfy retained < high < effective")
        if self.compaction_output_reserve >= self.compaction_input_budget:
            raise ProfileContractError("compaction output reserve must be below input budget")
        if self.fine_timeline_budget > self.effective_input_limit:
            raise ProfileContractError("fine timeline budget exceeds effective input limit")

    @property
    def working_headroom(self) -> int:
        return self.effective_input_limit - self.auto_gate_limit

    def to_variant(self) -> dict[str, object]:
        """Return the full candidate axis stored beside control fingerprints."""

        return {
            "id": self.profile_id,
            "parameters": {
                "effective_input_limit": self.effective_input_limit,
                "working_headroom": self.working_headroom,
                "auto_gate_limit": self.auto_gate_limit,
                "retained_target": self.retained_target,
                "fine_timeline_budget": self.fine_timeline_budget,
                "compaction_input_budget": self.compaction_input_budget,
                "compaction_output_reserve": self.compaction_output_reserve,
                "max_epochs": self.max_epochs,
                "count_allowance": self.count_allowance,
            },
        }


PROFILE_CANDIDATES: tuple[ContextProfile, ...] = (
    ContextProfile(
        profile_id="production-default",
        effective_input_limit=256_000,
        auto_gate_limit=243_200,
        retained_target=72_000,
        fine_timeline_budget=16_000,
        compaction_input_budget=64_000,
        compaction_output_reserve=4_000,
        max_epochs=4,
        count_allowance=0,
    ),
    ContextProfile(
        profile_id="balanced-208k",
        effective_input_limit=256_000,
        auto_gate_limit=208_000,
        retained_target=96_000,
        fine_timeline_budget=16_000,
        compaction_input_budget=64_000,
        compaction_output_reserve=4_096,
        max_epochs=4,
        count_allowance=8_192,
    ),
    ContextProfile(
        profile_id="compact-224k",
        effective_input_limit=256_000,
        auto_gate_limit=224_000,
        retained_target=128_000,
        fine_timeline_budget=12_000,
        compaction_input_budget=48_000,
        compaction_output_reserve=3_072,
        max_epochs=3,
        count_allowance=12_288,
    ),
)

PROFILE_IDS = tuple(profile.profile_id for profile in PROFILE_CANDIDATES)
_PROFILE_BY_ID = {profile.profile_id: profile for profile in PROFILE_CANDIDATES}


def profile_by_id(profile_id: str) -> ContextProfile:
    try:
        return _PROFILE_BY_ID[profile_id]
    except KeyError as exc:
        raise ProfileContractError(f"unknown profile: {profile_id}") from exc


@contextmanager
def applied_profile(profile: ContextProfile) -> Iterator[None]:
    """Temporarily inject one profile through the existing Application path."""

    if not isinstance(profile, ContextProfile):
        raise TypeError("profile must be a ContextProfile")
    original_generation_resolver = application_generation.resolve_context_budget
    original_context_resolver = application_context.resolve_context_budget
    original_compact_async = application_context.ApplicationContextService.compact_async

    def resolve_context_budget(**kwargs: Any) -> Any:
        budget = original_generation_resolver(**kwargs)
        if budget.effective_input_limit != profile.effective_input_limit:
            raise ProfileContractError(
                "candidate effective input limit does not match the active production limit"
            )
        return replace(
            budget,
            safety_allowance=profile.count_allowance,
            working_headroom=profile.working_headroom,
            auto_gate_limit=profile.auto_gate_limit,
            fine_timeline_budget=profile.fine_timeline_budget,
            retained_target=profile.retained_target,
            compaction_input_budget=profile.compaction_input_budget,
            compaction_output_reserve=profile.compaction_output_reserve,
        )

    async def compact_async(service: Any, *args: Any, **kwargs: Any) -> Any:
        kwargs["max_epochs"] = profile.max_epochs
        return await original_compact_async(service, *args, **kwargs)

    application_generation.resolve_context_budget = resolve_context_budget
    application_context.resolve_context_budget = resolve_context_budget
    application_context.ApplicationContextService.compact_async = compact_async
    try:
        yield
    finally:
        application_generation.resolve_context_budget = original_generation_resolver
        application_context.resolve_context_budget = original_context_resolver
        application_context.ApplicationContextService.compact_async = original_compact_async


__all__ = [
    "ContextProfile",
    "PROFILE_CANDIDATES",
    "PROFILE_IDS",
    "ProfileContractError",
    "applied_profile",
    "profile_by_id",
]
