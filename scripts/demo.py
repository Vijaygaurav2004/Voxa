"""
Voxa Demo Script.
Demonstrates the intent parsing and action execution pipeline
using text input (no microphone required).
"""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from voxa.config import config
from voxa.intelligence.intent_parser import parse_intent_with_retry
from voxa.actions.dispatcher import execute_plan
from voxa.intelligence.context import SessionContext

# Demo commands to test
DEMO_COMMANDS = [
    "Open Google Chrome",
    "Search for Python tutorials on YouTube",
    "Open the Downloads folder",
    "Open Safari and go to github.com",
    "Close Safari",
]


def run_demo():
    """Run through demo commands showing the full pipeline."""
    print("\n" + "=" * 60)
    print("  🎯 VOXA DEMO — Intent Parsing + Execution")
    print("=" * 60)

    # Validate API key
    errors = config.validate()
    if errors:
        print(f"\n❌ {errors[0]}")
        print("   Copy .env.example to .env and add your OpenAI API key.")
        sys.exit(1)

    context = SessionContext()

    for i, command in enumerate(DEMO_COMMANDS):
        print(f"\n{'━' * 60}")
        print(f"  Demo {i + 1}/{len(DEMO_COMMANDS)}")
        print(f"  Command: \"\033[1m{command}\033[0m\"")
        print(f"{'━' * 60}")

        # Parse intent
        print("\n  🧠 Parsing intent...")
        plan = parse_intent_with_retry(command, context=context.get_context_for_llm())

        if not plan:
            print("  ❌ Failed to parse intent")
            continue

        print(f"  💡 Plan: {plan.confirmation}")
        print(f"  📋 Steps ({len(plan.actions)}):")
        for j, action in enumerate(plan.actions):
            print(f"     {j+1}. [{action.action.value}] {action.description}")

        # Ask before executing
        response = input(f"\n  ▶️  Execute this plan? (y/n/skip): ").strip().lower()

        if response == "y":
            print("\n  ⚡ Executing...")
            results = execute_plan(plan)

            for result in results:
                status = "✅" if result.get("success") else "❌"
                print(f"     {status} {result.get('message', 'Done')}")

            # Update context
            actions_dicts = [a.model_dump() for a in plan.actions]
            context.add_command(command, actions_dicts, "completed")
        elif response == "skip":
            continue
        else:
            print("  ⏭️  Skipped execution")

    print(f"\n{'=' * 60}")
    print("  ✅ Demo complete!")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    run_demo()
