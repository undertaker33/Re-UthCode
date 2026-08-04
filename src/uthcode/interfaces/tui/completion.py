"""Independent command completion state and widget."""

from __future__ import annotations

from dataclasses import dataclass

from textual.containers import VerticalScroll
from textual.events import Key
from textual.message import Message
from textual.widgets import Static

from uthcode.application import CompletionCandidate


@dataclass(frozen=True, slots=True)
class CompletionMenuItem:
    """Interface-local presentation and insertion data for one menu row."""

    value: str
    display: str
    usage: str
    argument_prompt: str = ""

    @classmethod
    def from_command(cls, candidate: CompletionCandidate) -> CompletionMenuItem:
        return cls(
            value=candidate.value,
            display=candidate.display,
            usage=candidate.usage,
            argument_prompt=candidate.argument_prompt,
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
        self.open = bool(self.candidates)

    def move(self, delta: int) -> None:
        if not self.candidates:
            return
        self.selected_index = (self.selected_index + delta) % len(self.candidates)

    def close(self) -> None:
        self.open = False


class CommandCompletionMenu(VerticalScroll):
    """Scrollable command candidates with keyboard-neutral action messages."""

    class Action(Message):
        def __init__(self, action: str) -> None:
            super().__init__()
            self.action = action

    def __init__(self, *, id: str | None = "completion-menu") -> None:
        super().__init__(id=id, can_focus=True)
        self.state = CompletionMenuState()
        self._body = Static(markup=False)

    def compose(self):
        yield self._body

    def open(self, candidates: tuple[CompletionMenuItem, ...]) -> None:
        self.state.replace(candidates)
        self.display = self.state.open
        self._refresh()

    def close(self) -> None:
        self.state.close()
        self.display = False

    def move(self, delta: int) -> None:
        self.state.move(delta)
        self._refresh()

    @property
    def selected(self) -> CompletionMenuItem | None:
        return self.state.selected

    def on_key(self, event: Key) -> None:
        key = event.key.lower()
        if not self.state.open:
            return
        if key == "up":
            event.stop()
            self.move(-1)
        elif key == "down":
            event.stop()
            self.move(1)
        elif key in {"escape", "esc"}:
            event.stop()
            self.post_message(self.Action("close"))
        elif key == "tab":
            event.stop()
            self.post_message(self.Action("complete"))
        elif key == "enter":
            event.stop()
            self.post_message(self.Action("execute"))

    def _refresh(self) -> None:
        lines = []
        for index, candidate in enumerate(self.state.candidates):
            marker = "❯" if index == self.state.selected_index else " "
            lines.append(f"{marker} {candidate.display}")
        selected = self.state.selected
        if selected is not None:
            lines.append("")
            lines.append(f"Usage: {selected.usage}")
            if selected.argument_prompt:
                lines.append(selected.argument_prompt)
        self._body.update("\n".join(lines))


__all__ = ["CommandCompletionMenu", "CompletionMenuItem", "CompletionMenuState"]
