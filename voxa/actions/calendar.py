"""
Calendar & Reminders Module for Voxa.
Read-only queries for macOS Calendar and Reminders via AppleScript.
"""
from __future__ import annotations

from voxa.utils.applescript import run_applescript, AppleScriptError
from voxa.utils.logger import get_logger

log = get_logger("calendar")


def get_today_events() -> dict:
    """Get all calendar events for today."""
    log.info("📅 Getting today's calendar events")
    try:
        # Launch Calendar in background if not running (fixes error -600)
        script = '''
            tell application "Calendar"
                launch
                set todayStart to current date
                set hours of todayStart to 0
                set minutes of todayStart to 0
                set seconds of todayStart to 0
                set todayEnd to todayStart + 86399
                set resultText to ""
                repeat with c in calendars
                    repeat with e in (every event of c whose start date >= todayStart and start date <= todayEnd)
                        if resultText is not "" then
                            set resultText to resultText & "; "
                        end if
                        set resultText to resultText & (summary of e) & " at " & (time string of (start date of e))
                    end repeat
                end repeat
                if resultText is "" then return "none"
                return resultText
            end tell
        '''
        result = run_applescript(script, timeout=25)

        if not result or result.strip() == "none":
            return {"success": True, "action": "calendar_today", "events": [], "message": "You have no events today"}

        events = [e.strip() for e in result.split(";") if e.strip()]
        if len(events) == 1:
            msg = f"You have 1 event today: {events[0]}"
        else:
            msg = f"You have {len(events)} events today. First: {events[0]}"

        return {"success": True, "action": "calendar_today", "events": events, "message": msg}

    except AppleScriptError as e:
        log.error("Calendar query failed: %s", e)
        return {"success": False, "action": "calendar_today", "error": str(e), "message": "Could not access Calendar. Try opening the Calendar app first."}


def get_upcoming_events(days: int = 7) -> dict:
    """Get calendar events for the next N days."""
    log.info("📅 Getting upcoming events for next %d days", days)
    try:
        script = f'''
            tell application "Calendar"
                launch
                set startDate to current date
                set endDate to startDate + ({days} * 86400)
                set resultText to ""
                repeat with c in calendars
                    repeat with e in (every event of c whose start date >= startDate and start date <= endDate)
                        set dayPart to short date string of (start date of e)
                        set timePart to time string of (start date of e)
                        if resultText is not "" then
                            set resultText to resultText & "|"
                        end if
                        set resultText to resultText & (summary of e) & " on " & dayPart & " at " & timePart
                    end repeat
                end repeat
                if resultText is "" then return "none"
                return resultText
            end tell
        '''
        result = run_applescript(script, timeout=25)

        if not result or result.strip() == "none":
            return {"success": True, "action": "calendar_upcoming", "events": [], "message": f"No events in the next {days} days"}

        events = [e.strip() for e in result.split("|") if e.strip()]
        msg = f"Upcoming events: {'; '.join(events[:3])}"
        return {"success": True, "action": "calendar_upcoming", "events": events, "message": msg}

    except AppleScriptError as e:
        log.error("Calendar upcoming query failed: %s", e)
        return {"success": False, "action": "calendar_upcoming", "error": str(e), "message": "Could not access Calendar. Try opening the Calendar app first."}


def get_reminders() -> dict:
    """Get incomplete reminders from the Reminders app."""
    log.info("🔔 Getting reminders")
    try:
        # Use launch to auto-start Reminders if not running
        script = '''
            tell application "Reminders"
                launch
                set resultText to ""
                repeat with aList in lists
                    set incompleteReminders to (reminders of aList whose completed is false)
                    repeat with r in incompleteReminders
                        if resultText is not "" then
                            set resultText to resultText & "|"
                        end if
                        set resultText to resultText & (name of r)
                    end repeat
                end repeat
                if resultText is "" then return "none"
                return resultText
            end tell
        '''
        result = run_applescript(script, timeout=20)

        if not result or result.strip() == "none":
            return {"success": True, "action": "reminders_list", "reminders": [], "message": "You have no pending reminders"}

        reminders = [r.strip() for r in result.split("|") if r.strip()]
        if len(reminders) == 1:
            msg = f"You have 1 reminder: {reminders[0]}"
        else:
            msg = f"You have {len(reminders)} reminders: {', '.join(reminders[:5])}"

        return {"success": True, "action": "reminders_list", "reminders": reminders, "message": msg}

    except AppleScriptError as e:
        log.error("Reminders query failed: %s", e)
        return {"success": False, "action": "reminders_list", "error": str(e), "message": "Could not access Reminders. Try opening the Reminders app first."}
