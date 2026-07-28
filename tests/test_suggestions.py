"""Tests for proactive 'add to calendar?' suggestions."""
from unittest.mock import MagicMock, patch

import pytest

from voxa.memory.suggestions import SuggestionManager

# A representative extraction result, as _extract would return it.
_EVENT = {
    "has_event": True,
    "title": "Sync with Sam",
    "start": "2026-07-24T15:00:00",
    "end": "2026-07-24T16:00:00",
    "location": "",
}

# A chunk that trips the keyword gate ("meet", "friday").
_CHUNK = "let's meet friday at 3"


def _mgr_with_events():
    """A fresh (non-singleton) manager with a capturing notifier."""
    sm = SuggestionManager()
    events = []
    sm.set_notifier(lambda e, d: events.append((e, d)))
    return sm, events


class TestKeywordGate:
    def test_non_scheduling_text_skips_extract(self):
        sm, events = _mgr_with_events()
        with patch.object(sm, "_extract") as extract:
            result = sm.analyze_chunk("the weather is nice today")
        assert result is None
        extract.assert_not_called()
        assert events == []


class TestExtraction:
    def test_extraction_notifies_and_stores(self):
        sm, events = _mgr_with_events()
        with patch.object(sm, "_extract", return_value=dict(_EVENT)):
            payload = sm.analyze_chunk(_CHUNK)

        assert payload is not None
        assert len(events) == 1
        event, data = events[0]
        assert event == "meeting_suggestion"
        assert data["id"]
        assert data["title"] == "Sync with Sam"
        assert data["when_text"]                      # human-formatted when-text
        assert data["start_iso"] == "2026-07-24T15:00:00"
        assert len(sm.list_pending()) == 1

    def test_missing_end_defaults_to_start_plus_hour(self):
        sm, _ = _mgr_with_events()
        no_end = {**_EVENT, "end": ""}
        with patch.object(sm, "_extract", return_value=no_end):
            payload = sm.analyze_chunk(_CHUNK)
        assert payload["end_iso"] == "2026-07-24T16:00:00"


class TestDedup:
    def test_same_event_suggested_once(self):
        sm, events = _mgr_with_events()
        with patch.object(sm, "_extract", return_value=dict(_EVENT)):
            first = sm.analyze_chunk(_CHUNK)
            second = sm.analyze_chunk(_CHUNK)
        assert first is not None
        assert second is None
        assert len(events) == 1
        assert len(sm.list_pending()) == 1


class TestConfirm:
    def _seed(self):
        sm, _ = _mgr_with_events()
        with patch.object(sm, "_extract", return_value=dict(_EVENT)):
            sm.analyze_chunk(_CHUNK)
        return sm, sm.list_pending()[0]["id"]

    def test_accept_routes_through_dispatcher(self):
        from voxa.intelligence.intent_parser import ActionType

        sm, sid = self._seed()
        fake_result = {"success": True, "action": "calendar_create_event", "message": "Added"}
        with patch("voxa.actions.dispatcher.execute_action", return_value=fake_result) as exec_action:
            result = sm.confirm(sid, True)

        assert result["success"] is True
        assert sm.list_pending() == []               # removed from pending
        exec_action.assert_called_once()
        action = exec_action.call_args[0][0]
        assert action.action == ActionType.CALENDAR_CREATE_EVENT
        assert action.event_title == "Sync with Sam"
        assert action.event_start == "2026-07-24T15:00:00"

    def test_dismiss_does_not_call_dispatcher(self):
        sm, sid = self._seed()
        with patch("voxa.actions.dispatcher.execute_action") as exec_action:
            result = sm.confirm(sid, False)

        assert result["success"] is True
        assert result["action"] == "suggestion_dismissed"
        assert sm.list_pending() == []
        exec_action.assert_not_called()

    def test_unknown_id_reports_failure(self):
        sm, _ = _mgr_with_events()
        result = sm.confirm("nope", True)
        assert result["success"] is False


class TestSuggestionEndpoint:
    def test_confirm_endpoint_accepts_seeded_suggestion(self):
        pytest.importorskip("httpx")
        from fastapi.testclient import TestClient
        from voxa.server import create_api_server
        from voxa.memory.suggestions import suggestion_manager

        # Drive through the real module singleton (what the endpoint imports).
        # Use a no-op notifier so seeding doesn't schedule a WS broadcast onto a
        # stale loop left by an earlier test's TestClient.
        suggestion_manager.reset()
        suggestion_manager.set_notifier(lambda e, d: None)
        with patch.object(type(suggestion_manager), "_extract", return_value=dict(_EVENT)):
            suggestion_manager.analyze_chunk(_CHUNK, session_id="endpoint-test")
        sid = suggestion_manager.list_pending()[0]["id"]

        fake_result = {"success": True, "action": "calendar_create_event", "message": "Added"}
        try:
            with patch("voxa.actions.dispatcher.execute_action", return_value=fake_result):
                with TestClient(create_api_server()) as c:
                    r = c.post(
                        "/api/meeting/suggestion/confirm",
                        json={"suggestion_id": sid, "accept": True},
                    )
            assert r.status_code == 200
            assert r.json()["success"] is True
        finally:
            suggestion_manager.reset()
