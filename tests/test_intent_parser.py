"""
Tests for the Intent Parser module.
Verifies that natural language commands are correctly converted to action plans.
"""

import os
import sys
# pyrefly: ignore [missing-import]
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from voxa.intelligence.intent_parser import (
    parse_intent,
    ActionType,
    is_simple_command,
)


# ─── Unit Tests (no API calls) ──────────────────────────────────────────────────

class TestIsSimpleCommand:
    """Test the simple command classifier."""

    def test_open_app(self):
        assert is_simple_command("Open Chrome") is True

    def test_close_app(self):
        assert is_simple_command("Close Safari") is True

    def test_search(self):
        assert is_simple_command("Search for Python tutorials") is True

    def test_multi_step(self):
        assert is_simple_command("Open Chrome and search for music") is False

    def test_complex(self):
        assert is_simple_command("Open Chrome then go to YouTube and play lo-fi music") is False

    def test_go_to(self):
        assert is_simple_command("Go to github.com") is True

    def test_play(self):
        assert is_simple_command("Play music") is True


# ─── Integration Tests (require API key) ────────────────────────────────────────

_API_KEY = os.getenv("OPENAI_API_KEY", "")
_SKIP_INTEGRATION = (
    not _API_KEY
    or _API_KEY == "sk-your-key-here"
    or _API_KEY.startswith("sk-test-")
)

@pytest.mark.skipif(_SKIP_INTEGRATION, reason="OPENAI_API_KEY not set or is a placeholder")
class TestIntentParsing:
    """Integration tests that call the OpenAI API."""

    def test_open_app(self):
        plan = parse_intent("Open Google Chrome")
        assert plan is not None
        assert len(plan.actions) >= 1
        assert plan.actions[0].action == ActionType.OPEN_APP
        assert "chrome" in plan.actions[0].app.lower()

    def test_open_url(self):
        plan = parse_intent("Go to github.com")
        assert plan is not None
        assert any(a.action in (ActionType.OPEN_URL, ActionType.BROWSER_NAVIGATE)
                   for a in plan.actions)

    def test_multi_step(self):
        plan = parse_intent("Open Chrome and search YouTube for coding music")
        assert plan is not None
        assert len(plan.actions) >= 2

    def test_close_app(self):
        plan = parse_intent("Close Safari")
        assert plan is not None
        assert any(a.action == ActionType.CLOSE_APP for a in plan.actions)

    def test_shell_command(self):
        plan = parse_intent("Run ls in the terminal")
        assert plan is not None
        assert any(a.action == ActionType.SHELL_COMMAND for a in plan.actions)

    def test_has_confirmation(self):
        plan = parse_intent("Open Finder")
        assert plan is not None
        assert plan.confirmation  # Should have a confirmation message

    def test_has_thought(self):
        plan = parse_intent("Open Chrome and play lo-fi music on YouTube")
        assert plan is not None
        assert plan.thought  # Should have reasoning

    def test_maps_search(self):
        plan = parse_intent("Show me the Eiffel Tower on maps")
        assert plan is not None
        assert any(a.action == ActionType.MAPS_SEARCH for a in plan.actions)

    def test_maps_directions(self):
        plan = parse_intent("Directions from Delhi to Mumbai")
        assert plan is not None
        assert any(a.action == ActionType.MAPS_DIRECTIONS for a in plan.actions)

    def test_maps_distance_phrase(self):
        plan = parse_intent("How far is Bangalore from Mysore")
        assert plan is not None
        assert any(a.action == ActionType.MAPS_DIRECTIONS for a in plan.actions)
