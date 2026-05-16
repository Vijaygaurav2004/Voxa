"""
WhatsApp Messaging Module for Voxa.

Sends WhatsApp messages hands-free by:
  1. WhatsApp Desktop app (primary — fastest, most reliable)
  2. WhatsApp Web in Chrome (fallback — always available)

Usage:
    send_whatsapp_message("John", "Hey, are you free tonight?")
"""
from __future__ import annotations

import time
import urllib.parse
from typing import Optional

from voxa.utils.applescript import run_applescript, AppleScriptError
from voxa.utils.logger import get_logger

log = get_logger("whatsapp")

# WhatsApp Desktop process names to try
_WA_APP_NAMES = ["WhatsApp", "WhatsApp Messenger"]
BROWSER = "Google Chrome"


# ── Public API ────────────────────────────────────────────────────────────────

def send_whatsapp_message(contact: str, message: str) -> dict:
    """
    Send a WhatsApp message to a named contact.

    Tries:
      1. WhatsApp Desktop app via Accessibility API
      2. WhatsApp Web in Chrome
    """
    log.info("💬 WhatsApp → %s: %s", contact, message[:50])

    # Escape for AppleScript
    safe_contact = contact.replace('"', '\\"').replace("'", "\\'")
    safe_message = message.replace('"', '\\"').replace("'", "\\'")

    # ── Strategy 1: WhatsApp Desktop ─────────────────────────────────────────
    result = _send_via_desktop(safe_contact, safe_message, contact, message)
    if result.get("success"):
        return result

    log.info("Desktop failed — trying WhatsApp Web...")

    # ── Strategy 2: WhatsApp Web ──────────────────────────────────────────────
    return _send_via_web(contact, message)


# ── Desktop implementation ────────────────────────────────────────────────────

def _send_via_desktop(safe_contact: str, safe_message: str,
                      contact: str, message: str) -> dict:
    """Control WhatsApp Desktop app via System Events."""

    # Find which WhatsApp app name works
    app_name = _find_whatsapp_app()
    if not app_name:
        return {"success": False, "message": "WhatsApp Desktop not found"}

    log.info("Found WhatsApp Desktop: %s", app_name)

    script = f'''
        tell application "{app_name}" to activate
        delay 1.5

        tell application "System Events"
            tell process "{app_name}"

                -- Open new chat / search (Cmd+N or Cmd+F)
                keystroke "n" using command down
                delay 1.0

                -- Type contact name in search box
                keystroke "{safe_contact}"
                delay 1.2

                -- Press Down to select first result, then Enter
                key code 125
                delay 0.4
                key code 36
                delay 1.0

                -- Type message
                keystroke "{safe_message}"
                delay 0.3

                -- Send with Enter
                key code 36
                delay 0.5

            end tell
        end tell
        return "sent"
    '''

    try:
        result = run_applescript(script, timeout=20)
        if result and "sent" in result:
            return {
                "success": True, "action": "send_whatsapp",
                "message": f"WhatsApp message sent to {contact}",
            }
        return {"success": False, "message": f"Desktop script returned: {result}"}
    except AppleScriptError as e:
        log.warning("WhatsApp Desktop error: %s", e)
        return {"success": False, "message": str(e)}


def _find_whatsapp_app() -> Optional[str]:
    """Return the WhatsApp app name if it's installed/running."""
    for name in _WA_APP_NAMES:
        try:
            run_applescript(f'tell application "{name}" to get name', timeout=4)
            return name
        except AppleScriptError:
            # Try open -a to launch it
            import subprocess
            r = subprocess.run(["open", "-a", name],
                               capture_output=True, timeout=5)
            if r.returncode == 0:
                time.sleep(2.0)
                return name
    return None


# ── WhatsApp Web fallback ─────────────────────────────────────────────────────

def _send_via_web(contact: str, message: str) -> dict:
    """
    Send via WhatsApp Web in Chrome.

    Opens https://web.whatsapp.com, searches for contact,
    clicks the chat, types the message, and sends.
    """
    from voxa.actions.browser import _open_tab, _run_js, get_current_url

    encoded_msg = urllib.parse.quote(message)

    # Open WhatsApp Web
    if not _open_tab("https://web.whatsapp.com"):
        return {"success": False, "action": "send_whatsapp",
                "message": "Could not open WhatsApp Web"}

    log.info("⏳ Waiting for WhatsApp Web to load...")
    time.sleep(5)  # WhatsApp Web needs time

    # Try JS to find and click the contact search box, search, click chat
    js_search = f"""(function(){{
        // Click search box
        var searchBox = document.querySelector(
            '[data-testid="chat-list-search"],' +
            '[title="Search input textbox"],' +
            'div[contenteditable][data-tab="3"]'
        );
        if (!searchBox) return 'no-search-box';
        searchBox.click();
        return 'clicked-search';
    }})();"""

    result = _run_js(js_search)
    log.info("WhatsApp Web search box: %s", result)

    if result == "clicked-search":
        # Type contact name via keyboard
        _wa_web_type_and_send(contact, message)
        time.sleep(1.5)
        return {
            "success": True, "action": "send_whatsapp",
            "message": f"WhatsApp Web: message sent to {contact}",
        }

    # JS unavailable — use pure keyboard navigation
    return _wa_web_keyboard(contact, message)


def _wa_web_type_and_send(contact: str, message: str):
    """After clicking search box, type contact, select, type message, send."""
    safe_contact = contact.replace('"', '\\"')
    safe_message = message.replace('"', '\\"')

    script = f'''
        tell application "{BROWSER}" to activate
        delay 0.5
        tell application "System Events"
            tell process "{BROWSER}"
                -- Type contact name
                keystroke "{safe_contact}"
                delay 1.5

                -- Press Down to highlight first result, Enter to open
                key code 125
                delay 0.4
                key code 36
                delay 1.0

                -- Type message
                keystroke "{safe_message}"
                delay 0.3

                -- Press Enter to send
                key code 36
            end tell
        end tell
    '''
    try:
        run_applescript(script, timeout=15)
    except AppleScriptError as e:
        log.warning("WhatsApp Web keyboard type failed: %s", e)


def _wa_web_keyboard(contact: str, message: str) -> dict:
    """Pure keyboard navigation fallback for WhatsApp Web."""
    safe_contact = contact.replace('"', '\\"')
    safe_message = message.replace('"', '\\"')

    script = f'''
        tell application "{BROWSER}" to activate
        delay 0.5
        tell application "System Events"
            tell process "{BROWSER}"
                -- Tab to search box (usually ~3 tabs from page load)
                key code 48  -- Tab
                delay 0.2
                key code 48
                delay 0.2
                key code 48
                delay 0.5

                -- Type contact
                keystroke "{safe_contact}"
                delay 1.5

                -- Down arrow to first result
                key code 125
                delay 0.4

                -- Enter to open chat
                key code 36
                delay 1.0

                -- Type message
                keystroke "{safe_message}"
                delay 0.3

                -- Enter to send
                key code 36
            end tell
        end tell
    '''
    try:
        run_applescript(script, timeout=15)
        return {
            "success": True, "action": "send_whatsapp",
            "message": f"WhatsApp Web: sent to {contact} (keyboard mode)",
        }
    except AppleScriptError as e:
        return {
            "success": False, "action": "send_whatsapp",
            "error": str(e),
            "message": f"Could not send WhatsApp to {contact}: {e}",
        }
