"""
Tests for the Action execution modules.
Tests AppleScript generation, app control, browser control, and safety checks.
"""

import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from voxa.utils.applescript import escape_applescript_string
from voxa.actions.shell import _check_dangerous


# ─── AppleScript Helpers ─────────────────────────────────────────────────────────

class TestAppleScriptEscape:
    def test_plain_text(self):
        assert escape_applescript_string("hello") == "hello"

    def test_quotes(self):
        assert escape_applescript_string('say "hi"') == 'say \\"hi\\"'

    def test_backslash(self):
        assert escape_applescript_string("path\\to") == "path\\\\to"

    def test_mixed(self):
        result = escape_applescript_string('file "test\\path"')
        assert result == 'file \\"test\\\\path\\"'


# ─── Safety Checks ──────────────────────────────────────────────────────────────

class TestDangerousCommands:
    def test_safe_command(self):
        assert _check_dangerous("ls -la") is None

    def test_safe_echo(self):
        assert _check_dangerous("echo hello") is None

    def test_dangerous_rm(self):
        result = _check_dangerous("rm -rf /tmp/test")
        assert result is not None
        assert "rm" in result.lower()

    def test_dangerous_sudo(self):
        result = _check_dangerous("sudo apt-get install something")
        assert result is not None

    def test_dangerous_kill(self):
        result = _check_dangerous("kill -9 1234")
        assert result is not None

    def test_dangerous_in_pipe(self):
        result = _check_dangerous("echo test | rm -rf /")
        assert result is not None

    def test_fork_bomb(self):
        result = _check_dangerous(":(){ :|:& };:")
        assert result is not None

    def test_dd_command(self):
        result = _check_dangerous("dd if=/dev/zero of=/dev/sda")
        assert result is not None

    def test_safe_grep(self):
        assert _check_dangerous("grep -r 'pattern' ./src") is None

    def test_safe_python(self):
        assert _check_dangerous("python3 script.py") is None
