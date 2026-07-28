import Foundation
import SwiftUI
import AppKit
import Combine
import AVFoundation
import Speech

/// Main Voxa orchestrator — manages the Python backend process,
/// coordinates voice → intent → execute pipeline.
@MainActor
final class VoxaEngine: ObservableObject {
    static let shared = VoxaEngine()

    private let config = VoxaConfig.shared
    private let bridge = PythonBridge.shared
    private let router = ActionRouter.shared
    private let state = VoxaState.shared

    @Published var isRunning = false

    private var backendProcess: Process?
    private var voiceCapture: VoiceCapture?
    private var meetingCapture: MeetingCapture?
    private var systemAudioCapture: SystemAudioCapture?
    private var wakeWordListener: WakeWordListener?
    private var hotkeyManager: HotkeyManager?
    private var webSocketTask: URLSessionWebSocketTask?

    private init() {
        // Start everything on init
        Task {
            await start()
        }
    }

    nonisolated private func logMessage(_ message: String) {
        appLog("[Engine] \(message)")
    }

    // MARK: - Lifecycle

    private func requestPermissionsIfNeeded() async {
        let audioStatus = AVCaptureDevice.authorizationStatus(for: .audio)
        let speechStatus = SFSpeechRecognizer.authorizationStatus()
        
        if audioStatus == .notDetermined || speechStatus == .notDetermined {
            logMessage("⚠️ Permissions not determined. Activating application to display prompts...")
            await MainActor.run {
                NSApp.activate(ignoringOtherApps: true)
            }
            
            // Request microphone access
            let micGranted = await withCheckedContinuation { (continuation: CheckedContinuation<Bool, Never>) in
                AVCaptureDevice.requestAccess(for: .audio) { granted in
                    continuation.resume(returning: granted)
                }
            }
            
            // Request speech recognition access
            let speechGranted = await withCheckedContinuation { (continuation: CheckedContinuation<Bool, Never>) in
                SFSpeechRecognizer.requestAuthorization { status in
                    continuation.resume(returning: status == .authorized)
                }
            }
            
            logMessage("🔑 Permissions result: Microphone=\(micGranted), Speech=\(speechGranted)")
        }
    }

    func start() async {
        guard !isRunning else { return }
        isRunning = true

        logMessage("🚀 Voxa Engine starting...")

        // Request permissions first
        await requestPermissionsIfNeeded()

        // First-run onboarding (replaces the old blocking key alert).
        if VoxaConfig.readAPIKey() == nil {
            // No key yet — the onboarding's key step must complete before the
            // backend can start. Suspends until a key is saved (or the user quits).
            let ok = await OnboardingManager.shared.runFirstLaunch(requireKey: true)
            guard ok, VoxaConfig.readAPIKey() != nil else {
                logMessage("Onboarding closed without an API key — quitting.")
                NSApplication.shared.terminate(nil)
                return
            }
        } else if !OnboardingManager.shared.isComplete {
            // Key already present (dev .env, or a future embedded key) — show the
            // friendly first-run onboarding non-blocking; backend starts normally.
            OnboardingManager.shared.presentFirstLaunch(requireKey: false)
        }

        // 1. Check if Python backend is already running
        let alreadyRunning = await bridge.healthCheck()
        if alreadyRunning {
            logMessage("ℹ️ Python backend is already running. Skipping launch.")
        } else {
            logMessage("🐍 Launching new Python backend...")
            launchBackend()
        }

        // 2. Wait for backend to be ready
        let ready = await bridge.waitForBackend(maxAttempts: 30, intervalSeconds: 1.0)
        state.isBackendReady = ready

        if !ready {
            logMessage("❌ Could not connect to Python backend")
            state.setState(.error, message: "Backend not available")
            return
        }

        // 3. Start voice capture
        voiceCapture = VoiceCapture()

        // 4. Start wake word listener
        wakeWordListener = WakeWordListener { [weak self] inlineCommand in
            Task { @MainActor in
                await self?.handleWakeWord(inlineCommand: inlineCommand)
            }
        }
        wakeWordListener?.start()

        // 5. Start hotkey listener
        hotkeyManager = HotkeyManager { [weak self] in
            Task { @MainActor in
                await self?.handleHotkey()
            }
        }
        hotkeyManager?.start()

        state.setState(.idle, message: "Ready")
        logMessage("✅ Voxa Engine ready")

        // 6. Connect WebSocket for real-time status updates
        connectWebSocket()
    }

    func stop() {
        isRunning = false
        meetingCapture?.stop()
        meetingCapture = nil
        systemAudioCapture?.stop()
        systemAudioCapture = nil
        wakeWordListener?.stop()
        hotkeyManager?.stop()
        disconnectWebSocket()
        terminateBackend()
        print("👋 Voxa Engine stopped")
    }

    // MARK: - Command Processing
 
    /// Process a text command through the full pipeline.
    func processCommand(_ text: String) async {
        logMessage("💬 Processing command: \"\(text)\"")
        state.addCommand(text)
        state.setState(.thinking, message: "Understanding: \"\(text)\"")
 
        do {
            // Get context for follow-up resolution
            logMessage("🔍 Getting context from Python backend...")
            let contextResponse = try await bridge.getContext()
 
            // Parse intent via Python AI
            logMessage("🧠 Parsing intent via Python backend...")
            let intentResponse = try await bridge.parseIntent(text: text, context: contextResponse.contextText)
            let plan = intentResponse.plan
            logMessage("💡 Parsed plan: \(plan.confirmation) with \(plan.actions.count) actions")
 
            state.setState(.executing, message: plan.confirmation)

            // Speak the confirmation — but ONLY if the plan doesn't produce its own
            // spoken response (a `speak` action or an auto-spoken query result).
            // Otherwise the user hears two overlapping answers (e.g. "how are you").
            if !ActionRouter.planSpeaksItsOwnResponse(plan) {
                try? await bridge.speak(text: plan.confirmation, blocking: false)
            }

            // Execute via router — Swift actions locally, Python via API
            let results = await router.executePlan(plan)
 
            let successCount = results.filter(\.success).count
            let total = results.count
            let allSuccess = successCount == total
            logMessage("📊 Plan execution finished: \(successCount)/\(total) steps succeeded")
 
            if allSuccess {
                state.setState(.done, message: "✅ \(plan.confirmation)")
            } else {
                state.setState(.error, message: "⚠️ \(successCount)/\(total) steps succeeded")
            }
        } catch let error as PythonBridgeError {
            state.setState(.error, message: error.localizedDescription)
            logMessage("❌ Command error: \(error.localizedDescription)")
        } catch {
            state.setState(.error, message: "Command failed")
            logMessage("❌ Unexpected command error: \(error.localizedDescription)")
        }
    }
 
    // MARK: - Voice Pipeline
 
    private func handleWakeWord(inlineCommand: String?) async {
        // Stop wake word listener to avoid microphone resource sharing conflicts and double triggers
        wakeWordListener?.stop()

        if let command = inlineCommand, !command.isEmpty {
            // "Hey Voxa open Chrome" — show orb instantly, then process
            logMessage("🎯 Wake word + inline command: \"\(command)\"")
            state.setState(.listening, message: "Hey Voxa")
            // No recording happens for inline commands — still show what was heard.
            state.setTranscript(command, final: true)
            await processCommand(command)
        } else {
            // "Hey Voxa" alone — show orb INSTANTLY, play local chime, then listen
            logMessage("🎯 Wake word detected — orb up, local TTS, listening...")
            state.setState(.listening, message: "Listening...")
            // Local AVSpeechSynthesizer — zero network latency, plays in <50ms
            TTSManager.shared.speakLocal("Yes?")
            // Wait just long enough for "Yes?" to finish (~0.5s) so mic doesn't echo
            try? await Task.sleep(nanoseconds: 500_000_000)
            await handleVoiceCommand()
        }
        // Restart wake word listener after execution finishes
        wakeWordListener?.start()
    }
 
    /// Public entry point to start a voice command manually (e.g. from the
    /// menu-bar "Speak" button), mirroring the hotkey path.
    func triggerVoiceCommand() async {
        await handleHotkey()
    }

    private func handleHotkey() async {
        logMessage("🔑 Hotkey ⌘+Shift+V activated!")
        // Stop wake word listener to avoid microphone resource sharing conflicts
        wakeWordListener?.stop()
        await handleVoiceCommand()
        // Restart wake word listener
        wakeWordListener?.start()
    }
 
    private func handleVoiceCommand() async {
        guard let capture = voiceCapture else { return }

        // Only set state if not already listening (wake-word path pre-sets it)
        if state.pipelineState != .listening {
            state.setState(.listening)
        }

        // Start of listening — clear any stale transcript, then stream live
        // display-only partials (on-device SFSpeechRecognizer) into the overlay.
        state.setTranscript("", final: false)
        capture.onPartialTranscript = { text in
            Task { @MainActor in
                VoxaState.shared.setTranscript(text, final: false)
            }
        }

        // Record audio
        guard let audioData = await capture.recordUntilSilence() else {
            state.setState(.idle, message: "No speech detected")
            return
        }

        // Transcribe via Python Whisper
        state.setState(.transcribing)

        do {
            let text = try await bridge.transcribe(audioData: audioData)
            logMessage("📝 Transcribed: \"\(text)\"")

            // Whisper's final text replaces the live partial (locks in).
            state.setTranscript(text, final: true)

            // Strip wake word if present
            var command = text
            let lowerText = text.lowercased()
            if lowerText.hasPrefix(config.wakeWord) {
                command = String(text.dropFirst(config.wakeWord.count))
                    .trimmingCharacters(in: .whitespaces)
                    .trimmingCharacters(in: CharacterSet(charactersIn: ".,!? "))
            }
 
            guard !command.isEmpty else {
                // User just said "Hey Voxa" — wait for next command
                state.setState(.idle, message: "Yes? What can I do?")
                return
            }
 
            await processCommand(command)
        } catch {
            state.setState(.error, message: "Transcription failed")
            logMessage("❌ Transcription error: \(error.localizedDescription)")
        }
    }
 
    // MARK: - Python Backend Process Management
 
    private func launchBackend() {
        let process = Process()

        // Inject config + the user's API key into the backend's environment.
        var environment = ProcessInfo.processInfo.environment
        if let key = VoxaConfig.readAPIKey() {
            environment["OPENAI_API_KEY"] = key
        }
        environment["VOXA_BRIDGE_TOKEN"] = VoxaConfig.bridgeToken()
        environment["API_SERVER_HOST"] = config.apiServerHost
        environment["API_SERVER_PORT"] = String(config.apiServerPort)
        environment["PYTHONUNBUFFERED"] = "1"

        // DMG-embedded credentials (OAuth client ids/secrets, OpenAI key fallback)
        // so a downloaded app works out of the box. Only fill what the environment
        // doesn't already provide — real env / ~/.voxa/.env always take precedence.
        for (k, v) in VoxaConfig.embeddedDefaults where (environment[k]?.isEmpty ?? true) {
            environment[k] = v
        }

        if let backend = config.embeddedBackendURL {
            // ── Distributed app: launch the self-contained bundled backend ──
            logMessage("📦 Launching embedded backend: \(backend.path)")
            // Ensure ~/.voxa exists — it's the working dir, and it may not have
            // been created yet if the key came from an env var (no key prompt).
            try? FileManager.default.createDirectory(
                at: VoxaConfig.userConfigDir, withIntermediateDirectories: true)
            process.executableURL = backend
            process.arguments = ["--server"]
            process.currentDirectoryURL = VoxaConfig.userConfigDir
        } else {
            // ── Developer checkout: launch via the project venv ──
            let python = config.pythonPath
            guard FileManager.default.fileExists(atPath: python.path) else {
                logMessage("❌ No embedded backend and Python venv not found at \(python.path)")
                return
            }
            process.executableURL = python
            process.arguments = ["-m", "voxa.main", "--server"]
            process.currentDirectoryURL = config.projectRoot
        }
        process.environment = environment

        // Pipe stdout/stderr for logging
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = pipe
 
        pipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            if let output = String(data: data, encoding: .utf8), !output.isEmpty {
                self?.logMessage("[Python Output] \(output.trimmingCharacters(in: .newlines))")
            }
        }
 
        process.terminationHandler = { [weak self] proc in
            self?.logMessage("⚠️ Python backend exited with code \(proc.terminationStatus)")
            Task { @MainActor in
                self?.state.isBackendReady = false
                // Auto-restart after 2 seconds if engine is still running AND backend is not already running on port
                if self?.isRunning == true {
                    let alreadyRunning = await PythonBridge.shared.healthCheck()
                    if !alreadyRunning {
                        self?.logMessage("⏳ Restarting Python backend in 2 seconds...")
                        try? await Task.sleep(nanoseconds: 2_000_000_000)
                        self?.launchBackend()
                    } else {
                        self?.logMessage("ℹ️ Backend is already running on port. No need to restart.")
                        self?.state.isBackendReady = true
                    }
                }
            }
        }
 
        do {
            try process.run()
            backendProcess = process
            logMessage("🐍 Python backend launched (PID: \(process.processIdentifier))")
        } catch {
            logMessage("❌ Failed to launch Python backend: \(error.localizedDescription)")
        }
    }

    private func connectWebSocket() {
        // Cancel any existing task first to prevent duplicate active listeners
        webSocketTask?.cancel(with: .goingAway, reason: nil)

        // Authenticate the socket with the shared bridge token via header —
        // never in the URL, so it can't end up in request logs.
        var request = URLRequest(url: config.wsURL)
        request.setValue(VoxaConfig.bridgeToken(), forHTTPHeaderField: "X-Voxa-Token")
        let task = URLSession.shared.webSocketTask(with: request)
        self.webSocketTask = task
        task.resume()
        listenWebSocket()
        print("🔌 WebSocket connecting to \(config.wsURL)...")
    }

    private func listenWebSocket() {
        webSocketTask?.receive { [weak self] result in
            Task { @MainActor in
                guard let self = self else { return }
                switch result {
                case .success(let message):
                    switch message {
                    case .string(let text):
                        self.handleWebSocketEvent(text)
                    case .data(let data):
                        print("💬 WebSocket received binary data: \(data.count) bytes")
                    @unknown default:
                        break
                    }
                    self.listenWebSocket()
                case .failure(let error):
                    print("⚠️ WebSocket error: \(error)")
                    // Reconnect after 5 seconds if running
                    try? await Task.sleep(nanoseconds: 5_000_000_000)
                    if self.isRunning {
                        self.connectWebSocket()
                    }
                }
            }
        }
    }

    // MARK: - WebSocket Events

    /// Handle a real-time event pushed from the backend over the WebSocket.
    private func handleWebSocketEvent(_ text: String) {
        guard let data = text.data(using: .utf8),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let event = obj["event"] as? String else { return }
        let payload = obj["data"] as? [String: Any] ?? [:]

        switch event {
        case "meeting_detected":
            let platform = (payload["platform"] as? String) ?? "meeting"
            promptRecordMeeting(platform: platform)
        case "meeting_recording":
            MeetingPromptManager.shared.hide()
            let platform = (payload["platform"] as? String) ?? "meeting"
            // Backend asked us to stream mic audio (it can't reliably access it).
            if (payload["external_audio"] as? Bool) ?? false {
                let systemAudio = (payload["capture_system_audio"] as? Bool) ?? false
                startMeetingCapture(captureSystemAudio: systemAudio)
            }
            // Brief, self-dismissing confirmation — NOT a persistent state, so the
            // orb doesn't animate for the whole meeting.
            state.setState(.done, message: "Recording \(platform)…")
        case "meeting_paused":
            meetingCapture?.pause()
            systemAudioCapture?.pause()
        case "meeting_resumed":
            meetingCapture?.resume()
            systemAudioCapture?.resume()
        case "meeting_suggestion":
            let id = (payload["id"] as? String) ?? ""
            let title = (payload["title"] as? String) ?? "New event"
            let whenText = (payload["when_text"] as? String) ?? ""
            guard !id.isEmpty else { break }
            SuggestionPromptManager.shared.show(
                id: id, title: title, whenText: whenText,
                onAdd: { [weak self] in
                    Task { @MainActor in
                        _ = try? await self?.bridge.confirmSuggestion(id: id, accept: true)
                        self?.state.setState(.done, message: "Added to calendar")
                    }
                },
                onDismiss: { [weak self] in
                    Task { @MainActor in
                        _ = try? await self?.bridge.confirmSuggestion(id: id, accept: false)
                    }
                }
            )
        case "meeting_ended", "meeting_dismissed":
            MeetingPromptManager.shared.hide()
            SuggestionPromptManager.shared.clearAll()
            stopMeetingCapture()
            // Make sure the overlay/animation returns to idle.
            state.setState(.idle, message: "Ready")
        case "integration_connected", "integration_disconnected":
            // Let any open Accounts page refresh its provider list.
            NotificationCenter.default.post(name: .voxaIntegrationsChanged, object: nil)
        default:
            break
        }
    }

    private func startMeetingCapture(captureSystemAudio: Bool) {
        // Free the microphone for meeting capture: the wake-word listener holds
        // its own AVAudioEngine on the input, and two engines contend — which is
        // why meeting audio came back empty. Pause it for the duration.
        wakeWordListener?.stop()

        if meetingCapture == nil { meetingCapture = MeetingCapture() }
        meetingCapture?.start()
        if captureSystemAudio {
            if systemAudioCapture == nil { systemAudioCapture = SystemAudioCapture() }
            systemAudioCapture?.start()   // captures the other participants
        }
        logMessage("🎙️ Streaming meeting audio to backend (system audio: \(captureSystemAudio))")
    }

    private func stopMeetingCapture() {
        meetingCapture?.stop()
        meetingCapture = nil
        systemAudioCapture?.stop()
        systemAudioCapture = nil
        // Resume wake-word listening now that the mic is free again.
        if isRunning {
            wakeWordListener?.start()
        }
    }

    /// Show a minimal, non-intrusive pill asking whether to record the detected
    /// meeting; report the answer. Does not steal focus from the meeting.
    private func promptRecordMeeting(platform: String) {
        MeetingPromptManager.shared.show(
            platform: platform,
            onRecord: { [weak self] in
                // Capture + the brief indicator are driven by the meeting_recording
                // event so the orb doesn't stay animating for the whole meeting.
                Task {
                    try? await PythonBridge.shared.confirmMeeting(record: true)
                    self?.logMessage("🎙️ User agreed to record meeting")
                }
            },
            onDismiss: { [weak self] in
                Task {
                    try? await PythonBridge.shared.confirmMeeting(record: false)
                    self?.logMessage("🙅 User declined meeting recording")
                }
            }
        )
    }

    private func disconnectWebSocket() {
        webSocketTask?.cancel(with: .goingAway, reason: nil)
        webSocketTask = nil
        print("🔌 WebSocket disconnected")
    }

    private func terminateBackend() {
        guard let process = backendProcess, process.isRunning else { return }
        process.terminate()
        backendProcess = nil
        print("🛑 Python backend terminated")
    }
}
