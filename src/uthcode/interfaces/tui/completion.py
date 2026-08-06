"""Pure command-completion presentation state."""

from __future__ import annotations

from dataclasses import dataclass

from uthcode.application import CompletionCandidate


@dataclass(frozen=True, slots=True)
class CompletionMenuItem:
    value: str
    display: str

    @classmethod
    def from_command(cls, candidate: CompletionCandidate) -> "CompletionMenuItem":
        return cls(
            value=candidate.value,
            display=candidate.display,
        )


@dataclass(slots=True)
class CompletionMenuState:
    candidates: tuple[CompletionMenuItem, ...] = ()
    selected_index: int = 0
    open: bool = False

    @property
    def selected(self) -> CompletionMenuItem | None:
        if not self.candidates:
            return None
        return self.candidates[self.selected_index]

    def replace(self, candidates: tuple[CompletionMenuItem, ...]) -> None:
        self.candidates = tuple(candidates)
        self.selected_index = 0
        self.open = bool(candidates)

    def move(self, delta: int) -> None:
        if self.candidates:
            self.selected_index = (self.selected_index + delta) % len(self.candidates)

    def close(self) -> None:
        self.open = False


__all__ = ["CompletionMenuItem", "CompletionMenuState"]
