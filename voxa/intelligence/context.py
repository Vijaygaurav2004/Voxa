"""
Context & Memory Layer for Voxa.
Maintains session state and persistent command history in SQLite.
"""
from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional, Any
from voxa.config import config
from voxa.utils.logger import get_logger

log = get_logger("context")


# ─── Session Context (In-Memory) ────────────────────────────────────────────────

@dataclass
class SessionContext:
    """
    Maintains in-memory session state for follow-up command resolution.
    Tracks recent commands, last-used entities, and conversation flow.
    """
    history: list[dict] = field(default_factory=list)
    last_app: Optional[str] = None
    last_url: Optional[str] = None
    last_query: Optional[str] = None
    last_file_path: Optional[str] = None
    session_start: float = field(default_factory=time.time)

    def add_command(self, user_input: str, actions: list[dict], result: str):
        """Record a completed command in session history."""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "input": user_input,
            "actions": actions,
            "result": result,
        }
        self.history.append(entry)

        # Cap history at 20 entries
        if len(self.history) > 20:
            self.history = self.history[-20:]

        # Track last-used entities for pronoun resolution
        for action in actions:
            if action.get("app"):
                self.last_app = action["app"]
            if action.get("url"):
                self.last_url = action["url"]
            if action.get("query"):
                self.last_query = action["query"]
            if action.get("path"):
                self.last_file_path = action["path"]

        log.debug("Context updated — last_app=%s, last_url=%s",
                  self.last_app, self.last_url)

    def get_context_for_llm(self, n: int = 5) -> str:
        """
        Format recent history for injection into LLM prompt.
        Provides enough context for the LLM to resolve follow-up commands.
        """
        recent = self.history[-n:]
        if not recent:
            return "No previous commands in this session."

        lines = []
        for entry in recent:
            lines.append(f"User said: \"{entry['input']}\"")
            action_summary = ", ".join(
                f"{a['action']}({a.get('app', a.get('url', a.get('query', '')))})"
                for a in entry["actions"]
            )
            lines.append(f"Actions taken: {action_summary}")
            lines.append(f"Result: {entry['result']}")
            lines.append("---")

        # Add current entity state
        state_parts = []
        if self.last_app:
            state_parts.append(f"Last app used: {self.last_app}")
        if self.last_url:
            state_parts.append(f"Last URL: {self.last_url}")
        if self.last_query:
            state_parts.append(f"Last search query: {self.last_query}")
        if state_parts:
            lines.append("Current state: " + "; ".join(state_parts))

        return "\n".join(lines)

    def clear(self):
        """Reset session context."""
        self.history.clear()
        self.last_app = None
        self.last_url = None
        self.last_query = None
        self.last_file_path = None
        self.session_start = time.time()
        log.info("Session context cleared")


# ─── Persistent History (SQLite) ────────────────────────────────────────────────

class CommandHistory:
    """
    Persistent command history stored in SQLite.
    Used for analytics, debugging, and long-term learning.
    """

    def __init__(self, db_path: str = str(config.DB_PATH)):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Create the history table if it doesn't exist."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS command_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    user_input TEXT NOT NULL,
                    actions_json TEXT NOT NULL,
                    result TEXT NOT NULL,
                    duration_ms INTEGER,
                    success INTEGER DEFAULT 1
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_timestamp ON command_history(timestamp)
            """)
        log.debug("Command history DB initialized at %s", self.db_path)

    def record(
        self,
        user_input: str,
        actions: list[dict],
        result: str,
        duration_ms: int,
        success: bool = True,
    ):
        """Record a command execution in persistent history."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO command_history
                   (timestamp, user_input, actions_json, result, duration_ms, success)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    datetime.now().isoformat(),
                    user_input,
                    json.dumps(actions),
                    result,
                    duration_ms,
                    1 if success else 0,
                ),
            )
        log.debug("Command recorded in history: \"%s\"", user_input[:50])

    def get_recent(self, n: int = 10) -> list[dict]:
        """Retrieve the N most recent commands."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM command_history ORDER BY id DESC LIMIT ?", (n,)
            ).fetchall()
        return [dict(row) for row in rows]

    def get_stats(self) -> dict:
        """Get usage statistics."""
        with sqlite3.connect(self.db_path) as conn:
            total = conn.execute("SELECT COUNT(*) FROM command_history").fetchone()[0]
            success = conn.execute(
                "SELECT COUNT(*) FROM command_history WHERE success = 1"
            ).fetchone()[0]
            avg_duration = conn.execute(
                "SELECT AVG(duration_ms) FROM command_history"
            ).fetchone()[0]
        return {
            "total_commands": total,
            "successful": success,
            "failed": total - success,
            "success_rate": f"{(success / total * 100):.1f}%" if total > 0 else "N/A",
            "avg_duration_ms": int(avg_duration) if avg_duration else 0,
        }
