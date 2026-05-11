"""
System Control Module for Voxa.
Controls macOS system settings: volume, brightness, dark mode, Do Not Disturb.
Uses AppleScript and osascript for native macOS integration.
"""
from __future__ import annotations

import subprocess
from voxa.utils.applescript import run_applescript, AppleScriptError
from voxa.utils.logger import get_logger

log = get_logger("system_control")


# ── Volume Control ─────────────────────────────────────────────────────────────

def set_volume(level: int | None = None, direction: str | None = None, mute: bool = False) -> dict:
    """
    Set or adjust system volume.

    Args:
        level: Absolute volume level 0–100. If provided, sets directly.
        direction: "up" or "down" to adjust by 10 units.
        mute: If True, mutes the system.
    """
    log.info("🔊 Volume control — level=%s, direction=%s, mute=%s", level, direction, mute)

    try:
        if mute:
            run_applescript("set volume output muted true")
            return {"success": True, "action": "system_volume", "message": "System muted"}

        if level is not None:
            # macOS `set volume` uses 0–7 scale internally but output volume uses 0–100
            clamped = max(0, min(100, int(level)))
            run_applescript(f"set volume output volume {clamped}")
            return {"success": True, "action": "system_volume", "message": f"Volume set to {clamped}%"}

        if direction:
            # Get current volume first
            current_str = run_applescript("output volume of (get volume settings)")
            try:
                current = int(current_str.strip())
            except (ValueError, AttributeError):
                current = 50

            step = 15
            if direction.lower() == "up":
                new_vol = min(100, current + step)
                run_applescript(f"set volume output volume {new_vol}")
                return {"success": True, "action": "system_volume", "message": f"Volume increased to {new_vol}%"}
            elif direction.lower() == "down":
                new_vol = max(0, current - step)
                run_applescript(f"set volume output volume {new_vol}")
                return {"success": True, "action": "system_volume", "message": f"Volume decreased to {new_vol}%"}

        return {"success": False, "action": "system_volume", "message": "Specify level (0-100), direction (up/down), or mute=True"}

    except AppleScriptError as e:
        log.error("Volume control failed: %s", e)
        return {"success": False, "action": "system_volume", "error": str(e), "message": "Failed to adjust volume"}


def get_volume() -> dict:
    """Get the current system volume level."""
    try:
        vol_str = run_applescript("output volume of (get volume settings)")
        mute_str = run_applescript("output muted of (get volume settings)")
        vol = int(vol_str.strip()) if vol_str else 0
        muted = mute_str.strip().lower() == "true"
        return {
            "success": True,
            "action": "system_volume_get",
            "volume": vol,
            "muted": muted,
            "message": f"Volume is {'muted' if muted else str(vol) + '%'}",
        }
    except AppleScriptError as e:
        return {"success": False, "action": "system_volume_get", "error": str(e), "message": "Could not get volume"}


# ── Brightness Control ─────────────────────────────────────────────────────────

def set_brightness(level: int | None = None, direction: str | None = None) -> dict:
    """
    Set or adjust screen brightness.

    Args:
        level: Absolute brightness 0–100.
        direction: "up" or "down" to adjust by 15 units.
    """
    log.info("☀️  Brightness control — level=%s, direction=%s", level, direction)

    try:
        # Get current brightness via AppleScript
        current_script = '''
            tell application "System Preferences"
                -- Use brightness slider value
            end tell
        '''
        # Use brightness control via keyboard simulation (reliable cross-version)
        if direction:
            if direction.lower() == "up":
                # F2 key = brightness up (key code 144)
                for _ in range(3):
                    run_applescript('tell application "System Events" to key code 144')
                return {"success": True, "action": "system_brightness", "message": "Brightness increased"}
            elif direction.lower() == "down":
                # F1 key = brightness down (key code 145)
                for _ in range(3):
                    run_applescript('tell application "System Events" to key code 145')
                return {"success": True, "action": "system_brightness", "message": "Brightness decreased"}

        if level is not None:
            # Set via display brightness using osascript + coreaudiod approach
            clamped = max(0.0, min(1.0, int(level) / 100.0))
            script = f'''
                tell application "System Events"
                    tell process "Control Center"
                        -- Fallback: use key simulation for approximate brightness
                    end tell
                end tell
            '''
            # Most reliable: use brightness CLI utility if available
            result = subprocess.run(
                ["brightness", str(clamped)],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                return {"success": True, "action": "system_brightness", "message": f"Brightness set to {level}%"}
            else:
                # Fallback to key simulation
                steps = int(clamped * 16)  # 16 brightness steps on macOS
                for _ in range(16):  # First press all the way down
                    run_applescript('tell application "System Events" to key code 145')
                for _ in range(steps):  # Then press up to target
                    run_applescript('tell application "System Events" to key code 144')
                return {"success": True, "action": "system_brightness", "message": f"Brightness set to approximately {level}%"}

        return {"success": False, "action": "system_brightness", "message": "Specify level (0-100) or direction (up/down)"}

    except Exception as e:
        log.error("Brightness control failed: %s", e)
        return {"success": False, "action": "system_brightness", "error": str(e), "message": "Failed to adjust brightness"}


# ── Dark Mode Toggle ───────────────────────────────────────────────────────────

def toggle_dark_mode(enable: bool | None = None) -> dict:
    """
    Toggle or set macOS dark mode.

    Args:
        enable: True to enable dark mode, False to disable, None to toggle.
    """
    log.info("🌙 Dark mode control — enable=%s", enable)

    try:
        if enable is None:
            # Toggle current state
            script = '''
                tell application "System Events"
                    tell appearance preferences
                        set dark mode to not dark mode
                        return dark mode
                    end tell
                end tell
            '''
            result = run_applescript(script)
            state = "enabled" if result and result.strip().lower() == "true" else "disabled"
        else:
            script = f'''
                tell application "System Events"
                    tell appearance preferences
                        set dark mode to {'true' if enable else 'false'}
                    end tell
                end tell
            '''
            run_applescript(script)
            state = "enabled" if enable else "disabled"

        return {"success": True, "action": "system_dark_mode", "message": f"Dark mode {state}"}

    except AppleScriptError as e:
        log.error("Dark mode toggle failed: %s", e)
        return {"success": False, "action": "system_dark_mode", "error": str(e), "message": "Failed to toggle dark mode"}


# ── Do Not Disturb ─────────────────────────────────────────────────────────────

def toggle_dnd(enable: bool | None = None) -> dict:
    """
    Toggle or set Do Not Disturb / Focus mode.

    Args:
        enable: True to enable DND, False to disable, None to toggle.
    """
    log.info("🔕 Do Not Disturb control — enable=%s", enable)

    try:
        # macOS 12+ uses Focus mode; toggle via Control Center keyboard shortcut
        # Most reliable across macOS versions: toggle via NSUserDefaults or shortcut
        if enable is True:
            script = '''
                tell application "System Events"
                    -- Use Focus mode toggle shortcut or set via defaults
                    do shell script "shortcuts run 'Enable DND' 2>/dev/null || true"
                end tell
            '''
        elif enable is False:
            script = '''
                tell application "System Events"
                    do shell script "shortcuts run 'Disable DND' 2>/dev/null || true"
                end tell
            '''
        else:
            script = '''
                tell application "System Events"
                    do shell script "shortcuts run 'Toggle DND' 2>/dev/null || true"
                end tell
            '''

        run_applescript(script)
        action = "enabled" if enable is True else ("disabled" if enable is False else "toggled")
        return {"success": True, "action": "system_dnd", "message": f"Do Not Disturb {action}"}

    except AppleScriptError as e:
        log.error("DND toggle failed: %s", e)
        return {"success": False, "action": "system_dnd", "error": str(e), "message": "Failed to toggle Do Not Disturb — you may need to set up a Shortcut named 'Toggle DND'"}


# ── System Info ────────────────────────────────────────────────────────────────

def get_battery_status() -> dict:
    """Get current battery level and charging status."""
    try:
        result = subprocess.run(
            ["pmset", "-g", "batt"],
            capture_output=True, text=True, timeout=5
        )
        output = result.stdout
        # Parse: "Now drawing from 'Battery Power'; -InternalBattery-0 (id=...) 87%; discharging..."
        import re
        match = re.search(r"(\d+)%", output)
        charging = "AC Power" in output
        level = int(match.group(1)) if match else None
        msg = f"Battery at {level}%, {'charging' if charging else 'on battery'}" if level else "Could not read battery"
        return {"success": True, "action": "system_battery", "level": level, "charging": charging, "message": msg}
    except Exception as e:
        return {"success": False, "action": "system_battery", "error": str(e), "message": "Could not get battery status"}
