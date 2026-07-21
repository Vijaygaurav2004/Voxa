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
        """Parse plain English instructions into structured actions using the LLM."""
        from voxa.intelligence.intent_parser import parse_intent_with_retry
        
        all_actions = []
        for inst in instructions:
            plan = parse_intent_with_retry(inst)
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

    # ── Trigger Matching ──────────────────────────────────────────────────────

    def match_mode(self, user_input: str) -> Mode | None:
        """
        Check if user input matches any mode trigger.
        Matching is case-insensitive. Supports exact match and common
        activation phrases like "activate X", "switch to X", "enable X".

        Args:
            user_input: The raw user command string.

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

        return None

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
