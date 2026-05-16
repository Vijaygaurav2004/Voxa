"""
Intent Parser for Voxa.
Converts natural language commands into structured action plans using OpenAI GPT-4o.
Uses strict structured outputs for reliable JSON action schemas.
"""
from __future__ import annotations

import json
import time
from openai import OpenAI
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
    # ── Messaging ──────────────────────────────────────────────────────────
    SEND_WHATSAPP = "send_whatsapp"        # Send WhatsApp message to a contact


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


class ActionPlan(BaseModel):
    """A complete plan generated by the LLM."""
    thought: str
    actions: list[Action]
    confirmation: str


# ─── System Prompt ───────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are Voxa, an intelligent macOS voice assistant that converts natural language commands into executable action plans.

You control the user's Mac computer completely — mouse, keyboard, UI, apps, system settings. The user should NEVER need to touch the keyboard or mouse.

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
| open_url | url | Open a URL in Chrome |
| browser_search | query | Search Google in Chrome |
| browser_navigate | url | Navigate current tab to URL |
| play_youtube | query | Search YouTube and play first result |
| search_netflix | query | Search Netflix and open first result |

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

### Coding Editor AI
| Action | Required Fields | Description |
|--------|----------------|-------------|
| editor_ai_prompt | editor_prompt | Send a prompt to the AI in the active editor (VS Code Copilot / Cursor / Windsurf). Auto-detects which editor is open. Use app field to force a specific editor. |

### Messaging
| Action | Required Fields | Description |
|--------|----------------|-------------|
| send_whatsapp | contact_name, text | Send a WhatsApp message to a contact by name. Tries WhatsApp Desktop first, then WhatsApp Web. |

## Critical Rules
1. **Mouse clicks by description** → use `vision_click` with element=natural language description like "the blue Send button" or "the search bar".
2. **Any app** → use `open_app` with the app name as the user said it. Do NOT assume VS Code is installed; use the actual app name.
3. **Typing in a specific field** → first `vision_click` the field, then `type_text` the content.
4. **Keyboard shortcuts** → use `keystroke` e.g. `keys="cmd+s"` to save, `keys="cmd+c"` to copy.
5. **Open app then do something** → always add `wait` (1.5-2s) after `open_app` before interacting.
6. **Menu bar items** → use `ax_menu` with `menu_path=["File", "Open"]`.
7. **YouTube** → `play_youtube`. **Netflix** → `search_netflix`.
8. **Volume up/down** → `system_volume` with direction="up" or "down".
9. **What's on screen** → `screen_read`. **Take screenshot** → `screenshot`.
10. `confirmation` must be a friendly 1-sentence summary of what you're about to do.
11. For complex tasks like "open Cursor and open a folder", break into: open_app → wait → ax_menu(File→Open) → type_text(path) → keystroke(return).
12. **Coding AI prompts** → `editor_ai_prompt` with editor_prompt=the exact prompt text.
13. **WhatsApp messages** → `send_whatsapp` with contact_name=the person's name and text=the message. Extract both from the command. e.g. "send hi to John on WhatsApp" → contact_name="John", text="hi".

## Examples
"Turn volume up" → [{system_volume: direction="up"}]
"Set a 5 minute timer" → [{set_timer: duration_seconds=300, reminder_text="5 minute timer is done!"}]
"What's on my screen?" → [{screen_read: screen_question="What is on the screen?"}]
"Pause Spotify" → [{media_play_pause: media_app="Spotify"}]
"What's on my calendar today?" → [{calendar_today}]
"Send email to john@example.com about the meeting" → [{email_compose: email_to="john@example.com", email_subject="Meeting", email_body="Hi John"}]
"Take a screenshot" → [{screenshot}]
"Ask Copilot to write a function that reverses a string" → [{editor_ai_prompt: editor_prompt="write a function that reverses a string"}]
"Tell Cursor to refactor this code to use async await" → [{editor_ai_prompt: app="Cursor", editor_prompt="refactor this code to use async await", editor_mode="chat"}]
"Write a React component for a login form" → [{editor_ai_prompt: editor_prompt="write a React component for a login form"}]
"Open WhatsApp and send hello to John" → [{send_whatsapp: contact_name="John", text="hello"}]
"WhatsApp Priya saying I'll be late" → [{send_whatsapp: contact_name="Priya", text="I'll be late"}]
"Send a WhatsApp message to Rahul: can we talk?" → [{send_whatsapp: contact_name="Rahul", text="can we talk?"}]

## Context
Default browser: Google Chrome. OS: macOS.
For follow-up commands like "close that" or "the next one", use conversation history to resolve references.
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

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
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
    """Parse intent with retry logic. Falls back to fast model, then Ollama if enabled."""
    for attempt in range(max_retries + 1):
        use_fast = attempt > 0  # Use fast model on retries
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
    ]
    lower = user_input.lower().strip()
    # If command matches a simple pattern and has no "and" / "then", it's simple
    if any(lower.startswith(p) for p in simple_patterns):
        if " and " not in lower and " then " not in lower:
            return True
    return False
