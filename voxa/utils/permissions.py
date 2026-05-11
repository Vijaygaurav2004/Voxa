"""
macOS Permission checker for Voxa.
Validates that all required system permissions are granted.
"""
from __future__ import annotations

import subprocess
import os
from voxa.utils.logger import get_logger

log = get_logger("permissions")


def check_accessibility_permission() -> bool:
    """
    Check if the current process has Accessibility permission.
    Uses a quick AppleScript test that requires Accessibility access.
    """
    try:
        result = subprocess.run(
            ["/usr/bin/osascript", "-e",
             'tell application "System Events" to get name of first process'],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, Exception):
        return False


def check_microphone_permission() -> bool:
    """
    Check if microphone access is available.
    Attempts to briefly query audio devices.
    """
    try:
        import sounddevice as sd
        devices = sd.query_devices()
        # Check if any input device exists
        input_devices = [d for d in devices if d["max_input_channels"] > 0]
        return len(input_devices) > 0
    except Exception as e:
        log.warning("Microphone check failed: %s", e)
        return False


def open_accessibility_settings():
    """Open System Settings to the Accessibility privacy pane."""
    subprocess.run([
        "open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
    ])


def open_microphone_settings():
    """Open System Settings to the Microphone privacy pane."""
    subprocess.run([
        "open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone"
    ])


def check_all_permissions() -> dict[str, bool]:
    """
    Check all required permissions and return status.

    Returns:
        Dict mapping permission name to granted status.
    """
    results = {
        "microphone": check_microphone_permission(),
        "accessibility": check_accessibility_permission(),
    }

    for perm, granted in results.items():
        status = "✅ Granted" if granted else "❌ Not Granted"
        log.info("Permission [%s]: %s", perm, status)

    return results


def ensure_permissions() -> bool:
    """
    Check all permissions and print guidance for any missing ones.
    Returns True if all permissions are granted.
    """
    perms = check_all_permissions()
    all_granted = all(perms.values())

    if not all_granted:
        print("\n" + "=" * 60)
        print("⚠️  VOXA REQUIRES ADDITIONAL PERMISSIONS")
        print("=" * 60)

        if not perms["microphone"]:
            print("""
🎤 MICROPHONE ACCESS:
   Go to: System Settings → Privacy & Security → Microphone
   Enable access for your Terminal application.
""")
            open_microphone_settings()

        if not perms["accessibility"]:
            print("""
♿ ACCESSIBILITY ACCESS:
   Go to: System Settings → Privacy & Security → Accessibility
   Add and enable your Terminal application.
   (This is needed to control other apps via AppleScript.)
""")
            open_accessibility_settings()

        print("=" * 60)
        print("After granting permissions, restart Voxa.")
        print("=" * 60 + "\n")

    return all_granted
