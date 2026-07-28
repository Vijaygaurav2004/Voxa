"""
Meeting Detector — Granola-style automatic meeting detection for Voxa.

Polls the system on a background thread and detects when the user joins a
video/audio meeting (Zoom, Google Meet, Microsoft Teams, Webex, Whereby, Jitsi,
etc.). On a start→meeting transition it fires `on_meeting_start`; when the
meeting ends it fires `on_meeting_end`. The MeetingManager wires these to the
ambient MemoryEngine so notes are captured automatically.

Detection signals (no special entitlements required):
  1. Browser meetings — Chrome tab URLs matching known meeting-room patterns
     (e.g. meet.google.com/abc-defg-hij, zoom.us/j/…, teams…meetup-join).
  2. Native apps in a call — a running meeting app with an in-call window title
     (e.g. Zoom's "Zoom Meeting" window). Window-title checks need Accessibility
     permission; they degrade gracefully to no-signal if it isn't granted.

The classification step (`classify_meeting`) is a pure function so it can be
unit-tested without a live meeting; the I/O gatherers are thin and defensive.
"""
from __future__ import annotations

import re
import threading
import time
from typing import Callable, Optional

from voxa.utils.logger import get_logger
from voxa.utils.applescript import run_applescript, AppleScriptError

log = get_logger("memory.meeting")

# ── Detection patterns ─────────────────────────────────────────────────────────

# Browser tab URLs that indicate an active meeting room. The presence of a
# room/meeting code (not just the product homepage) is what distinguishes
# "in a meeting" from "has the site open".
MEETING_URL_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("Google Meet", re.compile(r"meet\.google\.com/[a-z]{3}-[a-z]{4}-[a-z]{3}", re.I)),
    ("Zoom",        re.compile(r"zoom\.us/(?:j|wc|w|s)/\d", re.I)),
    ("Microsoft Teams", re.compile(r"teams\.(?:microsoft|live)\.com/.*(?:meetup-join|/meet/|l/meetup)", re.I)),
    ("Webex",       re.compile(r"\.webex\.com/(?:meet|join|wbxmjs|webappng)", re.I)),
    ("Whereby",     re.compile(r"whereby\.com/[\w-]+", re.I)),
    ("Jitsi",       re.compile(r"meet\.jit\.si/\S+", re.I)),
    ("Around",      re.compile(r"around\.co/r/", re.I)),
    ("Slack Huddle", re.compile(r"app\.slack\.com/huddle/", re.I)),
]

# Native meeting apps: (platform, process name, in-call window-title pattern).
MEETING_WINDOW_PATTERNS: list[tuple[str, str, re.Pattern]] = [
    ("Zoom",  "zoom.us", re.compile(r"\bZoom Meeting\b", re.I)),
    ("Webex", "Webex",   re.compile(r"\bMeeting\b", re.I)),
]

# Browsers whose tabs we scan for meeting URLs. All use the same AppleScript
# tab model (windows → tabs → URL), so one script template covers them.
_SUPPORTED_BROWSERS = [
    "Google Chrome",
    "Safari",
    "Brave Browser",
    "Microsoft Edge",
    "Arc",
    "Vivaldi",
    "Chromium",
    "Opera",
]


def classify_meeting(
    chrome_urls: list[str],
    native_signals: list[tuple[str, list[str]]],
    mic_active: Optional[bool] = None,
    require_mic_for_browser: bool = False,
) -> Optional[dict]:
    """
    Decide whether the collected signals indicate an active meeting. PURE — no I/O.

    Args:
        chrome_urls: URLs of all open Chrome tabs.
        native_signals: list of (process_name, window_titles) for running meeting
            apps whose windows we managed to read.
        mic_active: True/False if the mic's live state is known, None if unknown.
        require_mic_for_browser: if True, a browser meeting tab only counts when
            the mic is actively in use — filtering out tabs left open after a
            call. Only applied when mic_active is definitively False; unknown
            (None) never blocks.

    Returns:
        {"platform", "source", "detail"} for the first match, or None.
    """
    # 1. Browser meetings — first matching tab wins.
    browser_hit: Optional[dict] = None
    for url in chrome_urls:
        matched = False
        for platform, pattern in MEETING_URL_PATTERNS:
            if pattern.search(url):
                browser_hit = {"platform": platform, "source": "browser", "detail": url}
                matched = True
                break
        if matched:
            break

    if browser_hit is not None:
        # A meeting tab is open but the mic is provably idle → treat as a stale
        # left-open tab, not an active call. (Native signals are still checked.)
        stale_tab = require_mic_for_browser and mic_active is False
        if not stale_tab:
            return browser_hit

    # 2. Native app in-call windows (reliable on their own — no mic gate).
    titles_by_proc = {proc: titles for proc, titles in native_signals}
    for platform, proc, pattern in MEETING_WINDOW_PATTERNS:
        for title in titles_by_proc.get(proc, []):
            if pattern.search(title):
                return {"platform": platform, "source": "app", "detail": title}

    return None


class MeetingDetector:
    """
    Background poller that fires callbacks on meeting start/stop transitions.
    Debounced to avoid flapping: a meeting starts on the first positive poll, but
    only ends after `end_confirmations` consecutive negative polls (a grace
    window that tolerates brief mutes, tab switches, or reconnects).
    """

    def __init__(
        self,
        on_meeting_start: Callable[[dict], None],
        on_meeting_end: Callable[[dict], None],
        poll_interval: float = 10.0,
        end_confirmations: int = 3,
        require_mic: bool = True,
    ):
        self.on_meeting_start = on_meeting_start
        self.on_meeting_end = on_meeting_end
        self.poll_interval = max(3.0, poll_interval)
        self.end_confirmations = max(1, end_confirmations)
        # Require live mic to *start* a browser meeting (filters stale tabs).
        self.require_mic = require_mic

        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._current: Optional[dict] = None   # active meeting info, if any
        self._miss_streak = 0

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def start(self):
        if self._running:
            log.warning("Meeting detector already running")
            return
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True, name="meeting-detector")
        self._thread.start()
        log.info("🔎 Meeting detector started (every %.0fs)", self.poll_interval)

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        self._thread = None
        log.info("🔎 Meeting detector stopped")

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def current_meeting(self) -> Optional[dict]:
        return self._current

    # ── Poll loop ──────────────────────────────────────────────────────────────

    def _poll_loop(self):
        while self._running:
            try:
                detected = self._detect_once()
                self._apply(detected)
            except Exception as e:
                log.warning("Meeting poll error: %s", e)
            # Sleep in small steps so stop() is responsive.
            slept = 0.0
            while self._running and slept < self.poll_interval:
                time.sleep(0.5)
                slept += 0.5

    def _apply(self, detected: Optional[dict]):
        """Turn a single detection into start/stop transitions with debounce."""
        if detected:
            self._miss_streak = 0
            if self._current is None:
                self._current = {**detected, "started_at": time.time()}
                log.info("🟢 Meeting started: %s (%s)", detected["platform"], detected["source"])
                try:
                    self.on_meeting_start(self._current)
                except Exception as e:
                    log.error("on_meeting_start callback failed: %s", e)
        else:
            if self._current is not None:
                self._miss_streak += 1
                if self._miss_streak >= self.end_confirmations:
                    ended = {**self._current, "ended_at": time.time()}
                    self._current = None
                    self._miss_streak = 0
                    log.info("🔴 Meeting ended: %s", ended["platform"])
                    try:
                        self.on_meeting_end(ended)
                    except Exception as e:
                        log.error("on_meeting_end callback failed: %s", e)

    def _detect_once(self) -> Optional[dict]:
        chrome_urls = self._browser_tab_urls()
        native = self._native_signals()

        # Only gate the *start* of a browser meeting on mic activity. Once a
        # meeting is active, Voxa itself holds the mic, so re-gating is pointless.
        require_mic_for_browser = self.require_mic and self._current is None
        mic_active: Optional[bool] = None
        if require_mic_for_browser:
            from voxa.utils.audio_activity import is_input_active
            mic_active = is_input_active()

        return classify_meeting(
            chrome_urls, native,
            mic_active=mic_active,
            require_mic_for_browser=require_mic_for_browser,
        )

    # ── Signal gatherers (thin + defensive) ─────────────────────────────────────

    def _browser_tab_urls(self) -> list[str]:
        """
        URLs of every open tab across all running supported browsers. Covers the
        common Chromium browsers and Safari (same AppleScript tab model), so
        meeting detection isn't limited to Chrome users. Defensive per-browser.
        """
        urls: list[str] = []
        for app_name in _SUPPORTED_BROWSERS:
            urls.extend(self._tab_urls_for_browser(app_name))
        return urls

    def _tab_urls_for_browser(self, app_name: str) -> list[str]:
        safe = app_name.replace('"', '')
        script = (
            f'if application "{safe}" is running then\n'
            f'  tell application "{safe}"\n'
            '    set out to ""\n'
            '    repeat with w in windows\n'
            '      try\n'
            '        repeat with t in tabs of w\n'
            '          set out to out & (URL of t) & linefeed\n'
            '        end repeat\n'
            '      end try\n'
            '    end repeat\n'
            '    return out\n'
            '  end tell\n'
            'end if'
        )
        try:
            out = run_applescript(script, timeout=6.0)
        except AppleScriptError as e:
            # Most likely Automation permission not yet granted for this browser.
            self._note_permission_hint(app_name, e)
            return []
        except Exception:
            return []
        if not out:
            return []
        return [line.strip() for line in out.splitlines() if line.strip()]

    def _note_permission_hint(self, target: str, err: Exception):
        """Log a one-time hint when AppleScript is blocked by Automation perms."""
        if not getattr(self, "_perm_hint_logged", False):
            msg = str(err).lower()
            if "not allowed" in msg or "authoriz" in msg or "1743" in msg or "-1743" in msg:
                log.warning(
                    "Meeting detection needs Automation permission for '%s'. "
                    "Grant it in System Settings → Privacy & Security → Automation.",
                    target,
                )
                self._perm_hint_logged = True

    def _native_signals(self) -> list[tuple[str, list[str]]]:
        """Return (process, window_titles) for running native meeting apps."""
        signals: list[tuple[str, list[str]]] = []
        procs = {proc for _, proc, _ in MEETING_WINDOW_PATTERNS}
        for proc in procs:
            titles = self._app_window_titles(proc)
            if titles:
                signals.append((proc, titles))
        return signals

    def _app_window_titles(self, process_name: str) -> list[str]:
        """
        Window titles for a running process (empty if not running or if
        Accessibility permission isn't granted — degrades gracefully).
        """
        safe = process_name.replace('"', '')
        script = (
            'tell application "System Events"\n'
            f'  if exists (process "{safe}") then\n'
            f'    return name of windows of process "{safe}"\n'
            '  end if\n'
            'end tell'
        )
        try:
            out = run_applescript(script, timeout=6.0)
        except AppleScriptError:
            return []
        except Exception:
            return []
        if not out:
            return []
        # AppleScript lists come back comma-separated.
        return [t.strip() for t in out.split(",") if t.strip()]
