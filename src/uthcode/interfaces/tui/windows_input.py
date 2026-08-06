"""Windows Unicode console input with a Shift+Enter key distinction."""

from __future__ import annotations

import sys

from prompt_toolkit.input.base import Input


if sys.platform == "win32":
    from prompt_toolkit.input.win32 import ConsoleInputReader, Win32Input
    from prompt_toolkit.key_binding.key_processor import KeyPress
    from prompt_toolkit.keys import Keys
    from prompt_toolkit.win32_types import KEY_EVENT_RECORD

    class _UthCodeConsoleInputReader(ConsoleInputReader):
        def _event_to_key_presses(
            self,
            event: KEY_EVENT_RECORD,
        ) -> list[KeyPress]:
            keys = super()._event_to_key_presses(event)
            if event.ControlKeyState & self.SHIFT_PRESSED:
                return [
                    KeyPress(Keys.ControlJ, "\n")
                    if key.key == Keys.ControlM
                    else key
                    for key in keys
                ]
            return keys

    class _UthCodeWindowsInput(Win32Input):
        def __init__(self) -> None:
            super().__init__()
            # Native records preserve both IME Unicode and the Shift modifier.
            self._use_virtual_terminal_input = False
            self.console_input_reader = _UthCodeConsoleInputReader()


def create_windows_unicode_input() -> Input:
    """Create prompt_toolkit input backed by native Windows console events."""

    if sys.platform != "win32":
        raise RuntimeError("Windows console input is only available on Windows")
    return _UthCodeWindowsInput()


__all__ = ["create_windows_unicode_input"]
