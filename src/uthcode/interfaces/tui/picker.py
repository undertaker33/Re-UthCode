"""Pure model-picker state for the inline terminal UI."""

from __future__ import annotations

from dataclasses import dataclass

from uthcode.application import ModelProfile


@dataclass(slots=True)
class ModelPickerState:
    models: tuple[ModelProfile, ...] = ()
    current_model_ref: str = ""
    selected_index: int = 0
    open: bool = False

    @property
    def selected(self) -> ModelProfile | None:
        if not self.models:
            return None
        return self.models[self.selected_index]

    def replace(
        self,
        models: tuple[ModelProfile, ...],
        current_model_ref: str,
    ) -> None:
        self.models = tuple(models)
        self.current_model_ref = current_model_ref
        self.selected_index = next(
            (
                index
                for index, model in enumerate(models)
                if model.model_ref == current_model_ref
            ),
            0,
        )
        self.open = bool(models)

    def move(self, delta: int) -> None:
        if self.models:
            self.selected_index = (self.selected_index + delta) % len(self.models)

    def close(self) -> None:
        self.open = False


__all__ = ["ModelPickerState"]
