import SwiftUI
import AppKit
import AVFoundation
import Speech
import ApplicationServices

// MARK: - First-run onboarding

/// Multi-step first-run flow: Welcome → (API Key, only if needed) → Permissions
/// → Connect Google → Done. Built only from `AppTheme` primitives so it matches
/// the monochrome design system. Talks to `OnboardingManager.shared` for the
/// key-gate and completion; reads `VoxaState.shared` for backend readiness.
struct OnboardingView: View {
    let requireKey: Bool

    private enum Step: Int {
        case welcome, apiKey, permissions, google, done
    }

    @State private var step: Step = .welcome

    // API-key step
    @State private var keyInput = ""

    // Permissions step
    @State private var perms = Permissions()

    // Google step
    @ObservedObject private var appState = VoxaState.shared
    @State private var googlePending = false
    @State private var googleConnected = false
    @State private var googleNote: String? = nil

    // Ordered sequence — the API-Key page appears only when a key is needed.
    private var steps: [Step] {
        requireKey
            ? [.welcome, .apiKey, .permissions, .google, .done]
            : [.welcome, .permissions, .google, .done]
    }

    private var currentIndex: Int { steps.firstIndex(of: step) ?? 0 }

    var body: some View {
        VStack(spacing: 0) {
            pageDots
                .padding(.top, 22)
                .padding(.bottom, 8)

            ZStack {
                content
                    .id(step)                       // re-identify so transitions fire
                    .transition(.opacity)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .padding(.horizontal, 40)

            footer
                .padding(.horizontal, 40)
                .padding(.bottom, 32)
                .padding(.top, 8)
        }
        .frame(width: 640, height: 600)
        .background(Color(NSColor.windowBackgroundColor))
        .onReceive(NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)) { _ in
            refreshPerms()
        }
        .onReceive(NotificationCenter.default.publisher(for: .voxaIntegrationsChanged)) { _ in
            googlePending = false
            googleConnected = true
            googleNote = nil
        }
        .onAppear(perform: refreshPerms)
    }

    // MARK: - Progress dots

    private var pageDots: some View {
        HStack(spacing: 7) {
            ForEach(steps.indices, id: \.self) { i in
                Capsule()
                    .fill(i == currentIndex ? Theme.text : Theme.stroke)
                    .frame(width: i == currentIndex ? 20 : 7, height: 7)
                    .animation(.easeInOut(duration: 0.25), value: currentIndex)
            }
        }
    }

    // MARK: - Step content

    @ViewBuilder private var content: some View {
        switch step {
        case .welcome:     welcomeStep
        case .apiKey:      apiKeyStep
        case .permissions: permissionsStep
        case .google:      googleStep
        case .done:        doneStep
        }
    }

    // MARK: 1 · Welcome

    private var welcomeStep: some View {
        VStack(spacing: 18) {
            ZStack {
                Circle().fill(Theme.card).frame(width: 96, height: 96)
                Circle().strokeBorder(Theme.stroke, lineWidth: 1).frame(width: 96, height: 96)
                Image(systemName: "waveform")
                    .font(.system(size: 40, weight: .semibold))
                    .foregroundStyle(Theme.text)
            }
            VStack(spacing: 8) {
                Text("Welcome to Voxa")
                    .font(.system(size: 28, weight: .bold, design: .rounded))
                Text("Your voice, in command of your Mac.")
                    .font(.system(size: 14))
                    .foregroundStyle(Theme.subtle)
            }
            VStack(spacing: 12) {
                bullet("mic.fill", "Voice control", "Speak naturally to open apps, search, and act.")
                bullet("text.bubble", "Live transcription", "See what you say in real time as you talk.")
                bullet("calendar.badge.clock", "Meeting notes & reminders", "Capture meetings and never miss a follow-up.")
            }
            .padding(.top, 4)
        }
        .frame(maxWidth: .infinity)
    }

    private func bullet(_ icon: String, _ title: String, _ subtitle: String) -> some View {
        HStack(spacing: 12) {
            ZStack {
                RoundedRectangle(cornerRadius: Theme.radiusSmall, style: .continuous)
                    .fill(Theme.card)
                    .frame(width: 34, height: 34)
                Image(systemName: icon).font(.system(size: 15, weight: .medium)).foregroundStyle(Theme.text)
            }
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(.system(size: 13, weight: .semibold)).foregroundStyle(Theme.text)
                Text(subtitle).font(.system(size: 11.5)).foregroundStyle(Theme.subtle)
            }
            Spacer(minLength: 0)
        }
        .frame(maxWidth: 380)
    }

    // MARK: 2 · API Key

    private var keyLooksValid: Bool {
        let k = keyInput.trimmed
        return k.hasPrefix("sk-") && k.count >= 20
    }

    private var apiKeyStep: some View {
        VStack(alignment: .leading, spacing: 16) {
            VStack(alignment: .leading, spacing: 6) {
                Text("Add your OpenAI key")
                    .font(.system(size: 24, weight: .bold))
                Text("Voxa uses OpenAI to understand your commands.")
                    .font(.system(size: 13)).foregroundStyle(Theme.subtle)
            }

            SecureField("sk-…", text: $keyInput)
                .textFieldStyle(.roundedBorder)
                .font(.system(size: 13, design: .monospaced))
                .onSubmit { saveKey() }

            if !keyInput.isEmpty && !keyLooksValid {
                Text("That doesn't look like an OpenAI key — keys start with “sk-”.")
                    .font(.system(size: 11))
                    .foregroundStyle(.red)
            }

            VStack(alignment: .leading, spacing: 4) {
                Text("Stored only on this Mac at ~/.voxa/.env — never uploaded or shared.")
                    .font(.system(size: 11)).foregroundStyle(Theme.subtle)
                Button {
                    if let url = URL(string: "https://platform.openai.com/api-keys") {
                        NSWorkspace.shared.open(url)
                    }
                } label: {
                    Text("Get one at platform.openai.com/api-keys")
                        .font(.system(size: 11, weight: .medium))
                        .foregroundStyle(Theme.text)
                        .underline()
                }
                .buttonStyle(.plain)
            }
        }
        .frame(maxWidth: 420, alignment: .leading)
        .frame(maxWidth: .infinity, alignment: .center)
    }

    private func saveKey() {
        guard keyLooksValid else { return }
        guard VoxaConfig.saveAPIKey(keyInput.trimmed) else { return }
        OnboardingManager.shared.resolveKeyStep(saved: true)
        advance()
    }

    // MARK: 3 · Permissions

    struct Permissions { var mic = false; var speech = false; var screen = false; var accessibility = false }

    private var permissionsStep: some View {
        VStack(alignment: .leading, spacing: 16) {
            VStack(alignment: .leading, spacing: 6) {
                Text("Grant a few permissions")
                    .font(.system(size: 24, weight: .bold))
                Text("Voxa needs these to hear you and act on your Mac.")
                    .font(.system(size: 13)).foregroundStyle(Theme.subtle)
            }

            Card {
                VStack(spacing: 14) {
                    permRow("mic", "Microphone", "Hear your voice commands", perms.mic) {
                        AVCaptureDevice.requestAccess(for: .audio) { _ in }
                    }
                    Divider().overlay(Theme.stroke)
                    permRow("waveform.badge.mic", "Speech Recognition", "Transcribe what you say", perms.speech) {
                        SFSpeechRecognizer.requestAuthorization { _ in }
                    }
                    Divider().overlay(Theme.stroke)
                    permRow("rectangle.dashed.badge.record", "Screen Recording", "See your screen for context", perms.screen) {
                        CGRequestScreenCaptureAccess()
                    }
                    Divider().overlay(Theme.stroke)
                    permRow("hand.tap", "Accessibility", "Control apps and the hotkey", perms.accessibility) {
                        openAccessibilitySettings()
                    }
                }
            }

            Text("You can grant these later in Settings.")
                .font(.system(size: 11)).foregroundStyle(Theme.subtle)
        }
        .frame(maxWidth: 460, alignment: .leading)
        .frame(maxWidth: .infinity, alignment: .center)
    }

    private func permRow(_ icon: String, _ title: String, _ subtitle: String, _ granted: Bool, action: @escaping () -> Void) -> some View {
        SettingRow(icon: icon, title: title, subtitle: granted ? "Granted" : subtitle) {
            if granted {
                Image(systemName: "checkmark.circle.fill")
                    .font(.system(size: 16))
                    .foregroundStyle(.green)
            } else {
                Button("Grant") {
                    action()
                    // Re-poll shortly after — the system prompt / pane resolves async.
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.8) { refreshPerms() }
                }
                .buttonStyle(GhostButtonStyle())
                .frame(width: 80)
            }
        }
    }

    private func openAccessibilitySettings() {
        if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility") {
            NSWorkspace.shared.open(url)
        }
    }

    private func refreshPerms() {
        var p = Permissions()
        p.mic = AVCaptureDevice.authorizationStatus(for: .audio) == .authorized
        p.speech = SFSpeechRecognizer.authorizationStatus() == .authorized
        p.screen = CGPreflightScreenCaptureAccess()
        p.accessibility = AXIsProcessTrusted()
        perms = p
    }

    // MARK: 4 · Connect Google

    private var backendReady: Bool { appState.isBackendReady }

    private var googleStep: some View {
        VStack(spacing: 18) {
            ZStack {
                Circle().fill(Theme.card).frame(width: 72, height: 72)
                Circle().strokeBorder(Theme.stroke, lineWidth: 1).frame(width: 72, height: 72)
                Image(systemName: googleConnected ? "checkmark.circle.fill" : "person.crop.circle.badge.plus")
                    .font(.system(size: 30, weight: .light))
                    .foregroundStyle(googleConnected ? .green : Theme.text)
            }
            VStack(spacing: 8) {
                Text("Connect your Google account")
                    .font(.system(size: 22, weight: .bold))
                Text("So Voxa can add calendar events and send email by voice.")
                    .font(.system(size: 13))
                    .foregroundStyle(Theme.subtle)
                    .multilineTextAlignment(.center)
            }

            if googleConnected {
                Text("Connected ✓")
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(.green)
            } else if googlePending {
                HStack(spacing: 8) {
                    ProgressView().controlSize(.small)
                    Text("Waiting for browser…")
                        .font(.system(size: 12)).foregroundStyle(Theme.subtle)
                }
            }

            if let googleNote {
                Text(googleNote)
                    .font(.system(size: 11))
                    .foregroundStyle(Theme.subtle)
                    .multilineTextAlignment(.center)
                    .frame(maxWidth: 360)
            }
        }
        .frame(maxWidth: .infinity)
    }

    private func connectGoogle() {
        googleNote = nil
        Task { @MainActor in
            do {
                let res = try await PythonBridge.shared.connectIntegration("google")
                if res.success, let auth = res.auth_url, let url = URL(string: auth) {
                    googlePending = true
                    NSWorkspace.shared.open(url)
                } else {
                    // e.g. not_configured — no OAuth creds yet. Not an error.
                    googlePending = false
                    googleNote = "You can connect accounts later in Settings → Accounts."
                }
            } catch {
                googlePending = false
                googleNote = "You can connect accounts later in Settings → Accounts."
            }
        }
    }

    // MARK: 5 · Done

    private var doneStep: some View {
        VStack(spacing: 18) {
            ZStack {
                Circle().fill(Theme.card).frame(width: 96, height: 96)
                Circle().strokeBorder(Theme.stroke, lineWidth: 1).frame(width: 96, height: 96)
                Image(systemName: "checkmark")
                    .font(.system(size: 40, weight: .semibold))
                    .foregroundStyle(Theme.text)
            }
            VStack(spacing: 8) {
                Text("You're all set.")
                    .font(.system(size: 28, weight: .bold, design: .rounded))
                Text("Say “\(VoxaConfig.shared.wakeWord)” or press \(VoxaConfig.shared.hotkeyCombo.uppercased()) any time to start.")
                    .font(.system(size: 14))
                    .foregroundStyle(Theme.subtle)
                    .multilineTextAlignment(.center)
            }
        }
        .frame(maxWidth: .infinity)
    }

    // MARK: - Footer / navigation

    @ViewBuilder private var footer: some View {
        HStack(spacing: 12) {
            if currentIndex > 0 && step != .done {
                Button("Back") { goBack() }
                    .buttonStyle(GhostButtonStyle())
                    .frame(width: 96)
            }

            Spacer(minLength: 0)

            switch step {
            case .welcome:
                Button("Get Started") { advance() }
                    .buttonStyle(PrimaryButtonStyle())
                    .frame(width: 200)

            case .apiKey:
                Button("Continue") { saveKey() }
                    .buttonStyle(PrimaryButtonStyle(disabled: !keyLooksValid))
                    .frame(width: 200)
                    .disabled(!keyLooksValid)

            case .permissions:
                Button("Continue") { advance() }
                    .buttonStyle(PrimaryButtonStyle())
                    .frame(width: 200)

            case .google:
                if googleConnected {
                    Button("Continue") { advance() }
                        .buttonStyle(PrimaryButtonStyle())
                        .frame(width: 200)
                } else {
                    Button("Skip for now") { advance() }
                        .buttonStyle(GhostButtonStyle())
                        .frame(width: 130)
                    Button(backendReady ? "Sign in with Google" : "Starting Voxa…") { connectGoogle() }
                        .buttonStyle(PrimaryButtonStyle(disabled: !backendReady || googlePending))
                        .frame(width: 200)
                        .disabled(!backendReady || googlePending)
                }

            case .done:
                Button("Start using Voxa") { OnboardingManager.shared.finish() }
                    .buttonStyle(PrimaryButtonStyle())
                    .frame(width: 220)
            }
        }
    }

    private func advance() {
        let idx = currentIndex
        guard idx + 1 < steps.count else { return }
        withAnimation(.easeInOut(duration: 0.25)) { step = steps[idx + 1] }
    }

    private func goBack() {
        let idx = currentIndex
        guard idx > 0 else { return }
        withAnimation(.easeInOut(duration: 0.25)) { step = steps[idx - 1] }
    }
}
