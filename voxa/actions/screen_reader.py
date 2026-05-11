"""
Screen Reader Module for Voxa.
Takes screenshots and uses GPT-4o Vision to describe what's on screen.
Also handles the 'take a screenshot' action (save to desktop).
"""
from __future__ import annotations

import base64
import os
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from voxa.config import config
from voxa.utils.logger import get_logger

log = get_logger("screen_reader")


def capture_screen(output_path: str | None = None) -> str | None:
    """Capture a screenshot using macOS screencapture."""
    if output_path is None:
        fd, output_path = tempfile.mkstemp(suffix=".png", prefix="voxa_screen_")
        os.close(fd)
    try:
        result = subprocess.run(
            ["screencapture", "-x", output_path],
            capture_output=True, timeout=10,
        )
        if result.returncode == 0 and os.path.exists(output_path):
            log.info("📸 Screenshot captured: %s", output_path)
            return output_path
        return None
    except Exception as e:
        log.error("Screenshot error: %s", e)
        return None


def describe_screen(question: str = "What is on the screen?") -> dict:
    """Capture the screen and describe it using GPT-4o Vision."""
    log.info("👁️  Describing screen — question: %s", question)
    screenshot_path = capture_screen()
    if not screenshot_path:
        return {"success": False, "action": "screen_read", "message": "Could not capture screenshot"}

    try:
        with open(screenshot_path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode("utf-8")

        from openai import OpenAI
        client = OpenAI(api_key=config.OPENAI_API_KEY)

        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are Voxa, a voice assistant. Describe what you see on the screen "
                        "concisely in 2-3 sentences, suitable for text-to-speech."
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_data}", "detail": "low"}},
                        {"type": "text", "text": question},
                    ],
                },
            ],
            max_tokens=200,
        )

        description = response.choices[0].message.content.strip()
        log.info("👁️  Screen described: %s", description[:100])
        return {"success": True, "action": "screen_read", "description": description, "message": description}

    except Exception as e:
        log.error("Screen description failed: %s", e)
        return {"success": False, "action": "screen_read", "error": str(e), "message": "Could not describe screen"}
    finally:
        try:
            if screenshot_path and "voxa_screen_" in screenshot_path:
                os.unlink(screenshot_path)
        except Exception:
            pass


def take_screenshot(destination: str | None = None, window_only: bool = False) -> dict:
    """Take a screenshot and save it to a file."""
    if destination is None:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        destination = str(Path.home() / "Desktop" / f"Screenshot_{timestamp}.png")

    destination = str(Path(destination).expanduser())
    log.info("📸 Taking screenshot → %s", destination)

    try:
        cmd = ["screencapture", "-x"]
        if window_only:
            cmd.append("-w")
        cmd.append(destination)
        result = subprocess.run(cmd, capture_output=True, timeout=15)
        if result.returncode == 0 and os.path.exists(destination):
            return {"success": True, "action": "screenshot", "path": destination, "message": f"Screenshot saved to Desktop"}
        return {"success": False, "action": "screenshot", "message": "Screenshot failed"}
    except Exception as e:
        log.error("Screenshot failed: %s", e)
        return {"success": False, "action": "screenshot", "error": str(e), "message": f"Could not take screenshot: {e}"}
