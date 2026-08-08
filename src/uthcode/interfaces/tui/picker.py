"""Pure model-picker state for the inline terminal UI."""

from __future__ import annotations

from dataclasses import dataclass

from uthcode.application import ModelProfile, PermissionMode


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


@dataclass(slots=True)
class PermissionPickerState:
    """Temporary picker state; the authoritative mode remains on AgentRun."""

    modes: tuple[PermissionMode, ...] = tuple(PermissionMode)
    current_mode: PermissionMode = PermissionMode.DEFAULT
    selected_index: int = 0
    open: bool = False

    @property
    def selected(self) -> PermissionMode:
        return self.modes[self.selected_index]

    @property
    def warning(self) -> str | None:
        if self.selected is PermissionMode.FULL_ACCESS:
            return (
                "高风险提示：full_access 仅跳过普通 Policy/Strategy，"
                "Guard 仍然生效。"
            )
        return None

    def replace(self, current_mode: PermissionMode) -> None:
        if not isinstance(current_mode, PermissionMode):
            current_mode = PermissionMode(current_mode)
        self.current_mode = current_mode
        self.selected_index = self.modes.index(current_mode)
        self.open = True

    def move(self, delta: int) -> None:
        if self.modes:
            self.selected_index = (self.selected_index + delta) % len(self.modes)

    def close(self) -> None:
        self.open = False


__all__ = ["ModelPickerState", "PermissionPickerState"]
