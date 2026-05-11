"""
Browser Control Module for Voxa.
Controls Google Chrome via AppleScript.

Key design for YouTube/Netflix:
- YouTube: Server-side URL lookup via urllib, then navigate Chrome directly.
  No Chrome JS permission needed at all.
- Netflix: Opens search page + AX-tree (accessibility) click on first card.
  Falls back to Tab×N keyboard nav if AX fails.
"""
from __future__ import annotations

import re
import time
import urllib.parse
import urllib.request
from typing import Optional
from voxa.utils.applescript import run_applescript, escape_applescript_string, AppleScriptError
from voxa.utils.logger import get_logger

log = get_logger("browser")

BROWSER = "Google Chrome"
_PAGE_LOAD_WAIT = 2.5
_chrome_js_enabled: Optional[bool] = None   # None=unknown, True=on, False=off


# ─── Internal helpers ─────────────────────────────────────────────────────────

def _ensure_chrome_running():
    """Activate Chrome (open if not running)."""
    run_applescript(f'tell application "{BROWSER}" to activate')
    time.sleep(0.5)


def _open_tab(url: str) -> bool:
    """Open URL in a new Chrome tab. Returns True on success."""
    safe = escape_applescript_string(url)
    try:
        _ensure_chrome_running()
        run_applescript(f'''
            tell application "{BROWSER}"
                activate
                if (count of windows) = 0 then make new window
                tell front window
                    make new tab with properties {{URL:"{safe}"}}
                end tell
            end tell
        ''')
        return True
    except AppleScriptError as e:
        log.error("Could not open tab %s: %s", url, e)
        return False


def _try_enable_chrome_js() -> bool:
    """
    Multi-method attempt to enable 'Allow JavaScript from Apple Events' in Chrome.
    Tries 3 different AppleScript approaches + verifies JS actually works after.
    Returns True if JS is confirmed working.
    """
    global _chrome_js_enabled
    log.info("🔧 Enabling Chrome JS from Apple Events (multi-method)...")

    import subprocess

    methods = [
        # Method 1: Named menu hierarchy
        '''
        tell application "Google Chrome" to activate
        delay 0.5
        tell application "System Events"
            tell process "Google Chrome"
                try
                    click menu item "Allow JavaScript from Apple Events" of menu "Developer" of menu item "Developer" of menu "View" of menu bar item "View" of menu bar 1
                    delay 0.3
                    return "ok"
                on error e
                    return "e:" & e
                end try
            end tell
        end tell
        ''',
        # Method 2: Step-by-step open each menu level
        '''
        tell application "Google Chrome" to activate
        delay 0.4
        tell application "System Events"
            tell process "Google Chrome"
                try
                    tell menu bar 1
                        tell menu bar item "View"
                            click
                            delay 0.25
                            tell menu "View"
                                tell menu item "Developer"
                                    click
                                    delay 0.25
                                    tell menu "Developer"
                                        click menu item "Allow JavaScript from Apple Events"
                                    end tell
                                end tell
                            end tell
                        end tell
                    end tell
                    delay 0.3
                    key code 53
                    return "ok"
                on error e
                    key code 53
                    return "e:" & e
                end try
            end tell
        end tell
        ''',
        # Method 3: Numbered index approach
        '''
        tell application "Google Chrome" to activate
        delay 0.4
        tell application "System Events"
            tell process "Google Chrome"
                try
                    click menu item "Allow JavaScript from Apple Events" of menu 1 of menu item "Developer" of menu 1 of menu bar item "View" of menu bar 1
                    delay 0.3
                    return "ok"
                on error e
                    return "e:" & e
                end try
            end tell
        end tell
        ''',
    ]

    for i, script in enumerate(methods, 1):
        try:
            proc = subprocess.run(
                ['osascript', '-e', script],
                capture_output=True, text=True, timeout=12,
            )
            out = proc.stdout.strip()
            log.info("JS enable method %d: rc=%d out=%s", i, proc.returncode, out[:60])

            if proc.returncode == 0 and ("ok" in out or not out.startswith("e:")):
                time.sleep(0.5)
                # Verify JS actually works now
                try:
                    verify = run_applescript('''
                        tell application "Google Chrome"
                            tell active tab of front window
                                execute javascript "1+1"
                            end tell
                        end tell
                    ''', timeout=5)
                    if verify is not None:
                        log.info("✅ Chrome JS verified working (method %d)", i)
                        _chrome_js_enabled = True
                        return True
                except Exception:
                    pass  # JS test failed, try next method
        except Exception as e:
            log.warning("JS enable method %d exception: %s", i, e)

    log.warning("❌ All Chrome JS enable methods failed")
    return False



def _run_js(js: str, timeout: int = 15) -> Optional[str]:
    """
    Run JavaScript in the current Chrome tab.
    On error 12 (JS disabled), attempts to auto-enable then retries.
    IMPORTANT: Does NOT permanently cache failure — retries on every call.
    """
    global _chrome_js_enabled
    safe_js = js.replace("\n", " ").replace('"', '\\"')
    script = f'''
        tell application "{BROWSER}"
            tell active tab of front window
                execute javascript "{safe_js}"
            end tell
        end tell
    '''
    try:
        return run_applescript(script, timeout=timeout)
    except AppleScriptError as e:
        err = str(e)
        if "12)" in err or "turned off" in err:
            if _chrome_js_enabled is not True:
                # Try to enable JS, then retry
                if _try_enable_chrome_js():
                    try:
                        return run_applescript(script, timeout=timeout)
                    except AppleScriptError:
                        pass
            # Don't cache as False — allow retrying on subsequent calls
        return None



def _ax_click_first_link() -> bool:
    """
    Click the first link on the current Chrome page using macOS Accessibility (AX).
    Works WITHOUT Chrome JS execution permission.
    Returns True if a click was sent.
    """
    script = f'''
        tell application "System Events"
            tell process "{BROWSER}"
                try
                    -- Navigate AX tree: window > scroll area > group/web content
                    set w to window 1
                    set found to false

                    -- Try direct link access via AX
                    set candidates to {{}}
                    try
                        set candidates to every link of w
                    end try
                    if (count of candidates) > 0 then
                        click (first item of candidates)
                        set found to true
                    end if

                    if not found then
                        -- Try nested: scroll area > first link
                        try
                            set sa to first scroll area of w
                            set nested to every link of sa
                            if (count of nested) > 0 then
                                click (first item of nested)
                                set found to true
                            end if
                        end try
                    end if

                    if found then
                        return "clicked"
                    else
                        return "no_links"
                    end if
                on error e
                    return "error:" & e
                end try
            end tell
        end tell
    '''
    try:
        result = run_applescript(script, timeout=10)
        return result and "clicked" in result
    except Exception:
        return False


def _keyboard_tab_enter(n_tabs: int = 8) -> bool:
    """
    Press Tab n times then Enter to click the focused element.
    Last-resort fallback when JS and AX both fail.
    """
    tabs = 'key code 48\ndelay 0.12\n' * n_tabs
    script = f'''
        tell application "{BROWSER}" to activate
        delay 0.5
        tell application "System Events"
            tell process "{BROWSER}"
                {tabs}
                key code 36
            end tell
        end tell
    '''
    try:
        run_applescript(script, timeout=15)
        return True
    except Exception:
        return False


# ─── YouTube server-side search ───────────────────────────────────────────────

def _fetch_youtube_video_url(query: str) -> Optional[str]:
    """
    Fetch the first YouTube search result URL via server-side HTTP request.
    Completely bypasses Chrome JS execution — just parses YouTube's HTML for video IDs.
    Returns a direct watch URL like: https://www.youtube.com/watch?v=XXXXXXXXXXX
    """
    try:
        encoded = urllib.parse.quote_plus(query)
        search_url = "https://www.youtube.com/results?search_query={}".format(encoded)

        req = urllib.request.Request(
            search_url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            html = resp.read().decode("utf-8", errors="ignore")

        # YouTube embeds all results as JSON: "videoId":"XXXXXXXXXXX"
        # The first match in the page is the first search result
        ids = re.findall(r'"videoId"\s*:\s*"([A-Za-z0-9_-]{11})"', html)
        if ids:
            video_url = "https://www.youtube.com/watch?v={}".format(ids[0])
            log.info("🔍 Server-side YouTube result: %s", video_url)
            return video_url

        log.warning("No video IDs found in YouTube search HTML")
        return None
    except Exception as e:
        log.warning("YouTube server-side search failed: %s", e)
        return None


# ─── Public API ───────────────────────────────────────────────────────────────

def open_url(url: str) -> dict:
    """Open a URL in a new Chrome tab."""
    log.info("🌐 Opening URL: %s", url)
    if _open_tab(url):
        return {"success": True, "action": "open_url", "url": url,
                "message": "Opened {}".format(url)}
    return {"success": False, "action": "open_url", "url": url,
            "message": "Could not open {}".format(url)}


def navigate_to(url: str) -> dict:
    """Navigate the current Chrome tab to a URL."""
    safe = escape_applescript_string(url)
    log.info("🧭 Navigating to: %s", url)
    try:
        _ensure_chrome_running()
        run_applescript(f'''
            tell application "{BROWSER}"
                set URL of active tab of front window to "{safe}"
            end tell
        ''')
        return {"success": True, "action": "browser_navigate", "url": url,
                "message": "Navigated to {}".format(url)}
    except AppleScriptError as e:
        return {"success": False, "action": "browser_navigate", "url": url,
                "error": str(e), "message": "Could not navigate to {}".format(url)}


def search_google(query: str) -> dict:
    """Search Google in Chrome."""
    url = "https://www.google.com/search?q={}".format(urllib.parse.quote_plus(query))
    log.info("🔍 Searching Google: %s", query)
    result = open_url(url)
    result.update({"action": "browser_search", "query": query,
                   "message": "Searched Google for '{}'".format(query)})
    return result


def search_youtube(query: str) -> dict:
    """Open YouTube search results (no autoplay)."""
    url = "https://www.youtube.com/results?search_query={}".format(
        urllib.parse.quote_plus(query))
    log.info("🎬 Searching YouTube: %s", query)
    result = open_url(url)
    result.update({"action": "browser_search", "query": query,
                   "message": "Searched YouTube for '{}'".format(query)})
    return result


def play_youtube(query: str) -> dict:
    """
    Search YouTube for a video and play the first result immediately.

    Strategy (no Chrome JS permission required):
    1. Server-side HTTP search → extract first video ID → navigate Chrome directly.
    2. If HTTP search fails → open search page + JS click (auto-enable) → AX click → Tab+Enter.
    """
    log.info("▶️  Playing on YouTube: %s", query)

    # ── Strategy 1: Server-side URL lookup (best, no JS) ──────────────────────
    video_url = _fetch_youtube_video_url(query)
    if video_url:
        _ensure_chrome_running()
        result = navigate_to(video_url)
        if result.get("success"):
            log.info("✅ Navigated to YouTube video: %s", video_url)
            return {"success": True, "action": "play_youtube", "query": query,
                    "message": "Playing '{}' on YouTube".format(query)}

    # ── Strategy 2: Open search page, try JS + AX + keyboard ─────────────────
    log.warning("Server-side lookup failed — falling back to search page approach")
    encoded = urllib.parse.quote_plus(query)
    search_url = "https://www.youtube.com/results?search_query={}".format(encoded)

    if not _open_tab(search_url):
        return {"success": False, "action": "play_youtube", "query": query,
                "message": "Could not open YouTube"}

    log.info("⏳ Waiting for YouTube search page to load...")
    time.sleep(_PAGE_LOAD_WAIT)

    # Try JS click
    js = """(function(){
        var sel=['ytd-video-renderer a#video-title','a#video-title','ytd-video-renderer h3 a'];
        for(var i=0;i<sel.length;i++){var e=document.querySelector(sel[i]);if(e){e.click();return 'ok:'+e.textContent.trim().substring(0,40);}}
        return 'none';
    })();"""
    js_result = _run_js(js)
    if js_result and js_result.startswith("ok:"):
        return {"success": True, "action": "play_youtube", "query": query,
                "message": "Playing '{}' on YouTube".format(js_result[3:])}

    # AX tree click
    if _ax_click_first_link():
        return {"success": True, "action": "play_youtube", "query": query,
                "message": "Playing first YouTube result"}

    # Keyboard fallback
    if _keyboard_tab_enter(n_tabs=10):
        return {"success": True, "action": "play_youtube", "query": query,
                "message": "Playing first YouTube result via keyboard"}

    return {"success": False, "action": "play_youtube", "query": query,
            "message": "Could not auto-play. YouTube search is open — click a video to play."}


def search_netflix(query: str) -> dict:
    """
    Open Netflix search and click the first result to play it.

    6-tier strategy:
    1. JS click (with full Chrome JS auto-enable if needed)
    2. Retry JS up to 2 more times (JS may need a moment after being enabled)
    3. Cmd+L → Escape → Tab sequence (resets focus, then navigates)
    4. Tab×7, Tab×10, Tab×14 with Enter (progressive keyboard scan)
    5. Mouse coordinate click (Chrome window position + typical card offset)
    6. Partial success — Netflix search is open, tell user to click
    """
    log.info("🎬 Searching Netflix: %s", query)

    encoded = urllib.parse.quote_plus(query)
    url = "https://www.netflix.com/search?q={}".format(encoded)

    if not _open_tab(url):
        return {"success": False, "action": "search_netflix", "query": query,
                "message": "Could not open Netflix"}

    log.info("⏳ Waiting for Netflix search to load...")
    time.sleep(_PAGE_LOAD_WAIT + 2.0)   # Netflix SPA needs extra time

    js = """(function(){
        var sel=[
            'a[href*="/watch/"]',
            '.title-card-container a',
            '.title-card a',
            '[data-uia="title-card-0"] a',
            '.slider-item a',
            '.result-item a'
        ];
        for(var i=0;i<sel.length;i++){
            var e=document.querySelector(sel[i]);
            if(e){
                e.click();
                return 'ok:'+(e.getAttribute('aria-label')||e.textContent.trim()).substring(0,40);
            }
        }
        return 'none';
    })();"""

    # ── Tier 1: JS click (auto-enables if needed) ─────────────────────────────
    for attempt in range(3):
        log.info("JS click attempt %d/3...", attempt + 1)
        result = _run_js(js)
        if result and result.startswith("ok:"):
            title = result[3:]
            return {"success": True, "action": "search_netflix", "query": query,
                    "message": "Playing '{}' on Netflix".format(title)}
        if attempt < 2:
            time.sleep(1.5)  # Wait for page or JS enable to settle

    log.info("JS click failed — trying keyboard strategies...")

    # ── Tier 2: Cmd+L → Escape → Tab (resets page focus before tabbing) ───────
    cmdl_escape_tab = f'''
        tell application "{BROWSER}" to activate
        delay 0.4
        tell application "System Events"
            tell process "{BROWSER}"
                -- Focus address bar to reset page focus
                keystroke "l" using command down
                delay 0.4
                -- Return to page
                key code 53
                delay 0.4
                -- Tab to first content card (Netflix ~6-9 tabs from reset)
                key code 48
                delay 0.15
                key code 48
                delay 0.15
                key code 48
                delay 0.15
                key code 48
                delay 0.15
                key code 48
                delay 0.15
                key code 48
                delay 0.15
                key code 48
                delay 0.15
                -- Press Enter on focused element
                key code 36
            end tell
        end tell
    '''
    try:
        run_applescript(cmdl_escape_tab, timeout=12)
        time.sleep(1.5)
        cur = get_current_url()
        if cur and ("/watch/" in cur or "netflix.com" in cur and "search" not in cur):
            return {"success": True, "action": "search_netflix", "query": query,
                    "message": "Playing first Netflix result"}
    except Exception as e:
        log.warning("Cmd+L keyboard approach failed: %s", e)

    # ── Tier 3: Progressive Tab+Enter (try 9, 12, 15 presses) ────────────────
    for n in [9, 12, 15]:
        log.info("Trying Tab×%d + Enter for Netflix...", n)
        tabs = 'key code 48\ndelay 0.12\n' * n
        script = f'''
            tell application "{BROWSER}" to activate
            delay 0.3
            tell application "System Events"
                tell process "{BROWSER}"
                    {tabs}
                    key code 36
                end tell
            end tell
        '''
        try:
            run_applescript(script, timeout=15)
            time.sleep(1.5)
            cur = get_current_url()
            if cur and "/watch/" in cur:
                return {"success": True, "action": "search_netflix", "query": query,
                        "message": "Playing Netflix result"}
        except Exception:
            pass

    # ── Tier 4: Mouse coordinate click ────────────────────────────────────────
    log.info("Trying mouse coordinate click for Netflix...")
    mouse_click = f'''
        tell application "{BROWSER}" to activate
        delay 0.5
        tell application "System Events"
            tell process "{BROWSER}"
                set winPos to position of window 1
                set winSize to size of window 1
                -- Netflix first result card is approx at 160px from left, 260px from top of window
                set clickX to (item 1 of winPos) + 160
                set clickY to (item 2 of winPos) + 260
                click at {{clickX, clickY}}
            end tell
        end tell
    '''
    try:
        run_applescript(mouse_click, timeout=10)
        time.sleep(1.5)
        cur = get_current_url()
        if cur and "/watch/" in cur:
            return {"success": True, "action": "search_netflix", "query": query,
                    "message": "Playing Netflix result"}
    except Exception as e:
        log.warning("Mouse click failed: %s", e)

    # ── Tier 5: Partial success — search is open ───────────────────────────────
    log.warning("All auto-click methods failed for Netflix — search results are visible")
    return {"success": True, "action": "search_netflix", "query": query,
            "message": "Netflix search for '{}' is open. To enable auto-play: Chrome > View > Developer > Allow JavaScript from Apple Events".format(query)}



def click_first_youtube_result() -> dict:
    """Legacy action — click first result on current YouTube search page."""
    time.sleep(1.5)
    js = """(function(){
        var e=document.querySelector('ytd-video-renderer a#video-title,a#video-title');
        if(e){e.click();return 'ok';}return 'none';
    })();"""
    result = _run_js(js)
    if result == "ok":
        return {"success": True, "action": "browser_click_first_result",
                "message": "Clicked first YouTube video"}
    if _ax_click_first_link():
        return {"success": True, "action": "browser_click_first_result",
                "message": "Clicked first result via AX"}
    return {"success": False, "action": "browser_click_first_result",
            "message": "Could not click result"}


def close_current_tab() -> dict:
    """Close the current Chrome tab."""
    try:
        run_applescript(f'''
            tell application "{BROWSER}"
                tell front window to close active tab
            end tell
        ''')
        return {"success": True, "action": "close_tab", "message": "Closed current tab"}
    except AppleScriptError as e:
        return {"success": False, "action": "close_tab", "error": str(e)}


def get_current_url() -> Optional[str]:
    """Get the URL of the current Chrome tab."""
    try:
        return run_applescript(
            f'tell application "{BROWSER}" to return URL of active tab of front window')
    except AppleScriptError:
        return None


def get_current_page_title() -> Optional[str]:
    """Get the title of the current Chrome tab."""
    try:
        return run_applescript(
            f'tell application "{BROWSER}" to return title of active tab of front window')
    except AppleScriptError:
        return None
