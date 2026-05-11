"""
Shell Command Execution Module for Voxa.
Runs shell commands with safety checks and output capture.
"""
from __future__ import annotations

import subprocess
import shlex
from voxa.config import config
from voxa.utils.logger import get_logger

log = get_logger("shell")


class DangerousCommandError(Exception):
    """Raised when a command is flagged as dangerous and confirmation is required."""
    pass


def execute_command(command: str, timeout: float = 30.0, confirm_dangerous: bool = True) -> dict:
    """
    Execute a shell command and capture output.

    Args:
        command: Shell command string to execute.
        timeout: Maximum execution time in seconds.
        confirm_dangerous: If True, raise error for dangerous commands.

    Returns:
        Result dict with stdout, stderr, exit code.
    """
    log.info("💻 Executing shell command: %s", command[:100])

    # Safety check
    if confirm_dangerous and config.CONFIRM_DANGEROUS_COMMANDS:
        danger = _check_dangerous(command)
        if danger:
            log.warning("⚠️  Dangerous command detected: %s — %s", danger, command)
            return {
                "success": False,
                "action": "shell_command",
                "command": command,
                "dangerous": True,
                "requires_confirmation": True,
                "danger_reason": danger,
                "message": f"This command needs your confirmation: '{command[:60]}'. Say 'confirm' to run it or 'cancel' to abort.",
            }

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=None,  # Use current directory
        )

        success = result.returncode == 0
        output = result.stdout.strip() if result.stdout else ""
        error = result.stderr.strip() if result.stderr else ""

        if success:
            log.info("✅ Command succeeded (exit 0)")
            if output:
                log.debug("Output: %s", output[:200])
        else:
            log.warning("Command failed (exit %d): %s", result.returncode, error[:200])

        return {
            "success": success,
            "action": "shell_command",
            "command": command,
            "exit_code": result.returncode,
            "stdout": output[:1000],  # Cap output
            "stderr": error[:500],
            "message": f"Command {'succeeded' if success else 'failed'}: {command[:50]}",
        }

    except subprocess.TimeoutExpired:
        log.error("Command timed out after %.1fs: %s", timeout, command)
        return {
            "success": False,
            "action": "shell_command",
            "command": command,
            "error": f"Timed out after {timeout}s",
            "message": f"Command timed out: {command[:50]}",
        }
    except Exception as e:
        log.error("Command error: %s", e)
        return {
            "success": False,
            "action": "shell_command",
            "command": command,
            "error": str(e),
            "message": f"Command failed: {str(e)}",
        }


def _check_dangerous(command: str) -> str | None:
    """
    Check if a command contains dangerous patterns.
    Returns a reason string if dangerous, None if safe.
    """
    lower = command.lower().strip()

    # Check against configured dangerous commands
    for dangerous in config.DANGEROUS_COMMANDS:
        dangerous = dangerous.strip().lower()
        if not dangerous:
            continue
        # Check if the dangerous command appears as a word/command boundary
        if lower.startswith(dangerous + " ") or lower == dangerous:
            return f"Contains dangerous command: {dangerous}"
        # Also check in pipes
        parts = lower.split("|")
        for part in parts:
            part = part.strip()
            if part.startswith(dangerous + " ") or part == dangerous:
                return f"Contains dangerous command in pipe: {dangerous}"

    # Additional heuristic checks
    danger_patterns = [
        ("rm -rf /", "Recursive deletion from root"),
        ("rm -rf ~", "Recursive deletion of home directory"),
        ("> /dev/", "Writing to device file"),
        (":(){ :", "Fork bomb detected"),
        ("mkfs", "Filesystem format command"),
        ("dd if=", "Raw disk operation"),
    ]
    for pattern, reason in danger_patterns:
        if pattern in lower:
            return reason

    return None
