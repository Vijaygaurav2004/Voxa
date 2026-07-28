"""
Google API Client for Voxa Integrations.
Calendar event creation and Gmail send/unread via the REST APIs (requests only).
Tokens come from the token store; every function returns a uniform
{success, action, message, ...} dict with a TTS-friendly message.
"""
from __future__ import annotations

import base64
import time
from datetime import datetime
from typing import Optional

import requests

from voxa.utils.logger import get_logger

log = get_logger("integrations.google")

_CALENDAR_EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
_GMAIL_BASE_URL = "https://gmail.googleapis.com/gmail/v1/users/me"


def get_userinfo(token: str) -> dict:
    """Fetch the Google account profile for an access token."""
    resp = requests.get(
        "https://openidconnect.googleapis.com/v1/userinfo",
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    return resp.json() if resp.status_code == 200 else {}


def _service_token(service: str, service_name: str) -> tuple[Optional[str], Optional[dict]]:
    """
    Return (access_token, None) when the service is connected, else
    (None, not-connected result dict).
    """
    from voxa.integrations.token_store import token_store
    from voxa.integrations.oauth import _google_service_connected

    record = token_store.get("google")
    if not _google_service_connected(record, service):
        return None, {
            "success": False,
            "not_connected": True,
            "message": f"{service_name} isn't connected — open Voxa Settings → Accounts to connect it.",
        }
    token = token_store.get_google_access_token()
    if not token:
        return None, {
            "success": False,
            "not_connected": True,
            "message": f"{service_name} isn't connected — open Voxa Settings → Accounts to connect it.",
        }
    return token, None


def _ensure_offset(iso: str) -> str:
    """Append the local UTC offset to a naive ISO 8601 datetime string."""
    if not iso:
        return iso
    tail = iso.split("T")[-1]
    if iso.endswith("Z") or "+" in tail or "-" in tail:
        return iso
    offset = datetime.now().astimezone().strftime("%z")  # e.g. "+0530"
    return f"{iso}{offset[:3]}:{offset[3:]}"


# ─── Calendar ────────────────────────────────────────────────────────────────────

def create_calendar_event(
    title: str,
    start_iso: str,
    end_iso: str,
    description: str = "",
    location: str = "",
    attendees: Optional[list[str]] = None,
) -> dict:
    """Create an event on the user's primary Google Calendar."""
    token, err = _service_token("google_calendar", "Google Calendar")
    if err:
        err["action"] = "calendar_create_event"
        return err

    body = {
        "summary": title,
        "start": {"dateTime": _ensure_offset(start_iso)},
        "end": {"dateTime": _ensure_offset(end_iso)},
    }
    if description:
        body["description"] = description
    if location:
        body["location"] = location
    if attendees:
        body["attendees"] = [{"email": a} for a in attendees]

    try:
        resp = requests.post(
            _CALENDAR_EVENTS_URL,
            headers={"Authorization": f"Bearer {token}"},
            json=body,
            timeout=20,
        )
        if resp.status_code >= 400:
            log.error("Calendar event create failed (%d): %s", resp.status_code, resp.text[:200])
            return {"success": False, "action": "calendar_create_event",
                    "message": "Couldn't add the event to Google Calendar."}
        data = resp.json()
        log.info("📅 Created calendar event: %s", title)
        return {
            "success": True,
            "action": "calendar_create_event",
            "message": f"Added '{title}' to your Google Calendar.",
            "event_link": data.get("htmlLink"),
        }
    except Exception as e:
        log.error("Calendar event create error: %s", e)
        return {"success": False, "action": "calendar_create_event",
                "message": f"Couldn't add the event: {e}"}


def list_upcoming_events(max_results: int = 10) -> dict:
    """List the next upcoming events on the primary calendar."""
    token, err = _service_token("google_calendar", "Google Calendar")
    if err:
        err["action"] = "calendar_upcoming"
        return err

    try:
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        resp = requests.get(
            _CALENDAR_EVENTS_URL,
            headers={"Authorization": f"Bearer {token}"},
            params={
                "timeMin": now_iso,
                "singleEvents": "true",
                "orderBy": "startTime",
                "maxResults": max_results,
            },
            timeout=20,
        )
        if resp.status_code >= 400:
            return {"success": False, "action": "calendar_upcoming",
                    "message": "Couldn't fetch your Google Calendar events."}
        items = resp.json().get("items", [])
        if not items:
            return {"success": True, "action": "calendar_upcoming",
                    "message": "You have no upcoming events.", "events": []}
        lines = []
        for ev in items:
            start = ev.get("start", {}).get("dateTime") or ev.get("start", {}).get("date") or ""
            lines.append(f"{ev.get('summary', 'Untitled')} at {start}")
        return {
            "success": True,
            "action": "calendar_upcoming",
            "message": f"You have {len(items)} upcoming event(s): " + "; ".join(lines),
            "events": items,
        }
    except Exception as e:
        log.error("Calendar list error: %s", e)
        return {"success": False, "action": "calendar_upcoming",
                "message": f"Couldn't fetch calendar events: {e}"}


# ─── Gmail ───────────────────────────────────────────────────────────────────────

def send_gmail(to: str, subject: str, body: str) -> dict:
    """Send an email through the user's Gmail account."""
    token, err = _service_token("gmail", "Gmail")
    if err:
        err["action"] = "gmail_send"
        return err

    try:
        mime = f"To: {to}\r\nSubject: {subject}\r\n\r\n{body}"
        raw = base64.urlsafe_b64encode(mime.encode("utf-8")).decode("ascii")
        resp = requests.post(
            f"{_GMAIL_BASE_URL}/messages/send",
            headers={"Authorization": f"Bearer {token}"},
            json={"raw": raw},
            timeout=20,
        )
        if resp.status_code >= 400:
            log.error("Gmail send failed (%d): %s", resp.status_code, resp.text[:200])
            return {"success": False, "action": "gmail_send",
                    "message": "Couldn't send the email through Gmail."}
        log.info("📤 Gmail sent to %s", to)
        return {"success": True, "action": "gmail_send",
                "message": f"Email sent to {to}."}
    except Exception as e:
        log.error("Gmail send error: %s", e)
        return {"success": False, "action": "gmail_send",
                "message": f"Couldn't send the email: {e}"}


def get_unread_summary(max_results: int = 5) -> dict:
    """Summarize unread inbox emails (sender + subject for the newest few)."""
    token, err = _service_token("gmail", "Gmail")
    if err:
        err["action"] = "gmail_unread"
        return err

    try:
        headers = {"Authorization": f"Bearer {token}"}
        resp = requests.get(
            f"{_GMAIL_BASE_URL}/messages",
            headers=headers,
            params={"q": "is:unread in:inbox", "maxResults": max_results},
            timeout=20,
        )
        if resp.status_code >= 400:
            return {"success": False, "action": "gmail_unread",
                    "message": "Couldn't check your Gmail inbox."}
        data = resp.json()
        messages = data.get("messages", [])
        total = data.get("resultSizeEstimate", len(messages))
        if not messages:
            return {"success": True, "action": "gmail_unread",
                    "message": "No unread emails — your inbox is clear."}

        lines = []
        for m in messages:
            msg_resp = requests.get(
                f"{_GMAIL_BASE_URL}/messages/{m['id']}",
                headers=headers,
                params={"format": "metadata", "metadataHeaders": ["From", "Subject"]},
                timeout=20,
            )
            if msg_resp.status_code >= 400:
                continue
            msg_headers = {
                h.get("name"): h.get("value", "")
                for h in msg_resp.json().get("payload", {}).get("headers", [])
            }
            sender = msg_headers.get("From", "Unknown sender").split("<")[0].strip().strip('"')
            lines.append(f"{sender}: {msg_headers.get('Subject', '(no subject)')}")

        summary = f"You have {total} unread email(s). " + "; ".join(lines)
        return {"success": True, "action": "gmail_unread", "message": summary, "count": total}
    except Exception as e:
        log.error("Gmail unread error: %s", e)
        return {"success": False, "action": "gmail_unread",
                "message": f"Couldn't check your inbox: {e}"}
