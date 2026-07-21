import Foundation
import SwiftUI
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
 
            // Speak confirmation voice response
            try? await bridge.speak(text: plan.confirmation, blocking: false)
 
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
        let python = config.pythonPath
        let projectRoot = config.projectRoot
 
        guard FileManager.default.fileExists(atPath: python.path) else {
            logMessage("❌ Python venv not found at \(python.path)")
            return
        }
 
        let process = Process()
        process.executableURL = python
        process.arguments = ["-m", "voxa.main", "--server"]
        process.currentDirectoryURL = projectRoot
        process.environment = ProcessInfo.processInfo.environment
 
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

        let url = config.wsURL
        let task = URLSession.shared.webSocketTask(with: url)
        self.webSocketTask = task
        task.resume()
        listenWebSocket()
        print("🔌 WebSocket connecting to \(url)...")
    }

    private func listenWebSocket() {
        webSocketTask?.receive { [weak self] result in
            Task { @MainActor in
                guard let self = self else { return }
                switch result {
                case .success(let message):
                    switch message {
                    case .string(let text):
                        print("💬 WebSocket received event: \(text)")
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
