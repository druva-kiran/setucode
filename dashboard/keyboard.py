"""Cross-platform keyboard input reader for interactive TUI components.

Supports arrow keys, Enter, Escape, Backspace, and characters across
Windows (msvcrt) and Unix (termios/tty). Also supports mock key injection
for automated testing.
"""
from __future__ import annotations

import os
import sys
from typing import List, Optional

_MOCK_KEYS: List[str] = []


def set_mock_keys(keys: list[str]) -> None:
    """Inject mock keys for automated unit tests."""
    global _MOCK_KEYS
    _MOCK_KEYS = list(keys)


def clear_mock_keys() -> None:
    """Clear mock keys."""
    global _MOCK_KEYS
    _MOCK_KEYS = []


def is_interactive() -> bool:
    """Return True if running in an interactive terminal."""
    if _MOCK_KEYS:
        return True
    try:
        return sys.stdin.isatty()
    except Exception:
        return False


def read_key() -> str:
    """Read a single keypress.

    Returns one of:
      "UP", "DOWN", "LEFT", "RIGHT", "ENTER", "ESC", "BACKSPACE",
      "CTRL_C", "TAB", or the string character representation.
    """
    global _MOCK_KEYS
    if _MOCK_KEYS:
        return _MOCK_KEYS.pop(0)

    if not is_interactive():
        # Fallback for non-interactive / piped environments
        return "ENTER"

    if os.name == "nt":
        return _read_key_windows()
    else:
        return _read_key_posix()


def _read_key_windows() -> str:
    import msvcrt

    try:
        ch = msvcrt.getch()
    except (EOFError, KeyboardInterrupt):
        return "CTRL_C"

    # Arrow keys and functional keys have a 0x00 or 0xe0 prefix
    if ch in (b"\x00", b"\xe0"):
        try:
            ch2 = msvcrt.getch()
        except Exception:
            return "UNKNOWN"

        if ch2 == b"H":
            return "UP"
        elif ch2 == b"P":
            return "DOWN"
        elif ch2 == b"K":
            return "LEFT"
        elif ch2 == b"M":
            return "RIGHT"
        elif ch2 == b"S":
            return "DELETE"
        return "SPECIAL"

    if ch in (b"\r", b"\n"):
        return "ENTER"
    if ch == b"\x1b":
        return "ESC"
    if ch == b"\x08":
        return "BACKSPACE"
    if ch == b"\x03":
        return "CTRL_C"
    if ch == b"\t":
        return "TAB"

    try:
        return ch.decode("utf-8", errors="ignore")
    except Exception:
        return ""


def _read_key_posix() -> str:
    import select
    import termios
    import tty

    fd = sys.stdin.fileno()
    try:
        old_settings = termios.tcgetattr(fd)
    except Exception:
        return "ENTER"

    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
        if ch == "\x1b":
            # Check if there are trailing escape sequence characters
            r, _, _ = select.select([sys.stdin], [], [], 0.05)
            if r:
                ch2 = sys.stdin.read(1)
                if ch2 == "[":
                    ch3 = sys.stdin.read(1)
                    if ch3 == "A":
                        return "UP"
                    elif ch3 == "B":
                        return "DOWN"
                    elif ch3 == "C":
                        return "RIGHT"
                    elif ch3 == "D":
                        return "LEFT"
            return "ESC"

        if ch in ("\r", "\n"):
            return "ENTER"
        if ch in ("\x7f", "\x08"):
            return "BACKSPACE"
        if ch == "\x03":
            return "CTRL_C"
        if ch == "\t":
            return "TAB"

        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
