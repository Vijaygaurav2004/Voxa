"""
Tests for the Timer module (voxa/actions/timers.py).
All tests are pure-unit — no macOS APIs are touched.
"""
from __future__ import annotations

import time
import threading
import pytest

from voxa.actions import timers as timer_mod


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _clear_timers():
    """Reset global timer registry between tests."""
    with timer_mod._timers_lock:
        timer_mod._timers.clear()


@pytest.fixture(autouse=True)
def reset_timers():
    _clear_timers()
    yield
    _clear_timers()


# ─── set_timer ────────────────────────────────────────────────────────────────

class TestSetTimer:
    def test_returns_success(self):
        result = timer_mod.set_timer(10, label="Test")
        assert result["success"] is True
        assert result["action"] == "set_timer"

    def test_returns_timer_name(self):
        result = timer_mod.set_timer(10)
        assert "timer_name" in result
        assert result["timer_name"]

    def test_custom_name(self):
        result = timer_mod.set_timer(10, name="my_timer")
        assert result["timer_name"] == "my_timer"

    def test_rejects_zero_duration(self):
        result = timer_mod.set_timer(0)
        assert result["success"] is False

    def test_rejects_negative_duration(self):
        result = timer_mod.set_timer(-5)
        assert result["success"] is False

    def test_timer_registered_in_registry(self):
        timer_mod.set_timer(60, name="reg_test")
        assert "reg_test" in timer_mod._timers

    def test_duration_str_seconds(self):
        result = timer_mod.set_timer(45)
        assert "45 seconds" in result["message"]

    def test_duration_str_minutes(self):
        result = timer_mod.set_timer(120)
        assert "2 minutes" in result["message"]

    def test_duration_str_hours(self):
        result = timer_mod.set_timer(3600)
        assert "1h" in result["message"]

    def test_multiple_timers_unique_names(self):
        r1 = timer_mod.set_timer(60, name="t1")
        r2 = timer_mod.set_timer(60, name="t2")
        assert r1["timer_name"] != r2["timer_name"]
        assert timer_mod.get_active_timer_count() == 2

    def test_custom_label_propagated(self):
        result = timer_mod.set_timer(60, label="Drink water!")
        # The label should appear in the registry
        name = result["timer_name"]
        assert timer_mod._timers[name]["label"] == "Drink water!"


# ─── cancel_timer ─────────────────────────────────────────────────────────────

class TestCancelTimer:
    def test_cancel_named_timer(self):
        timer_mod.set_timer(60, name="cancel_me")
        result = timer_mod.cancel_timer(name="cancel_me")
        assert result["success"] is True
        assert "cancel_me" not in timer_mod._timers

    def test_cancel_most_recent_when_no_name(self):
        timer_mod.set_timer(60, name="aaa")
        result = timer_mod.cancel_timer()
        assert result["success"] is True
        assert timer_mod.get_active_timer_count() == 0

    def test_cancel_nonexistent_name_falls_back_to_latest(self):
        timer_mod.set_timer(60, name="only_one")
        result = timer_mod.cancel_timer(name="nonexistent")
        # Should fall back to cancelling latest
        assert result["success"] is True

    def test_cancel_when_no_timers(self):
        result = timer_mod.cancel_timer()
        assert result["success"] is False
        assert "no active" in result["message"].lower()

    def test_cancel_flag_set(self):
        timer_mod.set_timer(60, name="flag_test")
        cancel_flag = timer_mod._timers["flag_test"]["cancel_flag"]
        timer_mod.cancel_timer(name="flag_test")
        assert cancel_flag["cancelled"] is True


# ─── list_timers ──────────────────────────────────────────────────────────────

class TestListTimers:
    def test_empty_returns_success(self):
        result = timer_mod.list_timers()
        assert result["success"] is True
        assert result["timers"] == []
        assert "no active" in result["message"].lower()

    def test_single_timer_listed(self):
        timer_mod.set_timer(120, name="list_me", label="Test label")
        result = timer_mod.list_timers()
        assert len(result["timers"]) == 1
        assert result["timers"][0]["name"] == "list_me"

    def test_remaining_time_is_positive(self):
        timer_mod.set_timer(60, name="remaining_check")
        result = timer_mod.list_timers()
        assert result["timers"][0]["remaining_seconds"] > 0

    def test_multiple_timers(self):
        timer_mod.set_timer(60, name="a")
        timer_mod.set_timer(120, name="b")
        result = timer_mod.list_timers()
        assert len(result["timers"]) == 2

    def test_remaining_str_seconds_format(self):
        timer_mod.set_timer(30, name="secs")
        result = timer_mod.list_timers()
        # Remaining should be something like "29s" or "30s"
        assert "s" in result["timers"][0]["remaining_str"]


# ─── get_active_timer_count ───────────────────────────────────────────────────

class TestGetActiveTimerCount:
    def test_zero_when_empty(self):
        assert timer_mod.get_active_timer_count() == 0

    def test_increments_with_each_timer(self):
        timer_mod.set_timer(60, name="c1")
        timer_mod.set_timer(60, name="c2")
        assert timer_mod.get_active_timer_count() == 2

    def test_decrements_after_cancel(self):
        timer_mod.set_timer(60, name="dec")
        timer_mod.cancel_timer(name="dec")
        assert timer_mod.get_active_timer_count() == 0


# ─── Timer fires (fast integration) ──────────────────────────────────────────

class TestTimerFires:
    def test_timer_fires_and_calls_speak(self):
        fired = threading.Event()
        spoken = []

        def fake_speak(msg):
            spoken.append(msg)
            fired.set()

        timer_mod.set_speak_fn(fake_speak)
        timer_mod.set_timer(0.2, label="Fire test!")

        assert fired.wait(timeout=3), "Timer did not fire within 3 seconds"
        assert "Fire test!" in spoken[0]

        # Cleanup
        timer_mod.set_speak_fn(None)

    def test_cancelled_timer_does_not_fire(self):
        fired = threading.Event()

        def fake_speak(msg):
            fired.set()

        timer_mod.set_speak_fn(fake_speak)
        timer_mod.set_timer(0.3, name="cancel_early")
        timer_mod.cancel_timer(name="cancel_early")

        # Wait longer than the timer duration
        assert not fired.wait(timeout=1), "Cancelled timer should not fire"
        timer_mod.set_speak_fn(None)

    def test_timer_removed_from_registry_after_firing(self):
        fired = threading.Event()
        timer_mod.set_speak_fn(lambda _: fired.set())
        timer_mod.set_timer(0.1, name="cleanup_test")
        fired.wait(timeout=3)
        time.sleep(0.1)  # Give thread time to clean up
        assert "cleanup_test" not in timer_mod._timers
        timer_mod.set_speak_fn(None)
