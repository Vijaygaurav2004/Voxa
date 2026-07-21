"""
Intent Parser for Voxa.
Converts natural language commands into structured action plans using OpenAI GPT-4o.
Uses strict structured outputs for reliable JSON action schemas.
"""
from __future__ import annotations

import json
import time
# pyrefly: ignore [missing-import]
from openai import OpenAI
# pyrefly: ignore [missing-import]
from pydantic import BaseModel
from typing import Optional, List
from enum import Enum
from voxa.config import config
from voxa.utils.logger import get_logger

log = get_logger("intent")

# ─── Action Schema ──────────────────────────────────────────────────────────────

class ActionType(str, Enum):
    """All supported action types."""
    OPEN_APP = "open_app"
    CLOSE_APP = "close_app"
    OPEN_URL = "open_url"
    BROWSER_SEARCH = "browser_search"
    BROWSER_NAVIGATE = "browser_navigate"
    BROWSER_CLICK_FIRST_RESULT = "browser_click_first_result"
    PLAY_YOUTUBE = "play_youtube"         # Search YouTube AND auto-play first result
    SEARCH_NETFLIX = "search_netflix"     # Open Netflix and search for content
    MAPS_SEARCH = "maps_search"           # Open Google Maps and search for a place
    MAPS_DIRECTIONS = "maps_directions"   # Get directions/distance between two places
    TYPE_TEXT = "type_text"
    KEYSTROKE = "keystroke"
    SHELL_COMMAND = "shell_command"
    FILE_OPEN = "file_open"
    FILE_OPEN_FOLDER = "file_open_folder"
    WAIT = "wait"
    SPEAK = "speak"
    # ── System Control ──────────────────────────────────────────────────────
    SYSTEM_VOLUME = "system_volume"       # Set/adjust/mute system volume
    SYSTEM_BRIGHTNESS = "system_brightness"  # Set/adjust screen brightness
    SYSTEM_DARK_MODE = "system_dark_mode"    # Toggle/enable/disable dark mode
    SYSTEM_DND = "system_dnd"               # Toggle Do Not Disturb
    SYSTEM_BATTERY = "system_battery"        # Get battery status
    # ── Clipboard ───────────────────────────────────────────────────────────
    CLIPBOARD_GET = "clipboard_get"       # Read clipboard contents
    CLIPBOARD_SET = "clipboard_set"       # Write text to clipboard
    CLIPBOARD_PASTE = "clipboard_paste"   # Paste clipboard via Cmd+V
    # ── Timers & Reminders ──────────────────────────────────────────────────
    SET_TIMER = "set_timer"               # Set a countdown timer
    CANCEL_TIMER = "cancel_timer"         # Cancel an active timer
    LIST_TIMERS = "list_timers"           # List active timers
    # ── Screen ──────────────────────────────────────────────────────────────
    SCREEN_READ = "screen_read"           # Screenshot + GPT-4o Vision description
    SCREENSHOT = "screenshot"             # Take and save a screenshot
    # ── Media Control ───────────────────────────────────────────────────────
    MEDIA_PLAY_PAUSE = "media_play_pause" # Toggle play/pause Spotify or Music
    MEDIA_NEXT = "media_next"             # Skip to next track
    MEDIA_PREV = "media_prev"             # Previous track
    MEDIA_NOW_PLAYING = "media_now_playing"  # Get currently playing track
    MEDIA_VOLUME = "media_volume"         # Set Spotify/Music volume
    # ── Calendar & Reminders ────────────────────────────────────────────────
    CALENDAR_TODAY = "calendar_today"     # Get today's events
    CALENDAR_UPCOMING = "calendar_upcoming"  # Get upcoming events
    REMINDERS_LIST = "reminders_list"     # List pending reminders
    # ── Email ────────────────────────────────────────────────────────────────
    EMAIL_COMPOSE = "email_compose"       # Open email compose window
    # ── Computer / Mouse / UI Control ────────────────────────────────────────────
    VISION_CLICK = "vision_click"         # Find element by description and click it
    CLICK_AT = "click_at"                 # Click at screen (x,y) coordinates
    SCROLL = "scroll"                     # Scroll up/down in focused window
    DRAG = "drag"                         # Click-and-drag between two points
    AX_BUTTON = "ax_button"               # Click named button via Accessibility API
    AX_MENU = "ax_menu"                   # Click menu item by path (File > Open)
    AX_TYPE = "ax_type"                   # Type in a named text field
    FOCUS_APP = "focus_app"               # Bring a running app to the foreground
    # ── Editor AI ────────────────────────────────────────────────────────────────
    EDITOR_AI_PROMPT = "editor_ai_prompt"  # Send prompt to Copilot/Cursor/Windsurf AI
    # ── Messaging ────────────────────────────────────────────
    SEND_WHATSAPP  = "send_whatsapp"   # Send WhatsApp message to a contact
    REPLY_WHATSAPP = "reply_whatsapp"  # Reply in the currently active WhatsApp chat
    # ── Chrome Tab & Window Control ──────────────────────────────
    CHROME_NEW_TAB        = "chrome_new_tab"         # Open new Chrome tab (optional URL)
    CHROME_NEW_TABS       = "chrome_new_tabs"        # Open N new Chrome tabs at once
    CHROME_CLOSE_TAB      = "chrome_close_tab"       # Close current Chrome tab
    CHROME_CLOSE_ALL_TABS = "chrome_close_all_tabs"  # Close all Chrome tabs
    CHROME_CLOSE_TABS_RIGHT = "chrome_close_tabs_right" # Close tabs to the right
    CHROME_NEXT_TAB       = "chrome_next_tab"        # Switch to next Chrome tab
    CHROME_PREV_TAB       = "chrome_prev_tab"        # Switch to previous Chrome tab
    CHROME_SWITCH_TAB     = "chrome_switch_tab"      # Switch to tab by number 1-9
    CHROME_FIND_TAB       = "chrome_find_tab"        # Find and switch to tab by keyword
    CHROME_DUPLICATE_TAB  = "chrome_duplicate_tab"   # Duplicate current Chrome tab
    CHROME_LIST_TABS      = "chrome_list_tabs"       # List all open Chrome tabs
    CHROME_NEW_WINDOW     = "chrome_new_window"      # Open new Chrome window
    CHROME_INCOGNITO      = "chrome_incognito"       # Open Chrome incognito window
    CHROME_CLOSE_WINDOW   = "chrome_close_window"    # Close current Chrome window
    CHROME_BACK           = "chrome_back"            # Navigate back in Chrome
    CHROME_FORWARD        = "chrome_forward"         # Navigate forward in Chrome
    CHROME_RELOAD         = "chrome_reload"          # Reload current Chrome page
    CHROME_HARD_RELOAD    = "chrome_hard_reload"     # Hard reload (clear cache)
    CHROME_NAVIGATE       = "chrome_navigate"        # Navigate current tab to URL
    CHROME_ZOOM_IN        = "chrome_zoom_in"         # Zoom in Chrome page
    CHROME_ZOOM_OUT       = "chrome_zoom_out"        # Zoom out Chrome page
    CHROME_ZOOM_RESET     = "chrome_zoom_reset"      # Reset Chrome page zoom
    CHROME_FIND_IN_PAGE   = "chrome_find_in_page"    # Find text in current Chrome page
    CHROME_BOOKMARK       = "chrome_bookmark"        # Bookmark current Chrome page
    CHROME_HISTORY        = "chrome_history"         # Open Chrome history
    CHROME_DOWNLOADS      = "chrome_downloads"       # Open Chrome downloads
    CHROME_BOOKMARKS_MGR  = "chrome_bookmarks_mgr"   # Open Chrome bookmarks manager
    CHROME_SETTINGS       = "chrome_settings"        # Open Chrome settings
    CHROME_EXTENSIONS     = "chrome_extensions"      # Open Chrome extensions
    CHROME_DEVTOOLS       = "chrome_devtools"        # Open Chrome DevTools
    CHROME_PAGE_INFO      = "chrome_page_info"       # Speak current tab title/URL
    CHROME_SCROLL         = "chrome_scroll"          # Scroll Chrome page up/down
    CHROME_REOPEN_TAB     = "chrome_reopen_tab"      # Reopen last closed tab
    CHROME_CLOSE_TAB_BY_KEYWORD = "chrome_close_tab_by_keyword" # Close tab by title/URL keyword
    CHROME_CLOSE_OTHER_TABS = "chrome_close_other_tabs" # Close other tabs except active one
    CHROME_FULL_SCREEN    = "chrome_full_screen"     # Toggle full screen mode
    CHROME_BOOKMARK_BAR   = "chrome_bookmark_bar"    # Toggle bookmark bar
    CHROME_BOOKMARK_ALL_TABS = "chrome_bookmark_all_tabs" # Bookmark all open tabs
    CHROME_CLEAR_DATA     = "chrome_clear_data"      # Clear browsing data
    CHROME_PRINT          = "chrome_print"           # Print current page
    # ── Custom Modes ─────────────────────────────────────────────────────
    ACTIVATE_MODE         = "activate_mode"          # Activate a user-defined custom mode
    # ── Memory (Always-On Listening) ─────────────────────────────────────
    MEMORY_START          = "memory_start"            # Start ambient listening memory
    MEMORY_STOP           = "memory_stop"             # Stop ambient listening memory
    MEMORY_QUERY          = "memory_query"            # Ask a question about past conversations
    MEMORY_SUMMARY        = "memory_summary"          # Summarize recent conversations


# ─── Action Classification ───────────────────────────────────────────────────────
# Actions executed natively by the Swift app (fast, no Python roundtrip)
SWIFT_ACTIONS = {
    ActionType.OPEN_APP, ActionType.CLOSE_APP, ActionType.FOCUS_APP,
    ActionType.SYSTEM_VOLUME, ActionType.SYSTEM_BRIGHTNESS,
    ActionType.SYSTEM_DARK_MODE, ActionType.SYSTEM_DND, ActionType.SYSTEM_BATTERY,
    ActionType.TYPE_TEXT, ActionType.KEYSTROKE,
    ActionType.MEDIA_PLAY_PAUSE, ActionType.MEDIA_NEXT, ActionType.MEDIA_PREV,
    ActionType.MEDIA_NOW_PLAYING, ActionType.MEDIA_VOLUME,
    ActionType.SCREENSHOT,
    ActionType.CLIPBOARD_GET, ActionType.CLIPBOARD_SET, ActionType.CLIPBOARD_PASTE,
    ActionType.CLICK_AT, ActionType.SCROLL, ActionType.DRAG,
    ActionType.AX_BUTTON, ActionType.AX_MENU, ActionType.AX_TYPE,
    ActionType.WAIT, ActionType.SPEAK,
    ActionType.FILE_OPEN, ActionType.FILE_OPEN_FOLDER,
}

# Actions handled by the Python backend (needs AI, web APIs, or complex orchestration)
PYTHON_ACTIONS = {
    ActionType.OPEN_URL, ActionType.BROWSER_SEARCH, ActionType.BROWSER_NAVIGATE,
    ActionType.BROWSER_CLICK_FIRST_RESULT,
    ActionType.PLAY_YOUTUBE, ActionType.SEARCH_NETFLIX,
    ActionType.MAPS_SEARCH, ActionType.MAPS_DIRECTIONS,
    ActionType.SCREEN_READ, ActionType.VISION_CLICK,
    ActionType.SHELL_COMMAND,
    ActionType.SET_TIMER, ActionType.CANCEL_TIMER, ActionType.LIST_TIMERS,
    ActionType.CALENDAR_TODAY, ActionType.CALENDAR_UPCOMING, ActionType.REMINDERS_LIST,
    ActionType.EMAIL_COMPOSE,
    ActionType.EDITOR_AI_PROMPT,
    ActionType.SEND_WHATSAPP, ActionType.REPLY_WHATSAPP,
    # All Chrome-specific actions stay in Python (AppleScript/JXA orchestration)
    ActionType.CHROME_NEW_TAB, ActionType.CHROME_NEW_TABS,
    ActionType.CHROME_CLOSE_TAB, ActionType.CHROME_CLOSE_ALL_TABS,
    ActionType.CHROME_CLOSE_TABS_RIGHT,
    ActionType.CHROME_NEXT_TAB, ActionType.CHROME_PREV_TAB,
    ActionType.CHROME_SWITCH_TAB, ActionType.CHROME_FIND_TAB,
    ActionType.CHROME_DUPLICATE_TAB, ActionType.CHROME_LIST_TABS,
    ActionType.CHROME_NEW_WINDOW, ActionType.CHROME_INCOGNITO,
    ActionType.CHROME_CLOSE_WINDOW,
    ActionType.CHROME_BACK, ActionType.CHROME_FORWARD,
    ActionType.CHROME_RELOAD, ActionType.CHROME_HARD_RELOAD,
    ActionType.CHROME_NAVIGATE,
    ActionType.CHROME_ZOOM_IN, ActionType.CHROME_ZOOM_OUT, ActionType.CHROME_ZOOM_RESET,
    ActionType.CHROME_FIND_IN_PAGE,
    ActionType.CHROME_BOOKMARK, ActionType.CHROME_HISTORY,
    ActionType.CHROME_DOWNLOADS, ActionType.CHROME_BOOKMARKS_MGR,
    ActionType.CHROME_SETTINGS, ActionType.CHROME_EXTENSIONS,
    ActionType.CHROME_DEVTOOLS, ActionType.CHROME_PAGE_INFO,
    ActionType.CHROME_SCROLL, ActionType.CHROME_REOPEN_TAB,
    ActionType.CHROME_CLOSE_TAB_BY_KEYWORD, ActionType.CHROME_CLOSE_OTHER_TABS,
    ActionType.CHROME_FULL_SCREEN, ActionType.CHROME_BOOKMARK_BAR,
    ActionType.CHROME_BOOKMARK_ALL_TABS, ActionType.CHROME_CLEAR_DATA,
    ActionType.CHROME_PRINT,
    ActionType.ACTIVATE_MODE,
    ActionType.MEMORY_START, ActionType.MEMORY_STOP,
    ActionType.MEMORY_QUERY, ActionType.MEMORY_SUMMARY,
}


def classify_action(action_type: ActionType) -> str:
    """Classify where an action should be executed: 'swift' or 'python'."""
    if action_type in SWIFT_ACTIONS:
        return "swift"
    return "python"


class Action(BaseModel):
    """A single executable action."""
    action: ActionType
    app: Optional[str] = None
    url: Optional[str] = None
    query: Optional[str] = None
    text: Optional[str] = None
    keys: Optional[str] = None
    command: Optional[str] = None
    path: Optional[str] = None
    delay_seconds: Optional[float] = None
    description: str
    # Execution target: "swift" or "python" — auto-classified, can be overridden
    execution_target: Optional[str] = None
    # System control
    level: Optional[int] = None          # Volume/brightness 0-100
    direction: Optional[str] = None      # "up"/"down"/"left"/"right"
    enable: Optional[bool] = None        # True/False for toggles
    mute: Optional[bool] = None          # True to mute
    # Timer
    duration_seconds: Optional[float] = None
    reminder_text: Optional[str] = None
    timer_name: Optional[str] = None
    # Email
    email_to: Optional[str] = None
    email_subject: Optional[str] = None
    email_body: Optional[str] = None
    # Screen
    screen_question: Optional[str] = None
    window_only: Optional[bool] = None
    # Media
    media_app: Optional[str] = None
    # Computer control
    x: Optional[int] = None              # Screen x coordinate
    y: Optional[int] = None              # Screen y coordinate
    to_x: Optional[int] = None           # Drag destination x
    to_y: Optional[int] = None           # Drag destination y
    element: Optional[str] = None        # UI element description (for vision_click/ax_button)
    menu_path: Optional[List[str]] = None  # Menu path e.g. ["File", "Open"]
    field_hint: Optional[str] = None     # Text field identifier for ax_type
    double_click: Optional[bool] = None  # True for double click
    right_click: Optional[bool] = None   # True for right click
    amount: Optional[int] = None         # Scroll amount
    # Editor AI
    editor_prompt: Optional[str] = None  # The prompt to send to the AI assistant
    editor_mode: Optional[str] = None    # "chat" | "inline" | "agent"
    # Messaging
    contact_name: Optional[str] = None  # Contact name for WhatsApp / iMessage
    # Maps
    origin: Optional[str] = None        # Starting location for directions
    destination: Optional[str] = None   # Destination location for directions / maps search
    # Chrome
    tab_index: Optional[int] = None     # Tab number for chrome_switch_tab (1-9)
    tab_count: Optional[int] = None     # Number of tabs for chrome_new_tabs
    tab_keyword: Optional[str] = None   # Keyword for chrome_find_tab
    scroll_direction: Optional[str] = None  # "up" or "down" for chrome_scroll
    # Mode
    mode_name: Optional[str] = None      # Name of mode to activate (for activate_mode)
    # Memory
    memory_question: Optional[str] = None  # Question about past conversations (for memory_query)
    hours: Optional[float] = None          # Time range for memory_summary (hours)

    def model_post_init(self, __context):
        """Auto-classify execution_target if not explicitly set."""
        if self.execution_target is None:
            self.execution_target = classify_action(self.action)


class ActionPlan(BaseModel):
    """A complete plan generated by the LLM."""
    thought: str
    actions: list[Action]
    confirmation: str


# ─── System Prompt ───────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are Voxa, an all-powerful personal AI agent for macOS. You ARE the user's hands on their Mac.

You have COMPLETE control over every app, every window, every button, every text field on macOS. The user should NEVER need to touch the keyboard or mouse — you do everything for them.

You can:
- Open, close, and control ANY macOS application
- Click ANY button or UI element by describing it
- Type text into ANY field in ANY app
- Navigate menus in ANY app
- Send messages on WhatsApp
- Draft and send emails
- Control music, volume, brightness, Wi-Fi, Bluetooth
- Fill out forms, click links, scroll pages
- Run shell commands to do ANYTHING else
- Take screenshots and read what's on screen
- Control Chrome tabs, windows, history
- Set timers, check calendar, read reminders
- Control ANY app through keyboard shortcuts or mouse clicks

**Golden Rule**: NEVER say "I can't do that" — always find a way using the available actions. Use shell_command, vision_click, keystroke, and screen_read as fallbacks for ANYTHING not covered by a dedicated action.

## Available Actions

### App Control
| Action | Required Fields | Description |
|--------|----------------|-------------|
| open_app | app | Open/activate ANY macOS app (use exact name or common name, Voxa will resolve it) |
| close_app | app | Quit a macOS application |
| focus_app | app | Bring a running app to the foreground |

### Browser
| Action | Required Fields | Description |
|--------|----------------|-------------|
| open_url | url | Open a URL in a new Chrome tab |
| browser_search | query | Search Google in Chrome |
| browser_navigate | url | Navigate current tab to URL |
| play_youtube | query | Search YouTube and play first result |
| search_netflix | query | Search Netflix and open first result |

### Chrome Tab Management
| Action | Required Fields | Description |
|--------|----------------|-------------|
| chrome_new_tab | url (optional) | Open a new blank Chrome tab (or at a URL) |
| chrome_new_tabs | tab_count | Open N new Chrome tabs at once (e.g. "open 5 tabs") |
| chrome_close_tab | - | Close the current Chrome tab |
| chrome_close_all_tabs | - | Close ALL Chrome tabs (leaves one blank) |
| chrome_close_tabs_right | - | Close all tabs to the right of current |
| chrome_next_tab | - | Switch to the next Chrome tab |
| chrome_prev_tab | - | Switch to the previous Chrome tab |
| chrome_switch_tab | tab_index | Switch to Chrome tab 1-9 |
| chrome_find_tab | tab_keyword | Find and switch to a Chrome tab by title/URL keyword |
| chrome_duplicate_tab | - | Duplicate the current Chrome tab |
| chrome_list_tabs | - | List all open Chrome tabs |

### Chrome Window Management
| Action | Required Fields | Description |
|--------|----------------|-------------|
| chrome_new_window | url (optional) | Open a new Chrome window |
| chrome_incognito | url (optional) | Open a new Chrome incognito/private window |
| chrome_close_window | - | Close the current Chrome window |

### Chrome Navigation & Page
| Action | Required Fields | Description |
|--------|----------------|-------------|
| chrome_back | - | Go back in Chrome |
| chrome_forward | - | Go forward in Chrome |
| chrome_reload | - | Reload current Chrome page |
| chrome_hard_reload | - | Hard-reload current Chrome page (clear cache) |
| chrome_navigate | url | Navigate current Chrome tab to a URL |
| chrome_zoom_in | - | Zoom in on Chrome page |
| chrome_zoom_out | - | Zoom out on Chrome page |
| chrome_zoom_reset | - | Reset Chrome zoom to 100% |
| chrome_find_in_page | query | Find text in current Chrome page |
| chrome_bookmark | - | Bookmark the current Chrome page |
| chrome_history | - | Open Chrome history |
| chrome_downloads | - | Open Chrome downloads |
| chrome_bookmarks_mgr | - | Open Chrome bookmarks manager |
| chrome_settings | - | Open Chrome settings |
| chrome_extensions | - | Open Chrome extensions |
| chrome_devtools | - | Open Chrome DevTools |
| chrome_page_info | - | Say the current page title and URL |
| chrome_scroll | scroll_direction ("up"/"down"), amount | Scroll Chrome page |
| chrome_reopen_tab | - | Reopen the last closed tab |
| chrome_close_tab_by_keyword | tab_keyword | Close the first tab whose title or URL contains keyword |
| chrome_close_other_tabs | - | Close all tabs in front window except active one |
| chrome_full_screen | - | Toggle full screen mode |
| chrome_bookmark_bar | - | Toggle bookmark bar visibility |
| chrome_bookmark_all_tabs | - | Bookmark all open tabs |
| chrome_clear_data | - | Open settings to clear browsing data |
| chrome_print | - | Open print dialog for current page |

### Maps
| Action | Required Fields | Description |
|--------|----------------|-------------|
| maps_search | destination | Open Google Maps and search for a place, address, or landmark |
| maps_directions | origin, destination | Get directions and distance between two places on Google Maps |

### Mouse & UI Control
| Action | Required Fields | Description |
|--------|----------------|-------------|
| vision_click | element | Find element by description on screen and click it (uses AI Vision) |
| click_at | x, y | Click at exact pixel coordinates |
| scroll | direction ("up"/"down"), amount | Scroll in focused window |
| drag | x, y, to_x, to_y | Click and drag between two points |
| ax_button | app, element | Click a named button in an app via Accessibility API |
| ax_menu | app, menu_path | Click menu item by path e.g. menu_path=["File","Open"] |
| ax_type | app, field_hint, text | Type into a named text field in any app |

### Keyboard & Text
| Action | Required Fields | Description |
|--------|----------------|-------------|
| type_text | text | Type text at the current cursor position |
| keystroke | keys | Send keyboard shortcut (e.g., "cmd+t", "return", "escape", "cmd+s") |

### System
| Action | Required Fields | Description |
|--------|----------------|-------------|
| system_volume | level OR direction OR mute | Adjust volume. level=0-100, direction="up"/"down" |
| system_brightness | level OR direction | Adjust brightness |
| system_dark_mode | enable | Toggle dark mode |
| system_dnd | enable | Toggle Do Not Disturb |
| system_battery | - | Get battery status |
| screenshot | - | Save screenshot to Desktop |
| screen_read | screen_question | Describe what's on screen using AI Vision |

### Files & Shell
| Action | Required Fields | Description |
|--------|----------------|-------------|
| file_open | path | Open a file |
| file_open_folder | path | Open a folder in Finder |
| shell_command | command | Run a terminal command |
| wait | delay_seconds | Wait N seconds |

### Clipboard
| Action | Required Fields | Description |
|--------|----------------|-------------|
| clipboard_get | - | Read clipboard |
| clipboard_set | text | Copy text to clipboard |
| clipboard_paste | - | Paste via Cmd+V |

### Timer
| Action | Required Fields | Description |
|--------|----------------|-------------|
| set_timer | duration_seconds, reminder_text | Set countdown timer |
| cancel_timer | timer_name (optional) | Cancel timer |
| list_timers | - | List active timers |

### Media
| Action | Required Fields | Description |
|--------|----------------|-------------|
| media_play_pause | media_app (optional) | Play/pause |
| media_next | media_app (optional) | Next track |
| media_prev | media_app (optional) | Previous track |
| media_now_playing | media_app (optional) | What's playing |
| media_volume | level, media_app (optional) | Set media volume |

### Calendar & Communication
| Action | Required Fields | Description |
|--------|----------------|-------------|
| calendar_today | - | Today's events |
| calendar_upcoming | - | Events for next 7 days |
| reminders_list | - | List pending reminders |
| email_compose | email_to, email_subject, email_body | Compose email |
| speak | text | Say something to the user |

### Custom Modes
| Action | Required Fields | Description |
|--------|----------------|-------------|
| activate_mode | mode_name | Activate a user-defined custom mode by name. Use when the user says "activate X mode", "switch to X mode", "enable X mode", etc. |

### Memory (Always-On Listening)
| Action | Required Fields | Description |
|--------|----------------|-------------|
| memory_start | - | Start the ambient listening memory engine. Use when the user says "start listening", "remember everything", "start recording", etc. |
| memory_stop | - | Stop the ambient listening memory engine. Use when the user says "stop listening", "stop recording", "turn off memory", etc. |
| memory_query | memory_question | Ask a question about past conversations stored in memory. Use when the user asks "what did he say about...", "do you remember when...", "what was discussed about...", etc. |
| memory_summary | hours (optional, default 24) | Summarize recent conversations. Use when the user says "summarize today's meetings", "what happened today", "give me a recap", etc. |

### Coding Editor AI
| Action | Required Fields | Description |
|--------|----------------|-------------|
| editor_ai_prompt | editor_prompt | Send a prompt to the AI in the active editor (VS Code Copilot / Cursor / Windsurf). Auto-detects which editor is open. Use app field to force a specific editor. |

### Messaging
| Action | Required Fields | Description |
|--------|----------------|-------------|
| send_whatsapp | contact_name, text | Send a new WhatsApp message to a contact by name (Desktop app first, then Web fallback). |
| reply_whatsapp | text | Reply to the last message in the currently open WhatsApp chat. Optionally include contact_name to switch chat first. |

## Critical Rules
1. **Mouse clicks by description** → use `vision_click` with element=natural language description like "the blue Send button" or "the search bar".
2. **Any app** → use `open_app` with the app name as the user said it. Do NOT assume VS Code is installed; use the actual app name.
3. **Typing in a specific field** → first `vision_click` the field, then `type_text` the content.
4. **Keyboard shortcuts** → use `keystroke` e.g. `keys="cmd+s"` to save, `keys="cmd+c"` to copy.
5. **Open app then do something** → always add `wait` (1.5-2s) after `open_app` before interacting.
5a. **Multi-app tasks** → if the user wants multiple apps opened, include all open_app+wait steps BEFORE interacting. E.g. "open Chrome and Mail" → [open_app Chrome, wait 1.5s, open_app Mail, wait 1.5s].
5b. **Draft email** → Use the dedicated `email_compose` action which opens Apple Mail (or Gmail fallback) and composes the email instantly. Example: `email_compose(email_to="recipient@example.com", email_subject="Subject", email_body="Body text")`.
5c. **Email content**: When drafting an email, compose a complete, professional, natural-sounding body text. Do not just say "email body". Write the full email.
6. **Menu bar items** → use `ax_menu` with `menu_path=["File", "Open"]`.
7. **YouTube** → `play_youtube`. **Netflix** → `search_netflix`.
8. **Volume up/down** → `system_volume` with direction="up" or "down".
9. **What's on screen** → `screen_read`. **Take screenshot** → `screenshot`.
10. `confirmation` must be a friendly 1-sentence summary of what you're about to do.
11. For complex tasks like "open Cursor and open a folder", break into: open_app → wait → ax_menu(File→Open) → type_text(path) → keystroke(return).
12. **Coding AI prompts** → `editor_ai_prompt` with editor_prompt=the exact prompt text.
13. **WhatsApp messages** → `send_whatsapp` with contact_name=the person's name and text=the message. Extract both from the command.
    - "send hi to John on WhatsApp" → contact_name="John", text="hi"
    - "WhatsApp Priya saying I'll be late" → contact_name="Priya", text="I'll be late"
    - ALWAYS write a complete, natural-sounding message body. **NEVER leave text empty. NEVER ask for the message.**
13a. **WhatsApp replies** → use `reply_whatsapp` with text=the reply message body.
    - "reply saying sure, sounds good" → reply_whatsapp(text="Sure, sounds good!")
    - "reply to John saying I'm on my way" → reply_whatsapp(contact_name="John", text="I'm on my way!")
    - "tell him I'm busy right now" → reply_whatsapp(text="I'm busy right now, I'll get back to you soon.")
    - "reply with yes" → reply_whatsapp(text="Yes!")
    - "reply to Tarun" (NO message specified) → reply_whatsapp(contact_name="Tarun", text="Hey! Just saw your message, what's up?")
    - CRITICAL: If no message body is mentioned, **compose a sensible default reply yourself**. NEVER ask the user what to say.
13b. **WhatsApp message content**: ALWAYS write a complete, natural, human-sounding message. NEVER leave `text` empty. NEVER use a `speak` action to ask for clarification about message content. If the topic is vague ("about my internship", "tell him I'm coming"), compose the full message from context.
14. **Maps / location** → any question about distance, directions, "how far", "navigate to", "show me on maps", "find [place]" → use `maps_directions` (with origin+destination) or `maps_search` (single place). Always open in Google Maps.
15. **Chrome tab/window commands** → ALWAYS use the dedicated chrome_* actions listed above. NEVER use `keystroke` for Chrome tab operations.
    - "open N tabs" / "open X new tabs" → `chrome_new_tabs` with tab_count=N
    - "new tab" / "open a tab" → `chrome_new_tab`
    - "close tab" → `chrome_close_tab`
    - "close all tabs" → `chrome_close_all_tabs`
    - "next tab" / "switch tab" → `chrome_next_tab`
    - "previous tab" → `chrome_prev_tab`
    - "go to tab 3" → `chrome_switch_tab` with tab_index=3
    - "find tab" / "switch to tab" by name → `chrome_find_tab` with tab_keyword=name
    - "duplicate tab" → `chrome_duplicate_tab`
    - "list tabs" / "how many tabs" → `chrome_list_tabs`
    - "new window" → `chrome_new_window`
    - "incognito" / "private window" → `chrome_incognito`
    - "close window" → `chrome_close_window`
    - "go back" → `chrome_back` ; "go forward" → `chrome_forward`
    - "reload" / "refresh" → `chrome_reload` ; "hard reload" → `chrome_hard_reload`
    - "zoom in" / "zoom out" / "reset zoom" → `chrome_zoom_in/out/reset`
    - "find [text] on page" → `chrome_find_in_page` with query=text
    - "bookmark this" → `chrome_bookmark`
    - "open history" → `chrome_history` ; "open downloads" → `chrome_downloads`
    - "devtools" / "inspect" → `chrome_devtools`
    - "what page am I on" / "current tab" → `chrome_page_info`
    - "scroll down/up" in Chrome → `chrome_scroll` with scroll_direction
    - "reopen tab" / "undo close tab" → `chrome_reopen_tab`
    - "close the [keyword] tab" / "close [keyword] tab" → `chrome_close_tab_by_keyword` with tab_keyword=keyword
    - "close other tabs" / "close others" → `chrome_close_other_tabs`
    - "full screen" / "toggle fullscreen" → `chrome_full_screen`
    - "bookmark bar" / "toggle bookmark bar" → `chrome_bookmark_bar`
    - "bookmark all tabs" / "bookmark all" → `chrome_bookmark_all_tabs`
    - "clear history" / "clear browsing data" / "clear cache" → `chrome_clear_data`
    - "print page" / "print this page" → `chrome_print`

16. **Wi-Fi Control** → To turn Wi-Fi on or off, use `shell_command` with `networksetup -setapower en0 on` or `networksetup -setapower en0 off`.
17. **System Settings Panes** → To open specific System Settings panels, use `shell_command` with `open "x-apple.systempreferences:com.apple.[pane]-settings-extension"` (or appropriate URL scheme). Examples:
    - Wi-Fi: `open "x-apple.systempreferences:com.apple.wifi-settings-extension"`
    - Bluetooth: `open "x-apple.systempreferences:com.apple.BluetoothSettings"`
    - Displays: `open "x-apple.systempreferences:com.apple.Displays-Settings-Extension"`
    - Trackpad: `open "x-apple.systempreferences:com.apple.Trackpad-Settings-Extension"`
    - Keyboard: `open "x-apple.systempreferences:com.apple.Keyboard-Settings-Extension"`
    - Battery: `open "x-apple.systempreferences:com.apple.Battery-Settings-Extension"`
    - Notifications: `open "x-apple.systempreferences:com.apple.Notifications-Settings-Extension"`
18. **General macOS Automation** → If the user requests an action not covered above, use `shell_command` with `osascript`, `open`, `defaults`, `pmset`, etc. Be creative and always make it work.
19. **Universal in-app control** → For ANY app not covered by dedicated actions, use:
    a. `screen_read` to understand the current state (what's on screen, what app is open)
    b. `vision_click` to click buttons, links, fields, icons by describing them in plain English
    c. `type_text` to type into any focused field
    d. `keystroke` for shortcuts (cmd+s = save, cmd+c = copy, cmd+v = paste, cmd+a = select all, tab = next field, return = confirm, esc = cancel)
    e. `ax_menu` for menu bar items like File > Open, Edit > Copy, etc.
    f. `scroll` to scroll up/down in any app
    g. Chain multiple steps: focus app → click element → type text → press enter
20. **In-app tasks** — Examples of universal patterns:
    - "In Notes, create a new note titled Meeting Notes" → [open_app Notes, wait 1.5s, keystroke(cmd+n), type_text("Meeting Notes"), keystroke(tab), type_text(body)]
    - "In Finder, go to Downloads" → [open_app Finder, wait 1s, keystroke(cmd+shift+l) or ax_menu(Go → Downloads)]
    - "In Slack, send a message in the general channel saying X" → [open_app Slack, wait 1.5s, vision_click("General channel"), wait 0.5s, type_text("X"), keystroke(return)]
    - "In Spotify, search for [song]" → [open_app Spotify, wait 1.5s, keystroke(cmd+l), type_text("song name"), keystroke(return)]
    - "Post a tweet saying X" → [open_app Google Chrome, wait 1.5s, chrome_navigate(url="https://twitter.com"), wait 2s, vision_click("What's happening? text box"), type_text("X"), vision_click("Post button")]
    - "In Excel, enter data in cell A1" → [open_app Microsoft Excel, wait 1.5s, keystroke(cmd+home), type_text("data"), keystroke(return)]
    - "Take a photo in Photo Booth" → [open_app Photo Booth, wait 2s, keystroke(cmd+t)]
    - "In FaceTime, call John" → [open_app FaceTime, wait 1.5s, vision_click("New FaceTime button"), type_text("John"), vision_click("first result"), vision_click("FaceTime button")]
    - "In iMessage, send 'hello' to mom" → [open_app Messages, wait 1.5s, keystroke(cmd+n), type_text("mom"), keystroke(return), type_text("hello"), keystroke(return)]
21. **Never give up** → If one approach might not work, add a fallback. If unsure which element to click, use screen_read first to understand context, then vision_click.

## Examples
"Turn volume up" → [{system_volume: direction="up"}]
"Turn WiFi off" → [{shell_command: command="networksetup -setapower en0 off"}]
"Turn WiFi on" → [{shell_command: command="networksetup -setapower en0 on"}]
"Open bluetooth settings" → [{shell_command: command="open \"x-apple.systempreferences:com.apple.BluetoothSettings\""}]
"Open wifi settings" → [{shell_command: command="open \"x-apple.systempreferences:com.apple.wifi-settings-extension\""}]
"Open display settings" → [{shell_command: command="open \"x-apple.systempreferences:com.apple.Displays-Settings-Extension\""}]
"Lock my Mac" → [{shell_command: command="osascript -e 'tell application \"System Events\" to keystroke \"q\" using {control down, command down}'"}]
"Open Chrome and draft an email about my internship result" → [
  {email_compose: email_to="", email_subject="Internship Result", email_body="Dear [Name],\n\nI am pleased to share that I have successfully completed my internship and received a positive result. The experience has been invaluable, and I look forward to discussing this further.\n\nBest regards,\n[Your Name]"}
]
"Open Mail and write an email to john@example.com about my internship result" → [
  {email_compose: email_to="john@example.com", email_subject="Internship Result Update", email_body="Dear John,\n\nI wanted to share that I have received a positive outcome from my recent internship. The experience was extremely valuable and I am grateful for the opportunity.\n\nBest regards"}
]
"Open Keynote" → [{open_app: app="Keynote"}]
"Open system settings" → [{open_app: app="System Settings"}]
"Open App Store" → [{open_app: app="App Store"}]
"Open calculator" → [{open_app: app="Calculator"}]
"Ask Copilot to write a function that reverses a string" → [{editor_ai_prompt: editor_prompt="write a function that reverses a string"}]
"Tell Cursor to refactor this code to use async await" → [{editor_ai_prompt: app="Cursor", editor_prompt="refactor this code to use async await"}]
"Write a React component for a login form" → [{editor_ai_prompt: editor_prompt="write a React component for a login form"}]
"Open WhatsApp and send hello to John" → [{send_whatsapp: contact_name="John", text="hello"}]
"WhatsApp Priya saying I'll be late" → [{send_whatsapp: contact_name="Priya", text="I'll be late, sorry!"}]
"Send a WhatsApp message to Rahul: can we talk?" → [{send_whatsapp: contact_name="Rahul", text="Hey Rahul, can we talk?"}]
"WhatsApp mom about my internship result" → [{send_whatsapp: contact_name="Mom", text="Hey Mom! I got my internship result and it went really well! I'm so excited to share the good news with you. Talk soon!"}]
"Send a WhatsApp to Aman telling him I'm on my way" → [{send_whatsapp: contact_name="Aman", text="Hey Aman! I'm on my way, see you soon!"}]
"Reply to that WhatsApp saying sure" → [{reply_whatsapp: text="Sure!"}]
"Reply saying I'll be there by 6" → [{reply_whatsapp: text="I'll be there by 6!"}]
"Reply to John on WhatsApp saying I'm busy" → [{reply_whatsapp: contact_name="John", text="Hey John, I'm a bit busy right now. I'll get back to you soon!"}]
"Tell him yes I'm coming" → [{reply_whatsapp: text="Yes, I'm coming!"}]
"Reply with sorry I missed your call" → [{reply_whatsapp: text="Sorry, I missed your call! I'll call you back soon."}]
"Show me the Eiffel Tower on maps" → [{maps_search: destination="Eiffel Tower"}]
"How far is Delhi from Mumbai" → [{maps_directions: origin="Delhi", destination="Mumbai"}]
"Distance from my location to JFK airport" → [{maps_directions: origin="my+location", destination="JFK airport"}]
"Directions from Bangalore to Mysore" → [{maps_directions: origin="Bangalore", destination="Mysore"}]
"Open maps and search for nearby coffee shops" → [{maps_search: destination="coffee shops near me"}]
"Turn WiFi off" → [{shell_command: command="networksetup -setapower en0 off"}]
"Turn WiFi on" → [{shell_command: command="networksetup -setapower en0 on"}]
"Open bluetooth settings" → [{shell_command: command="open \"x-apple.systempreferences:com.apple.BluetoothSettings\""}]
"Open wifi settings" → [{shell_command: command="open \"x-apple.systempreferences:com.apple.wifi-settings-extension\""}]
"Open display settings" → [{shell_command: command="open \"x-apple.systempreferences:com.apple.Displays-Settings-Extension\""}]
"Lock my Mac" → [{shell_command: command="osascript -e 'tell application \"System Events\" to keystroke \"q\" using {control down, command down}'"}]
"Activate work mode" → [{activate_mode: mode_name="work mode"}]
"Switch to study mode" → [{activate_mode: mode_name="study mode"}]
"Enable chill mode" → [{activate_mode: mode_name="chill mode"}]
"I need to focus and write code" → [{activate_mode: mode_name="work mode"}]
"Time to relax and listen to music" → [{activate_mode: mode_name="chill mode"}]
"Start listening to everything" → [{memory_start}]
"Remember everything from now" → [{memory_start}]
"Stop recording" → [{memory_stop}]
"What did he say about the deadline?" → [{memory_query: memory_question="What was said about the deadline?"}]
"Do you remember what Aman said about the project?" → [{memory_query: memory_question="What did Aman say about the project?"}]
"Summarize today's meetings" → [{memory_summary: hours=24}]
"What happened in the last hour?" → [{memory_summary: hours=1}]
"Give me a recap of today" → [{memory_summary: hours=24}]

## Context
Default browser: Google Chrome. OS: macOS.
For follow-up commands like "close that" or "the next one", use conversation history to resolve references.
{modes_context}
"""


# ─── Intent Parser ───────────────────────────────────────────────────────────────

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=config.OPENAI_API_KEY)
    return _client


def parse_intent(
    user_input: str,
    context: str = "",
    use_fast_model: bool = False,
) -> ActionPlan | None:
    """
    Parse a natural language command into a structured ActionPlan.

    Args:
        user_input: The transcribed user command.
        context: Previous conversation context for follow-up resolution.
        use_fast_model: If True, use gpt-4o-mini for faster/cheaper inference.

    Returns:
        ActionPlan with ordered actions, or None on failure.
    """
    start = time.time()
    model = config.LLM_MODEL_FAST if use_fast_model else config.LLM_MODEL
    log.info("🧠 Parsing intent with %s: \"%s\"", model, user_input)

    # Inject user-defined mode names into the system prompt
    try:
        from voxa.skills.modes import mode_manager
        modes_context = mode_manager.get_mode_names_for_prompt()
    except Exception:
        modes_context = ""
    system_prompt = SYSTEM_PROMPT.replace("{modes_context}", modes_context)

    messages = [
        {"role": "system", "content": system_prompt},
    ]

    # Inject conversation context if available
    if context:
        messages.append({
            "role": "system",
            "content": f"## Recent Conversation History\n{context}"
        })

    messages.append({"role": "user", "content": user_input})

    try:
        client = _get_client()

        response = client.beta.chat.completions.parse(
            model=model,
            messages=messages,
            response_format=ActionPlan,
            temperature=0.1,  # Low temp for deterministic action plans
        )

        plan = response.choices[0].message.parsed
        elapsed = time.time() - start

        if plan:
            log.info("✅ Intent parsed in %.2fs — %d action(s): %s",
                     elapsed, len(plan.actions), plan.confirmation)
            for i, action in enumerate(plan.actions):
                log.debug("  Step %d: %s — %s", i + 1, action.action.value, action.description)
        else:
            log.warning("LLM returned empty plan")

        return plan

    except Exception as e:
        elapsed = time.time() - start
        log.error("Intent parsing failed after %.2fs: %s", elapsed, e)
        return None


def parse_intent_with_retry(
    user_input: str,
    context: str = "",
    max_retries: int = 2,
) -> ActionPlan | None:
    """Parse intent with retry logic. Uses fast model for simple commands on first attempt."""
    # Use fast model immediately for simple, unambiguous commands
    _is_simple = is_simple_command(user_input)
    for attempt in range(max_retries + 1):
        # Simple commands: use fast model always. Complex: use fast on retries only.
        use_fast = _is_simple or (attempt > 0)
        plan = parse_intent(user_input, context=context, use_fast_model=use_fast)
        if plan is not None:
            return plan
        if attempt < max_retries:
            log.warning("Retrying intent parsing (attempt %d/%d)", attempt + 1, max_retries)

    # Final fallback: try local Ollama if enabled
    if config.OLLAMA_ENABLED:
        log.info("🦙 Trying Ollama local LLM fallback...")
        plan = _parse_with_ollama(user_input, context)
        if plan:
            return plan

    return None


def _parse_with_ollama(user_input: str, context: str = "") -> ActionPlan | None:
    """
    Fallback intent parser using a local Ollama instance.
    Requires Ollama running at localhost:11434 with a JSON-capable model.
    """
    try:
        import requests
        prompt = f"{SYSTEM_PROMPT}\n\nUser command: {user_input}"
        if context:
            prompt += f"\n\nContext:\n{context}"
        prompt += "\n\nRespond with ONLY valid JSON matching the ActionPlan schema."

        response = requests.post(
            f"{config.OLLAMA_BASE_URL}/api/generate",
            json={"model": config.OLLAMA_MODEL, "prompt": prompt, "stream": False, "format": "json"},
            timeout=30,
        )
        if response.status_code != 200:
            log.warning("Ollama returned status %d", response.status_code)
            return None

        raw = response.json().get("response", "")
        data = json.loads(raw)
        plan = ActionPlan(**data)
        log.info("✅ Ollama parsed intent: %s", plan.confirmation)
        return plan
    except Exception as e:
        log.warning("Ollama fallback failed: %s", e)
        return None


# ─── Quick classify (for hotkey vs wake word routing) ────────────────────────────

def is_simple_command(user_input: str) -> bool:
    """
    Heuristic check if a command is simple enough for the fast model.
    Simple = single action, no ambiguity.
    """
    simple_patterns = [
        "open ", "close ", "quit ", "launch ",
        "go to ", "navigate to ", "search for ",
        "play ", "pause", "stop",
        "show me ", "find ", "where is ",
        "how far ", "distance from ", "directions ", "directions from ",
        "maps ", "open maps",
        "activate ", "switch to ", "enable ", "enter mode", "mode ",
    ]
    lower = user_input.lower().strip()
    # If command matches a simple pattern and has no "and" / "then", it's simple
    if any(lower.startswith(p) for p in simple_patterns):
        if " and " not in lower and " then " not in lower:
            return True
    return False
