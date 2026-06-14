"""
Voice Capture Module for Voxa.
Captures microphone audio with Voice Activity Detection (VAD).
Bluetooth-aware: auto-detects device sample rate and resamples to 16kHz for Whisper.
"""
from __future__ import annotations

import io
import wave
import threading
import time
import numpy as np
import sounddevice as sd
import webrtcvad
from typing import Optional, Callable, List, Dict, Any
from voxa.config import config
from voxa.utils.logger import get_logger

log = get_logger("capture")

# VAD only supports these sample rates
VAD_SUPPORTED_RATES = (8000, 16000, 32000, 48000)
# Target rate for Whisper API (always 16kHz)
WHISPER_RATE = 16000


# ─── Device Utilities ────────────────────────────────────────────────────────────

def list_input_devices() -> List[Dict[str, Any]]:
    """
    Return a list of available audio input devices.
    Each dict has: index, name, channels, sample_rate, is_default.
    """
    devices = []
    try:
        default_idx = sd.default.device[0]  # default input device index
        for i, dev in enumerate(sd.query_devices()):
            if dev["max_input_channels"] > 0:
                devices.append({
                    "index": i,
                    "name": dev["name"],
                    "channels": dev["max_input_channels"],
                    "sample_rate": int(dev["default_samplerate"]),
                    "is_default": (i == default_idx),
                })
    except Exception as e:
        log.warning("Could not query audio devices: %s", e)
    return devices


def get_default_input_device() -> Optional[Dict[str, Any]]:
    """Get info about the current default input device."""
    devices = list_input_devices()
    for dev in devices:
        if dev["is_default"]:
            return dev
    return devices[0] if devices else None


def get_best_sample_rate(device_index: Optional[int] = None) -> int:
    """
    Determine the best sample rate to use for a device.
    Prefers 16kHz (ideal for VAD + Whisper).
    Falls back to the device's native rate if 16kHz is not supported.

    Bluetooth HFP mics typically report 8000 or 16000 Hz.
    Built-in mics typically report 44100 or 48000 Hz.
    """
    try:
        if device_index is None:
            device_info = sd.query_devices(kind="input")
        else:
            device_info = sd.query_devices(device_index)

        native_rate = int(device_info["default_samplerate"])
        log.debug("Device '%s' native rate: %dHz", device_info["name"], native_rate)

        # Try 16kHz first (ideal)
        for rate in (16000, 8000, 32000, 48000):
            try:
                sd.check_input_settings(
                    device=device_index,
                    channels=1,
                    dtype="int16",
                    samplerate=rate,
                )
                log.debug("Device supports %dHz", rate)
                return rate
            except Exception:
                pass

        # Fall back to native rate
        if native_rate in VAD_SUPPORTED_RATES:
            return native_rate

        # Last resort — use 16kHz and let sounddevice handle it
        return 16000

    except Exception as e:
        log.warning("Could not determine best sample rate: %s — using 16kHz", e)
        return 16000


def print_device_table():
    """Print a formatted table of available input devices."""
    devices = list_input_devices()
    if not devices:
        print("  No audio input devices found.")
        return

    print("\n  🎧 Available Microphone Devices:")
    print("  " + "─" * 60)
    print(f"  {'#':<4} {'Name':<38} {'Rate':<8} {'Default'}")
    print("  " + "─" * 60)
    for dev in devices:
        marker = "  ← active" if dev["is_default"] else ""
        print(f"  {dev['index']:<4} {dev['name'][:37]:<38} {dev['sample_rate']:<8}{marker}")
    print("  " + "─" * 60)
    print()


# ─── Resampling ──────────────────────────────────────────────────────────────────

def resample_audio(data: np.ndarray, from_rate: int, to_rate: int) -> np.ndarray:
    """
    Resample int16 audio from one sample rate to another using linear interpolation.
    Works for common ratios: 8k→16k (2x), 44.1k→16k, 48k→16k, etc.
    No external library needed — pure numpy.

    Args:
        data: int16 numpy array of audio samples.
        from_rate: Source sample rate in Hz.
        to_rate: Target sample rate in Hz.

    Returns:
        Resampled int16 numpy array.
    """
    if from_rate == to_rate:
        return data

    # Calculate target length
    target_len = int(len(data) * to_rate / from_rate)
    if target_len == 0:
        return data

    # Upsample or downsample using linear interpolation
    x_old = np.linspace(0, 1, len(data))
    x_new = np.linspace(0, 1, target_len)
    resampled = np.interp(x_new, x_old, data.astype(np.float64))

    return resampled.astype(np.int16)


# ─── Voice Capture ───────────────────────────────────────────────────────────────

class VoiceCapture:
    """
    Captures voice from the microphone using VAD to detect speech boundaries.
    Bluetooth-aware: uses the device's native sample rate and resamples to 16kHz.

    Usage:
        capture = VoiceCapture()
        audio_bytes = capture.record_until_silence()
        # audio_bytes is a 16kHz WAV file in memory, ready for Whisper API
    """

    def __init__(
        self,
        device_index: Optional[int] = None,
        vad_aggressiveness: int = config.VAD_AGGRESSIVENESS,
        silence_threshold_ms: int = config.SILENCE_THRESHOLD_MS,
        frame_duration_ms: int = config.VAD_FRAME_DURATION_MS,
        max_duration: float = config.MAX_RECORDING_DURATION,
        min_duration: float = config.MIN_RECORDING_DURATION,
    ):
        """
        Args:
            device_index: Specific device index to use, or None for system default.
        """
        self.device_index = device_index
        self.silence_threshold_ms = silence_threshold_ms
        self.frame_duration_ms = frame_duration_ms
        self.max_duration = max_duration
        self.min_duration = min_duration

        # Detect the best capture rate for this device
        self.capture_rate = get_best_sample_rate(device_index)

        # Frame size at the capture rate (e.g., 30ms at 16kHz = 480 samples)
        self.frame_size = int(self.capture_rate * frame_duration_ms / 1000)

        # VAD operates at the capture rate
        # webrtcvad requires the rate to be one of 8k/16k/32k/48k
        vad_rate = self.capture_rate if self.capture_rate in VAD_SUPPORTED_RATES else 16000
        self.vad_rate = vad_rate
        self.vad = webrtcvad.Vad(vad_aggressiveness)

        self._is_recording = False
        self._should_stop = False

        # Log device info
        dev = get_default_input_device() if device_index is None else None
        dev_name = dev["name"] if dev else f"Device #{device_index}"
        log.info(
            "🎧 Microphone: %s | Capture: %dHz | VAD: %dHz | Whisper: %dHz",
            dev_name, self.capture_rate, vad_rate, WHISPER_RATE,
        )
        if self.capture_rate != WHISPER_RATE:
            log.info("  (audio will be resampled %dHz → %dHz for Whisper)", self.capture_rate, WHISPER_RATE)

    def set_device(self, device_index: Optional[int]):
        """Switch to a different input device (takes effect on next recording)."""
        self.device_index = device_index
        self.capture_rate = get_best_sample_rate(device_index)
        self.frame_size = int(self.capture_rate * self.frame_duration_ms / 1000)
        self.vad_rate = self.capture_rate if self.capture_rate in VAD_SUPPORTED_RATES else 16000
        dev = get_default_input_device() if device_index is None else None
        dev_name = dev["name"] if dev else f"Device #{device_index}"
        log.info("🎧 Switched microphone to: %s (%dHz)", dev_name, self.capture_rate)

    def record_until_silence(self, on_speech_start: Optional[Callable] = None) -> Optional[bytes]:
        """
        Record audio from microphone, starting when speech is detected
        and stopping after silence exceeds the threshold.

        Handles Bluetooth devices by capturing at native rate and resampling.

        Args:
            on_speech_start: Optional callback fired when speech begins.

        Returns:
            WAV file bytes at 16kHz, ready for Whisper API. Returns None if no speech.
        """
        log.info("🎤 Listening for speech... (device rate: %dHz)", self.capture_rate)

        frames: List[np.ndarray] = []
        speech_detected = False
        silence_frames = 0
        total_frames = 0
        silence_frame_threshold = int(self.silence_threshold_ms / self.frame_duration_ms)
        max_frames = int(self.max_duration * 1000 / self.frame_duration_ms)

        self._is_recording = True
        self._should_stop = False

        try:
            with sd.RawInputStream(
                device=self.device_index,
                samplerate=self.capture_rate,
                channels=1,
                dtype="int16",
                blocksize=self.frame_size,
            ) as stream:
                while not self._should_stop and total_frames < max_frames:
                    data, overflowed = stream.read(self.frame_size)
                    if overflowed:
                        log.warning("Audio buffer overflow detected")

                    frame_bytes = bytes(data)
                    total_frames += 1

                    # VAD check — if capture rate != vad_rate, resample frame for VAD
                    vad_frame_bytes = frame_bytes
                    if self.capture_rate != self.vad_rate:
                        arr = np.frombuffer(frame_bytes, dtype=np.int16)
                        arr_resampled = resample_audio(arr, self.capture_rate, self.vad_rate)
                        # Ensure exact VAD frame size (webrtcvad requires exactly N samples)
                        vad_frame_samples = int(self.vad_rate * self.frame_duration_ms / 1000)
                        if len(arr_resampled) > vad_frame_samples:
                            arr_resampled = arr_resampled[:vad_frame_samples]
                        elif len(arr_resampled) < vad_frame_samples:
                            arr_resampled = np.pad(arr_resampled, (0, vad_frame_samples - len(arr_resampled)))
                        vad_frame_bytes = arr_resampled.tobytes()

                    try:
                        is_speech = self.vad.is_speech(vad_frame_bytes, self.vad_rate)
                    except Exception:
                        is_speech = False

                    if is_speech:
                        if not speech_detected:
                            speech_detected = True
                            log.info("🗣️  Speech detected — recording...")
                            if on_speech_start:
                                on_speech_start()
                        silence_frames = 0
                        frames.append(np.frombuffer(frame_bytes, dtype=np.int16).copy())
                    elif speech_detected:
                        silence_frames += 1
                        frames.append(np.frombuffer(frame_bytes, dtype=np.int16).copy())
                        if silence_frames >= silence_frame_threshold:
                            log.info("🔇 Silence detected — stopping recording")
                            break

        except sd.PortAudioError as e:
            err_str = str(e)
            log.error("Microphone error: %s", err_str)
            if "Invalid sample rate" in err_str or "Invalid number of channels" in err_str:
                log.error(
                    "Device does not support %dHz. "
                    "Try switching your Bluetooth device to HFP mode in macOS Sound settings, "
                    "or use 'devices' command to select a different input.", self.capture_rate
                )
            else:
                log.error("Make sure microphone permission is granted in System Settings")
            return None
        except Exception as e:
            log.error("Unexpected capture error: %s", e)
            return None
        finally:
            self._is_recording = False

        if not speech_detected or not frames:
            log.debug("No speech detected in this recording window")
            return None

        # Combine all frames
        audio_data = np.concatenate(frames)
        duration = len(audio_data) / self.capture_rate

        if duration < self.min_duration:
            log.debug("Recording too short (%.2fs), discarding", duration)
            return None

        log.info("📝 Recorded %.2fs of audio at %dHz", duration, self.capture_rate)

        # Resample to 16kHz for Whisper if needed
        if self.capture_rate != WHISPER_RATE:
            audio_data = resample_audio(audio_data, self.capture_rate, WHISPER_RATE)
            log.debug("Resampled %dHz → %dHz (%d samples)", self.capture_rate, WHISPER_RATE, len(audio_data))

        return self._array_to_wav(audio_data, WHISPER_RATE)

    def stop(self):
        """Signal the recording to stop."""
        self._should_stop = True

    @property
    def is_recording(self) -> bool:
        return self._is_recording

    def _array_to_wav(self, audio: np.ndarray, sample_rate: int) -> bytes:
        """Convert a numpy int16 array to WAV file bytes."""
        wav_buffer = io.BytesIO()
        with wave.open(wav_buffer, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # 16-bit = 2 bytes
            wf.setframerate(sample_rate)
            wf.writeframes(audio.tobytes())
        return wav_buffer.getvalue()


# ─── Continuous Listener ─────────────────────────────────────────────────────────

class ContinuousListener:
    """
    Continuously listens for speech and fires a callback with each utterance.
    Runs in a background thread.
    """

    def __init__(self, on_utterance: Callable[[bytes], None]):
        self.on_utterance = on_utterance
        self.capture = VoiceCapture()
        self._thread: Optional[threading.Thread] = None
        self._running = False

    def start(self):
        """Start continuous listening in background thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()
        log.info("Continuous listener started")

    def stop(self):
        """Stop continuous listening."""
        self._running = False
        self.capture.stop()
        if self._thread:
            self._thread.join(timeout=3)
        log.info("Continuous listener stopped")

    def _listen_loop(self):
        """Main listening loop."""
        while self._running:
            try:
                audio = self.capture.record_until_silence()
                if audio and self._running:
                    self.on_utterance(audio)
            except Exception as e:
                log.error("Error in listen loop: %s", e)
                time.sleep(1)
