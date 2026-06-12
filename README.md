# Voxa — Native macOS Voice Operating Layer & AI Agent

Voxa is a high-performance, native voice-controlled personal agent for macOS. By combining a premium, hardware-accelerated **SwiftUI frontend** with a robust **Python FastAPI backend**, Voxa achieves near-instant wake-word activation, real-time audio visualization, and absolute control over your Mac's apps, windows, settings, and workflows.

---

## 🏗️ Architecture Overview

Voxa uses a hybrid architecture designed to minimize latency and maximize system integration:

```
                  ┌──────────────────────────────────────────────┐
                  │              SwiftUI Frontend                │
                  │  (Waveforms, Siri-Orb, Voice Capture, UI)    │
                  └──────────────┬────────────────▲──────────────┘
                                 │ HTTP API       │ WebSockets
                                 │ (Port 7430)    │ (Real-time events)
                                 ▼                │
                  ┌───────────────────────────────┴──────────────┐
                  │            FastAPI Backend Bridge            │
                  │  (Intent Parsing, Whisper, Custom Skills)    │
                  └──────────────┬───────────────────────────────┘
                                 │
                                 ▼
                  ┌──────────────────────────────────────────────┐
                  │             macOS System Control             │
                  │ (NSWorkspace, AppleScript, Shell, CGEvent)   │
                  └──────────────────────────────────────────────┘
```

1. **SwiftUI Frontend (UI/Voice/Control Layer)**:
   - Listens for hotkeys (`⌘+Shift+V`) or the wake word (`"hey"`).
   - Renders a floating, glassmorphic overlay containing a real-time animated audio waveform and state-based orb animations (Idle, Listening, Thinking, Executing, Done).
   - Directly executes swift-native actions (e.g. launching/terminating apps, adjusting volume, sending keystrokes) in `< 10ms`.
2. **Python FastAPI Backend (AI/Automation Engine)**:
   - Handles natural language understanding via GPT-4o intent parsing.
   - Performs audio transcription and custom local fallback skills.
   - Hosts background timers, custom integration scripts, and a dedicated Google Chrome control bridge.

---

## ✨ Features

- **Floating Glassmorphic Overlay**: Beautiful native UI featuring real-time microphone level tracking and Siri-style wave animations.
- **Universal App Controller**: Can open, activate, focus, or terminate any application on macOS with staged graceful timeouts, falling back to force termination if necessary.
- **Google Chrome Suite**: Dedicated AppleScript integration to manage Chrome windows, tabs (open, close, navigate, pin, switch, close duplicates, bulk tabs), dev tools, bookmarks, and histories natively.
- **Enhanced WhatsApp Integration**: Smart contact searching, message typing, and thread replying. If a contact cannot be found in your WhatsApp list, Voxa will announce it aloud with voice feedback.
- **System Preference Pane Routing**: Instantly open specific macOS System Settings panes (Wi-Fi, Bluetooth, Displays, Keyboard, battery, etc.) via URL extensions.
- **Custom Skills**: Define custom commands in YAML/JSON to build instant macro actions.

---

## 🚀 Getting Started

### 📋 Prerequisites
- **macOS 13.0+** (Ventura or later)
- **Xcode 14.0+** / Swift Package Manager (to build the frontend)
- **Python 3.11+**
- **OpenAI API Key** (for LLM intent parsing and voice transcription)

---

### 🔧 Installation & Setup

#### 1. Set Up Python Backend
Create a virtual environment, install dependencies, and configure environment variables:

```bash
# Clone the repository
git clone https://github.com/Vijaygaurav2004/Voxa.git
cd Voxa

# Setup virtual environment
python3 -m venv venv
source venv/bin/activate

# Install required Python packages
pip install -r requirements.txt
```

Create a `.env` file in the root folder:
```bash
cp .env.example .env
```
Open `.env` and fill in your API credentials:
```env
OPENAI_API_KEY=your_openai_api_key_here
API_SERVER_PORT=7430
WAKE_WORD=hey
```

#### 2. Build and Launch the Swift Frontend
Voxa's frontend is a Swift Package. You can run the setup script or build it using Xcode/Swift CLI.

To compile and launch from the terminal:
```bash
cd VoxaApp
swift run
```

---

### ⚙️ macOS System Permissions
For Voxa to interact with other applications and capture voice commands, macOS requires specific permission grants:
- **Accessibility**: Required to control applications, type keystrokes, and interact with menus.
- **Microphone**: Required to capture audio commands.
- **Speech Recognition**: Required for local speech processing.

To prompt system permission dialogs, run:
```bash
chmod +x scripts/setup_permissions.sh
./scripts/setup_permissions.sh
```
Or grant permissions manually in **System Settings > Privacy & Security**.

---

## 🗣️ How to Use

### Triggering Voxa
- **Voice Wake-Word**: Simply say `"hey"` aloud.
- **Keyboard Shortcut**: Press **`⌘+Shift+V`** to summon the floating input bar.

### Example Voice Commands

#### 📁 System & Settings
- *"Open system settings"*
- *"Turn Wi-Fi off"* / *"Turn Wi-Fi on"*
- *"Open displays settings"*
- *"Set volume to 50%"*

#### 🌐 Google Chrome
- *"Open Chrome and search for fastAPI documentation"*
- *"Open a new tab to github.com"*
- *"Close all duplicate tabs in Chrome"*
- *"Switch to the next tab"*
- *"Reopen the last closed tab"*

#### 💬 Messaging & Social
- *"Open WhatsApp and send hey to Tarun"*
- *"Reply to John saying I'll be there in 5 minutes"*
- *"Open iMessage and text Mom that I am heading home"*

#### ⏱️ Timers & Utilities
- *"Set a timer for 10 minutes labeled pasta"*
- *"Show my active timers"*
- *"Cancel the pasta timer"*
