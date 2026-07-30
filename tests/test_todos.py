"""Tests for to-do capture from meetings and ordinary conversation."""
from unittest.mock import patch

import pytest

from voxa.memory.todos import TodoManager

# A representative extraction result, as _extract would return it.
_EXTRACTED = {
    "todos": [
        {"task": "Send the deck to Sam", "owner": "Me", "due": "tonight"},
    ]
}

# A chunk that trips the keyword gate ("i'll", "send").
_CHUNK = "yeah I'll send the deck to Sam tonight once I'm done"


@pytest.fixture
def mgr(tmp_path):
    """A fresh (non-singleton) manager writing to a temp file."""
    return TodoManager(path=tmp_path / "todos.json")


class TestKeywordGate:
    def test_idle_chatter_skips_extract(self, mgr):
        with patch.object(mgr, "_extract") as extract:
            added = mgr.analyze_chunk("the weather is really nice today isn't it")
        assert added == []
        extract.assert_not_called()

    def test_commitment_reaches_extract(self, mgr):
        with patch.object(mgr, "_extract", return_value=dict(_EXTRACTED)) as extract:
            added = mgr.analyze_chunk(_CHUNK)
        extract.assert_called_once()
        assert len(added) == 1
        assert added[0]["task"] == "Send the deck to Sam"
        assert added[0]["source"] == "conversation"
        assert added[0]["due"] == "tonight"

    def test_empty_text_is_ignored(self, mgr):
        with patch.object(mgr, "_extract") as extract:
            assert mgr.analyze_chunk("") == []
        extract.assert_not_called()


class TestExtractionHandling:
    def test_empty_todo_list_stores_nothing(self, mgr):
        with patch.object(mgr, "_extract", return_value={"todos": []}):
            assert mgr.analyze_chunk(_CHUNK) == []
        assert mgr.list_todos() == []

    def test_extract_failure_is_survivable(self, mgr):
        with patch.object(mgr, "_extract", return_value=None):
            assert mgr.analyze_chunk(_CHUNK) == []
        assert mgr.list_todos() == []

    def test_plain_string_items_are_tolerated(self, mgr):
        with patch.object(mgr, "_extract", return_value={"todos": ["Book the venue"]}):
            added = mgr.analyze_chunk(_CHUNK)
        assert len(added) == 1
        assert added[0]["task"] == "Book the venue"

    def test_junk_items_are_skipped(self, mgr):
        payload = {"todos": [{"task": ""}, 42, None, {"task": "Real one"}]}
        with patch.object(mgr, "_extract", return_value=payload):
            added = mgr.analyze_chunk(_CHUNK)
        assert [t["task"] for t in added] == ["Real one"]

    def test_caps_at_four_items(self, mgr):
        payload = {"todos": [{"task": f"Task {i}"} for i in range(9)]}
        with patch.object(mgr, "_extract", return_value=payload):
            added = mgr.analyze_chunk(_CHUNK)
        assert len(added) == 4


class TestDeduplication:
    def test_same_task_is_not_added_twice(self, mgr):
        with patch.object(mgr, "_extract", return_value=dict(_EXTRACTED)):
            mgr.analyze_chunk(_CHUNK)
            again = mgr.analyze_chunk(_CHUNK)
        assert again == []
        assert len(mgr.list_todos()) == 1

    def test_dedup_ignores_case_and_punctuation(self, mgr):
        mgr.add("Send the deck to Sam")
        assert mgr.add("send the DECK, to sam!") is None
        assert len(mgr.list_todos()) == 1

    def test_completed_task_can_recur(self, mgr):
        first = mgr.add("Water the plants")
        assert mgr.set_done(first["id"]) is True
        # It came up again in a later conversation — that is a real new task.
        assert mgr.add("Water the plants") is not None
        assert len(mgr.list_todos()) == 2


class TestLifecycle:
    def test_add_complete_delete(self, mgr):
        record = mgr.add("Review the PR", owner="Me", due="Friday")
        assert record["done"] is False
        assert mgr.open_count == 1

        assert mgr.set_done(record["id"]) is True
        assert mgr.list_todos()[0]["done"] is True
        assert mgr.list_todos()[0]["done_iso"]
        assert mgr.open_count == 0

        assert mgr.set_done(record["id"], False) is True
        assert mgr.open_count == 1

        assert mgr.delete(record["id"]) is True
        assert mgr.list_todos() == []

    def test_unknown_ids_report_failure(self, mgr):
        assert mgr.set_done("nope") is False
        assert mgr.delete("nope") is False

    def test_empty_task_is_rejected(self, mgr):
        assert mgr.add("   ") is None
        assert mgr.list_todos() == []

    def test_clear_completed_keeps_open_items(self, mgr):
        keep = mgr.add("Still open")
        drop = mgr.add("Already done")
        mgr.set_done(drop["id"])
        assert mgr.clear_completed() == 1
        assert [t["id"] for t in mgr.list_todos()] == [keep["id"]]

    def test_open_items_sort_before_done(self, mgr):
        old = mgr.add("Older open")
        done = mgr.add("Done one")
        mgr.set_done(done["id"])
        newer = mgr.add("Newer open")
        order = [t["task"] for t in mgr.list_todos()]
        assert order.index("Newer open") < order.index("Older open") < order.index("Done one")

    def test_include_done_false_filters(self, mgr):
        a = mgr.add("Open one")
        b = mgr.add("Closed one")
        mgr.set_done(b["id"])
        assert [t["task"] for t in mgr.list_todos(include_done=False)] == ["Open one"]
        assert a["id"]

    def test_survives_a_reload_from_disk(self, tmp_path):
        path = tmp_path / "todos.json"
        first = TodoManager(path=path)
        first.add("Persist me")
        assert [t["task"] for t in TodoManager(path=path).list_todos()] == ["Persist me"]

    def test_corrupt_file_does_not_raise(self, tmp_path):
        path = tmp_path / "todos.json"
        path.write_text("{ not json")
        mgr = TodoManager(path=path)
        assert mgr.list_todos() == []
        assert mgr.add("Recovered") is not None


class TestMeetingIngest:
    def test_action_items_and_todos_both_land(self, mgr):
        notes = {
            "action_items": [{"task": "Book the venue", "owner": "Sam", "due": "Friday"}],
            "todos": ["Write the summary"],
        }
        added = mgr.ingest_meeting_notes(notes, session_id="abc123", platform="Zoom")
        tasks = {t["task"] for t in added}
        assert tasks == {"Book the venue", "Write the summary"}
        assert all(t["source"] == "meeting" for t in added)
        assert all(t["session_id"] == "abc123" for t in added)
        assert all("Zoom" in t["context"] for t in added)

    def test_owner_is_preserved_for_action_items(self, mgr):
        notes = {"action_items": [{"task": "Book the venue", "owner": "Sam"}]}
        added = mgr.ingest_meeting_notes(notes)
        assert added[0]["owner"] == "Sam"

    def test_personal_todos_are_owned_by_me(self, mgr):
        added = mgr.ingest_meeting_notes({"todos": ["Write the summary"]})
        assert added[0]["owner"] == "Me"

    def test_duplicate_between_action_items_and_todos_lands_once(self, mgr):
        notes = {
            "action_items": [{"task": "Send the notes", "owner": "Me"}],
            "todos": ["Send the notes"],
        }
        added = mgr.ingest_meeting_notes(notes)
        assert len(added) == 1

    def test_empty_and_malformed_notes_are_safe(self, mgr):
        assert mgr.ingest_meeting_notes({}) == []
        assert mgr.ingest_meeting_notes(None) == []
        assert mgr.ingest_meeting_notes({"action_items": None, "todos": None}) == []


class TestNotifier:
    def test_add_pushes_an_event(self, mgr):
        events = []
        mgr.set_notifier(lambda e, d: events.append((e, d)))
        mgr.add("Ping the team")
        assert len(events) == 1
        assert events[0][0] == "todo_added"
        assert events[0][1]["task"] == "Ping the team"

    def test_notifier_failure_does_not_break_capture(self, mgr):
        def boom(_e, _d):
            raise RuntimeError("nope")
        mgr.set_notifier(boom)
        assert mgr.add("Still stored") is not None
        assert len(mgr.list_todos()) == 1


class TestRemindersExport:
    def test_exports_open_items_and_marks_them(self, mgr):
        mgr.add("Book the venue")
        with patch("voxa.actions.calendar.create_reminder", return_value={"success": True}) as create:
            result = mgr.export_to_reminders()
        assert result["success"] is True
        assert result["created"] == 1
        create.assert_called_once()
        assert mgr.list_todos()[0]["exported"] is True

    def test_already_exported_items_are_skipped(self, mgr):
        mgr.add("Book the venue")
        with patch("voxa.actions.calendar.create_reminder", return_value={"success": True}):
            mgr.export_to_reminders()
            second = mgr.export_to_reminders()
        assert second["created"] == 0
        assert second["success"] is False

    def test_completed_items_are_not_exported(self, mgr):
        done = mgr.add("Already handled")
        mgr.set_done(done["id"])
        with patch("voxa.actions.calendar.create_reminder", return_value={"success": True}) as create:
            result = mgr.export_to_reminders()
        create.assert_not_called()
        assert result["created"] == 0

    def test_reminder_failure_leaves_item_unexported(self, mgr):
        mgr.add("Book the venue")
        with patch("voxa.actions.calendar.create_reminder", return_value={"success": False}):
            result = mgr.export_to_reminders()
        assert result["created"] == 0
        assert mgr.list_todos()[0]["exported"] is False

    def test_reminder_exception_is_survivable(self, mgr):
        mgr.add("Book the venue")
        with patch("voxa.actions.calendar.create_reminder", side_effect=RuntimeError("boom")):
            result = mgr.export_to_reminders()
        assert result["created"] == 0
        assert mgr.list_todos()[0]["exported"] is False
