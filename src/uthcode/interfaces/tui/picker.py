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


@dataclass(slots=True)
class SessionPickerState:
    """Temporary page/selection state; discovery stays in Application."""

    sessions: tuple[object, ...] = ()
    page: int = 0
    selected_index: int = 0
    page_size: int = 10
    open: bool = False

    def __post_init__(self) -> None:
        if self.page_size != 10:
            raise ValueError("Session Picker page_size must remain 10")

    @property
    def page_count(self) -> int:
        if not self.sessions:
            return 0
        return (len(self.sessions) + self.page_size - 1) // self.page_size

    @property
    def page_items(self) -> tuple[object, ...]:
        start = self.page * self.page_size
        return self.sessions[start : start + self.page_size]

    @property
    def selected(self) -> object | None:
        items = self.page_items
        if not items:
            return None
        return items[self.selected_index]

    def replace(self, sessions: tuple[object, ...] | list[object]) -> None:
        self.sessions = tuple(sessions)
        self.page = 0
        self.selected_index = 0
        self.open = bool(self.sessions)

    def move(self, delta: int) -> None:
        items = self.page_items
        if items:
            self.selected_index = (self.selected_index + delta) % len(items)

    def next_page(self) -> None:
        if self.page_count:
            self.page = min(self.page + 1, self.page_count - 1)
            self.selected_index = min(self.selected_index, len(self.page_items) - 1)

    def previous_page(self) -> None:
        if self.page_count:
            self.page = max(self.page - 1, 0)
            self.selected_index = min(self.selected_index, len(self.page_items) - 1)

    def close(self) -> None:
        self.open = False


__all__ = [
    "ModelPickerState",
    "PermissionPickerState",
    "SessionPickerState",
]
