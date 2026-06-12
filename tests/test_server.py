"""
Tests for the Voxa API Server.
Tests the HTTP endpoints that the Swift app communicates with.
"""
import pytest
import json
from unittest.mock import patch, MagicMock

# Skip if httpx is not available
httpx = pytest.importorskip("httpx")


@pytest.fixture
def client():
    """Create a test client for the API server."""
    from voxa.server import create_api_server
    from fastapi.testclient import TestClient

    app = create_api_server()
    return TestClient(app)


class TestHealthEndpoint:
    """Test /api/health endpoint."""

    def test_health_returns_ok(self, client):
        response = client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["version"] == "2.0.0"
        assert "timestamp" in data
        assert "config" in data

    def test_health_includes_config(self, client):
        response = client.get("/api/health")
        data = response.json()
        assert "llm_model" in data["config"]
        assert "whisper_model" in data["config"]
        assert "wake_word" in data["config"]


class TestIntentEndpoint:
    """Test /api/intent endpoint."""

    @patch("voxa.intelligence.intent_parser.parse_intent_with_retry")
    def test_parse_intent_success(self, mock_parse, client):
        from voxa.intelligence.intent_parser import ActionPlan, Action, ActionType

        mock_plan = ActionPlan(
            thought="User wants to open Chrome",
            actions=[
                Action(action=ActionType.OPEN_APP, app="Google Chrome", description="Open Chrome")
            ],
            confirmation="Opening Chrome"
        )
        mock_parse.return_value = mock_plan

        response = client.post("/api/intent", json={
            "text": "open Chrome",
            "context": "",
        })
        assert response.status_code == 200
        data = response.json()
        assert "plan" in data
        assert "elapsed_ms" in data
        assert data["plan"]["confirmation"] == "Opening Chrome"

    @patch("voxa.intelligence.intent_parser.parse_intent_with_retry")
    def test_parse_intent_failure(self, mock_parse, client):
        mock_parse.return_value = None

        response = client.post("/api/intent", json={
            "text": "asdfgjkl",
            "context": "",
        })
        assert response.status_code == 422

    def test_parse_intent_missing_text(self, client):
        response = client.post("/api/intent", json={})
        assert response.status_code == 422


class TestExecuteEndpoint:
    """Test /api/execute endpoint."""

    @patch("voxa.actions.dispatcher.execute_python_only")
    def test_execute_python_only(self, mock_exec, client):
        mock_exec.return_value = [
            {"success": True, "action": "browser_search", "message": "Searched Google"}
        ]

        plan = {
            "thought": "Search Google",
            "actions": [{
                "action": "browser_search",
                "query": "Python tutorials",
                "description": "Search Google for Python tutorials"
            }],
            "confirmation": "Searching Google"
        }

        response = client.post("/api/execute", json={
            "plan": plan,
            "python_only": True,
        })
        assert response.status_code == 200
        data = response.json()
        assert data["success_count"] == 1
        assert data["total"] == 1


class TestContextEndpoint:
    """Test /api/context endpoint."""

    def test_get_context(self, client):
        response = client.get("/api/context")
        assert response.status_code == 200
        data = response.json()
        assert "context_text" in data

    def test_clear_context(self, client):
        response = client.post("/api/context/clear")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True


class TestConfigEndpoint:
    """Test /api/config endpoint."""

    def test_get_config(self, client):
        response = client.get("/api/config")
        assert response.status_code == 200
        data = response.json()
        assert "wake_word" in data
        assert "llm_model" in data
        assert "whisper_model" in data
        # API key should NOT be exposed
        assert "openai_api_key" not in data
        assert "OPENAI_API_KEY" not in data


class TestSkillsEndpoint:
    """Test /api/skills endpoint."""

    def test_get_skills(self, client):
        response = client.get("/api/skills")
        assert response.status_code == 200
        data = response.json()
        assert "skills" in data
        assert "count" in data

    def test_match_skill_no_match(self, client):
        response = client.post("/api/skills/match", json={"text": "random gibberish 12345"})
        assert response.status_code == 200
        data = response.json()
        assert data["matched"] is False


class TestTimersEndpoint:
    """Test /api/timers endpoint."""

    def test_get_timers(self, client):
        response = client.get("/api/timers")
        assert response.status_code == 200

    def test_set_timer(self, client):
        response = client.post("/api/timers", json={
            "duration_seconds": 5.0,
            "label": "Test timer",
            "name": "test-timer-api",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

        # Clean up
        client.delete("/api/timers/test-timer-api")


class TestHistoryEndpoint:
    """Test /api/history endpoint."""

    def test_get_history(self, client):
        response = client.get("/api/history")
        assert response.status_code == 200
        data = response.json()
        assert "history" in data
        assert "count" in data

    def test_get_stats(self, client):
        response = client.get("/api/stats")
        assert response.status_code == 200
        data = response.json()
        assert "total_commands" in data
        assert "success_rate" in data


class TestActionClassification:
    """Test action classification (Swift vs Python)."""

    def test_swift_actions_classified_correctly(self):
        from voxa.intelligence.intent_parser import Action, ActionType, classify_action

        swift_types = [
            ActionType.OPEN_APP, ActionType.CLOSE_APP,
            ActionType.SYSTEM_VOLUME, ActionType.TYPE_TEXT,
            ActionType.KEYSTROKE, ActionType.CLIPBOARD_GET,
            ActionType.MEDIA_PLAY_PAUSE, ActionType.SCREENSHOT,
        ]
        for at in swift_types:
            assert classify_action(at) == "swift", f"{at} should be swift"

    def test_python_actions_classified_correctly(self):
        from voxa.intelligence.intent_parser import Action, ActionType, classify_action

        python_types = [
            ActionType.BROWSER_SEARCH, ActionType.PLAY_YOUTUBE,
            ActionType.SCREEN_READ, ActionType.VISION_CLICK,
            ActionType.CHROME_NEW_TAB, ActionType.SHELL_COMMAND,
            ActionType.SET_TIMER, ActionType.EMAIL_COMPOSE,
        ]
        for at in python_types:
            assert classify_action(at) == "python", f"{at} should be python"

    def test_action_auto_classifies_on_creation(self):
        from voxa.intelligence.intent_parser import Action, ActionType

        action = Action(action=ActionType.OPEN_APP, app="Chrome", description="Open Chrome")
        assert action.execution_target == "swift"

        action2 = Action(action=ActionType.BROWSER_SEARCH, query="test", description="Search")
        assert action2.execution_target == "python"
