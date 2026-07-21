import SwiftUI
import AppKit

// MARK: - Floating Orb Panel (NSPanel)

/// A frameless, always-on-top panel that hosts the Siri-style orb overlay.
/// Uses NSPanel so it floats above other app windows and appears on all Spaces.
final class VoxaOrbPanel: NSPanel {
    init(state: VoxaState) {
        super.init(
            contentRect: .init(x: 0, y: 0, width: 260, height: 280),
            styleMask: [.nonactivatingPanel, .borderless],
            backing: .buffered,
            defer: false
        )
        isOpaque = false
        backgroundColor = .clear
        hasShadow = false            // SwiftUI view draws its own shadow
        isFloatingPanel = true
        level = .statusBar           // Floats above the menu bar level to wrap the notch
        collectionBehavior = [.canJoinAllSpaces, .stationary]
        isMovableByWindowBackground = true

        let host = NSHostingView(
            rootView: OverlayView()
                .environmentObject(state)
        )
        host.frame = contentView?.bounds ?? .zero
        host.autoresizingMask = [.width, .height]
        contentView = host

        // Position dynamic frame correctly from the start
        updateFrame(for: state)
    }

    // Override constrainFrameRect to prevent macOS from automatically shifting the window below the menu bar
    override func constrainFrameRect(_ frameRect: NSRect, to screen: NSScreen?) -> NSRect {
        return frameRect
    }

    func updateFrame(for state: VoxaState) {
        // Fallback to the primary screen if NSScreen.main is not active/available.
        guard let screen = NSScreen.main ?? NSScreen.screens.first else { return }
        
        let calculatedNotchRect: NSRect
        if #available(macOS 12.0, *) {
            if let rect = screen.notchRect {
                calculatedNotchRect = rect
            } else {
                // Fallback simulated notch in the top center of the screen
                let w: CGFloat = 180
                let h: CGFloat = 32
                calculatedNotchRect = NSRect(
                    x: screen.frame.midX - w / 2,
                    y: screen.frame.maxY - h,
                    width: w,
                    height: h
                )
            }
        } else {
            // Fallback simulated notch in the top center of the screen
            let w: CGFloat = 180
            let h: CGFloat = 32
            calculatedNotchRect = NSRect(
                x: screen.frame.midX - w / 2,
                y: screen.frame.maxY - h,
                width: w,
                height: h
            )
        }
        
        // Update the state's notchRect
        if state.notchRect != calculatedNotchRect {
            state.notchRect = calculatedNotchRect
        }
        
        let width = state.useNotchHalo ? (calculatedNotchRect.width + 180) : 260
        let height = state.useNotchHalo ? (calculatedNotchRect.height + 120) : 280
        
        let x: CGFloat
        let y: CGFloat
        
        if state.useNotchHalo {
            // Align the panel centered horizontally on the notch and hugging the screen's top edge
            x = calculatedNotchRect.midX - width / 2
            y = screen.frame.maxY - height
        } else {
            // Centre-right position (matches default Siri placement style)
            x = screen.visibleFrame.maxX - 300
            y = screen.visibleFrame.midY - 140
        }
        
        let newFrame = NSRect(x: x, y: y, width: width, height: height)
        if frame != newFrame {
            setFrame(newFrame, display: true, animate: false)
        }
    }
}

// MARK: - App Delegate

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    var orbPanel: VoxaOrbPanel?
    private var stateObserver: Any?

    func applicationDidFinishLaunching(_ notification: Notification) {
        let state = VoxaState.shared
        orbPanel = VoxaOrbPanel(state: state)

        // Show/hide the floating panel synchronously on the main queue.
        // We use DispatchQueue.main.async (not Task) so orderFront fires on
        // the very next runloop tick — no async scheduling overhead.
        stateObserver = NotificationCenter.default.addObserver(
            forName: .voxaStateChanged,
            object: nil,
            queue: .main
        ) { [weak self] _ in
            // NotificationCenter guarantees delivery on .main queue.
            // MainActor.assumeIsolated satisfies the compiler without async overhead.
            MainActor.assumeIsolated {
                guard let self, let panel = self.orbPanel else { return }
                panel.updateFrame(for: state)
                if state.isOverlayVisible {
                    // Instant — same runloop tick
                    panel.orderFront(nil)
                } else {
                    // Brief hold so fade-out SwiftUI animation can play
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { [weak self] in
                        guard self != nil, !state.isOverlayVisible else { return }
                        panel.orderOut(nil)
                    }
                }
            }
        }

        // Show the floating chat ball
        FloatingBallManager.shared.show()
    }

    func applicationWillTerminate(_ notification: Notification) {
        VoxaEngine.shared.stop()
    }
}

// MARK: - Notification name

extension Notification.Name {
    static let voxaStateChanged = Notification.Name("voxaStateChanged")
}

// MARK: - Main App

/// Main Voxa macOS menu bar application.
@main
struct VoxaApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var appDelegate
    @StateObject private var engine = VoxaEngine.shared
    @StateObject private var state = VoxaState.shared

    var body: some Scene {
        // Menu bar extra — no Dock icon, just a menu bar presence
        MenuBarExtra {
            MenuBarView()
                .environmentObject(engine)
                .environmentObject(state)
        } label: {
            Label {
                Text("Voxa")
            } icon: {
                Image(systemName: state.menuBarIcon)
                    .symbolRenderingMode(.hierarchical)
                    .foregroundStyle(state.pipelineState == .listening ? .cyan : .primary)
            }
        }
        .menuBarExtraStyle(.window)
    }
}
