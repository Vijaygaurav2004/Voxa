"""
Computer Control Module for Voxa.
Gives full mouse + keyboard control over ANY macOS app via:
  1. Smart Vision Click — GPT-4o looks at screenshot, returns (x,y) of element
  2. Raw mouse: click, double-click, right-click, scroll, drag
  3. Accessibility (AX) tree: click buttons/menu items/text fields by name
  4. Universal app open via Spotlight + open -a
"""
from __future__ import annotations

import base64
import subprocess
import tempfile
import os
import time
from typing import Optional
from voxa.utils.applescript import run_applescript, AppleScriptError
from voxa.utils.logger import get_logger

log = get_logger("computer")

# ── Internal helpers ──────────────────────────────────────────────────────────

def _screenshot_b64() -> Optional[str]:
    """Take a silent screenshot and return base64-encoded PNG."""
    try:
        fd, path = tempfile.mkstemp(suffix=".png", prefix="voxa_cc_")
        os.close(fd)
        r = subprocess.run(["screencapture", "-x", path], capture_output=True, timeout=8)
        if r.returncode == 0 and os.path.exists(path):
            with open(path, "rb") as f:
                return base64.b64encode(f.read()).decode()
    except Exception as e:
        log.warning("Screenshot failed: %s", e)
    finally:
        try:
            os.unlink(path)
        except Exception:
            pass
    return None


def _screen_size() -> tuple[int, int]:
    """Return (width, height) of the main display."""
    try:
        out = subprocess.check_output(
            ["osascript", "-e",
             'tell application "Finder" to return bounds of window of desktop'],
            text=True, timeout=5,
        ).strip()
        parts = [int(x.strip()) for x in out.split(",")]
        return parts[2], parts[3]
    except Exception:
        return 1440, 900  # safe default


def _clic(x: int, y: int, button: str = "l", double: bool = False):
    """Click at screen coordinates using cliclick or AppleScript."""
    # Use cliclick if available (more reliable than AppleScript for mouse)
    r = subprocess.run(["which", "cliclick"], capture_output=True, text=True)
    if r.returncode == 0:
        cmd = ["cliclick"]
        if double:
            cmd += [f"dc:{x},{y}"]
        elif button == "r":
            cmd += [f"rc:{x},{y}"]
        else:
            cmd += [f"c:{x},{y}"]
        subprocess.run(cmd, timeout=5)
    else:
        # Pure AppleScript mouse click — use correct coordinate syntax
        clicks = 2 if double else 1
        btn_code = 2 if button == "r" else 1
        for _ in range(clicks):
            run_applescript(f"""
                tell application "System Events"
                    click at {{{x}, {y}}}
                end tell
            """, timeout=5)
            if double:
                time.sleep(0.05)


# ── Vision-powered smart click ────────────────────────────────────────────────

def vision_click(description: str, double: bool = False, right: bool = False) -> dict:
    """
    Find a UI element by natural language description and click it.
    Uses GPT-4o Vision to locate the element on screen.
    """
    from voxa.config import config
    log.info("🖱️  Vision click: '%s'", description)

    img_b64 = _screenshot_b64()
    if not img_b64:
        return {"success": False, "action": "vision_click", "message": "Could not capture screen"}

    w, h = _screen_size()

    try:
        from openai import OpenAI
        client = OpenAI(api_key=config.OPENAI_API_KEY)

        prompt = (
            f"The screen is {w}x{h} pixels. "
            f"Find the UI element described as: '{description}'. "
            "Return ONLY a JSON object like {\"x\": 123, \"y\": 456} with the pixel coordinates "
            "of the CENTER of that element. If not found, return {\"x\": null, \"y\": null}."
        )

        resp = client.chat.completions.create(
            model="gpt-4o",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}", "detail": "high"}},
                    {"type": "text", "text": prompt},
                ],
            }],
            max_tokens=60,
            response_format={"type": "json_object"},
        )

        import json
        coords = json.loads(resp.choices[0].message.content)
        x, y = coords.get("x"), coords.get("y")

        if x is None or y is None:
            return {"success": False, "action": "vision_click",
                    "message": f"Could not find '{description}' on screen"}

        x, y = int(x), int(y)
        log.info("🎯 Found '%s' at (%d, %d) — clicking", description, x, y)
        _clic(x, y, button="r" if right else "l", double=double)
        time.sleep(0.3)

        action_word = "Right-clicked" if right else ("Double-clicked" if double else "Clicked")
        return {"success": True, "action": "vision_click",
                "message": f"{action_word} '{description}'", "x": x, "y": y}

    except Exception as e:
        log.error("Vision click failed: %s", e)
        return {"success": False, "action": "vision_click", "error": str(e),
                "message": f"Could not click '{description}': {e}"}


# ── Raw mouse actions ─────────────────────────────────────────────────────────

def click_at(x: int, y: int, double: bool = False, right: bool = False) -> dict:
    """Click at exact screen coordinates."""
    log.info("🖱️  Click at (%d, %d) double=%s right=%s", x, y, double, right)
    try:
        _clic(x, y, button="r" if right else "l", double=double)
        word = "Right-clicked" if right else ("Double-clicked" if double else "Clicked")
        return {"success": True, "action": "click_at", "message": f"{word} at ({x}, {y})"}
    except Exception as e:
        return {"success": False, "action": "click_at", "error": str(e),
                "message": f"Click failed: {e}"}


def scroll(direction: str = "down", amount: int = 3) -> dict:
    """Scroll in the focused window."""
    log.info("🔱️  Scroll %s x%d", direction, amount)
    delta = -amount if direction == "down" else amount
    try:
        # Try cliclick first (most reliable scroll wheel simulation)
        r = subprocess.run(["which", "cliclick"], capture_output=True, text=True)
        if r.returncode == 0:
            subprocess.run(["cliclick", f"kp:arrow-{'down' if direction == 'down' else 'up'}"], timeout=5)
        else:
            # Fallback: use AppleScript scroll event
            run_applescript(f"""
                tell application "System Events"
                    scroll (first process whose frontmost is true) by {delta}
                end tell
            """, timeout=5)
    except Exception:
        # Last resort: arrow keys
        key = "125" if direction == "down" else "126"  # down/up arrow keycodes
        for _ in range(amount * 3):
            run_applescript(f'tell application "System Events" to key code {key}', timeout=3)
    return {"success": True, "action": "scroll", "message": f"Scrolled {direction}"}


def drag(from_x: int, from_y: int, to_x: int, to_y: int) -> dict:
    """Click and drag from one point to another."""
    log.info("🖱️  Drag (%d,%d) → (%d,%d)", from_x, from_y, to_x, to_y)
    try:
        r = subprocess.run(["which", "cliclick"], capture_output=True, text=True)
        if r.returncode == 0:
            subprocess.run(["cliclick", f"dd:{from_x},{from_y}", f"du:{to_x},{to_y}"], timeout=10)
        else:
            run_applescript(f"""
                tell application "System Events"
                    set origPos to {{from_x, from_y}}
                    set destPos to {{to_x, to_y}}
                    drag from origPos to destPos
                end tell
            """, timeout=10)
        return {"success": True, "action": "drag",
                "message": f"Dragged from ({from_x},{from_y}) to ({to_x},{to_y})"}
    except Exception as e:
        return {"success": False, "action": "drag", "error": str(e),
                "message": f"Drag failed: {e}"}


# ── AX Accessibility UI control ───────────────────────────────────────────────

def ax_click_button(app: str, button_name: str, window_index: int = 1) -> dict:
    """Click a button by name in any app using Accessibility API."""
    log.info("🔘 AX click button '%s' in '%s'", button_name, app)
    try:
        result = run_applescript(f"""
            tell application "System Events"
                tell process "{app}"
                    click button "{button_name}" of window {window_index}
                end tell
            end tell
        """, timeout=8)
        return {"success": True, "action": "ax_click", "message": f"Clicked '{button_name}' in {app}"}
    except AppleScriptError as e:
        log.warning("Button click failed: %s — trying fuzzy search", e)
        # Fuzzy: find any button whose name contains the text
        try:
            result = run_applescript(f"""
                tell application "System Events"
                    tell process "{app}"
                        set btns to every button of window {window_index}
                        repeat with b in btns
                            if name of b contains "{button_name}" then
                                click b
                                return "ok"
                            end if
                        end repeat
                        return "none"
                    end tell
                end tell
            """, timeout=10)
            if result == "ok":
                return {"success": True, "action": "ax_click",
                        "message": f"Clicked button matching '{button_name}'"}
        except Exception:
            pass
        return {"success": False, "action": "ax_click", "error": str(e),
                "message": f"Could not click '{button_name}' in {app}"}


def ax_click_menu(app: str, menu_path: list[str]) -> dict:
    """
    Click a menu item by path. menu_path = ["File", "Open..."]
    Works for any macOS app's menu bar.
    """
    log.info("📋 AX menu click: %s → %s", app, " → ".join(menu_path))
    try:
        if len(menu_path) == 2:
            menu, item = menu_path
            script = f"""
                tell application "{app}" to activate
                delay 0.3
                tell application "System Events"
                    tell process "{app}"
                        click menu item "{item}" of menu "{menu}" of menu bar item "{menu}" of menu bar 1
                    end tell
                end tell
            """
        elif len(menu_path) == 3:
            menu, submenu, item = menu_path
            script = f"""
                tell application "{app}" to activate
                delay 0.3
                tell application "System Events"
                    tell process "{app}"
                        tell menu bar 1
                            click menu item "{submenu}" of menu "{menu}" of menu bar item "{menu}"
                            delay 0.2
                            click menu item "{item}" of menu "{submenu}" of menu item "{submenu}" of menu "{menu}" of menu bar item "{menu}"
                        end tell
                    end tell
                end tell
            """
        else:
            return {"success": False, "action": "ax_menu",
                    "message": "Menu path must have 2 or 3 items"}

        run_applescript(script, timeout=10)
        return {"success": True, "action": "ax_menu",
                "message": f"Clicked menu: {' → '.join(menu_path)}"}
    except AppleScriptError as e:
        return {"success": False, "action": "ax_menu", "error": str(e),
                "message": f"Menu click failed: {e}"}


def ax_type_in_field(app: str, field_hint: str, text: str, window_index: int = 1) -> dict:
    """Click a text field matching field_hint then type text."""
    log.info("⌨️  AX type in '%s' field of '%s'", field_hint, app)
    try:
        run_applescript(f"""
            tell application "System Events"
                tell process "{app}"
                    set flds to every text field of window {window_index}
                    repeat with f in flds
                        if description of f contains "{field_hint}" or value of f contains "{field_hint}" then
                            click f
                            delay 0.2
                            set value of f to "{text}"
                            return "ok"
                        end if
                    end repeat
                    -- fallback: click first text field and type
                    if (count of flds) > 0 then
                        click (first item of flds)
                        delay 0.2
                        keystroke "{text}"
                        return "ok"
                    end if
                    return "none"
                end tell
            end tell
        """, timeout=10)
        return {"success": True, "action": "ax_type",
                "message": f"Typed '{text[:30]}' in {app}"}
    except AppleScriptError as e:
        return {"success": False, "action": "ax_type", "error": str(e),
                "message": f"Could not type in {app}: {e}"}


# ── Universal open + focus ────────────────────────────────────────────────────

_APP_ALIASES_CC = {
    "visual studio code": "Cursor",
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
    "keynote": "Keynote",
    "pages": "Pages",
    "numbers": "Numbers",
    "xcode": "Xcode",
    "system settings": "System Settings",
    "system preferences": "System Settings",
    "app store": "App Store",
    "calculator": "Calculator",
    "calendar": "Calendar",
    "contacts": "Contacts",
    "maps": "Maps",
    "preview": "Preview",
    "finder": "Finder",
    "activity monitor": "Activity Monitor",
    "font book": "Font Book",
    "textedit": "TextEdit",
    "stickies": "Stickies",
    "voice memos": "Voice Memos",
    "reminders": "Reminders",
    "shortcuts": "Shortcuts",
    "automator": "Automator",
    "script editor": "Script Editor",
    "console": "Console",
    "disk utility": "Disk Utility",
    "keychain access": "Keychain Access",
    "migration assistant": "Migration Assistant",
    "time machine": "Time Machine",
    "boot camp assistant": "Boot Camp Assistant",
}


def _resolve_cc_app_name(app_name: str) -> str:
    """Resolve app name aliases and strip generic suffixes like 'application', 'app'."""
    cleaned = app_name.strip()

    # Strip leading "the " (e.g. "the calendar app" → "calendar app")
    if cleaned.lower().startswith("the "):
        cleaned = cleaned[4:].strip()

    # Strip trailing generic suffixes
    for suffix in [" application", " app", " program", " software"]:
        if cleaned.lower().endswith(suffix):
            cleaned = cleaned[:-len(suffix)].strip()

    # Look up alias (lowercase match)
    resolved = _APP_ALIASES_CC.get(cleaned.lower())
    if resolved:
        return resolved

    # Fallback: title-case the cleaned name (e.g. "google chrome" → "Google Chrome")
    return " ".join(word.capitalize() for word in cleaned.split())


def open_any_app(app_name: str) -> dict:
    """
    Open any macOS app dynamically.
    Resolves aliases and strips generic suffixes before attempting open.
    Tries: AppleScript activate → open -a → Spotlight mdfind.
    """
    resolved = _resolve_cc_app_name(app_name)
    if resolved != app_name:
        log.info("📌 Resolved app name '%s' → '%s'", app_name, resolved)
    app_name = resolved

    log.info("🚀 Universal open: %s", app_name)

    # 1. Try AppleScript (fastest for known apps)
    try:
        run_applescript(f'tell application "{app_name}" to activate', timeout=8)
        time.sleep(0.8)
        return {"success": True, "action": "open_app", "message": f"Opened {app_name}"}
    except AppleScriptError:
        pass

    # 2. Try open -a (works for any .app bundle name)
    r = subprocess.run(["open", "-a", app_name], capture_output=True, text=True, timeout=10)
    if r.returncode == 0:
        time.sleep(1.2)
        return {"success": True, "action": "open_app", "message": f"Opened {app_name}"}

    # 3. Spotlight: find .app path and open it
    try:
        out = subprocess.check_output(
            ["mdfind", "-name", app_name, "kind:application"],
            text=True, timeout=8,
        ).strip().splitlines()
        apps = [p for p in out if p.endswith(".app")]
        if apps:
            subprocess.run(["open", apps[0]], timeout=10)
            time.sleep(1.2)
            return {"success": True, "action": "open_app",
                    "message": f"Opened {app_name} from {apps[0]}"}
    except Exception as e:
        log.warning("Spotlight open failed: %s", e)

    return {"success": False, "action": "open_app",
            "message": f"Could not find or open '{app_name}'. Is it installed?"}


def focus_app(app_name: str) -> dict:
    """Bring an already-running app to the foreground."""
    resolved = _resolve_cc_app_name(app_name)
    if resolved != app_name:
        log.info("📌 Resolved app name '%s' → '%s'", app_name, resolved)
    app_name = resolved
    log.info("🎯 Focusing: %s", app_name)
    try:
        run_applescript(f'tell application "{app_name}" to activate', timeout=5)
        return {"success": True, "action": "focus_app", "message": f"Focused {app_name}"}
    except AppleScriptError as e:
        return {"success": False, "action": "focus_app", "error": str(e),
                "message": f"Could not focus {app_name}"}


def get_frontmost_app() -> str:
    """Return the name of the currently focused app."""
    try:
        return run_applescript(
            'tell application "System Events" to return name of first process whose frontmost is true',
            timeout=5,
        ) or "Unknown"
    except Exception:
        return "Unknown"
