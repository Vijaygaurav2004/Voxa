"""
Tests for Context & Memory module (voxa/intelligence/context.py).
Uses in-memory SQLite for CommandHistory — no disk writes.
"""
from __future__ import annotations

import json
import time
import pytest

from unittest.mock import patch

from voxa.intelligence.context import SessionContext, CommandHistory


# ─── SessionContext ───────────────────────────────────────────────────────────

class TestSessionContext:

    def test_initial_state_is_empty(self):
        ctx = SessionContext()
        assert ctx.history == []
        assert ctx.last_app is None
        assert ctx.last_url is None
        assert ctx.last_query is None

    def test_add_command_appends_history(self):
        ctx = SessionContext()
        ctx.add_command("Open Chrome", [{"action": "open_app", "app": "Chrome"}], "ok")
        assert len(ctx.history) == 1
        assert ctx.history[0]["input"] == "Open Chrome"

    def test_tracks_last_app(self):
        ctx = SessionContext()
        ctx.add_command("Open Finder", [{"action": "open_app", "app": "Finder"}], "ok")
        assert ctx.last_app == "Finder"

    def test_tracks_last_url(self):
        ctx = SessionContext()
        ctx.add_command("Visit site", [{"action": "open_url", "url": "https://google.com"}], "ok")
        assert ctx.last_url == "https://google.com"

    def test_tracks_last_query(self):
        ctx = SessionContext()
        ctx.add_command("Search Python", [{"action": "browser_search", "query": "Python"}], "ok")
        assert ctx.last_query == "Python"

    def test_tracks_last_file_path(self):
        ctx = SessionContext()
        ctx.add_command("Open file", [{"action": "file_open", "path": "/tmp/test.txt"}], "ok")
        assert ctx.last_file_path == "/tmp/test.txt"

    def test_history_capped_at_20(self):
        ctx = SessionContext()
        for i in range(25):
            ctx.add_command(f"Cmd {i}", [], "ok")
        assert len(ctx.history) == 20

    def test_history_keeps_latest_entries(self):
        ctx = SessionContext()
        for i in range(25):
            ctx.add_command(f"Cmd {i}", [], "ok")
        assert ctx.history[0]["input"] == "Cmd 5"
        assert ctx.history[-1]["input"] == "Cmd 24"

    def test_get_context_empty(self):
        ctx = SessionContext()
        result = ctx.get_context_for_llm()
        assert "no previous commands" in result.lower()

    def test_get_context_contains_input(self):
        ctx = SessionContext()
        ctx.add_command("Open Terminal", [{"action": "open_app", "app": "Terminal"}], "success")
        result = ctx.get_context_for_llm()
        assert "Open Terminal" in result

    def test_get_context_respects_n(self):
        ctx = SessionContext()
        for i in range(10):
            ctx.add_command(f"Cmd {i}", [], "ok")
        result = ctx.get_context_for_llm(n=2)
        assert "Cmd 9" in result
        assert "Cmd 8" in result
        assert "Cmd 6" not in result

    def test_clear_resets_everything(self):
        ctx = SessionContext()
        ctx.add_command("Open Chrome", [{"action": "open_app", "app": "Chrome"}], "ok")
        ctx.clear()
        assert ctx.history == []
        assert ctx.last_app is None

    def test_last_app_updates_with_each_command(self):
        ctx = SessionContext()
        ctx.add_command("Open Chrome", [{"action": "open_app", "app": "Chrome"}], "ok")
        ctx.add_command("Open Safari", [{"action": "open_app", "app": "Safari"}], "ok")
        assert ctx.last_app == "Safari"

    def test_history_entry_has_timestamp(self):
        ctx = SessionContext()
        ctx.add_command("Test", [], "ok")
        assert "timestamp" in ctx.history[0]

    def test_session_start_set_on_creation(self):
        before = time.time()
        ctx = SessionContext()
        assert ctx.session_start >= before


# ─── CommandHistory (SQLite) ──────────────────────────────────────────────────

@pytest.fixture
def history(tmp_path):
    """Fresh CommandHistory backed by a temp file for each test."""
    db_file = str(tmp_path / "test_history.db")
    return CommandHistory(db_path=db_file)


class TestCommandHistory:

    def test_init_creates_table(self, history):
        assert isinstance(history.get_recent(10), list)

    def test_record_and_retrieve(self, history):
        history.record("Open Chrome", [{"action": "open_app"}], "success", 120)
        rows = history.get_recent(1)
        assert rows[0]["user_input"] == "Open Chrome"

    def test_get_recent_respects_limit(self, history):
        for i in range(10):
            history.record(f"Cmd {i}", [], "ok", 100)
        assert len(history.get_recent(3)) == 3

    def test_get_recent_most_recent_first(self, history):
        history.record("First", [], "ok", 100)
        history.record("Second", [], "ok", 100)
        assert history.get_recent(2)[0]["user_input"] == "Second"

    def test_stats_total_count(self, history):
        for _ in range(5):
            history.record("cmd", [], "ok", 100, success=True)
        assert history.get_stats()["total_commands"] == 5

    def test_stats_success_failure_split(self, history):
        history.record("good", [], "ok", 100, success=True)
        history.record("bad", [], "fail", 100, success=False)
        stats = history.get_stats()
        assert stats["successful"] == 1
        assert stats["failed"] == 1

    def test_stats_success_rate(self, history):
        for _ in range(4):
            history.record("cmd", [], "ok", 100, success=True)
        history.record("bad", [], "fail", 100, success=False)
        assert history.get_stats()["success_rate"] == "80.0%"

    def test_stats_empty_db(self, history):
        assert history.get_stats()["success_rate"] == "N/A"

    def test_avg_duration(self, history):
        history.record("a", [], "ok", 100)
        history.record("b", [], "ok", 200)
        assert history.get_stats()["avg_duration_ms"] == 150

    def test_actions_json_round_trip(self, history):
        actions = [{"action": "open_app", "app": "Chrome"}]
        history.record("test", actions, "ok", 100)
        row = history.get_recent(1)[0]
        assert json.loads(row["actions_json"]) == actions
