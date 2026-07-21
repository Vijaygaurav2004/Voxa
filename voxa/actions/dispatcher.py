"""
Action Dispatcher for Voxa.
Routes Action objects to the correct executor module.
Handles sequencing, error recovery, and retry logic.
"""
from __future__ import annotations

import time
from typing import Optional, Callable, List, Dict
from voxa.intelligence.intent_parser import Action, ActionType, ActionPlan, classify_action, SWIFT_ACTIONS
from voxa.actions import app_control, browser, typing, filesystem, shell
from voxa.actions import system_control, clipboard, timers, screen_reader, media_control, calendar, email as email_action
from voxa.actions import computer_control, editor, whatsapp, chrome as chrome_mod
from voxa.voice.tts import speak_confirmation
from voxa.utils.logger import get_logger

log = get_logger("dispatcher")

# Max retries for transient failures
MAX_RETRIES = 2
RELAY_DELAY = 1.0
RETRY_DELAY = 1.0

# These action types return information that should be spoken aloud.
# After a successful execution, the dispatcher will automatically
# call speak_confirmation(result["message"]) so the user hears the answer.
SPEAK_RESULT_ACTIONS = {
    ActionType.SCREEN_READ,
    ActionType.SCREENSHOT,
    ActionType.CLIPBOARD_GET,
    ActionType.SYSTEM_BATTERY,
    ActionType.LIST_TIMERS,
    ActionType.CALENDAR_TODAY,
    ActionType.CALENDAR_UPCOMING,
    ActionType.REMINDERS_LIST,
    ActionType.MEDIA_NOW_PLAYING,
    ActionType.CHROME_LIST_TABS,
    ActionType.CHROME_PAGE_INFO,
    ActionType.SEND_WHATSAPP,
    ActionType.REPLY_WHATSAPP,
    ActionType.EMAIL_COMPOSE,
    ActionType.MEMORY_QUERY,
    ActionType.MEMORY_SUMMARY,
}


def execute_plan(plan: ActionPlan, on_step: Optional[Callable] = None) -> List[Dict]:
    """
    Execute a complete ActionPlan — runs each action in sequence.

    Args:
        plan: The ActionPlan from the intent parser.
        on_step: Optional callback(step_index, action, result) for UI updates.

    Returns:
        List of result dicts from each action.
    """
    log.info("▶️  Executing plan: %s (%d steps)", plan.confirmation, len(plan.actions))
    results = []

    for i, action in enumerate(plan.actions):
        step_num = i + 1
        log.info("━━ Step %d/%d: %s — %s",
                 step_num, len(plan.actions), action.action.value, action.description)

        result = execute_action_with_retry(action)
        results.append(result)

        # ── Auto-speak results for query actions ───────────────────────────────────────────
        # Query actions return information but don't speak it themselves.
        # We speak the result message here so the user always hears the answer.
        if action.action in SPEAK_RESULT_ACTIONS and result.get("success") and result.get("message"):
            log.info("🗣️  Speaking result for %s", action.action.value)
            speak_confirmation(result["message"])

        # Notify UI callback
        if on_step:
            try:
                on_step(i, action, result)
            except Exception as e:
                log.warning("Step callback error: %s", e)

        # Check if we should abort the sequence
        if not result.get("success", False):
            # Some failures are fatal (app not found), others are soft (button not found)
            if result.get("fatal", False):
                log.error("⛔ Fatal error at step %d — aborting plan", step_num)
                break
            else:
                log.warning("⚠️  Step %d failed but continuing: %s",
                           step_num, result.get("message", "Unknown error"))

    # Summary
    success_count = sum(1 for r in results if r.get("success", False))
    log.info("✅ Plan complete: %d/%d steps succeeded", success_count, len(results))

    return results


def execute_python_only(plan: ActionPlan, on_step: Optional[Callable] = None) -> List[Dict]:
    """
    Execute only Python-classified actions in a plan.
    Swift-classified actions are returned as {"routed": "swift", "skipped": True}.
    Used by the API server when the Swift app handles native actions itself.

    Args:
        plan: The ActionPlan from the intent parser.
        on_step: Optional callback(step_index, action, result) for status updates.

    Returns:
        List of result dicts — one per action, in order.
    """
    log.info("▶️  Executing Python-only plan: %s (%d steps)", plan.confirmation, len(plan.actions))
    results = []

    for i, action in enumerate(plan.actions):
        target = classify_action(action.action)

        if target == "swift":
            result = {
                "success": True,
                "routed": "swift",
                "skipped": True,
                "action": action.action.value,
                "message": f"Routed to Swift: {action.description}",
            }
            results.append(result)
            log.info("⏭️  Step %d/%d: %s → Swift (skipped)", i + 1, len(plan.actions), action.action.value)
        else:
            log.info("━━ Step %d/%d: %s — %s",
                     i + 1, len(plan.actions), action.action.value, action.description)
            result = execute_action_with_retry(action)
            results.append(result)

            # Auto-speak results for query actions
            if action.action in SPEAK_RESULT_ACTIONS and result.get("success") and result.get("message"):
                log.info("🗣️  Speaking result for %s", action.action.value)
                speak_confirmation(result["message"])

        if on_step:
            try:
                on_step(i, action, result)
            except Exception as e:
                log.warning("Step callback error: %s", e)

        if not result.get("success", False) and result.get("fatal", False):
            log.error("⛔ Fatal error at step %d — aborting plan", i + 1)
            break

    success_count = sum(1 for r in results if r.get("success", False))
    log.info("✅ Python-only plan complete: %d/%d steps succeeded", success_count, len(results))
    return results


def execute_action_with_retry(action: Action, max_retries: int = MAX_RETRIES) -> dict:
    """Execute a single action with retry logic for transient failures."""
    result = {}
    for attempt in range(max_retries + 1):
        result = execute_action(action)

        if result.get("success", False):
            return result

        # Don't retry certain failures
        if result.get("dangerous", False):  # Safety block — don't retry
            return result
        if "not found" in result.get("message", "").lower():  # Resource missing
            return result

        # Retry transient failures
        if attempt < max_retries:
            delay = RETRY_DELAY * (attempt + 1)
            log.warning("Retrying action %s in %.1fs (attempt %d/%d)",
                       action.action.value, delay, attempt + 1, max_retries)
            time.sleep(delay)

    return result


def execute_action(action: Action) -> dict:
    """
    Execute a single Action by routing to the correct handler.

    Args:
        action: The Action object to execute.

    Returns:
        Result dict with at least 'success' and 'message' keys.
    """
    try:
        action_type = action.action

        # ── App Control ──────────────────────────────────────────────
        if action_type == ActionType.OPEN_APP:
            # Use universal opener: AppleScript → open -a → Spotlight
            return computer_control.open_any_app(action.app)
        elif action_type == ActionType.FOCUS_APP:
            return computer_control.focus_app(action.app)
        elif action_type == ActionType.CLOSE_APP:
            return app_control.close_app(action.app)
        elif action_type == ActionType.OPEN_URL:
            return browser.open_url(action.url)
        elif action_type == ActionType.BROWSER_SEARCH:
            query = action.query or ""
            if "youtube" in query.lower() or "youtube" in (action.url or "").lower():
                return browser.search_youtube(query)
            return browser.search_google(query)
        elif action_type == ActionType.BROWSER_NAVIGATE:
            return browser.navigate_to(action.url)
        elif action_type == ActionType.BROWSER_CLICK_FIRST_RESULT:
            return browser.click_first_youtube_result()
        elif action_type == ActionType.PLAY_YOUTUBE:
            return browser.play_youtube(action.query or "")
        elif action_type == ActionType.SEARCH_NETFLIX:
            return browser.search_netflix(action.query or "")
        elif action_type == ActionType.MAPS_SEARCH:
            return browser.maps_search(action.destination or action.query or "")
        elif action_type == ActionType.MAPS_DIRECTIONS:
            return browser.maps_directions(
                origin=action.origin or "My Location",
                destination=action.destination or action.query or "",
            )

        # ── Input ──────────────────────────────────────────────────────────────
        elif action_type == ActionType.TYPE_TEXT:
            return typing.type_text(action.text)
        elif action_type == ActionType.KEYSTROKE:
            return typing.send_keystroke(action.keys)

        # ── Shell & Files ──────────────────────────────────────────────────────
        elif action_type == ActionType.SHELL_COMMAND:
            return shell.execute_command(action.command)
        elif action_type == ActionType.FILE_OPEN:
            return filesystem.open_file(action.path)
        elif action_type == ActionType.FILE_OPEN_FOLDER:
            return filesystem.open_folder(action.path)

        # ── Utility ────────────────────────────────────────────────────────────
        elif action_type == ActionType.WAIT:
            delay = action.delay_seconds or 1.0
            log.info("⏳ Waiting %.1fs...", delay)
            time.sleep(delay)
            return {"success": True, "action": "wait", "message": "Waited {}s".format(delay)}
        elif action_type == ActionType.SPEAK:
            speak_confirmation(action.text or action.description)
            return {"success": True, "action": "speak", "message": "Spoke: {}".format(action.text or action.description)}

        # ── System Control ─────────────────────────────────────────────────────
        elif action_type == ActionType.SYSTEM_VOLUME:
            return system_control.set_volume(level=action.level, direction=action.direction, mute=action.mute or False)
        elif action_type == ActionType.SYSTEM_BRIGHTNESS:
            return system_control.set_brightness(level=action.level, direction=action.direction)
        elif action_type == ActionType.SYSTEM_DARK_MODE:
            return system_control.toggle_dark_mode(enable=action.enable)
        elif action_type == ActionType.SYSTEM_DND:
            return system_control.toggle_dnd(enable=action.enable)
        elif action_type == ActionType.SYSTEM_BATTERY:
            return system_control.get_battery_status()

        # ── Clipboard ──────────────────────────────────────────────────────────
        elif action_type == ActionType.CLIPBOARD_GET:
            return clipboard.get_clipboard()
        elif action_type == ActionType.CLIPBOARD_SET:
            return clipboard.set_clipboard(action.text or "")
        elif action_type == ActionType.CLIPBOARD_PASTE:
            return clipboard.paste_clipboard()

        # ── Timers ─────────────────────────────────────────────────────────────
        elif action_type == ActionType.SET_TIMER:
            return timers.set_timer(
                duration_seconds=action.duration_seconds or 60,
                label=action.reminder_text or "Timer",
                name=action.timer_name,
            )
        elif action_type == ActionType.CANCEL_TIMER:
            return timers.cancel_timer(name=action.timer_name)
        elif action_type == ActionType.LIST_TIMERS:
            return timers.list_timers()

        # ── Screen ─────────────────────────────────────────────────────────────
        elif action_type == ActionType.SCREEN_READ:
            return screen_reader.describe_screen(question=action.screen_question or "What is on the screen?")
        elif action_type == ActionType.SCREENSHOT:
            return screen_reader.take_screenshot(destination=action.path, window_only=action.window_only or False)

        # ── Media Control ──────────────────────────────────────────────────────
        elif action_type == ActionType.MEDIA_PLAY_PAUSE:
            return media_control.play_pause(app=action.media_app)
        elif action_type == ActionType.MEDIA_NEXT:
            return media_control.next_track(app=action.media_app)
        elif action_type == ActionType.MEDIA_PREV:
            return media_control.prev_track(app=action.media_app)
        elif action_type == ActionType.MEDIA_NOW_PLAYING:
            return media_control.get_now_playing(app=action.media_app)
        elif action_type == ActionType.MEDIA_VOLUME:
            return media_control.set_media_volume(level=action.level or 50, app=action.media_app)

        # ── Calendar & Reminders ───────────────────────────────────────────────
        elif action_type == ActionType.CALENDAR_TODAY:
            return calendar.get_today_events()
        elif action_type == ActionType.CALENDAR_UPCOMING:
            return calendar.get_upcoming_events()
        elif action_type == ActionType.REMINDERS_LIST:
            return calendar.get_reminders()

        # ── Email ────────────────────────────────────────────────────────
        elif action_type == ActionType.EMAIL_COMPOSE:
            return email_action.compose_email(
                to=action.email_to,
                subject=action.email_subject,
                body=action.email_body,
            )

        # ── Computer / Mouse / UI Control ────────────────────────────────────
        elif action_type == ActionType.VISION_CLICK:
            return computer_control.vision_click(
                description=action.element or action.description,
                double=action.double_click or False,
                right=action.right_click or False,
            )
        elif action_type == ActionType.CLICK_AT:
            return computer_control.click_at(
                x=action.x or 0, y=action.y or 0,
                double=action.double_click or False,
                right=action.right_click or False,
            )
        elif action_type == ActionType.SCROLL:
            return computer_control.scroll(
                direction=action.direction or "down",
                amount=action.amount or 3,
            )
        elif action_type == ActionType.DRAG:
            return computer_control.drag(
                from_x=action.x or 0, from_y=action.y or 0,
                to_x=action.to_x or 0, to_y=action.to_y or 0,
            )
        elif action_type == ActionType.AX_BUTTON:
            return computer_control.ax_click_button(
                app=action.app or computer_control.get_frontmost_app(),
                button_name=action.element or "",
            )
        elif action_type == ActionType.AX_MENU:
            return computer_control.ax_click_menu(
                app=action.app or computer_control.get_frontmost_app(),
                menu_path=action.menu_path or [],
            )
        elif action_type == ActionType.AX_TYPE:
            return computer_control.ax_type_in_field(
                app=action.app or computer_control.get_frontmost_app(),
                field_hint=action.field_hint or "",
                text=action.text or "",
            )

        # ── Coding Editor AI ───────────────────────────────────────────────
        elif action_type == ActionType.EDITOR_AI_PROMPT:
            return editor.send_to_editor_ai(
                prompt=action.editor_prompt or action.text or action.description,
                app=action.app,
                mode=action.editor_mode or "chat",
            )

        # ── Messaging ───────────────────────────────────────────────────
        elif action_type == ActionType.SEND_WHATSAPP:
            contact = action.contact_name or action.query or ""
            msg     = action.text or ""
            return whatsapp.send_whatsapp_message(contact, msg)
        elif action_type == ActionType.REPLY_WHATSAPP:
            msg     = action.text or ""
            contact = action.contact_name or None   # optional — switch chat first if given
            return whatsapp.reply_whatsapp_message(msg, contact=contact)

        # ── Chrome Tab & Window Control ──────────────────────────────────
        elif action_type == ActionType.CHROME_NEW_TAB:
            return chrome_mod.open_new_tab(action.url or "chrome://newtab")
        elif action_type == ActionType.CHROME_NEW_TABS:
            count = action.tab_count or 1
            url   = action.url or "chrome://newtab"
            return chrome_mod.open_n_tabs(count, url)
        elif action_type == ActionType.CHROME_CLOSE_TAB:
            return chrome_mod.close_current_tab()
        elif action_type == ActionType.CHROME_CLOSE_ALL_TABS:
            return chrome_mod.close_all_tabs()
        elif action_type == ActionType.CHROME_CLOSE_TABS_RIGHT:
            return chrome_mod.close_tabs_to_right()
        elif action_type == ActionType.CHROME_NEXT_TAB:
            return chrome_mod.switch_to_next_tab()
        elif action_type == ActionType.CHROME_PREV_TAB:
            return chrome_mod.switch_to_prev_tab()
        elif action_type == ActionType.CHROME_SWITCH_TAB:
            return chrome_mod.switch_to_tab(action.tab_index or 1)
        elif action_type == ActionType.CHROME_FIND_TAB:
            return chrome_mod.find_and_switch_tab(action.tab_keyword or action.query or "")
        elif action_type == ActionType.CHROME_DUPLICATE_TAB:
            return chrome_mod.duplicate_current_tab()
        elif action_type == ActionType.CHROME_LIST_TABS:
            return chrome_mod.list_open_tabs()
        elif action_type == ActionType.CHROME_NEW_WINDOW:
            return chrome_mod.open_new_window(action.url or "chrome://newtab")
        elif action_type == ActionType.CHROME_INCOGNITO:
            return chrome_mod.open_incognito_window(action.url or "")
        elif action_type == ActionType.CHROME_CLOSE_WINDOW:
            return chrome_mod.close_current_window()
        elif action_type == ActionType.CHROME_BACK:
            return chrome_mod.navigate_back()
        elif action_type == ActionType.CHROME_FORWARD:
            return chrome_mod.navigate_forward()
        elif action_type == ActionType.CHROME_RELOAD:
            return chrome_mod.reload_page(hard=False)
        elif action_type == ActionType.CHROME_HARD_RELOAD:
            return chrome_mod.reload_page(hard=True)
        elif action_type == ActionType.CHROME_NAVIGATE:
            return chrome_mod.navigate_to_url(action.url or "")
        elif action_type == ActionType.CHROME_ZOOM_IN:
            return chrome_mod.zoom_in()
        elif action_type == ActionType.CHROME_ZOOM_OUT:
            return chrome_mod.zoom_out()
        elif action_type == ActionType.CHROME_ZOOM_RESET:
            return chrome_mod.zoom_reset()
        elif action_type == ActionType.CHROME_FIND_IN_PAGE:
            return chrome_mod.find_in_page(action.query or "")
        elif action_type == ActionType.CHROME_BOOKMARK:
            return chrome_mod.bookmark_current_page()
        elif action_type == ActionType.CHROME_HISTORY:
            return chrome_mod.open_history()
        elif action_type == ActionType.CHROME_DOWNLOADS:
            return chrome_mod.open_downloads()
        elif action_type == ActionType.CHROME_BOOKMARKS_MGR:
            return chrome_mod.open_bookmarks()
        elif action_type == ActionType.CHROME_SETTINGS:
            return chrome_mod.open_settings()
        elif action_type == ActionType.CHROME_EXTENSIONS:
            return chrome_mod.open_extensions()
        elif action_type == ActionType.CHROME_DEVTOOLS:
            return chrome_mod.open_devtools()
        elif action_type == ActionType.CHROME_PAGE_INFO:
            return chrome_mod.get_page_info()
        elif action_type == ActionType.CHROME_SCROLL:
            direction = action.scroll_direction or action.direction or "down"
            amount    = action.amount or 3
            return chrome_mod.scroll_page(direction, amount)
        elif action_type == ActionType.CHROME_REOPEN_TAB:
            return chrome_mod.reopen_closed_tab()
        elif action_type == ActionType.CHROME_CLOSE_TAB_BY_KEYWORD:
            return chrome_mod.close_tab_by_keyword(action.tab_keyword or action.query or "")
        elif action_type == ActionType.CHROME_CLOSE_OTHER_TABS:
            return chrome_mod.close_other_tabs()
        elif action_type == ActionType.CHROME_FULL_SCREEN:
            return chrome_mod.toggle_full_screen()
        elif action_type == ActionType.CHROME_BOOKMARK_BAR:
            return chrome_mod.toggle_bookmark_bar()
        elif action_type == ActionType.CHROME_BOOKMARK_ALL_TABS:
            return chrome_mod.bookmark_all_tabs()
        elif action_type == ActionType.CHROME_CLEAR_DATA:
            return chrome_mod.clear_browsing_data()
        elif action_type == ActionType.CHROME_PRINT:
            return chrome_mod.print_page()

        # ── Custom Modes ─────────────────────────────────────────────────────
        elif action_type == ActionType.ACTIVATE_MODE:
            from voxa.skills.modes import mode_manager
            return mode_manager.activate_mode(action.mode_name or action.description)

        # ── Memory (Always-On Listening) ─────────────────────────────────────
        elif action_type == ActionType.MEMORY_START:
            from voxa.memory.engine import memory_engine
            memory_engine.start()
            return {"success": True, "action": "memory_start", "message": "Memory engine started. I'm now listening to everything."}

        elif action_type == ActionType.MEMORY_STOP:
            from voxa.memory.engine import memory_engine
            memory_engine.stop()
            return {"success": True, "action": "memory_stop", "message": "Memory engine stopped."}

        elif action_type == ActionType.MEMORY_QUERY:
            from voxa.memory.recall import memory_recall
            question = action.memory_question or action.query or action.description
            result = memory_recall.answer_question(question)
            return {
                "success": True,
                "action": "memory_query",
                "message": result.get("answer", "No answer found."),
                "sources": result.get("source_count", 0),
            }

        elif action_type == ActionType.MEMORY_SUMMARY:
            from voxa.memory.recall import memory_recall
            hours = action.hours or 24.0
            result = memory_recall.summarize_recent(hours)
            return {
                "success": True,
                "action": "memory_summary",
                "message": result.get("summary", "No conversations found."),
                "segment_count": result.get("segment_count", 0),
            }

        else:
            log.error("Unknown action type: %s", action.action)
            return {
                "success": False,
                "action": action.action.value,
                "message": "Unknown action type: {}".format(action.action),
            }

    except Exception as e:
        log.error("Action execution error (%s): %s", action.action.value, e)
        return {
            "success": False,
            "action": action.action.value,
            "error": str(e),
            "message": "Error executing {}: {}".format(action.action.value, str(e)),
        }

