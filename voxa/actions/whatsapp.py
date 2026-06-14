"""
WhatsApp Messaging Module for Voxa.

Capabilities:
  1. Send a new WhatsApp message to any contact by name
  2. Reply to the last (most recent) message in an open chat
  3. Detects contact-not-found and speaks an appropriate error

Strategies (in order):
  1. WhatsApp Desktop app via AppleScript + System Events  (fastest, most reliable)
  2. WhatsApp Web via contact-name search in Chrome        (universal fallback)

Spoken feedback is always returned in `message` so the dispatcher voices it.
"""
from __future__ import annotations

import subprocess
import time
from typing import Optional

from voxa.utils.applescript import run_applescript, AppleScriptError
from voxa.utils.logger import get_logger

log = get_logger("whatsapp")

# WhatsApp Desktop process names (preference order)
_WA_APP_NAMES = ["WhatsApp", "WhatsApp Messenger"]
BROWSER = "Google Chrome"


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def send_whatsapp_message(contact: str, message: str) -> dict:
    """
    Send a WhatsApp message to a named contact.

    Returns a result dict whose `message` field is always a human-friendly
    sentence so the TTS layer can speak it directly.
    """
    log.info("💬 WhatsApp → %s: %s", contact, message[:60])

    result = _send_via_desktop(contact, message)
    if result.get("success"):
        return result

    log.info("Desktop failed (%s) — trying WhatsApp Web...", result.get("message", "?"))
    return _send_via_web(contact, message)


def reply_whatsapp_message(message: str, contact: Optional[str] = None) -> dict:
    """
    Reply to the last message in the currently open WhatsApp chat.

    If `contact` is given, switch to that chat first.
    """
    log.info("↩️  WhatsApp reply → %s: %s", contact or "active chat", message[:60])

    app_name = _find_whatsapp_app()
    if app_name:
        return _reply_via_desktop(app_name, contact, message)

    return _reply_via_web(contact, message)


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _esc(s: str) -> str:
    """Escape a string for safe embedding in AppleScript quoted strings."""
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("'", "\\'")


def _find_whatsapp_app() -> Optional[str]:
    """Return the running/installed WhatsApp app name, launching it if needed."""
    for name in _WA_APP_NAMES:
        try:
            run_applescript(f'tell application "{name}" to get name', timeout=4)
            return name
        except AppleScriptError:
            r = subprocess.run(["open", "-a", name],
                               capture_output=True, timeout=5)
            if r.returncode == 0:
                time.sleep(2.5)
                return name
    return None


def _get_window_title(app_name: str) -> str:
    """Return the frontmost window title of the given app, or ''."""
    try:
        title = run_applescript(
            f'tell application "System Events" to tell process "{app_name}" '
            f'to return name of window 1',
            timeout=5,
        )
        return title or ""
    except Exception:
        return ""


def _send_via_desktop(contact: str, message: str) -> dict:
    """
    Send via WhatsApp Desktop.

    After searching for the contact, we verify the window title changed
    to include the contact's name — if not, we report 'contact not found'.
    """
    app_name = _find_whatsapp_app()
    if not app_name:
        return {
            "success": False,
            "action": "send_whatsapp",
            "message": "WhatsApp is not installed on this Mac.",
        }

    log.info("📱 Using WhatsApp Desktop: %s", app_name)
    safe_contact = _esc(contact)
    safe_message  = _esc(message)

    # ── Step 1: Open search and type the contact name ──────────────────────
    open_search_script = f'''
        tell application "{app_name}" to activate
        delay 1.5
        tell application "System Events"
            tell process "{app_name}"
                keystroke "f" using command down
                delay 0.8
                keystroke "a" using command down
                delay 0.2
                keystroke "{safe_contact}"
                delay 1.8
            end tell
        end tell
    '''
    try:
        run_applescript(open_search_script, timeout=15)
    except AppleScriptError as e:
        return {"success": False, "action": "send_whatsapp",
                "message": f"WhatsApp search failed: {e}"}

    # ── Step 2: Check if there are results (press Down and see if window changes) ──
    # Capture current window title before opening
    title_before = _get_window_title(app_name)

    select_script = f'''
        tell application "System Events"
            tell process "{app_name}"
                key code 125
                delay 0.5
                key code 36
                delay 1.5
            end tell
        end tell
    '''
    try:
        run_applescript(select_script, timeout=10)
    except AppleScriptError as e:
        return {"success": False, "action": "send_whatsapp",
                "message": f"Could not open chat: {e}"}

    # ── Step 3: Verify a chat opened (window title should change) ──────────
    title_after = _get_window_title(app_name)
    log.info("Window title before: %r  after: %r", title_before, title_after)

    # Heuristic: if title_after is empty or same as before AND doesn't contain
    # part of the contact name → contact not found
    contact_lower = contact.strip().lower()
    first_name = contact_lower.split()[0] if contact_lower else contact_lower
    title_after_lower = title_after.lower()

    # WhatsApp Desktop shows contact name in window title when chat is open
    contact_found = (
        title_after_lower != title_before.lower()  # title changed
        or first_name in title_after_lower           # OR name is in title
    )

    if not contact_found:
        # Dismiss the search (Escape) and report
        try:
            run_applescript(
                f'tell application "System Events" to tell process "{app_name}" to key code 53',
                timeout=5,
            )
        except Exception:
            pass
        return {
            "success": False,
            "action": "send_whatsapp",
            "fatal": True,
            "message": (
                f"I couldn't find {contact} on WhatsApp. "
                f"Please check if the name is correct or if they're in your contacts."
            ),
        }

    # ── Step 4: Type and send the message ──────────────────────────────────
    send_script = f'''
        tell application "System Events"
            tell process "{app_name}"
                keystroke "{safe_message}"
                delay 0.4
                key code 36
                delay 0.5
            end tell
        end tell
        return "sent"
    '''
    try:
        res = run_applescript(send_script, timeout=15)
        if res and "sent" in res:
            return {
                "success": True,
                "action": "send_whatsapp",
                "message": f"WhatsApp message sent to {contact}.",
            }
        return {"success": False, "action": "send_whatsapp",
                "message": f"Message may not have sent. Result: {res}"}
    except AppleScriptError as e:
        return {"success": False, "action": "send_whatsapp",
                "message": f"Could not send message: {e}"}


def _reply_via_desktop(app_name: str, contact: Optional[str], message: str) -> dict:
    """Reply in WhatsApp Desktop — switch to contact's chat first if given."""
    safe_message = _esc(message)

    if contact:
        # Switch to that contact's chat first, reusing send logic (no send step)
        safe_contact = _esc(contact)
        switch = f'''
            tell application "{app_name}" to activate
            delay 1.0
            tell application "System Events"
                tell process "{app_name}"
                    keystroke "f" using command down
                    delay 0.8
                    keystroke "a" using command down
                    delay 0.2
                    keystroke "{safe_contact}"
                    delay 1.8
                    key code 125
                    delay 0.5
                    key code 36
                    delay 1.5
                end tell
            end tell
        '''
        # Check window title to verify contact found
        title_before = _get_window_title(app_name)
        try:
            run_applescript(switch, timeout=20)
        except AppleScriptError as e:
            return {"success": False, "action": "reply_whatsapp",
                    "message": f"Could not switch to {contact}'s chat: {e}"}

        title_after  = _get_window_title(app_name)
        first_name = contact.strip().lower().split()[0]
        if title_after.lower() == title_before.lower() and first_name not in title_after.lower():
            return {
                "success": False,
                "action": "reply_whatsapp",
                "fatal": True,
                "message": (
                    f"I couldn't find {contact} on WhatsApp. "
                    f"Make sure the name matches your contact list."
                ),
            }

    script = f'''
        tell application "{app_name}" to activate
        delay 0.5
        tell application "System Events"
            tell process "{app_name}"
                key code 48
                delay 0.3
                keystroke "{safe_message}"
                delay 0.3
                key code 36
                delay 0.5
            end tell
        end tell
        return "replied"
    '''
    try:
        res = run_applescript(script, timeout=20)
        if res and "replied" in res:
            return {
                "success": True,
                "action": "reply_whatsapp",
                "message": "WhatsApp reply sent" + (f" to {contact}." if contact else " in the active chat."),
            }
        return {"success": False, "action": "reply_whatsapp",
                "message": f"Reply may not have been sent. Got: {res}"}
    except AppleScriptError as e:
        return {"success": False, "action": "reply_whatsapp",
                "message": f"Reply failed: {e}"}


# ─────────────────────────────────────────────────────────────────────────────
# WhatsApp Web fallback
# ─────────────────────────────────────────────────────────────────────────────

def _open_whatsapp_web() -> bool:
    """Open WhatsApp Web in Chrome and wait for it to load."""
    try:
        run_applescript(
            f'tell application "{BROWSER}" to open location "https://web.whatsapp.com"',
            timeout=8,
        )
        time.sleep(5)
        return True
    except Exception as e:
        log.warning("Could not open WhatsApp Web: %s", e)
        return False


def _send_via_web(contact: str, message: str) -> dict:
    """Send via WhatsApp Web — searches for the contact by name."""
    if not _open_whatsapp_web():
        return {"success": False, "action": "send_whatsapp",
                "message": "Could not open WhatsApp Web. Please make sure Chrome is available."}

    safe_contact = _esc(contact)
    safe_message  = _esc(message)

    script = f'''
        tell application "{BROWSER}" to activate
        delay 0.5
        tell application "System Events"
            tell process "{BROWSER}"
                key code 48
                delay 0.3
                key code 48
                delay 0.3
                keystroke "{safe_contact}"
                delay 2.0
                key code 125
                delay 0.5
                key code 36
                delay 1.5
                keystroke "{safe_message}"
                delay 0.4
                key code 36
                delay 0.5
            end tell
        end tell
        return "sent"
    '''
    try:
        res = run_applescript(script, timeout=30)
        if res and "sent" in res:
            return {
                "success": True, "action": "send_whatsapp",
                "message": f"WhatsApp message sent to {contact} via WhatsApp Web.",
            }
        return {
            "success": False, "action": "send_whatsapp",
            "message": f"WhatsApp Web: I couldn't find {contact} or the message didn't send. Please try again.",
        }
    except AppleScriptError as e:
        return {
            "success": False, "action": "send_whatsapp",
            "error": str(e),
            "message": f"I couldn't find {contact} on WhatsApp. Please check if the contact name is correct.",
        }


def _reply_via_web(contact: Optional[str], message: str) -> dict:
    """Reply in the currently open WhatsApp Web chat."""
    if contact:
        return _send_via_web(contact, message)

    safe_message = _esc(message)
    script = f'''
        tell application "{BROWSER}" to activate
        delay 0.5
        tell application "System Events"
            tell process "{BROWSER}"
                key code 48
                delay 0.3
                keystroke "{safe_message}"
                delay 0.3
                key code 36
            end tell
        end tell
        return "replied"
    '''
    try:
        res = run_applescript(script, timeout=15)
        if res and "replied" in res:
            return {"success": True, "action": "reply_whatsapp",
                    "message": "WhatsApp reply sent in the active chat."}
        return {"success": False, "action": "reply_whatsapp",
                "message": "Could not send the reply — please make sure a WhatsApp chat is open."}
    except AppleScriptError as e:
        return {"success": False, "action": "reply_whatsapp",
                "message": f"Reply failed: {e}"}
