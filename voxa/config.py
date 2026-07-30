"""
Voxa Configuration Module.
Loads settings from .env and provides typed access to all config values.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load configuration from .env files. Search order (first match per key wins,
# and real environment variables always take precedence over both):
#   1. ~/.voxa/.env      — canonical location for the distributed/standalone app
#   2. <project root>/.env — developer checkout
# When frozen by PyInstaller there is no project root, so ~/.voxa/.env is what
# the shipped app relies on (written by the first-run key prompt).
if getattr(sys, "frozen", False):
    # In a PyInstaller bundle __file__ points inside the temp extraction dir.
    _project_root = Path(sys.executable).resolve().parent
else:
    _project_root = Path(__file__).parent.parent

_user_env = Path.home() / ".voxa" / ".env"
load_dotenv(_user_env)                 # user/distributed config first
load_dotenv(_project_root / ".env")    # then dev checkout (won't override existing keys)

# Writable base dir for logs/DB. The app bundle is read-only, so when frozen
# (or when the project root isn't writable) fall back to ~/.voxa.
def _writable_base() -> Path:
    if getattr(sys, "frozen", False):
        base = Path.home() / ".voxa"
    else:
        base = _project_root
    try:
        base.mkdir(parents=True, exist_ok=True)
        test = base / ".write_test"
        test.touch()
        test.unlink()
        return base
    except Exception:
        fallback = Path.home() / ".voxa"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback

_data_dir = _writable_base()


class Config:
    """Centralized configuration for Voxa."""

    # --- OpenAI ---
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    WHISPER_MODEL: str = os.getenv("WHISPER_MODEL", "whisper-1")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "gpt-4o")
    LLM_MODEL_FAST: str = os.getenv("LLM_MODEL_FAST", "gpt-4o-mini")

    # --- Audio ---
    SAMPLE_RATE: int = int(os.getenv("SAMPLE_RATE", "16000"))
    CHANNELS: int = 1
    DTYPE: str = "int16"
    SILENCE_THRESHOLD_MS: int = int(os.getenv("SILENCE_THRESHOLD_MS", "500"))
    VAD_AGGRESSIVENESS: int = int(os.getenv("VAD_AGGRESSIVENESS", "3"))
    # Frame duration for VAD (must be 10, 20, or 30 ms)
    VAD_FRAME_DURATION_MS: int = 30
    # Maximum recording duration (seconds) to prevent infinite recordings
    MAX_RECORDING_DURATION: float = 15.0
    # Minimum recording duration (seconds) to avoid noise triggers
    MIN_RECORDING_DURATION: float = 0.3

    # --- Activation ---
    WAKE_WORD: str = os.getenv("WAKE_WORD", "hey voxa")
    HOTKEY_COMBO: str = os.getenv("HOTKEY_COMBO", "cmd+shift+v")

    # --- Browser ---
    DEFAULT_BROWSER: str = os.getenv("DEFAULT_BROWSER", "Google Chrome")

    # --- Safety ---
    CONFIRM_DANGEROUS_COMMANDS: bool = os.getenv("CONFIRM_DANGEROUS_COMMANDS", "true").lower() == "true"
    DANGEROUS_COMMANDS: list[str] = os.getenv(
        "DANGEROUS_COMMANDS",
        "rm,kill,sudo,chmod,chown,mkfs,dd,shutdown,reboot"
    ).split(",")

    # --- Logging ---
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_FILE: str = os.getenv("LOG_FILE", str(_data_dir / "voxa.log"))

    # --- Paths ---
    PROJECT_ROOT: Path = _project_root
    DB_PATH: Path = _data_dir / "voxa_history.db"

    # --- Ollama (local LLM fallback) ---
    OLLAMA_ENABLED: bool = os.getenv("OLLAMA_ENABLED", "false").lower() == "true"
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "llama3")
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

    # --- Conversation Mode ---
    CONVERSATION_MODE: bool = os.getenv("CONVERSATION_MODE", "false").lower() == "true"
    FOLLOWUP_WINDOW_SECONDS: int = int(os.getenv("FOLLOWUP_WINDOW_SECONDS", "8"))

    # --- API Server (Swift ↔ Python bridge) ---
    API_SERVER_HOST: str = os.getenv("API_SERVER_HOST", "127.0.0.1")
    API_SERVER_PORT: int = int(os.getenv("API_SERVER_PORT", "7430"))

    # --- Dashboard ---
    DASHBOARD_ENABLED: bool = os.getenv("DASHBOARD_ENABLED", "true").lower() == "true"
    DASHBOARD_PORT: int = int(os.getenv("DASHBOARD_PORT", "7429"))

    # --- Memory (Always-On Ambient Listening) ---
    MEMORY_ENABLED: bool = os.getenv("MEMORY_ENABLED", "false").lower() == "true"
    MEMORY_CHUNK_DURATION: int = int(os.getenv("MEMORY_CHUNK_DURATION", "30"))
    MEMORY_RETENTION_DAYS: int = int(os.getenv("MEMORY_RETENTION_DAYS", "30"))
    MEMORY_AUTO_FILTER: bool = os.getenv("MEMORY_AUTO_FILTER", "true").lower() == "true"
    MEMORY_SYSTEM_AUDIO: bool = os.getenv("MEMORY_SYSTEM_AUDIO", "false").lower() == "true"
    MEMORY_STORAGE_PATH: Path = Path(os.getenv("MEMORY_STORAGE_PATH", str(Path.home() / ".voxa" / "memory")))
    # Keep the audio clip for each meaningful memory chunk on disk (for playback).
    MEMORY_KEEP_AUDIO: bool = os.getenv("MEMORY_KEEP_AUDIO", "true").lower() == "true"
    # RMS threshold below which an incoming chunk is treated as silence and
    # dropped before it costs a Whisper call (0..32767 on 16-bit PCM).
    MEMORY_SILENCE_RMS: float = float(os.getenv("MEMORY_SILENCE_RMS", "180"))

    # --- Integrations (Google / GitHub OAuth) ---
    GOOGLE_CLIENT_ID: str = os.getenv("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
    GITHUB_CLIENT_ID: str = os.getenv("GITHUB_CLIENT_ID", "")
    GITHUB_CLIENT_SECRET: str = os.getenv("GITHUB_CLIENT_SECRET", "")

    # --- Meeting Detection (Granola-style auto-capture) ---
    MEETING_AUTO_DETECT: bool = os.getenv("MEETING_AUTO_DETECT", "false").lower() == "true"
    MEETING_POLL_INTERVAL: float = float(os.getenv("MEETING_POLL_INTERVAL", "10"))
    # Require a live microphone to start a browser meeting (filters stale tabs).
    MEETING_REQUIRE_MIC: bool = os.getenv("MEETING_REQUIRE_MIC", "true").lower() == "true"
    # If true, record detected meetings immediately. If false (default), prompt
    # the user ("Record this meeting?") and only capture when they say yes.
    MEETING_AUTO_RECORD: bool = os.getenv("MEETING_AUTO_RECORD", "false").lower() == "true"
    # Capture meeting audio in the host app (Swift) and stream it to the backend,
    # instead of the Python mic. The app reliably holds macOS mic permission, so
    # this is what makes meeting notes actually fill in. Default on.
    MEETING_EXTERNAL_AUDIO: bool = os.getenv("MEETING_EXTERNAL_AUDIO", "true").lower() == "true"
    # Also capture system audio (the other participants) via ScreenCaptureKit, so
    # meeting notes have BOTH sides. Needs Screen Recording permission. Default on.
    MEETING_CAPTURE_SYSTEM_AUDIO: bool = os.getenv("MEETING_CAPTURE_SYSTEM_AUDIO", "true").lower() == "true"
    # Proactively detect scheduling agreements in a conversation ("let's meet
    # Friday at 3") and offer an "Add to calendar?" suggestion. Default on.
    MEETING_SUGGESTIONS: bool = os.getenv("MEETING_SUGGESTIONS", "true").lower() == "true"

    # --- To-dos ---
    # Pull commitments ("I'll send the deck tonight") out of meetings AND ordinary
    # conversation into a running to-do list. A keyword gate runs first, so only
    # chunks that sound like a commitment ever cost an LLM call. Default on.
    TODO_AUTO_CAPTURE: bool = os.getenv("TODO_AUTO_CAPTURE", "true").lower() == "true"

    @classmethod
    def validate(cls) -> list[str]:
        """Validate critical configuration. Returns list of errors."""
        errors = []
        if not cls.OPENAI_API_KEY or cls.OPENAI_API_KEY == "sk-your-key-here":
            errors.append("OPENAI_API_KEY is not set. Copy .env.example to .env and add your key.")
        return errors


def persist_env_setting(key: str, value) -> bool:
    """Upsert ``KEY=value`` into ~/.voxa/.env (the user/distributed config file).

    Creates the file/dir if missing, replaces an existing ``KEY=`` line, or
    appends a new one. Written with mode 0o600. Returns True on success, False
    on any failure (defensive — never raises).
    """
    try:
        path = _user_env
        path.parent.mkdir(parents=True, exist_ok=True)
        new_line = f"{key}={value}"
        lines: list[str] = []
        if path.exists():
            lines = path.read_text().splitlines()
        replaced = False
        for i, existing in enumerate(lines):
            stripped = existing.lstrip()
            if not stripped.startswith("#") and stripped.startswith(f"{key}="):
                lines[i] = new_line
                replaced = True
                break
        if not replaced:
            lines.append(new_line)
        path.write_text("\n".join(lines) + "\n")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return True
    except Exception:
        return False


# Singleton instance
config = Config()
