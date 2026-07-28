"""Tests for the meeting consent (prompt → confirm) flow."""
from unittest.mock import MagicMock, patch

from voxa.memory.meeting_manager import MeetingManager


def _fake_engine():
    eng = MagicMock()
    eng.is_active = False
    eng._current_session_id = "sess1"
    return eng


def _mgr_with_events():
    mm = MeetingManager()
    events = []
    mm.set_notifier(lambda e, d: events.append((e, d)))
    return mm, events


MEETING = {"platform": "Zoom", "source": "app", "detail": "Zoom Meeting"}


class TestPromptFlow:
    def test_detect_prompts_without_recording(self):
        mm, events = _mgr_with_events()
        eng = _fake_engine()
        with patch("voxa.memory.engine.memory_engine", eng):
            mm._on_meeting_start(MEETING)
        # Prompt sent, but nothing recorded yet.
        assert mm.status["awaiting_confirmation"] is True
        assert mm.status["recording"] is False
        assert any(e == "meeting_detected" for e, _ in events)
        eng.start.assert_not_called()

    def test_confirm_yes_starts_recording(self):
        mm, _ = _mgr_with_events()
        eng = _fake_engine()
        with patch("voxa.memory.engine.memory_engine", eng):
            mm._on_meeting_start(MEETING)
            res = mm.confirm(True)
        assert res["recording"] is True
        assert mm.status["recording"] is True
        assert mm.status["awaiting_confirmation"] is False
        eng.start.assert_called_once()

    def test_confirm_no_does_not_record(self):
        mm, events = _mgr_with_events()
        eng = _fake_engine()
        with patch("voxa.memory.engine.memory_engine", eng):
            mm._on_meeting_start(MEETING)
            res = mm.confirm(False)
        assert res["recording"] is False
        assert mm.status["recording"] is False
        assert mm.status["awaiting_confirmation"] is False
        eng.start.assert_not_called()

    def test_confirm_with_no_pending(self):
        mm, _ = _mgr_with_events()
        res = mm.confirm(True)
        assert res["success"] is False


class TestRecordingControls:
    def _recording(self):
        mm, events = _mgr_with_events()
        eng = _fake_engine()
        with patch("voxa.memory.engine.memory_engine", eng):
            mm._on_meeting_start(MEETING)
            mm.confirm(True)
        return mm, eng, events

    def test_pause_and_resume(self):
        mm, eng, _ = self._recording()
        with patch("voxa.memory.engine.memory_engine", eng):
            r = mm.pause_recording()
            assert r["paused"] is True
            assert mm.status["paused"] is True
            assert mm.status["recording"] is False   # paused ≠ recording
            eng.pause.assert_called_once()

            r = mm.resume_recording()
            assert r["paused"] is False
            assert mm.status["recording"] is True
            eng.resume.assert_called_once()

    def test_end_saves_and_clears(self):
        mm, eng, _ = self._recording()
        with patch("voxa.memory.engine.memory_engine", eng), \
             patch.object(mm, "_build_notes", return_value={"summary": "notes"}), \
             patch.object(mm, "_append_meeting") as append:
            r = mm.end_recording()
        assert r["success"] is True
        assert mm.status["in_meeting"] is False
        eng.stop.assert_called_once()
        append.assert_called_once()

    def test_pause_without_meeting(self):
        mm, _ = _mgr_with_events()
        assert mm.pause_recording()["success"] is False
        assert mm.end_recording()["success"] is False


class TestAutoRecord:
    def test_auto_record_skips_prompt(self):
        mm, events = _mgr_with_events()
        eng = _fake_engine()
        with patch("voxa.config.config.MEETING_AUTO_RECORD", True), \
             patch("voxa.memory.engine.memory_engine", eng):
            mm._on_meeting_start(MEETING)
        assert mm.status["recording"] is True
        assert mm.status["awaiting_confirmation"] is False
        eng.start.assert_called_once()
        assert not any(e == "meeting_detected" for e, _ in events)
