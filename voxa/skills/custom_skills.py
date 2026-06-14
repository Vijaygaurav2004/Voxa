"""
Custom Skills System for Voxa.
Loads user-defined YAML shortcuts and matches them against user input.
Matched skills bypass the LLM entirely — zero latency execution.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional
from voxa.utils.logger import get_logger

log = get_logger("skills")

# Default skills.yaml location next to this file
DEFAULT_SKILLS_PATH = Path(__file__).parent / "skills.yaml"


class SkillManager:
    """Loads and matches custom skills from a YAML file."""

    def __init__(self, skills_path: str | None = None):
        self.skills_path = Path(skills_path) if skills_path else DEFAULT_SKILLS_PATH
        self.skills: list[dict] = []
        self._load()

    def _load(self):
        """Load skills from YAML file. Silently skips if file not found or pyyaml missing."""
        try:
            import yaml
        except ImportError:
            log.warning("pyyaml not installed — custom skills disabled. Run: pip install pyyaml")
            return

        if not self.skills_path.exists():
            log.info("No skills.yaml found at %s — custom skills disabled", self.skills_path)
            return

        try:
            with open(self.skills_path, "r") as f:
                data = yaml.safe_load(f)
            self.skills = data.get("skills", []) if data else []
            log.info("✅ Loaded %d custom skill(s) from %s", len(self.skills), self.skills_path)
            for skill in self.skills:
                log.debug("  Skill: '%s' → trigger: '%s'", skill.get("name"), skill.get("trigger"))
        except Exception as e:
            log.error("Failed to load skills.yaml: %s", e)

    def reload(self):
        """Reload skills from disk."""
        self.skills = []
        self._load()

    def match_skill(self, user_input: str) -> Optional[dict]:
        """
        Check if user input matches any defined skill trigger.

        Matching is case-insensitive and supports simple wildcard with *.

        Args:
            user_input: The raw user command string.

        Returns:
            The matched skill dict, or None if no match.
        """
        lower_input = user_input.lower().strip()

        for skill in self.skills:
            trigger = skill.get("trigger", "").lower().strip()
            if not trigger:
                continue

            # Support wildcard * in trigger
            if "*" in trigger:
                pattern = re.escape(trigger).replace(r"\*", ".*")
                if re.fullmatch(pattern, lower_input):
                    log.info("✨ Skill matched: '%s' → '%s'", user_input, skill.get("name"))
                    return skill
            else:
                # Exact or contains match
                if lower_input == trigger or lower_input.startswith(trigger):
                    log.info("✨ Skill matched: '%s' → '%s'", user_input, skill.get("name"))
                    return skill

        return None

    def get_skill_plan(self, skill: dict) -> Optional["ActionPlan"]:
        """
        Convert a matched skill's action list to a Voxa ActionPlan.

        Args:
            skill: The skill dict from skills.yaml.

        Returns:
            The parsed ActionPlan, or None if no valid actions found.
        """
        from voxa.intelligence.intent_parser import ActionPlan

        raw_actions = skill.get("actions", [])
        parsed_actions = []

        for raw in raw_actions:
            try:
                action_obj = _parse_skill_action(raw)
                if action_obj:
                    parsed_actions.append(action_obj)
            except Exception as e:
                log.error("Failed to parse skill action %s: %s", raw, e)

        if not parsed_actions:
            return None

        return ActionPlan(
            thought=f"Executing custom skill: {skill.get('name')}",
            actions=parsed_actions,
            confirmation=skill.get("description", f"Running {skill.get('name')}"),
        )

    def execute_skill(self, skill: dict) -> list[dict]:
        """
        Execute a matched skill's action list.
        Actions are converted to Voxa ActionPlan format and dispatched.

        Args:
            skill: The skill dict from skills.yaml.

        Returns:
            List of result dicts from each action.
        """
        from voxa.actions.dispatcher import execute_plan

        plan = self.get_skill_plan(skill)
        if not plan:
            return [{"success": False, "message": f"Skill '{skill.get('name')}' has no valid actions"}]

        return execute_plan(plan)

    @property
    def skill_count(self) -> int:
        return len(self.skills)

    def list_skills(self) -> list[str]:
        """Return list of skill names."""
        return [s.get("name", "unnamed") for s in self.skills]


def _parse_skill_action(raw: dict) -> "Action | None":
    """Convert a raw YAML action dict to an Action object."""
    from voxa.intelligence.intent_parser import Action, ActionType

    if "open_app" in raw:
        return Action(action=ActionType.OPEN_APP, app=raw["open_app"], description=f"Open {raw['open_app']}")
    if "close_app" in raw:
        return Action(action=ActionType.CLOSE_APP, app=raw["close_app"], description=f"Close {raw['close_app']}")
    if "open_url" in raw:
        return Action(action=ActionType.OPEN_URL, url=raw["open_url"], description=f"Open {raw['open_url']}")
    if "search" in raw:
        return Action(action=ActionType.BROWSER_SEARCH, query=raw["search"], description=f"Search: {raw['search']}")
    if "type_text" in raw:
        return Action(action=ActionType.TYPE_TEXT, text=raw["type_text"], description=f"Type: {raw['type_text'][:30]}")
    if "keystroke" in raw:
        return Action(action=ActionType.KEYSTROKE, keys=raw["keystroke"], description=f"Press {raw['keystroke']}")
    if "shell" in raw:
        return Action(action=ActionType.SHELL_COMMAND, command=raw["shell"], description=f"Run: {raw['shell'][:30]}")
    if "wait" in raw:
        return Action(action=ActionType.WAIT, delay_seconds=float(raw["wait"]), description=f"Wait {raw['wait']}s")
    if "speak" in raw:
        return Action(action=ActionType.SPEAK, text=raw["speak"], description=f"Say: {raw['speak'][:30]}")
    if "screenshot" in raw:
        return Action(action=ActionType.SCREENSHOT, description="Take a screenshot")
    if "play_youtube" in raw:
        return Action(action=ActionType.PLAY_YOUTUBE, query=raw["play_youtube"], description=f"Play on YouTube: {raw['play_youtube']}")

    log.warning("Unknown skill action: %s", raw)
    return None


# Singleton instance
skill_manager = SkillManager()
