"""
Voxa Memory Engine — Central Orchestrator for Ambient Listening.

Runs as a background daemon that:
1. Captures ambient audio via AmbientCapture (30s chunks with VAD pre-filtering)
2. Transcribes speech chunks using Whisper API
3. Filters out filler/noise using gpt-4o-mini (keeps only substance)
4. Generates embeddings for semantic search
5. Stores everything permanently in the MemoryStore

Design priorities:
  - LOW CPU: VAD runs locally, everything else is API-based
  - LOW LATENCY: Processing is async, never blocks the main Voxa pipeline
  - HIGH ACCURACY: Whisper for transcription, gpt-4o-mini for filtering
  - PERSISTENT: Everything saved to disk, survives restarts
"""
from __future__ import annotations

import time
import uuid
import threading
import queue
from typing import Optional
from openai import OpenAI

from voxa.config import config
from voxa.utils.logger import get_logger
from voxa.memory.store import MemoryStore
from voxa.voice.capture import AmbientCapture

log = get_logger("memory.engine")

# How many seconds of silence between speech = new conversation session
SESSION_GAP_SECONDS = 300  # 5 minutes


class MemoryEngine:
    """
    Always-on ambient listener that captures, transcribes, filters, and stores
    conversations for later recall.

    Usage:
        engine = MemoryEngine()
        engine.start()    # Begin ambient listening
        engine.stop()     # Stop listening
        engine.pause()    # Temporarily pause (during Voxa commands)
        engine.resume()   # Resume after pause
    """

    def __init__(self):
        self.store = MemoryStore()
        self._capture: Optional[AmbientCapture] = None
        self._process_queue: queue.Queue = queue.Queue(maxsize=100)
        self._process_thread: Optional[threading.Thread] = None
        self._running = False
        self._paused = False
        # When True, audio is streamed in from the host app (Swift) via
        # ingest_chunk() instead of captured by the local Python mic. This is how
        # the bundled app records meetings — the app holds mic permission reliably.
        self._external_audio = False

        # Session tracking
        self._current_session_id: str = ""
        self._last_speech_time: float = 0.0

        # OpenAI client (lazy init)
        self._client: Optional[OpenAI] = None

    def _get_client(self) -> OpenAI:
        """Lazy-initialize OpenAI client."""
        if self._client is None:
            self._client = OpenAI(api_key=config.OPENAI_API_KEY)
        return self._client

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self, external_audio: bool = False):
        """
        Start the memory engine: background processing plus, unless
        external_audio is set, local ambient capture.

        Args:
            external_audio: when True, don't open the local Python microphone —
                the host app streams audio chunks in via ingest_chunk() instead.
        """
        if self._running:
            log.warning("Memory engine already running")
            return

        self._running = True
        self._paused = False
        self._external_audio = external_audio
        self._current_session_id = str(uuid.uuid4())[:8]
        self._last_speech_time = time.time()

        # Start background processing thread
        self._process_thread = threading.Thread(
            target=self._process_loop,
            daemon=True,
            name="memory-processor",
        )
        self._process_thread.start()

        if external_audio:
            self._capture = None
            log.info("🧠 Memory engine started in EXTERNAL audio mode (session: %s) — host app streams audio",
                     self._current_session_id)
        else:
            # Start local ambient capture
            chunk_duration = getattr(config, "MEMORY_CHUNK_DURATION", 30)
            enable_sys = getattr(config, "MEMORY_SYSTEM_AUDIO", False)

            self._capture = AmbientCapture(
                chunk_duration=chunk_duration,
                on_speech_chunk=self._on_speech_chunk,
                enable_system_audio=enable_sys,
                vad_aggressiveness=2,
            )
            self._capture.start()

            log.info("🧠 Memory engine started (session: %s)", self._current_session_id)

        # Auto-cleanup old segments on startup based on retention policy
        retention_days = getattr(config, "MEMORY_RETENTION_DAYS", 30)
        if retention_days > 0:
            try:
                deleted = self.store.delete_older_than(retention_days)
                if deleted > 0:
                    log.info("🧹 Auto-cleanup: removed %d segments older than %d days", deleted, retention_days)
            except Exception as e:
                log.warning("Auto-cleanup failed: %s", e)

    def stop(self):
        """Stop the memory engine."""
        self._running = False

        if self._capture:
            self._capture.stop()
            self._capture = None

        # Drain processing queue
        self._process_queue.put(None)  # Poison pill
        if self._process_thread:
            self._process_thread.join(timeout=10)

        # Flush vector store
        self.store.vector_store.flush()

        log.info("🛑 Memory engine stopped")

    def pause(self):
        """Temporarily pause capture (e.g., during Voxa command processing)."""
        self._paused = True
        if self._capture:
            self._capture.pause()
        log.debug("⏸️ Memory engine paused")

    def resume(self):
        """Resume capture after pause."""
        self._paused = False
        if self._capture:
            self._capture.resume()
        log.debug("▶️ Memory engine resumed")

    @property
    def is_active(self) -> bool:
        """Whether the memory engine is actively recording."""
        return self._running and not self._paused

    @property
    def status(self) -> dict:
        """Get current engine status."""
        stats = self.store.get_stats()
        return {
            "active": self.is_active,
            "running": self._running,
            "paused": self._paused,
            "current_session": self._current_session_id,
            "queue_size": self._process_queue.qsize(),
            **stats,
        }

    # ── Audio Callback ────────────────────────────────────────────────────────

    def _on_speech_chunk(self, wav_bytes: bytes, source: str):
        """
        Called by AmbientCapture when a speech-containing audio chunk is detected.
        Queues it for async processing (transcription + filtering + storage).
        """
        now = time.time()

        # Check if we need a new session (gap > 5 min since last speech)
        if now - self._last_speech_time > SESSION_GAP_SECONDS:
            self._current_session_id = str(uuid.uuid4())[:8]
            log.info("📝 New conversation session: %s", self._current_session_id)

        self._last_speech_time = now

        # Queue for processing
        chunk_duration = getattr(config, "MEMORY_CHUNK_DURATION", 30)
        try:
            self._process_queue.put_nowait({
                "wav_bytes": wav_bytes,
                "source": source,
                "session_id": self._current_session_id,
                "timestamp": time.time(),
                "chunk_duration": float(chunk_duration),
            })
        except queue.Full:
            log.warning("Memory processing queue full — dropping chunk")

    def ingest_chunk(self, wav_bytes: bytes, source: str = "mic") -> bool:
        """
        Feed an externally-captured audio chunk (WAV bytes from the host app)
        into the same pipeline as local capture. Used in external_audio mode.

        Returns True if the chunk was queued, False if ignored (not running,
        paused, or empty).
        """
        if not self._running or self._paused or not wav_bytes:
            return False
        # Silence gate: drop true silence before it costs a Whisper call. The
        # external-audio path has no local VAD, so this is the only filter here.
        from voxa.utils.audio_energy import is_silent
        if is_silent(wav_bytes, getattr(config, "MEMORY_SILENCE_RMS", 180.0)):
            log.debug("Ingest: dropping near-silent chunk")
            return False
        self._on_speech_chunk(wav_bytes, source)
        return True

    # ── Background Processing ─────────────────────────────────────────────────

    def _process_loop(self):
        """
        Background thread that processes queued speech chunks:
        1. Transcribe with Whisper
        2. Filter with gpt-4o-mini
        3. Generate embedding
        4. Store in database
        """
        log.info("📦 Memory processing thread started")

        while self._running:
            try:
                item = self._process_queue.get(timeout=2.0)
                if item is None:  # Poison pill
                    break

                self._process_chunk(item)

            except queue.Empty:
                continue
            except Exception as e:
                log.error("Error in memory processing loop: %s", e)

        log.info("📦 Memory processing thread stopped")

    def _process_chunk(self, item: dict):
        """Process a single speech chunk through the full pipeline."""
        wav_bytes = item["wav_bytes"]
        source = item["source"]
        session_id = item["session_id"]
        chunk_time = item["timestamp"]

        start = time.time()

        # 1. Transcribe with Whisper
        raw_transcript = self._transcribe(wav_bytes)
        if not raw_transcript or len(raw_transcript.strip()) < 5:
            log.debug("Transcription too short or empty — skipping")
            log.debug("Skipping clip — non-meaningful/short chunk")
            return

        # 2. Filter with LLM (remove filler, keep substance)
        filter_result = self._filter_transcript(raw_transcript, source=source)
        filtered_text = filter_result.get("filtered_text", raw_transcript)
        summary = filter_result.get("summary", "")
        tags = filter_result.get("tags", "")
        is_meaningful = filter_result.get("is_meaningful", True)

        if not is_meaningful:
            log.debug("LLM marked transcript as non-meaningful — skipping: '%s'",
                      raw_transcript[:80])
            log.debug("Skipping clip — non-meaningful/short chunk")
            return

        # 3. Generate embedding for semantic search
        embedding = self._generate_embedding(filtered_text)

        # 4. Store in database
        # Use actual audio chunk duration, not processing time
        duration_secs = item.get("chunk_duration", 30.0)
        # Persist the audio clip for meaningful chunks (silent/non-meaningful
        # audio already returned above, so it's never written to disk).
        audio_path = ""
        if getattr(config, "MEMORY_KEEP_AUDIO", True):
            audio_path = self.store.save_clip(wav_bytes)
        self.store.store_segment(
            raw_transcript=raw_transcript,
            filtered_text=filtered_text,
            summary=summary,
            source=source,
            tags=tags,
            session_id=session_id,
            duration_secs=duration_secs,
            embedding=embedding,
            audio_path=audio_path,
        )

        elapsed = time.time() - start
        log.info("✅ Memory chunk processed in %.1fs: '%s' → '%s'",
                 elapsed, raw_transcript[:50], summary[:50])

        # 5. Proactive suggestions — detect calendar intents in the conversation
        if config.MEETING_SUGGESTIONS:
            try:
                from voxa.memory.suggestions import suggestion_manager
                suggestion_manager.analyze_chunk(filtered_text, source=source, session_id=session_id)
            except Exception as e:
                log.debug("Suggestion analysis skipped: %s", e)

        # 6. To-do capture — pull commitments out of ordinary conversation, not
        # just meetings. Gated on a cheap keyword check inside analyze_chunk, so
        # idle chatter never reaches the model.
        if getattr(config, "TODO_AUTO_CAPTURE", True):
            try:
                from voxa.memory.todos import todo_manager
                todo_manager.analyze_chunk(filtered_text, source=source, session_id=session_id)
            except Exception as e:
                log.debug("Todo analysis skipped: %s", e)

    # ── Transcription ─────────────────────────────────────────────────────────

    def _transcribe(self, wav_bytes: bytes) -> Optional[str]:
        """Transcribe audio bytes using Whisper API."""
        import io
        try:
            client = self._get_client()
            audio_file = io.BytesIO(wav_bytes)
            audio_file.name = "ambient_chunk.wav"

            response = client.audio.transcriptions.create(
                model=config.WHISPER_MODEL,
                file=audio_file,
                language="en",
                response_format="text",
            )

            text = response.strip() if isinstance(response, str) else response.text.strip()
            return text if text else None

        except Exception as e:
            log.error("Memory transcription error: %s", e)
            return None

    # ── LLM Filtering ────────────────────────────────────────────────────────

    def _filter_transcript(self, raw_text: str, source: str = "mic") -> dict:
        """
        Use gpt-4o-mini to:
        1. Determine if the transcript is meaningful (vs. background noise / filler)
        2. Clean up the text (remove filler words, fix grammar)
        3. Generate a one-line summary
        4. Auto-tag with topics

        Args:
            source: "mic" (the primary user's own voice) or "system" (the other
                meeting participants, from system audio) — used to attribute turns.

        Returns:
            Dict with keys: is_meaningful, filtered_text, summary, tags
        """
        if source == "mic":
            source_hint = (
                "This audio is the PRIMARY USER's own microphone — attribute these "
                "turns to 'Me'."
            )
        elif source == "system":
            source_hint = (
                "This audio is the OTHER PARTICIPANTS (captured from system/speaker "
                "output) — attribute turns to the participant's name if known, "
                "otherwise 'Participant'. Do NOT label these as 'Me'."
            )
        else:
            source_hint = ""
        try:
            client = self._get_client()
            response = client.chat.completions.create(
                model=config.LLM_MODEL_FAST,  # gpt-4o-mini
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a conversation filter and speaker diarization assistant. Given a raw transcript from ambient audio "
                            "containing turn-taking speech, identify/distinguish between different speakers based on style, tone, "
                            "context clues, and turn-taking.\n\n"
                            + (source_hint + "\n\n" if source_hint else "")
                            + "Rules:\n"
                            "- Mark as NOT meaningful: random noise, single-word utterances, music lyrics, background TV/radio, pure filler.\n"
                            "- Mark as meaningful: actual conversations, discussions, phone calls, meetings.\n"
                            "- For meaningful content, output the dialog in structured transcript format, attributing each turn "
                            "  to a speaker (e.g. 'Person A: ...', 'Person B: ...'). If a speaker's actual name is mentioned or "
                            "  clear from the context, use their name (e.g. 'Aman: ...', 'John: ...').\n"
                            "- Clean up filler words, fix minor grammar, and keep the dialog style clear.\n"
                            "- Generate a brief one-line summary of the conversation topic (max 15 words).\n"
                            "- Auto-detect topic tags (comma-separated, max 5 tags).\n\n"
                            "Respond in JSON format only:\n"
                            '{"is_meaningful": true/false, "filtered_text": "Speaker dialogue here", '
                            '"summary": "one line summary", "tags": "tag1,tag2"}'
                        ),
                    },
                    {"role": "user", "content": raw_text},
                ],
                temperature=0.2,
                max_tokens=600,
            )

            content = response.choices[0].message.content.strip()

            # Parse JSON response
            import json
            # Handle markdown code blocks
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
                content = content.strip()

            result = json.loads(content)
            return {
                "is_meaningful": result.get("is_meaningful", True),
                "filtered_text": result.get("filtered_text", raw_text),
                "summary": result.get("summary", ""),
                "tags": result.get("tags", ""),
            }

        except Exception as e:
            log.warning("LLM filter failed, storing raw transcript: %s", e)
            return {
                "is_meaningful": True,
                "filtered_text": raw_text,
                "summary": "",
                "tags": "",
            }

    # ── Embedding Generation ──────────────────────────────────────────────────

    def _generate_embedding(self, text: str) -> Optional[list[float]]:
        """Generate a text embedding using OpenAI's embedding model."""
        try:
            client = self._get_client()
            response = client.embeddings.create(
                model="text-embedding-3-small",
                input=text,
            )
            return response.data[0].embedding
        except Exception as e:
            log.warning("Embedding generation failed: %s", e)
            return None

    # ── Maintenance ───────────────────────────────────────────────────────────

    def cleanup(self, days: int | None = None):
        """Delete old memory segments."""
        retention = days or getattr(config, "MEMORY_RETENTION_DAYS", 30)
        deleted = self.store.delete_older_than(retention)
        log.info("🧹 Cleaned up %d segments older than %d days", deleted, retention)
        return deleted


# ── Singleton ────────────────────────────────────────────────────────────────────

memory_engine = MemoryEngine()
