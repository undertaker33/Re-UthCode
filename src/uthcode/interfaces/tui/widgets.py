"""Small Textual widgets for the AgentEvent transcript projection."""

from __future__ import annotations

from pathlib import Path

from textual.containers import VerticalScroll
from textual.events import Key, MouseScrollDown, MouseScrollUp
from textual.message import Message
from textual.widgets import Markdown, Static, TextArea

from .rendering import ToolUpdate
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


class UserMessageBlock(Static):
    """A full-width, padded container for one user message."""

    def __init__(self, text: str) -> None:
        self.text = text
        super().__init__(f"› {text}", classes="user-message-block")


class AgentTextBlock(SelectableMarkdown):
    """One reusable normal-colour block for reasoning or assistant text."""

    def __init__(self, kind: str, text: str = "") -> None:
        if kind not in {"reasoning", "assistant"}:
            raise ValueError("AgentTextBlock kind must be reasoning or assistant")
        self.kind = kind
        self.content_text = text
        super().__init__(text, classes=f"agent-text-block {kind}-agent-entry")

    def set_content(self, text: str, *, streaming: bool) -> None:
        self.content_text = text
        self.set_markdown(text, streaming=streaming)


class ToolActivityRow(Static):
    """A muted row showing only Application-provided Tool activity metadata."""

    def __init__(self, update: ToolUpdate) -> None:
        self.tool_call_id = update.tool_call_id
        self.tool_name = update.tool_name
        self.command = update.command
        self.status = update.status
        super().__init__(self.display_text, classes="tool-activity-row")

    @property
    def display_text(self) -> str:
        return f"• {self.status}  {self.tool_name}  {self.command}"

    def update_activity(self, update: ToolUpdate) -> None:
        self.tool_name = update.tool_name
        self.command = update.command
        self.status = update.status
        self.update(self.display_text)


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
    """Project display-safe batches into reusable transcript widgets."""

    def __init__(
        self,
        state: TranscriptState | None = None,
        *,
        id: str | None = "transcript",
    ) -> None:
        super().__init__(id=id, can_focus=True)
        self.state = state if state is not None else TranscriptState()

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

    def add_user_message(self, message_id: str, text: str) -> None:
        if message_id in self.state.widgets:
            return
        widget = UserMessageBlock(text)
        self.state.add(TranscriptEntryKind.USER, text, display_id=message_id)
        self.state.widgets[message_id] = widget
        self._mount(widget)
        self._follow_bottom()

    def add_entry(self, kind: TranscriptEntryKind, text: str) -> None:
        """Add a local command/system/error display entry."""

        widget = Static(text, classes=f"transcript-entry {kind.value}-entry")
        self.state.add(kind, text)
        self._mount(widget)
        self._follow_bottom()

    def append_agent_text(self, block_id: str, kind: str, text: str) -> None:
        if not text:
            return
        entry_kind = (
            TranscriptEntryKind.REASONING
            if kind == "reasoning"
            else TranscriptEntryKind.ASSISTANT
        )
        widget = self.state.widgets.get(block_id)
        if not isinstance(widget, AgentTextBlock):
            widget = AgentTextBlock(kind)
            self.state.widgets[block_id] = widget
            self.state.add(entry_kind, "", display_id=block_id)
            self._mount(widget)
        full_text = widget.content_text + text
        widget.set_content(full_text, streaming=True)
        self.state.update_display(block_id, full_text)
        self._follow_bottom()

    def replace_agent_text(self, block_id: str, kind: str, text: str) -> None:
        entry_kind = (
            TranscriptEntryKind.REASONING
            if kind == "reasoning"
            else TranscriptEntryKind.ASSISTANT
        )
        widget = self.state.widgets.get(block_id)
        if not isinstance(widget, AgentTextBlock):
            widget = AgentTextBlock(kind)
            self.state.widgets[block_id] = widget
            self.state.add(entry_kind, "", display_id=block_id)
            self._mount(widget)
        widget.set_content(text, streaming=True)
        self.state.update_display(block_id, text)
        self._follow_bottom()

    def update_tool_activity(self, update: ToolUpdate) -> None:
        row = self.state.tool_rows.get(update.tool_call_id)
        if not isinstance(row, ToolActivityRow):
            row = ToolActivityRow(update)
            self.state.tool_rows[update.tool_call_id] = row
            self.state.add(
                TranscriptEntryKind.TOOL,
                row.display_text,
                display_id=update.tool_call_id,
            )
            self._mount(row)
        else:
            row.update_activity(update)
            self.state.update_display(update.tool_call_id, row.display_text)
        self._follow_bottom()

    def finish_stream(self) -> None:
        for widget in self.state.widgets.values():
            if isinstance(widget, AgentTextBlock):
                widget.finish_stream()

    def clear_transcript(self) -> None:
        self.state.clear()
        try:
            self.remove_children()
        except Exception:
            return

    def _mount(self, widget: Static) -> None:
        try:
            self.mount(widget)
        except Exception:
            return

    def _follow_bottom(self) -> None:
        if self.state.scroll.follow:
            try:
                self.scroll_end(animate=False)
            except Exception:
                return


__all__ = [
    "AgentTextBlock",
    "ComposerTextArea",
    "SelectableMarkdown",
    "ToolActivityRow",
    "Topbar",
    "TranscriptWidget",
    "UserMessageBlock",
]
