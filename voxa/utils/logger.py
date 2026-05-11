"""
Structured logging for Voxa.
Provides colored console output and file logging.
"""

import logging
import sys
from pathlib import Path
from voxa.config import config


class ColorFormatter(logging.Formatter):
    """Colored log output for terminal readability."""

    COLORS = {
        logging.DEBUG: "\033[36m",     # Cyan
        logging.INFO: "\033[32m",      # Green
        logging.WARNING: "\033[33m",   # Yellow
        logging.ERROR: "\033[31m",     # Red
        logging.CRITICAL: "\033[41m",  # Red background
    }
    RESET = "\033[0m"
    BOLD = "\033[1m"

    def format(self, record):
        color = self.COLORS.get(record.levelno, "")
        record.levelname = f"{color}{self.BOLD}{record.levelname:<8}{self.RESET}"
        record.name = f"\033[34m{record.name}\033[0m"
        return super().format(record)


def get_logger(name: str) -> logging.Logger:
    """Get a configured logger instance."""
    logger = logging.getLogger(f"voxa.{name}")

    if not logger.handlers:
        logger.setLevel(getattr(logging, config.LOG_LEVEL))

        # Console handler with colors
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(ColorFormatter(
            "%(asctime)s %(levelname)s %(name)s │ %(message)s",
            datefmt="%H:%M:%S"
        ))
        logger.addHandler(console)

        # File handler (plain text)
        try:
            file_handler = logging.FileHandler(config.LOG_FILE)
            file_handler.setFormatter(logging.Formatter(
                "%(asctime)s %(levelname)-8s %(name)s │ %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S"
            ))
            logger.addHandler(file_handler)
        except (OSError, PermissionError):
            logger.warning("Could not create log file at %s", config.LOG_FILE)

    return logger
