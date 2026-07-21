"""
Email Quick-Compose Module for Voxa.
Opens a compose window in Apple Mail or Gmail (Chrome) with pre-filled fields.
"""
from __future__ import annotations

import urllib.parse
import subprocess
from voxa.utils.applescript import run_applescript, AppleScriptError
from voxa.utils.logger import get_logger

log = get_logger("email")


def compose_email(
    to: str | None = None,
    subject: str | None = None,
    body: str | None = None,
    use_gmail: bool = False,
) -> dict:
    """
    Open an email compose window with pre-filled fields.

    Args:
        to: Recipient email address or name.
        subject: Email subject line.
        body: Email body text.
        use_gmail: If True, opens Gmail in Chrome instead of Apple Mail.
    """
    to = to or ""
    subject = subject or ""
    body = body or ""

    log.info("✉️  Composing email — to=%s, subject=%s", to, subject[:30])

    if use_gmail:
        return _compose_gmail(to, subject, body)
    else:
        return _compose_apple_mail(to, subject, body)


def _compose_apple_mail(to: str, subject: str, body: str) -> dict:
    """Open Apple Mail compose window via AppleScript."""
    try:
        # Escape for AppleScript strings
        safe_to = to.replace('"', '\\"')
        safe_subject = subject.replace('"', '\\"')
        safe_body = body.replace('"', '\\"').replace('\n', '\\n')

        script = f'''
            tell application "Mail"
                activate
                set newMessage to make new outgoing message with properties {{subject:"{safe_subject}", content:"{safe_body}"}}
                tell newMessage
                    make new to recipient with properties {{address:"{safe_to}"}}
                    set visible to true
                end tell
            end tell
        '''
        run_applescript(script)

        recipient_str = f" to {to}" if to else ""
        return {
            "success": True,
            "action": "email_compose",
            "to": to,
            "subject": subject,
            "message": f"Opened email compose{recipient_str}",
        }
    except AppleScriptError as e:
        log.error("Apple Mail compose failed: %s", e)
        # Fall back to Gmail
        return _compose_gmail(to, subject, body)


def _compose_gmail(to: str, subject: str, body: str) -> dict:
    """Open Gmail compose window via mailto: URL in Chrome."""
    try:
        params = {}
        if subject:
            params["subject"] = subject
        if body:
            params["body"] = body

        query = urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
        mailto = f"mailto:{urllib.parse.quote(to)}?{query}" if params else f"mailto:{urllib.parse.quote(to)}"

        subprocess.run(["open", mailto], check=True, timeout=10)

        recipient_str = f" to {to}" if to else ""
        return {
            "success": True,
            "action": "email_compose",
            "to": to,
            "subject": subject,
            "message": f"Opened email compose{recipient_str}",
        }
    except Exception as e:
        log.error("Gmail compose failed: %s", e)
        return {
            "success": False,
            "action": "email_compose",
            "error": str(e),
            "message": "Could not open email compose window",
        }


def open_compose_window() -> dict:
    """Open a blank email compose window."""
    return compose_email()
