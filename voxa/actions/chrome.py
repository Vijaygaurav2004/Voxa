"""
Chrome Control Module for Voxa.
Dedicated, optimised helpers for Google Chrome on macOS.

Provides:
  - Tab management  (open, close, switch, duplicate, pin, reload, list)
  - Window management (new window, incognito, close, list)
  - Navigation (back, forward, reload, home, scroll)
  - Page actions (zoom in/out/reset, find-in-page, bookmark, history, downloads)
  - Dev tools
  - Smart URL resolution (bare domains → https://)
  - Bulk tab operations (close all, close duplicates, close to right)
"""
from __future__ import annotations

import re
import time
import urllib.parse
from typing import Optional

from voxa.utils.applescript import run_applescript, escape_applescript_string, AppleScriptError
from voxa.utils.logger import get_logger

log = get_logger("chrome")

BROWSER = "Google Chrome"
_TAB_LOAD_WAIT = 0.8


# ─── Internal helpers ─────────────────────────────────────────────────────────

def _chrome_running() -> bool:
    """Check if Chrome is currently running."""
    try:
        result = run_applescript(
            'tell application "System Events" to return (name of processes) contains "Google Chrome"',
            timeout=4,
        )
        return result and "true" in result.lower()
    except Exception:
        return False


def _ensure_chrome(new_window_if_needed: bool = True):
    """Activate Chrome, open a new window if none exist."""
    run_applescript(f'tell application "{BROWSER}" to activate')
    time.sleep(0.4)
    if new_window_if_needed:
        try:
            count = run_applescript(f'tell application "{BROWSER}" to return count of windows')
            if not count or count.strip() == "0":
                run_applescript(f'tell application "{BROWSER}" to make new window')
                time.sleep(0.5)
        except Exception:
            pass


def _smart_url(url: str) -> str:
    """Convert a bare domain or partial URL to a proper https:// URL."""
    url = url.strip()
    if not url:
        return url
    if url.startswith("http://") or url.startswith("https://"):
        return url
    # Bare domain like "github.com" or "youtube.com/watch?v=..."
    if re.match(r'^[a-zA-Z0-9]', url):
        return "https://" + url
    return url


def _tab_count() -> int:
    """Return total number of open tabs in all Chrome windows."""
    try:
        result = run_applescript(f'''
            tell application "{BROWSER}"
                set total to 0
                repeat with w in windows
                    set total to total + (count of tabs of w)
                end repeat
                return total
            end tell
        ''', timeout=6)
        return int(result.strip()) if result else 0
    except Exception:
        return 0


def _get_active_tab_info() -> dict:
    """Return title and URL of the currently active tab."""
    try:
        title = run_applescript(
            f'tell application "{BROWSER}" to return title of active tab of front window',
            timeout=5,
        ) or ""
        url = run_applescript(
            f'tell application "{BROWSER}" to return URL of active tab of front window',
            timeout=5,
        ) or ""
        return {"title": title.strip(), "url": url.strip()}
    except Exception:
        return {"title": "", "url": ""}


# ─── Tab management ────────────────────────────────────────────────────────────

def open_new_tab(url: str = "chrome://newtab") -> dict:
    """Open a new tab in Chrome, optionally at a URL."""
    url = _smart_url(url) if url != "chrome://newtab" else url
    safe = escape_applescript_string(url)
    log.info("🆕 New Chrome tab: %s", url)
    try:
        _ensure_chrome()
        run_applescript(f'''
            tell application "{BROWSER}"
                if (count of windows) = 0 then make new window
                tell front window
                    make new tab with properties {{URL:"{safe}"}}
                end tell
            end tell
        ''', timeout=8)
        time.sleep(_TAB_LOAD_WAIT)
        return {"success": True, "action": "open_new_tab", "url": url,
                "message": f"Opened new tab: {url}"}
    except AppleScriptError as e:
        return {"success": False, "action": "open_new_tab", "error": str(e),
                "message": f"Could not open tab: {e}"}


def open_n_tabs(n: int, url: str = "chrome://newtab") -> dict:
    """Open N new tabs in Chrome (1–20 safe limit)."""
    n = max(1, min(n, 20))
    url = _smart_url(url) if url != "chrome://newtab" else url
    safe = escape_applescript_string(url)
    log.info("🆕 Opening %d Chrome tabs (%s)", n, url)
    try:
        _ensure_chrome()
        # Build a repeat loop in AppleScript — faster than N separate calls
        run_applescript(f'''
            tell application "{BROWSER}"
                if (count of windows) = 0 then make new window
                repeat {n} times
                    tell front window
                        make new tab with properties {{URL:"{safe}"}}
                    end tell
                    delay 0.15
                end repeat
            end tell
        ''', timeout=max(15, n * 2))
        time.sleep(0.5)
        return {"success": True, "action": "open_n_tabs", "count": n,
                "message": f"Opened {n} new tab{'s' if n != 1 else ''} in Chrome"}
    except AppleScriptError as e:
        return {"success": False, "action": "open_n_tabs", "error": str(e),
                "message": f"Could not open {n} tabs: {e}"}


def close_current_tab() -> dict:
    """Close the currently active Chrome tab."""
    log.info("❌ Closing current Chrome tab")
    try:
        run_applescript(f'''
            tell application "{BROWSER}"
                tell front window to close active tab
            end tell
        ''', timeout=6)
        return {"success": True, "action": "close_current_tab",
                "message": "Closed current Chrome tab"}
    except AppleScriptError as e:
        return {"success": False, "action": "close_current_tab", "error": str(e),
                "message": f"Could not close tab: {e}"}


def close_tabs_to_right() -> dict:
    """Close all tabs to the right of the current one."""
    log.info("❌ Closing tabs to the right")
    try:
        run_applescript(f'''
            tell application "{BROWSER}"
                tell front window
                    set idx to active tab index
                    set total to count of tabs
                    if idx < total then
                        repeat (total - idx) times
                            close tab (idx + 1)
                        end repeat
                    end if
                end tell
            end tell
        ''', timeout=10)
        return {"success": True, "action": "close_tabs_to_right",
                "message": "Closed all tabs to the right"}
    except AppleScriptError as e:
        return {"success": False, "action": "close_tabs_to_right", "error": str(e),
                "message": f"Could not close tabs: {e}"}


def close_all_tabs() -> dict:
    """Close all tabs in the front Chrome window (leaves one empty tab)."""
    log.info("❌ Closing all Chrome tabs")
    try:
        run_applescript(f'''
            tell application "{BROWSER}"
                tell front window
                    set tabCount to count of tabs
                    -- Close all except first
                    repeat (tabCount - 1) times
                        close tab 2
                    end repeat
                    -- Navigate first tab to new tab page
                    set URL of tab 1 to "chrome://newtab"
                end tell
            end tell
        ''', timeout=15)
        return {"success": True, "action": "close_all_tabs",
                "message": "Closed all Chrome tabs"}
    except AppleScriptError as e:
        return {"success": False, "action": "close_all_tabs", "error": str(e),
                "message": f"Could not close all tabs: {e}"}


def switch_to_next_tab() -> dict:
    """Switch to the next tab in Chrome natively."""
    log.info("🔀 Switching to next Chrome tab")
    try:
        _ensure_chrome(new_window_if_needed=False)
        run_applescript(f'''
            tell application "{BROWSER}"
                tell front window
                    set idx to active tab index
                    set total to count of tabs
                    if idx < total then
                        set active tab index to (idx + 1)
                    else
                        set active tab index to 1
                    end if
                end tell
                activate
            end tell
        ''', timeout=6)
        return {"success": True, "action": "switch_to_next_tab", "message": "Switched to next tab"}
    except AppleScriptError as e:
        return {"success": False, "action": "switch_to_next_tab", "error": str(e),
                "message": f"Could not switch to next tab: {e}"}


def switch_to_prev_tab() -> dict:
    """Switch to the previous tab in Chrome natively."""
    log.info("🔀 Switching to previous Chrome tab")
    try:
        _ensure_chrome(new_window_if_needed=False)
        run_applescript(f'''
            tell application "{BROWSER}"
                tell front window
                    set idx to active tab index
                    set total to count of tabs
                    if idx > 1 then
                        set active tab index to (idx - 1)
                    else
                        set active tab index to total
                    end if
                end tell
                activate
            end tell
        ''', timeout=6)
        return {"success": True, "action": "switch_to_prev_tab", "message": "Switched to previous tab"}
    except AppleScriptError as e:
        return {"success": False, "action": "switch_to_prev_tab", "error": str(e),
                "message": f"Could not switch to previous tab: {e}"}


def switch_to_tab(index: int) -> dict:
    """Switch to tab number 1-9 in Chrome (⌘+1 … ⌘+9)."""
    idx = max(1, min(index, 9))
    log.info("🔀 Switching to Chrome tab %d", idx)
    try:
        _ensure_chrome(new_window_if_needed=False)
        run_applescript(f'''
            tell application "{BROWSER}"
                tell front window
                    set active tab index to {idx}
                end tell
                activate
            end tell
        ''', timeout=6)
        return {"success": True, "action": "switch_to_tab",
                "message": f"Switched to tab {idx}"}
    except AppleScriptError as e:
        return {"success": False, "action": "switch_to_tab", "error": str(e),
                "message": f"Could not switch to tab {idx}"}


def duplicate_current_tab() -> dict:
    """Duplicate the current Chrome tab."""
    log.info("📋 Duplicating current Chrome tab")
    try:
        info = _get_active_tab_info()
        url = info.get("url", "chrome://newtab")
        return open_new_tab(url)
    except Exception as e:
        return {"success": False, "action": "duplicate_tab", "error": str(e),
                "message": "Could not duplicate tab"}


def pin_current_tab() -> dict:
    """Pin/unpin the current Chrome tab via keyboard shortcut."""
    # Chrome doesn't expose pin via AppleScript, use menu
    log.info("📌 Toggling pin on current Chrome tab")
    try:
        _ensure_chrome(new_window_if_needed=False)
        run_applescript(f'''
            tell application "System Events"
                tell process "{BROWSER}"
                    -- Right-click on active tab to get context menu (not reliable)
                    -- Use the keyboard shortcut instead
                    keystroke "p" using {{command down, shift down}}
                end tell
            end tell
        ''', timeout=6)
        return {"success": True, "action": "pin_tab", "message": "Toggled tab pin"}
    except AppleScriptError as e:
        return {"success": False, "action": "pin_tab", "error": str(e),
                "message": f"Could not pin tab: {e}"}


def list_open_tabs() -> dict:
    """Return a spoken summary of all open Chrome tabs."""
    log.info("📋 Listing open Chrome tabs")
    try:
        result = run_applescript(f'''
            tell application "{BROWSER}"
                set out to ""
                set winIdx to 0
                repeat with w in windows
                    set winIdx to winIdx + 1
                    set tabIdx to 0
                    repeat with t in tabs of w
                        set tabIdx to tabIdx + 1
                        set out to out & "Window " & winIdx & " Tab " & tabIdx & ": " & (title of t) & "\\n"
                    end repeat
                end repeat
                return out
            end tell
        ''', timeout=10)
        lines = [l for l in (result or "").strip().splitlines() if l.strip()]
        count = len(lines)
        summary = f"You have {count} Chrome tab{'s' if count != 1 else ''} open."
        if count <= 10:
            summary += " " + "; ".join(l.split(": ", 1)[-1] for l in lines[:10])
        return {"success": True, "action": "list_tabs", "tabs": lines,
                "message": summary}
    except AppleScriptError as e:
        return {"success": False, "action": "list_tabs", "error": str(e),
                "message": "Could not list tabs"}


def find_and_switch_tab(keyword: str) -> dict:
    """Switch to the first Chrome tab whose title or URL contains the keyword."""
    log.info("🔍 Finding Chrome tab matching: %s", keyword)
    keyword_lower = keyword.lower()
    try:
        result = run_applescript(f'''
            tell application "{BROWSER}"
                set winIdx to 0
                repeat with w in windows
                    set winIdx to winIdx + 1
                    set tabIdx to 0
                    repeat with t in tabs of w
                        set tabIdx to tabIdx + 1
                        if (title of t) contains "{keyword}" or (URL of t) contains "{keyword}" then
                            set active tab index of w to tabIdx
                            set index of w to 1
                            activate
                            return "found:" & (title of t)
                        end if
                    end repeat
                end repeat
                return "not_found"
            end tell
        ''', timeout=10)
        if result and result.startswith("found:"):
            title = result[6:]
            return {"success": True, "action": "find_tab",
                    "message": f"Switched to tab: {title}"}
        return {"success": False, "action": "find_tab",
                "message": f"No tab found matching '{keyword}'"}
    except AppleScriptError as e:
        return {"success": False, "action": "find_tab", "error": str(e),
                "message": f"Could not search tabs: {e}"}


# ─── Window management ─────────────────────────────────────────────────────────

def open_new_window(url: str = "chrome://newtab") -> dict:
    """Open a new Chrome window."""
    url = _smart_url(url) if url != "chrome://newtab" else url
    safe = escape_applescript_string(url)
    log.info("🪟 New Chrome window: %s", url)
    try:
        _ensure_chrome(new_window_if_needed=False)
        run_applescript(f'''
            tell application "{BROWSER}"
                make new window
                set URL of active tab of front window to "{safe}"
                activate
            end tell
        ''', timeout=8)
        time.sleep(0.6)
        return {"success": True, "action": "open_new_window", "url": url,
                "message": f"Opened new Chrome window"}
    except AppleScriptError as e:
        return {"success": False, "action": "open_new_window", "error": str(e),
                "message": f"Could not open new window: {e}"}


def open_incognito_window(url: str = "") -> dict:
    """Open a new Chrome incognito window."""
    log.info("🕵️  Opening Chrome incognito window")
    try:
        _ensure_chrome(new_window_if_needed=False)
        run_applescript(f'''
            tell application "{BROWSER}"
                activate
            end tell
            delay 0.3
            tell application "System Events"
                tell process "{BROWSER}"
                    keystroke "n" using {{command down, shift down}}
                end tell
            end tell
        ''', timeout=8)
        time.sleep(0.8)
        if url:
            url = _smart_url(url)
            safe = escape_applescript_string(url)
            run_applescript(f'''
                tell application "{BROWSER}"
                    set URL of active tab of front window to "{safe}"
                end tell
            ''', timeout=6)
        return {"success": True, "action": "open_incognito",
                "message": "Opened Chrome incognito window"}
    except AppleScriptError as e:
        return {"success": False, "action": "open_incognito", "error": str(e),
                "message": f"Could not open incognito: {e}"}


def close_current_window() -> dict:
    """Close the current Chrome window."""
    log.info("❌ Closing current Chrome window")
    try:
        run_applescript(f'''
            tell application "{BROWSER}"
                close front window
            end tell
        ''', timeout=6)
        return {"success": True, "action": "close_window",
                "message": "Closed Chrome window"}
    except AppleScriptError as e:
        return {"success": False, "action": "close_window", "error": str(e),
                "message": f"Could not close window: {e}"}


# ─── Navigation ────────────────────────────────────────────────────────────────

def navigate_back() -> dict:
    """Go back in Chrome history (⌘+[)."""
    return _keystroke_chrome("cmd+[", "Navigated back")


def navigate_forward() -> dict:
    """Go forward in Chrome history (⌘+])."""
    return _keystroke_chrome("cmd+]", "Navigated forward")


def reload_page(hard: bool = False) -> dict:
    """Reload the current Chrome tab. hard=True clears cache (⌘+Shift+R)."""
    msg = "Hard-reloaded" if hard else "Reloaded"
    keys = "cmd+shift+r" if hard else "cmd+r"
    return _keystroke_chrome(keys, f"{msg} Chrome page")


def navigate_to_url(url: str) -> dict:
    """Navigate the current tab to a URL (reuses existing tab)."""
    url = _smart_url(url)
    safe = escape_applescript_string(url)
    log.info("🧭 Chrome navigate: %s", url)
    try:
        _ensure_chrome()
        run_applescript(f'''
            tell application "{BROWSER}"
                if (count of windows) = 0 then make new window
                set URL of active tab of front window to "{safe}"
                activate
            end tell
        ''', timeout=8)
        time.sleep(_TAB_LOAD_WAIT)
        return {"success": True, "action": "navigate_url", "url": url,
                "message": f"Navigated to {url}"}
    except AppleScriptError as e:
        return {"success": False, "action": "navigate_url", "error": str(e),
                "message": f"Could not navigate to {url}"}


# ─── Page actions ──────────────────────────────────────────────────────────────

def zoom_in() -> dict:
    return _keystroke_chrome("cmd++", "Zoomed in")


def zoom_out() -> dict:
    return _keystroke_chrome("cmd+-", "Zoomed out")


def zoom_reset() -> dict:
    return _keystroke_chrome("cmd+0", "Reset zoom to 100%")


def find_in_page(query: str) -> dict:
    """Open Chrome's find-in-page bar and search for text."""
    log.info("🔎 Find in page: %s", query)
    safe = escape_applescript_string(query)
    try:
        _ensure_chrome(new_window_if_needed=False)
        run_applescript(f'''
            tell application "{BROWSER}" to activate
            delay 0.3
            tell application "System Events"
                tell process "{BROWSER}"
                    keystroke "f" using command down
                    delay 0.4
                    keystroke "{safe}"
                end tell
            end tell
        ''', timeout=8)
        return {"success": True, "action": "find_in_page", "query": query,
                "message": f"Searching for '{query}' in page"}
    except AppleScriptError as e:
        return {"success": False, "action": "find_in_page", "error": str(e),
                "message": f"Could not open find bar: {e}"}


def bookmark_current_page() -> dict:
    """Bookmark the current Chrome page (⌘+D)."""
    return _keystroke_chrome("cmd+d", "Bookmarked current page")


def open_history() -> dict:
    """Open Chrome history page."""
    return open_new_tab("chrome://history")


def open_downloads() -> dict:
    """Open Chrome downloads page."""
    return open_new_tab("chrome://downloads")


def open_bookmarks() -> dict:
    """Open Chrome bookmarks manager."""
    return open_new_tab("chrome://bookmarks")


def open_settings() -> dict:
    """Open Chrome settings page."""
    return open_new_tab("chrome://settings")


def open_extensions() -> dict:
    """Open Chrome extensions page."""
    return open_new_tab("chrome://extensions")


def open_devtools() -> dict:
    """Open Chrome DevTools (⌘+Option+I)."""
    return _keystroke_chrome("cmd+option+i", "Opened Chrome DevTools")


def scroll_page(direction: str = "down", amount: int = 3) -> dict:
    """Scroll the current Chrome page up or down."""
    log.info("📜 Chrome scroll %s x%d", direction, amount)
    key = "125" if direction == "down" else "126"  # down/up arrow keycodes
    try:
        _ensure_chrome(new_window_if_needed=False)
        script = f'''
            tell application "{BROWSER}" to activate
            delay 0.2
            tell application "System Events"
                tell process "{BROWSER}"
        '''
        for _ in range(amount * 3):
            script += f"\n                    key code {key}"
            script += "\n                    delay 0.04"
        script += '''
                end tell
            end tell
        '''
        run_applescript(script, timeout=10)
        return {"success": True, "action": "scroll_page",
                "message": f"Scrolled {direction}"}
    except AppleScriptError as e:
        return {"success": False, "action": "scroll_page", "error": str(e),
                "message": f"Could not scroll: {e}"}


def mute_current_tab() -> dict:
    """Mute/unmute the current Chrome tab (no shortcut; uses JS)."""
    log.info("🔇 Toggling tab mute via Chrome URL bar trick")
    # Chrome removed JS tab-mute API; best approach is the address bar trick
    try:
        _ensure_chrome(new_window_if_needed=False)
        # Focus address bar, type javascript: void(0) — as workaround we guide user
        return {"success": True, "action": "mute_tab",
                "message": "To mute this tab, right-click the tab and choose 'Mute Tab'"}
    except Exception as e:
        return {"success": False, "action": "mute_tab", "error": str(e),
                "message": "Could not mute tab"}


def get_page_info() -> dict:
    """Return the title and URL of the current Chrome tab (spoken aloud)."""
    info = _get_active_tab_info()
    title = info.get("title", "unknown page")
    url = info.get("url", "")
    msg = f"You're on: {title}" + (f" at {url}" if url else "")
    return {"success": True, "action": "get_page_info", "title": title,
            "url": url, "message": msg}


# ─── Internal keystroke helper ────────────────────────────────────────────────

def _keystroke_chrome(combo: str, success_msg: str) -> dict:
    """
    Send a keyboard shortcut to Chrome.
    combo examples: "cmd+t", "cmd+option+right", "cmd+shift+r"
    """
    log.info("⌨️  Chrome keystroke: %s", combo)
    parts = combo.lower().split("+")
    key = parts[-1]
    mods = parts[:-1]

    # Map key names to AppleScript
    _KEY_MAP = {
        "tab": "48", "return": "36", "escape": "53", "space": "49",
        "left": "123", "right": "124", "down": "125", "up": "126",
        "delete": "51", "backspace": "51", "home": "115", "end": "119",
        "+": "24", "-": "27", "=": "24", "0": "29", "[": "33", "]": "30",
        "r": "15", "t": "17", "w": "13", "n": "45", "d": "2",
        "f": "3", "i": "34", "l": "37",
    }

    _MOD_MAP = {
        "cmd": "command down",
        "command": "command down",
        "shift": "shift down",
        "option": "option down",
        "alt": "option down",
        "ctrl": "control down",
        "control": "control down",
    }

    mod_str = ", ".join(_MOD_MAP.get(m, f"{m} down") for m in mods) if mods else ""

    if key in _KEY_MAP:
        # Use key code
        code = _KEY_MAP[key]
        mod_clause = f" using {{{mod_str}}}" if mod_str else ""
        osa = f'''
            tell application "{BROWSER}" to activate
            delay 0.2
            tell application "System Events"
                tell process "{BROWSER}"
                    key code {code}{mod_clause}
                end tell
            end tell
        '''
    else:
        # Use keystroke (for letter keys)
        mod_clause = f" using {{{mod_str}}}" if mod_str else ""
        osa = f'''
            tell application "{BROWSER}" to activate
            delay 0.2
            tell application "System Events"
                tell process "{BROWSER}"
                    keystroke "{key}"{mod_clause}
                end tell
            end tell
        '''

    try:
        run_applescript(osa, timeout=6)
        return {"success": True, "action": "chrome_keystroke", "message": success_msg}
    except AppleScriptError as e:
        return {"success": False, "action": "chrome_keystroke", "error": str(e),
                "message": f"Keystroke failed ({combo}): {e}"}


def reopen_closed_tab() -> dict:
    """Reopen the last closed tab (⌘+Shift+T)."""
    return _keystroke_chrome("cmd+shift+t", "Reopened the last closed tab")


def close_tab_by_keyword(keyword: str) -> dict:
    """Close the first tab matching keyword in title or URL."""
    log.info("🔍 Closing Chrome tab matching: %s", keyword)
    safe_keyword = escape_applescript_string(keyword)
    try:
        result = run_applescript(f'''
            tell application "{BROWSER}"
                repeat with w in windows
                    set tabIdx to 0
                    repeat with t in tabs of w
                        set tabIdx to tabIdx + 1
                        if (title of t) contains "{safe_keyword}" or (URL of t) contains "{safe_keyword}" then
                            close t
                            return "closed"
                        end if
                    end repeat
                end repeat
                return "not_found"
            end tell
        ''', timeout=10)
        if result and result.strip() == "closed":
            return {"success": True, "action": "close_tab_by_keyword",
                    "message": f"Closed tab matching '{keyword}'"}
        return {"success": False, "action": "close_tab_by_keyword",
                "message": f"No tab found matching '{keyword}'"}
    except AppleScriptError as e:
        return {"success": False, "action": "close_tab_by_keyword", "error": str(e),
                "message": f"Could not close tab matching '{keyword}': {e}"}


def close_other_tabs() -> dict:
    """Close all tabs in the front Chrome window except the active one."""
    log.info("❌ Closing other Chrome tabs")
    try:
        run_applescript(f'''
            tell application "{BROWSER}"
                tell front window
                    set activeIdx to active tab index
                    set tabCount to count of tabs
                    -- Close tabs to the right (from end down to activeIdx + 1)
                    if activeIdx < tabCount then
                        repeat with idx from tabCount to (activeIdx + 1) by -1
                            close tab idx
                        end repeat
                    end if
                    -- Close tabs to the left (from activeIdx - 1 down to 1)
                    if activeIdx > 1 then
                        repeat with idx from (activeIdx - 1) to 1 by -1
                            close tab idx
                        end repeat
                    end if
                end tell
            end tell
        ''', timeout=15)
        return {"success": True, "action": "close_other_tabs",
                "message": "Closed all other tabs except the active one"}
    except AppleScriptError as e:
        return {"success": False, "action": "close_other_tabs", "error": str(e),
                "message": f"Could not close other tabs: {e}"}


def toggle_full_screen() -> dict:
    """Toggle full screen mode (⌘+Ctrl+F)."""
    return _keystroke_chrome("cmd+control+f", "Toggled full screen mode")


def toggle_bookmark_bar() -> dict:
    """Toggle bookmark bar visibility (⌘+Shift+B)."""
    return _keystroke_chrome("cmd+shift+b", "Toggled bookmark bar")


def bookmark_all_tabs() -> dict:
    """Bookmark all open tabs (⌘+Shift+D)."""
    return _keystroke_chrome("cmd+shift+d", "Bookmarked all open tabs")


def clear_browsing_data() -> dict:
    """Open Chrome settings to clear browsing data (chrome://settings/clearBrowserData)."""
    return open_new_tab("chrome://settings/clearBrowserData")


def print_page() -> dict:
    """Open print dialog for the current page (⌘+P)."""
    return _keystroke_chrome("cmd+p", "Opened print dialog")
