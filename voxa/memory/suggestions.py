"""
Proactive Suggestion Manager — "Add to your calendar?" prompts.

While Voxa is listening to a conversation/meeting, each transcribed chunk is
handed to :meth:`SuggestionManager.analyze_chunk`. When a concrete scheduling
agreement is detected ("let's meet Friday at 3"), a small non-intrusive
suggestion is pushed to the app over the WebSocket bridge. The user can Add it
(routes through the standard dispatcher — connected Google Calendar, or a
prefilled calendar.google.com page as a fallback) or dismiss it.

Design mirrors voxa/memory/meeting_manager.py (notifier + result-dict pattern)
and voxa/skills/modes.py (cheap gpt-4o-mini JSON call for the actual extraction).
"""
from __future__ import annotations

import threading
import time
import uuid
from datetime import datetime, timedelta
from typing import Callable, Optional

from voxa.utils.logger import get_logger

log = get_logger(__name__)

# Only bother calling the LLM when a chunk smells like scheduling. Cheap gate
# that keeps ~all ambient chatter from hitting the API.
_SCHEDULE_HINTS = (
    "meet", "meeting", "schedule", "calendar", "appointment", "sync", "catch up",
    "call at", "let's do", "tomorrow", "next week", "o'clock", "noon", "monday",
    "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", " am",
    " pm", "a.m", "p.m",
)

# Pending suggestions older than this (seconds) are dropped — the moment passed.
_SUGGESTION_TTL_SECONDS = 900


class SuggestionManager:
    """Detects calendar-worthy moments in a conversation and offers to add them."""

    def __init__(self):
        # Callback used to push events (meeting_suggestion, …) to the app over WS.
        self._notifier: Optional[Callable[[str, dict], None]] = None
        # id -> pending suggestion record (payload + raw event fields for confirm).
        self._pending: dict[str, dict] = {}
        # Dedup memory: (session_id, title_lower, start_iso) already suggested.
        self._suggested: set[tuple] = set()
        self._lock = threading.Lock()

    # ── Notifier (app prompt channel) ───────────────────────────────────────────

    def set_notifier(self, fn: Callable[[str, dict], None]):
        """Register a callback (event, data) used to notify the app (via WebSocket)."""
        self._notifier = fn

    def _notify(self, event: str, data: dict):
        if self._notifier:
            try:
                self._notifier(event, data)
            except Exception as e:
                log.warning("Suggestion notify failed: %s", e)

    # ── Analysis ────────────────────────────────────────────────────────────────

    def analyze_chunk(self, text: str, source: str = "mic", session_id: str = "") -> Optional[dict]:
        """
        Inspect a transcribed chunk for a concrete scheduling agreement. If one is
        found (and not already suggested this session), push a suggestion to the
        app and return its payload. Otherwise return None.
        """
        self._cleanup_expired()

        if not text:
            return None

        # Cheap keyword pre-gate — skip the LLM unless it smells like scheduling.
        lower = text.lower()
        if not any(hint in lower for hint in _SCHEDULE_HINTS):
            return None

        result = self._extract(text)
        if not result or not result.get("has_event"):
            return None

        start = str(result.get("start") or "").strip()
        if not start:
            return None
        try:
            start_dt = datetime.fromisoformat(start)
        except (ValueError, TypeError):
            return None

        title = str(result.get("title") or "New event").strip() or "New event"
        location = str(result.get("location") or "").strip()

        # Compute end — use the extracted end, else default to start + 1 hour.
        end = str(result.get("end") or "").strip()
        if not end:
            end = (start_dt + timedelta(hours=1)).isoformat(timespec="seconds")

        # Dedup: don't re-offer the same event within a session.
        key = (session_id, title.lower().strip(), start)
        with self._lock:
            if key in self._suggested:
                return None
            self._suggested.add(key)

        suggestion_id = uuid.uuid4().hex[:8]
        payload = {
            "id": suggestion_id,
            "kind": "calendar",
            "title": title,
            "when_text": self._format_when(start),
            "start_iso": start,
            "end_iso": end,
            "location": location,
        }

        with self._lock:
            self._pending[suggestion_id] = {
                **payload,
                "created": time.time(),
                # Raw fields used to build the Action on confirm.
                "start": start,
                "end": end,
                "location": location,
            }

        log.info("📅 Calendar suggestion: '%s' at %s (id=%s)", title, start, suggestion_id)
        self._notify("meeting_suggestion", payload)
        return payload

    def _extract(self, text: str) -> Optional[dict]:
        """
        The ONLY OpenAI touchpoint (patched directly in tests). Uses the small/fast
        model to decide whether the snippet contains a concrete scheduling
        agreement with a determinable date+time, and if so extract its fields.

        Returns the parsed dict, or None on any error / when there's no event.
        """
        try:
            import json
            from openai import OpenAI
            from voxa.config import config

            api_key = config.OPENAI_API_KEY
            if not api_key:
                return None

            system = (
                "You detect concrete scheduling agreements in a conversation snippet. "
                "A concrete agreement means the speakers settled on meeting/doing "
                "something at a determinable date AND time (e.g. 'let's meet Friday "
                "at 3', 'call me tomorrow at noon'). Vague intentions ('we should "
                "catch up sometime', 'maybe next week') are NOT events.\n\n"
                "Respond with JSON only:\n"
                '{"has_event": true/false, "title": "short event title", '
                '"start": "YYYY-MM-DDTHH:MM:SS", "end": "YYYY-MM-DDTHH:MM:SS", '
                '"location": "location or empty string"}\n\n'
                "Rules:\n"
                "- has_event MUST be false unless a specific time is present or "
                "clearly inferable from the snippet.\n"
                "- Resolve relative dates/times against the provided current "
                "date/time. Output start/end as local ISO 8601 (no timezone).\n"
                "- If no end time is stated, infer end = start + 1 hour.\n"
                "- Keep the title short and human (e.g. 'Sync with Sam')."
            )
            user = (
                f"Current date/time: {datetime.now().strftime('%A, %Y-%m-%dT%H:%M:%S')}. "
                f"Conversation snippet: {text}"
            )

            client = OpenAI(api_key=api_key)
            response = client.chat.completions.create(
                model=config.LLM_MODEL_FAST,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0.0,
                response_format={"type": "json_object"},
                max_tokens=200,
            )
            content = response.choices[0].message.content or ""
            data = json.loads(content)
            if not isinstance(data, dict) or not data.get("has_event"):
                return None
            return data
        except Exception as e:
            log.debug("Suggestion extraction failed: %s", e)
            return None

    def _format_when(self, start_iso: str) -> str:
        """Format an ISO start into a human 'Fri, Jul 24 · 3:00 PM'. Raw on failure."""
        try:
            dt = datetime.fromisoformat(start_iso)
            return dt.strftime("%a, %b %-d · %-I:%M %p")
        except (ValueError, TypeError):
            return start_iso

    # ── Confirmation ────────────────────────────────────────────────────────────

    def confirm(self, suggestion_id: str, accept: bool) -> dict:
        """
        Answer a proactive suggestion. accept=True creates the event via the
        dispatcher (connected Google Calendar, or a prefilled fallback page);
        accept=False just dismisses it. Unknown/expired ids report failure.
        """
        with self._lock:
            pending = self._pending.pop(suggestion_id, None)

        if pending is None:
            return {
                "success": False,
                "action": "calendar_create_event",
                "message": "That suggestion expired.",
            }

        if not accept:
            return {
                "success": True,
                "action": "suggestion_dismissed",
                "message": "Okay, skipped.",
            }

        title = pending.get("title", "New event")
        start = pending.get("start", "")
        end = pending.get("end", "")
        location = pending.get("location", "")

        try:
            from voxa.intelligence.intent_parser import Action, ActionType
            from voxa.actions import dispatcher

            action = Action(
                action=ActionType.CALENDAR_CREATE_EVENT,
                description=title,
                event_title=title,
                event_start=start,
                event_end=end,
                event_location=location or None,
            )
            return dispatcher.execute_action(action)
        except Exception as e:
            log.warning("Suggestion confirm failed: %s", e)
            return {
                "success": False,
                "action": "calendar_create_event",
                "message": f"Couldn't add it: {e}",
            }

    # ── Introspection / maintenance ─────────────────────────────────────────────

    def list_pending(self) -> list[dict]:
        """Return the payloads of all currently-pending suggestions."""
        self._cleanup_expired()
        with self._lock:
            return [
                {
                    "id": rec["id"],
                    "kind": rec["kind"],
                    "title": rec["title"],
                    "when_text": rec["when_text"],
                    "start_iso": rec["start_iso"],
                    "end_iso": rec["end_iso"],
                    "location": rec["location"],
                }
                for rec in self._pending.values()
            ]

    def _cleanup_expired(self):
        """Drop pending suggestions older than the TTL (their moment passed)."""
        now = time.time()
        with self._lock:
            expired = [
                sid for sid, rec in self._pending.items()
                if now - rec.get("created", now) > _SUGGESTION_TTL_SECONDS
            ]
            for sid in expired:
                self._pending.pop(sid, None)

    def reset(self):
        """Clear all pending suggestions and per-session dedup memory."""
        with self._lock:
            self._pending.clear()
            self._suggested.clear()


# ── Singleton ────────────────────────────────────────────────────────────────────
suggestion_manager = SuggestionManager()
