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

_on_speaking_start: Optional[Callable] = None
_on_speaking_end:   Optional[Callable] = None

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
    Speak text aloud using the best available TTS engine.
    Mutes the wake listener before speaking and resumes after.
    """
    if not text:
        return

    log.info("🔊 Speaking: \"%s\"", text[:100])

    def _run():
        if _on_speaking_start:
            _on_speaking_start()
        try:
            _speak_best(text)
        finally:
            time.sleep(0.6)
            if _on_speaking_end:
                _on_speaking_end()

    if blocking:
        _run()
    else:
        threading.Thread(target=_run, daemon=True, name="tts").start()


def speak_confirmation(text: str):
    """Non-blocking speak — mutes wake listener before spawning thread."""
    if not text:
        return
    if _on_speaking_start:
        _on_speaking_start()

    def _run():
        try:
            _speak_best(text)
        finally:
            time.sleep(0.6)
            if _on_speaking_end:
                _on_speaking_end()

    threading.Thread(target=_run, daemon=True, name="tts-confirm").start()


def speak_error(text: str):
    """Speak error — blocking."""
    speak(text, blocking=True)


def stop_speaking():
    """Kill any active TTS playback immediately."""
    global _current_proc
    try:
        subprocess.run(["killall", "say"],    capture_output=True)
        subprocess.run(["killall", "afplay"], capture_output=True)
        with _proc_lock:
            if _current_proc:
                _current_proc.terminate()
                _current_proc = None
    except Exception:
        pass


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

        with _proc_lock:
            _current_proc = subprocess.Popen(
                ["afplay", tmp_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        _current_proc.wait()
    finally:
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
        with _proc_lock:
            _current_proc = subprocess.Popen(
                ["afplay", tmp_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        _current_proc.wait()
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


def _speak_macos(text: str):
    """Speak using macOS `say` — fallback only."""
    global _current_proc
    with _proc_lock:
        _current_proc = subprocess.Popen(
            ["/usr/bin/say", "-v", MACOS_VOICE, "-r", str(MACOS_RATE), text],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    _current_proc.wait()
