"""
Speech-to-Text Transcription Module for Voxa.
Uses OpenAI Whisper API for high-accuracy transcription.
"""
from __future__ import annotations

import io
import time
from typing import Optional
from openai import OpenAI
from voxa.config import config
from voxa.utils.logger import get_logger

log = get_logger("transcribe")

# Initialize OpenAI client
_client: OpenAI | None = None


def _get_client() -> OpenAI:
    """Lazy-initialize the OpenAI client."""
    global _client
    if _client is None:
        _client = OpenAI(api_key=config.OPENAI_API_KEY)
    return _client


def transcribe(audio_bytes: bytes, language: str = "en", prompt: Optional[str] = None) -> Optional[str]:
    """
    Transcribe audio bytes (WAV format) to text using OpenAI Whisper API.

    Args:
        audio_bytes: WAV file content as bytes.
        language: Language code (default: "en").
        prompt: Optional hint to Whisper (e.g. "Hey Voxa") to reduce hallucinations
                and bias transcription toward expected words.

    Returns:
        Transcribed text string, or None on failure.
    """
    start = time.time()
    log.info("🎙️  Sending audio to Whisper API (%d bytes)...", len(audio_bytes))

    try:
        client = _get_client()

        audio_file = io.BytesIO(audio_bytes)
        audio_file.name = "recording.wav"

        kwargs = {
            "model": config.WHISPER_MODEL,
            "file": audio_file,
            "language": language,
            "response_format": "text",
        }
        if prompt:
            kwargs["prompt"] = prompt

        response = client.audio.transcriptions.create(**kwargs)

        elapsed = time.time() - start
        text = response.strip() if isinstance(response, str) else response.text.strip()

        if not text:
            log.warning("Whisper returned empty transcription")
            return None

        log.info("📝 Transcribed in %.2fs: \"%s\"", elapsed, text)
        return text

    except Exception as e:
        elapsed = time.time() - start
        log.error("Whisper API error after %.2fs: %s", elapsed, e)
        return None



def transcribe_with_retry(audio_bytes: bytes, max_retries: int = 2) -> str | None:
    """Transcribe with retry logic for transient API failures."""
    for attempt in range(max_retries + 1):
        result = transcribe(audio_bytes)
        if result is not None:
            return result
        if attempt < max_retries:
            wait = 1.0 * (attempt + 1)
            log.warning("Retrying transcription in %.1fs (attempt %d/%d)",
                       wait, attempt + 1, max_retries)
            import time as t
            t.sleep(wait)
    return None
