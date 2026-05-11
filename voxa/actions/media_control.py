"""
Media Control Module for Voxa.
Controls Spotify and Apple Music via AppleScript.
Commands: play, pause, next, previous, get now playing, set volume.
"""
from __future__ import annotations

from voxa.utils.applescript import run_applescript, AppleScriptError
from voxa.utils.logger import get_logger

log = get_logger("media_control")

# Supported apps in priority order
MEDIA_APPS = ["Spotify", "Music"]


def _get_active_media_app() -> str | None:
    """Return the name of the first running media app."""
    for app in MEDIA_APPS:
        try:
            result = run_applescript(f'''
                tell application "System Events"
                    return (name of every process) contains "{app}"
                end tell
            ''')
            if result and result.strip().lower() == "true":
                return app
        except AppleScriptError:
            continue
    return None


def play_pause(app: str | None = None) -> dict:
    """Toggle play/pause for Spotify or Apple Music."""
    target = app or _get_active_media_app() or "Spotify"
    log.info("⏯️  Play/pause — %s", target)
    try:
        run_applescript(f'tell application "{target}" to playpause')
        return {"success": True, "action": "media_play_pause", "app": target, "message": f"Toggled play/pause on {target}"}
    except AppleScriptError as e:
        return {"success": False, "action": "media_play_pause", "error": str(e), "message": f"Could not control {target}. Is it open?"}


def next_track(app: str | None = None) -> dict:
    """Skip to the next track."""
    target = app or _get_active_media_app() or "Spotify"
    log.info("⏭️  Next track — %s", target)
    try:
        run_applescript(f'tell application "{target}" to next track')
        return {"success": True, "action": "media_next", "app": target, "message": f"Skipped to next track on {target}"}
    except AppleScriptError as e:
        return {"success": False, "action": "media_next", "error": str(e), "message": f"Could not skip track on {target}"}


def prev_track(app: str | None = None) -> dict:
    """Go back to the previous track."""
    target = app or _get_active_media_app() or "Spotify"
    log.info("⏮️  Previous track — %s", target)
    try:
        run_applescript(f'tell application "{target}" to previous track')
        return {"success": True, "action": "media_prev", "app": target, "message": f"Playing previous track on {target}"}
    except AppleScriptError as e:
        return {"success": False, "action": "media_prev", "error": str(e), "message": f"Could not go back on {target}"}


def get_now_playing(app: str | None = None) -> dict:
    """Get the currently playing track name and artist."""
    target = app or _get_active_media_app()
    if not target:
        return {"success": False, "action": "media_now_playing", "message": "No media app is running"}

    log.info("🎵 Getting now playing — %s", target)
    try:
        if target == "Spotify":
            track = run_applescript('tell application "Spotify" to name of current track')
            artist = run_applescript('tell application "Spotify" to artist of current track')
        else:
            track = run_applescript('tell application "Music" to name of current track')
            artist = run_applescript('tell application "Music" to artist of current track')

        track = (track or "Unknown").strip()
        artist = (artist or "Unknown").strip()
        msg = f"Currently playing: {track} by {artist}"
        return {"success": True, "action": "media_now_playing", "track": track, "artist": artist, "message": msg}
    except AppleScriptError as e:
        return {"success": False, "action": "media_now_playing", "error": str(e), "message": "Nothing is playing right now"}


def set_media_volume(level: int, app: str | None = None) -> dict:
    """Set Spotify/Music volume (0–100)."""
    target = app or _get_active_media_app() or "Spotify"
    clamped = max(0, min(100, int(level)))
    log.info("🔊 Media volume → %d — %s", clamped, target)
    try:
        run_applescript(f'tell application "{target}" to set sound volume to {clamped}')
        return {"success": True, "action": "media_volume", "app": target, "message": f"{target} volume set to {clamped}%"}
    except AppleScriptError as e:
        return {"success": False, "action": "media_volume", "error": str(e), "message": f"Could not set {target} volume"}
