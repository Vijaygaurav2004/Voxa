import Foundation
import Speech
import AVFoundation

/// On-device wake word detection using Apple's SFSpeechRecognizer.
/// Robust against session timeouts, audio engine conflicts, and authorization edge cases.
final class WakeWordListener {
    private let wakeWord: String
    private let onWake: (String?) -> Void

    private var speechRecognizer: SFSpeechRecognizer?
    private var recognitionRequest: SFSpeechAudioBufferRecognitionRequest?
    private var recognitionTask: SFSpeechRecognitionTask?
    private var audioEngine: AVAudioEngine?

    private var isActive = false       // Intent: should be listening
    private var isRunning = false      // Reality: engine is actually running
    private var restartWorkItem: DispatchWorkItem?

    // Transcripts already processed — avoids re-triggering on the same partial result
    private var lastMatchedTranscript = ""

    // Variants that SFSpeechRecognizer may produce for "hey voxa"
    private let wakeWordVariants = [
        "hey voxa", "hey vox", "hey boxer", "hey boca",
        "hey voca", "hey volga", "hey moxa", "voxa",
        "a voxa", "hey mocha", "hey wokka",
    ]

    init(onWake: @escaping (String?) -> Void) {
        self.wakeWord = VoxaConfig.shared.wakeWord.lowercased()
        self.onWake = onWake
        // Use server-side recognition (more reliable than on-device)
        self.speechRecognizer = SFSpeechRecognizer(locale: Locale(identifier: "en-US"))
    }

    // MARK: - Public API

    func start() {
        isActive = true
        guard !isRunning else { return }

        SFSpeechRecognizer.requestAuthorization { [weak self] status in
            DispatchQueue.main.async {
                guard let self else { return }
                if status == .authorized {
                    self.startSession()
                } else {
                    appLog("❌ Speech recognition not authorized: \(status.rawValue)")
                }
            }
        }
    }

    func stop() {
        isActive = false
        tearDown()
    }

    // MARK: - Session Lifecycle

    private func startSession() {
        guard isActive, !isRunning else { return }

        guard let recognizer = speechRecognizer, recognizer.isAvailable else {
            appLog("⚠️ SFSpeechRecognizer not available — retrying in 2s")
            scheduleRestart(delay: 2.0)
            return
        }

        let engine = AVAudioEngine()
        self.audioEngine = engine

        let request = SFSpeechAudioBufferRecognitionRequest()
        request.shouldReportPartialResults = true
        // NOTE: requiresOnDeviceRecognition = false — server recognition is far more
        // reliable and accurate for continuous wake-word sessions on macOS.
        request.requiresOnDeviceRecognition = false
        self.recognitionRequest = request

        let inputNode = engine.inputNode
        let fmt = inputNode.outputFormat(forBus: 0)

        guard fmt.sampleRate > 0 else {
            appLog("❌ Invalid audio format — no microphone? Retrying in 2s")
            scheduleRestart(delay: 2.0)
            return
        }

        inputNode.installTap(onBus: 0, bufferSize: 1024, format: fmt) { [weak request] buffer, _ in
            request?.append(buffer)
        }

        recognitionTask = recognizer.recognitionTask(with: request) { [weak self] result, error in
            guard let self else { return }

            if let result {
                let transcript = result.bestTranscription.formattedString.lowercased()

                // Log every partial result so we can confirm mic is working
                if !transcript.isEmpty {
                    appLog("👂 Heard: \"\(transcript)\"")
                }

                // Check for wake word — only if we haven't already matched this transcript
                if transcript != self.lastMatchedTranscript, self.matchesWakeWord(transcript) {
                    self.lastMatchedTranscript = transcript
                    let inlineCommand = self.extractCommandAfterWake(transcript)
                    appLog("🎯 Wake word detected: \"\(transcript)\" inline=\(inlineCommand ?? "nil")")

                    self.tearDown()
                    DispatchQueue.main.async {
                        self.onWake(inlineCommand)
                    }
                    return
                }

                // Auto-reset if the transcript is getting too long without matching the wake word.
                // This clears any accumulated background noise/conversations and ensures the buffer is fresh.
                let wordCount = transcript.components(separatedBy: .whitespacesAndNewlines).filter { !$0.isEmpty }.count
                if wordCount >= 10 {
                    appLog("⟳ Auto-resetting wake word session (transcript too long: \(wordCount) words)")
                    self.tearDown()
                    if self.isActive {
                        self.scheduleRestart(delay: 0.1)
                    }
                    return
                }
            }

            if let error {
                let nsErr = error as NSError
                // Code 1110 = no speech for 60s (expected timeout) — just restart quietly
                let isTimeout = nsErr.code == 1110 || nsErr.domain == "kAFAssistantErrorDomain"
                if isTimeout {
                    appLog("⟳ Wake word session timeout — restarting")
                } else {
                    appLog("⟳ Wake word error (\(nsErr.code)): \(error.localizedDescription) — restarting")
                }
                self.tearDown()
                if self.isActive {
                    self.scheduleRestart(delay: 0.3)
                }
            }
        }

        do {
            try engine.start()
            isRunning = true
            lastMatchedTranscript = ""
            appLog("🎙️ Wake word listener active — say \"\(wakeWord)\"")
        } catch {
            appLog("❌ Audio engine failed: \(error.localizedDescription)")
            tearDown()
            scheduleRestart(delay: 1.0)
        }
    }

    private func tearDown() {
        isRunning = false
        restartWorkItem?.cancel()
        restartWorkItem = nil

        recognitionTask?.cancel()
        recognitionTask = nil
        recognitionRequest?.endAudio()
        recognitionRequest = nil

        audioEngine?.inputNode.removeTap(onBus: 0)
        audioEngine?.stop()
        audioEngine = nil
    }

    private func scheduleRestart(delay: Double) {
        restartWorkItem?.cancel()
        let item = DispatchWorkItem { [weak self] in
            guard let self, self.isActive else { return }
            self.startSession()
        }
        restartWorkItem = item
        DispatchQueue.main.asyncAfter(deadline: .now() + delay, execute: item)
    }

    // MARK: - Wake Word Matching

    private func matchesWakeWord(_ text: String) -> Bool {
        let normalized = text
            .replacingOccurrences(of: "[^a-z\\s]", with: " ", options: .regularExpression)
            .components(separatedBy: .whitespaces)
            .filter { !$0.isEmpty }
            .joined(separator: " ")

        if normalized.contains(wakeWord) {
            return true
        }

        // Only use the hardcoded variants if using the default "hey voxa" wake word
        if wakeWord == "hey voxa" {
            for variant in wakeWordVariants where normalized.contains(variant) {
                return true
            }
        }
        return false
    }

    private func extractCommandAfterWake(_ text: String) -> String? {
        let normalized = text.lowercased()
        
        // Try actual wake word first
        if let range = normalized.range(of: wakeWord) {
            let after = String(text[range.upperBound...]).trimmingCharacters(in: .whitespaces)
            return after.count > 3 ? after : nil
        }

        // Fall back to variants only if default
        if wakeWord == "hey voxa" {
            for variant in wakeWordVariants {
                if let range = normalized.range(of: variant) {
                    let after = String(text[range.upperBound...]).trimmingCharacters(in: .whitespaces)
                    return after.count > 3 ? after : nil
                }
            }
        }
        return nil
    }
}
