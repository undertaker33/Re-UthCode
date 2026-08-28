"""Rich renderers for permanent terminal-scrollback records."""

from __future__ import annotations

import io
import re
from dataclasses import dataclass

from pygments.style import Style as PygmentsStyle
from pygments.token import Comment, Keyword, Name, Number, Operator, String, Token
from rich import box
from rich.console import Console, Group
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text
from rich.theme import Theme


CLEAR_VIEWPORT = "\x1b[2J\x1b[H"
KITTY_KEYBOARD_ON = "\x1b[>1u"
KITTY_KEYBOARD_OFF = "\x1b[<u"
SYNCHRONIZED_OUTPUT_ON = "\x1b[?2026h"
SYNCHRONIZED_OUTPUT_OFF = "\x1b[?2026l"


@dataclass(frozen=True, slots=True)
class Palette:
    accent: str = "#FEA62B"
    user_background: str = "#242F38"
    input_background: str = "#1E1E1E"
    reasoning_accent: str = "#78A9FF"
    plan_accent: str = "#78A9FF"
    plan_background: str = "#17233A"
    code_background: str = "#121212"
    text: str = "#E0E0E0"
    muted: str = "#9A9A9A"
    success: str = "#4EBF71"
    error: str = "#B93C5B"


PALETTE = Palette()


class UthCodeCodeStyle(PygmentsStyle):
    """Foreground syntax colours on the fixed UthCode code surface."""

    background_color = PALETTE.code_background
    styles = {
        Token: PALETTE.text,
        Comment: "italic #7F8C8D",
        Keyword: "bold #FEA62B",
        Name.Builtin: "#56B6C2",
        Name.Function: "#61AFEF",
        Number: "#D19A66",
        Operator: "#C678DD",
        String: "#98C379",
    }


class RichTerminalRenderer:
    """Render stable records without owning cursor or terminal input state."""

    def __init__(self, *, width: int = 80, palette: Palette = PALETTE) -> None:
        self.width = max(20, width)
        self.palette = palette

    def resize(self, width: int) -> None:
        self.width = max(20, width)

    def welcome(self, model_ref: str, cwd: str) -> str:
        logo = (
            "██╗   ██╗████████╗██╗  ██╗\n"
            "██║   ██║╚══██╔══╝██║  ██║\n"
            "██║   ██║   ██║   ███████║\n"
            "██║   ██║   ██║   ██╔══██║\n"
            "╚██████╔╝   ██║   ██║  ██║\n"
            " ╚═════╝    ╚═╝   ╚═╝  ╚═╝ CODE"
        )
        if self.width < 66:
            logo = "UthCode"
        body = Group(
            Text(logo, style=f"bold {self.palette.accent}", justify="center"),
            Text(""),
            Text.from_markup(
                f"[bold]{_escape(model_ref)}[/bold]\n"
                f"{_escape(cwd)}\n"
                "Enter 发送 · Shift+Enter / Ctrl+J 换行 · 生成中连续 Esc 暂停 · Ctrl+C 退出",
                justify="center",
            ),
        )
        panel = Panel(
            body,
            title="[bold] UthCode [/bold]",
            border_style=self.palette.accent,
            box=box.ROUNDED,
            padding=(1, 2),
            expand=True,
        )
        return self._capture(panel) + "\n"

    def user_message(self, text: str, *, role: str = "you") -> str:
        return self._role_block(
            role=role,
            content=Text(text, style=self.palette.text),
            background=self.palette.user_background,
            bar=self.palette.muted,
        )

    def reasoning_message(
        self,
        markdown: str,
        *,
        role: str = "UthCode · reasoning",
        show_role: bool = True,
        trailing_blank: bool = True,
    ) -> str:
        """Render typed reasoning with its own semantic bar colour."""

        content = Markdown(
            _protect_nested_markdown_fences(markdown),
            code_theme=UthCodeCodeStyle,
        )
        return self._role_block(
            role=role if show_role else "",
            content=content,
            background=None,
            bar=self.palette.reasoning_accent,
            trailing_blank=trailing_blank,
        )

    def agent_message(
        self,
        markdown: str,
        *,
        role: str = "UthCode:",
        show_role: bool = True,
        trailing_blank: bool = True,
    ) -> str:
        content = Markdown(
            _protect_nested_markdown_fences(markdown),
            code_theme=UthCodeCodeStyle,
        )
        return self._role_block(
            role=role if show_role else "",
            content=content,
            background=None,
            bar=self.palette.success,
            trailing_blank=trailing_blank,
        )

    def plan_message(self, markdown: str, *, revision: int) -> str:
        content = Markdown(
            _protect_nested_markdown_fences(markdown),
            code_theme=UthCodeCodeStyle,
        )
        return self._role_block(
            role=f"UthCode · Plan v{revision}",
            content=content,
            background=self.palette.plan_background,
            bar=self.palette.plan_accent,
        )

    def task_state(self, items: tuple[tuple[str, str], ...]) -> str:
        markers = {
            "completed": "✓",
            "in_progress": "›",
            "pending": "○",
        }
        content = Text()
        if not items:
            content.append("○ no active tasks", style=self.palette.muted)
        for index, (status, text) in enumerate(items):
            if index:
                content.append("\n")
            colour = (
                self.palette.success
                if status == "completed"
                else self.palette.plan_accent
                if status == "in_progress"
                else self.palette.muted
            )
            content.append(f"{markers.get(status, '○')} ", style=f"bold {colour}")
            content.append(text, style=self.palette.text)
        return self._role_block(
            role="Tasks",
            content=content,
            background=None,
            bar=self.palette.plan_accent,
        )

    def tool(self, *, status: str, name: str, command: str) -> str:
        normalized = status.casefold()
        if normalized == "finished":
            colour = self.palette.success
        elif normalized in {"failed", "error", "denied"}:
            colour = self.palette.error
        else:
            colour = self.palette.muted
        text = Text()
        text.append("┃ ", style=self.palette.muted)
        text.append("• ", style=f"bold {colour}")
        text.append(f"{status}  ", style=f"bold {colour}")
        text.append(f"{name}  {command}", style=self.palette.muted)
        return self._capture(text) + "\n\n"

    def system(self, text: str, *, error: bool = False) -> str:
        colour = self.palette.error if error else self.palette.muted
        value = Text()
        value.append("┃ ", style=colour)
        value.append(text, style=colour)
        return self._capture(value) + "\n"

    def correction(self, authoritative: str) -> str:
        return (
            self.system("响应已修正", error=True)
            + self.agent_message(authoritative)
        )

    def _role_block(
        self,
        *,
        role: str,
        content: object,
        background: str | None,
        bar: str,
        trailing_blank: bool = True,
    ) -> str:
        content_width = max(8, self.width - 4)
        rendered = self._capture(content, width=content_width).rstrip("\n")
        content_lines = rendered.splitlines() or [""]
        rows: list[str] = []
        if role:
            rows.append(self._styled_row(role, background, bar, bold=True))
        for line in content_lines:
            rows.append(self._styled_row(line, background, bar))
        return "\n".join(rows) + ("\n\n" if trailing_blank else "\n")

    def _styled_row(
        self,
        value: str,
        background: str | None,
        bar: str,
        *,
        bold: bool = False,
    ) -> str:
        available = max(1, self.width - 2)
        decoded = Text.from_ansi(value)
        if decoded.cell_len > available:
            decoded.truncate(available, overflow="ellipsis")
        if background is not None and decoded.cell_len < available:
            decoded.append(" " * (available - decoded.cell_len))
        decoded.style = f"{'bold ' if bold else ''}{self.palette.text}"
        if background is not None:
            decoded.style += f" on {background}"
        row = Text()
        row.append("┃", style=f"bold {bar}")
        row.append(" ")
        row.append_text(decoded)
        return self._capture(row, width=self.width).rstrip("\n")

    def _capture(self, renderable: object, *, width: int | None = None) -> str:
        buffer = io.StringIO()
        console = Console(
            file=buffer,
            force_terminal=True,
            color_system="truecolor",
            no_color=False,
            width=max(20, width or self.width),
            soft_wrap=False,
            theme=Theme(
                {
                    "markdown.code_inline": (
                        f"bold {self.palette.accent} on {self.palette.code_background}"
                    ),
                    "markdown.item.bullet": self.palette.accent,
                    "markdown.item.number": self.palette.accent,
                    "markdown.block_quote": self.palette.muted,
                    "markdown.h1": f"bold {self.palette.accent}",
                    "markdown.h2": f"bold {self.palette.accent}",
                    "markdown.h3": f"bold {self.palette.accent}",
                }
            ),
        )
        console.print(renderable, end="")
        return buffer.getvalue()


def _escape(value: str) -> str:
    return value.replace("[", r"\[").replace("]", r"\]")


def _protect_nested_markdown_fences(value: str) -> str:
    """Make common Markdown-in-Markdown fences unambiguous for Rich."""

    lines = value.splitlines(keepends=True)
    index = 0
    while index < len(lines):
        opening = re.match(
            r"^( {0,3})(`{3,}|~{3,})[ \t]*(?:markdown|md)[ \t]*(\r?\n)?$",
            lines[index],
            re.IGNORECASE,
        )
        if opening is None:
            index += 1
            continue
        indent, marker, ending = opening.groups()
        fence_char = marker[0]
        nested_depth = 0
        saw_nested = False
        max_size = len(marker)
        outer_close: int | None = None
        for candidate_index in range(index + 1, len(lines)):
            candidate = re.match(
                rf"^( {{0,3}})({re.escape(fence_char)}{{3,}})(.*?)(\r?\n)?$",
                lines[candidate_index],
            )
            if candidate is None:
                continue
            candidate_marker = candidate.group(2)
            remainder = candidate.group(3).strip()
            max_size = max(max_size, len(candidate_marker))
            if remainder:
                nested_depth += 1
                saw_nested = True
            elif nested_depth:
                nested_depth -= 1
            else:
                outer_close = candidate_index
                break
        if saw_nested and outer_close is not None:
            replacement = fence_char * (max_size + 1)
            lines[index] = (
                f"{indent}{replacement}markdown{ending or ''}"
            )
            close_ending = "\n" if lines[outer_close].endswith("\n") else ""
            if lines[outer_close].endswith("\r\n"):
                close_ending = "\r\n"
            close_indent = re.match(r"^ {0,3}", lines[outer_close]).group(0)  # type: ignore[union-attr]
            lines[outer_close] = f"{close_indent}{replacement}{close_ending}"
            index = outer_close + 1
        else:
            index += 1
    return "".join(lines)


__all__ = [
    "CLEAR_VIEWPORT",
    "KITTY_KEYBOARD_OFF",
    "KITTY_KEYBOARD_ON",
    "PALETTE",
    "Palette",
    "RichTerminalRenderer",
]
