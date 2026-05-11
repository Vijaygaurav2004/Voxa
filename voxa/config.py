"""
Voxa Configuration Module.
Loads settings from .env and provides typed access to all config values.
"""
from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root
_project_root = Path(__file__).parent.parent
load_dotenv(_project_root / ".env")


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
    SILENCE_THRESHOLD_MS: int = int(os.getenv("SILENCE_THRESHOLD_MS", "700"))
    VAD_AGGRESSIVENESS: int = int(os.getenv("VAD_AGGRESSIVENESS", "2"))
    # Frame duration for VAD (must be 10, 20, or 30 ms)
    VAD_FRAME_DURATION_MS: int = 30
    # Maximum recording duration (seconds) to prevent infinite recordings
    MAX_RECORDING_DURATION: float = 30.0
    # Minimum recording duration (seconds) to avoid noise triggers
    MIN_RECORDING_DURATION: float = 0.5

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
    LOG_FILE: str = os.getenv("LOG_FILE", str(_project_root / "voxa.log"))

    # --- Paths ---
    PROJECT_ROOT: Path = _project_root
    DB_PATH: Path = _project_root / "voxa_history.db"

    # --- Ollama (local LLM fallback) ---
    OLLAMA_ENABLED: bool = os.getenv("OLLAMA_ENABLED", "false").lower() == "true"
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "llama3")
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

    # --- Conversation Mode ---
    CONVERSATION_MODE: bool = os.getenv("CONVERSATION_MODE", "false").lower() == "true"
    FOLLOWUP_WINDOW_SECONDS: int = int(os.getenv("FOLLOWUP_WINDOW_SECONDS", "8"))

    # --- Dashboard ---
    DASHBOARD_ENABLED: bool = os.getenv("DASHBOARD_ENABLED", "true").lower() == "true"
    DASHBOARD_PORT: int = int(os.getenv("DASHBOARD_PORT", "7429"))

    @classmethod
    def validate(cls) -> list[str]:
        """Validate critical configuration. Returns list of errors."""
        errors = []
        if not cls.OPENAI_API_KEY or cls.OPENAI_API_KEY == "sk-your-key-here":
            errors.append("OPENAI_API_KEY is not set. Copy .env.example to .env and add your key.")
        return errors


# Singleton instance
config = Config()
