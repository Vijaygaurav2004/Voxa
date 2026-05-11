#!/bin/bash
# Voxa — macOS Permission Setup Script
# Guides the user through granting required permissions.

set -e

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║         🎙️  VOXA — Permission Setup             ║"
echo "╠══════════════════════════════════════════════════╣"
echo "║  Voxa requires the following macOS permissions:  ║"
echo "║                                                  ║"
echo "║  1. 🎤 Microphone Access                         ║"
echo "║  2. ♿ Accessibility Access                       ║"
echo "║  3. 🤖 Automation Access (per-app, auto-prompted)║"
echo "╚══════════════════════════════════════════════════╝"
echo ""

# Check which terminal we're running in
TERMINAL_APP=$(osascript -e 'tell application "System Events" to get name of first application process whose frontmost is true' 2>/dev/null || echo "Terminal")
echo "📌 You are running from: $TERMINAL_APP"
echo "   This app needs the permissions listed above."
echo ""

# Step 1: Microphone
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Step 1: Microphone Access"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  Go to: System Settings → Privacy & Security → Microphone"
echo "  Enable: $TERMINAL_APP"
echo ""
read -p "  Press Enter to open Microphone settings..." _
open "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone"
echo "  ✅ Opened Microphone settings"
echo ""

# Step 2: Accessibility
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Step 2: Accessibility Access"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  Go to: System Settings → Privacy & Security → Accessibility"
echo "  Click '+' and add: $TERMINAL_APP"
echo ""
read -p "  Press Enter to open Accessibility settings..." _
open "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
echo "  ✅ Opened Accessibility settings"
echo ""

# Step 3: Note about Automation
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Step 3: Automation Access"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  Automation permissions are granted per-app."
echo "  When Voxa first tries to control an app (e.g., Chrome),"
echo "  macOS will show a dialog asking for permission."
echo "  Just click 'OK' / 'Allow' when prompted."
echo ""

# Done
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "🎉 Setup complete! You can now run Voxa:"
echo ""
echo "   python -m voxa.main"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
