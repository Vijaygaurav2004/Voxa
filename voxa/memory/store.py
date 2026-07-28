"""
Voxa Memory Store — Persistent Storage for Conversation Memory.

Uses SQLite with FTS5 full-text search for keyword queries and
numpy-based vector storage for semantic similarity search.

Storage location: ~/.voxa/memory/
  - voxa_memory.db   (SQLite database)
  - vectors/          (numpy .npy embedding files)
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
import uuid
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from voxa.utils.logger import get_logger

log = get_logger("memory.store")

# ── Storage Paths ────────────────────────────────────────────────────────────────

MEMORY_DIR = Path.home() / ".voxa" / "memory"
MEMORY_DB = MEMORY_DIR / "voxa_memory.db"
VECTORS_DIR = MEMORY_DIR / "vectors"


# ── Data Classes ─────────────────────────────────────────────────────────────────

class MemorySegment:
    """A single segment of conversation stored in memory."""

    def __init__(
        self,
        raw_transcript: str,
        filtered_text: str,
        summary: str = "",
        source: str = "microphone",
        tags: str = "",
        session_id: str = "",
        duration_secs: float = 0.0,
        timestamp: str | None = None,
        segment_id: int | None = None,
        embedding_id: int | None = None,
        audio_path: str = "",
    ):
        self.segment_id = segment_id
        self.timestamp = timestamp or datetime.now().isoformat()
        self.duration_secs = duration_secs
        self.raw_transcript = raw_transcript
        self.filtered_text = filtered_text
        self.summary = summary
        self.source = source
        self.tags = tags
        self.session_id = session_id or str(uuid.uuid4())[:8]
        self.embedding_id = embedding_id
        self.audio_path = audio_path

    def to_dict(self) -> dict:
        return {
            "id": self.segment_id,
            "timestamp": self.timestamp,
            "duration_secs": self.duration_secs,
            "raw_transcript": self.raw_transcript,
            "filtered_text": self.filtered_text,
            "summary": self.summary,
            "source": self.source,
            "tags": self.tags,
            "session_id": self.session_id,
            "embedding_id": self.embedding_id,
            "audio_path": self.audio_path,
        }

    @classmethod
    def from_row(cls, row: dict) -> "MemorySegment":
        return cls(
            segment_id=row.get("id"),
            timestamp=row.get("timestamp"),
            duration_secs=row.get("duration_secs", 0.0),
            raw_transcript=row.get("raw_transcript", ""),
            filtered_text=row.get("filtered_text", ""),
            summary=row.get("summary", ""),
            source=row.get("source", "microphone"),
            tags=row.get("tags", ""),
            session_id=row.get("session_id", ""),
            embedding_id=row.get("embedding_id"),
            audio_path=row.get("audio_path", ""),
        )


# ── Vector Store ─────────────────────────────────────────────────────────────────

class VectorStore:
    """
    Lightweight numpy-based vector store for semantic search.
    Stores embeddings as a single .npy matrix file and an ID mapping.
    Optimized for fast cosine similarity over 100K+ vectors.
    """

    def __init__(self, vectors_dir: Path = VECTORS_DIR):
        self.vectors_dir = vectors_dir
        self.vectors_file = vectors_dir / "embeddings.npy"
        self.ids_file = vectors_dir / "ids.json"
        self._embeddings: np.ndarray | None = None  # shape: (N, dim)
        self._ids: list[int] = []
        self._dirty = False
        self._load()

    def _load(self):
        """Load embeddings and IDs from disk."""
        self.vectors_dir.mkdir(parents=True, exist_ok=True)

        if self.vectors_file.exists() and self.ids_file.exists():
            try:
                self._embeddings = np.load(self.vectors_file)
                with open(self.ids_file, "r") as f:
                    self._ids = json.load(f)
                log.info("📦 Loaded %d embeddings from disk", len(self._ids))
            except Exception as e:
                log.error("Failed to load vector store: %s", e)
                self._embeddings = None
                self._ids = []
        else:
            self._embeddings = None
            self._ids = []

    def _save(self):
        """Persist embeddings and IDs to disk."""
        if not self._dirty:
            return
        try:
            self.vectors_dir.mkdir(parents=True, exist_ok=True)
            if self._embeddings is not None and len(self._ids) > 0:
                np.save(self.vectors_file, self._embeddings)
                with open(self.ids_file, "w") as f:
                    json.dump(self._ids, f)
            self._dirty = False
        except Exception as e:
            log.error("Failed to save vector store: %s", e)

    def add(self, segment_id: int, embedding: list[float]) -> int:
        """
        Add an embedding vector for a segment.

        Args:
            segment_id: The database ID of the memory segment.
            embedding: The embedding vector (e.g., 1536-dim from text-embedding-3-small).

        Returns:
            The embedding index.
        """
        vec = np.array(embedding, dtype=np.float32).reshape(1, -1)

        if self._embeddings is None:
            self._embeddings = vec
        else:
            self._embeddings = np.vstack([self._embeddings, vec])

        self._ids.append(segment_id)
        self._dirty = True

        # Auto-save every 50 additions
        if len(self._ids) % 50 == 0:
            self._save()

        return len(self._ids) - 1

    def search(self, query_embedding: list[float], top_k: int = 10) -> list[tuple[int, float]]:
        """
        Find the most similar segments using cosine similarity.

        Args:
            query_embedding: The query embedding vector.
            top_k: Number of top results to return.

        Returns:
            List of (segment_id, similarity_score) tuples, sorted by relevance.
        """
        if self._embeddings is None or len(self._ids) == 0:
            return []

        query = np.array(query_embedding, dtype=np.float32).reshape(1, -1)

        # Cosine similarity: dot(A, B) / (||A|| * ||B||)
        norms = np.linalg.norm(self._embeddings, axis=1, keepdims=True)
        query_norm = np.linalg.norm(query)

        if query_norm == 0:
            return []

        # Avoid division by zero
        norms = np.maximum(norms, 1e-8)
        similarities = (self._embeddings @ query.T).flatten() / (norms.flatten() * query_norm)

        # Get top-k indices
        k = min(top_k, len(self._ids))
        top_indices = np.argpartition(similarities, -k)[-k:]
        top_indices = top_indices[np.argsort(similarities[top_indices])[::-1]]

        return [(self._ids[i], float(similarities[i])) for i in top_indices]

    def remove(self, segment_id: int):
        """Remove an embedding by segment ID."""
        if segment_id in self._ids:
            idx = self._ids.index(segment_id)
            self._ids.pop(idx)
            if self._embeddings is not None:
                self._embeddings = np.delete(self._embeddings, idx, axis=0)
                if len(self._embeddings) == 0:
                    self._embeddings = None
            self._dirty = True

    def flush(self):
        """Force save to disk."""
        self._save()

    def clear(self):
        """Remove all embeddings and persist."""
        self._embeddings = None
        self._ids = []
        self._dirty = True
        self._save()

    @property
    def count(self) -> int:
        return len(self._ids)


# ── Memory Store (SQLite + FTS5) ─────────────────────────────────────────────────

class MemoryStore:
    """
    Persistent storage for conversation memory segments.
    Uses SQLite with FTS5 for keyword search and VectorStore for semantic search.
    """

    def __init__(self, db_path: Path = MEMORY_DB):
        self.db_path = str(db_path)
        # Derive the clips dir from the db path parent so an injected db_path
        # (e.g. tests using tmp_path) automatically isolates its audio clips.
        self.clips_dir = Path(self.db_path).parent / "clips"
        self.vector_store = VectorStore()
        self._init_db()

    def _init_db(self):
        """Create tables if they don't exist."""
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)

        with sqlite3.connect(self.db_path) as conn:
            # Main table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memory_segments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    duration_secs REAL DEFAULT 0.0,
                    raw_transcript TEXT NOT NULL,
                    filtered_text TEXT NOT NULL,
                    summary TEXT DEFAULT '',
                    source TEXT DEFAULT 'microphone',
                    tags TEXT DEFAULT '',
                    embedding_id INTEGER,
                    session_id TEXT DEFAULT ''
                )
            """)

            # Idempotent migration: add audio_path column for on-disk clips.
            cols = [r[1] for r in conn.execute("PRAGMA table_info(memory_segments)").fetchall()]
            if "audio_path" not in cols:
                conn.execute("ALTER TABLE memory_segments ADD COLUMN audio_path TEXT DEFAULT ''")

            # Indexes
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_memory_timestamp
                ON memory_segments(timestamp)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_memory_session
                ON memory_segments(session_id)
            """)

            # FTS5 full-text search
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts
                USING fts5(
                    filtered_text,
                    summary,
                    tags,
                    content=memory_segments,
                    content_rowid=id
                )
            """)

            # Sync triggers
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS memory_ai AFTER INSERT ON memory_segments BEGIN
                    INSERT INTO memory_fts(rowid, filtered_text, summary, tags)
                    VALUES (new.id, new.filtered_text, new.summary, new.tags);
                END
            """)
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS memory_ad AFTER DELETE ON memory_segments BEGIN
                    INSERT INTO memory_fts(memory_fts, rowid, filtered_text, summary, tags)
                    VALUES ('delete', old.id, old.filtered_text, old.summary, old.tags);
                END
            """)
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS memory_au AFTER UPDATE ON memory_segments BEGIN
                    INSERT INTO memory_fts(memory_fts, rowid, filtered_text, summary, tags)
                    VALUES ('delete', old.id, old.filtered_text, old.summary, old.tags);
                    INSERT INTO memory_fts(rowid, filtered_text, summary, tags)
                    VALUES (new.id, new.filtered_text, new.summary, new.tags);
                END
            """)

        log.info("✅ Memory database initialized at %s", self.db_path)

    # ── Write Operations ─────────────────────────────────────────────────────

    def store_segment(
        self,
        raw_transcript: str,
        filtered_text: str,
        summary: str = "",
        source: str = "microphone",
        tags: str = "",
        session_id: str = "",
        duration_secs: float = 0.0,
        embedding: list[float] | None = None,
        audio_path: str = "",
    ) -> MemorySegment:
        """
        Store a new conversation segment.

        Args:
            raw_transcript: Original Whisper output.
            filtered_text: LLM-cleaned version (substance only).
            summary: One-line summary.
            source: Audio source ('microphone', 'system_audio', 'both').
            tags: Comma-separated topic tags.
            session_id: Conversation session grouping ID.
            duration_secs: Duration of the audio segment.
            embedding: Optional pre-computed embedding vector.
            audio_path: Full path to the stored audio clip (empty if not kept).

        Returns:
            The stored MemorySegment with its assigned ID.
        """
        timestamp = datetime.now().isoformat()

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """INSERT INTO memory_segments
                   (timestamp, duration_secs, raw_transcript, filtered_text,
                    summary, source, tags, session_id, audio_path)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (timestamp, duration_secs, raw_transcript, filtered_text,
                 summary, source, tags, session_id, audio_path),
            )
            segment_id = cursor.lastrowid

        # Store embedding if provided
        embedding_id = None
        if embedding and segment_id:
            embedding_id = self.vector_store.add(segment_id, embedding)
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "UPDATE memory_segments SET embedding_id = ? WHERE id = ?",
                    (embedding_id, segment_id),
                )

        segment = MemorySegment(
            segment_id=segment_id,
            timestamp=timestamp,
            duration_secs=duration_secs,
            raw_transcript=raw_transcript,
            filtered_text=filtered_text,
            summary=summary,
            source=source,
            tags=tags,
            session_id=session_id,
            embedding_id=embedding_id,
            audio_path=audio_path,
        )

        log.info("💾 Stored memory segment #%d (session: %s, %.1fs)",
                 segment_id, session_id[:8], duration_secs)
        return segment

    # ── Audio Clips ──────────────────────────────────────────────────────────

    def save_clip(self, wav_bytes: bytes) -> str:
        """Write WAV bytes to clips/<uuid>.wav; return the full path str, or '' on failure.

        Does NOT touch the DB — the caller passes the returned path to
        store_segment(audio_path=...).
        """
        try:
            self.clips_dir.mkdir(parents=True, exist_ok=True)
            path = self.clips_dir / f"{uuid.uuid4().hex}.wav"
            path.write_bytes(wav_bytes)
            return str(path)
        except Exception as e:
            log.warning("Failed to save audio clip: %s", e)
            return ""

    def list_clips(self, limit: int = 50) -> list[dict]:
        """List segments that still have a clip file, newest first."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT id, timestamp, duration_secs, summary, source,
                          session_id, audio_path
                   FROM memory_segments
                   WHERE audio_path != ''
                   ORDER BY timestamp DESC
                   LIMIT ?""",
                (limit,),
            ).fetchall()

        clips = []
        for r in rows:
            audio_path = r["audio_path"]
            p = Path(audio_path)
            size = p.stat().st_size if p.exists() else 0
            clips.append({
                "id": r["id"],
                "timestamp": r["timestamp"],
                "duration_secs": r["duration_secs"],
                "summary": r["summary"],
                "source": r["source"],
                "session_id": r["session_id"],
                "size_bytes": size,
                "audio_path": audio_path,
            })
        return clips

    def get_clip_path(self, segment_id: int) -> Optional[str]:
        """Return the audio_path for a segment if its file exists, else None."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT audio_path FROM memory_segments WHERE id = ?",
                (segment_id,),
            ).fetchone()
        if not row or not row[0]:
            return None
        return row[0] if Path(row[0]).exists() else None

    def delete_segment(self, segment_id: int) -> bool:
        """Delete a segment: unlink its clip file, remove the DB row + its vector.

        Returns True if a row was deleted, False if the id didn't exist.
        """
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT audio_path FROM memory_segments WHERE id = ?",
                (segment_id,),
            ).fetchone()
            if row is None:
                return False
            audio_path = row[0]
            # FTS trigger handles the FTS row cleanup.
            conn.execute("DELETE FROM memory_segments WHERE id = ?", (segment_id,))

        if audio_path:
            try:
                p = Path(audio_path)
                if p.exists():
                    p.unlink()
            except Exception as e:
                log.warning("Failed to unlink clip %s: %s", audio_path, e)

        self.vector_store.remove(segment_id)
        self.vector_store.flush()

        log.info("🗑️ Deleted memory segment #%s", segment_id)
        return True

    def clear_clips(self) -> int:
        """Unlink all clip FILES but keep transcripts (audio_path reset to '').

        Returns the count of files removed.
        """
        removed = 0
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT audio_path FROM memory_segments WHERE audio_path != ''"
            ).fetchall()
            for (audio_path,) in rows:
                if not audio_path:
                    continue
                try:
                    p = Path(audio_path)
                    if p.exists():
                        p.unlink()
                        removed += 1
                except Exception as e:
                    log.warning("Failed to unlink clip %s: %s", audio_path, e)
            conn.execute("UPDATE memory_segments SET audio_path = '' WHERE audio_path != ''")

        log.info("🧹 Cleared %d audio clips (transcripts kept)", removed)
        return removed

    def clips_stats(self) -> tuple[int, int]:
        """Return (count of rows with an existing clip file, total bytes on disk)."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT audio_path FROM memory_segments WHERE audio_path != ''"
            ).fetchall()
        count = 0
        total = 0
        for (audio_path,) in rows:
            p = Path(audio_path)
            if p.exists():
                count += 1
                total += p.stat().st_size
        return count, total

    # ── Session-grouped Clips ──────────────────────────────────────────────────

    def get_session_clips(self, session_id: str) -> list[dict]:
        """Clips for one session that still have a file, oldest→newest.

        Each dict is {id, timestamp, duration_secs, summary, source, session_id,
        size_bytes} (size from the file on disk, 0 if missing). audio_path is
        intentionally omitted — the server never leaks disk paths to the client.
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT id, timestamp, duration_secs, summary, source,
                          session_id, audio_path
                   FROM memory_segments
                   WHERE session_id = ? AND audio_path != ''
                   ORDER BY timestamp ASC""",
                (session_id,),
            ).fetchall()

        clips = []
        for r in rows:
            p = Path(r["audio_path"])
            size = p.stat().st_size if p.exists() else 0
            clips.append({
                "id": r["id"],
                "timestamp": r["timestamp"],
                "duration_secs": r["duration_secs"],
                "summary": r["summary"],
                "source": r["source"],
                "session_id": r["session_id"],
                "size_bytes": size,
            })
        return clips

    def list_sessions_with_clips(self, limit: int = 30) -> list[dict]:
        """Group clip-bearing segments by session, newest session first.

        Returns per session {session_id, clip_count, started_iso (MIN timestamp),
        ended_iso (MAX timestamp), duration_secs (SUM), sources (DISTINCT source)}.
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT session_id,
                          COUNT(*) as clip_count,
                          MIN(timestamp) as started_iso,
                          MAX(timestamp) as ended_iso,
                          COALESCE(SUM(duration_secs), 0.0) as duration_secs,
                          GROUP_CONCAT(DISTINCT source) as sources
                   FROM memory_segments
                   WHERE audio_path != ''
                   GROUP BY session_id
                   ORDER BY MAX(timestamp) DESC
                   LIMIT ?""",
                (limit,),
            ).fetchall()

        sessions = []
        for r in rows:
            sources_raw = r["sources"] or ""
            sources = [s for s in sources_raw.split(",") if s]
            sessions.append({
                "session_id": r["session_id"],
                "clip_count": r["clip_count"],
                "started_iso": r["started_iso"],
                "ended_iso": r["ended_iso"],
                "duration_secs": r["duration_secs"],
                "sources": sources,
            })
        return sessions

    def clear_session_clips(self, session_id: str) -> int:
        """Unlink one session's clip FILES but keep its transcripts.

        Mirrors clear_clips() but scoped to a single session_id: removes the files
        then resets their audio_path to ''. Returns the count of files removed.
        """
        removed = 0
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT audio_path FROM memory_segments "
                "WHERE session_id = ? AND audio_path != ''",
                (session_id,),
            ).fetchall()
            for (audio_path,) in rows:
                if not audio_path:
                    continue
                try:
                    p = Path(audio_path)
                    if p.exists():
                        p.unlink()
                        removed += 1
                except Exception as e:
                    log.warning("Failed to unlink clip %s: %s", audio_path, e)
            conn.execute(
                "UPDATE memory_segments SET audio_path = '' "
                "WHERE session_id = ? AND audio_path != ''",
                (session_id,),
            )

        log.info("🧹 Cleared %d clips for session %s (transcripts kept)",
                 removed, (session_id or "")[:8])
        return removed

    # ── Read Operations ──────────────────────────────────────────────────────

    @staticmethod
    def _sanitize_fts_query(query: str) -> str:
        """
        Sanitize a user query for FTS5 MATCH syntax.
        Strips special FTS5 operators to prevent parse errors.
        """
        # Remove FTS5 special chars that can cause parse errors
        sanitized = re.sub(r'["*(){}\[\]^~:!]', ' ', query)
        # Collapse whitespace
        sanitized = re.sub(r'\s+', ' ', sanitized).strip()
        # If empty after sanitization, fall back to wildcard-safe token
        return sanitized if sanitized else 'a'

    def search_text(self, query: str, limit: int = 20) -> list[MemorySegment]:
        """
        Full-text search using FTS5.
        Supports natural language queries — FTS5 handles tokenization.
        """
        safe_query = self._sanitize_fts_query(query)
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                # Use FTS5 MATCH with BM25 ranking
                rows = conn.execute(
                    """SELECT m.*, rank
                       FROM memory_fts fts
                       JOIN memory_segments m ON m.id = fts.rowid
                       WHERE memory_fts MATCH ?
                       ORDER BY rank
                       LIMIT ?""",
                    (safe_query, limit),
                ).fetchall()

            return [MemorySegment.from_row(dict(r)) for r in rows]
        except Exception as e:
            log.warning("FTS5 search failed for query '%s': %s", query[:50], e)
            return []

    def search_semantic(
        self,
        query_embedding: list[float],
        limit: int = 10,
    ) -> list[tuple[MemorySegment, float]]:
        """
        Semantic similarity search using vector embeddings.

        Args:
            query_embedding: The embedding of the search query.
            limit: Max results.

        Returns:
            List of (MemorySegment, similarity_score) tuples.
        """
        results = self.vector_store.search(query_embedding, top_k=limit)
        if not results:
            return []

        segments = []
        segment_ids = [sid for sid, _ in results]
        score_map = {sid: score for sid, score in results}

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            placeholders = ",".join("?" * len(segment_ids))
            rows = conn.execute(
                f"SELECT * FROM memory_segments WHERE id IN ({placeholders})",
                segment_ids,
            ).fetchall()

        row_map = {r["id"]: r for r in rows}
        for sid in segment_ids:
            if sid in row_map:
                seg = MemorySegment.from_row(dict(row_map[sid]))
                segments.append((seg, score_map[sid]))

        return segments

    def search_hybrid(
        self,
        query: str,
        query_embedding: list[float] | None = None,
        limit: int = 10,
    ) -> list[MemorySegment]:
        """
        Combined FTS + semantic search with deduplication and re-ranking.

        Args:
            query: Text query for FTS5.
            query_embedding: Embedding for semantic search.
            limit: Max results.

        Returns:
            Deduplicated, re-ranked list of MemorySegments.
        """
        seen_ids: set[int] = set()
        scored: list[tuple[MemorySegment, float]] = []

        # 1. FTS5 results (keyword relevance)
        fts_results = self.search_text(query, limit=limit * 2)
        for i, seg in enumerate(fts_results):
            if seg.segment_id and seg.segment_id not in seen_ids:
                seen_ids.add(seg.segment_id)
                # BM25 score: higher rank = earlier position, normalize to 0-1
                fts_score = 1.0 - (i / max(len(fts_results), 1))
                scored.append((seg, fts_score * 0.4))  # 40% weight

        # 2. Semantic results (meaning relevance)
        if query_embedding:
            sem_results = self.search_semantic(query_embedding, limit=limit * 2)
            for seg, sim_score in sem_results:
                if seg.segment_id and seg.segment_id not in seen_ids:
                    seen_ids.add(seg.segment_id)
                    scored.append((seg, sim_score * 0.6))  # 60% weight
                elif seg.segment_id:
                    # Boost existing FTS result with semantic score
                    for i, (existing, existing_score) in enumerate(scored):
                        if existing.segment_id == seg.segment_id:
                            scored[i] = (existing, existing_score + sim_score * 0.6)
                            break

        # Sort by combined score (descending)
        scored.sort(key=lambda x: x[1], reverse=True)
        return [seg for seg, _ in scored[:limit]]

    def get_recent(self, hours: float = 24.0, limit: int = 50) -> list[MemorySegment]:
        """Get recent memory segments within the last N hours."""
        cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT * FROM memory_segments
                   WHERE timestamp >= ?
                   ORDER BY timestamp DESC
                   LIMIT ?""",
                (cutoff, limit),
            ).fetchall()
        return [MemorySegment.from_row(dict(r)) for r in rows]

    def get_by_session(self, session_id: str) -> list[MemorySegment]:
        """Get all segments from a specific conversation session."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT * FROM memory_segments
                   WHERE session_id = ?
                   ORDER BY timestamp ASC""",
                (session_id,),
            ).fetchall()
        return [MemorySegment.from_row(dict(r)) for r in rows]

    def list_sessions(self, limit: int = 20) -> list[dict]:
        """List recent conversation sessions with metadata."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT session_id,
                          COUNT(*) as segment_count,
                          MIN(timestamp) as start_time,
                          MAX(timestamp) as end_time,
                          SUM(duration_secs) as total_duration,
                          GROUP_CONCAT(DISTINCT tags) as all_tags
                   FROM memory_segments
                   WHERE session_id != ''
                   GROUP BY session_id
                   ORDER BY MAX(timestamp) DESC
                   LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Maintenance ──────────────────────────────────────────────────────────

    def delete_older_than(self, days: int) -> int:
        """Delete segments older than N days. Returns count deleted."""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()

        with sqlite3.connect(self.db_path) as conn:
            # Get IDs + clip paths to delete (for vector + clip-file cleanup)
            rows = conn.execute(
                "SELECT id, audio_path FROM memory_segments WHERE timestamp < ?",
                (cutoff,),
            ).fetchall()
            ids_to_delete = [r[0] for r in rows]
            clip_paths = [r[1] for r in rows if r[1]]

            if not ids_to_delete:
                return 0

            # Delete from main table (FTS trigger handles FTS cleanup)
            conn.execute(
                "DELETE FROM memory_segments WHERE timestamp < ?",
                (cutoff,),
            )

        # Unlink clip files
        for cp in clip_paths:
            try:
                p = Path(cp)
                if p.exists():
                    p.unlink()
            except Exception as e:
                log.warning("Failed to unlink clip %s: %s", cp, e)

        # Clean up vectors
        for sid in ids_to_delete:
            self.vector_store.remove(sid)
        self.vector_store.flush()

        log.info("🧹 Deleted %d memory segments older than %d days", len(ids_to_delete), days)
        return len(ids_to_delete)

    def clear_all(self) -> int:
        """Delete ALL memory segments. Returns count deleted."""
        with sqlite3.connect(self.db_path) as conn:
            count = conn.execute("SELECT COUNT(*) FROM memory_segments").fetchone()[0]
            conn.execute("DELETE FROM memory_segments")
            # Rebuild FTS index
            conn.execute("INSERT INTO memory_fts(memory_fts) VALUES('rebuild')")

        # Remove all clip files so none are orphaned
        try:
            if self.clips_dir.exists():
                for f in self.clips_dir.glob("*.wav"):
                    try:
                        f.unlink()
                    except Exception:
                        pass
        except Exception as e:
            log.warning("Failed clearing clips dir: %s", e)

        # Clear vectors via public API
        self.vector_store.clear()

        log.info("🧹 Cleared all %d memory segments", count)
        return count

    def get_stats(self) -> dict:
        """Get memory storage statistics."""
        with sqlite3.connect(self.db_path) as conn:
            total = conn.execute("SELECT COUNT(*) FROM memory_segments").fetchone()[0]
            total_duration = conn.execute(
                "SELECT COALESCE(SUM(duration_secs), 0) FROM memory_segments"
            ).fetchone()[0]
            sessions = conn.execute(
                "SELECT COUNT(DISTINCT session_id) FROM memory_segments WHERE session_id != ''"
            ).fetchone()[0]
            oldest = conn.execute(
                "SELECT MIN(timestamp) FROM memory_segments"
            ).fetchone()[0]
            newest = conn.execute(
                "SELECT MAX(timestamp) FROM memory_segments"
            ).fetchone()[0]

        # Disk usage
        db_size = Path(self.db_path).stat().st_size if Path(self.db_path).exists() else 0
        vec_size = sum(
            f.stat().st_size for f in VECTORS_DIR.glob("*") if f.is_file()
        ) if VECTORS_DIR.exists() else 0

        clips_count, clips_bytes = self.clips_stats()

        return {
            "total_segments": total,
            "total_sessions": sessions,
            "total_duration_hours": round(total_duration / 3600, 2),
            "total_embeddings": self.vector_store.count,
            "oldest_segment": oldest,
            "newest_segment": newest,
            "db_size_mb": round(db_size / (1024 * 1024), 2),
            "vectors_size_mb": round(vec_size / (1024 * 1024), 2),
            "clips_count": clips_count,
            "clips_size_mb": round(clips_bytes / (1024 * 1024), 2),
        }
