"""
Voxa API Server — Swift ↔ Python Bridge.

Headless FastAPI server that exposes the Python AI/automation pipeline
as HTTP endpoints. The Swift native app communicates with this server
for intent parsing, transcription, TTS, and Python-side action execution.

Run:  python -m voxa.main --server
Port: 7430 (configurable via API_SERVER_PORT in .env)
"""
from __future__ import annotations

import io
import os
import html as _html
import json
import time
import asyncio
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from voxa.config import config
from voxa.utils.logger import get_logger

log = get_logger("server")


# ─── Request / Response Models ───────────────────────────────────────────────────

class IntentRequest(BaseModel):
    """Request body for intent parsing."""
    text: str
    context: str = ""
    use_fast_model: bool = False


class ExecutePlanRequest(BaseModel):
    """Request body for executing an action plan."""
    plan: dict  # ActionPlan as JSON dict
    python_only: bool = True  # Only execute Python-side actions


class ExecuteActionRequest(BaseModel):
    """Request body for executing a single action."""
    action: dict  # Action as JSON dict


class SkillMatchRequest(BaseModel):
    """Request body for checking skill match."""
    text: str


class TimerRequest(BaseModel):
    """Request body for setting a timer."""
    duration_seconds: float
    label: str = "Timer"
    name: Optional[str] = None


class TTSRequest(BaseModel):
    """Request body for TTS generation."""
    text: str
    blocking: bool = False


class CommandRequest(BaseModel):
    """Request body for processing a full command (intent → execute)."""
    text: str
    context: str = ""
    python_only: bool = True


class ModeCreateRequest(BaseModel):
    """Request body for creating a custom mode."""
    name: str
    instructions: list[str]
    description: str = ""


class ModeDescribeRequest(BaseModel):
    """Request body for creating a custom mode from a plain-English description."""
    description: str


class ModeUpdateRequest(BaseModel):
    """Request body for updating a custom mode."""
    instructions: list[str] | None = None
    description: str | None = None


# ─── WebSocket Connections ───────────────────────────────────────────────────────

_ws_connections: list[WebSocket] = []

# The server's running event loop, captured at startup so background threads
# (e.g. the meeting detector) can schedule WebSocket broadcasts thread-safely.
_event_loop: "asyncio.AbstractEventLoop | None" = None


async def broadcast_status(event: str, data: dict):
    """Broadcast a status event to all connected WebSocket clients."""
    message = json.dumps({"event": event, "data": data, "timestamp": time.time()})
    dead = []
    for ws in _ws_connections:
        try:
            await ws.send_text(message)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _ws_connections.remove(ws)


def notify_clients_threadsafe(event: str, data: dict):
    """Schedule a WebSocket broadcast from any thread (no-op if loop not ready)."""
    loop = _event_loop
    if loop is None:
        return
    try:
        asyncio.run_coroutine_threadsafe(broadcast_status(event, data), loop)
    except Exception as e:
        log.warning("Threadsafe notify failed: %s", e)


def _auth_result_page(success: bool, detail: str = "") -> str:
    """Small self-contained result page shown after an OAuth redirect."""
    icon = "✓" if success else "✕"
    title = "Connected" if success else "Connection failed"
    # Escape — `detail` can carry attacker-controlled query params or exception text.
    body = "You can close this tab and return to Voxa." if success else _html.escape(detail or "Please try again from Voxa.")
    color = "#34d399" if success else "#f87171"
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Voxa — {title}</title>
<style>
  body {{ margin: 0; display: flex; align-items: center; justify-content: center;
         min-height: 100vh; background: #101014; color: #e7e7ea;
         font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", sans-serif; }}
  .card {{ text-align: center; padding: 48px 56px; border-radius: 18px;
          background: #1a1a20; border: 1px solid #2a2a32; }}
  .icon {{ font-size: 44px; color: {color}; }}
  h1 {{ font-size: 20px; font-weight: 600; margin: 16px 0 8px; }}
  p {{ font-size: 14px; color: #9a9aa2; margin: 0; }}
</style>
</head>
<body>
  <div class="card">
    <div class="icon">{icon}</div>
    <h1>{title}</h1>
    <p>{body}</p>
  </div>
</body>
</html>"""


# ─── App Factory ─────────────────────────────────────────────────────────────────

def create_api_server() -> FastAPI:
    """Create and return the Voxa API server FastAPI application."""

    app = FastAPI(
        title="Voxa API Server",
        description="Swift ↔ Python bridge for Voxa voice assistant",
        version="2.0.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1", "http://localhost"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Bridge auth (shared-secret between the Swift app and this server) ──────
    # When VOXA_BRIDGE_TOKEN is set (the app injects it at launch), every /api/
    # request must carry it — except /api/health and the two OAuth callback
    # pages, which the browser hits directly. Unset (dev CLI, tests) = no token
    # required, but state-changing requests from foreign browser origins are
    # still rejected (CSRF guard: browsers attach Origin, native clients don't).
    _bridge_token = os.environ.get("VOXA_BRIDGE_TOKEN", "")
    _AUTH_EXEMPT_PATHS = {"/api/health", "/api/auth/google/callback", "/api/auth/github/callback"}

    def _is_local_origin(origin: str) -> bool:
        try:
            from urllib.parse import urlparse
            return urlparse(origin).hostname in ("127.0.0.1", "localhost")
        except Exception:
            return False

    @app.middleware("http")
    async def _bridge_auth_middleware(request: Request, call_next):
        path = request.url.path
        method = request.method.upper()
        if path.startswith("/api/") and method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if origin and not _is_local_origin(origin):
                return JSONResponse(status_code=403, content={"detail": "forbidden origin"})
        if (
            _bridge_token
            and method != "OPTIONS"  # let CORS preflights through to CORSMiddleware
            and path.startswith("/api/")
            and path not in _AUTH_EXEMPT_PATHS
            and request.headers.get("X-Voxa-Token") != _bridge_token
        ):
            return JSONResponse(status_code=401, content={"detail": "unauthorized"})
        return await call_next(request)

    # ── Lazy imports (avoid circular imports at module level) ──────────────────
    def _get_intent_parser():
        from voxa.intelligence.intent_parser import (
            parse_intent, parse_intent_with_retry, ActionPlan, Action, is_simple_command,
        )
        return parse_intent, parse_intent_with_retry, ActionPlan, Action, is_simple_command

    def _get_dispatcher():
        from voxa.actions.dispatcher import execute_plan, execute_python_only, execute_action, execute_action_with_retry
        return execute_plan, execute_python_only, execute_action, execute_action_with_retry

    def _get_context():
        from voxa.intelligence.context import SessionContext, CommandHistory
        return SessionContext, CommandHistory

    # Shared state
    _context = None
    _history = None

    def get_context():
        nonlocal _context
        if _context is None:
            SessionContext, _ = _get_context()
            _context = SessionContext()
        return _context

    def get_history():
        nonlocal _history
        if _history is None:
            _, CommandHistory = _get_context()
            _history = CommandHistory()
        return _history

    # ── Health ────────────────────────────────────────────────────────────────

    @app.get("/api/health")
    async def health():
        """Health check — used by Swift app to confirm backend is ready."""
        return {
            "status": "ok",
            "version": "2.0.0",
            "timestamp": time.time(),
            "config": {
                "llm_model": config.LLM_MODEL,
                "whisper_model": config.WHISPER_MODEL,
                "wake_word": config.WAKE_WORD,
            },
        }

    # ── Intent Parsing ────────────────────────────────────────────────────────

    @app.post("/api/intent")
    async def parse_intent_endpoint(req: IntentRequest):
        """
        Parse natural language into an ActionPlan.
        Returns the full plan with execution_target annotations per action.
        """
        parse_intent, parse_intent_with_retry, ActionPlan, Action, is_simple_command = _get_intent_parser()

        start = time.time()

        # Check skills first
        try:
            from voxa.skills.custom_skills import skill_manager
            skill = skill_manager.match_skill(req.text)
            if skill:
                plan = skill_manager.get_skill_plan(skill)
                if plan:
                    elapsed = time.time() - start
                    return {
                        "plan": plan.model_dump(),
                        "elapsed_ms": int(elapsed * 1000),
                    }
        except Exception as e:
            log.warning("Skill matching in intent endpoint failed: %s", e)

        # Check for natural-language mode CREATION before matching/activation.
        # e.g. "create a work mode that opens VS Code and turns on do not disturb"
        try:
            from voxa.skills.modes import mode_manager
            if mode_manager.is_create_mode_command(req.text):
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(
                    None, lambda: mode_manager.create_mode_from_description(req.text)
                )
                from voxa.intelligence.intent_parser import ActionPlan
                msg = result.get("message", "Mode saved.")
                # Nothing for the Swift app to execute — just speak the confirmation.
                plan = ActionPlan(thought="Built a custom mode from the user's description.", actions=[], confirmation=msg)
                elapsed = time.time() - start
                return {"plan": plan.model_dump(), "elapsed_ms": int(elapsed * 1000)}
        except Exception as e:
            log.warning("Mode creation in intent endpoint failed: %s", e)

        # Check custom modes next
        try:
            from voxa.skills.modes import mode_manager
            matched_mode = mode_manager.match_mode(req.text)
            if matched_mode:
                loop = asyncio.get_running_loop()

                # If the mode was created previously without pre-compiled actions, compile now and save
                if not matched_mode.actions:
                    def _compile_and_save():
                        actions = mode_manager._parse_instructions(matched_mode.instructions)
                        matched_mode.actions = actions
                        mode_manager._save()
                    await loop.run_in_executor(None, _compile_and_save)

                from voxa.intelligence.intent_parser import Action, ActionPlan
                actions = []
                for a in matched_mode.actions:
                    try:
                        actions.append(Action.model_validate(a))
                    except Exception as e:
                        log.error("Failed to validate pre-compiled action: %s", e)

                plan = ActionPlan(
                    thought=f"Executing custom mode: {matched_mode.name}",
                    actions=actions,
                    confirmation=matched_mode.description,
                )
                elapsed = time.time() - start
                return {
                    "plan": plan.model_dump(),
                    "elapsed_ms": int(elapsed * 1000),
                }
        except Exception as e:
            log.warning("Mode matching in intent endpoint failed: %s", e)

        # Run in thread pool to avoid blocking the event loop
        loop = asyncio.get_running_loop()
        plan = await loop.run_in_executor(
            None,
            lambda: parse_intent_with_retry(req.text, context=req.context),
        )

        elapsed = time.time() - start

        if plan is None:
            raise HTTPException(status_code=422, detail="Could not parse intent from the given text")

        return {
            "plan": plan.model_dump(),
            "elapsed_ms": int(elapsed * 1000),
        }

    # ── Action Execution ──────────────────────────────────────────────────────

    @app.post("/api/execute")
    async def execute_plan_endpoint(req: ExecutePlanRequest):
        """
        Execute an action plan.
        If python_only=True (default), only Python-classified actions are executed.
        Swift-classified actions are returned as skipped with routed='swift'.
        """
        _, _, ActionPlan, _, _ = _get_intent_parser()
        execute_plan_fn, execute_python_only_fn, _, _ = _get_dispatcher()

        try:
            plan = ActionPlan.model_validate(req.plan)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid plan format: {e}")

        start = time.time()
        loop = asyncio.get_running_loop()

        if req.python_only:
            results = await loop.run_in_executor(None, lambda: execute_python_only_fn(plan))
        else:
            results = await loop.run_in_executor(None, lambda: execute_plan_fn(plan))

        elapsed = time.time() - start

        # Update context and history
        context = get_context()
        history = get_history()
        actions_dicts = [
            {"action": a.action.value, **{k: v for k, v in a.model_dump().items() if v is not None and k != "action"}}
            for a in plan.actions
        ]
        success_count = sum(1 for r in results if r.get("success", False))
        summary = f"{'✅' if success_count == len(results) else '⚠️'} {success_count}/{len(results)} steps"
        context.add_command(req.plan.get("confirmation", ""), actions_dicts, summary)
        history.record(
            user_input=req.plan.get("confirmation", ""),
            actions=actions_dicts,
            result=summary,
            duration_ms=int(elapsed * 1000),
            success=success_count == len(results),
        )

        # Broadcast status to WebSocket clients
        await broadcast_status("plan_complete", {
            "success_count": success_count,
            "total": len(results),
            "elapsed_ms": int(elapsed * 1000),
        })

        return {
            "results": results,
            "success_count": success_count,
            "total": len(results),
            "elapsed_ms": int(elapsed * 1000),
        }

    @app.post("/api/execute-action")
    async def execute_single_action(req: ExecuteActionRequest):
        """Execute a single action directly."""
        _, _, _, Action, _ = _get_intent_parser()
        _, _, execute_action_fn, _ = _get_dispatcher()

        try:
            action = Action.model_validate(req.action)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid action format: {e}")

        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, lambda: execute_action_fn(action))
        return result

    # ── Full Command Pipeline ─────────────────────────────────────────────────

    @app.post("/api/command")
    async def process_command(req: CommandRequest):
        """
        Full pipeline: text → intent → execute.
        Combines /api/intent + /api/execute in a single call.
        Returns both the plan and execution results.
        """
        _, parse_intent_with_retry, ActionPlan, _, _ = _get_intent_parser()
        _, execute_python_only_fn, _, _ = _get_dispatcher()

        start = time.time()
        loop = asyncio.get_running_loop()

        # Check skills first
        try:
            from voxa.skills.custom_skills import skill_manager
            skill = skill_manager.match_skill(req.text)
            if skill:
                results = await loop.run_in_executor(None, lambda: skill_manager.execute_skill(skill))
                elapsed = time.time() - start
                return {
                    "type": "skill",
                    "skill_name": skill.get("name"),
                    "results": results,
                    "elapsed_ms": int(elapsed * 1000),
                }
        except Exception as e:
            log.warning("Skill check error: %s", e)

        # Check for natural-language mode CREATION before matching/activation.
        try:
            from voxa.skills.modes import mode_manager
            if mode_manager.is_create_mode_command(req.text):
                result = await loop.run_in_executor(
                    None, lambda: mode_manager.create_mode_from_description(req.text)
                )
                elapsed = time.time() - start
                return {
                    "type": "mode_created",
                    "success": result.get("success", False),
                    "message": result.get("message", ""),
                    "mode": result.get("mode"),
                    "elapsed_ms": int(elapsed * 1000),
                }
        except Exception as e:
            log.warning("Mode creation in command endpoint failed: %s", e)

        # Check custom modes next
        try:
            from voxa.skills.modes import mode_manager
            matched_mode = mode_manager.match_mode(req.text)
            if matched_mode:
                if not matched_mode.actions:
                    def _compile_and_save():
                        actions = mode_manager._parse_instructions(matched_mode.instructions)
                        matched_mode.actions = actions
                        mode_manager._save()
                    await loop.run_in_executor(None, _compile_and_save)

                def _execute_mode():
                    from voxa.intelligence.intent_parser import Action, ActionPlan
                    from voxa.actions.dispatcher import execute_plan
                    actions = []
                    for a in matched_mode.actions:
                        try:
                            actions.append(Action.model_validate(a))
                        except Exception as e:
                            log.error("Failed to validate action: %s", e)

                    combined_plan = ActionPlan(
                        thought=f"Executing custom mode: {matched_mode.name}",
                        actions=actions,
                        confirmation=matched_mode.description,
                    )
                    return execute_plan(combined_plan)
                
                results = await loop.run_in_executor(None, _execute_mode)
                elapsed = time.time() - start
                return {
                    "type": "mode",
                    "mode_name": matched_mode.name,
                    "results": results,
                    "elapsed_ms": int(elapsed * 1000),
                }
        except Exception as e:
            log.warning("Mode check error: %s", e)

        # Parse intent
        plan = await loop.run_in_executor(
            None,
            lambda: parse_intent_with_retry(req.text, context=req.context),
        )

        if plan is None:
            raise HTTPException(status_code=422, detail="Could not understand the command")

        # Execute
        if req.python_only:
            results = await loop.run_in_executor(None, lambda: execute_python_only_fn(plan))
        else:
            from voxa.actions.dispatcher import execute_plan as exec_all
            results = await loop.run_in_executor(None, lambda: exec_all(plan))

        elapsed = time.time() - start
        success_count = sum(1 for r in results if r.get("success", False))

        return {
            "type": "plan",
            "plan": plan.model_dump(),
            "results": results,
            "success_count": success_count,
            "total": len(results),
            "elapsed_ms": int(elapsed * 1000),
        }

    # ── Transcription ─────────────────────────────────────────────────────────

    @app.post("/api/transcribe")
    async def transcribe_audio(audio: UploadFile = File(...)):
        """
        Transcribe audio file (WAV) to text using Whisper API.
        The Swift app sends recorded audio here for transcription.
        """
        from voxa.voice.transcribe import transcribe_with_retry

        audio_bytes = await audio.read()
        if not audio_bytes:
            raise HTTPException(status_code=400, detail="Empty audio file")

        loop = asyncio.get_running_loop()
        text = await loop.run_in_executor(None, lambda: transcribe_with_retry(audio_bytes))

        if text is None:
            raise HTTPException(status_code=422, detail="Could not transcribe audio")

        return {"text": text}

    # ── TTS ───────────────────────────────────────────────────────────────────

    @app.post("/api/tts")
    async def generate_tts(req: TTSRequest):
        """
        Generate TTS audio and return it as bytes, or speak locally.
        If blocking=True, speaks using the Python TTS chain and returns when done.
        If blocking=False (default), returns immediately.
        """
        from voxa.voice.tts import speak, speak_confirmation

        loop = asyncio.get_running_loop()
        if req.blocking:
            await loop.run_in_executor(None, lambda: speak(req.text, blocking=True))
        else:
            speak_confirmation(req.text)

        return {"success": True, "text": req.text}

    # ── Timers ────────────────────────────────────────────────────────────────

    @app.get("/api/timers")
    async def get_timers():
        """List active timers."""
        from voxa.actions.timers import list_timers
        return list_timers()

    @app.post("/api/timers")
    async def set_timer(req: TimerRequest):
        """Set a new timer."""
        from voxa.actions.timers import set_timer
        result = set_timer(
            duration_seconds=req.duration_seconds,
            label=req.label,
            name=req.name,
        )
        return result

    @app.delete("/api/timers/{name}")
    async def cancel_timer(name: str):
        """Cancel a timer by name."""
        from voxa.actions.timers import cancel_timer
        result = cancel_timer(name=name)
        return result

    # ── History & Stats ───────────────────────────────────────────────────────

    @app.get("/api/history")
    async def get_history_endpoint(limit: int = 50):
        """Get recent command history."""
        history = get_history()
        recent = history.get_recent(limit)
        return {"history": recent, "count": len(recent)}

    @app.get("/api/stats")
    async def get_stats():
        """Get usage statistics."""
        history = get_history()
        stats = history.get_stats()
        from voxa.actions.timers import get_active_timer_count
        return {**stats, "active_timers": get_active_timer_count()}

    # ── Skills ────────────────────────────────────────────────────────────────

    @app.get("/api/skills")
    async def get_skills():
        """List loaded custom skills."""
        from voxa.skills.custom_skills import skill_manager
        return {
            "skills": skill_manager.skills,
            "count": skill_manager.skill_count,
        }

    @app.post("/api/skills/match")
    async def match_skill(req: SkillMatchRequest):
        """Check if user input matches a custom skill."""
        from voxa.skills.custom_skills import skill_manager
        skill = skill_manager.match_skill(req.text)
        if skill:
            return {"matched": True, "skill": skill}
        return {"matched": False, "skill": None}

    @app.post("/api/skills/reload")
    async def reload_skills():
        """Reload skills from disk."""
        from voxa.skills.custom_skills import skill_manager
        skill_manager.reload()
        return {"success": True, "count": skill_manager.skill_count}

    # ── Custom Modes ──────────────────────────────────────────────────────────

    @app.get("/api/modes")
    async def get_modes():
        """List all user-defined custom modes."""
        from voxa.skills.modes import mode_manager
        return {
            "modes": mode_manager.list_modes(),
            "count": mode_manager.mode_count,
        }

    @app.post("/api/modes")
    async def create_mode(req: ModeCreateRequest):
        """Create a new custom mode."""
        from voxa.skills.modes import mode_manager
        result = mode_manager.create_mode(
            name=req.name,
            instructions=req.instructions,
            description=req.description,
        )
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result["message"])
        return result

    @app.post("/api/modes/generate")
    async def generate_mode_spec_endpoint(req: ModeDescribeRequest):
        """
        Preview a custom mode from a plain-English description WITHOUT saving it,
        so the UI can let the user review/edit the generated steps before creating.
        Returns {name, description, instructions}.
        """
        from voxa.skills.modes import mode_manager
        loop = asyncio.get_running_loop()
        spec = await loop.run_in_executor(
            None, lambda: mode_manager.generate_mode_spec(req.description)
        )
        if not spec:
            raise HTTPException(
                status_code=422,
                detail="Couldn't turn that into a mode. Try describing what it should do.",
            )
        return spec

    @app.post("/api/modes/describe")
    async def create_mode_from_description_endpoint(req: ModeDescribeRequest):
        """
        Build a custom mode from a plain-English description using the small/fast LLM.
        e.g. {"description": "a work mode that opens VS Code and turns on do not disturb"}
        """
        from voxa.skills.modes import mode_manager
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None, lambda: mode_manager.create_mode_from_description(req.description)
        )
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result["message"])
        return result

    @app.put("/api/modes/{name}")
    async def update_mode(name: str, req: ModeUpdateRequest):
        """Update an existing custom mode."""
        from voxa.skills.modes import mode_manager
        result = mode_manager.edit_mode(
            name=name,
            instructions=req.instructions,
            description=req.description,
        )
        if not result["success"]:
            raise HTTPException(status_code=404, detail=result["message"])
        return result

    @app.delete("/api/modes/{name}")
    async def delete_mode(name: str):
        """Delete a custom mode."""
        from voxa.skills.modes import mode_manager
        result = mode_manager.delete_mode(name)
        if not result["success"]:
            raise HTTPException(status_code=404, detail=result["message"])
        return result

    @app.post("/api/modes/{name}/activate")
    async def activate_mode(name: str):
        """Activate a custom mode — parses and executes all instructions."""
        from voxa.skills.modes import mode_manager
        mode = mode_manager.get_mode(name)
        if not mode:
            raise HTTPException(status_code=404, detail=f"Mode '{name}' not found")

        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, lambda: mode_manager.activate_mode(mode))
        return result

    @app.post("/api/modes/reload")
    async def reload_modes():
        """Reload modes from disk."""
        from voxa.skills.modes import mode_manager
        mode_manager.reload()
        return {"success": True, "count": mode_manager.mode_count}

    # ── Context ───────────────────────────────────────────────────────────────

    @app.get("/api/context")
    async def get_context_endpoint():
        """Get current session context for LLM."""
        context = get_context()
        return {
            "context_text": context.get_context_for_llm(),
            "last_app": context.last_app,
            "last_url": context.last_url,
            "last_query": context.last_query,
        }

    @app.post("/api/context/clear")
    async def clear_context():
        """Clear session context."""
        context = get_context()
        context.clear()
        return {"success": True}

    # ── Config (non-sensitive) ────────────────────────────────────────────────

    @app.get("/api/config")
    async def get_config():
        """Get non-sensitive configuration values."""
        return {
            "wake_word": config.WAKE_WORD,
            "hotkey_combo": config.HOTKEY_COMBO,
            "default_browser": config.DEFAULT_BROWSER,
            "llm_model": config.LLM_MODEL,
            "llm_model_fast": config.LLM_MODEL_FAST,
            "whisper_model": config.WHISPER_MODEL,
            "conversation_mode": config.CONVERSATION_MODE,
            "followup_window_seconds": config.FOLLOWUP_WINDOW_SECONDS,
            "dashboard_enabled": config.DASHBOARD_ENABLED,
            "dashboard_port": config.DASHBOARD_PORT,
            "memory_enabled": config.MEMORY_ENABLED,
            "memory_chunk_duration": config.MEMORY_CHUNK_DURATION,
            "memory_retention_days": config.MEMORY_RETENTION_DAYS,
        }

    # ── Integrations (Google / GitHub connections) ────────────────────────────

    @app.get("/api/integrations")
    async def get_integrations():
        """List integration providers with connection status (no tokens/secrets)."""
        from voxa.integrations.oauth import provider_status
        return provider_status()

    @app.post("/api/integrations/{provider}/connect")
    async def connect_integration(provider: str):
        """Start an OAuth connect flow — returns the auth URL to open in a browser."""
        from voxa.integrations.oauth import PROVIDERS, begin_connect
        if provider not in PROVIDERS:
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": f"Unknown provider '{provider}'"},
            )
        return begin_connect(provider)

    @app.post("/api/integrations/{provider}/disconnect")
    async def disconnect_integration(provider: str):
        """Disconnect a provider (revokes/deletes tokens or disables the service)."""
        from voxa.integrations.oauth import PROVIDERS, disconnect
        if provider not in PROVIDERS:
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": f"Unknown provider '{provider}'"},
            )
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, lambda: disconnect(provider))
        await broadcast_status("integration_disconnected", {"provider": provider})
        return result

    @app.get("/api/auth/google/callback")
    async def google_auth_callback(code: str = "", state: str = "", error: str = ""):
        """OAuth loopback redirect target for Google — shown in the user's browser."""
        from voxa.integrations.oauth import handle_google_callback
        if error or not code:
            return HTMLResponse(_auth_result_page(False, error or "Missing authorization code."), status_code=400)
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, lambda: handle_google_callback(code, state))
        if not result.get("success"):
            return HTMLResponse(_auth_result_page(False, result.get("message", "")), status_code=400)
        account = result.get("account") or {}
        label = account.get("email", "")
        if account.get("name") and label:
            label = f"{account['name']} ({label})"
        await broadcast_status("integration_connected", {
            "provider": result.get("provider"),
            "account_label": label,
        })
        return HTMLResponse(_auth_result_page(True))

    @app.get("/api/auth/github/callback")
    async def github_auth_callback(code: str = "", state: str = "", error: str = ""):
        """OAuth loopback redirect target for GitHub — shown in the user's browser."""
        from voxa.integrations.oauth import handle_github_callback
        if error or not code:
            return HTMLResponse(_auth_result_page(False, error or "Missing authorization code."), status_code=400)
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, lambda: handle_github_callback(code, state))
        if not result.get("success"):
            return HTMLResponse(_auth_result_page(False, result.get("message", "")), status_code=400)
        account = result.get("account") or {}
        await broadcast_status("integration_connected", {
            "provider": "github",
            "account_label": account.get("login", ""),
        })
        return HTMLResponse(_auth_result_page(True))

    # ── Memory (Always-On Ambient Listening) ──────────────────────────────────

    @app.post("/api/memory/start")
    async def start_memory():
        """Start the ambient listening memory engine."""
        from voxa.memory.engine import memory_engine
        if memory_engine.is_active:
            return {"success": True, "message": "Memory engine is already running."}
        
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, memory_engine.start)
        return {"success": True, "message": "Memory engine started. Listening to everything."}

    @app.post("/api/memory/stop")
    async def stop_memory():
        """Stop the ambient listening memory engine."""
        from voxa.memory.engine import memory_engine
        if not memory_engine._running:
            return {"success": True, "message": "Memory engine is not running."}
        
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, memory_engine.stop)
        return {"success": True, "message": "Memory engine stopped."}

    @app.get("/api/memory/status")
    async def memory_status():
        """Get memory engine status and statistics."""
        from voxa.memory.engine import memory_engine
        return memory_engine.status

    @app.post("/api/memory/ingest")
    async def memory_ingest(audio: UploadFile = File(...), source: str = Form("mic")):
        """
        Ingest an externally-captured audio chunk (WAV) from the host app. Used
        when the engine runs in external-audio mode (e.g. meeting recording), so
        audio is captured by the Swift app, which reliably holds mic access.

        source: "mic" (this user) or "system" (other participants, via system
        audio) — stored so the transcript can attribute both sides of the call.
        """
        from voxa.memory.engine import memory_engine
        if not memory_engine._running:
            return {"success": False, "ignored": True, "reason": "engine not running"}
        data = await audio.read()
        src = source if source in ("mic", "system") else "mic"
        loop = asyncio.get_running_loop()
        queued = await loop.run_in_executor(None, lambda: memory_engine.ingest_chunk(data, src))
        return {"success": True, "queued": queued, "bytes": len(data), "source": src}

    @app.post("/api/memory/query")
    async def memory_query(req: dict):
        """
        Ask a question about past conversations.
        Body: {"question": "What did they say about the deadline?"}
        """
        from voxa.memory.recall import memory_recall
        question = req.get("question", req.get("text", ""))
        if not question:
            raise HTTPException(status_code=400, detail="Missing 'question' field")
        
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, lambda: memory_recall.answer_question(question))
        return result

    @app.get("/api/memory/recent")
    async def memory_recent(hours: float = 24.0, limit: int = 50):
        """Get recent memory segments."""
        from voxa.memory.engine import memory_engine
        store = memory_engine.store
        segments = store.get_recent(hours=hours, limit=limit)
        return {"segments": [s.to_dict() for s in segments], "count": len(segments)}

    @app.get("/api/memory/sessions")
    async def memory_sessions(limit: int = 20):
        """List recent conversation sessions."""
        from voxa.memory.engine import memory_engine
        store = memory_engine.store
        sessions = store.list_sessions(limit=limit)
        return {"sessions": sessions, "count": len(sessions)}

    @app.get("/api/memory/session/{session_id}")
    async def memory_session_detail(session_id: str):
        """Get all segments from a specific conversation session."""
        from voxa.memory.engine import memory_engine
        store = memory_engine.store
        segments = store.get_by_session(session_id)
        return {"segments": [s.to_dict() for s in segments], "count": len(segments)}

    @app.post("/api/memory/summarize")
    async def memory_summarize(req: dict):
        """
        Summarize conversations.
        Body: {"hours": 24} or {"session_id": "abc12345"}
        """
        from voxa.memory.recall import memory_recall
        loop = asyncio.get_running_loop()

        if "session_id" in req:
            result = await loop.run_in_executor(
                None, lambda: memory_recall.summarize_session(req["session_id"])
            )
        else:
            hours = req.get("hours", 24.0)
            result = await loop.run_in_executor(
                None, lambda: memory_recall.summarize_recent(hours)
            )
        return result

    @app.post("/api/memory/search")
    async def memory_search(req: dict):
        """
        Raw search across memory.
        Body: {"query": "search terms", "limit": 10}
        """
        from voxa.memory.recall import memory_recall
        query = req.get("query", "")
        limit = req.get("limit", 10)
        if not query:
            raise HTTPException(status_code=400, detail="Missing 'query' field")
        
        loop = asyncio.get_running_loop()
        results = await loop.run_in_executor(None, lambda: memory_recall.search(query, limit))
        return {"results": results, "count": len(results)}

    @app.delete("/api/memory/clear")
    async def memory_clear():
        """Clear ALL memory segments permanently."""
        from voxa.memory.engine import memory_engine
        store = memory_engine.store
        count = store.clear_all()
        return {"success": True, "message": f"Cleared {count} memory segments.", "deleted_count": count}

    @app.post("/api/memory/cleanup")
    async def memory_cleanup(req: dict = None):
        """Delete memory segments older than N days."""
        from voxa.memory.engine import memory_engine
        days = (req or {}).get("days", config.MEMORY_RETENTION_DAYS)
        deleted = memory_engine.cleanup(days)
        return {"success": True, "deleted_count": deleted, "retention_days": days}

    # ── Memory Audio Clips + Storage ──────────────────────────────────────────

    def _storage_info(store) -> dict:
        """Build the storage/settings dict (shared by GET storage + POST settings)."""
        stats = store.get_stats()
        return {
            "clips_count": stats.get("clips_count", 0),
            "clips_size_mb": stats.get("clips_size_mb", 0.0),
            "db_size_mb": stats.get("db_size_mb", 0.0),
            "keep_audio": bool(getattr(config, "MEMORY_KEEP_AUDIO", True)),
            "retention_days": int(getattr(config, "MEMORY_RETENTION_DAYS", 30)),
        }

    @app.get("/api/memory/clips")
    async def memory_clips(limit: int = 50):
        """List stored audio clips (segments with a clip file on disk), newest first."""
        from voxa.memory.engine import memory_engine
        clips = memory_engine.store.list_clips(limit=limit)
        # Don't leak absolute disk paths to the client.
        for c in clips:
            c.pop("audio_path", None)
        return {"clips": clips, "count": len(clips)}

    @app.get("/api/memory/clip/{segment_id}")
    async def memory_clip_audio(segment_id: int):
        """Stream a single clip's raw WAV bytes."""
        from voxa.memory.engine import memory_engine
        path = memory_engine.store.get_clip_path(segment_id)
        if not path:
            raise HTTPException(status_code=404, detail="Clip not found")
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError:
            raise HTTPException(status_code=404, detail="Clip file missing")
        return Response(content=data, media_type="audio/wav")

    @app.delete("/api/memory/clip/{segment_id}")
    async def memory_clip_delete(segment_id: int):
        """Delete a clip's audio file AND its DB segment row + vector."""
        from voxa.memory.engine import memory_engine
        deleted = memory_engine.store.delete_segment(segment_id)
        return {"success": deleted, "deleted": deleted}

    @app.get("/api/memory/storage")
    async def memory_storage():
        """Clip/DB storage usage plus keep-audio and retention settings."""
        from voxa.memory.engine import memory_engine
        return _storage_info(memory_engine.store)

    @app.post("/api/memory/settings")
    async def memory_settings(req: dict):
        """Update keep-audio / retention at runtime and persist them to ~/.voxa/.env."""
        from voxa.config import persist_env_setting
        from voxa.memory.engine import memory_engine
        if "keep_audio" in req:
            val = bool(req["keep_audio"])
            config.MEMORY_KEEP_AUDIO = val
            persist_env_setting("MEMORY_KEEP_AUDIO", "true" if val else "false")
        if "retention_days" in req:
            try:
                days = int(req["retention_days"])
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="retention_days must be an integer")
            config.MEMORY_RETENTION_DAYS = days
            persist_env_setting("MEMORY_RETENTION_DAYS", days)
        return _storage_info(memory_engine.store)

    @app.post("/api/memory/clips/clear")
    async def memory_clips_clear():
        """Delete all clip FILES but keep transcripts (audio_path reset to '')."""
        from voxa.memory.engine import memory_engine
        deleted = memory_engine.store.clear_clips()
        return {"success": True, "deleted": deleted}

    @app.get("/api/memory/clip-sessions")
    async def memory_clip_sessions(limit: int = 30):
        """Group clips into session cards (AI title · date · platform), newest first."""
        from voxa.memory.sessions import session_organizer
        loop = asyncio.get_running_loop()
        # Title generation may call the LLM — keep it off the event loop.
        sessions = await loop.run_in_executor(
            None, lambda: session_organizer.list_clip_sessions(limit)
        )
        return {"sessions": sessions, "count": len(sessions)}

    @app.delete("/api/memory/session/{session_id}")
    async def memory_session_delete(session_id: str):
        """Delete a session's clip FILES (transcripts stay searchable in Memory)."""
        from voxa.memory.sessions import session_organizer
        return session_organizer.delete_session(session_id)

    # ── Meeting Detection (Granola-style auto-capture) ────────────────────────

    @app.get("/api/meeting/status")
    async def meeting_status():
        """Whether meeting auto-detection is on and if a meeting is active."""
        from voxa.memory.meeting_manager import meeting_manager
        return meeting_manager.status

    @app.post("/api/meeting/start")
    async def meeting_start():
        """Enable automatic meeting detection + capture."""
        from voxa.memory.meeting_manager import meeting_manager
        return meeting_manager.enable()

    @app.post("/api/meeting/stop")
    async def meeting_stop():
        """Disable automatic meeting detection."""
        from voxa.memory.meeting_manager import meeting_manager
        return meeting_manager.disable()

    @app.post("/api/meeting/confirm")
    async def meeting_confirm(req: dict):
        """Answer the 'record this meeting?' prompt. Body: {"record": true/false}."""
        from voxa.memory.meeting_manager import meeting_manager
        record = bool(req.get("record", False))
        return meeting_manager.confirm(record)

    @app.post("/api/meeting/pause")
    async def meeting_pause():
        """Pause the active meeting recording."""
        from voxa.memory.meeting_manager import meeting_manager
        return meeting_manager.pause_recording()

    @app.post("/api/meeting/resume")
    async def meeting_resume():
        """Resume a paused meeting recording."""
        from voxa.memory.meeting_manager import meeting_manager
        return meeting_manager.resume_recording()

    @app.post("/api/meeting/end")
    async def meeting_end():
        """End the current meeting recording now and save its notes."""
        from voxa.memory.meeting_manager import meeting_manager
        loop = asyncio.get_running_loop()
        # Summarization can be slow — run off the event loop.
        return await loop.run_in_executor(None, meeting_manager.end_recording)

    @app.get("/api/meeting/list")
    async def meeting_list(limit: int = 20):
        """List recently captured meetings (newest first)."""
        from voxa.memory.meeting_manager import meeting_manager
        meetings = meeting_manager.list_meetings(limit)
        return {"meetings": meetings, "count": len(meetings)}

    @app.post("/api/meeting/insights/{session_id}")
    async def meeting_regenerate_insights(session_id: str):
        """(Re)generate structured notes (summary + action items + to-dos +
        follow-ups) for a saved meeting and persist them into its record."""
        from voxa.memory.meeting_manager import meeting_manager
        loop = asyncio.get_running_loop()
        # Extraction is an LLM call — run it off the event loop.
        return await loop.run_in_executor(None, meeting_manager.regenerate_insights, session_id)

    @app.post("/api/meeting/reminders/{session_id}")
    async def meeting_export_reminders(session_id: str):
        """Create macOS Reminders from a saved meeting's action items and to-dos."""
        from voxa.memory.meeting_manager import meeting_manager
        loop = asyncio.get_running_loop()
        # AppleScript calls block — run off the event loop.
        return await loop.run_in_executor(None, meeting_manager.export_to_reminders, session_id)

    @app.post("/api/meeting/suggestion/confirm")
    async def suggestion_confirm(req: dict):
        """Answer a proactive 'add to calendar?' suggestion. Body: {suggestion_id, accept}."""
        from voxa.memory.suggestions import suggestion_manager
        suggestion_id = req.get("suggestion_id", "")
        accept = bool(req.get("accept", False))
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, suggestion_manager.confirm, suggestion_id, accept)

    # ── To-dos (captured from meetings and ordinary conversation) ─────────────

    @app.get("/api/todos")
    async def todos_list(include_done: bool = True, limit: int = 200):
        """The running to-do list — open items first, newest first."""
        from voxa.memory.todos import todo_manager
        items = todo_manager.list_todos(include_done=include_done, limit=limit)
        return {
            "todos": items,
            "count": len(items),
            "open_count": sum(1 for t in items if not t.get("done")),
        }

    @app.post("/api/todos")
    async def todos_add(req: dict):
        """Add a to-do by hand. Body: {task, owner?, due?}."""
        from voxa.memory.todos import todo_manager
        task = (req or {}).get("task", "")
        if not str(task).strip():
            raise HTTPException(status_code=400, detail="Missing 'task'")
        record = todo_manager.add(
            task=task,
            owner=(req or {}).get("owner", ""),
            due=(req or {}).get("due", ""),
            source="manual",
        )
        if record is None:
            return {"success": False, "message": "That's already on your list."}
        return {"success": True, "todo": record}

    @app.post("/api/todos/{todo_id}/done")
    async def todos_done(todo_id: str, req: dict = None):
        """Tick a to-do off (or un-tick it with {"done": false})."""
        from voxa.memory.todos import todo_manager
        done = bool((req or {}).get("done", True))
        ok = todo_manager.set_done(todo_id, done)
        if not ok:
            raise HTTPException(status_code=404, detail="No such to-do")
        return {"success": True, "done": done}

    @app.delete("/api/todos/{todo_id}")
    async def todos_delete(todo_id: str):
        """Remove a to-do entirely."""
        from voxa.memory.todos import todo_manager
        ok = todo_manager.delete(todo_id)
        if not ok:
            raise HTTPException(status_code=404, detail="No such to-do")
        return {"success": True}

    @app.post("/api/todos/clear-completed")
    async def todos_clear_completed():
        """Drop everything already ticked off."""
        from voxa.memory.todos import todo_manager
        return {"success": True, "removed": todo_manager.clear_completed()}

    @app.post("/api/todos/export-reminders")
    async def todos_export_reminders():
        """Push not-yet-exported to-dos into the macOS Reminders app."""
        from voxa.memory.todos import todo_manager
        loop = asyncio.get_running_loop()
        # AppleScript blocks — keep it off the event loop.
        return await loop.run_in_executor(None, todo_manager.export_to_reminders)

    @app.get("/api/meeting/suggestions")
    async def suggestion_list():
        """List currently-pending calendar suggestions awaiting the user's answer."""
        from voxa.memory.suggestions import suggestion_manager
        items = suggestion_manager.list_pending()
        return {"suggestions": items, "count": len(items)}

    @app.on_event("startup")
    async def _meeting_startup():
        """Capture the loop, wire the app-notify channel, and auto-enable if set."""
        global _event_loop
        _event_loop = asyncio.get_running_loop()
        try:
            from voxa.memory.meeting_manager import meeting_manager
            meeting_manager.set_notifier(notify_clients_threadsafe)
            from voxa.memory.suggestions import suggestion_manager
            suggestion_manager.set_notifier(notify_clients_threadsafe)
            from voxa.memory.todos import todo_manager
            todo_manager.set_notifier(notify_clients_threadsafe)
            if config.MEETING_AUTO_DETECT:
                meeting_manager.enable()
        except Exception as e:
            log.warning("Meeting startup init failed: %s", e)

    # ── WebSocket for real-time status ────────────────────────────────────────

    @app.websocket("/ws/status")
    async def websocket_status(websocket: WebSocket):
        """
        WebSocket endpoint for real-time status updates.
        The Swift app connects here to receive:
        - Timer alerts
        - Execution progress
        - State changes
        """
        if _bridge_token:
            # Prefer the header (never logged); query param kept for compatibility.
            supplied = websocket.headers.get("x-voxa-token") or websocket.query_params.get("token")
            if supplied != _bridge_token:
                await websocket.close(code=4401)
                return
        await websocket.accept()
        _ws_connections.append(websocket)
        log.info("WebSocket client connected (%d total)", len(_ws_connections))

        try:
            while True:
                # Keep alive — receive pings or commands from Swift
                data = await websocket.receive_text()
                if data == "ping":
                    await websocket.send_text(json.dumps({"event": "pong", "timestamp": time.time()}))
        except WebSocketDisconnect:
            if websocket in _ws_connections:
                _ws_connections.remove(websocket)
            log.info("WebSocket client disconnected (%d remaining)", len(_ws_connections))

    return app


# ─── Server Launcher ─────────────────────────────────────────────────────────────

def start_api_server(background: bool = False):
    """
    Start the Voxa API server.

    Args:
        background: If True, runs in a daemon thread.
    """
    def _run():
        try:
            import uvicorn
            app = create_api_server()
            log.info("🚀 Voxa API Server starting at http://%s:%d",
                     config.API_SERVER_HOST, config.API_SERVER_PORT)
            uvicorn.run(
                app,
                host=config.API_SERVER_HOST,
                port=config.API_SERVER_PORT,
                log_level="info",
                access_log=False,  # request lines would log the ws bridge token
            )
        except ImportError:
            log.error("uvicorn not installed. Run: pip install uvicorn")
        except OSError as e:
            log.error(
                "API server could not bind %s:%d — %s. "
                "Another Voxa backend may already be running on that port.",
                config.API_SERVER_HOST, config.API_SERVER_PORT, e,
            )
        except Exception as e:
            log.error("API server failed to start: %s", e)

    if background:
        import threading
        t = threading.Thread(target=_run, daemon=True, name="voxa-api-server")
        t.start()
        return t
    else:
        _run()
