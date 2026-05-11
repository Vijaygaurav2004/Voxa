"""
Tests for the Dispatcher module (voxa/actions/dispatcher.py).
All macOS side-effects (AppleScript, subprocess, TTS) are mocked.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from voxa.intelligence.intent_parser import Action, ActionType, ActionPlan
from voxa.actions import dispatcher


# ─── Fixtures ─────────────────────────────────────────────────────────────────

def _make_action(action_type: ActionType, **kwargs) -> Action:
    return Action(action=action_type, description="test", **kwargs)


def _make_plan(*actions: Action, confirmation="ok") -> ActionPlan:
    return ActionPlan(thought="thinking", actions=list(actions), confirmation=confirmation)


# ─── execute_action: WAIT ─────────────────────────────────────────────────────

class TestExecuteWait:
    def test_wait_returns_success(self):
        action = _make_action(ActionType.WAIT, delay_seconds=0.01)
        result = dispatcher.execute_action(action)
        assert result["success"] is True

    def test_wait_uses_default_delay(self):
        action = _make_action(ActionType.WAIT)  # delay_seconds=None → defaults to 1.0
        with patch("time.sleep") as mock_sleep:
            dispatcher.execute_action(action)
            mock_sleep.assert_called_with(1.0)

    def test_wait_message_contains_duration(self):
        action = _make_action(ActionType.WAIT, delay_seconds=2.5)
        with patch("time.sleep"):
            result = dispatcher.execute_action(action)
        assert "2.5" in result["message"]


# ─── execute_action: SPEAK ────────────────────────────────────────────────────

class TestExecuteSpeak:
    def test_speak_calls_tts(self):
        action = _make_action(ActionType.SPEAK, text="Hello world")
        with patch("voxa.actions.dispatcher.speak_confirmation") as mock_speak:
            result = dispatcher.execute_action(action)
            mock_speak.assert_called_once_with("Hello world")
        assert result["success"] is True

    def test_speak_falls_back_to_description(self):
        action = Action(action=ActionType.SPEAK, description="fallback text", text=None)
        with patch("voxa.actions.dispatcher.speak_confirmation") as mock_speak:
            dispatcher.execute_action(action)
            mock_speak.assert_called_once_with("fallback text")


# ─── execute_action routing ───────────────────────────────────────────────────

class TestActionRouting:
    """Verify each action type routes to the correct handler function."""

    def test_open_app_routes_correctly(self):
        action = _make_action(ActionType.OPEN_APP, app="Chrome")
        with patch("voxa.actions.computer_control.open_any_app", return_value={"success": True, "message": ""}) as m:
            dispatcher.execute_action(action)
            m.assert_called_once_with("Chrome")

    def test_close_app_routes_correctly(self):
        action = _make_action(ActionType.CLOSE_APP, app="Safari")
        with patch("voxa.actions.app_control.close_app", return_value={"success": True, "message": ""}) as m:
            dispatcher.execute_action(action)
            m.assert_called_once_with("Safari")

    def test_browser_search_routes_to_google(self):
        action = _make_action(ActionType.BROWSER_SEARCH, query="test query")
        with patch("voxa.actions.browser.search_google", return_value={"success": True, "message": ""}) as m:
            dispatcher.execute_action(action)
            m.assert_called_once_with("test query")

    def test_browser_search_youtube_routes_to_youtube(self):
        action = _make_action(ActionType.BROWSER_SEARCH, query="python tutorial on youtube")
        with patch("voxa.actions.browser.search_youtube", return_value={"success": True, "message": ""}) as m:
            dispatcher.execute_action(action)
            m.assert_called_once()

    def test_type_text_routes_correctly(self):
        action = _make_action(ActionType.TYPE_TEXT, text="hello")
        with patch("voxa.actions.typing.type_text", return_value={"success": True, "message": ""}) as m:
            dispatcher.execute_action(action)
            m.assert_called_once_with("hello")

    def test_shell_command_routes_correctly(self):
        action = _make_action(ActionType.SHELL_COMMAND, command="echo hi")
        with patch("voxa.actions.shell.execute_command", return_value={"success": True, "message": ""}) as m:
            dispatcher.execute_action(action)
            m.assert_called_once_with("echo hi")

    def test_clipboard_get_routes_correctly(self):
        action = _make_action(ActionType.CLIPBOARD_GET)
        with patch("voxa.actions.clipboard.get_clipboard", return_value={"success": True, "message": ""}) as m:
            dispatcher.execute_action(action)
            m.assert_called_once()

    def test_set_timer_routes_correctly(self):
        action = _make_action(ActionType.SET_TIMER, duration_seconds=60, reminder_text="Done!")
        with patch("voxa.actions.timers.set_timer", return_value={"success": True, "message": ""}) as m:
            dispatcher.execute_action(action)
            m.assert_called_once()

    def test_media_play_pause_routes_correctly(self):
        action = _make_action(ActionType.MEDIA_PLAY_PAUSE, media_app="Spotify")
        with patch("voxa.actions.media_control.play_pause", return_value={"success": True, "message": ""}) as m:
            dispatcher.execute_action(action)
            m.assert_called_once_with(app="Spotify")

    def test_system_volume_routes_correctly(self):
        action = _make_action(ActionType.SYSTEM_VOLUME, level=50)
        with patch("voxa.actions.system_control.set_volume", return_value={"success": True, "message": ""}) as m:
            dispatcher.execute_action(action)
            m.assert_called_once()

    def test_unknown_action_returns_failure(self):
        # Create an action with a fake enum that has a .value attribute
        action = _make_action(ActionType.WAIT, delay_seconds=0)
        fake_enum = MagicMock()
        fake_enum.value = "completely_unknown_type"
        object.__setattr__(action, "action", fake_enum)
        result = dispatcher.execute_action(action)
        assert result["success"] is False


# ─── execute_plan ─────────────────────────────────────────────────────────────

class TestExecutePlan:
    def test_empty_plan_returns_empty_results(self):
        plan = _make_plan()
        with patch("voxa.actions.dispatcher.speak_confirmation"):
            results = dispatcher.execute_plan(plan)
        assert results == []

    def test_all_success_returns_all_results(self):
        a1 = _make_action(ActionType.WAIT, delay_seconds=0.01)
        a2 = _make_action(ActionType.WAIT, delay_seconds=0.01)
        plan = _make_plan(a1, a2)
        with patch("time.sleep"):
            results = dispatcher.execute_plan(plan)
        assert len(results) == 2
        assert all(r["success"] for r in results)

    def test_fatal_error_aborts_remaining_steps(self):
        a1 = _make_action(ActionType.WAIT, delay_seconds=0.01)
        a2 = _make_action(ActionType.WAIT, delay_seconds=0.01)
        plan = _make_plan(a1, a2)

        call_count = 0

        def fake_execute(action):
            nonlocal call_count
            call_count += 1
            return {"success": False, "fatal": True, "message": "fatal error"}

        with patch("voxa.actions.dispatcher.execute_action_with_retry", side_effect=fake_execute):
            results = dispatcher.execute_plan(plan)

        assert call_count == 1  # Aborted after step 1

    def test_non_fatal_error_continues_execution(self):
        a1 = _make_action(ActionType.WAIT, delay_seconds=0.01)
        a2 = _make_action(ActionType.WAIT, delay_seconds=0.01)
        plan = _make_plan(a1, a2)

        call_count = 0

        def fake_execute(action):
            nonlocal call_count
            call_count += 1
            return {"success": False, "fatal": False, "message": "soft error"}

        with patch("voxa.actions.dispatcher.execute_action_with_retry", side_effect=fake_execute):
            results = dispatcher.execute_plan(plan)

        assert call_count == 2  # Continued after soft failure

    def test_on_step_callback_is_called(self):
        a1 = _make_action(ActionType.WAIT, delay_seconds=0.01)
        plan = _make_plan(a1)
        calls = []

        with patch("time.sleep"):
            dispatcher.execute_plan(plan, on_step=lambda i, a, r: calls.append(i))

        assert calls == [0]

    def test_speak_result_actions_trigger_tts(self):
        action = _make_action(ActionType.SYSTEM_BATTERY)
        plan = _make_plan(action)

        with patch("voxa.actions.system_control.get_battery_status",
                   return_value={"success": True, "message": "Battery at 80%"}):
            with patch("voxa.actions.dispatcher.speak_confirmation") as mock_speak:
                dispatcher.execute_plan(plan)
                mock_speak.assert_called_once_with("Battery at 80%")


# ─── execute_action_with_retry ────────────────────────────────────────────────

class TestRetryLogic:
    def test_no_retry_on_success(self):
        action = _make_action(ActionType.WAIT, delay_seconds=0)
        call_count = 0

        def fake_execute(a):
            nonlocal call_count
            call_count += 1
            return {"success": True, "message": "ok"}

        with patch("voxa.actions.dispatcher.execute_action", side_effect=fake_execute):
            with patch("time.sleep"):
                dispatcher.execute_action_with_retry(action, max_retries=2)

        assert call_count == 1

    def test_retries_on_failure(self):
        action = _make_action(ActionType.WAIT, delay_seconds=0)
        call_count = 0

        def fake_execute(a):
            nonlocal call_count
            call_count += 1
            return {"success": False, "message": "transient failure"}

        with patch("voxa.actions.dispatcher.execute_action", side_effect=fake_execute):
            with patch("time.sleep"):
                dispatcher.execute_action_with_retry(action, max_retries=2)

        assert call_count == 3  # initial + 2 retries

    def test_no_retry_on_dangerous(self):
        action = _make_action(ActionType.SHELL_COMMAND, command="rm -rf /")
        call_count = 0

        def fake_execute(a):
            nonlocal call_count
            call_count += 1
            return {"success": False, "dangerous": True, "message": "Blocked"}

        with patch("voxa.actions.dispatcher.execute_action", side_effect=fake_execute):
            dispatcher.execute_action_with_retry(action, max_retries=2)

        assert call_count == 1

    def test_no_retry_on_not_found(self):
        action = _make_action(ActionType.OPEN_APP, app="Nonexistent")
        call_count = 0

        def fake_execute(a):
            nonlocal call_count
            call_count += 1
            return {"success": False, "message": "app not found"}

        with patch("voxa.actions.dispatcher.execute_action", side_effect=fake_execute):
            dispatcher.execute_action_with_retry(action, max_retries=2)

        assert call_count == 1
