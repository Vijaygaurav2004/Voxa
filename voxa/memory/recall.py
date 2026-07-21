"""
Voxa Memory Recall — Query & Answer System.

Provides RAG (Retrieval-Augmented Generation) over stored conversation memory.
When the user asks a question about past conversations, this module:
1. Runs hybrid search (keyword + semantic) to find relevant segments
2. Constructs a context window from retrieved segments
3. Calls gpt-4o to synthesize an accurate, grounded answer

Also supports:
  - Summarizing a day's conversations
  - Summarizing a specific meeting/session
  - Raw search results
"""
from __future__ import annotations

import time
import threading
from datetime import datetime, timedelta
from typing import Optional
from openai import OpenAI

from voxa.config import config
from voxa.utils.logger import get_logger
from voxa.memory.store import MemoryStore, MemorySegment

log = get_logger("memory.recall")

# OpenAI client (lazy, thread-safe)
_client: OpenAI | None = None
_client_lock = threading.Lock()


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        with _client_lock:
            # Double-check after acquiring lock
            if _client is None:
                _client = OpenAI(api_key=config.OPENAI_API_KEY)
    return _client


def _generate_query_embedding(query: str) -> Optional[list[float]]:
    """Generate an embedding for a search query."""
    try:
        client = _get_client()
        response = client.embeddings.create(
            model="text-embedding-3-small",
            input=query,
        )
        return response.data[0].embedding
    except Exception as e:
        log.warning("Query embedding generation failed: %s", e)
        return None


class MemoryRecall:
    """
    Query interface for Voxa's conversation memory.
    Supports natural language questions, summaries, and raw search.
    """

    def __init__(self, store: MemoryStore | None = None):
        self.store = store or MemoryStore()

    # ── Natural Language Q&A ──────────────────────────────────────────────────

    def answer_question(self, question: str, max_context_segments: int = 15) -> dict:
        """
        Answer a natural language question about past conversations using RAG.

        Args:
            question: The user's question (e.g., "What did Aman say about the deadline?")
            max_context_segments: Max number of segments to include in the context.

        Returns:
            Dict with: answer, sources (list of relevant segments), elapsed_ms
        """
        start = time.time()
        log.info("🔍 Memory recall: '%s'", question)

        # 1. Generate query embedding for semantic search
        query_embedding = _generate_query_embedding(question)

        # 2. Hybrid search — keyword + semantic
        results = self.store.search_hybrid(
            query=question,
            query_embedding=query_embedding,
            limit=max_context_segments,
        )

        if not results:
            elapsed = int((time.time() - start) * 1000)
            return {
                "answer": "I don't have any relevant conversations in my memory about that. "
                          "Make sure memory mode is enabled so I can listen and remember.",
                "sources": [],
                "elapsed_ms": elapsed,
            }

        # 3. Build context window from retrieved segments
        context_parts = []
        sources = []
        for seg in results:
            timestamp = seg.timestamp[:19] if seg.timestamp else "unknown"
            text = seg.filtered_text or seg.raw_transcript
            summary_hint = f" (Topic: {seg.summary})" if seg.summary else ""

            context_parts.append(
                f"[{timestamp}]{summary_hint}\n{text}"
            )
            sources.append(seg.to_dict())

        context = "\n\n---\n\n".join(context_parts)

        # 4. RAG — call gpt-4o with retrieved context
        answer = self._generate_answer(question, context)

        elapsed = int((time.time() - start) * 1000)
        log.info("✅ Memory recall answered in %dms (%d sources)", elapsed, len(sources))

        return {
            "answer": answer,
            "sources": sources,
            "source_count": len(sources),
            "elapsed_ms": elapsed,
        }

    def _generate_answer(self, question: str, context: str) -> str:
        """Generate an answer using gpt-4o with retrieved conversation context."""
        try:
            client = _get_client()
            response = client.chat.completions.create(
                model=config.LLM_MODEL,  # gpt-4o
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are Voxa's memory recall system. The user is asking about past conversations "
                            "that were recorded and transcribed. You have been provided with relevant conversation "
                            "segments from the user's recorded history.\n\n"
                            "Rules:\n"
                            "- Answer based ONLY on the provided conversation segments\n"
                            "- If the answer isn't in the segments, say so honestly\n"
                            "- Include timestamps when referencing specific conversations\n"
                            "- Be concise and direct\n"
                            "- If multiple conversations are relevant, synthesize the information\n"
                            "- Use natural, conversational language\n\n"
                            "Conversation segments from memory:\n"
                            f"{context}"
                        ),
                    },
                    {"role": "user", "content": question},
                ],
                temperature=0.2,
                max_tokens=500,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            log.error("RAG answer generation failed: %s", e)
            return f"Sorry, I encountered an error trying to recall that: {e}"

    # ── Summaries ─────────────────────────────────────────────────────────────

    def summarize_recent(self, hours: float = 24.0) -> dict:
        """
        Summarize all conversations from the last N hours.

        Args:
            hours: How far back to look.

        Returns:
            Dict with: summary, segment_count, elapsed_ms
        """
        start = time.time()
        segments = self.store.get_recent(hours=hours)

        if not segments:
            return {
                "summary": f"No conversations recorded in the last {hours:.0f} hours.",
                "segment_count": 0,
                "elapsed_ms": int((time.time() - start) * 1000),
            }

        # Build combined transcript
        parts = []
        for seg in segments:
            timestamp = seg.timestamp[:19] if seg.timestamp else ""
            text = seg.filtered_text or seg.raw_transcript
            parts.append(f"[{timestamp}] {text}")

        combined = "\n".join(parts)

        # Summarize with LLM
        summary = self._generate_summary(
            combined,
            f"Summarize the following conversations from the last {hours:.0f} hours. "
            "Group by topic/meeting if possible. Highlight key decisions, action items, and important information."
        )

        elapsed = int((time.time() - start) * 1000)
        return {
            "summary": summary,
            "segment_count": len(segments),
            "elapsed_ms": elapsed,
        }

    def summarize_session(self, session_id: str) -> dict:
        """
        Summarize a specific conversation session (meeting/call).

        Args:
            session_id: The session ID to summarize.

        Returns:
            Dict with: summary, segment_count, elapsed_ms
        """
        start = time.time()
        segments = self.store.get_by_session(session_id)

        if not segments:
            return {
                "summary": f"No segments found for session '{session_id}'.",
                "segment_count": 0,
                "elapsed_ms": int((time.time() - start) * 1000),
            }

        parts = []
        for seg in segments:
            timestamp = seg.timestamp[:19] if seg.timestamp else ""
            text = seg.filtered_text or seg.raw_transcript
            parts.append(f"[{timestamp}] {text}")

        combined = "\n".join(parts)

        summary = self._generate_summary(
            combined,
            "Summarize this conversation/meeting. Include: "
            "1) Key topics discussed, 2) Decisions made, 3) Action items, "
            "4) Any deadlines or commitments mentioned."
        )

        elapsed = int((time.time() - start) * 1000)
        return {
            "summary": summary,
            "segment_count": len(segments),
            "elapsed_ms": elapsed,
        }

    def _generate_summary(self, transcript: str, instruction: str) -> str:
        """Generate a summary of conversation segments using gpt-4o."""
        try:
            client = _get_client()
            
            # Truncate if too long (keep under ~12K tokens)
            max_chars = 40000
            if len(transcript) > max_chars:
                transcript = transcript[:max_chars] + "\n\n[... truncated ...]"

            response = client.chat.completions.create(
                model=config.LLM_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": instruction,
                    },
                    {"role": "user", "content": transcript},
                ],
                temperature=0.3,
                max_tokens=800,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            log.error("Summary generation failed: %s", e)
            return f"Error generating summary: {e}"

    # ── Raw Search ────────────────────────────────────────────────────────────

    def search(self, query: str, limit: int = 10) -> list[dict]:
        """
        Raw search across memory (hybrid keyword + semantic).

        Args:
            query: Search query.
            limit: Max results.

        Returns:
            List of segment dicts.
        """
        query_embedding = _generate_query_embedding(query)
        results = self.store.search_hybrid(
            query=query,
            query_embedding=query_embedding,
            limit=limit,
        )
        return [seg.to_dict() for seg in results]


# ── Singleton ────────────────────────────────────────────────────────────────────

memory_recall = MemoryRecall()
