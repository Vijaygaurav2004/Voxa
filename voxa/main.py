"""
Voxa — Main Entry Point.
Orchestrates the full pipeline: Voice → Transcribe → Intent → Execute → Feedback.
Supports both hotkey activation and wake word detection.
"""
from __future__ import annotations

import sys
import os
import time
import signal
import threading
import subprocess
from typing import Optional

from voxa.config import config
from voxa.utils.logger import get_logger
from voxa.utils.permissions import ensure_permissions
from voxa.voice.capture import VoiceCapture, list_input_devices, print_device_table, get_default_input_device
from voxa.voice.transcribe import transcribe_with_retry
from voxa.voice.tts import speak_confirmation, speak_error, stop_speaking, speak, set_speaking_hooks as set_tts_hooks
from voxa.voice.wake_word import WakeWordListener
from voxa.intelligence.intent_parser import parse_intent_with_retry, is_simple_command
from voxa.intelligence.context import SessionContext, CommandHistory
from voxa.actions.dispatcher import execute_plan
from voxa.actions import timers as timer_module
from voxa.feedback.overlay import VoxaOverlay
from voxa.skills.custom_skills import skill_manager

log = get_logger("main")

# Suppress SIGABRT from broken system libraries (e.g. old pynput builds).
# We handle it gracefully instead of crashing.
signal.signal(signal.SIGABRT, lambda *_: None)

# ─── ASCII Art Banner ────────────────────────────────────────────────────────────

BANNER = """
\033[36m
 ██╗   ██╗ ██████╗ ██╗  ██╗ █████╗
 ██║   ██║██╔═══██╗╚██╗██╔╝██╔══██╗
 ██║   ██║██║   ██║ ╚███╔╝ ███████║
 ╚██╗ ██╔╝██║   ██║ ██╔██╗ ██╔══██║
  ╚████╔╝ ╚██████╔╝██╔╝ ██╗██║  ██║
   ╚═══╝   ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝
\033[0m
\033[90m  Voice Operating Layer for macOS  v0.1.0\033[0m
"""


class Voxa:
    """
    Main Voxa orchestrator.
    Manages the full pipeline from voice capture to action execution.
    """

    def __init__(self, enable_overlay: bool = True, text_only: bool = False):
        self.capture = VoiceCapture()
        self.context = SessionContext()
        self.history = CommandHistory()
        self.overlay: Optional[VoxaOverlay] = None
        self.text_only = text_only
        self._running = False
        self._hotkey_listener = None
        self._wake_listener: Optional[WakeWordListener] = None
        self._command_lock = threading.Lock()

        if enable_overlay:
            try:
                self.overlay = VoxaOverlay()
            except Exception as e:
                log.warning("Could not initialize overlay: %s", e)

    def start(self):
        """Start Voxa — display banner, check permissions, begin listening."""
        print(BANNER)

        # Validate configuration
        errors = config.validate()
        if errors:
            for error in errors:
                log.error("Config error: %s", error)
            print("\n❌ Fix the above errors and restart Voxa.")
            sys.exit(1)

        # Check macOS permissions
        log.info("Checking macOS permissions...")
        if not ensure_permissions():
            print("\n⚠️  Grant the required permissions and restart Voxa.")
            sys.exit(1)

        log.info("✅ All permissions granted")

        # Register TTS function with timer module so timers can speak
        timer_module.set_speak_fn(lambda text: speak_confirmation(text))
        log.info("⏰ Timer TTS hook registered")

        # Start web dashboard (background thread)
        if config.DASHBOARD_ENABLED:
            try:
                from voxa.dashboard.server import start_dashboard
                start_dashboard(background=True)
                print(f"  🌐 Dashboard: http://localhost:{config.DASHBOARD_PORT}")
            except Exception as e:
                log.warning("Dashboard could not start: %s", e)

        # Start overlay
        if self.overlay:
            self.overlay.start()

        # Setup signal handlers
        signal.signal(signal.SIGINT, self._handle_shutdown)
        signal.signal(signal.SIGTERM, self._handle_shutdown)

        self._running = True

        if self.text_only:
            # ── Text-only testing mode ────────────────────────────────────────
            print("\n" + "=" * 55)
            print("  ⌨️   \033[1mText-only mode\033[0m — type commands below")
            print("  🛑  Press \033[1mCtrl+C\033[0m or type \033[1mquit\033[0m to exit")
            print("=" * 55 + "\n")
            self._run_interactive_loop()
            return

        # ── Full mode: hotkey + wake word + text ──────────────────────────────
        # Start hotkey listener
        self._start_hotkey_listener()

        # Start wake word listener (background always-on)
        self._start_wake_word_listener()

        # Show active microphone
        self._print_active_mic()

        # Show loaded skills
        if skill_manager.skill_count > 0:
            print(f"  ✨ Skills: {skill_manager.skill_count} custom skill(s) loaded")

        wake_word_display = config.WAKE_WORD.title()
        print("\n" + "=" * 55)
        print(f"  🎤  Press \033[1m⌘+Shift+V\033[0m to speak a command")
        print(f"  🗣️   Or say \033[1m\"{wake_word_display}\"\033[0m to activate")
        print("  ⌨️   Or type a command and press Enter")
        if config.CONVERSATION_MODE:
            print(f"  💬  Conversation mode ON ({config.FOLLOWUP_WINDOW_SECONDS}s follow-up window)")
        print("  🛑  Press \033[1mCtrl+C\033[0m to quit")
        print("=" * 55 + "\n")

        self._run_interactive_loop()

    def _run_interactive_loop(self):
        """
        Main loop — allows both voice and text input.
        Text input is useful for testing without a microphone.
        """
        while self._running:
            try:
                # Allow text input as fallback
                user_input = input("\033[36mvoxa>\033[0m ").strip()

                if not user_input:
                    continue

                if user_input.lower() in ("quit", "exit", "q"):
                    self._handle_shutdown()
                    break

                if user_input.lower() == "voice":
                    # Trigger voice capture
                    self._handle_voice_command()
                    continue

                if user_input.lower() == "stats":
                    self._show_stats()
                    continue

                if user_input.lower() == "history":
                    self._show_history()
                    continue

                if user_input.lower() == "help":
                    self._show_help()
                    continue

                if user_input.lower() == "devices":
                    self._show_devices()
                    continue

                # Handle: 'device <index>' to switch mic
                if user_input.lower().startswith("device "):
                    self._switch_device(user_input.split(None, 1)[1].strip())
                    continue

                if user_input.lower() == "skills":
                    self._show_skills()
                    continue

                # Process text command — same pipeline as voice, speaks result back
                self._process_command(user_input)

            except EOFError:
                break
            except KeyboardInterrupt:
                self._handle_shutdown()
                break

    def _handle_voice_command(self, inline_command: Optional[str] = None):
        """
        Capture voice input and process the command.

        Args:
            inline_command: If the user said "Hey Voxa open Chrome" in one breath,
                            this is the "open Chrome" part already extracted.
                            If None, we listen for a fresh command.
        """
        # Prevent simultaneous command processing from wake + hotkey
        if not self._command_lock.acquire(blocking=False):
            log.debug("Command already in progress — ignoring duplicate trigger")
            return

        try:
            # If we got an inline command (e.g. "Hey Voxa open Chrome")
            if inline_command:
                print("\n🎯 \033[1mWake word detected!\033[0m")
                print("📝 Command: \"\033[1m{}\033[0m\"\n".format(inline_command))
                self._process_command(inline_command)
                return

            if self.overlay:
                self.overlay.set_state("listening")

            print("\n🎤 \033[1mListening...\033[0m (speak your command)\n")

            audio = self.capture.record_until_silence(
                on_speech_start=lambda: print("🗣️  Speech detected — recording...")
            )

            if not audio:
                print("❌ No speech detected. Try again.\n")
                if self.overlay:
                    self.overlay.set_state("idle")
                return

            # Transcribe
            if self.overlay:
                self.overlay.set_state("thinking", "Transcribing...")

            text = transcribe_with_retry(audio)

            if not text:
                print("❌ Could not transcribe audio. Try again.\n")
                speak_error("I didn't catch that. Please try again.")
                if self.overlay:
                    self.overlay.set_state("error", "Transcription failed")
                return

            print("📝 You said: \"\033[1m{}\033[0m\"\n".format(text))

            # Strip wake word if user accidentally triggered hotkey after saying it
            lower = text.lower().strip()
            if lower.startswith(config.WAKE_WORD):
                text = text[len(config.WAKE_WORD):].strip().lstrip(".,!? ")
                if not text:
                    speak_confirmation("Yes? What can I do for you?")
                    audio2 = self.capture.record_until_silence(
                        on_speech_start=lambda: print("🗣️  Listening for command...")
                    )
                    if audio2:
                        text = transcribe_with_retry(audio2) or ""
                    if not text:
                        return
                    print("📝 Command: \"\033[1m{}\033[0m\"\n".format(text))

            self._process_command(text)

        finally:
            self._command_lock.release()
            # Resume wake word listener after command finishes
            if self._wake_listener:
                self._wake_listener.resume()

    def _process_command(self, user_input: str):
        """
        Full pipeline: Check skills → Parse intent → Execute plan → Update context → Feedback.
        """
        start_time = time.time()

        # 0. Check custom skills FIRST (zero latency, no LLM call)
        skill = skill_manager.match_skill(user_input)
        if skill:
            print(f"\n✨ Skill matched: \033[1m{skill.get('name')}\033[0m")
            speak_confirmation(skill.get("description", f"Running {skill.get('name')}"))
            if self.overlay:
                self.overlay.set_state("executing", skill.get("description", ""))
            results = skill_manager.execute_skill(skill)
            elapsed = time.time() - start_time
            success_count = sum(1 for r in results if r.get("success"))
            summary = f"✅ Skill '{skill.get('name')}' done ({elapsed:.1f}s)" if success_count == len(results) else f"⚠️  Skill partially done ({elapsed:.1f}s)"
            print(f"\n{summary}\n")
            if self.overlay:
                self.overlay.set_state("done", "Complete!")
            return

        # 1. Parse intent
        if self.overlay:
            self.overlay.set_state("thinking", "Understanding command...")

        print("\n🧠 Parsing intent...")

        context_str = self.context.get_context_for_llm()
        plan = parse_intent_with_retry(user_input, context=context_str)

        if not plan:
            print("❌ Could not understand the command. Please rephrase.\n")
            speak_error("I couldn't understand that. Could you rephrase?")
            if self.overlay:
                self.overlay.set_state("error", "Could not understand")
            return

        # 2. Announce plan
        print(f"\n💡 Plan: \033[1m{plan.confirmation}\033[0m")
        print(f"   Steps: {len(plan.actions)}")
        for i, action in enumerate(plan.actions):
            print(f"   {i+1}. {action.action.value}: {action.description}")
        print()

        speak_confirmation(plan.confirmation)

        # 3. Check for dangerous commands requiring voice confirmation
        needs_confirm = any(
            getattr(a, 'requires_confirmation', False) or
            (a.action.value == 'shell_command' and a.command)
            for a in plan.actions
        )
        # We detect dangerous at execution time via shell.py, handled in step 4

        # 4. Execute
        if self.overlay:
            self.overlay.set_state("executing", plan.confirmation)

        def on_step(idx, action, result):
            status = "✅" if result.get("success") else "❌"
            print(f"   {status} Step {idx+1}: {result.get('message', 'Done')}")
            if self.overlay:
                self.overlay.set_state("executing", f"Step {idx+1}/{len(plan.actions)}")

            # Dangerous command voice confirmation
            if result.get("requires_confirmation"):
                speak_confirmation(result["message"])
                print(f"\n⚠️  Type 'confirm' to execute or 'cancel' to abort: ", end="", flush=True)
                try:
                    answer = input().strip().lower()
                    if answer == "confirm":
                        # Re-run without safety check
                        from voxa.actions import shell
                        confirmed_result = shell.execute_command(action.command, confirm_dangerous=False)
                        results_override[idx] = confirmed_result
                        print(f"   ✅ Confirmed: {confirmed_result.get('message', '')}")
                    else:
                        print("   ❌ Cancelled.")
                except Exception:
                    pass

        results_override = {}
        results = execute_plan(plan, on_step=on_step)

        # Apply any overrides from confirmation
        for idx, res in results_override.items():
            if idx < len(results):
                results[idx] = res

        # 5. Summary
        elapsed = time.time() - start_time
        success_count = sum(1 for r in results if r.get("success"))
        total = len(results)

        if success_count == total:
            summary = f"✅ All {total} steps completed successfully ({elapsed:.1f}s)"
            if self.overlay:
                self.overlay.set_state("done", "Complete!")
        else:
            summary = f"⚠️  {success_count}/{total} steps succeeded ({elapsed:.1f}s)"
            if self.overlay:
                self.overlay.set_state("error", f"{total - success_count} steps failed")

        print(f"\n{summary}\n")

        # 6. Update context and history
        actions_dicts = [
            {"action": a.action.value, **{k: v for k, v in a.model_dump().items() if v is not None and k != "action"}}
            for a in plan.actions
        ]
        self.context.add_command(user_input, actions_dicts, summary)
        self.history.record(
            user_input=user_input,
            actions=actions_dicts,
            result=summary,
            duration_ms=int(elapsed * 1000),
            success=success_count == total,
        )

        # 7. Conversation mode — stay listening for follow-up
        if config.CONVERSATION_MODE and self._running:
            self._attempt_followup()


    def _attempt_followup(self):
        """
        Conversation mode: stay listening for a follow-up command for FOLLOWUP_WINDOW_SECONDS.
        If the user speaks within that window, process it without requiring a new wake word.
        """
        from voxa.voice.tts import speak_and_listen
        window = config.FOLLOWUP_WINDOW_SECONDS

        def _listen_for_followup():
            try:
                print(f"\n💬 Listening for follow-up ({window}s)...")
                audio = self.capture.record_until_silence(
                    on_speech_start=lambda: print("🗣️  Follow-up detected...")
                )
                if audio:
                    text = transcribe_with_retry(audio)
                    if text:
                        print(f"📝 Follow-up: \"\033[1m{text}\033[0m\"\n")
                        self._process_command(text)
            except Exception as e:
                log.debug("Follow-up listen error: %s", e)

        speak_and_listen("Anything else?", on_done=_listen_for_followup)

    def _show_skills(self):
        """Display loaded custom skills."""
        skills = skill_manager.skills
        if not skills:
            print("\n✨ No custom skills loaded. Edit voxa/skills/skills.yaml to add some.\n")
            return
        print(f"\n✨ Custom Skills ({len(skills)} loaded):")
        for s in skills:
            print(f"   📌 \033[1m{s.get('name')}\033[0m — trigger: \"{s.get('trigger')}\"")
            actions = s.get('actions', [])
            print(f"      {len(actions)} step{'s' if len(actions) != 1 else ''}")
        print()

    def _start_hotkey_listener(self):
        """
        Start a global hotkey listener for ⌘+Shift+V using PyObjC NSEvent.
        This avoids pynput which crashes (SIGABRT) on macOS 15 build 1506.
        PyObjC is already installed as a dependency and works on all macOS 15 builds.
        """
        try:
            import AppKit
            import Quartz

            # NSEvent modifier flags for Cmd + Shift
            CMD_SHIFT_FLAGS = (
                Quartz.kCGEventFlagMaskCommand
                | Quartz.kCGEventFlagMaskShift
            )
            TARGET_CHAR = "v"

            def _hotkey_thread():
                """Run the NSEvent monitor on its own run loop."""
                # We need an NSApplication run loop for the monitor to fire.
                # Use a minimal NSApp without showing a window.
                app = AppKit.NSApplication.sharedApplication()

                def _handler(event):
                    try:
                        flags = event.modifierFlags()
                        chars = event.charactersIgnoringModifiers()
                        # Check Cmd+Shift are held and key is 'v'
                        has_cmd   = bool(flags & Quartz.kCGEventFlagMaskCommand)
                        has_shift = bool(flags & Quartz.kCGEventFlagMaskShift)
                        is_v      = chars and chars.lower() == TARGET_CHAR
                        if has_cmd and has_shift and is_v:
                            log.info("🔑 Hotkey ⌘+Shift+V activated!")
                            threading.Thread(
                                target=self._handle_voice_command, daemon=True
                            ).start()
                    except Exception as exc:
                        log.debug("Hotkey handler error: %s", exc)
                    return event  # Must return event to pass it through

                mask = AppKit.NSEventMaskKeyDown
                monitor = AppKit.NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
                    mask, _handler
                )
                if monitor is None:
                    log.warning(
                        "Could not install NSEvent global monitor. "
                        "Grant Accessibility permission to Terminal in "
                        "System Settings → Privacy & Security → Accessibility."
                    )
                    return

                log.info("✅ Hotkey listener active (⌘+Shift+V) via NSEvent")
                # Run the current thread's run loop so NSEvent callbacks fire
                AppKit.NSRunLoop.currentRunLoop().runUntilDate_(
                    AppKit.NSDate.distantFuture()
                )

            t = threading.Thread(target=_hotkey_thread, daemon=True)
            t.start()
            self._hotkey_listener = t

        except ImportError:
            log.warning(
                "PyObjC AppKit not available — hotkey disabled. "
                "Use 'voice' command or type commands directly."
            )
        except Exception as e:
            log.warning("Could not start hotkey listener: %s", e)

    def _start_wake_word_listener(self):
        """
        Start the always-on background wake word listener.
        Also registers TTS hooks so the listener mutes itself while Voxa speaks
        (prevents Voxa from hearing its own voice).
        """
        try:
            def on_wake(inline_command=None):
                if not self._running:
                    return
                print("\n")
                # Blocking speak so recording starts AFTER 'Yes?' finishes playing.
                # Non-blocking would cause Voxa to hear its own voice as a command.
                speak("Yes?", blocking=True)
                self._handle_voice_command(inline_command=inline_command)

            self._wake_listener = WakeWordListener(on_wake=on_wake)
            self._wake_listener.start()

            # Register TTS hooks — pause/resume wake listener around every speak() call
            set_tts_hooks(
                on_start=lambda: self._wake_listener.pause() if self._wake_listener else None,
                on_end=lambda: self._wake_listener.resume() if self._wake_listener else None,
            )
            log.info("🔇 TTS mute hooks registered — Voxa won't hear its own voice")

        except Exception as e:
            log.warning("Could not start wake word listener: %s", e)


    def _print_active_mic(self):
        """Print the active microphone device info at startup."""
        dev = get_default_input_device()
        if dev:
            bt_hint = " \033[33m(Bluetooth detected)\033[0m" if any(
                k in dev["name"].lower() for k in ("airpods", "bluetooth", "bt", "wireless", "headset", "bose", "sony", "jabra", "jbl")
            ) else ""
            print(
                "  🎧 Microphone: \033[1m{}\033[0m ({} Hz){}".format(
                    dev["name"], self.capture.capture_rate, bt_hint
                )
            )
            if self.capture.capture_rate != 16000:
                print(
                    "  \033[90m     Audio will be resampled {}Hz → 16kHz for transcription.\033[0m".format(
                        self.capture.capture_rate
                    )
                )
        else:
            print("  ⚠️  No microphone detected")

    def _show_devices(self):
        """List all available audio input devices."""
        print_device_table()
        print("  To switch: type \033[1mdevice <number>\033[0m (e.g. 'device 2')")
        print()

    def _switch_device(self, index_str: str):
        """Switch the active microphone to a specific device index."""
        try:
            idx = int(index_str)
            devices = list_input_devices()
            match = next((d for d in devices if d["index"] == idx), None)
            if match is None:
                print("  ❌ Device #{} not found. Type 'devices' to see available inputs.\n".format(idx))
                return
            self.capture.set_device(idx)
            print("  ✅ Switched to: \033[1m{}\033[0m ({} Hz)\n".format(
                match["name"], match["sample_rate"]
            ))
        except ValueError:
            print("  ❌ Usage: device <number>  (e.g. 'device 2')\n")

    def _show_stats(self):
        """Display usage statistics."""
        stats = self.history.get_stats()
        print("\n📊 Voxa Statistics:")
        print(f"   Total commands:  {stats['total_commands']}")
        print(f"   Successful:      {stats['successful']}")
        print(f"   Failed:          {stats['failed']}")
        print(f"   Success rate:    {stats['success_rate']}")
        print(f"   Avg duration:    {stats['avg_duration_ms']}ms")
        print()

    def _show_history(self):
        """Display recent command history."""
        recent = self.history.get_recent(5)
        if not recent:
            print("\n📜 No commands in history yet.\n")
            return
        print("\n📜 Recent Commands:")
        for entry in reversed(recent):
            status = "✅" if entry["success"] else "❌"
            print(f"   {status} [{entry['timestamp'][:19]}] {entry['user_input']}")
        print()

    def _show_help(self):
        """Display help text."""
        print("""
\033[1m📖 Voxa Commands:\033[0m

  \033[36mVoice Commands (examples):\033[0m
    "Turn volume up / down / set to 50"
    "Enable dark mode"
    "Turn on Do Not Disturb"
    "Set a 10 minute timer to drink water"
    "What's on my screen?"
    "Take a screenshot"
    "Pause Spotify / next track / what's playing?"
    "What's on my calendar today?"
    "Send email to john@example.com about the meeting"
    "What's in my clipboard?"
    "Open Chrome and search for Python tutorials"
    "Play lo-fi music on YouTube"

  \033[36mSystem REPL Commands:\033[0m
    voice          — Activate voice input
    devices        — List available microphones
    device <num>   — Switch to a different microphone
    skills         — List loaded custom skills
    stats          — Show usage statistics
    history        — Show recent commands
    help           — Show this help
    quit           — Exit Voxa

  \033[36mCustom Skills:\033[0m
    Edit voxa/skills/skills.yaml to define your own shortcuts.
    Skills bypass the LLM for instant, zero-latency execution.

  \033[36mDashboard:\033[0m
    Open http://localhost:7429 in your browser to view the
    command history, stats, timers, skills, and config.
""")

    def _handle_shutdown(self, *args):
        """Graceful shutdown."""
        print("\n\n👋 Shutting down Voxa...")
        self._running = False
        stop_speaking()
        if self.overlay:
            self.overlay.stop()
        if self._wake_listener:
            self._wake_listener.stop()
        # Hotkey listener is a daemon thread — it stops automatically on exit
        log.info("Voxa shutdown complete")
        sys.exit(0)


def main():
    """Entry point for Voxa."""
    if "--server" in sys.argv:
        # ── Headless API server mode (Swift ↔ Python bridge) ────────────────
        print(BANNER)
        print("  \033[1m🖥️  Mode: API Server\033[0m (headless)")
        print(f"  🌐 Endpoint: http://{config.API_SERVER_HOST}:{config.API_SERVER_PORT}")
        print(f"  📡 WebSocket: ws://{config.API_SERVER_HOST}:{config.API_SERVER_PORT}/ws/status")
        print("  🛑 Press \033[1mCtrl+C\033[0m to quit")
        print("=" * 55 + "\n")

        from voxa.server import start_api_server
        start_api_server(background=False)
        return

    text_only = "--text" in sys.argv
    voxa = Voxa(
        enable_overlay=("--no-overlay" not in sys.argv) and not text_only,
        text_only=text_only,
    )
    voxa.start()


if __name__ == "__main__":
    main()
