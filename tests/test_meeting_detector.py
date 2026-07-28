"""Tests for Granola-style meeting detection classification (pure logic)."""
from voxa.memory.meeting_detector import classify_meeting


class TestBrowserMeetings:
    def test_google_meet_room_detected(self):
        m = classify_meeting(["https://meet.google.com/abc-defg-hij"], [])
        assert m and m["platform"] == "Google Meet" and m["source"] == "browser"

    def test_google_meet_homepage_not_detected(self):
        # Landing page (no room code) should NOT trigger.
        assert classify_meeting(["https://meet.google.com/"], []) is None

    def test_zoom_web_join_detected(self):
        m = classify_meeting(["https://us02web.zoom.us/j/1234567890"], [])
        assert m and m["platform"] == "Zoom"

    def test_teams_meetup_detected(self):
        m = classify_meeting(
            ["https://teams.microsoft.com/l/meetup-join/19%3ameeting_abc"], []
        )
        assert m and m["platform"] == "Microsoft Teams"

    def test_jitsi_detected(self):
        m = classify_meeting(["https://meet.jit.si/MyStandup"], [])
        assert m and m["platform"] == "Jitsi"

    def test_ordinary_tabs_not_detected(self):
        urls = ["https://github.com/foo", "https://news.ycombinator.com", "https://google.com"]
        assert classify_meeting(urls, []) is None

    def test_first_matching_tab_wins(self):
        m = classify_meeting(
            ["https://github.com", "https://meet.google.com/xyz-abcd-efg"], []
        )
        assert m["source"] == "browser"


class TestMicGate:
    URL = ["https://meet.google.com/abc-defg-hij"]

    def test_stale_tab_blocked_when_mic_idle(self):
        # Meeting tab open but mic provably idle → treated as stale, not a call.
        assert classify_meeting(self.URL, [], mic_active=False, require_mic_for_browser=True) is None

    def test_allowed_when_mic_active(self):
        m = classify_meeting(self.URL, [], mic_active=True, require_mic_for_browser=True)
        assert m and m["platform"] == "Google Meet"

    def test_unknown_mic_never_blocks(self):
        m = classify_meeting(self.URL, [], mic_active=None, require_mic_for_browser=True)
        assert m and m["platform"] == "Google Meet"

    def test_gate_off_ignores_mic(self):
        m = classify_meeting(self.URL, [], mic_active=False, require_mic_for_browser=False)
        assert m and m["platform"] == "Google Meet"

    def test_native_not_gated_by_mic(self):
        # A native in-call window is reliable on its own — mic idle shouldn't block it.
        m = classify_meeting([], [("zoom.us", ["Zoom Meeting"])], mic_active=False, require_mic_for_browser=True)
        assert m and m["platform"] == "Zoom"


class TestMultiBrowser:
    def test_aggregates_urls_across_browsers(self):
        from unittest.mock import patch
        from voxa.memory.meeting_detector import MeetingDetector, _SUPPORTED_BROWSERS

        det = MeetingDetector(on_meeting_start=lambda m: None, on_meeting_end=lambda m: None)

        def fake(app_name):
            return {
                "Google Chrome": ["https://github.com"],
                "Safari": ["https://meet.google.com/abc-defg-hij"],
            }.get(app_name, [])

        with patch.object(MeetingDetector, "_tab_urls_for_browser", side_effect=fake, autospec=False):
            urls = det._browser_tab_urls()
        assert "https://meet.google.com/abc-defg-hij" in urls
        # Detection then classifies the Safari meeting tab.
        assert classify_meeting(urls, []) is not None

    def test_supported_browsers_include_common(self):
        from voxa.memory.meeting_detector import _SUPPORTED_BROWSERS
        for b in ["Google Chrome", "Safari", "Brave Browser", "Microsoft Edge", "Arc"]:
            assert b in _SUPPORTED_BROWSERS


class TestNativeMeetings:
    def test_zoom_in_meeting_window(self):
        m = classify_meeting([], [("zoom.us", ["Zoom Meeting"])])
        assert m and m["platform"] == "Zoom" and m["source"] == "app"

    def test_zoom_idle_window_not_detected(self):
        # Idle Zoom shows a "Zoom" / "Zoom Workplace" window, not "Zoom Meeting".
        assert classify_meeting([], [("zoom.us", ["Zoom Workplace"])]) is None

    def test_no_signals(self):
        assert classify_meeting([], []) is None
