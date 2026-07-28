import SwiftUI
import AppKit

// MARK: - Minimal Meeting Prompt (Granola-style)

/// A small, non-intrusive floating pill shown near the notch when a meeting is
/// detected: "Record & take notes?" with Record / dismiss. Does NOT steal focus
/// from the meeting (non-activating panel), unlike a modal NSAlert.
struct MeetingPromptView: View {
    let platform: String
    let onRecord: () -> Void
    let onDismiss: () -> Void

    @State private var appear = false
    @State private var pulse = false

    private var accent: LinearGradient {
        LinearGradient(colors: [Color(hue: 0.75, saturation: 0.7, brightness: 0.95), .blue],
                       startPoint: .leading, endPoint: .trailing)
    }

    var body: some View {
        HStack(spacing: 11) {
            ZStack {
                Circle().fill(accent).frame(width: 34, height: 34)
                    .overlay(Circle().stroke(.white.opacity(0.25), lineWidth: 0.5))
                Image(systemName: "waveform")
                    .font(.system(size: 15, weight: .bold))
                    .foregroundStyle(.white)
                    .scaleEffect(pulse ? 1.12 : 0.92)
            }

            VStack(alignment: .leading, spacing: 1) {
                Text("\(platform) meeting detected")
                    .font(.system(size: 12.5, weight: .semibold))
                Text("Record & take notes?")
                    .font(.system(size: 10.5))
                    .foregroundStyle(.secondary)
            }

            Spacer(minLength: 6)

            Button(action: onRecord) {
                Text("Record")
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(.white)
                    .padding(.horizontal, 14)
                    .padding(.vertical, 6)
                    .background(Capsule().fill(accent))
            }
            .buttonStyle(.plain)

            Button(action: onDismiss) {
                Image(systemName: "xmark")
                    .font(.system(size: 10, weight: .bold))
                    .foregroundStyle(.secondary)
                    .padding(6)
                    .background(Circle().fill(Color.primary.opacity(0.08)))
            }
            .buttonStyle(.plain)
            .help("Dismiss")
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 9)
        .background(
            RoundedRectangle(cornerRadius: 20, style: .continuous)
                .fill(.ultraThinMaterial)
        )
        .overlay(
            RoundedRectangle(cornerRadius: 20, style: .continuous)
                .strokeBorder(Color.white.opacity(0.12), lineWidth: 1)
        )
        .shadow(color: .black.opacity(0.28), radius: 18, y: 8)
        .scaleEffect(appear ? 1 : 0.92)
        .opacity(appear ? 1 : 0)
        .onAppear {
            withAnimation(.spring(response: 0.35, dampingFraction: 0.7)) { appear = true }
            withAnimation(.easeInOut(duration: 1.0).repeatForever(autoreverses: true)) { pulse = true }
        }
    }
}

// MARK: - Panel host

/// Borderless, non-activating panel so the pill floats over the meeting without
/// stealing keyboard/window focus.
private final class MeetingPromptPanel: NSPanel {
    override var canBecomeKey: Bool { true }   // needed so the buttons receive clicks
    override var canBecomeMain: Bool { false }
}

@MainActor
final class MeetingPromptManager {
    static let shared = MeetingPromptManager()
    private var panel: NSPanel?
    private var autoDismiss: DispatchWorkItem?

    private init() {}

    /// Show the pill near the notch. `onRecord`/`onDismiss` fire once, then hide.
    func show(platform: String,
              autoDismissAfter seconds: Double = 30,
              onRecord: @escaping () -> Void,
              onDismiss: @escaping () -> Void) {
        hide()

        let size = NSSize(width: 372, height: 60)
        var answered = false

        let view = MeetingPromptView(
            platform: platform,
            onRecord: { [weak self] in
                guard !answered else { return }
                answered = true
                self?.hide()
                onRecord()
            },
            onDismiss: { [weak self] in
                guard !answered else { return }
                answered = true
                self?.hide()
                onDismiss()
            }
        )

        let host = NSHostingView(rootView: view)
        host.frame = NSRect(origin: .zero, size: size)

        let p = MeetingPromptPanel(
            contentRect: NSRect(origin: .zero, size: size),
            styleMask: [.nonactivatingPanel, .borderless],
            backing: .buffered,
            defer: false
        )
        p.isOpaque = false
        p.backgroundColor = .clear
        p.hasShadow = false
        p.isFloatingPanel = true
        p.level = .statusBar
        p.hidesOnDeactivate = false
        p.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary]
        p.contentView = host

        // Position top-center, just under the menu bar / notch.
        if let screen = NSScreen.main ?? NSScreen.screens.first {
            let vf = screen.visibleFrame
            p.setFrameOrigin(NSPoint(x: vf.midX - size.width / 2,
                                     y: vf.maxY - size.height - 10))
        }
        p.orderFrontRegardless()
        panel = p

        // Auto-dismiss (treated as "not now") so a forgotten prompt clears itself.
        if seconds > 0 {
            let work = DispatchWorkItem {
                guard !answered else { return }
                answered = true
                self.hide()
                onDismiss()
            }
            autoDismiss = work
            DispatchQueue.main.asyncAfter(deadline: .now() + seconds, execute: work)
        }
    }

    func hide() {
        autoDismiss?.cancel()
        autoDismiss = nil
        panel?.orderOut(nil)
        panel = nil
    }
}
