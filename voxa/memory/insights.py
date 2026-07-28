"""
Meeting Insights — structured notes extracted from a recorded conversation.

Given a session's transcript (the same clips the MemoryEngine already captured &
transcribed), this runs ONE LLM pass that returns discrete, usable structures
rather than a single prose blob:

  • summary       — a short narrative recap (2–4 sentences)
  • key_points    — the topics/highlights that were discussed
  • decisions     — decisions the group actually landed on
  • action_items  — {task, owner, due} — concrete commitments someone owns
  • todos         — the primary user's own personal to-dos ("I'll …")
  • follow_ups    — {task, person} — things to circle back on with someone

The MeetingManager calls :meth:`MeetingInsights.extract` when a meeting ends and
persists the result into ~/.voxa/meetings.json, so the Meetings UI can render
each section on its own. ``_extract_llm`` is the ONLY OpenAI touchpoint — tests
patch it so they never hit the network.

Design mirrors voxa/memory/suggestions.py and voxa/memory/sessions.py (module
singleton, a single fresh-client fast/quality-model call, defensive JSON parse).
"""
from __future__ import annotations

import json
import time
from typing import Optional

from voxa.utils.logger import get_logger

log = get_logger("memory.insights")

# Longest transcript slice we send to the model (keeps us well under context).
_MAX_TRANSCRIPT_CHARS = 40000

# Shown (and stored as the summary) when a session captured no usable speech —
# an honest, actionable note instead of a hallucinated summary.
NO_SPEECH_NOTE = (
    "No speech was captured for this meeting. Make sure Voxa has Microphone "
    "access (System Settings → Privacy & Security → Microphone). To capture "
    "other participants, enable system audio."
)

_SYSTEM_PROMPT = (
    "You are a meeting notetaker. You are given a transcript of a conversation or "
    "meeting, with turns attributed to speakers (e.g. 'Me:', 'Aman:', "
    "'Participant:'). Produce concise, structured notes. Base everything ONLY on "
    "what the transcript actually says — never invent details, names, or dates.\n\n"
    "Return JSON only, with exactly these keys:\n"
    "{\n"
    '  "summary": "2-4 sentence narrative recap of what the meeting was about and how it ended",\n'
    '  "key_points": ["the main topics / highlights discussed", ...],\n'
    '  "decisions": ["concrete decisions the group actually landed on", ...],\n'
    '  "action_items": [{"task": "what needs to be done", "owner": "who owns it (name, \'Me\', or \'\' if unclear)", "due": "when it\'s due, verbatim from the talk, or \'\'"}],\n'
    '  "todos": ["a personal to-do for the primary user (things *I* said I would do)", ...],\n'
    '  "follow_ups": [{"task": "something to circle back on later", "person": "who to follow up with, or \'\'"}]\n'
    "}\n\n"
    "Rules:\n"
    "- Every list may be empty. Prefer an empty list over a weak or invented item.\n"
    "- action_items are commitments *anyone* made; todos are only the primary "
    "user's ('Me') own commitments. An item can appear in both if it's the "
    "user's own action.\n"
    "- follow_ups are open threads / 'let's revisit', NOT already-settled actions.\n"
    "- Keep each item to one short line. No markdown, no numbering, no trailing periods on list items.\n"
    "- Do not include speaker labels inside the item text."
)


def _clean_str(value) -> str:
    """Coerce a model value to a trimmed string ('' for None/other types)."""
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    return value.strip()


def _clean_str_list(value) -> list[str]:
    """Coerce a model value to a de-duplicated list of non-empty strings."""
    if not isinstance(value, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = _clean_str(item)
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            out.append(text)
    return out


class MeetingInsights:
    """Turns a session transcript into structured meeting notes."""

    def __init__(self, store=None):
        # Injectable so tests never touch the live DB.
        self._store_override = store

    # ── Store access (lazy — resolve the live DB at call time) ─────────────────

    @property
    def _store(self):
        if self._store_override is not None:
            return self._store_override
        from voxa.memory.engine import memory_engine
        return memory_engine.store

    # ── Public API ─────────────────────────────────────────────────────────────

    def empty(self, note: str = "") -> dict:
        """A fully-formed, empty insights payload (all sections present)."""
        return {
            "summary": note,
            "key_points": [],
            "decisions": [],
            "action_items": [],
            "todos": [],
            "follow_ups": [],
            "segment_count": 0,
        }

    def extract(self, session_id: str) -> dict:
        """
        Build structured notes for a session. Always returns a fully-formed dict
        with every section present (empty lists when nothing applies), plus
        ``segment_count`` and ``elapsed_ms``. Never raises.
        """
        start = time.time()

        if not session_id:
            return {**self.empty(), "elapsed_ms": 0}

        try:
            segments = self._store.get_by_session(session_id)
        except Exception as e:
            log.warning("Insights: failed to load session %s: %s", session_id, e)
            segments = []

        segment_count = len(segments)
        if segment_count == 0:
            # No speech captured — honest note, empty structures.
            return {
                **self.empty(NO_SPEECH_NOTE),
                "elapsed_ms": int((time.time() - start) * 1000),
            }

        transcript = self._session_transcript(segments)
        raw = self._extract_llm(transcript) if transcript else None
        insights = self._normalize(raw, segment_count)
        insights["segment_count"] = segment_count
        insights["elapsed_ms"] = int((time.time() - start) * 1000)

        log.info(
            "🧾 Meeting insights for %s: %d action items, %d todos, %d follow-ups (%dms)",
            (session_id or "")[:8],
            len(insights["action_items"]),
            len(insights["todos"]),
            len(insights["follow_ups"]),
            insights["elapsed_ms"],
        )
        return insights

    # ── Normalization ──────────────────────────────────────────────────────────

    def _normalize(self, raw: Optional[dict], segment_count: int) -> dict:
        """Coerce the model's (untrusted) JSON into the strict output schema."""
        if not isinstance(raw, dict):
            # LLM unavailable / parse failure — return empty structures but keep a
            # neutral summary so the UI isn't blank.
            return self.empty(
                "Notes couldn't be generated for this meeting. The transcript is "
                "saved and searchable in Memory."
            )

        action_items = []
        for item in raw.get("action_items") or []:
            if not isinstance(item, dict):
                # Tolerate a plain string action item (ignore other junk types).
                if isinstance(item, str) and item.strip():
                    action_items.append({"task": item.strip(), "owner": "", "due": ""})
                continue
            task = _clean_str(item.get("task") or item.get("text"))
            if not task:
                continue
            action_items.append({
                "task": task,
                "owner": _clean_str(item.get("owner") or item.get("assignee")),
                "due": _clean_str(item.get("due") or item.get("deadline")),
            })

        follow_ups = []
        for item in raw.get("follow_ups") or []:
            if not isinstance(item, dict):
                if isinstance(item, str) and item.strip():
                    follow_ups.append({"task": item.strip(), "person": ""})
                continue
            task = _clean_str(item.get("task") or item.get("text"))
            if not task:
                continue
            follow_ups.append({
                "task": task,
                "person": _clean_str(item.get("person") or item.get("with")),
            })

        return {
            "summary": _clean_str(raw.get("summary")),
            "key_points": _clean_str_list(raw.get("key_points")),
            "decisions": _clean_str_list(raw.get("decisions")),
            "action_items": action_items,
            "todos": _clean_str_list(raw.get("todos")),
            "follow_ups": follow_ups,
        }

    @staticmethod
    def _session_transcript(segments) -> str:
        """Join a session's filtered_text (falling back to raw), oldest→newest."""
        parts = []
        for seg in segments:
            text = (getattr(seg, "filtered_text", "") or
                    getattr(seg, "raw_transcript", "") or "").strip()
            if text:
                ts = (getattr(seg, "timestamp", "") or "")[:19]
                parts.append(f"[{ts}] {text}" if ts else text)
        return "\n".join(parts)[:_MAX_TRANSCRIPT_CHARS]

    # ── OpenAI touchpoint (patched in tests) ───────────────────────────────────

    def _extract_llm(self, transcript: str) -> Optional[dict]:
        """
        The ONLY OpenAI touchpoint. Returns the parsed JSON dict, or None on any
        failure / missing key (caller falls back to a neutral payload).
        """
        try:
            from openai import OpenAI
            from voxa.config import config

            api_key = config.OPENAI_API_KEY
            if not api_key:
                return None

            client = OpenAI(api_key=api_key)
            response = client.chat.completions.create(
                model=config.LLM_MODEL,  # gpt-4o — runs once per meeting
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": transcript[:_MAX_TRANSCRIPT_CHARS]},
                ],
                temperature=0.2,
                response_format={"type": "json_object"},
                max_tokens=1200,
            )
            content = response.choices[0].message.content or ""
            data = json.loads(content)
            return data if isinstance(data, dict) else None
        except Exception as e:
            log.warning("Insights extraction failed: %s", e)
            return None


def render_summary_text(insights: dict) -> str:
    """
    Flatten structured insights into a single readable text block.

    Used for the meeting record's ``summary`` field (backward-compat with older
    clients / the plain-text card) and anywhere a one-string recap is handy.
    """
    if not isinstance(insights, dict):
        return ""

    lines: list[str] = []
    summary = _clean_str(insights.get("summary"))
    if summary:
        lines.append(summary)

    def _section(title: str, items: list[str]):
        if not items:
            return
        if lines:
            lines.append("")
        lines.append(title)
        lines.extend(f"• {it}" for it in items)

    _section("Key points:", _clean_str_list(insights.get("key_points")))
    _section("Decisions:", _clean_str_list(insights.get("decisions")))

    action_lines = []
    for item in insights.get("action_items") or []:
        if not isinstance(item, dict):
            continue
        task = _clean_str(item.get("task"))
        if not task:
            continue
        owner = _clean_str(item.get("owner"))
        due = _clean_str(item.get("due"))
        suffix = ""
        if owner:
            suffix += f" — {owner}"
        if due:
            suffix += f" (due {due})"
        action_lines.append(task + suffix)
    _section("Action items:", action_lines)

    _section("To-dos:", _clean_str_list(insights.get("todos")))

    followup_lines = []
    for item in insights.get("follow_ups") or []:
        if not isinstance(item, dict):
            continue
        task = _clean_str(item.get("task"))
        if not task:
            continue
        person = _clean_str(item.get("person"))
        followup_lines.append(f"{task} — with {person}" if person else task)
    _section("Follow-ups:", followup_lines)

    return "\n".join(lines).strip()


# ── Singleton ──────────────────────────────────────────────────────────────────
meeting_insights = MeetingInsights()
