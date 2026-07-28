import SwiftUI
import AppKit

// MARK: - Proactive "Add to calendar?" Suggestion Prompt

/// A small, non-intrusive floating pill shown while Voxa is listening when it
/// detects a concrete scheduling agreement ("let's meet Friday at 3"):
/// "Add to your calendar?" with the event details + Add / dismiss. Does NOT
/// steal focus from the meeting (non-activating panel), and reads as a sibling
/// of the record prompt (MeetingPromptView) without being identical.
struct SuggestionPromptView: View {
    let title: String
    let whenText: String
    let onAdd: () -> Void
    let onDismiss: () -> Void

    @State private var appear = false
    @State private var pulse = false

    private var accent: LinearGradient {
        LinearGradient(colors: [.blue, Color(hue: 0.48, saturation: 0.7, brightness: 0.9)],
                       startPoint: .leading, endPoint: .trailing)
    }

    var body: some View {
        HStack(spacing: 11) {
            ZStack {
                Circle().fill(accent).frame(width: 34, height: 34)
                    .overlay(Circle().stroke(.white.opacity(0.25), lineWidth: 0.5))
                Image(systemName: "calendar.badge.plus")
                    .font(.system(size: 15, weight: .bold))
                    .foregroundStyle(.white)
                    .scaleEffect(pulse ? 1.12 : 0.92)
            }

            VStack(alignment: .leading, spacing: 1) {
                Text(title)
                    .font(.system(size: 12.5, weight: .semibold))
                    .lineLimit(1)
                Text(whenText)
                    .font(.system(size: 10.5))
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }

            Spacer(minLength: 6)

            Button(action: onAdd) {
                Text("Add")
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(.white)
                    .padding(.horizontal, 14)
                    .padding(.vertical, 6)
                    .background(Capsule().fill(Color.accentColor))
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
private final class SuggestionPanel: NSPanel {
    override var canBecomeKey: Bool { true }   // needed so the buttons receive clicks
    override var canBecomeMain: Bool { false }
}

/// Queue-based manager: suggestions can arrive back-to-back while a meeting is
/// running, so we enqueue them and present one at a time. Positioned top-center
/// but LOWER than the record prompt so the two proactive pills never overlap.
@MainActor
final class SuggestionPromptManager {
    static let shared = SuggestionPromptManager()

    private struct Item {
        let id: String
        let title: String
        let whenText: String
        let autoDismiss: Double
        let onAdd: () -> Void
        let onDismiss: () -> Void
    }

    private var panel: NSPanel?
    private var autoDismiss: DispatchWorkItem?
    private var queue: [Item] = []
    private var showing = false

    private init() {}

    /// Enqueue a suggestion pill. If nothing is currently displayed, present it
    /// immediately; otherwise it waits its turn. `onAdd`/`onDismiss` fire once.
    func show(id: String,
              title: String,
              whenText: String,
              autoDismissAfter seconds: Double = 30,
              onAdd: @escaping () -> Void,
              onDismiss: @escaping () -> Void) {
        queue.append(Item(id: id, title: title, whenText: whenText,
                          autoDismiss: seconds, onAdd: onAdd, onDismiss: onDismiss))
        presentNextIfIdle()
    }

    func hide() {
        autoDismiss?.cancel()
        autoDismiss = nil
        panel?.orderOut(nil)
        panel = nil
        showing = false
    }

    /// Drop any pending suggestions and hide the current one (e.g. the meeting
    /// ended, so stale suggestions shouldn't linger). Callbacks do NOT fire.
    func clearAll() {
        queue.removeAll()
        hide()
    }

    private func presentNextIfIdle() {
        guard !showing, !queue.isEmpty else { return }
        let item = queue.removeFirst()
        present(item)
    }

    private func present(_ item: Item) {
        showing = true

        let size = NSSize(width: 380, height: 60)
        var answered = false

        let advance: (@escaping () -> Void) -> Void = { [weak self] callback in
            guard !answered else { return }
            answered = true
            self?.hide()
            callback()
            // Present the next queued suggestion, if any.
            self?.presentNextIfIdle()
        }

        let view = SuggestionPromptView(
            title: item.title,
            whenText: item.whenText,
            onAdd: { advance(item.onAdd) },
            onDismiss: { advance(item.onDismiss) }
        )

        let host = NSHostingView(rootView: view)
        host.frame = NSRect(origin: .zero, size: size)

        let p = SuggestionPanel(
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

        // Position top-center, but lower than the record prompt so they never overlap.
        if let screen = NSScreen.main ?? NSScreen.screens.first {
            let vf = screen.visibleFrame
            p.setFrameOrigin(NSPoint(x: vf.midX - size.width / 2,
                                     y: vf.maxY - size.height - 78))
        }
        p.orderFrontRegardless()
        panel = p

        // Auto-dismiss (treated as "not now") so a forgotten prompt clears itself.
        if item.autoDismiss > 0 {
            let work = DispatchWorkItem { advance(item.onDismiss) }
            autoDismiss = work
            DispatchQueue.main.asyncAfter(deadline: .now() + item.autoDismiss, execute: work)
        }
    }
}
