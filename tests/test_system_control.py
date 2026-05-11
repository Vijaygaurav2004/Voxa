"""
Tests for system_control volume/brightness/dark-mode helpers.
All AppleScript calls are mocked — no macOS interaction.
"""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

from voxa.actions import system_control
from voxa.utils.applescript import AppleScriptError


# ─── set_volume ───────────────────────────────────────────────────────────────

class TestSetVolume:

    def test_mute_success(self):
        with patch("voxa.actions.system_control.run_applescript", return_value=None):
            result = system_control.set_volume(mute=True)
        assert result["success"] is True
        assert "muted" in result["message"].lower()

    def test_set_level_clamped_max(self):
        with patch("voxa.actions.system_control.run_applescript") as m:
            result = system_control.set_volume(level=150)
        assert result["success"] is True
        # Verify clamped to 100
        call_args = m.call_args[0][0]
        assert "100" in call_args

    def test_set_level_clamped_min(self):
        with patch("voxa.actions.system_control.run_applescript") as m:
            result = system_control.set_volume(level=-10)
        assert result["success"] is True
        call_args = m.call_args[0][0]
        assert "0" in call_args

    def test_set_level_50(self):
        with patch("voxa.actions.system_control.run_applescript") as m:
            result = system_control.set_volume(level=50)
        assert result["success"] is True
        assert "50" in result["message"]

    def test_direction_up(self):
        with patch("voxa.actions.system_control.run_applescript", return_value="40"):
            result = system_control.set_volume(direction="up")
        assert result["success"] is True
        assert "increased" in result["message"].lower()

    def test_direction_down(self):
        with patch("voxa.actions.system_control.run_applescript", return_value="40"):
            result = system_control.set_volume(direction="down")
        assert result["success"] is True
        assert "decreased" in result["message"].lower()

    def test_direction_up_caps_at_100(self):
        with patch("voxa.actions.system_control.run_applescript", return_value="95") as m:
            result = system_control.set_volume(direction="up")
        assert result["success"] is True
        # New volume should not exceed 100
        call_args = m.call_args_list[-1][0][0]
        assert "100" in call_args

    def test_direction_down_floors_at_0(self):
        with patch("voxa.actions.system_control.run_applescript", return_value="5") as m:
            result = system_control.set_volume(direction="down")
        assert result["success"] is True
        call_args = m.call_args_list[-1][0][0]
        assert "0" in call_args

    def test_no_args_returns_failure(self):
        result = system_control.set_volume()
        assert result["success"] is False

    def test_applescript_error_returns_failure(self):
        with patch("voxa.actions.system_control.run_applescript",
                   side_effect=AppleScriptError("oops")):
            result = system_control.set_volume(level=50)
        assert result["success"] is False

    def test_invalid_current_volume_defaults_to_50(self):
        with patch("voxa.actions.system_control.run_applescript", return_value="not_a_number"):
            result = system_control.set_volume(direction="up")
        assert result["success"] is True


# ─── toggle_dark_mode ─────────────────────────────────────────────────────────

class TestToggleDarkMode:

    def test_enable_dark_mode(self):
        with patch("voxa.actions.system_control.run_applescript", return_value=None):
            result = system_control.toggle_dark_mode(enable=True)
        assert result["success"] is True
        assert "enabled" in result["message"].lower()

    def test_disable_dark_mode(self):
        with patch("voxa.actions.system_control.run_applescript", return_value=None):
            result = system_control.toggle_dark_mode(enable=False)
        assert result["success"] is True
        assert "disabled" in result["message"].lower()

    def test_toggle_dark_mode_on(self):
        with patch("voxa.actions.system_control.run_applescript", return_value="true"):
            result = system_control.toggle_dark_mode(enable=None)
        assert result["success"] is True
        assert "enabled" in result["message"].lower()

    def test_toggle_dark_mode_off(self):
        with patch("voxa.actions.system_control.run_applescript", return_value="false"):
            result = system_control.toggle_dark_mode(enable=None)
        assert result["success"] is True
        assert "disabled" in result["message"].lower()

    def test_applescript_error_returns_failure(self):
        with patch("voxa.actions.system_control.run_applescript",
                   side_effect=AppleScriptError("perm denied")):
            result = system_control.toggle_dark_mode(enable=True)
        assert result["success"] is False


# ─── toggle_dnd ───────────────────────────────────────────────────────────────

class TestToggleDnd:

    def test_enable_dnd(self):
        with patch("voxa.actions.system_control.run_applescript", return_value=None):
            result = system_control.toggle_dnd(enable=True)
        assert result["success"] is True
        assert "enabled" in result["message"].lower()

    def test_disable_dnd(self):
        with patch("voxa.actions.system_control.run_applescript", return_value=None):
            result = system_control.toggle_dnd(enable=False)
        assert result["success"] is True
        assert "disabled" in result["message"].lower()

    def test_toggle_dnd(self):
        with patch("voxa.actions.system_control.run_applescript", return_value=None):
            result = system_control.toggle_dnd(enable=None)
        assert result["success"] is True
        assert "toggled" in result["message"].lower()

    def test_applescript_error_returns_failure(self):
        with patch("voxa.actions.system_control.run_applescript",
                   side_effect=AppleScriptError("error")):
            result = system_control.toggle_dnd(enable=True)
        assert result["success"] is False


# ─── get_battery_status ───────────────────────────────────────────────────────

class TestGetBatteryStatus:

    def test_returns_level_and_charging(self):
        mock_run = MagicMock()
        mock_run.return_value.stdout = (
            "Now drawing from 'AC Power'\n"
            "-InternalBattery-0 (id=1234) 87%; charging"
        )
        mock_run.return_value.returncode = 0
        with patch("subprocess.run", return_value=mock_run.return_value):
            result = system_control.get_battery_status()
        assert result["success"] is True
        assert result["level"] == 87
        assert result["charging"] is True

    def test_returns_discharging(self):
        mock_result = MagicMock()
        mock_result.stdout = "-InternalBattery-0 62%; discharging"
        with patch("subprocess.run", return_value=mock_result):
            result = system_control.get_battery_status()
        assert result["success"] is True
        assert result["charging"] is False

    def test_subprocess_error_returns_failure(self):
        with patch("subprocess.run", side_effect=Exception("pmset not found")):
            result = system_control.get_battery_status()
        assert result["success"] is False
