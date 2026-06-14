import Foundation
import AVFoundation

/// Text-to-Speech manager.
/// Uses AVSpeechSynthesizer for local TTS and can delegate to Python for premium voices.
final class TTSManager {
    static let shared = TTSManager()

    private let synthesizer = AVSpeechSynthesizer()
    private let bridge = PythonBridge.shared

    private init() {}

    /// Speak text using the best available method.
    /// Tries Python TTS (ElevenLabs/OpenAI) first, falls back to local AVSpeech.
    func speak(_ text: String, blocking: Bool = false) async {
        guard !text.isEmpty else { return }

        // Try Python TTS (better voices)
        do {
            try await bridge.speak(text: text, blocking: blocking)
            return
        } catch {
            // Fall back to local TTS
            print("⚠️ Python TTS failed, using local: \(error.localizedDescription)")
        }

        // Local fallback
        speakLocal(text)
    }

    /// Speak using macOS local TTS (AVSpeechSynthesizer).
    /// Picks the "Samantha" voice (same voice macOS Siri uses) if available.
    func speakLocal(_ text: String) {
        let utterance = AVSpeechUtterance(string: text)
        // Samantha is the default macOS Siri voice — identical to the real Siri "Yes?"
        let preferredVoices = ["com.apple.voice.enhanced.en-US.Samantha",
                               "com.apple.ttsbundle.Samantha-compact",
                               "en-US"]
        utterance.voice = preferredVoices.compactMap { AVSpeechSynthesisVoice(identifier: $0) }.first
                       ?? AVSpeechSynthesisVoice(language: "en-US")
        utterance.rate  = 0.52      // Natural, slightly quicker than default
        utterance.pitchMultiplier = 1.1  // Slightly higher — sounds like Siri
        utterance.volume = 0.9
        synthesizer.stopSpeaking(at: .immediate)  // Stop any leftover speech instantly
        synthesizer.speak(utterance)
    }

    /// Stop any ongoing speech.
    func stopSpeaking() {
        synthesizer.stopSpeaking(at: .immediate)
    }

    /// Whether TTS is currently speaking.
    var isSpeaking: Bool {
        synthesizer.isSpeaking
    }
}
