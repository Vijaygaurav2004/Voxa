"""Lightweight RMS energy / silence check on 16-bit PCM WAV bytes.

`audioop` was removed from the Python standard library in 3.13+, so this uses a
small numpy-based RMS (numpy is already a Voxa dependency) instead of
`audioop.rms`. The public surface — ``rms_energy()`` / ``is_silent()`` — is the
same either way.
"""
from __future__ import annotations

import io
import wave

import numpy as np

# Little-endian integer dtype per PCM sample width (bytes).
_DTYPE_BY_WIDTH = {1: np.int8, 2: np.int16, 4: np.int32}


def _decode_pcm(wav_bytes: bytes) -> tuple[bytes | None, int]:
    """Return (frame_bytes, sample_width) for a PCM WAV.

    Returns (None, 0) if the bytes can't be parsed as a WAV at all — the caller
    uses that to distinguish "unmeasurable" from "measured and silent".
    """
    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as w:
            frames = w.readframes(w.getnframes())
            width = w.getsampwidth()
        return frames, width
    except Exception:
        return None, 0


def _rms(frames: bytes, width: int) -> float:
    """RMS amplitude of raw little-endian PCM frames."""
    try:
        dtype = _DTYPE_BY_WIDTH.get(width, np.int16)
        itemsize = np.dtype(dtype).itemsize
        # np.frombuffer needs a whole number of samples.
        usable = len(frames) - (len(frames) % itemsize)
        if usable <= 0:
            return 0.0
        samples = np.frombuffer(frames[:usable], dtype=dtype).astype(np.float64)
        if width == 1:  # 8-bit PCM is unsigned, centered at 128
            samples -= 128.0
        if samples.size == 0:
            return 0.0
        return float(np.sqrt(np.mean(np.square(samples))))
    except Exception:
        return 0.0


def rms_energy(wav_bytes: bytes) -> float:
    """Return RMS amplitude (0..32767) of a 16-bit PCM WAV, or 0.0 on any error."""
    frames, width = _decode_pcm(wav_bytes)
    if not frames:
        return 0.0
    return _rms(frames, width)


def is_silent(wav_bytes: bytes, threshold: float = 180.0) -> bool:
    """True if the clip's RMS is below ``threshold`` (near-silence).

    Unparseable audio returns False on purpose: we never drop bytes we can't
    actually measure (a corrupt/placeholder chunk still reaches the pipeline),
    while a valid but empty/all-zero clip is correctly reported as silent.
    """
    frames, width = _decode_pcm(wav_bytes)
    if frames is None:      # couldn't parse a WAV at all
        return False
    if not frames:          # valid WAV, no audio frames → silent
        return True
    return _rms(frames, width) < threshold
