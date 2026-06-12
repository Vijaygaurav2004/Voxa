"""
Timer & Reminder Module for Voxa.
Background threading timers that fire TTS alerts when they complete.
Timers survive TTS muting — they use a direct speak call with no hooks.
"""
from __future__ import annotations

import threading
import time
from typing import Optional
from voxa.utils.logger import get_logger

log = get_logger("timers")

# Active timers registry: name → (timer_thread, fire_time, label)
_timers: dict[str, dict] = {}
_timers_lock = threading.Lock()

# Injected TTS function to avoid circular imports
_speak_fn = None


def set_speak_fn(fn):
    """Register the TTS speak function. Called from main.py at startup."""
    global _speak_fn
    _speak_fn = fn


def _fire_timer(name: str, message: str):
    """Internal: fires when a timer completes."""
    with _timers_lock:
        _timers.pop(name, None)

    log.info("⏰ Timer fired: '%s' — %s", name, message)
    print(f"\n⏰  \033[1mTimer done: {message}\033[0m\n")

    if _speak_fn:
        _speak_fn(message)


def set_timer(
    duration_seconds: float,
    label: str = "Timer",
    name: Optional[str] = None,
) -> dict:
    """
    Set a countdown timer that speaks an alert when it fires.

    Args:
        duration_seconds: How long to wait before firing.
        label: What to say when the timer fires (e.g., "Time to drink water!").
        name: Unique name for this timer (auto-generated if not provided).
    """
    if duration_seconds <= 0:
        return {
            "success": False,
            "action": "set_timer",
            "message": "Timer duration must be greater than 0",
        }

    timer_name = name or f"timer_{int(time.time())}"
    fire_time = time.time() + duration_seconds

    # Friendly duration string
    if duration_seconds >= 3600:
        duration_str = f"{int(duration_seconds // 3600)}h {int((duration_seconds % 3600) // 60)}m"
    elif duration_seconds >= 60:
        duration_str = f"{int(duration_seconds // 60)} minute{'s' if duration_seconds >= 120 else ''}"
    else:
        duration_str = f"{int(duration_seconds)} second{'s' if duration_seconds != 1 else ''}"

    message = label if label != "Timer" else f"Your {duration_str} timer is done!"

    # Cancel existing timer with same name
    with _timers_lock:
        existing = _timers.get(timer_name)
        if existing and existing.get("thread"):
            existing["cancelled"] = True

    cancel_flag = {"cancelled": False}

    def _run():
        start = time.time()
        while time.time() - start < duration_seconds:
            if cancel_flag["cancelled"]:
                log.info("Timer '%s' cancelled", timer_name)
                return
            time.sleep(0.5)
        if not cancel_flag["cancelled"]:
            _fire_timer(timer_name, message)

    t = threading.Thread(target=_run, daemon=True, name=f"voxa-timer-{timer_name}")
    t.start()

    with _timers_lock:
        _timers[timer_name] = {
            "thread": t,
            "fire_time": fire_time,
            "label": message,
            "duration_seconds": duration_seconds,
            "cancel_flag": cancel_flag,
            "created_at": time.time(),
        }

    log.info("⏱️  Timer set: '%s' for %s", timer_name, duration_str)
    return {
        "success": True,
        "action": "set_timer",
        "timer_name": timer_name,
        "duration_seconds": duration_seconds,
        "message": f"Timer set for {duration_str}. I'll remind you when it's done.",
    }


def cancel_timer(name: Optional[str] = None) -> dict:
    """
    Cancel an active timer.

    Args:
        name: Specific timer name to cancel. If None, cancels the most recent timer.
    """
    with _timers_lock:
        if not _timers:
            return {
                "success": False,
                "action": "cancel_timer",
                "message": "No active timers to cancel",
            }

        if name and name in _timers:
            timer = _timers.pop(name)
            timer["cancel_flag"]["cancelled"] = True
            return {"success": True, "action": "cancel_timer", "message": f"Timer '{name}' cancelled"}

        # Cancel most recently set timer
        last_name = max(_timers.keys(), key=lambda k: _timers[k].get("created_at", 0))
        timer = _timers.pop(last_name)
        timer["cancel_flag"]["cancelled"] = True
        return {"success": True, "action": "cancel_timer", "message": f"Timer cancelled"}


def list_timers() -> dict:
    """List all active timers and their remaining time."""
    with _timers_lock:
        if not _timers:
            return {
                "success": True,
                "action": "list_timers",
                "timers": [],
                "message": "No active timers",
            }

        now = time.time()
        timer_list = []
        for name, info in _timers.items():
            remaining = max(0, info["fire_time"] - now)
            if remaining >= 60:
                rem_str = f"{int(remaining // 60)}m {int(remaining % 60)}s"
            else:
                rem_str = f"{int(remaining)}s"
            timer_list.append({
                "name": name,
                "label": info["label"],
                "remaining_seconds": int(remaining),
                "remaining_str": rem_str,
            })

        if len(timer_list) == 1:
            t = timer_list[0]
            msg = f"1 active timer: {t['label']}, {t['remaining_str']} remaining"
        else:
            msg = f"{len(timer_list)} active timers"

        return {
            "success": True,
            "action": "list_timers",
            "timers": timer_list,
            "message": msg,
        }


def get_active_timer_count() -> int:
    """Return the number of currently active timers."""
    with _timers_lock:
        return len(_timers)
