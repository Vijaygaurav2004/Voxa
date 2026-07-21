"""
Voxa Web Dashboard — Local FastAPI server.
Provides a browser UI at http://localhost:7429 for:
  - Viewing command history
  - Usage stats
  - Managing custom skills
  - Configuring settings
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from voxa.utils.logger import get_logger

log = get_logger("dashboard")

DASHBOARD_PORT = int(os.getenv("DASHBOARD_PORT", "7429"))
TEMPLATES_DIR = Path(__file__).parent / "templates"


def create_app():
    """Create and return the FastAPI application."""
    try:
        from fastapi import FastAPI
        from fastapi.responses import HTMLResponse, JSONResponse
        from fastapi.middleware.cors import CORSMiddleware
    except ImportError:
        log.warning("FastAPI not installed — dashboard disabled. Run: pip install fastapi uvicorn")
        return None

    from voxa.config import config
    from voxa.intelligence.context import CommandHistory
    from voxa.actions.timers import list_timers, get_active_timer_count

    app = FastAPI(title="Voxa Dashboard", version="1.0.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    history = CommandHistory()

    @app.get("/", response_class=HTMLResponse)
    async def dashboard_home():
        """Serve the dashboard HTML."""
        html_path = TEMPLATES_DIR / "index.html"
        if html_path.exists():
            return HTMLResponse(content=html_path.read_text())
        return HTMLResponse(content="<h1>Voxa Dashboard</h1><p>Template not found.</p>")

    @app.get("/api/stats")
    async def get_stats():
        """Get usage statistics."""
        stats = history.get_stats()
        timer_count = get_active_timer_count()
        return JSONResponse({**stats, "active_timers": timer_count})

    @app.get("/api/history")
    async def get_history(limit: int = 50):
        """Get recent command history."""
        recent = history.get_recent(limit)
        return JSONResponse({"history": recent, "count": len(recent)})

    @app.get("/api/timers")
    async def get_timers():
        """Get active timers."""
        return JSONResponse(list_timers())

    @app.get("/api/skills")
    async def get_skills():
        """Get loaded custom skills."""
        try:
            from voxa.skills.custom_skills import skill_manager
            return JSONResponse({
                "skills": skill_manager.skills,
                "count": skill_manager.skill_count,
                "skills_path": str(skill_manager.skills_path),
            })
        except Exception as e:
            return JSONResponse({"error": str(e), "skills": []})

    @app.post("/api/skills/reload")
    async def reload_skills():
        """Reload skills from disk."""
        try:
            from voxa.skills.custom_skills import skill_manager
            skill_manager.reload()
            return JSONResponse({"success": True, "count": skill_manager.skill_count})
        except Exception as e:
            return JSONResponse({"success": False, "error": str(e)})

    # ── Modes ──────────────────────────────────────────────────────────────

    @app.get("/api/modes")
    async def get_modes():
        """List all user-defined custom modes."""
        try:
            from voxa.skills.modes import mode_manager
            return JSONResponse({
                "modes": mode_manager.list_modes(),
                "count": mode_manager.mode_count,
            })
        except Exception as e:
            return JSONResponse({"modes": [], "count": 0, "error": str(e)})

    # Use a flexible approach for the dashboard's mode endpoints
    from fastapi import Request

    @app.post("/api/modes")
    async def create_mode_endpoint(request: Request):
        """Create a new custom mode."""
        from voxa.skills.modes import mode_manager
        body = await request.json()
        result = mode_manager.create_mode(
            name=body.get("name", ""),
            instructions=body.get("instructions", []),
            description=body.get("description", ""),
        )
        status = 200 if result["success"] else 400
        return JSONResponse(result, status_code=status)

    @app.put("/api/modes/{name}")
    async def update_mode_endpoint(name: str, request: Request):
        """Update an existing mode."""
        from voxa.skills.modes import mode_manager
        body = await request.json()
        result = mode_manager.edit_mode(
            name=name,
            instructions=body.get("instructions"),
            description=body.get("description"),
        )
        status = 200 if result["success"] else 404
        return JSONResponse(result, status_code=status)

    @app.delete("/api/modes/{name}")
    async def delete_mode_endpoint(name: str):
        """Delete a custom mode."""
        from voxa.skills.modes import mode_manager
        result = mode_manager.delete_mode(name)
        status = 200 if result["success"] else 404
        return JSONResponse(result, status_code=status)

    @app.post("/api/modes/{name}/activate")
    async def activate_mode_endpoint(name: str):
        """Activate a custom mode."""
        from voxa.skills.modes import mode_manager
        import asyncio
        mode = mode_manager.get_mode(name)
        if not mode:
            return JSONResponse({"success": False, "message": f"Mode '{name}' not found"}, status_code=404)
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, lambda: mode_manager.activate_mode(mode))
        return JSONResponse(result)

    @app.post("/api/modes/reload")
    async def reload_modes():
        """Reload modes from disk."""
        from voxa.skills.modes import mode_manager
        mode_manager.reload()
        return JSONResponse({"success": True, "count": mode_manager.mode_count})

    @app.get("/api/config")
    async def get_config():
        """Get non-sensitive configuration values."""
        return JSONResponse({
            "wake_word": config.WAKE_WORD,
            "hotkey_combo": config.HOTKEY_COMBO,
            "default_browser": config.DEFAULT_BROWSER,
            "llm_model": config.LLM_MODEL,
            "llm_model_fast": config.LLM_MODEL_FAST,
            "whisper_model": config.WHISPER_MODEL,
            "log_level": config.LOG_LEVEL,
            "dashboard_port": config.DASHBOARD_PORT,
            "dashboard_enabled": config.DASHBOARD_ENABLED,
            "conversation_mode": config.CONVERSATION_MODE,
            "followup_window_seconds": config.FOLLOWUP_WINDOW_SECONDS,
            "confirm_dangerous": config.CONFIRM_DANGEROUS_COMMANDS,
            "ollama_enabled": config.OLLAMA_ENABLED,
        })

    return app


def _find_free_port(start_port: int, max_attempts: int = 10) -> int:
    """Find a free port starting from start_port."""
    import socket
    for port in range(start_port, start_port + max_attempts):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", port))
                return port
        except OSError:
            continue
    return start_port  # Fall back to original and let uvicorn report the error


def start_dashboard(background: bool = True):
    """
    Start the dashboard server.

    Args:
        background: If True, runs in a daemon thread (default).
    """
    def _run():
        try:
            import uvicorn
            app = create_app()
            if app is None:
                return
            port = _find_free_port(DASHBOARD_PORT)
            if port != DASHBOARD_PORT:
                log.info("🌐 Port %d busy — using %d instead", DASHBOARD_PORT, port)
            log.info("🌐 Voxa Dashboard starting at http://localhost:%d", port)
            uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
        except ImportError:
            log.warning("uvicorn not installed — dashboard disabled. Run: pip install uvicorn")
        except Exception as e:
            log.warning("Dashboard failed to start: %s", e)

    if background:
        t = threading.Thread(target=_run, daemon=True, name="voxa-dashboard")
        t.start()
        return t
    else:
        _run()
