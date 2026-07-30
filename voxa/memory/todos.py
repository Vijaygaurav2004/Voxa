"""
Todo Capture — turns whatever Voxa hears into a running to-do list.

Two feeds, one list:

  1. **Ambient** — every transcribed chunk from the MemoryEngine is offered to
     :meth:`TodoManager.analyze_chunk`. A cheap keyword gate skips ~all idle
     chatter, and only what survives costs a small/fast LLM call that pulls out
     genuine commitments ("I'll send the deck tonight").
  2. **Meetings** — when a meeting ends, MeetingManager hands its extracted
     ``action_items`` and ``todos`` to :meth:`TodoManager.ingest_meeting_notes`,
     so the structured notes and the live list never drift apart.

Both land in one de-duplicated store at ``~/.voxa/todos.json`` that the app's
Todos page reads, and that can be pushed to macOS Reminders in one tap.

Design mirrors voxa/memory/suggestions.py (module singleton, threading.Lock, a
single fresh-OpenAI-client fast-model touchpoint, defensive JSON persistence).
``_extract`` is the ONLY OpenAI touchpoint — tests patch it so they never hit
the network.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from voxa.utils.logger import get_logger

log = get_logger("memory.todos")

TODOS_FILE = Path.home() / ".voxa" / "todos.json"

# Keep the file bounded; completed items age out first.
MAX_STORED_TODOS = 500

# Cheap gate: only chunks that sound like a commitment cost an LLM call. Tuned
# to be generous (a missed to-do is worse than one wasted mini call) while still
# rejecting the overwhelming majority of ambient speech.
_TASK_HINTS = (
    "i'll", "i will", "ill send", "i'm going to", "im going to", "i am going to",
    "need to", "needs to", "have to", "has to", "gotta", "got to",
    "let me", "let's", "lets ", "remind me", "don't forget", "dont forget",
    "make sure", "action item", "to-do", "todo", "task",
    "follow up", "follow-up", "get back to", "circle back",
    "send", "email", "call", "ping", "share", "write up", "draft",
    "finish", "review", "check", "fix", "update", "book", "order",
    "by tomorrow", "by monday", "by friday", "by tonight", "end of day", "eod",
    "before the", "deadline", "due",
)

_SYSTEM_PROMPT = (
    "You extract concrete to-dos from a snippet of a real conversation.\n\n"
    "A to-do is something a person actually COMMITTED to doing — 'I'll send the "
    "deck tonight', 'can you review the PR by Friday', 'we need to book the "
    "venue'. It is NOT: idle chatter, opinions, questions, hypotheticals "
    "('we could maybe someday...'), things already finished ('I sent it'), or "
    "generic statements.\n\n"
    "Respond with JSON only:\n"
    '{"todos": [{"task": "short imperative task", "owner": "Me | <name> | \\"\\"", '
    '"due": "verbatim timing from the talk, or \\"\\"" }]}\n\n'
    "Rules:\n"
    "- Return an EMPTY list when nothing was genuinely committed to. That is the "
    "common case and is strongly preferred over inventing a task.\n"
    "- task: one short imperative line, no speaker labels, no trailing period.\n"
    "- owner: 'Me' when the speaker committed to it themselves, otherwise the "
    "person's name if it is clear, else an empty string.\n"
    "- due: copy the timing words actually used ('Friday', 'tonight', 'end of "
    "week'); empty string when none was given. Never invent a date.\n"
    "- Never output more than 4 items for one snippet."
)


def _norm(text: str) -> str:
    """Normalised key for de-duplication: lowercase, no punctuation/extra space."""
    cleaned = re.sub(r"[^\w\s]", " ", (text or "").lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def _clean(value) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    return value.strip()


class TodoManager:
    """Captures, stores and serves the to-do list."""

    def __init__(self, path: Optional[Path] = None):
        # Injectable so tests never touch the real ~/.voxa.
        self._path = Path(path) if path else TODOS_FILE
        self._lock = threading.Lock()
        self._notifier: Optional[Callable[[str, dict], None]] = None

    # ── Notifier (app push channel) ─────────────────────────────────────────────

    def set_notifier(self, fn: Callable[[str, dict], None]):
        """Register a callback (event, data) used to notify the app over WebSocket."""
        self._notifier = fn

    def _notify(self, event: str, data: dict):
        if self._notifier:
            try:
                self._notifier(event, data)
            except Exception as e:
                log.warning("Todo notify failed: %s", e)

    # ── Persistence ─────────────────────────────────────────────────────────────

    def _read(self) -> list[dict]:
        if not self._path.exists():
            return []
        try:
            with open(self._path, "r") as f:
                data = json.load(f)
            items = data.get("todos", []) if isinstance(data, dict) else []
            return [t for t in items if isinstance(t, dict)]
        except Exception as e:
            log.warning("Failed to read todos.json: %s", e)
            return []

    def _write(self, todos: list[dict]):
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            # Trim oldest completed first, then oldest overall.
            if len(todos) > MAX_STORED_TODOS:
                done = [t for t in todos if t.get("done")]
                open_items = [t for t in todos if not t.get("done")]
                keep_done = done[: max(0, MAX_STORED_TODOS - len(open_items))]
                todos = (open_items + keep_done)[:MAX_STORED_TODOS]
            with open(self._path, "w") as f:
                json.dump({"todos": todos}, f, indent=2)
            try:
                os.chmod(self._path, 0o600)
            except OSError:
                pass
        except Exception as e:
            log.warning("Failed to write todos.json: %s", e)

    # ── Public API ──────────────────────────────────────────────────────────────

    def list_todos(self, include_done: bool = True, limit: int = 200) -> list[dict]:
        """Open items first (newest first), then completed ones."""
        with self._lock:
            todos = self._read()
        if not include_done:
            todos = [t for t in todos if not t.get("done")]
        todos.sort(key=lambda t: (bool(t.get("done")), -(t.get("created", 0) or 0)))
        return todos[:limit]

    @property
    def open_count(self) -> int:
        return sum(1 for t in self.list_todos() if not t.get("done"))

    def add(
        self,
        task: str,
        owner: str = "",
        due: str = "",
        source: str = "manual",
        session_id: str = "",
        context: str = "",
    ) -> Optional[dict]:
        """Add one to-do. Returns the record, or None if empty/duplicate."""
        task = _clean(task)
        if not task:
            return None

        record = {
            "id": uuid.uuid4().hex[:8],
            "task": task,
            "owner": _clean(owner),
            "due": _clean(due),
            "source": source,
            "session_id": session_id,
            "context": _clean(context),
            "created": time.time(),
            "created_iso": datetime.now().isoformat(timespec="seconds"),
            "done": False,
            "done_iso": "",
            "exported": False,
        }

        with self._lock:
            todos = self._read()
            key = _norm(task)
            # Only de-duplicate against items that are still open — a task that
            # was completed and genuinely comes up again should be re-added.
            for existing in todos:
                if not existing.get("done") and _norm(existing.get("task", "")) == key:
                    return None
            todos.insert(0, record)
            self._write(todos)

        log.info("📝 Todo captured (%s): %s", source, task[:60])
        self._notify("todo_added", {"id": record["id"], "task": task, "source": source})
        return record

    def set_done(self, todo_id: str, done: bool = True) -> bool:
        with self._lock:
            todos = self._read()
            hit = False
            for todo in todos:
                if todo.get("id") == todo_id:
                    todo["done"] = bool(done)
                    todo["done_iso"] = datetime.now().isoformat(timespec="seconds") if done else ""
                    hit = True
                    break
            if hit:
                self._write(todos)
        return hit

    def delete(self, todo_id: str) -> bool:
        with self._lock:
            todos = self._read()
            remaining = [t for t in todos if t.get("id") != todo_id]
            changed = len(remaining) != len(todos)
            if changed:
                self._write(remaining)
        return changed

    def clear_completed(self) -> int:
        with self._lock:
            todos = self._read()
            remaining = [t for t in todos if not t.get("done")]
            removed = len(todos) - len(remaining)
            if removed:
                self._write(remaining)
        return removed

    # ── Ambient capture ─────────────────────────────────────────────────────────

    def analyze_chunk(self, text: str, source: str = "mic", session_id: str = "") -> list[dict]:
        """
        Inspect one transcribed chunk for commitments and store any it finds.
        Returns the records that were newly added (often empty — by design).
        """
        if not text:
            return []

        lower = text.lower()
        if not any(hint in lower for hint in _TASK_HINTS):
            return []

        result = self._extract(text)
        if not result:
            return []

        added: list[dict] = []
        for item in (result.get("todos") or [])[:4]:
            if isinstance(item, str):
                item = {"task": item}
            if not isinstance(item, dict):
                continue
            record = self.add(
                task=item.get("task", ""),
                owner=item.get("owner", ""),
                due=item.get("due", ""),
                source="conversation",
                session_id=session_id,
                context=text[:240],
            )
            if record:
                added.append(record)
        return added

    def ingest_meeting_notes(self, notes: dict, session_id: str = "", platform: str = "") -> list[dict]:
        """
        Fold a finished meeting's structured notes into the same list, so the
        Meetings page and the Todos page never disagree.
        """
        if not isinstance(notes, dict):
            return []

        context = f"From {platform}" if platform else "From a meeting"
        added: list[dict] = []

        for item in notes.get("action_items") or []:
            if isinstance(item, str):
                item = {"task": item}
            if not isinstance(item, dict):
                continue
            record = self.add(
                task=item.get("task", ""),
                owner=item.get("owner", ""),
                due=item.get("due", ""),
                source="meeting",
                session_id=session_id,
                context=context,
            )
            if record:
                added.append(record)

        for task in notes.get("todos") or []:
            record = self.add(
                task=task if isinstance(task, str) else "",
                owner="Me",
                source="meeting",
                session_id=session_id,
                context=context,
            )
            if record:
                added.append(record)

        if added:
            log.info("📝 %d to-do(s) captured from meeting %s", len(added), (session_id or "")[:8])
        return added

    # ── Reminders export ────────────────────────────────────────────────────────

    def export_to_reminders(self, only_open: bool = True) -> dict:
        """Push to-dos into the macOS Reminders app. Skips already-exported ones."""
        from voxa.actions import calendar

        with self._lock:
            todos = self._read()

        pending = [
            t for t in todos
            if not t.get("exported") and (not only_open or not t.get("done"))
        ]
        if not pending:
            return {"success": False, "created": 0, "message": "Nothing new to add."}

        created_ids: list[str] = []
        for todo in pending:
            note_lines = [todo.get("context") or "Captured by Voxa"]
            owner = todo.get("owner", "")
            due = todo.get("due", "")
            if owner and owner.lower() != "me":
                note_lines.append(f"Owner: {owner}")
            if due:
                note_lines.append(f"Due: {due}")
            try:
                if calendar.create_reminder(todo["task"], notes="\n".join(note_lines)).get("success"):
                    created_ids.append(todo["id"])
            except Exception as e:
                log.warning("Reminder create failed for '%s': %s", todo.get("task", "")[:40], e)

        if created_ids:
            with self._lock:
                todos = self._read()
                for todo in todos:
                    if todo.get("id") in created_ids:
                        todo["exported"] = True
                self._write(todos)

        count = len(created_ids)
        message = (
            f"Added {count} reminder{'s' if count != 1 else ''} to your Reminders app."
            if count else "Couldn't add reminders. Open the Reminders app and try again."
        )
        return {"success": count > 0, "created": count, "message": message}

    # ── OpenAI touchpoint (patched in tests) ────────────────────────────────────

    def _extract(self, text: str) -> Optional[dict]:
        """
        The ONLY OpenAI touchpoint. Returns the parsed JSON dict, or None on any
        failure / missing key.
        """
        try:
            from openai import OpenAI
            from voxa.config import config

            api_key = config.OPENAI_API_KEY
            if not api_key:
                return None

            client = OpenAI(api_key=api_key)
            response = client.chat.completions.create(
                model=config.LLM_MODEL_FAST,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": (
                            f"Current date/time: {datetime.now().strftime('%A, %Y-%m-%d %H:%M')}.\n"
                            f"Conversation snippet: {text}"
                        ),
                    },
                ],
                temperature=0.0,
                response_format={"type": "json_object"},
                max_tokens=300,
            )
            content = response.choices[0].message.content or ""
            data = json.loads(content)
            return data if isinstance(data, dict) else None
        except Exception as e:
            log.debug("Todo extraction failed: %s", e)
            return None


# ── Singleton ────────────────────────────────────────────────────────────────────
todo_manager = TodoManager()
