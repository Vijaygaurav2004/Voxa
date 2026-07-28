"""
Meeting Manager — orchestrates Granola-style automatic meeting capture.

Wires the MeetingDetector to the ambient MemoryEngine:
  • When a meeting is detected, start ambient listening (if not already on) so the
    conversation is transcribed and stored.
  • When the meeting ends, stop listening (only if WE started it), then generate
    and persist a summary / notes for that session.

Past meetings are stored as JSON at ~/.voxa/meetings.json for the UI to list.
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from voxa.utils.logger import get_logger
from voxa.memory.meeting_detector import MeetingDetector

log = get_logger("memory.meeting_mgr")

MEETINGS_DIR = Path.home() / ".voxa"
MEETINGS_FILE = MEETINGS_DIR / "meetings.json"
MAX_STORED_MEETINGS = 100


class MeetingManager:
    """Singleton that turns detected meetings into captured, summarized notes."""

    def __init__(self, poll_interval: float | None = None):
        from voxa.config import config
        self._detector = MeetingDetector(
            on_meeting_start=self._on_meeting_start,
            on_meeting_end=self._on_meeting_end,
            poll_interval=poll_interval if poll_interval is not None else config.MEETING_POLL_INTERVAL,
            require_mic=config.MEETING_REQUIRE_MIC,
        )
        self._lock = threading.Lock()
        self._enabled = False
        # Whether WE auto-started the memory engine (so we know to stop it).
        self._auto_started_engine = False
        # The active meeting being recorded (with session_id), if any.
        self._active: Optional[dict] = None
        # Whether the active recording is currently paused.
        self._paused = False
        # A detected meeting awaiting the user's "record?" answer, if any.
        self._pending: Optional[dict] = None
        # Callback used to push events (meeting_detected, …) to the app over WS.
        self._notifier: Optional[Callable[[str, dict], None]] = None

    # ── Notifier (app prompt channel) ───────────────────────────────────────────

    def set_notifier(self, fn: Callable[[str, dict], None]):
        """Register a callback (event, data) used to notify the app (via WebSocket)."""
        self._notifier = fn

    def _notify(self, event: str, data: dict):
        if self._notifier:
            try:
                self._notifier(event, data)
            except Exception as e:
                log.warning("Meeting notify failed: %s", e)

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def enable(self) -> dict:
        """Begin automatically detecting meetings."""
        if self._enabled:
            return {"success": True, "message": "Meeting detection already on.", "enabled": True}
        self._enabled = True
        self._detector.start()
        log.info("📅 Meeting auto-detection enabled")
        return {"success": True, "message": "Meeting detection on — I'll ask before recording.", "enabled": True}

    def disable(self) -> dict:
        """Stop detecting meetings. Ends any in-progress capture cleanly."""
        if not self._enabled:
            return {"success": True, "message": "Meeting detection already off.", "enabled": False}
        self._enabled = False
        # If a meeting is currently being recorded, close it out first.
        if self._active is not None:
            self._on_meeting_end({**self._active, "ended_at": time.time()})
        with self._lock:
            self._pending = None
        self._detector.stop()
        log.info("📅 Meeting auto-detection disabled")
        return {"success": True, "message": "Meeting detection off.", "enabled": False}

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def status(self) -> dict:
        cur = self._active or self._pending or self._detector.current_meeting
        return {
            "enabled": self._enabled,
            "detecting": self._detector.is_running,
            "in_meeting": self._active is not None,
            "recording": self._active is not None and not self._paused,
            "paused": self._paused and self._active is not None,
            "awaiting_confirmation": self._pending is not None,
            "current": cur,
        }

    # ── Recording controls (pause / resume / end) ────────────────────────────────

    def pause_recording(self) -> dict:
        """Pause the active meeting recording (keeps the session open)."""
        with self._lock:
            if self._active is None:
                return {"success": False, "message": "No active meeting to pause."}
            if self._paused:
                return {"success": True, "paused": True, "message": "Already paused."}
            if self._auto_started_engine:
                try:
                    from voxa.memory.engine import memory_engine
                    memory_engine.pause()
                except Exception as e:
                    log.warning("Failed to pause capture: %s", e)
            self._paused = True
        self._notify("meeting_paused", {})
        log.info("⏸️  Meeting recording paused")
        return {"success": True, "paused": True, "message": "Recording paused."}

    def resume_recording(self) -> dict:
        """Resume a paused meeting recording."""
        with self._lock:
            if self._active is None:
                return {"success": False, "message": "No active meeting to resume."}
            if not self._paused:
                return {"success": True, "paused": False, "message": "Already recording."}
            if self._auto_started_engine:
                try:
                    from voxa.memory.engine import memory_engine
                    memory_engine.resume()
                except Exception as e:
                    log.warning("Failed to resume capture: %s", e)
            self._paused = False
        self._notify("meeting_resumed", {})
        log.info("▶️  Meeting recording resumed")
        return {"success": True, "paused": False, "message": "Recording resumed."}

    def end_recording(self) -> dict:
        """
        Manually end the current meeting recording now (even if the meeting app
        is still open) — stops capture, summarizes, and saves the notes.
        """
        with self._lock:
            active = self._active
        if active is None:
            return {"success": False, "message": "No active meeting recording to end."}
        platform = active.get("platform", "Meeting")
        saved = self._finalize(time.time())
        if saved:
            return {"success": True, "message": f"Ended and saved the {platform} meeting."}
        return {"success": True, "message": "Meeting ended."}

    # ── User confirmation ────────────────────────────────────────────────────────

    def confirm(self, record: bool) -> dict:
        """
        Answer the "record this meeting?" prompt. record=True starts capture for
        the pending meeting; record=False dismisses it (no capture).
        """
        pending = self._pending
        if pending is None and self._active is None:
            return {"success": False, "recording": False, "message": "No meeting to record right now."}

        if not record:
            with self._lock:
                self._pending = None
            self._notify("meeting_dismissed", {})
            log.info("🙅 User declined to record the meeting")
            return {"success": True, "recording": False, "message": "Okay, I won't record this meeting."}

        if self._active is not None:
            return {"success": True, "recording": True, "message": "Already recording this meeting."}
        if pending is None:
            return {"success": False, "recording": False, "message": "No meeting to record right now."}

        self._start_recording(pending)
        return {"success": True, "recording": True, "message": "Recording the meeting — I'll take notes."}

    # ── Detector callbacks ──────────────────────────────────────────────────────

    def _on_meeting_start(self, meeting: dict):
        from voxa.config import config

        # Auto-record mode: capture immediately, no prompt.
        if config.MEETING_AUTO_RECORD:
            self._start_recording(meeting)
            return

        # Default: ask the user first via the app.
        with self._lock:
            self._pending = {
                "platform": meeting.get("platform", "Meeting"),
                "source": meeting.get("source", ""),
                "detail": meeting.get("detail", ""),
                "started_at": meeting.get("started_at", time.time()),
            }
            platform = self._pending["platform"]
        log.info("🔔 Meeting detected (%s) — asking user whether to record", platform)
        self._notify("meeting_detected", {"platform": platform, "source": meeting.get("source", "")})

    def _start_recording(self, meeting: dict):
        """Start ambient capture for a meeting and mark it active."""
        from voxa.config import config
        external = config.MEETING_EXTERNAL_AUDIO
        with self._lock:
            from voxa.memory.engine import memory_engine

            if not memory_engine.is_active:
                try:
                    # External audio: the host app streams mic chunks in (it holds
                    # mic permission). Otherwise fall back to local Python capture.
                    memory_engine.start(external_audio=external)
                    self._auto_started_engine = True
                    log.info("🎙️  Started meeting capture (external_audio=%s)", external)
                except Exception as e:
                    log.error("Failed to start memory engine for meeting: %s", e)
                    self._auto_started_engine = False
            else:
                # Engine already running (e.g. always-on Memory) — reuse it; don't
                # ask the app to stream a duplicate audio source.
                self._auto_started_engine = False
                external = getattr(memory_engine, "_external_audio", False)

            self._active = {
                "platform": meeting.get("platform", "Meeting"),
                "source": meeting.get("source", ""),
                "detail": meeting.get("detail", ""),
                "started_at": meeting.get("started_at", time.time()),
                "session_id": getattr(memory_engine, "_current_session_id", ""),
            }
            self._pending = None
            platform = self._active["platform"]
        # Tell the app whether it should stream mic audio (and system audio, for
        # the other participants) for this meeting.
        self._notify("meeting_recording", {
            "platform": platform,
            "external_audio": external,
            "capture_system_audio": external and config.MEETING_CAPTURE_SYSTEM_AUDIO,
        })

    def _on_meeting_end(self, meeting: dict):
        self._finalize(meeting.get("ended_at", time.time()))

    def _finalize(self, ended_at: float) -> bool:
        """
        Stop capture, summarize, and persist the active meeting (if any).
        Returns True if a recorded meeting was saved, False otherwise.
        """
        with self._lock:
            active = self._active
            self._active = None
            self._pending = None
            self._paused = False
            if active is None:
                # Detected but never recorded (declined or unanswered), or already
                # finalized manually.
                self._notify("meeting_ended", {"recorded": False})
                return False

            from voxa.memory.engine import memory_engine

            session_id = active.get("session_id", "")

            # Stop capture only if we were the ones who started it.
            if self._auto_started_engine:
                try:
                    memory_engine.stop()
                except Exception as e:
                    log.warning("Failed to stop memory engine after meeting: %s", e)
                self._auto_started_engine = False

        # Extract structured notes outside the lock (LLM call can be slow).
        notes = self._build_notes(session_id)

        record = {
            "platform": active.get("platform", "Meeting"),
            "source": active.get("source", ""),
            "detail": active.get("detail", ""),
            "session_id": session_id,
            "started_at": active.get("started_at"),
            "ended_at": ended_at,
            "duration_secs": round(max(0.0, ended_at - (active.get("started_at") or ended_at)), 1),
            "started_iso": _iso(active.get("started_at")),
            "ended_iso": _iso(ended_at),
            **notes,
        }
        self._append_meeting(record)
        log.info("📝 Meeting saved: %s (%.0fs)", record["platform"], record["duration_secs"])
        self._notify("meeting_ended", {"recorded": True, "platform": record["platform"]})
        return True

    def _build_notes(self, session_id: str) -> dict:
        """
        Structured meeting notes for a session — a narrative summary plus discrete
        action items, personal to-dos, and follow-ups. Always returns every field
        (empty lists when nothing applies); never raises.
        """
        from voxa.memory.insights import meeting_insights, render_summary_text

        try:
            insights = meeting_insights.extract(session_id)
        except Exception as e:
            log.warning("Meeting insights failed: %s", e)
            insights = meeting_insights.empty()

        # Ensure a non-empty summary for real meetings even if the model returned
        # only structured lists (the "no speech" case already carries its note).
        summary = insights.get("summary", "") or ""
        if insights.get("segment_count", 0) > 0 and not summary:
            summary = render_summary_text(insights)

        return {
            "summary": summary,
            "key_points": insights.get("key_points", []),
            "decisions": insights.get("decisions", []),
            "action_items": insights.get("action_items", []),
            "todos": insights.get("todos", []),
            "follow_ups": insights.get("follow_ups", []),
        }

    def regenerate_insights(self, session_id: str) -> dict:
        """
        Re-run notes extraction for a previously-saved meeting and persist the
        refreshed summary / action items / to-dos / follow-ups into its record.
        Useful for meetings captured before insights existed, or to refresh notes.
        """
        if not session_id:
            return {"success": False, "message": "No session to summarize."}
        notes = self._build_notes(session_id)
        if not self._update_meeting(session_id, notes):
            return {"success": False, "message": "No saved meeting for that session."}
        log.info("🔁 Regenerated meeting notes for session %s", (session_id or "")[:8])
        return {"success": True, "message": "Notes regenerated.", **notes}

    # ── Persistence ─────────────────────────────────────────────────────────────

    def _load_meetings(self) -> list[dict]:
        if not MEETINGS_FILE.exists():
            return []
        try:
            with open(MEETINGS_FILE, "r") as f:
                data = json.load(f)
            return data.get("meetings", [])
        except Exception as e:
            log.warning("Failed to read meetings.json: %s", e)
            return []

    def _append_meeting(self, record: dict):
        meetings = self._load_meetings()
        meetings.insert(0, record)  # newest first
        meetings = meetings[:MAX_STORED_MEETINGS]
        try:
            MEETINGS_DIR.mkdir(parents=True, exist_ok=True)
            with open(MEETINGS_FILE, "w") as f:
                json.dump({"meetings": meetings}, f, indent=2)
        except Exception as e:
            log.warning("Failed to write meetings.json: %s", e)

    def export_to_reminders(self, session_id: str) -> dict:
        """
        Turn a saved meeting's action items and to-dos into macOS Reminders — the
        one-tap "these are my tasks now" step. Follow-ups (open threads) are left
        as notes and not exported. De-duplicates a to-do that repeats an owned
        action item. Returns {success, created, message}.
        """
        if not session_id:
            return {"success": False, "created": 0, "message": "No meeting selected."}
        rec = self._find_meeting(session_id)
        if rec is None:
            return {"success": False, "created": 0, "message": "No saved meeting for that session."}

        from voxa.actions import calendar

        platform = rec.get("platform") or "meeting"
        date_str = _short_date(rec.get("started_iso"))
        context = f"From {platform}" + (f" · {date_str}" if date_str else "") + " (via Voxa)"

        tasks: list[tuple[str, str]] = []  # (title, notes)
        seen: set[str] = set()

        for item in rec.get("action_items") or []:
            if not isinstance(item, dict):
                continue
            task = (item.get("task") or "").strip()
            key = task.lower()
            if not task or key in seen:
                continue
            seen.add(key)
            note_lines = [context]
            owner = (item.get("owner") or "").strip()
            due = (item.get("due") or "").strip()
            if owner and owner.lower() != "me":
                note_lines.append(f"Owner: {owner}")
            if due:
                note_lines.append(f"Due: {due}")
            tasks.append((task, "\n".join(note_lines)))

        for todo in rec.get("todos") or []:
            task = (todo or "").strip()
            key = task.lower()
            if not task or key in seen:
                continue
            seen.add(key)
            tasks.append((task, context))

        if not tasks:
            return {"success": False, "created": 0, "message": "No action items or to-dos to add."}

        created = 0
        for title, notes in tasks:
            try:
                if calendar.create_reminder(title, notes=notes).get("success"):
                    created += 1
            except Exception as e:
                log.warning("Reminder create failed for '%s': %s", title[:40], e)

        if created:
            self._update_meeting(session_id, {"reminders_exported": True})
        msg = (
            f"Added {created} reminder{'s' if created != 1 else ''} to your Reminders app."
            if created else
            "Couldn't add reminders. Open the Reminders app and try again."
        )
        log.info("🔔 Exported %d reminder(s) for session %s", created, (session_id or "")[:8])
        return {"success": created > 0, "created": created, "message": msg}

    def _find_meeting(self, session_id: str) -> Optional[dict]:
        """The first stored meeting record matching a session_id, or None."""
        if not session_id:
            return None
        for m in self._load_meetings():
            if isinstance(m, dict) and m.get("session_id") == session_id:
                return m
        return None

    def _update_meeting(self, session_id: str, fields: dict) -> bool:
        """Merge `fields` into the stored meeting record(s) for a session_id.

        Returns True if at least one record was found and rewritten to disk.
        """
        if not session_id:
            return False
        meetings = self._load_meetings()
        found = False
        for m in meetings:
            if isinstance(m, dict) and m.get("session_id") == session_id:
                m.update(fields)
                found = True
        if not found:
            return False
        try:
            MEETINGS_DIR.mkdir(parents=True, exist_ok=True)
            with open(MEETINGS_FILE, "w") as f:
                json.dump({"meetings": meetings}, f, indent=2)
        except Exception as e:
            log.warning("Failed to update meetings.json: %s", e)
            return False
        return True

    def list_meetings(self, limit: int = 20) -> list[dict]:
        return self._load_meetings()[:limit]


def _iso(ts: Optional[float]) -> str:
    if not ts:
        return ""
    try:
        return datetime.fromtimestamp(ts).isoformat(timespec="seconds")
    except Exception:
        return ""


def _short_date(iso_str: Optional[str]) -> str:
    """A human 'Jul 22' from an ISO timestamp string, or '' if unparseable."""
    if not iso_str:
        return ""
    try:
        return datetime.fromisoformat(iso_str).strftime("%b %-d")
    except (ValueError, TypeError):
        return ""


# ── Singleton ────────────────────────────────────────────────────────────────────
meeting_manager = MeetingManager()
