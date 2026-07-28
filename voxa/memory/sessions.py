"""
Session Organizer — turns loose 20-30s clips into named "meeting" cards.

The Recordings drawer used to show one row per clip (a 40-min meeting = ~100
rows). This joins three sources into a single card per conversation session:

  1. The store's clip-bearing sessions (``list_sessions_with_clips`` / the live DB).
  2. The meeting platform recorded in ~/.voxa/meetings.json, keyed by the SAME
     session_id (meeting_manager captures it at record start) — so a card can be
     badged *Google Meet* / *Zoom* / *Microphone*.
  3. A short AI title derived from what was actually discussed, cached on disk at
     ~/.voxa/session_titles.json so we don't re-summarize a stable session.

Design mirrors voxa/memory/suggestions.py (module singleton, threading.Lock, a
single fresh-OpenAI-client fast-model touchpoint) and meeting_manager.py
(defensive JSON persistence). ``_llm_title`` is the ONLY OpenAI touchpoint —
tests patch it (or ``_title_for``) so they never hit the network.
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from voxa.utils.logger import get_logger

log = get_logger("memory.sessions")

# Persistent cache of generated titles, keyed by session_id:
#   {session_id: {"title": str, "clip_count": int, "generated_at": float}}
TITLE_CACHE_FILE = Path.home() / ".voxa" / "session_titles.json"

_TITLE_SYSTEM_PROMPT = (
    "Give a concise 3–6 word title for this conversation. "
    "Plain text, no quotes, no trailing period."
)

# Longest transcript slice we send to the title model.
_MAX_TRANSCRIPT_CHARS = 2500


class SessionOrganizer:
    """Joins store sessions + meeting platform + cached AI titles into cards."""

    def __init__(self, cache_path: Optional[Path] = None, store=None):
        # Both are test-injectable so tests never touch real ~/.voxa or the live
        # DB: point cache_path at a tmp file and pass an isolated MemoryStore.
        self._cache_path = Path(cache_path) if cache_path else TITLE_CACHE_FILE
        self._store_override = store
        self._lock = threading.Lock()
        self._cache: dict[str, dict] = self._load_cache()
        # Refreshed at the start of each list_clip_sessions(); consulted by the
        # per-session platform/title fallbacks.
        self._meeting_index: dict[str, dict] = {}

    # ── Store access (lazy — resolve the live DB at call time) ────────────────

    @property
    def _store(self):
        """The injected store, else the live memory engine's store (lazy import)."""
        if self._store_override is not None:
            return self._store_override
        from voxa.memory.engine import memory_engine
        return memory_engine.store

    # ── Public API ────────────────────────────────────────────────────────────

    def list_clip_sessions(self, limit: int = 30) -> list[dict]:
        """Build the /api/memory/clip-sessions payload, newest session first."""
        store = self._store
        rows = store.list_sessions_with_clips(limit)
        self._meeting_index = self._build_meeting_index()

        sessions = []
        for row in rows:
            session_id = row.get("session_id") or ""
            platform, platform_kind = self._platform_for(session_id)
            title = self._title_for(session_id)
            clips = store.get_session_clips(session_id)
            sessions.append({
                "session_id": session_id,
                "title": title,
                "platform": platform,
                "platform_kind": platform_kind,
                "started_iso": row.get("started_iso", "") or "",
                "ended_iso": row.get("ended_iso", "") or "",
                "duration_secs": row.get("duration_secs", 0.0) or 0.0,
                "clip_count": row.get("clip_count", 0),
                "sources": row.get("sources", []),
                "clips": clips,
            })
        return sessions

    def delete_session(self, session_id: str) -> dict:
        """Delete a session's clip files (transcripts stay searchable in Memory)."""
        n = self._store.clear_session_clips(session_id)
        self.invalidate(session_id)
        return {"success": n > 0, "deleted_clips": n}

    # ── Platform / meeting join ───────────────────────────────────────────────

    def _build_meeting_index(self) -> dict[str, dict]:
        """Map session_id -> its meeting record (newest wins) from meetings.json."""
        try:
            from voxa.memory.meeting_manager import meeting_manager
            meetings = meeting_manager.list_meetings(limit=200)
        except Exception as e:
            log.debug("Failed to load meetings for session index: %s", e)
            return {}
        index: dict[str, dict] = {}
        for m in meetings:
            sid = (m.get("session_id") or "") if isinstance(m, dict) else ""
            if sid and sid not in index:
                index[sid] = m
        return index

    def _platform_for(self, session_id: str) -> tuple[str, str]:
        """(platform, platform_kind) for a session — 'Microphone'/'mic' if ambient."""
        rec = self._meeting_index.get(session_id)
        if not rec:
            return "Microphone", "mic"
        platform = rec.get("platform") or "Microphone"
        source = rec.get("source") or ""
        # Browser meeting tabs → "browser"; native app calls (or unlabeled
        # meeting records) → "app".
        kind = "browser" if source == "browser" else "app"
        return platform, kind

    # ── AI titles (cached) ────────────────────────────────────────────────────

    def _title_for(self, session_id: str) -> str:
        """A short title for the session, from cache or freshly generated.

        Regenerates only when the cache is missing or the session grew materially
        since it was cached (so the title reflects a fuller conversation). This is
        the only path that reaches OpenAI (via ``_llm_title``); it always returns
        a usable string, falling back to platform + date or "Conversation".
        """
        segments = []
        try:
            segments = self._store.get_by_session(session_id)
        except Exception as e:
            log.debug("Failed to load session %s for title: %s", session_id, e)
        clip_count = len(segments)

        with self._lock:
            cached = self._cache.get(session_id)
            if cached and not self._needs_regen(cached, clip_count):
                return cached.get("title") or "Conversation"

        transcript = self._session_transcript(segments)
        title = self._llm_title(transcript) if transcript else ""
        is_fallback = not title
        if is_fallback:
            title = self._fallback_title(session_id, segments)

        with self._lock:
            self._cache[session_id] = {
                "title": title,
                "clip_count": clip_count,
                "generated_at": time.time(),
                # A fallback ("Google Meet · Jul 22") means the LLM was unavailable
                # (no key / API error / empty transcript). Never treat it as final —
                # retry a real title next time. Only a real AI title is sticky.
                "fallback": is_fallback,
            }
            self._save_cache()
        return title

    @staticmethod
    def _needs_regen(cached: dict, clip_count: int) -> bool:
        """True if the cached title should be regenerated."""
        # Always retry a previously-failed fallback title — the key/API may work now.
        if cached.get("fallback"):
            return True
        cached_count = cached.get("clip_count", 0) or 0
        if clip_count <= cached_count:
            return False
        # "Materially" = at least a few more clips (and ~50% more), so a stable
        # session keeps its title but a still-growing meeting gets re-titled.
        return (clip_count - cached_count) >= max(3, int(cached_count * 0.5))

    @staticmethod
    def _session_transcript(segments) -> str:
        """Join a session's filtered_text, truncated to the model's input budget."""
        parts = []
        for seg in segments:
            text = (getattr(seg, "filtered_text", "") or "").strip()
            if text:
                parts.append(text)
        return " ".join(parts)[:_MAX_TRANSCRIPT_CHARS]

    def _llm_title(self, transcript: str) -> str:
        """The ONLY OpenAI touchpoint (patched in tests).

        Uses a fresh small/fast-model client to name the conversation. Returns a
        cleaned title, or '' on any failure / missing key (caller falls back).
        """
        try:
            from openai import OpenAI
            from voxa.config import config

            api_key = config.OPENAI_API_KEY
            if not api_key:
                return ""

            client = OpenAI(api_key=api_key)
            response = client.chat.completions.create(
                model=config.LLM_MODEL_FAST,
                messages=[
                    {"role": "system", "content": _TITLE_SYSTEM_PROMPT},
                    {"role": "user", "content": transcript[:_MAX_TRANSCRIPT_CHARS]},
                ],
                temperature=0.3,
                max_tokens=20,
            )
            content = response.choices[0].message.content or ""
            return content.strip().strip('"').strip().rstrip(".").strip()
        except Exception as e:
            log.debug("Session title generation failed: %s", e)
            return ""

    def _fallback_title(self, session_id: str, segments) -> str:
        """Platform + date (e.g. 'Google Meet · Jul 22'), else 'Conversation'."""
        rec = self._meeting_index.get(session_id)
        platform = (rec.get("platform") or "").strip() if rec else ""

        date_str = ""
        if segments:
            try:
                date_str = datetime.fromisoformat(segments[0].timestamp).strftime("%b %-d")
            except Exception:
                date_str = ""

        if platform and date_str:
            return f"{platform} · {date_str}"
        if platform:
            return platform
        if date_str:
            return f"Conversation · {date_str}"
        return "Conversation"

    # ── Cache persistence ─────────────────────────────────────────────────────

    def _load_cache(self) -> dict[str, dict]:
        try:
            if self._cache_path.exists():
                with open(self._cache_path, "r") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception as e:
            log.debug("Failed to read session title cache: %s", e)
        return {}

    def _save_cache(self):
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._cache_path, "w") as f:
                json.dump(self._cache, f)
            try:
                os.chmod(self._cache_path, 0o600)
            except OSError:
                pass
        except Exception as e:
            log.debug("Failed to write session title cache: %s", e)

    def invalidate(self, session_id: str):
        """Drop a session's cached title (e.g. after its clips are deleted)."""
        with self._lock:
            if session_id in self._cache:
                self._cache.pop(session_id, None)
                self._save_cache()

    def reset(self):
        """Clear the in-memory title cache + meeting index (for tests)."""
        with self._lock:
            self._cache = {}
            self._meeting_index = {}


# ── Singleton ────────────────────────────────────────────────────────────────────
session_organizer = SessionOrganizer()
