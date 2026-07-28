"""
Text-to-Speech Module for Voxa.

Priority chain (auto-detected):
  1. ElevenLabs  — if ELEVENLABS_API_KEY set AND paid plan (most realistic)
  2. OpenAI TTS  — uses your existing OPENAI_API_KEY, nova voice (very natural, human-like)
  3. macOS `say` — last resort fallback (robotic, offline)

Auto-pauses the wake word listener during playback to prevent Voxa
from hearing its own voice.
"""
from __future__ import annotations

import os
import queue as _queue
import subprocess
import tempfile
import threading
import time
from typing import Optional, Callable

from voxa.utils.logger import get_logger

log = get_logger("tts")

# ── macOS fallback settings ───────────────────────────────────────────────────
MACOS_VOICE = "Samantha"
MACOS_RATE  = 170

# ── OpenAI TTS settings ───────────────────────────────────────────────────────
# nova  = warm, natural, energetic — best for assistants
# Other options: alloy, echo, fable, onyx, shimmer
OPENAI_TTS_VOICE = os.environ.get("OPENAI_TTS_VOICE", "nova")
OPENAI_TTS_MODEL = os.environ.get("OPENAI_TTS_MODEL", "tts-1")  # tts-1-hd = higher quality

# ── ElevenLabs settings ───────────────────────────────────────────────────────
EL_VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")
EL_MODEL    = os.environ.get("ELEVENLABS_MODEL",    "eleven_turbo_v2_5")

# ── State ─────────────────────────────────────────────────────────────────────
_current_proc: Optional[subprocess.Popen] = None
_proc_lock = threading.Lock()

_active_count = 0
_count_lock = threading.Lock()

def _increment_active():
    global _active_count
    with _count_lock:
        _active_count += 1

def _decrement_active():
    global _active_count
    with _count_lock:
        _active_count = max(0, _active_count - 1)

def is_speaking() -> bool:
    """Return True if TTS is currently generating or speaking audio."""
    global _active_count, _current_proc
    with _count_lock:
        if _active_count > 0:
            return True
    with _proc_lock:
        if _current_proc and _current_proc.poll() is None:
            return True
    return False

_on_speaking_start: Optional[Callable] = None
_on_speaking_end:   Optional[Callable] = None

# ── Serial TTS queue ──────────────────────────────────────────────────────────
# ALL speech goes through one worker thread so utterances never overlap, no
# matter how many speak() calls arrive concurrently (e.g. a plan with multiple
# speak actions, or a confirmation plus an auto-spoken result).
_tts_queue: "_queue.Queue" = _queue.Queue()
_worker_started = False
_worker_lock = threading.Lock()


def _ensure_tts_worker():
    global _worker_started
    with _worker_lock:
        if _worker_started:
            return
        _worker_started = True
        threading.Thread(target=_tts_worker_loop, daemon=True, name="tts-worker").start()


def _enqueue_tts(text: str, done: Optional[threading.Event] = None):
    """Queue an utterance. Pauses the wake listener when going idle→busy."""
    if not text:
        if done:
            done.set()
        return
    _ensure_tts_worker()
    global _active_count
    with _count_lock:
        was_idle = _active_count == 0
        _active_count += 1
    if was_idle and _on_speaking_start:
        _on_speaking_start()
    _tts_queue.put((text, done))


def _tts_worker_loop():
    """Play queued utterances strictly one at a time."""
    global _active_count
    while True:
        text, done = _tts_queue.get()
        try:
            if text:
                _speak_best(text)
        except Exception as e:
            log.warning("TTS playback error: %s", e)
        finally:
            with _count_lock:
                _active_count = max(0, _active_count - 1)
                idle = _active_count == 0
            if idle:
                # Let the audio tail finish before re-enabling the mic, and
                # re-check in case another utterance was queued meanwhile.
                time.sleep(0.5)
                with _count_lock:
                    still_idle = _active_count == 0
                if still_idle and _on_speaking_end:
                    _on_speaking_end()
            if done:
                done.set()
            _tts_queue.task_done()

_el_client    = None
_el_checked   = False
_openai_client = None
_openai_checked = False


# ── Client init ───────────────────────────────────────────────────────────────

def _get_el_client():
    """Return ElevenLabs client if API key set and plan is paid."""
    global _el_client, _el_checked
    if _el_checked:
        return _el_client
    _el_checked = True
    api_key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        from elevenlabs.client import ElevenLabs
        _el_client = ElevenLabs(api_key=api_key)
        return _el_client
    except Exception:
        return None


def _get_openai_client():
    """Return OpenAI client (uses existing OPENAI_API_KEY)."""
    global _openai_client, _openai_checked
    if _openai_checked:
        return _openai_client
    _openai_checked = True
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        from openai import OpenAI
        _openai_client = OpenAI(api_key=api_key)
        log.info("✅ OpenAI TTS ready — voice: %s (%s)", OPENAI_TTS_VOICE, OPENAI_TTS_MODEL)
        return _openai_client
    except Exception as e:
        log.warning("OpenAI TTS init failed: %s", e)
        return None


# ── Public API ────────────────────────────────────────────────────────────────

def set_speaking_hooks(on_start: Callable, on_end: Callable):
    """Register callbacks to pause/resume wake word listener during speech."""
    global _on_speaking_start, _on_speaking_end
    _on_speaking_start = on_start
    _on_speaking_end   = on_end


def speak(text: str, blocking: bool = True):
    """
    Speak text aloud using the best available TTS engine, serialized through the
    TTS queue so it never overlaps other speech. Mutes the wake listener while
    speaking. If blocking, waits until this utterance has finished playing.
    """
    if not text:
        return

    log.info("🔊 Speaking: \"%s\"", text[:100])

    if blocking:
        done = threading.Event()
        _enqueue_tts(text, done)
        done.wait(timeout=30)
    else:
        _enqueue_tts(text)


def speak_confirmation(text: str):
    """Non-blocking speak — queued so it plays after any in-flight speech."""
    if not text:
        return
    log.info("🔊 Speaking: \"%s\"", text[:100])
    _enqueue_tts(text)


def speak_error(text: str):
    """Speak error — blocking."""
    speak(text, blocking=True)


def stop_speaking():
    """Kill any active TTS playback immediately and clear the queue."""
    global _current_proc, _active_count
    # Drain any pending utterances (release blocked callers waiting on them).
    try:
        while True:
            _, done = _tts_queue.get_nowait()
            if done:
                done.set()
            _tts_queue.task_done()
    except _queue.Empty:
        pass
    with _count_lock:
        _active_count = 0
    try:
        subprocess.run(["killall", "say"],    capture_output=True)
        subprocess.run(["killall", "afplay"], capture_output=True)
        with _proc_lock:
            if _current_proc:
                _current_proc.terminate()
                _current_proc = None
    except Exception:
        pass
    if _on_speaking_end:
        _on_speaking_end()


def speak_and_listen(text: str, on_done: callable):
    """Speak then call on_done() — used by conversation mode."""
    def _run():
        speak(text, blocking=True)
        if on_done:
            on_done()
    threading.Thread(target=_run, daemon=True, name="tts-and-listen").start()


# ── Engine selector ───────────────────────────────────────────────────────────

def _speak_best(text: str):
    """Try TTS engines in priority order."""
    # 1. ElevenLabs (if paid plan available)
    el = _get_el_client()
    if el:
        try:
            _speak_elevenlabs(el, text)
            return
        except Exception:
            pass  # fall through

    # 2. OpenAI TTS (uses existing API key — natural human voice)
    oai = _get_openai_client()
    if oai:
        try:
            _speak_openai(oai, text)
            return
        except Exception as e:
            log.warning("OpenAI TTS failed (%s) — falling back to macOS say", e)

    # 3. macOS say (last resort)
    _speak_macos(text)


# ── TTS backends ──────────────────────────────────────────────────────────────

def _speak_openai(client, text: str):
    """Speak using OpenAI TTS API — nova voice sounds very natural."""
    global _current_proc
    fd, tmp_path = tempfile.mkstemp(suffix=".mp3", prefix="voxa_tts_")
    try:
        os.close(fd)
        response = client.audio.speech.create(
            model=OPENAI_TTS_MODEL,
            voice=OPENAI_TTS_VOICE,
            input=text,
            response_format="mp3",
        )
        response.stream_to_file(tmp_path)

        proc = subprocess.Popen(
            ["afplay", tmp_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        with _proc_lock:
            _current_proc = proc
        proc.wait()  # Use local ref to avoid NoneType if stop_speaking() clears _current_proc
    finally:
        with _proc_lock:
            if _current_proc is not None and _current_proc.poll() is not None:
                _current_proc = None
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


def _speak_elevenlabs(client, text: str):
    """Speak using ElevenLabs API (requires paid plan)."""
    global _current_proc
    audio_bytes = client.text_to_speech.convert(
        voice_id=EL_VOICE_ID,
        text=text,
        model_id=EL_MODEL,
        output_format="mp3_44100_128",
    )
    if hasattr(audio_bytes, '__iter__') and not isinstance(audio_bytes, (bytes, bytearray)):
        audio_data = b"".join(audio_bytes)
    else:
        audio_data = bytes(audio_bytes)

    if not audio_data:
        raise RuntimeError("ElevenLabs returned empty audio")

    fd, tmp_path = tempfile.mkstemp(suffix=".mp3", prefix="voxa_tts_")
    try:
        os.write(fd, audio_data)
        os.close(fd)
        proc = subprocess.Popen(
            ["afplay", tmp_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        with _proc_lock:
            _current_proc = proc
        proc.wait()  # Use local ref to avoid NoneType crash
    finally:
        with _proc_lock:
            if _current_proc is not None and _current_proc.poll() is not None:
                _current_proc = None
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


def _speak_macos(text: str):
    """Speak using macOS `say` — fallback only."""
    global _current_proc
    proc = subprocess.Popen(
        ["/usr/bin/say", "-v", MACOS_VOICE, "-r", str(MACOS_RATE), text],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    with _proc_lock:
        _current_proc = proc
    proc.wait()  # Use local ref to avoid NoneType crash
