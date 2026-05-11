"""
App Control Module for Voxa.
Opens, closes, activates, and queries macOS applications via AppleScript.
"""
from __future__ import annotations

import time
from voxa.utils.applescript import run_applescript, escape_applescript_string, AppleScriptError
from voxa.utils.logger import get_logger

log = get_logger("app_control")


# Common app name aliases — maps LLM-generated names to actual macOS app names
APP_ALIASES = {
    "visual studio code": "Cursor",  # VS Code not installed; user uses Cursor
    "vscode": "Cursor",
    "vs code": "Cursor",
    "code": "Cursor",
    "terminal": "Terminal",
    "iterm": "iTerm",
    "iterm2": "iTerm",
    "chrome": "Google Chrome",
    "firefox": "Firefox",
    "safari": "Safari",
    "word": "Microsoft Word",
    "excel": "Microsoft Excel",
    "powerpoint": "Microsoft PowerPoint",
    "outlook": "Microsoft Outlook",
    "slack": "Slack",
    "discord": "Discord",
    "zoom": "zoom.us",
    "notes": "Notes",
    "mail": "Mail",
    "photos": "Photos",
    "music": "Music",
    "podcasts": "Podcasts",
    "messages": "Messages",
    "facetime": "FaceTime",
}


def _resolve_app_name(app_name: str) -> str:
    """Resolve common app name aliases to the actual macOS app name."""
    return APP_ALIASES.get(app_name.lower().strip(), app_name)


def open_app(app_name: str) -> dict:
    """
    Open/activate a macOS application by name.
    Resolves common aliases (e.g. 'VS Code' → 'Cursor').
    Falls back to `open -a` if AppleScript doesn't know the app name.
    """
    resolved = _resolve_app_name(app_name)
    if resolved != app_name:
        log.info("📌 Resolved '%s' → '%s'", app_name, resolved)
    app_name = resolved

    safe_name = escape_applescript_string(app_name)
    log.info("🚀 Opening app: %s", app_name)

    try:
        # First try AppleScript activate
        run_applescript(f'tell application "{safe_name}" to activate')
        time.sleep(0.5)
        return {"success": True, "action": "open_app", "app": app_name, "message": f"Opened {app_name}"}

    except AppleScriptError:
        # Fallback: try `open -a "App Name"` (works for most apps by bundle name)
        import subprocess
        log.info("⚡ AppleScript failed — trying 'open -a %s'", app_name)
        try:
            result = subprocess.run(
                ["open", "-a", app_name],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                time.sleep(1.0)
                return {"success": True, "action": "open_app", "app": app_name, "message": f"Opened {app_name}"}
            else:
                err = result.stderr.strip()
                log.error("Failed to open %s: %s", app_name, err)
                return {"success": False, "action": "open_app", "app": app_name, "error": err,
                        "message": f"Could not open {app_name}. Is it installed?"}
        except Exception as e:
            log.error("Failed to open %s: %s", app_name, e)
            return {"success": False, "action": "open_app", "app": app_name, "error": str(e),
                    "message": f"Could not open {app_name}. Is it installed?"}



def close_app(app_name: str) -> dict:
    """Quit a macOS application by name."""
    safe_name = escape_applescript_string(app_name)
    log.info("❌ Closing app: %s", app_name)

    try:
        run_applescript(f'tell application "{safe_name}" to quit')
        return {
            "success": True,
            "action": "close_app",
            "app": app_name,
            "message": f"Closed {app_name}",
        }
    except AppleScriptError as e:
        log.error("Failed to close %s: %s", app_name, e)
        return {
            "success": False,
            "action": "close_app",
            "app": app_name,
            "error": str(e),
            "message": f"Could not close {app_name}",
        }


def is_app_running(app_name: str) -> bool:
    """Check if an application is currently running."""
    safe_name = escape_applescript_string(app_name)
    try:
        result = run_applescript(f'''
            tell application "System Events"
                return (name of every process) contains "{safe_name}"
            end tell
        ''')
        return result == "true"
    except AppleScriptError:
        return False


def get_frontmost_app() -> str | None:
    """Get the name of the currently focused application."""
    try:
        result = run_applescript('''
            tell application "System Events"
                return name of first application process whose frontmost is true
            end tell
        ''')
        return result
    except AppleScriptError:
        return None


def list_running_apps() -> list[str]:
    """Get a list of all currently running applications."""
    try:
        result = run_applescript('''
            tell application "System Events"
                return name of every application process whose background only is false
            end tell
        ''')
        if result:
            return [app.strip() for app in result.split(",")]
        return []
    except AppleScriptError:
        return []
