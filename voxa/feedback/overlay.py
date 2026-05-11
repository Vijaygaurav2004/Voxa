"""
Visual Feedback Module for Voxa.
Provides terminal-based status display as the overlay.

NOTE: Tkinter on macOS requires running on the main thread, which conflicts
with Voxa's interactive input loop. This module provides a lightweight
terminal-only alternative that works reliably on all macOS versions.
"""
from __future__ import annotations

import sys
import threading
from typing import Optional
from voxa.utils.logger import get_logger

log = get_logger("overlay")

# ANSI color codes
_CYAN   = "\033[36m"
_GREEN  = "\033[32m"
_YELLOW = "\033[33m"
_RED    = "\033[31m"
_BLUE   = "\033[34m"
_GRAY   = "\033[90m"
_BOLD   = "\033[1m"
_RESET  = "\033[0m"

_STATE_ICONS = {
    "idle":      (_GRAY,   "◦", "Ready"),
    "listening": (_CYAN,   "◉", "Listening..."),
    "thinking":  (_YELLOW, "◎", "Thinking..."),
    "executing": (_GREEN,  "▶", "Executing..."),
    "error":     (_RED,    "✕", "Error"),
    "done":      (_GREEN,  "✓", "Done"),
}


class VoxaOverlay:
    """
    Terminal-based status display.
    Prints colored status lines to stdout instead of a floating window.
    Fully thread-safe and works on all macOS versions.
    """

    def __init__(self):
        self._state = "idle"
        self._message = ""
        self._lock = threading.Lock()

    def start(self):
        """No-op for terminal mode."""
        log.debug("Overlay started (terminal mode)")

    def stop(self):
        """No-op for terminal mode."""
        pass

    def set_state(self, state: str, message: str = ""):
        """
        Update and display the current state.

        Args:
            state: One of 'idle', 'listening', 'thinking', 'executing', 'error', 'done'
            message: Optional status message.
        """
        with self._lock:
            self._state = state
            self._message = message

        color, icon, default_text = _STATE_ICONS.get(state, (_GRAY, "◦", state))
        display = message if message else default_text

        # Only print non-idle state changes to avoid console spam
        if state != "idle":
            # Use \r to overwrite the line for executing updates
            end = "\r" if state == "executing" else "\n"
            print(f"  {color}{_BOLD}{icon}{_RESET} {color}{display}{_RESET}", end=end, flush=True)

        # Auto-reset to idle line after done/error
        if state in ("done", "error"):
            print()  # Ensure newline after final status
