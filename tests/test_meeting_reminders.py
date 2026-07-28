"""
Tests for exporting meeting action items / to-dos to macOS Reminders.

Hermetic: AppleScript is never run (the ``run_applescript`` seam is patched),
and meetings.json is redirected to pytest's tmp_path.
"""
import json
from unittest.mock import patch

import pytest

from voxa.actions import calendar
from voxa.memory import meeting_manager as mm_module
from voxa.memory.meeting_manager import MeetingManager


# ── 1. calendar.create_reminder primitive ─────────────────────────────────────

class TestCreateReminder:
    def test_builds_script_and_succeeds(self):
        with patch("voxa.actions.calendar.run_applescript", return_value="") as run:
            res = calendar.create_reminder("Send the email", notes="From Zoom · Jul 22")
        assert res["success"] is True
        script = run.call_args[0][0]
        assert 'name:"Send the email"' in script
        assert 'body:"From Zoom · Jul 22"' in script
        assert 'tell application "Reminders"' in script

    def test_empty_title_is_rejected(self):
        with patch("voxa.actions.calendar.run_applescript") as run:
            res = calendar.create_reminder("   ")
        assert res["success"] is False
        run.assert_not_called()

    def test_escapes_quotes(self):
        with patch("voxa.actions.calendar.run_applescript", return_value="") as run:
            calendar.create_reminder('Fix "the" bug', notes='a\\b')
        script = run.call_args[0][0]
        assert '\\"the\\"' in script
        assert 'a\\\\b' in script

    def test_applescript_error_is_handled(self):
        with patch("voxa.actions.calendar.run_applescript",
                   side_effect=calendar.AppleScriptError("nope")):
            res = calendar.create_reminder("do thing")
        assert res["success"] is False
        assert "Reminders app" in res["message"]

    def test_named_list_targeted(self):
        with patch("voxa.actions.calendar.run_applescript", return_value="") as run:
            calendar.create_reminder("task", list_name="Voxa")
        assert 'at list "Voxa"' in run.call_args[0][0]


# ── 2. MeetingManager.export_to_reminders ─────────────────────────────────────

@pytest.fixture
def redirect_meetings(tmp_path):
    mfile = tmp_path / "meetings.json"
    with patch.object(mm_module, "MEETINGS_DIR", tmp_path), \
         patch.object(mm_module, "MEETINGS_FILE", mfile):
        yield mfile


RECORD = {
    "session_id": "sess1",
    "platform": "Zoom",
    "started_iso": "2026-07-22T15:00:00",
    "action_items": [
        {"task": "Send the launch email", "owner": "Me", "due": "Thursday"},
        {"task": "Prepare release notes", "owner": "Aman", "due": ""},
    ],
    "todos": [
        "Draft the launch email",       # unique to-do
        "send the launch email",        # dup of an action item (case-insensitive)
    ],
    "follow_ups": [{"task": "Confirm pricing", "person": "Sam"}],
}


class TestExportToReminders:
    def _mgr(self, mfile, records):
        mfile.write_text(json.dumps({"meetings": records}))
        return MeetingManager()

    def test_creates_reminders_for_actions_and_todos(self, redirect_meetings):
        mm = self._mgr(redirect_meetings, [RECORD])
        with patch("voxa.actions.calendar.create_reminder",
                   return_value={"success": True}) as cr:
            res = mm.export_to_reminders("sess1")

        # 2 action items + 1 unique to-do = 3 (the dup to-do is skipped).
        assert res["success"] is True
        assert res["created"] == 3
        titles = [c.args[0] for c in cr.call_args_list]
        assert "Send the launch email" in titles
        assert "Prepare release notes" in titles
        assert "Draft the launch email" in titles
        assert titles.count("Send the launch email") == 1  # not duplicated by the to-do

    def test_owner_and_due_go_into_notes(self, redirect_meetings):
        mm = self._mgr(redirect_meetings, [RECORD])
        with patch("voxa.actions.calendar.create_reminder",
                   return_value={"success": True}) as cr:
            mm.export_to_reminders("sess1")
        notes_by_title = {c.args[0]: c.kwargs.get("notes", "") for c in cr.call_args_list}
        # Non-"Me" owner + due surface in notes; a "Me" owner is omitted.
        assert "Owner: Aman" in notes_by_title["Prepare release notes"]
        assert "Due: Thursday" in notes_by_title["Send the launch email"]
        assert "Owner: Me" not in notes_by_title["Send the launch email"]
        assert "From Zoom" in notes_by_title["Send the launch email"]

    def test_sets_exported_flag_on_record(self, redirect_meetings):
        mfile = redirect_meetings
        mm = self._mgr(mfile, [RECORD])
        with patch("voxa.actions.calendar.create_reminder", return_value={"success": True}):
            mm.export_to_reminders("sess1")
        saved = json.loads(mfile.read_text())["meetings"][0]
        assert saved["reminders_exported"] is True

    def test_no_tasks_returns_failure(self, redirect_meetings):
        rec = {"session_id": "s2", "platform": "Meet", "action_items": [], "todos": []}
        mm = self._mgr(redirect_meetings, [rec])
        with patch("voxa.actions.calendar.create_reminder") as cr:
            res = mm.export_to_reminders("s2")
        assert res["success"] is False
        assert res["created"] == 0
        cr.assert_not_called()

    def test_unknown_session(self, redirect_meetings):
        mm = self._mgr(redirect_meetings, [RECORD])
        assert mm.export_to_reminders("nope")["success"] is False

    def test_blank_session(self, redirect_meetings):
        assert MeetingManager().export_to_reminders("")["success"] is False

    def test_partial_failure_counts_only_successes(self, redirect_meetings):
        mm = self._mgr(redirect_meetings, [RECORD])
        results = [{"success": True}, {"success": False}, {"success": True}]
        with patch("voxa.actions.calendar.create_reminder", side_effect=results):
            res = mm.export_to_reminders("sess1")
        assert res["created"] == 2
        assert res["success"] is True
