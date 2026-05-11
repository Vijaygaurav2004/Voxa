"""
Typing & Keystroke Module for Voxa.
Simulates keyboard input via AppleScript System Events.
"""
from __future__ import annotations

import time
from voxa.utils.applescript import run_applescript, escape_applescript_string, AppleScriptError
from voxa.utils.logger import get_logger

log = get_logger("typing")

# Mapping of human-readable key names to AppleScript key codes
KEY_MAP = {
    "return": "return",
    "enter": "return",
    "tab": "tab",
    "escape": "escape",
    "esc": "escape",
    "space": "space",
    "delete": "delete",
    "backspace": "delete",
    "up": "up arrow",
    "down": "down arrow",
    "left": "left arrow",
    "right": "right arrow",
    "home": "home",
    "end": "end",
    "pageup": "page up",
    "pagedown": "page down",
}

# Modifier key mapping
MODIFIER_MAP = {
    "cmd": "command down",
    "command": "command down",
    "ctrl": "control down",
    "control": "control down",
    "alt": "option down",
    "option": "option down",
    "shift": "shift down",
}


def type_text(text: str) -> dict:
    """
    Type text at the current cursor position using System Events keystroke.

    Args:
        text: The text to type.
    """
    safe_text = escape_applescript_string(text)
    log.info("⌨️  Typing: \"%s\"", text[:50])

    try:
        script = f'''
            tell application "System Events"
                keystroke "{safe_text}"
            end tell
        '''
        run_applescript(script)
        return {
            "success": True,
            "action": "type_text",
            "text": text,
            "message": f"Typed text: '{text[:30]}...'",
        }
    except AppleScriptError as e:
        log.error("Failed to type text: %s", e)
        return {
            "success": False,
            "action": "type_text",
            "error": str(e),
            "message": "Failed to type text — Accessibility permission may be needed",
        }


def send_keystroke(keys: str) -> dict:
    """
    Send a keyboard shortcut.
    Format: "cmd+shift+n", "return", "cmd+t", "cmd+a"

    Args:
        keys: Key combination string (e.g., "cmd+c", "cmd+shift+t").
    """
    log.info("🎹 Keystroke: %s", keys)

    try:
        parts = [p.strip().lower() for p in keys.split("+")]

        # Separate modifiers from the main key
        modifiers = []
        main_key = None

        for part in parts:
            if part in MODIFIER_MAP:
                modifiers.append(MODIFIER_MAP[part])
            elif part in KEY_MAP:
                main_key = KEY_MAP[part]
            else:
                main_key = part  # Assume it's a character key

        if main_key is None:
            return {
                "success": False,
                "action": "keystroke",
                "error": f"Could not parse key: {keys}",
                "message": f"Invalid keystroke: {keys}",
            }

        # Build AppleScript
        if main_key in KEY_MAP.values():
            # It's a special key — use "key code" approach
            key_part = f'key code (key code of "{main_key}")'
            # Actually, for special keys use the key name
            if modifiers:
                modifier_str = ", ".join(modifiers)
                script = f'''
                    tell application "System Events"
                        key code {_get_key_code(main_key)} using {{{modifier_str}}}
                    end tell
                '''
            else:
                script = f'''
                    tell application "System Events"
                        key code {_get_key_code(main_key)}
                    end tell
                '''
        else:
            # It's a character key — use keystroke
            safe_key = escape_applescript_string(main_key)
            if modifiers:
                modifier_str = ", ".join(modifiers)
                script = f'''
                    tell application "System Events"
                        keystroke "{safe_key}" using {{{modifier_str}}}
                    end tell
                '''
            else:
                script = f'''
                    tell application "System Events"
                        keystroke "{safe_key}"
                    end tell
                '''

        run_applescript(script)
        return {
            "success": True,
            "action": "keystroke",
            "keys": keys,
            "message": f"Pressed {keys}",
        }
    except AppleScriptError as e:
        log.error("Failed keystroke %s: %s", keys, e)
        return {
            "success": False,
            "action": "keystroke",
            "error": str(e),
            "message": f"Failed to press {keys}",
        }


def _get_key_code(key_name: str) -> int:
    """Map special key names to macOS virtual key codes."""
    codes = {
        "return": 36,
        "tab": 48,
        "space": 49,
        "delete": 51,
        "escape": 53,
        "up arrow": 126,
        "down arrow": 125,
        "left arrow": 123,
        "right arrow": 124,
        "home": 115,
        "end": 119,
        "page up": 116,
        "page down": 121,
    }
    return codes.get(key_name, 36)  # Default to return
