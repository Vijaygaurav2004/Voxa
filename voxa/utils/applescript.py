"""
AppleScript execution helper for Voxa.
Provides safe, timeout-protected execution of AppleScript commands via osascript.
"""
from __future__ import annotations

import subprocess
from typing import Optional
from voxa.utils.logger import get_logger

log = get_logger("applescript")


class AppleScriptError(Exception):
    """Raised when an AppleScript execution fails."""
    pass


def run_applescript(script: str, timeout: float = 10.0) -> Optional[str]:
    """
    Execute an AppleScript string via /usr/bin/osascript.

    Args:
        script: AppleScript source code to execute.
        timeout: Maximum execution time in seconds.

    Returns:
        stdout output (stripped) or None if no output.

    Raises:
        AppleScriptError: If the script fails or times out.
    """
    log.debug("Executing AppleScript:\n%s", script.strip()[:200])

    try:
        result = subprocess.run(
            ["/usr/bin/osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        if result.returncode != 0:
            error_msg = result.stderr.strip()
            log.error("AppleScript error (exit %d): %s", result.returncode, error_msg)
            raise AppleScriptError(f"AppleScript failed: {error_msg}")

        output = result.stdout.strip() if result.stdout else None
        if output:
            log.debug("AppleScript output: %s", output[:200])
        return output

    except subprocess.TimeoutExpired:
        log.error("AppleScript timed out after %.1fs", timeout)
        raise AppleScriptError(f"AppleScript timed out after {timeout}s")


def run_applescript_multi(script_lines: list[str], timeout: float = 10.0) -> Optional[str]:
    """
    Execute multi-line AppleScript (joins lines with newlines).

    Args:
        script_lines: List of AppleScript lines.
        timeout: Maximum execution time.

    Returns:
        stdout output or None.
    """
    script = "\n".join(script_lines)
    return run_applescript(script, timeout=timeout)


def escape_applescript_string(value: str) -> str:
    """Escape a string for safe inclusion in AppleScript."""
    return value.replace("\\", "\\\\").replace('"', '\\"')
