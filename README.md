# Voxa — Voice Operating Layer for macOS

A production-grade, fully autonomous voice-controlled assistant that executes real system-level actions on macOS via natural language.

## Quick Start

### 1. Setup Environment

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure API Key

```bash
cp .env.example .env
# Edit .env and add your OpenAI API key
```

### 3. Grant macOS Permissions

```bash
chmod +x scripts/setup_permissions.sh
./scripts/setup_permissions.sh
```

### 4. Run Voxa

```bash
# Interactive mode (text + voice)
python -m voxa.main

# Without visual overlay
python -m voxa.main --no-overlay

# Demo mode (guided walkthrough)
python scripts/demo.py
```

## Usage

### Text Commands
Type any natural language command at the `voxa>` prompt:

```
voxa> Open Chrome and search for Python tutorials
voxa> Play lo-fi music on YouTube
voxa> Open my Downloads folder
voxa> Close Safari
```

### Voice Commands
- Press **⌘+Shift+V** to activate the microphone
- Say **"Hey Voxa"** followed by your command
- Type `voice` at the prompt to activate microphone

### System Commands
| Command | Description |
|---------|-------------|
| `voice` | Activate voice input |
| `stats` | Show usage statistics |
| `history` | Show recent commands |
| `help` | Show help text |
| `quit` | Exit Voxa |

## Supported Actions

| Action | Example |
|--------|---------|
| Open apps | "Open Chrome", "Launch Finder" |
| Close apps | "Close Safari", "Quit Terminal" |
| Open URLs | "Go to github.com" |
| Search Google | "Search for React tutorials" |
| Search YouTube | "Search YouTube for coding music" |
| Play videos | "Play lo-fi music on YouTube" |
| File operations | "Open my Downloads folder" |
| Type text | "Type hello world" |
| Keyboard shortcuts | "Press Cmd+T" |
| Shell commands | "Run ls in terminal" |

## Architecture

```
Voice Input → VAD → Whisper API → GPT-4o Intent Parser → Action Dispatcher → macOS APIs
                                                                              ↓
                                                              AppleScript / Shell / Accessibility
```

## Requirements

- macOS 13+ (Ventura or later)
- Python 3.11+
- OpenAI API key
- Microphone access
- Accessibility permission (for UI automation)
