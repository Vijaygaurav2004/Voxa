"""
Clipboard Module for Voxa.
Read, write, and paste clipboard contents using macOS pbcopy/pbpaste.
"""
from __future__ import annotations

import subprocess
from voxa.utils.applescript import run_applescript, AppleScriptError
from voxa.utils.logger import get_logger

log = get_logger("clipboard")


def get_clipboard() -> dict:
    """
    Read the current clipboard contents and speak/return them.

    Returns:
        Result dict with clipboard text content.
    """
    log.info("📋 Reading clipboard")
    try:
        result = subprocess.run(
            ["pbpaste"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        content = result.stdout.strip()
        if not content:
            return {
                "success": True,
                "action": "clipboard_get",
                "content": "",
                "message": "Clipboard is empty",
            }

        # Truncate for voice feedback
        preview = content[:200] + ("..." if len(content) > 200 else "")
        return {
            "success": True,
            "action": "clipboard_get",
            "content": content,
            "message": f"Clipboard contains: {preview}",
        }
    except Exception as e:
        log.error("Failed to read clipboard: %s", e)
        return {
            "success": False,
            "action": "clipboard_get",
            "error": str(e),
            "message": "Could not read clipboard",
        }


def set_clipboard(text: str) -> dict:
    """
    Write text to the clipboard.

    Args:
        text: The text to copy to clipboard.
    """
    log.info("📋 Writing to clipboard: \"%s\"", text[:50])
    try:
        result = subprocess.run(
            ["pbcopy"],
            input=text,
            text=True,
            capture_output=True,
            timeout=5,
        )
        if result.returncode == 0:
            return {
                "success": True,
                "action": "clipboard_set",
                "content": text,
                "message": f"Copied to clipboard: \"{text[:50]}{'...' if len(text) > 50 else ''}\"",
            }
        else:
            return {
                "success": False,
                "action": "clipboard_set",
                "error": result.stderr,
                "message": "Failed to write to clipboard",
            }
    except Exception as e:
        log.error("Failed to write clipboard: %s", e)
        return {
            "success": False,
            "action": "clipboard_set",
            "error": str(e),
            "message": "Could not write to clipboard",
        }


def paste_clipboard() -> dict:
    """
    Paste the clipboard contents into the currently focused application.
    Uses Cmd+V keystroke via AppleScript.
    """
    log.info("📋 Pasting clipboard")
    try:
        run_applescript('''
            tell application "System Events"
                keystroke "v" using {command down}
            end tell
        ''')
        return {
            "success": True,
            "action": "clipboard_paste",
            "message": "Pasted clipboard content",
        }
    except AppleScriptError as e:
        log.error("Failed to paste clipboard: %s", e)
        return {
            "success": False,
            "action": "clipboard_paste",
            "error": str(e),
            "message": "Failed to paste — Accessibility permission may be needed",
        }


def clear_clipboard() -> dict:
    """Clear the clipboard."""
    log.info("📋 Clearing clipboard")
    try:
        subprocess.run(["pbcopy"], input="", text=True, timeout=5)
        return {
            "success": True,
            "action": "clipboard_clear",
            "message": "Clipboard cleared",
        }
    except Exception as e:
        return {
            "success": False,
            "action": "clipboard_clear",
            "error": str(e),
            "message": "Could not clear clipboard",
        }
