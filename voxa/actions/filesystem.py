"""
File System Operations Module for Voxa.
Open files, folders, and perform basic file operations.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from voxa.utils.applescript import run_applescript, escape_applescript_string, AppleScriptError
from voxa.utils.logger import get_logger

log = get_logger("filesystem")


def open_file(path: str) -> dict:
    """
    Open a file with its default application using macOS `open` command.

    Args:
        path: Absolute or relative path to the file.
    """
    resolved = _resolve_path(path)
    log.info("📄 Opening file: %s", resolved)

    if not os.path.exists(resolved):
        return {
            "success": False,
            "action": "file_open",
            "path": resolved,
            "message": f"File not found: {resolved}",
        }

    try:
        subprocess.run(["open", resolved], check=True, capture_output=True, timeout=10)
        return {
            "success": True,
            "action": "file_open",
            "path": resolved,
            "message": f"Opened {Path(resolved).name}",
        }
    except subprocess.CalledProcessError as e:
        return {
            "success": False,
            "action": "file_open",
            "path": resolved,
            "error": str(e),
            "message": f"Could not open {resolved}",
        }


def open_folder(path: str) -> dict:
    """
    Open a folder in Finder.

    Args:
        path: Path to the folder.
    """
    resolved = _resolve_path(path)
    log.info("📁 Opening folder: %s", resolved)

    if not os.path.isdir(resolved):
        return {
            "success": False,
            "action": "file_open_folder",
            "path": resolved,
            "message": f"Folder not found: {resolved}",
        }

    try:
        subprocess.run(["open", resolved], check=True, capture_output=True, timeout=10)
        return {
            "success": True,
            "action": "file_open_folder",
            "path": resolved,
            "message": f"Opened folder {Path(resolved).name}",
        }
    except subprocess.CalledProcessError as e:
        return {
            "success": False,
            "action": "file_open_folder",
            "path": resolved,
            "error": str(e),
            "message": f"Could not open folder {resolved}",
        }


def open_file_with_app(path: str, app_name: str) -> dict:
    """Open a file with a specific application."""
    resolved = _resolve_path(path)
    log.info("📄 Opening %s with %s", resolved, app_name)

    try:
        subprocess.run(
            ["open", "-a", app_name, resolved],
            check=True, capture_output=True, timeout=10,
        )
        return {
            "success": True,
            "action": "file_open",
            "path": resolved,
            "app": app_name,
            "message": f"Opened {Path(resolved).name} in {app_name}",
        }
    except subprocess.CalledProcessError as e:
        return {
            "success": False,
            "action": "file_open",
            "path": resolved,
            "error": str(e),
            "message": f"Could not open {resolved} with {app_name}",
        }


def _resolve_path(path: str) -> str:
    """Resolve ~ and relative paths to absolute paths."""
    return str(Path(path).expanduser().resolve())
