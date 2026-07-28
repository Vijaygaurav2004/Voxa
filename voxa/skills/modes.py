"""
Custom Modes System for Voxa.
Lets users define modes (e.g. "work mode", "chill mode") with plain English
instructions. When activated, the instructions are parsed by the LLM into
ActionPlans and executed through the standard dispatcher pipeline.

Modes are stored in ~/.voxa/modes.json and persist across sessions.
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Optional
from voxa.utils.logger import get_logger

log = get_logger("modes")

# Persistent storage location
MODES_DIR = Path.home() / ".voxa"
MODES_FILE = MODES_DIR / "modes.json"

# Detects natural-language "create a mode" commands, e.g.
#   "create a work mode that opens VS Code and turns on do not disturb"
#   "make me a focus mode", "set up a study mode", "define a gaming mode"
_CREATE_MODE_RE = re.compile(
    r'\b(create|make|set\s?up|build|define|configure|design|new)\b'
    r'.{0,40}?\bmode\b',
    re.IGNORECASE,
)

# Built-in macOS / device "modes" that are NOT user-defined Voxa modes. When the
# user names one of these, they want to toggle a system feature (handled by the
# normal intent parser), not define a custom automation mode.
_SYSTEM_MODE_RE = re.compile(
    r'\b(dark|light|night|airplane|aeroplane|sleep|standby|safe|silent|'
    r'incognito|private|'
    r'low[\s-]?power|power[\s-]?saving|battery[\s-]?saver|'
    r'full[\s-]?screen|do not disturb|dnd)\s+mode\b',
    re.IGNORECASE,
)


class Mode:
    """Represents a single user-defined mode."""

    def __init__(
        self,
        name: str,
        trigger: str,
        description: str,
        instructions: list[str],
        actions: list[dict] | None = None,
        created_at: str | None = None,
        updated_at: str | None = None,
    ):
        self.name = name
        self.trigger = trigger.lower().strip()
        self.description = description
        self.instructions = instructions
        self.actions = actions or []
        self.created_at = created_at or datetime.now().isoformat()
        self.updated_at = updated_at or self.created_at

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "trigger": self.trigger,
            "description": self.description,
            "instructions": self.instructions,
            "actions": self.actions,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Mode":
        return cls(
            name=data["name"],
            trigger=data["trigger"],
            description=data.get("description", ""),
            instructions=data.get("instructions", []),
            actions=data.get("actions", []),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )


class ModeManager:
    """
    Manages user-defined modes: CRUD, trigger matching, and activation.
    Modes are stored as JSON in ~/.voxa/modes.json.
    """

    def __init__(self):
        self.modes: list[Mode] = []
        self._load()

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load(self):
        """Load modes from disk."""
        if not MODES_FILE.exists():
            log.info("No modes.json found at %s — starting with empty modes", MODES_FILE)
            return

        try:
            with open(MODES_FILE, "r") as f:
                data = json.load(f)
            raw_modes = data.get("modes", [])
            self.modes = [Mode.from_dict(m) for m in raw_modes]
            log.info("✅ Loaded %d custom mode(s) from %s", len(self.modes), MODES_FILE)
        except Exception as e:
            log.error("Failed to load modes.json: %s", e)

    def _save(self):
        """Save modes to disk."""
        try:
            MODES_DIR.mkdir(parents=True, exist_ok=True)
            data = {"modes": [m.to_dict() for m in self.modes]}
            with open(MODES_FILE, "w") as f:
                json.dump(data, f, indent=2)
            log.info("💾 Saved %d mode(s) to %s", len(self.modes), MODES_FILE)
        except Exception as e:
            log.error("Failed to save modes.json: %s", e)

    def reload(self):
        """Reload modes from disk."""
        self.modes = []
        self._load()

    # ── CRUD ──────────────────────────────────────────────────────────────────

    def _parse_instructions(self, instructions: list[str]) -> list[dict]:
        """
        Parse plain English instructions into structured actions using the LLM.

        Each instruction is an independent LLM call, so they are compiled
        concurrently (order preserved) instead of serially — a 5-step mode goes
        from ~5 round-trips of latency down to ~1.
        """
        from concurrent.futures import ThreadPoolExecutor
        from voxa.intelligence.intent_parser import parse_intent_with_retry

        if not instructions:
            return []

        # ThreadPoolExecutor.map preserves input order; the OpenAI client is
        # safe to call from multiple threads.
        max_workers = min(len(instructions), 5)
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            plans = list(ex.map(parse_intent_with_retry, instructions))

        all_actions = []
        for plan in plans:
            if plan and plan.actions:
                for a in plan.actions:
                    a_dict = {"action": a.action.value, **{k: v for k, v in a.model_dump().items() if v is not None and k != "action"}}
                    all_actions.append(a_dict)
        return all_actions

    def create_mode(
        self,
        name: str,
        instructions: list[str],
        description: str = "",
    ) -> dict:
        """
        Create a new mode.

        Args:
            name: Display name (e.g. "Work Mode").
            instructions: List of plain English instructions.
            description: Optional short description shown on activation.

        Returns:
            Result dict with success status and message.
        """
        trigger = name.lower().strip()

        # Check for duplicate trigger
        existing = self._find_by_trigger(trigger)
        if existing:
            return {
                "success": False,
                "message": f"A mode with trigger '{trigger}' already exists. Use 'mode edit {name}' to modify it.",
            }

        if not instructions:
            return {
                "success": False,
                "message": "Mode must have at least one instruction.",
            }

        # Auto-generate description if not provided
        if not description:
            n_inst = len(instructions)
            description = f"Activating {name} — {n_inst} action{'s' if n_inst != 1 else ''}"

        # Parse instructions to actions permanently now
        log.info("🔮 Compiling custom mode '%s' instructions to actions...", name)
        try:
            actions = self._parse_instructions(instructions)
        except Exception as e:
            log.error("Failed to compile mode instructions: %s", e)
            actions = []

        mode = Mode(
            name=name,
            trigger=trigger,
            description=description,
            instructions=instructions,
            actions=actions,
        )
        self.modes.append(mode)
        self._save()

        log.info("✨ Mode created: '%s' with %d instructions", name, len(instructions))
        return {
            "success": True,
            "message": f"Mode '{name}' created with {len(instructions)} instruction(s)!",
            "mode": mode.to_dict(),
        }

    def edit_mode(
        self,
        name: str,
        instructions: list[str] | None = None,
        description: str | None = None,
    ) -> dict:
        """
        Edit an existing mode's instructions and/or description.

        Args:
            name: Mode name or trigger to edit.
            instructions: New list of instructions (replaces existing).
            description: New description (replaces existing).

        Returns:
            Result dict.
        """
        mode = self._find_by_trigger(name.lower().strip())
        if not mode:
            return {
                "success": False,
                "message": f"Mode '{name}' not found. Use 'mode list' to see available modes.",
            }

        if instructions is not None:
            if not instructions:
                return {"success": False, "message": "Mode must have at least one instruction."}
            mode.instructions = instructions
            
            # Re-compile instructions to actions permanently now
            log.info("🔮 Re-compiling custom mode '%s' instructions to actions...", mode.name)
            try:
                mode.actions = self._parse_instructions(instructions)
            except Exception as e:
                log.error("Failed to re-compile mode instructions: %s", e)

        if description is not None:
            mode.description = description

        mode.updated_at = datetime.now().isoformat()
        self._save()

        log.info("✏️  Mode edited: '%s'", mode.name)
        return {
            "success": True,
            "message": f"Mode '{mode.name}' updated!",
            "mode": mode.to_dict(),
        }

    def delete_mode(self, name: str) -> dict:
        """
        Delete a mode by name.

        Args:
            name: Mode name or trigger to delete.

        Returns:
            Result dict.
        """
        trigger = name.lower().strip()
        mode = self._find_by_trigger(trigger)
        if not mode:
            return {
                "success": False,
                "message": f"Mode '{name}' not found.",
            }

        self.modes.remove(mode)
        self._save()

        log.info("🗑️  Mode deleted: '%s'", mode.name)
        return {
            "success": True,
            "message": f"Mode '{mode.name}' deleted.",
        }

    def get_mode(self, name: str) -> Mode | None:
        """Get a mode by name or trigger."""
        return self._find_by_trigger(name.lower().strip())

    def list_modes(self) -> list[dict]:
        """Return all modes as dicts."""
        return [m.to_dict() for m in self.modes]

    @property
    def mode_count(self) -> int:
        return len(self.modes)

    # ── Small/Fast LLM helper ─────────────────────────────────────────────────

    @staticmethod
    def _fast_llm_json(
        system: str,
        user: str,
        temperature: float = 0.0,
        max_tokens: int = 60,
    ) -> dict | None:
        """
        Call the small/fast LLM (config.LLM_MODEL_FAST, e.g. gpt-4o-mini) with a
        JSON-only response format and return the parsed object.

        This is the shared entry point for all the "cheap intelligence" that Voxa
        uses to understand vague prompts: matching a fuzzy phrase to an existing
        mode, and building a brand-new mode from a plain English description.

        Returns the parsed dict, or None on any failure (missing key, API error,
        malformed JSON).
        """
        try:
            from openai import OpenAI
            from voxa.config import config

            api_key = config.OPENAI_API_KEY
            if not api_key:
                return None

            client = OpenAI(api_key=api_key)
            response = client.chat.completions.create(
                model=config.LLM_MODEL_FAST,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=temperature,
                response_format={"type": "json_object"},
                max_tokens=max_tokens,
            )
            content = response.choices[0].message.content or ""
            return json.loads(content)
        except Exception as e:
            log.warning("Fast LLM JSON call failed: %s", e)
            return None

    # ── Trigger Matching ──────────────────────────────────────────────────────

    def _match_mode_with_llm(self, user_input: str) -> Mode | None:
        """
        Use small/fast LLM (config.LLM_MODEL_FAST e.g. gpt-4o-mini) to match
        vague user prompts (e.g. "I want to focus now", "time to relax") to custom modes.
        """
        if not self.modes:
            return None

        modes_info = []
        for m in self.modes:
            inst_str = ", ".join(m.instructions[:3])
            modes_info.append(f'- Mode Name: "{m.name}" | Trigger: "{m.trigger}" | Description: "{m.description}" | Steps: [{inst_str}]')

        prompt = (
            "You are an intent classifier for system modes.\n"
            "The user has defined the following custom modes:\n"
            + "\n".join(modes_info) + "\n\n"
            f'User prompt: "{user_input}"\n\n'
            "Task: Decide if the user prompt is vaguely or explicitly describing an intent to activate or switch to one of the custom modes listed above.\n"
            "Examples:\n"
            "- Prompt: 'I need to focus and write code' -> matches 'Work Mode'\n"
            "- Prompt: 'Time to chill and play music' -> matches 'Chill Mode'\n"
            "- Prompt: 'Getting ready for study' -> matches 'Study Mode'\n\n"
            "Return a JSON object:\n"
            '{"match": true, "trigger": "<trigger_or_name>"}\n'
            "or if it does not match any mode:\n"
            '{"match": false, "trigger": null}'
        )

        data = self._fast_llm_json(
            system="You are a fast intent classifier. Return valid JSON only.",
            user=prompt,
            temperature=0.0,
            max_tokens=60,
        )
        if data and data.get("match") and data.get("trigger"):
            trig = str(data["trigger"]).lower().strip()
            matched = self._find_by_trigger(trig)
            if matched:
                log.info("🧠 Small LLM matched vague prompt '%s' -> mode '%s'", user_input, matched.name)
                return matched

        return None

    def match_mode(self, user_input: str, allow_llm: bool = True) -> Mode | None:
        """
        Check if user input matches any mode trigger.
        Matching is case-insensitive. Supports:
        1. Exact match & activation prefixes ("activate X", "switch to X")
        2. Levenshtein fuzzy distance matching
        3. Small LLM intent classification for vague prompts ("I want to focus now" -> Work Mode)

        Args:
            user_input: The raw user command string.
            allow_llm: Whether to use fast LLM fallback for vague intent matching.

        Returns:
            Matched Mode, or None.
        """
        lower = user_input.lower().strip()

        # Clean up leading filler words and trailing punctuation
        cleaned = re.sub(r'^(yes|ok|okay)[.,!\s]+', '', lower).strip()
        cleaned = cleaned.rstrip(".!?").strip()

        # Direct trigger match (e.g., "work mode")
        matched = self._find_by_trigger(cleaned)
        if matched:
            return matched

        # Activation phrase patterns
        activation_prefixes = [
            "activate ", "switch to ", "enable ", "enter ",
            "start ", "turn on ", "go to ", "launch ", "run ",
            "open ", "load ",
        ]
        for prefix in activation_prefixes:
            if cleaned.startswith(prefix):
                remainder = cleaned[len(prefix):].strip()
                matched = self._find_by_trigger(remainder)
                if matched:
                    return matched

        # Fast LLM intent matching for vague prompts
        if allow_llm and self.modes:
            matched_llm = self._match_mode_with_llm(user_input)
            if matched_llm:
                return matched_llm

        return None

    # ── Natural-language Creation ─────────────────────────────────────────────

    def is_create_mode_command(self, user_input: str) -> bool:
        """
        Heuristic check for whether the user is asking to CREATE / DEFINE a new
        mode from a plain-English description (as opposed to activating one).

        Matches: "create a work mode that...", "make me a focus mode",
                 "set up a study mode", "build a gaming mode".
        Does NOT match pure activation phrases like "switch to work mode".
        """
        lower = user_input.lower().strip()
        if "mode" not in lower:
            return False
        # Don't hijack commands about built-in system modes (dark mode, sleep
        # mode, do not disturb mode…) — those are toggles, not custom modes.
        if _SYSTEM_MODE_RE.search(lower):
            return False
        return bool(_CREATE_MODE_RE.search(lower))

    # Capabilities summary given to the small LLM so it only proposes feasible steps.
    _CAPABILITY_HINT = (
        "Voxa can, per instruction: open or close any macOS app; open URLs and "
        "search/play on the web (Google, YouTube, Netflix, Maps); control Chrome "
        "tabs and windows; set system volume, brightness, dark mode, Do Not Disturb; "
        "control media playback (Spotify/Music); set timers; check calendar; send "
        "WhatsApp messages and compose email; run shell commands; and speak to the user. "
        "Connected integrations MAY also exist: create Google Calendar events, send "
        "Gmail, and check GitHub notifications."
    )

    def generate_mode_spec(self, description: str) -> dict | None:
        """
        Use the small/fast LLM to turn a free-form description into a structured
        mode spec WITHOUT saving it. Returns {name, description, instructions[]}
        or None on failure.

        This is the shared brain used by both the "create from voice" path and the
        UI "✨ generate" button (which lets the user review/edit before saving).
        """
        system = (
            "You design custom automation 'modes' for Voxa, a hands-free macOS "
            "voice assistant. The user describes, in plain English, a mode they want. "
            "Convert it into a concrete, executable mode.\n\n"
            + self._CAPABILITY_HINT + "\n\n"
            "Return ONLY a JSON object:\n"
            '{"name": "<Short Mode Name>", "description": "<one friendly sentence>", '
            '"instructions": ["<single imperative command>", "..."]}\n\n'
            "Rules:\n"
            "- name: 1-3 words, Title Case, ending in 'Mode' (e.g. 'Work Mode').\n"
            "- instructions: each is ONE atomic command phrased exactly as the user "
            "would speak it to Voxa (e.g. 'Open Visual Studio Code', 'Turn on Do Not "
            "Disturb', 'Set brightness to 100%', 'Play lofi beats on YouTube'). Keep "
            "each step to a single action.\n"
            "- If the description is vague (e.g. 'make a focus mode'), infer 3-5 "
            "sensible steps that fit the theme.\n"
            "- Only propose steps within Voxa's listed capabilities."
        )
        user = f'User request: "{description}"'

        data = self._fast_llm_json(system=system, user=user, temperature=0.3, max_tokens=500)
        if not data:
            return None

        name = str(data.get("name") or "").strip() or "Custom Mode"
        desc = str(data.get("description") or "").strip()
        instructions = [str(i).strip() for i in (data.get("instructions") or []) if str(i).strip()]
        if not instructions:
            return None

        log.info(
            "🪄 Small LLM built mode spec '%s' from '%s' — %d step(s): %s",
            name, description, len(instructions), instructions,
        )
        return {"name": name, "description": desc, "instructions": instructions}

    def create_mode_from_description(self, description: str) -> dict:
        """
        Turn a free-form natural-language description into a fully-formed custom
        mode using the small/fast LLM, then create (or update) it.

        The small LLM extracts:
          - a short mode name (e.g. "Work Mode")
          - a friendly one-line description
          - a list of atomic, plain-English instructions Voxa can execute

        Works for both explicit descriptions ("create a work mode that opens VS
        Code, turns on do not disturb and sets brightness to full") and vague ones
        ("make me a focus mode"), where the LLM infers sensible default actions.

        Args:
            description: The raw user command describing the desired mode.

        Returns:
            Result dict with success status and message (same shape as create_mode).
        """
        spec = self.generate_mode_spec(description)
        if not spec:
            return {
                "success": False,
                "message": "I couldn't understand that mode description. Try naming a mode and what it should do.",
            }

        name = spec["name"]
        desc = spec["description"]
        instructions = spec["instructions"]

        # Never silently clobber an existing mode's carefully-built steps. If one
        # with this name already exists, refuse and point the user at editing it.
        existing = self._find_by_trigger(name.lower().strip())
        if existing:
            return {
                "success": False,
                "message": (
                    f"A mode called '{existing.name}' already exists. "
                    f"Say 'edit {existing.name}' to change it, or delete it first."
                ),
                "created": False,
                "mode": existing.to_dict(),
            }

        result = self.create_mode(name=name, instructions=instructions, description=desc)
        result["created"] = result.get("success", False)
        return result

    # ── Activation ────────────────────────────────────────────────────────────

    def activate_mode(self, mode: Mode | str) -> dict:
        """
        Activate a mode: parse each English instruction through the LLM,
        then execute the combined action plan via the dispatcher.

        Args:
            mode: A Mode object or mode name string.

        Returns:
            Result dict with overall success and per-step results.
        """
        from voxa.intelligence.intent_parser import Action, ActionPlan
        from voxa.actions.dispatcher import execute_plan

        if isinstance(mode, str):
            mode_name = mode
            mode = self._find_by_trigger(mode.lower().strip())
            if not mode:
                return {"success": False, "message": f"Mode '{mode_name}' not found."}

        log.info("🎯 Activating mode: '%s' (%d instructions, %d pre-compiled actions)", mode.name, len(mode.instructions), len(mode.actions))

        # Check if we have pre-compiled actions
        actions_dict = mode.actions
        if not actions_dict:
            # Fallback to parse and save on the fly
            log.info("🔮 Pre-compiled actions not found. Compiling now...")
            try:
                actions_dict = self._parse_instructions(mode.instructions)
                mode.actions = actions_dict
                self._save()
            except Exception as e:
                log.error("Failed to parse instructions on activation: %s", e)
                actions_dict = []

        if not actions_dict:
            return {
                "success": False,
                "message": f"Could not parse any instructions for mode '{mode.name}'.",
            }

        # Convert action dicts to pydantic Action objects
        actions = []
        for a_dict in actions_dict:
            try:
                actions.append(Action.model_validate(a_dict))
            except Exception as e:
                log.error("Failed to validate action dict %s: %s", a_dict, e)

        if not actions:
            return {
                "success": False,
                "message": "Failed to load structured actions.",
            }

        # Build combined plan
        combined_plan = ActionPlan(
            thought=f"Executing custom mode: {mode.name}",
            actions=actions,
            confirmation=mode.description,
        )

        # Execute
        results = execute_plan(combined_plan)

        success_count = sum(1 for r in results if r.get("success", False))
        total = len(results)

        return {
            "success": success_count == total,
            "message": f"Mode '{mode.name}' activated — {success_count}/{total} steps completed.",
            "results": results,
            "success_count": success_count,
            "total": total,
        }

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _find_by_trigger(self, trigger: str) -> Mode | None:
        """Find a mode by its trigger string (case-insensitive) with fuzzy fallback."""
        trigger = trigger.lower().strip()
        
        # 1. Exact Match
        for mode in self.modes:
            if mode.trigger == trigger or mode.name.lower().strip() == trigger:
                return mode
                
        # 2. Fuzzy Match (Levenshtein Distance)
        best_mode = None
        min_distance = 999
        
        def _lev_dist(s1: str, s2: str) -> int:
            if len(s1) < len(s2):
                return _lev_dist(s2, s1)
            if len(s2) == 0:
                return len(s1)
            previous_row = range(len(s2) + 1)
            for i, c1 in enumerate(s1):
                current_row = [i + 1]
                for j, c2 in enumerate(s2):
                    insertions = previous_row[j + 1] + 1
                    deletions = current_row[j] + 1
                    substitutions = previous_row[j] + (c1 != c2)
                    current_row.append(min(insertions, deletions, substitutions))
                previous_row = current_row
            return previous_row[-1]

        for mode in self.modes:
            # Check against both trigger and name
            for candidate in [mode.trigger, mode.name.lower().strip()]:
                dist = _lev_dist(trigger, candidate)
                if dist < min_distance:
                    min_distance = dist
                    best_mode = mode

        # Determine if the distance is within tolerance
        if best_mode is not None:
            trigger_len = len(trigger)
            tolerance = 1
            if trigger_len >= 10:
                tolerance = 3
            elif trigger_len >= 5:
                tolerance = 2
                
            if min_distance <= tolerance:
                log.info("🎯 Fuzzy matched mode: '%s' ≈ '%s' (dist: %d, tolerance: %d)", trigger, best_mode.name, min_distance, tolerance)
                return best_mode
                
        return None

    def get_mode_names_for_prompt(self) -> str:
        """
        Return a formatted string of mode names for the LLM system prompt.
        This helps the LLM know which modes exist so it can generate
        ACTIVATE_MODE actions.
        """
        if not self.modes:
            return ""
        names = [f'"{m.name}" (trigger: "{m.trigger}")' for m in self.modes]
        return "User-defined modes: " + ", ".join(names)


# Singleton instance
mode_manager = ModeManager()
