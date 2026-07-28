"""Tests for Feature 8 — session-grouped recordings (AI title · date · platform).

All hermetic: stores + clips live under pytest's tmp_path, the title cache is an
injected tmp file (never real ~/.voxa/session_titles.json), and OpenAI is never
hit — tests patch either ``_title_for`` or the ``_llm_title`` seam.
"""
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from voxa.memory.store import MemoryStore
from voxa.memory.sessions import SessionOrganizer


# ── Fixed timestamps so MIN/MAX/order assertions are deterministic ────────────
A_TS = ["2026-07-22T15:00:00", "2026-07-22T15:00:30", "2026-07-22T15:01:00"]
B_TS = ["2026-07-22T16:00:00", "2026-07-22T16:00:30"]


def _seed_clip(store: MemoryStore, session_id: str, ts_iso: str,
               source: str = "mic", text: str = "hello there",
               summary: str = "greeting", duration: float = 20.0):
    """Write a real clip file + a segment row, then pin its timestamp/duration."""
    path = store.save_clip(b"RIFF____WAVEdata" + b"\x00" * 128)
    seg = store.store_segment(
        raw_transcript=text,
        filtered_text=text,
        summary=summary,
        source=source,
        session_id=session_id,
        duration_secs=duration,
        audio_path=path,
    )
    with sqlite3.connect(store.db_path) as conn:
        conn.execute(
            "UPDATE memory_segments SET timestamp = ? WHERE id = ?",
            (ts_iso, seg.segment_id),
        )
    return seg, path


def _seed_two_sessions(store: MemoryStore):
    """Session A: 3 clips (mic/system/mic). Session B: 2 clips (mic). B is newer."""
    a = [_seed_clip(store, "sessAAAA", A_TS[0], source="mic"),
         _seed_clip(store, "sessAAAA", A_TS[1], source="system"),
         _seed_clip(store, "sessAAAA", A_TS[2], source="mic")]
    b = [_seed_clip(store, "sessBBBB", B_TS[0], source="mic"),
         _seed_clip(store, "sessBBBB", B_TS[1], source="mic")]
    return a, b


# ── 1. store.list_sessions_with_clips ─────────────────────────────────────────

class TestListSessionsWithClips:
    def test_groups_correctly(self, tmp_path):
        store = MemoryStore(db_path=tmp_path / "m.db")
        _seed_two_sessions(store)

        rows = store.list_sessions_with_clips()
        assert len(rows) == 2
        # Newest session (B, max ts 16:00:30) first.
        assert [r["session_id"] for r in rows] == ["sessBBBB", "sessAAAA"]

        by_id = {r["session_id"]: r for r in rows}
        a = by_id["sessAAAA"]
        assert a["clip_count"] == 3
        assert a["started_iso"] == A_TS[0]
        assert a["ended_iso"] == A_TS[2]
        assert a["duration_secs"] == pytest.approx(60.0)
        assert set(a["sources"]) == {"mic", "system"}

        b = by_id["sessBBBB"]
        assert b["clip_count"] == 2
        assert b["duration_secs"] == pytest.approx(40.0)
        assert set(b["sources"]) == {"mic"}

    def test_excludes_sessions_without_clip_files(self, tmp_path):
        store = MemoryStore(db_path=tmp_path / "m.db")
        # A transcript-only segment (no audio_path) must not surface as a session.
        store.store_segment(raw_transcript="x", filtered_text="x", session_id="noaudio")
        assert store.list_sessions_with_clips() == []


# ── 2. store.get_session_clips ────────────────────────────────────────────────

class TestGetSessionClips:
    def test_oldest_to_newest_with_size(self, tmp_path):
        store = MemoryStore(db_path=tmp_path / "m.db")
        _seed_two_sessions(store)

        clips = store.get_session_clips("sessAAAA")
        assert [c["timestamp"] for c in clips] == A_TS  # oldest → newest
        assert all(c["size_bytes"] > 0 for c in clips)
        assert all(c["session_id"] == "sessAAAA" for c in clips)
        # Disk paths are never leaked in this payload.
        assert all("audio_path" not in c for c in clips)


# ── 3. store.clear_session_clips ──────────────────────────────────────────────

class TestClearSessionClips:
    def test_scoped_to_one_session(self, tmp_path):
        store = MemoryStore(db_path=tmp_path / "m.db")
        a, b = _seed_two_sessions(store)
        a_paths = [p for _, p in a]
        b_paths = [p for _, p in b]

        removed = store.clear_session_clips("sessAAAA")
        assert removed == 3
        # A's files gone + rows cleared; B untouched.
        assert all(not Path(p).exists() for p in a_paths)
        assert all(Path(p).exists() for p in b_paths)
        assert store.get_session_clips("sessAAAA") == []
        assert len(store.get_session_clips("sessBBBB")) == 2
        # Transcripts survive (audio_path reset to '').
        segs = store.get_by_session("sessAAAA")
        assert len(segs) == 3
        assert all(s.audio_path == "" for s in segs)


# ── 4. SessionOrganizer.list_clip_sessions (platform join) ────────────────────

class TestListClipSessions:
    def test_joins_platform_and_title(self, tmp_path):
        store = MemoryStore(db_path=tmp_path / "m.db")
        _seed_two_sessions(store)
        org = SessionOrganizer(cache_path=tmp_path / "titles.json", store=store)

        meeting_rec = [{
            "session_id": "sessAAAA",
            "platform": "Google Meet",
            "source": "browser",
        }]
        with patch.object(org, "_title_for", return_value="Test Title"), \
             patch("voxa.memory.meeting_manager.meeting_manager.list_meetings",
                   return_value=meeting_rec):
            sessions = org.list_clip_sessions()

        assert [s["session_id"] for s in sessions] == ["sessBBBB", "sessAAAA"]
        by_id = {s["session_id"]: s for s in sessions}

        a = by_id["sessAAAA"]
        assert a["platform"] == "Google Meet"
        assert a["platform_kind"] == "browser"
        assert a["title"] == "Test Title"
        assert a["clip_count"] == 3
        assert len(a["clips"]) == 3

        b = by_id["sessBBBB"]
        assert b["platform"] == "Microphone"
        assert b["platform_kind"] == "mic"
        assert b["title"] == "Test Title"
        assert len(b["clips"]) == 2


# ── 5. Title cache (generate once, then serve cached) ─────────────────────────

class TestTitleCache:
    def test_generates_once_then_cached(self, tmp_path):
        store = MemoryStore(db_path=tmp_path / "m.db")
        _seed_clip(store, "sessAAAA", A_TS[0], text="Let's plan the Q3 roadmap")
        _seed_clip(store, "sessAAAA", A_TS[1], text="Owners and deadlines")
        org = SessionOrganizer(cache_path=tmp_path / "titles.json", store=store)

        llm = MagicMock(return_value="Q3 Roadmap Planning")
        with patch.object(org, "_llm_title", llm):
            first = org._title_for("sessAAAA")
            second = org._title_for("sessAAAA")

        assert first == "Q3 Roadmap Planning"
        assert second == "Q3 Roadmap Planning"
        llm.assert_called_once()                      # second call served from cache
        # Persisted to the injected cache file, not real ~/.voxa.
        assert (tmp_path / "titles.json").exists()

    def test_empty_transcript_falls_back(self, tmp_path):
        store = MemoryStore(db_path=tmp_path / "m.db")
        org = SessionOrganizer(cache_path=tmp_path / "titles.json", store=store)
        # No segments for this session → no LLM call, graceful fallback.
        with patch.object(org, "_llm_title", MagicMock()) as llm:
            title = org._title_for("ghost")
        assert title == "Conversation"
        llm.assert_not_called()


# ── 6. delete_session ─────────────────────────────────────────────────────────

class TestDeleteSession:
    def test_removes_clips_and_reports_count(self, tmp_path):
        store = MemoryStore(db_path=tmp_path / "m.db")
        a, _ = _seed_two_sessions(store)
        org = SessionOrganizer(cache_path=tmp_path / "titles.json", store=store)

        result = org.delete_session("sessAAAA")
        assert result == {"success": True, "deleted_clips": 3}
        assert all(not Path(p).exists() for _, p in a)
        assert store.get_session_clips("sessAAAA") == []

    def test_unknown_session_reports_failure(self, tmp_path):
        store = MemoryStore(db_path=tmp_path / "m.db")
        org = SessionOrganizer(cache_path=tmp_path / "titles.json", store=store)
        result = org.delete_session("nope")
        assert result == {"success": False, "deleted_clips": 0}


# ── 7. Endpoints via TestClient ───────────────────────────────────────────────

class TestSessionEndpoints:
    def test_clip_sessions_and_delete(self, tmp_path, monkeypatch):
        pytest.importorskip("httpx")
        from fastapi.testclient import TestClient
        from voxa.server import create_api_server
        from voxa.memory.engine import memory_engine
        from voxa.memory.sessions import session_organizer

        store = MemoryStore(db_path=tmp_path / "m.db")
        _seed_two_sessions(store)

        # Drive the endpoints through the real singleton, but isolated: tmp store,
        # tmp title cache, patched title + meetings so nothing hits OpenAI/~/.voxa.
        monkeypatch.setattr(memory_engine, "store", store)
        monkeypatch.setattr(session_organizer, "_cache_path", tmp_path / "titles.json")
        session_organizer.reset()

        with patch.object(type(session_organizer), "_title_for", return_value="Test Title"), \
             patch("voxa.memory.meeting_manager.meeting_manager.list_meetings", return_value=[]):
            with TestClient(create_api_server()) as c:
                r = c.get("/api/memory/clip-sessions")
                assert r.status_code == 200
                body = r.json()
                assert body["count"] == 2
                assert [s["session_id"] for s in body["sessions"]] == ["sessBBBB", "sessAAAA"]
                first = body["sessions"][0]
                for key in ("title", "platform", "platform_kind", "started_iso",
                            "ended_iso", "duration_secs", "clip_count", "sources", "clips"):
                    assert key in first
                assert first["title"] == "Test Title"
                assert first["platform"] == "Microphone"
                assert first["platform_kind"] == "mic"

                # DELETE a session's clips.
                r = c.delete("/api/memory/session/sessAAAA")
                assert r.status_code == 200
                assert r.json() == {"success": True, "deleted_clips": 3}
                assert store.get_session_clips("sessAAAA") == []

                # Unknown session → success False.
                r = c.delete("/api/memory/session/ghost")
                assert r.json() == {"success": False, "deleted_clips": 0}
