"""
Tests for the Custom Skills module (voxa/skills/custom_skills.py).
No YAML file I/O — skills are injected directly into the manager.
"""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

from voxa.skills.custom_skills import SkillManager, _parse_skill_action


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _make_manager(*skills) -> SkillManager:
    """Create a SkillManager with skills injected (no YAML load)."""
    mgr = SkillManager.__new__(SkillManager)
    mgr.skills_path = None
    mgr.skills = list(skills)
    return mgr


# ─── match_skill ──────────────────────────────────────────────────────────────

class TestMatchSkill:

    def test_exact_match(self):
        mgr = _make_manager({"name": "test", "trigger": "open my editor"})
        result = mgr.match_skill("open my editor")
        assert result is not None
        assert result["name"] == "test"

    def test_case_insensitive_match(self):
        mgr = _make_manager({"name": "test", "trigger": "open my editor"})
        assert mgr.match_skill("OPEN MY EDITOR") is not None

    def test_starts_with_match(self):
        mgr = _make_manager({"name": "test", "trigger": "open"})
        assert mgr.match_skill("open chrome now") is not None

    def test_no_match_returns_none(self):
        mgr = _make_manager({"name": "test", "trigger": "open my editor"})
        assert mgr.match_skill("close everything") is None

    def test_empty_skills_returns_none(self):
        mgr = _make_manager()
        assert mgr.match_skill("open chrome") is None

    def test_wildcard_match(self):
        mgr = _make_manager({"name": "play music", "trigger": "play * on spotify"})
        assert mgr.match_skill("play jazz on spotify") is not None

    def test_wildcard_no_match(self):
        mgr = _make_manager({"name": "play music", "trigger": "play * on spotify"})
        assert mgr.match_skill("play jazz on youtube") is None

    def test_empty_trigger_is_skipped(self):
        mgr = _make_manager({"name": "broken", "trigger": ""})
        assert mgr.match_skill("anything") is None

    def test_first_match_returned(self):
        mgr = _make_manager(
            {"name": "first", "trigger": "open"},
            {"name": "second", "trigger": "open"},
        )
        result = mgr.match_skill("open something")
        assert result["name"] == "first"

    def test_leading_trailing_whitespace_ignored(self):
        mgr = _make_manager({"name": "test", "trigger": "open editor"})
        assert mgr.match_skill("  open editor  ") is not None


# ─── skill_count & list_skills ───────────────────────────────────────────────

class TestSkillManagerMeta:

    def test_skill_count(self):
        mgr = _make_manager(
            {"name": "a", "trigger": "x"},
            {"name": "b", "trigger": "y"},
        )
        assert mgr.skill_count == 2

    def test_list_skills(self):
        mgr = _make_manager(
            {"name": "Alpha", "trigger": "x"},
            {"name": "Beta", "trigger": "y"},
        )
        assert mgr.list_skills() == ["Alpha", "Beta"]

    def test_list_skills_unnamed(self):
        mgr = _make_manager({"trigger": "x"})  # No "name" key
        assert mgr.list_skills() == ["unnamed"]

    def test_empty_manager(self):
        mgr = _make_manager()
        assert mgr.skill_count == 0
        assert mgr.list_skills() == []


# ─── _parse_skill_action ──────────────────────────────────────────────────────

class TestParseSkillAction:
    from voxa.intelligence.intent_parser import ActionType

    def test_open_app(self):
        from voxa.intelligence.intent_parser import ActionType
        result = _parse_skill_action({"open_app": "Chrome"})
        assert result is not None
        assert result.action == ActionType.OPEN_APP
        assert result.app == "Chrome"

    def test_close_app(self):
        from voxa.intelligence.intent_parser import ActionType
        result = _parse_skill_action({"close_app": "Safari"})
        assert result.action == ActionType.CLOSE_APP

    def test_open_url(self):
        from voxa.intelligence.intent_parser import ActionType
        result = _parse_skill_action({"open_url": "https://github.com"})
        assert result.action == ActionType.OPEN_URL
        assert result.url == "https://github.com"

    def test_search(self):
        from voxa.intelligence.intent_parser import ActionType
        result = _parse_skill_action({"search": "python tips"})
        assert result.action == ActionType.BROWSER_SEARCH
        assert result.query == "python tips"

    def test_type_text(self):
        from voxa.intelligence.intent_parser import ActionType
        result = _parse_skill_action({"type_text": "hello world"})
        assert result.action == ActionType.TYPE_TEXT
        assert result.text == "hello world"

    def test_keystroke(self):
        from voxa.intelligence.intent_parser import ActionType
        result = _parse_skill_action({"keystroke": "cmd+s"})
        assert result.action == ActionType.KEYSTROKE
        assert result.keys == "cmd+s"

    def test_shell(self):
        from voxa.intelligence.intent_parser import ActionType
        result = _parse_skill_action({"shell": "ls -la"})
        assert result.action == ActionType.SHELL_COMMAND
        assert result.command == "ls -la"

    def test_wait(self):
        from voxa.intelligence.intent_parser import ActionType
        result = _parse_skill_action({"wait": 2})
        assert result.action == ActionType.WAIT
        assert result.delay_seconds == 2.0

    def test_speak(self):
        from voxa.intelligence.intent_parser import ActionType
        result = _parse_skill_action({"speak": "Hello there!"})
        assert result.action == ActionType.SPEAK
        assert result.text == "Hello there!"

    def test_play_youtube(self):
        from voxa.intelligence.intent_parser import ActionType
        result = _parse_skill_action({"play_youtube": "lo-fi music"})
        assert result.action == ActionType.PLAY_YOUTUBE
        assert result.query == "lo-fi music"

    def test_screenshot(self):
        from voxa.intelligence.intent_parser import ActionType
        result = _parse_skill_action({"screenshot": True})
        assert result.action == ActionType.SCREENSHOT

    def test_unknown_action_returns_none(self):
        result = _parse_skill_action({"totally_unknown": "value"})
        assert result is None
