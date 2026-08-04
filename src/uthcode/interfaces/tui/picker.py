"""Independent model picker state and widget."""

from __future__ import annotations

from dataclasses import dataclass

from textual.containers import VerticalScroll
from textual.events import Key
from textual.message import Message
from textual.widgets import Static


@dataclass(slots=True)
class ModelPickerState:
    models: tuple[object, ...] = ()
    current_model_ref: str = ""
    selected_index: int = 0
    open: bool = False

    @property
    def selected(self) -> object | None:
        if not self.models:
            return None
        return self.models[self.selected_index]

    def replace(self, models: tuple[object, ...], current_model_ref: str) -> None:
        self.models = tuple(models)
        self.current_model_ref = current_model_ref
        self.selected_index = next(
            (
                index
                for index, model in enumerate(self.models)
                if getattr(model, "model_ref", "") == current_model_ref
            ),
            0,
        )
        self.open = bool(self.models)

    def move(self, delta: int) -> None:
        if not self.models:
            return
        self.selected_index = (self.selected_index + delta) % len(self.models)

    def close(self) -> None:
        self.open = False


class ModelPicker(VerticalScroll):
    """Display the complete Application model catalog."""

    class Action(Message):
        def __init__(self, action: str) -> None:
            super().__init__()
            self.action = action

    def __init__(self, *, id: str | None = "model-picker") -> None:
        super().__init__(id=id, can_focus=True)
        self.state = ModelPickerState()
        self._body = Static()

    def compose(self):
        yield self._body

    def open(self, models: tuple[object, ...], current_model_ref: str) -> None:
        self.state.replace(models, current_model_ref)
        self.display = self.state.open
        self._refresh()

    def close(self) -> None:
        self.state.close()
        self.display = False

    def move(self, delta: int) -> None:
        self.state.move(delta)
        self._refresh()

    @property
    def selected(self) -> object | None:
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
        elif key == "enter":
            event.stop()
            self.post_message(self.Action("select"))

    def _refresh(self) -> None:
        lines = []
        for index, model in enumerate(self.state.models):
            ref = str(getattr(model, "model_ref", ""))
            label = str(getattr(model, "label", ref))
            provider = str(getattr(model, "provider_profile_id", ""))
            marker = "❯" if index == self.state.selected_index else " "
            current = "  · current" if ref == self.state.current_model_ref else ""
            lines.append(f"{marker} {ref} — {label} [{provider}]{current}")
        self._body.update("\n".join(lines))


__all__ = ["ModelPicker", "ModelPickerState"]
