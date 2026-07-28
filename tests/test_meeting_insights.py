"""
Tests for structured meeting insights — AI summary, action items, to-dos, and
follow-up detection.

All hermetic: the store is a MagicMock returning fake segments, meetings.json is
redirected to pytest's tmp_path, and OpenAI is never hit — tests patch the
single ``_extract_llm`` seam (or ``meeting_insights.extract``).
"""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from voxa.memory.insights import (
    MeetingInsights,
    render_summary_text,
    NO_SPEECH_NOTE,
)


def _seg(text, ts="2026-07-22T15:00:00", raw=None):
    return SimpleNamespace(filtered_text=text, raw_transcript=raw or text, timestamp=ts)


def _store_with(segments):
    store = MagicMock()
    store.get_by_session.return_value = segments
    return store


FULL_LLM = {
    "summary": "The team reviewed the Q3 roadmap and agreed to ship the beta.",
    "key_points": ["Q3 roadmap review", "Beta scope locked"],
    "decisions": ["Ship beta on Friday"],
    "action_items": [
        {"task": "Send the launch email", "owner": "Me", "due": "Thursday"},
        {"task": "Prepare release notes", "owner": "Aman", "due": ""},
    ],
    "todos": ["Draft the launch email"],
    "follow_ups": [{"task": "Confirm pricing", "person": "Sam"}],
}


# ── 1. Happy path — full structured extraction ────────────────────────────────

class TestExtract:
    def test_full_structured_result(self):
        ins = MeetingInsights(store=_store_with([_seg("Let's ship the beta Friday.")]))
        with patch.object(ins, "_extract_llm", return_value=FULL_LLM):
            out = ins.extract("sess1")

        assert out["summary"].startswith("The team reviewed")
        assert out["key_points"] == ["Q3 roadmap review", "Beta scope locked"]
        assert out["decisions"] == ["Ship beta on Friday"]
        assert out["segment_count"] == 1
        assert "elapsed_ms" in out

        items = out["action_items"]
        assert len(items) == 2
        assert items[0] == {"task": "Send the launch email", "owner": "Me", "due": "Thursday"}
        assert items[1] == {"task": "Prepare release notes", "owner": "Aman", "due": ""}

        assert out["todos"] == ["Draft the launch email"]
        assert out["follow_ups"] == [{"task": "Confirm pricing", "person": "Sam"}]

    def test_transcript_passed_to_llm_oldest_first(self):
        segs = [_seg("First thing.", ts="2026-07-22T15:00:00"),
                _seg("Second thing.", ts="2026-07-22T15:01:00")]
        ins = MeetingInsights(store=_store_with(segs))
        with patch.object(ins, "_extract_llm", return_value=FULL_LLM) as m:
            ins.extract("sess1")
        transcript = m.call_args[0][0]
        assert transcript.index("First thing.") < transcript.index("Second thing.")


# ── 2. Empty / no-speech session ──────────────────────────────────────────────

class TestNoSpeech:
    def test_no_segments_returns_honest_note(self):
        ins = MeetingInsights(store=_store_with([]))
        # Should never even call the LLM.
        with patch.object(ins, "_extract_llm", side_effect=AssertionError("LLM called")):
            out = ins.extract("sess1")
        assert out["summary"] == NO_SPEECH_NOTE
        assert out["action_items"] == []
        assert out["todos"] == []
        assert out["follow_ups"] == []
        assert out["segment_count"] == 0

    def test_blank_session_id(self):
        out = MeetingInsights(store=_store_with([_seg("hi")])).extract("")
        assert out["segment_count"] == 0
        assert out["summary"] == ""


# ── 3. LLM unavailable / bad output ───────────────────────────────────────────

class TestDegraded:
    def test_llm_returns_none_gives_neutral_summary(self):
        ins = MeetingInsights(store=_store_with([_seg("real talk here")]))
        with patch.object(ins, "_extract_llm", return_value=None):
            out = ins.extract("sess1")
        assert out["summary"]  # non-empty neutral note
        assert "searchable in Memory" in out["summary"]
        assert out["action_items"] == []
        assert out["segment_count"] == 1

    def test_store_failure_is_swallowed(self):
        store = MagicMock()
        store.get_by_session.side_effect = RuntimeError("db down")
        out = MeetingInsights(store=store).extract("sess1")
        assert out["segment_count"] == 0
        assert out["summary"] == NO_SPEECH_NOTE


# ── 4. Normalization robustness (untrusted model JSON) ────────────────────────

class TestNormalize:
    def _run(self, raw):
        ins = MeetingInsights(store=_store_with([_seg("x")]))
        with patch.object(ins, "_extract_llm", return_value=raw):
            return ins.extract("sess1")

    def test_string_action_item_coerced(self):
        out = self._run({"action_items": ["Just do the thing"]})
        assert out["action_items"] == [{"task": "Just do the thing", "owner": "", "due": ""}]

    def test_action_item_field_aliases(self):
        out = self._run({"action_items": [{"text": "Fix bug", "assignee": "Me", "deadline": "EOD"}]})
        assert out["action_items"] == [{"task": "Fix bug", "owner": "Me", "due": "EOD"}]

    def test_followup_with_alias(self):
        out = self._run({"follow_ups": [{"task": "Ping legal", "with": "Dana"}]})
        assert out["follow_ups"] == [{"task": "Ping legal", "person": "Dana"}]

    def test_empty_and_bad_items_dropped(self):
        out = self._run({
            "action_items": [{"task": ""}, {"owner": "Me"}, None, 5],
            "key_points": ["A", "a", "", "B"],  # dedup case-insensitively, drop empty
            "todos": "not a list",
        })
        assert out["action_items"] == []
        assert out["key_points"] == ["A", "B"]
        assert out["todos"] == []

    def test_non_dict_llm_output(self):
        out = self._run(["not", "a", "dict"])
        assert out["action_items"] == []
        assert out["summary"]  # neutral fallback note


# ── 5. render_summary_text ────────────────────────────────────────────────────

class TestRenderSummary:
    def test_renders_all_sections(self):
        text = render_summary_text(MeetingInsights(store=None)._normalize(FULL_LLM, 1))
        assert "The team reviewed" in text
        assert "Key points:" in text
        assert "Decisions:" in text
        assert "Action items:" in text
        assert "Send the launch email — Me (due Thursday)" in text
        assert "Prepare release notes — Aman" in text
        assert "To-dos:" in text
        assert "Follow-ups:" in text
        assert "Confirm pricing — with Sam" in text

    def test_empty_insights_renders_empty(self):
        assert render_summary_text({"summary": "", "action_items": []}) == ""

    def test_summary_only(self):
        assert render_summary_text({"summary": "Just a recap."}) == "Just a recap."


# ── 6. MeetingManager integration ─────────────────────────────────────────────

from voxa.memory import meeting_manager as mm_module
from voxa.memory.meeting_manager import MeetingManager


@pytest.fixture
def redirect_meetings(tmp_path):
    """Point the manager's meetings.json at tmp_path for the test."""
    mfile = tmp_path / "meetings.json"
    with patch.object(mm_module, "MEETINGS_DIR", tmp_path), \
         patch.object(mm_module, "MEETINGS_FILE", mfile):
        yield mfile


class TestManagerIntegration:
    def test_build_notes_shapes_record(self, redirect_meetings):
        mm = MeetingManager()
        canned = {**FULL_LLM, "segment_count": 3}
        with patch("voxa.memory.insights.meeting_insights.extract", return_value=canned):
            notes = mm._build_notes("sess1")
        assert notes["summary"].startswith("The team reviewed")
        assert notes["action_items"][0]["task"] == "Send the launch email"
        assert notes["todos"] == ["Draft the launch email"]
        assert notes["follow_ups"][0]["person"] == "Sam"

    def test_build_notes_falls_back_to_flattened_summary(self, redirect_meetings):
        mm = MeetingManager()
        # Model gave structure but no narrative summary → flatten it.
        canned = {**FULL_LLM, "summary": "", "segment_count": 2}
        with patch("voxa.memory.insights.meeting_insights.extract", return_value=canned):
            notes = mm._build_notes("sess1")
        assert notes["summary"]  # not blank
        assert "Action items:" in notes["summary"]

    def test_regenerate_updates_saved_record(self, redirect_meetings):
        mfile = redirect_meetings
        # A meeting saved before insights existed (only a summary field).
        mfile.write_text(json.dumps({"meetings": [
            {"session_id": "sess1", "platform": "Zoom", "summary": "old"},
            {"session_id": "other", "platform": "Meet", "summary": "keep me"},
        ]}))

        mm = MeetingManager()
        canned = {**FULL_LLM, "segment_count": 4}
        with patch("voxa.memory.insights.meeting_insights.extract", return_value=canned):
            res = mm.regenerate_insights("sess1")

        assert res["success"] is True
        saved = json.loads(mfile.read_text())["meetings"]
        rec = next(m for m in saved if m["session_id"] == "sess1")
        assert rec["summary"].startswith("The team reviewed")
        assert rec["action_items"][0]["owner"] == "Me"
        assert rec["todos"] == ["Draft the launch email"]
        # Untouched record preserved.
        other = next(m for m in saved if m["session_id"] == "other")
        assert other["summary"] == "keep me"

    def test_regenerate_unknown_session(self, redirect_meetings):
        redirect_meetings.write_text(json.dumps({"meetings": []}))
        mm = MeetingManager()
        with patch("voxa.memory.insights.meeting_insights.extract",
                   return_value={**FULL_LLM, "segment_count": 1}):
            res = mm.regenerate_insights("nope")
        assert res["success"] is False

    def test_regenerate_blank_session(self, redirect_meetings):
        assert MeetingManager().regenerate_insights("")["success"] is False
