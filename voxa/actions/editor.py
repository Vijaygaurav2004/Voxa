"""
Editor AI Integration for Voxa.

Sends voice prompts directly into AI coding assistants:
  - VS Code  → GitHub Copilot Chat  (Ctrl+Shift+I)
  - Cursor   → Cursor AI Chat       (Cmd+L)
  - Windsurf → Cascade Chat         (Cmd+L)
  - Xcode    → GitHub Copilot       (Cmd+Ctrl+P or toolbar icon)

All methods:
1. Activate the editor app
2. Open the AI chat panel via keyboard shortcut
3. Clear any existing text in the input
4. Type the prompt
5. Press Enter to submit
"""
from __future__ import annotations

import subprocess
import time
from typing import Optional
from voxa.utils.applescript import run_applescript, AppleScriptError
from voxa.utils.logger import get_logger

log = get_logger("editor")

# ── Known editors and their AI shortcuts ──────────────────────────────────────

EDITOR_CONFIGS = {
    "Visual Studio Code": {
        "process": "Code",
        "copilot_chat_key": "ctrl+shift+i",      # Copilot Chat panel
        "inline_chat_key": "cmd+i",               # Copilot inline
        "agent_key": "ctrl+shift+i",              # Same panel, switch to Agent tab
    },
    "Cursor": {
        "process": "Cursor",
        "copilot_chat_key": "cmd+l",              # Cursor AI chat sidebar
        "inline_chat_key": "cmd+k",               # Cursor inline edit
        "agent_key": "cmd+l",
    },
    "Windsurf": {
        "process": "Windsurf",
        "copilot_chat_key": "cmd+l",              # Cascade chat
        "inline_chat_key": "cmd+i",
        "agent_key": "cmd+l",
    },
    "Xcode": {
        "process": "Xcode",
        "copilot_chat_key": "cmd+ctrl+p",         # Copilot chat
        "inline_chat_key": "cmd+ctrl+p",
        "agent_key": "cmd+ctrl+p",
    },
}

# Shorthand aliases users might say
EDITOR_ALIASES = {
    "vscode": "Visual Studio Code",
    "vs code": "Visual Studio Code",
    "code": "Visual Studio Code",
    "cursor": "Cursor",
    "windsurf": "Windsurf",
    "xcode": "Xcode",
}


# ── Internal helpers ──────────────────────────────────────────────────────────

def _get_frontmost_app() -> str:
    """Return the name of the currently focused app."""
    try:
        return run_applescript(
            'tell application "System Events" to return name of first process whose frontmost is true',
            timeout=5,
        ) or ""
    except Exception:
        return ""


def _resolve_editor(app_hint: Optional[str] = None) -> Optional[dict]:
    """
    Resolve which editor to target.
    If app_hint is given, use that. Otherwise detect frontmost editor.
    Returns the config dict or None.
    """
    if app_hint:
        # Check aliases
        normalized = app_hint.lower().strip()
        full_name = EDITOR_ALIASES.get(normalized, app_hint)
        for name, cfg in EDITOR_CONFIGS.items():
            if name.lower() == full_name.lower() or cfg["process"].lower() == full_name.lower():
                return {"name": name, **cfg}
        return None

    # Auto-detect: check which editor is running and frontmost
    front = _get_frontmost_app()
    for name, cfg in EDITOR_CONFIGS.items():
        if cfg["process"] in front or name in front:
            return {"name": name, **cfg}

    # Check if any editor is running (even if not frontmost)
    try:
        running = run_applescript(
            'tell application "System Events" to return name of every process whose background only is false',
            timeout=5,
        ) or ""
        for name, cfg in EDITOR_CONFIGS.items():
            if cfg["process"] in running:
                return {"name": name, **cfg}
    except Exception:
        pass

    return None


def _open_chat_and_send(editor_cfg: dict, prompt: str, mode: str = "chat") -> dict:
    """
    Core function: activate editor, open AI panel, send prompt.

    mode: "chat" | "inline" | "agent"
    """
    app_name = editor_cfg["name"]
    process  = editor_cfg["process"]

    key_map = {
        "chat":   editor_cfg.get("copilot_chat_key", "ctrl+shift+i"),
        "inline": editor_cfg.get("inline_chat_key",  "cmd+i"),
        "agent":  editor_cfg.get("agent_key",         "ctrl+shift+i"),
    }
    shortcut = key_map.get(mode, key_map["chat"])

    log.info("🤖 [%s] Sending %s prompt: %s", app_name, mode, prompt[:60])

    # Escape the prompt for AppleScript keystroke
    safe_prompt = (
        prompt
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", " ")
    )

    # Convert shortcut string to AppleScript modifier syntax
    as_keys = _shortcut_to_applescript(shortcut, safe_prompt)

    script = f'''
        tell application "{app_name}" to activate
        delay 0.8

        tell application "System Events"
            tell process "{process}"
                -- Open AI chat panel
                {as_keys}
                delay 1.2

                -- Clear any existing text (select all + delete)
                keystroke "a" using command down
                delay 0.2
                key code 51  -- delete/backspace
                delay 0.2

                -- Type the prompt
                keystroke "{safe_prompt}"
                delay 0.4

                -- Submit
                key code 36  -- Return
            end tell
        end tell
    '''

    try:
        run_applescript(script, timeout=20)
        return {
            "success": True,
            "action": "editor_ai_prompt",
            "editor": app_name,
            "mode": mode,
            "message": "Sent to {} {} chat: {}".format(app_name, mode, prompt[:50]),
        }
    except AppleScriptError as e:
        log.error("Editor AI prompt failed: %s", e)
        return {
            "success": False,
            "action": "editor_ai_prompt",
            "error": str(e),
            "message": "Could not send to {} — make sure {} is open".format(app_name, app_name),
        }


def _shortcut_to_applescript(shortcut: str, prompt: str) -> str:
    """
    Convert a shortcut string like 'ctrl+shift+i' into an AppleScript
    keystroke/key code command. Returns the AppleScript lines to inject.
    """
    parts = [p.strip().lower() for p in shortcut.split("+")]
    key   = parts[-1]
    mods  = parts[:-1]

    modifier_map = {
        "cmd":    "command down",
        "command": "command down",
        "ctrl":   "control down",
        "control": "control down",
        "shift":  "shift down",
        "alt":    "option down",
        "option": "option down",
    }

    key_code_map = {
        "i": 34,
        "l": 37,
        "p": 35,
        "k": 40,
        "t": 17,
        "s": 1,
        "n": 45,
    }

    as_mods = ", ".join(modifier_map[m] for m in mods if m in modifier_map)
    mod_str = f" using {{{as_mods}}}" if as_mods else ""

    if key in key_code_map:
        kc = key_code_map[key]
        return f"key code {kc}{mod_str}"
    else:
        return f'keystroke "{key}"{mod_str}'


# ── Public API ────────────────────────────────────────────────────────────────

def send_to_editor_ai(prompt: str, app: Optional[str] = None, mode: str = "chat") -> dict:
    """
    Send a voice prompt to the AI assistant in the user's coding editor.

    Automatically detects VS Code / Cursor / Windsurf / Xcode.
    If no editor is open, returns a helpful error.

    Args:
        prompt: The natural language prompt to send.
        app:    Optional editor override ("cursor", "vscode", etc.)
        mode:   "chat" | "inline" | "agent"
    """
    cfg = _resolve_editor(app)

    if cfg is None:
        # No editor found — tell the user clearly
        editors = list(EDITOR_CONFIGS.keys())
        return {
            "success": False,
            "action": "editor_ai_prompt",
            "message": "No coding editor is open. Please open VS Code, Cursor, or Windsurf first.",
        }

    return _open_chat_and_send(cfg, prompt, mode=mode)


def send_to_vscode_copilot(prompt: str, mode: str = "chat") -> dict:
    """Explicitly target VS Code Copilot Chat."""
    cfg = _resolve_editor("Visual Studio Code")
    if cfg is None:
        return {"success": False, "action": "copilot_prompt",
                "message": "VS Code is not open or not installed."}
    return _open_chat_and_send(cfg, prompt, mode=mode)


def send_to_cursor(prompt: str, mode: str = "chat") -> dict:
    """Explicitly target Cursor AI."""
    cfg = _resolve_editor("Cursor")
    if cfg is None:
        return {"success": False, "action": "cursor_prompt",
                "message": "Cursor is not open or not installed."}
    return _open_chat_and_send(cfg, prompt, mode=mode)


def send_to_windsurf(prompt: str, mode: str = "chat") -> dict:
    """Explicitly target Windsurf Cascade."""
    cfg = _resolve_editor("Windsurf")
    if cfg is None:
        return {"success": False, "action": "windsurf_prompt",
                "message": "Windsurf is not open or not installed."}
    return _open_chat_and_send(cfg, prompt, mode=mode)


def get_active_editor() -> dict:
    """Return which editor is currently active, for diagnostic purposes."""
    cfg = _resolve_editor()
    if cfg:
        return {"success": True, "editor": cfg["name"],
                "message": "Active editor: {}".format(cfg["name"])}
    return {"success": False, "message": "No known coding editor is running"}
