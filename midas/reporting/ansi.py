"""ANSI colour helpers. The only module that knows an escape code exists."""

from __future__ import annotations

import sys

CODES = {"bold": "1", "red": "31", "green": "32", "yellow": "33",
         "cyan": "36", "grey": "90"}


class Palette:
    """Wraps text in colour, or leaves it alone when output is not a terminal.

    Passing `enabled=False` (a pipe, a log file, a test) yields plain strings,
    so the same formatting code produces both coloured and clean output.
    """

    def __init__(self, enabled: bool | None = None):
        self.enabled = sys.stdout.isatty() if enabled is None else bool(enabled)

    def paint(self, style: str, text) -> str:
        if not self.enabled or style not in CODES:
            return str(text)
        return f"\033[{CODES[style]}m{text}\033[0m"

    def __getattr__(self, style):
        if style not in CODES:
            raise AttributeError(style)
        return lambda text: self.paint(style, text)


DEFAULT = Palette()
