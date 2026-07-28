import SwiftUI
import AVFoundation
import Speech
import ApplicationServices

struct SettingsPage: View {
    @EnvironmentObject var engine: VoxaEngine
    @EnvironmentObject var state: VoxaState

    @State private var editingKey = false
    @State private var keyInput = ""
    @State private var keySaved = false
    @State private var chatBallVisible = FloatingBallManager.shared.isShowing
    @State private var perms = Permissions()

    var body: some View {
        Page(title: "Settings", subtitle: "Configure Voxa") {
            // API key
            group("OpenAI API Key") {
                if editingKey {
                    VStack(alignment: .leading, spacing: 10) {
                        SecureField("sk-…", text: $keyInput).textFieldStyle(.roundedBorder)
                        HStack(spacing: 10) {
                            Button("Cancel") { editingKey = false }.buttonStyle(GhostButtonStyle())
                            Button("Save") { saveKey() }.buttonStyle(PrimaryButtonStyle())
                        }
                    }
                } else {
                    SettingRow(icon: "key", title: "API Key", subtitle: maskedKey) {
                        Button(keySaved ? "Saved" : "Change") { keyInput = ""; editingKey = true }
                            .buttonStyle(GhostButtonStyle()).frame(width: 96)
                    }
                }
            }

            // Voice
            group("Voice") {
                VStack(spacing: 14) {
                    SettingRow(icon: "waveform", title: "Wake Word", subtitle: "Say it to activate hands-free") {
                        Text("“\(VoxaConfig.shared.wakeWord)”").font(.system(size: 12, weight: .medium)).foregroundStyle(Theme.subtle)
                    }
                    Divider().overlay(Theme.stroke)
                    SettingRow(icon: "command", title: "Hotkey", subtitle: "Push-to-talk shortcut") {
                        Text(VoxaConfig.shared.hotkeyCombo.uppercased()).font(.system(size: 12, weight: .medium)).foregroundStyle(Theme.subtle)
                    }
                }
            }

            // Permissions
            group("Permissions") {
                VStack(spacing: 14) {
                    permRow("mic", "Microphone", perms.mic, "Privacy_Microphone")
                    Divider().overlay(Theme.stroke)
                    permRow("waveform.badge.mic", "Speech Recognition", perms.speech, "Privacy_SpeechRecognition")
                    Divider().overlay(Theme.stroke)
                    permRow("rectangle.dashed.badge.record", "Screen Recording", perms.screen, "Privacy_ScreenCapture")
                    Divider().overlay(Theme.stroke)
                    permRow("hand.tap", "Accessibility", perms.accessibility, "Privacy_Accessibility")
                }
            }

            // Appearance / behaviour
            group("Interface") {
                VStack(spacing: 14) {
                    SettingRow(icon: "sparkles.rectangle.stack", title: "Notch Halo", subtitle: "Wrap the animation around the notch") {
                        MonoToggle(isOn: $state.useNotchHalo)
                    }
                    Divider().overlay(Theme.stroke)
                    SettingRow(icon: "bubble.left.and.bubble.right", title: "Chat Ball", subtitle: "Floating chat button on screen") {
                        MonoToggle(isOn: Binding(get: { chatBallVisible }, set: { v in chatBallVisible = v; v ? FloatingBallManager.shared.show() : FloatingBallManager.shared.hide() }))
                    }
                    Divider().overlay(Theme.stroke)
                    SettingRow(icon: "sparkles", title: "Setup Guide", subtitle: "Replay the first-run walkthrough") {
                        Button("Replay") { OnboardingManager.shared.present(force: true) }
                            .buttonStyle(GhostButtonStyle()).frame(width: 96)
                    }
                }
            }

            // About
            group("About") {
                VStack(alignment: .leading, spacing: 6) {
                    Text("Voxa — your voice on the Mac").font(.system(size: 13, weight: .medium))
                    Text("Version \(appVersion)").font(.system(size: 12)).foregroundStyle(Theme.subtle)
                }
                Button("Quit Voxa") { engine.stop(); NSApplication.shared.terminate(nil) }
                    .buttonStyle(GhostButtonStyle(tint: .red)).frame(width: 130).padding(.top, 4)
            }
        }
        .onAppear(perform: refreshPerms)
    }

    // MARK: - Pieces

    private func group<V: View>(_ title: String, @ViewBuilder _ content: () -> V) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            SectionLabel(text: title)
            Card { content() }
        }
    }

    private func permRow(_ icon: String, _ title: String, _ granted: Bool, _ pane: String) -> some View {
        SettingRow(icon: icon, title: title, subtitle: granted ? "Granted" : "Not granted") {
            if granted {
                Image(systemName: "checkmark.circle.fill").foregroundStyle(Theme.text)
            } else {
                Button("Grant") { openPrivacy(pane) }.buttonStyle(GhostButtonStyle()).frame(width: 80)
            }
        }
    }

    // MARK: - Data

    private var maskedKey: String {
        guard let k = VoxaConfig.readAPIKey(), k.count > 10 else { return "Not set" }
        return String(k.prefix(6)) + "••••" + String(k.suffix(4))
    }
    private var appVersion: String {
        Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "—"
    }

    private func saveKey() {
        let k = keyInput.trimmed
        guard k.hasPrefix("sk-"), k.count >= 20 else { return }
        keySaved = VoxaConfig.saveAPIKey(k)
        editingKey = false
    }

    private func openPrivacy(_ pane: String) {
        if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?\(pane)") {
            NSWorkspace.shared.open(url)
        }
    }

    struct Permissions { var mic = false; var speech = false; var screen = false; var accessibility = false }

    private func refreshPerms() {
        var p = Permissions()
        p.mic = AVCaptureDevice.authorizationStatus(for: .audio) == .authorized
        p.speech = SFSpeechRecognizer.authorizationStatus() == .authorized
        p.screen = CGPreflightScreenCaptureAccess()
        p.accessibility = AXIsProcessTrusted()
        perms = p
    }
}
