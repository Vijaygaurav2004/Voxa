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
import json
import time
import asyncio
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, HTTPException, UploadFile, File, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response
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


class ModeUpdateRequest(BaseModel):
    """Request body for updating a custom mode."""
    instructions: list[str] | None = None
    description: str | None = None


# ─── WebSocket Connections ───────────────────────────────────────────────────────

_ws_connections: list[WebSocket] = []


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
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

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
            )
        except ImportError:
            log.error("uvicorn not installed. Run: pip install uvicorn")
        except Exception as e:
            log.error("API server failed to start: %s", e)

    if background:
        import threading
        t = threading.Thread(target=_run, daemon=True, name="voxa-api-server")
        t.start()
        return t
    else:
        _run()
