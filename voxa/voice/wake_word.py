"""
Wake Word Listener for Voxa.
Runs a continuous background listener that detects "Hey Voxa" in real-time.
Uses RMS energy filtering + strict VAD + punctuation-normalized matching
to avoid false triggers from background noise (like Siri does).
"""
from __future__ import annotations

import re
import time
import threading
from typing import Callable, Optional
from voxa.config import config
from voxa.voice.capture import VoiceCapture
from voxa.voice.transcribe import transcribe
from voxa.utils.logger import get_logger

log = get_logger("wakeword")

# Whisper prompt hint — guides the model to expect this phrase, reducing hallucinations
WHISPER_WAKE_PROMPT = "Hey Voxa"

# Fuzzy variants Whisper might produce for "Hey Voxa" (normalized, no punctuation)
WAKE_WORD_VARIANTS = [
    "hey voxa",
    "hey vox",
    "hey voxa",
    "a voxa",
    "hey boxer",
    "hey boca",
    "hey voca",
    "hey volga",
    "hey moxa",
    "voxa",
]

# Minimum RMS energy (0–32767 scale) to bother sending audio to Whisper.
# Filters out near-silent ambient noise that VAD sometimes passes through.
# Raised to 400 to avoid picking up TTS echo/reverb from speakers.
MIN_RMS_ENERGY = 400

# How long to wait after TTS finishes before listening again (seconds).
# Prevents wake listener from hearing Voxa's own voice echo.
POST_TTS_SETTLE_SECS = 1.2


def _normalize(text: str) -> str:
    """
    Strip all punctuation and lowercase so fuzzy matching works
    even when Whisper adds commas: "Hey, Vox," → "hey vox"
    """
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)   # replace punctuation with space
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _matches_wake_word(text: str, wake_word: str) -> bool:
    """
    Fuzzy wake word detection after punctuation normalization.
    Handles Whisper comma/period artifacts and common misrecognitions.
    """
    norm = _normalize(text)
    wake_norm = _normalize(wake_word)

    # Direct match
    if wake_norm in norm:
        return True

    # All known variants
    for variant in WAKE_WORD_VARIANTS:
        if _normalize(variant) in norm:
            return True

    return False


def _rms_energy(audio_bytes: bytes) -> float:
    """
    Calculate Root Mean Square energy of raw PCM int16 audio bytes.
    Returns a value 0–32767. Values below ~200 are near silence/noise.
    """
    import struct
    import math
    n = len(audio_bytes) // 2
    if n == 0:
        return 0.0
    samples = struct.unpack(f"{n}h", audio_bytes[:n * 2])
    rms = math.sqrt(sum(s * s for s in samples) / n)
    return rms


def _extract_command_after_wake(text: str, wake_word: str) -> Optional[str]:
    """
    Extract what the user said AFTER the wake word.
    "Hey Voxa open Chrome" → "open Chrome"
    Returns None if only the wake word was said.
    """
    norm_text = _normalize(text)

    # Try each variant to find where it ends in the normalized text
    for variant in [_normalize(wake_word)] + [_normalize(v) for v in WAKE_WORD_VARIANTS]:
        idx = norm_text.find(variant)
        if idx != -1:
            # Get the position in the original text (approx)
            after_norm = norm_text[idx + len(variant):].strip()
            if len(after_norm) > 3:
                # Reconstruct from original text after the wake word position
                # Use the normalized remainder as the command
                return after_norm
            return None

    return None


class WakeWordListener:
    """
    Always-on background listener that detects "Hey Voxa" using:
    - Strict VAD (aggressiveness=3) to ignore ambient noise
    - RMS energy threshold to skip truly silent frames
    - Whisper transcription with wake word prompt hint
    - Punctuation-normalized fuzzy matching

    When detected, fires on_wake(inline_command) and pauses until resume() is called.
    """

    def __init__(
        self,
        on_wake: Callable,
        wake_word: str = config.WAKE_WORD,
    ):
        self.on_wake = on_wake
        self.wake_word = wake_word.lower().strip()

        # Dedicated capture: strict VAD (3), short segments for fast response
        self.capture = VoiceCapture(
            vad_aggressiveness=3,      # Most strict — ignores background noise
            silence_threshold_ms=600,  # 600ms silence ends segment
            frame_duration_ms=30,
            max_duration=5.0,
            min_duration=0.4,          # Ignore clips shorter than 0.4s (noise)
        )

        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._paused = threading.Event()
        self._paused.set()   # Start as active (not paused)
        self._paused_at: Optional[float] = None   # timestamp of last pause()
        self._command_lock = threading.Lock()

    def start(self):
        """Start background wake word detection."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._listen_loop, daemon=True, name="wake-word"
        )
        self._thread.start()
        log.info("🎙️  Wake word listener active — say \"%s\" to activate", self.wake_word)

    def stop(self):
        """Stop the listener."""
        self._running = False
        self.capture.stop()
        if self._thread:
            self._thread.join(timeout=3)
        log.info("Wake word listener stopped")

    def pause(self):
        """Pause detection while a command is being processed."""
        self._paused.clear()
        self._paused_at = time.time()   # track when we paused
        self.capture.stop()

    def resume(self):
        """Resume detection after a command finishes. Includes a settle delay."""
        # Short delay so mic doesn't pick up TTS room reverb or echo
        time.sleep(POST_TTS_SETTLE_SECS)
        self._paused_at = None
        self._paused.set()

    # Maximum seconds the listener can stay paused before auto-resuming.
    # Prevents permanent freeze if command handler throws an exception.
    _MAX_PAUSE_SECS = 30.0

    def _listen_loop(self):
        while self._running:
            # Block while paused — wait with timeout so we can check _running
            if not self._paused.wait(timeout=0.5):
                # Check watchdog: if paused too long, force resume
                if self._paused_at and (time.time() - self._paused_at) > self._MAX_PAUSE_SECS:
                    log.warning("⚠️  Wake listener paused >%.0fs — force-resuming", self._MAX_PAUSE_SECS)
                    self._paused_at = None
                    self._paused.set()
                continue

            # Extra settle after resume: let microphone clear speaker echo
            if not self._paused.is_set():
                continue

            try:
                audio_bytes = self.capture.record_until_silence()

                # Double-check we weren't paused during the recording
                if not audio_bytes or not self._paused.is_set():
                    continue

                # ── Energy gate: skip near-silent clips (noise, AC hum, TTS echo) ──
                # audio_bytes is a WAV file; PCM data starts at byte 44
                pcm_data = audio_bytes[44:]
                energy = _rms_energy(pcm_data)
                if energy < MIN_RMS_ENERGY:
                    log.debug("Skipping low-energy audio (RMS=%.0f)", energy)
                    continue

                log.debug("Sending to Whisper for wake check (RMS=%.0f)", energy)

                # ── Transcribe with prompt to bias Whisper toward wake word ──
                text = transcribe(audio_bytes, prompt=WHISPER_WAKE_PROMPT)

                if not text:
                    continue

                log.debug("Wake check: \"%s\"", text)

                # ── Fuzzy punctuation-normalized match ──
                if _matches_wake_word(text, self.wake_word):
                    inline_cmd = _extract_command_after_wake(text, self.wake_word)
                    log.info("🎯 Wake word detected! transcript=\"%s\" inline=%s",
                             text, repr(inline_cmd))
                    self.pause()
                    threading.Thread(
                        target=self.on_wake,
                        args=(inline_cmd,),
                        daemon=True,
                        name="wake-handler",
                    ).start()

            except Exception as e:
                if self._running:
                    log.error("Wake word loop error: %s", e)
                    time.sleep(1)
