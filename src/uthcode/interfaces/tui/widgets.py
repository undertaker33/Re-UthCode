"""Textual widgets for the small UthCode transcript interface."""

from __future__ import annotations

from pathlib import Path

from textual.containers import VerticalScroll
from textual.events import Key, MouseScrollDown, MouseScrollUp
from textual.message import Message
from textual.widgets import Markdown, Static, TextArea

from .state import TranscriptEntryKind, TranscriptState


class Topbar(Static):
    """Show the application name, selected model and launch directory."""

    def __init__(
        self,
        model_ref: str,
        cwd: str | Path,
        *,
        id: str | None = "topbar",
    ) -> None:
        self.model_ref = model_ref
        self.cwd = Path(cwd)
        super().__init__(id=id)

    def on_mount(self) -> None:
        self._refresh_text()

    def update_model(self, model_ref: str) -> None:
        self.model_ref = model_ref
        self._refresh_text()

    def update_cwd(self, cwd: str | Path) -> None:
        self.cwd = Path(cwd)
        self._refresh_text()

    def _refresh_text(self) -> None:
        self.update(f"UthCode  |  {self.model_ref}  |  {self.cwd}")


class SelectableMarkdown(Markdown):
    """Markdown whose selection is disabled only while content is replaced."""

    ALLOW_SELECT = True

    def set_markdown(self, value: str, *, streaming: bool) -> None:
        self.ALLOW_SELECT = not streaming
        try:
            self.update(value)
        except Exception:
            # Textual can cancel a pending render while a screen is closing.
            # The next final flush remains authoritative.
            return

    def finish_stream(self) -> None:
        self.ALLOW_SELECT = True


class ComposerTextArea(TextArea):
    """Send on Enter and insert a line break on Shift+Enter."""

    class Submitted(Message):
        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    def on_key(self, event: Key) -> None:
        key = event.key.lower()
        if key in {"shift+enter", "ctrl+j"}:
            event.prevent_default()
            event.stop()
            self.insert("\n")
            return
        if key == "enter":
            event.prevent_default()
            event.stop()
            text = self.text
            if text.strip():
                self.post_message(self.Submitted(text))


class TranscriptWidget(VerticalScroll):
    """Render transcript entries while keeping the assistant block reusable."""

    def __init__(
        self,
        state: TranscriptState | None = None,
        *,
        id: str | None = "transcript",
    ) -> None:
        super().__init__(id=id, can_focus=True)
        self.state = state or TranscriptState()
        self._assistant_widget: SelectableMarkdown | None = None
        self._assistant_text = ""
        self._reasoning_widget: Static | None = None

    def on_mouse_scroll_up(self, _event: MouseScrollUp) -> None:
        self.state.scroll.observe(self.scroll_y, self.max_scroll_y)
        self.state.scroll.follow = False

    def on_mouse_scroll_down(self, _event: MouseScrollDown) -> None:
        self.state.scroll.observe(self.scroll_y, self.max_scroll_y)

    def observe_scroll(self) -> None:
        self.state.scroll.observe(self.scroll_y, self.max_scroll_y)

    def watch_scroll_y(self, old_value: float, new_value: float) -> None:
        """Track every scroll source, including keys and scrollbar dragging."""

        super().watch_scroll_y(old_value, new_value)
        if hasattr(self, "state"):
            self.state.scroll.observe(new_value, self.max_scroll_y)

    def add_entry(self, kind: TranscriptEntryKind, text: str) -> None:
        self.state.add(kind, text)
        if kind is TranscriptEntryKind.ASSISTANT:
            widget = SelectableMarkdown(text, classes="assistant-entry")
            self._assistant_widget = widget
            self._assistant_text = text
        elif kind is TranscriptEntryKind.REASONING:
            widget = Static(text, classes="reasoning-entry")
            self._reasoning_widget = widget
        else:
            widget = Static(
                text,
                classes=f"transcript-entry {kind.value}-entry",
            )
        try:
            self.mount(widget)
        except Exception:
            return
        self._follow_bottom()

    def begin_stream(self) -> None:
        """Start a fresh assistant block for the next single message."""

        self._assistant_widget = None
        self._assistant_text = ""
        self._reasoning_widget = None

    def append_assistant(self, text: str) -> None:
        if not text:
            return
        if self._assistant_widget is None:
            self.add_entry(TranscriptEntryKind.ASSISTANT, "")
        self._assistant_text += text
        if self.state.entries and self.state.entries[-1].kind is TranscriptEntryKind.ASSISTANT:
            self.state.append_to_last(TranscriptEntryKind.ASSISTANT, text)
        elif not self.state.entries or self.state.entries[-1].kind is not TranscriptEntryKind.ASSISTANT:
            self.state.add(TranscriptEntryKind.ASSISTANT, text)
        if self._assistant_widget is not None:
            self._assistant_widget.set_markdown(self._assistant_text, streaming=True)
        self._follow_bottom()

    def append_reasoning(self, text: str) -> None:
        if not text:
            return
        if self._reasoning_widget is None:
            self.add_entry(TranscriptEntryKind.REASONING, text)
            return
        self.state.append_to_last(TranscriptEntryKind.REASONING, text)
        self._reasoning_widget.update(self.state.entries[-1].text)
        self._follow_bottom()

    def finish_stream(self) -> None:
        if self._assistant_widget is not None:
            self._assistant_widget.finish_stream()

    def clear_transcript(self) -> None:
        self.state.clear()
        self._assistant_widget = None
        self._reasoning_widget = None
        self._assistant_text = ""
        try:
            self.remove_children()
        except Exception:
            return

    def _follow_bottom(self) -> None:
        if self.state.scroll.follow:
            try:
                self.scroll_end(animate=False)
            except Exception:
                return


__all__ = [
    "ComposerTextArea",
    "SelectableMarkdown",
    "Topbar",
    "TranscriptWidget",
]
