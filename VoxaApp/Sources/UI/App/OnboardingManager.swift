import AppKit
import SwiftUI

// MARK: - Onboarding window manager

/// Owns the first-run onboarding window and the key-gate that lets the engine
/// suspend startup until an OpenAI key exists. Mirrors the app's other AppKit
/// window managers (VoxaOrbPanel / FloatingBallManager / MeetingPromptManager):
/// a `@MainActor` singleton that keeps a strong ref to its window and nils it on
/// close. Persistence key `voxa.onboarding.complete.v1`.
@MainActor
final class OnboardingManager {
    static let shared = OnboardingManager()

    private static let completeKey = "voxa.onboarding.complete.v1"

    /// True once the user has finished (or replayed and finished) onboarding.
    var isComplete: Bool {
        UserDefaults.standard.bool(forKey: Self.completeKey)
    }

    private func markComplete() {
        UserDefaults.standard.set(true, forKey: Self.completeKey)
    }

    private var window: NSWindow?
    /// Suspends the engine's backend launch until the API-key step resolves.
    /// Resumed EXACTLY once — either `true` (key saved) or `false` (window closed
    /// with no key). Nil-ed out on resume so a second resume can't crash.
    private var keyContinuation: CheckedContinuation<Bool, Never>?
    private var closeObserver: NSObjectProtocol?

    private init() {}

    // MARK: - Presentation entry points

    /// Key-gated first launch (no OpenAI key yet). Presents the onboarding window
    /// and SUSPENDS via a continuation until the API-key step resolves: `true`
    /// once a valid key is saved (the window stays open and continues to the
    /// remaining pages non-blockingly), or `false` if the user closes the window
    /// first. Called by `VoxaEngine.start()` before it launches the backend.
    func runFirstLaunch(requireKey: Bool) async -> Bool {
        // A key already exists — nothing to gate on; just show the friendly flow.
        guard requireKey else {
            presentFirstLaunch(requireKey: false)
            return true
        }
        return await withCheckedContinuation { (cont: CheckedContinuation<Bool, Never>) in
            // Defensive: never overwrite a live continuation (would strand it).
            guard keyContinuation == nil else {
                cont.resume(returning: VoxaConfig.readAPIKey() != nil)
                return
            }
            keyContinuation = cont
            showWindow(requireKey: true)
        }
    }

    /// Non-blocking first launch (a key already exists). Shows the full flow;
    /// the API-Key step is included only when `requireKey`. No-op if already up.
    func presentFirstLaunch(requireKey: Bool) {
        showWindow(requireKey: requireKey)
    }

    /// Re-open onboarding on demand (Settings → "Replay setup guide"). Opens even
    /// when `isComplete` because the user explicitly asked; starts at Welcome with
    /// no key page (a key already exists by now). `force` is accepted for call-site
    /// clarity — this always opens regardless.
    func present(force: Bool = false) {
        showWindow(requireKey: false)
    }

    // MARK: - View callbacks

    /// Called by the API-Key step once the user saves a valid key. Resumes the
    /// key gate exactly once (nil-guarded against a double-resume).
    func resolveKeyStep(saved: Bool) {
        guard let cont = keyContinuation else { return }
        keyContinuation = nil
        cont.resume(returning: saved)
    }

    /// Called by the Done step. Marks onboarding complete and closes the window.
    func finish() {
        markComplete()
        closeWindow()
    }

    // MARK: - Window lifecycle

    private func showWindow(requireKey: Bool) {
        // Never present two onboarding windows concurrently.
        if let window {
            NSApp.activate(ignoringOtherApps: true)
            window.makeKeyAndOrderFront(nil)
            return
        }

        let hosting = NSHostingView(rootView: OnboardingView(requireKey: requireKey))
        let win = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 640, height: 600),
            styleMask: [.titled, .closable, .fullSizeContentView],
            backing: .buffered,
            defer: false
        )
        win.titlebarAppearsTransparent = true
        win.titleVisibility = .hidden
        win.title = ""
        win.isReleasedWhenClosed = false
        win.contentView = hosting
        win.setContentSize(NSSize(width: 640, height: 600))
        win.center()

        // Detect user-close so a key-gated flow closed without a key resumes false.
        closeObserver = NotificationCenter.default.addObserver(
            forName: NSWindow.willCloseNotification,
            object: win,
            queue: .main
        ) { [weak self] _ in
            MainActor.assumeIsolated {
                self?.handleWindowClosed()
            }
        }

        window = win
        NSApp.activate(ignoringOtherApps: true)
        win.makeKeyAndOrderFront(nil)
    }

    /// Programmatic close (from `finish()`); routes through `willCloseNotification`.
    private func closeWindow() {
        window?.close()
    }

    /// Cleanup + key-gate resolution when the window goes away for any reason.
    private func handleWindowClosed() {
        if let observer = closeObserver {
            NotificationCenter.default.removeObserver(observer)
            closeObserver = nil
        }
        window = nil
        // Key gate still pending → the user closed without saving a key. The
        // resume is nil-guarded so a prior `resolveKeyStep(true)` can't double-fire.
        if let cont = keyContinuation {
            keyContinuation = nil
            cont.resume(returning: false)
        }
    }
}
