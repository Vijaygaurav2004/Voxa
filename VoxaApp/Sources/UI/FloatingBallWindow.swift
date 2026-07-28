import SwiftUI
import AppKit

// MARK: - Floating Ball Window (NSPanel)

/// A frameless, always-on-top, draggable NSPanel that hosts the floating chat ball.
/// The ball can be dragged to any position on screen, like iPhone's AssistiveTouch.
/// Dragging is handled via SwiftUI DragGesture in FloatingBallView.
final class FloatingBallPanel: NSPanel {

    init(state: VoxaState, engine: VoxaEngine) {
        // Start at a reasonable size — expands when chat opens
        let initialSize = NSSize(width: 64, height: 64)

        super.init(
            contentRect: NSRect(origin: .zero, size: initialSize),
            styleMask: [.nonactivatingPanel, .borderless],
            backing: .buffered,
            defer: false
        )

        isOpaque = false
        backgroundColor = .clear
        hasShadow = false
        isFloatingPanel = true
        level = .floating                  // Above normal windows but below status bar
        collectionBehavior = [.canJoinAllSpaces, .stationary, .fullScreenAuxiliary]
        isMovableByWindowBackground = false // We handle dragging manually
        hidesOnDeactivate = false          // Stay visible when app loses focus
        animationBehavior = .utilityWindow

        let host = NSHostingView(
            rootView: FloatingBallContentView()
                .environmentObject(state)
                .environmentObject(engine)
        )
        host.frame = contentView?.bounds ?? .zero
        host.autoresizingMask = [.width, .height]
        contentView = host

        // Position: bottom-right of screen
        positionAtDefault()
    }

    // Allow the window to be placed anywhere (no automatic menu bar push-down)
    override func constrainFrameRect(_ frameRect: NSRect, to screen: NSScreen?) -> NSRect {
        return frameRect
    }

    // Don't become key window (don't steal focus from other apps)
    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { false }

    // MARK: - Native Drag Interception

    override func sendEvent(_ event: NSEvent) {
        if event.type == .leftMouseDown {
            let localPoint = event.locationInWindow
            // The ball is always a 56x56 square at the bottom-right of the window
            let ballRect = NSRect(
                x: frame.width - 56,
                y: 0,
                width: 56,
                height: 56
            )

            if ballRect.contains(localPoint) {
                let startLocation = NSEvent.mouseLocation
                var isDrag = false
                let mask: NSEvent.EventTypeMask = [.leftMouseUp, .leftMouseDragged]

                // Look ahead 150ms to see if mouse is held or dragged
                if let nextEvent = self.nextEvent(
                    matching: mask,
                    until: Date(timeIntervalSinceNow: 0.15),
                    inMode: RunLoop.Mode.default,
                    dequeue: false
                ) {
                    if nextEvent.type == NSEvent.EventType.leftMouseDragged {
                        let currentLoc = NSEvent.mouseLocation
                        let dx = currentLoc.x - startLocation.x
                        let dy = currentLoc.y - startLocation.y
                        if sqrt(dx*dx + dy*dy) > 3 {
                            isDrag = true
                        }
                    }
                } else {
                    // Timeout (held down without releasing) -> drag
                    isDrag = true
                }

                if isDrag {
                    // Call macOS native window dragging — 100% fluid, zero jitter
                    self.performDrag(with: event)
                    // Once dragging completes, snap to nearest screen edge
                    self.snapToNearestEdge()
                    return
                }
            }
        }
        super.sendEvent(event)
    }

    // MARK: - Positioning

    func positionAtDefault() {
        guard let screen = NSScreen.main ?? NSScreen.screens.first else { return }
        let margin: CGFloat = 24
        let x = screen.visibleFrame.maxX - frame.width - margin
        let y = screen.visibleFrame.midY
        setFrameOrigin(NSPoint(x: x, y: y))
    }

    // MARK: - Edge Snapping

    /// Snaps the window to the nearest horizontal screen edge with animation.
    /// Called from SwiftUI drag gesture's onEnded.
    func snapToNearestEdge() {
        guard let screen = NSScreen.main ?? NSScreen.screens.first else { return }
        let visible = screen.visibleFrame
        let margin: CGFloat = 8

        var newOrigin = frame.origin

        // Calculate distances to each horizontal edge
        let distLeft = frame.midX - visible.minX
        let distRight = visible.maxX - frame.midX

        // Snap horizontally to nearest edge
        if distLeft < distRight {
            newOrigin.x = visible.minX + margin
        } else {
            newOrigin.x = visible.maxX - frame.width - margin
        }

        // Clamp vertically within visible area
        newOrigin.y = max(visible.minY + margin, min(newOrigin.y, visible.maxY - frame.height - margin))

        // Animate snap
        NSAnimationContext.runAnimationGroup({ context in
            context.duration = 0.25
            context.timingFunction = CAMediaTimingFunction(name: .easeInEaseOut)
            self.animator().setFrameOrigin(newOrigin)
        })
    }

    // MARK: - Resize for Chat

    func updateSize(chatOpen: Bool) {
        let newSize: NSSize
        if chatOpen {
            newSize = NSSize(width: 360, height: 560)   // match the SwiftUI frame
        } else {
            newSize = NSSize(width: 64, height: 64)
        }

        // Anchor to the current bottom-right corner (where the ball sits)…
        var newOrigin = NSPoint(
            x: frame.maxX - newSize.width,
            y: frame.origin.y
        )

        // …then clamp fully on-screen. Without this, collapsing the chat back to
        // the ball after the panel was dragged near/over a screen edge can leave
        // the ball off-screen — i.e. pressing ✕ "loses" the button.
        newOrigin = Self.clampOnScreen(origin: newOrigin, size: newSize, screen: self.screen)

        NSAnimationContext.runAnimationGroup({ context in
            context.duration = 0.3
            context.timingFunction = CAMediaTimingFunction(name: .easeInEaseOut)
            self.animator().setFrame(
                NSRect(origin: newOrigin, size: newSize),
                display: true
            )
        })
    }

    /// Clamp a window rect so it stays fully within the given screen's visible
    /// area (margin from each edge). Used for collapse/expand and dragging.
    static func clampOnScreen(origin: NSPoint, size: NSSize, screen: NSScreen?, margin: CGFloat = 8) -> NSPoint {
        guard let screen = screen ?? NSScreen.main ?? NSScreen.screens.first else { return origin }
        let vis = screen.visibleFrame
        // Guard against a window larger than the screen (keep top-left visible).
        let maxX = max(vis.minX + margin, vis.maxX - size.width - margin)
        let maxY = max(vis.minY + margin, vis.maxY - size.height - margin)
        return NSPoint(
            x: min(max(origin.x, vis.minX + margin), maxX),
            y: min(max(origin.y, vis.minY + margin), maxY)
        )
    }
}

// MARK: - Content Wrapper View

/// Wrapper view that notifies the panel about chat state changes.
struct FloatingBallContentView: View {
    @EnvironmentObject var engine: VoxaEngine
    @EnvironmentObject var state: VoxaState

    var body: some View {
        FloatingBallView()
            .environmentObject(engine)
            .environmentObject(state)
    }
}

// MARK: - FloatingBallManager

/// Manages the lifecycle of the floating ball panel.
@MainActor
final class FloatingBallManager {
    static let shared = FloatingBallManager()
    private var panel: FloatingBallPanel?
    private var isVisible = false

    private init() {}

    func show() {
        guard !isVisible else { return }

        let state = VoxaState.shared
        let engine = VoxaEngine.shared

        let panel = FloatingBallPanel(state: state, engine: engine)
        panel.orderFront(nil)
        self.panel = panel
        isVisible = true
    }

    func hide() {
        panel?.orderOut(nil)
        panel = nil
        isVisible = false
    }

    /// Called by the SwiftUI ball view when the chat panel opens/closes so the
    /// host NSPanel grows/shrinks to fit — otherwise the chat is clipped to the
    /// collapsed 64×64 window and appears not to open.
    func setChatOpen(_ open: Bool) {
        panel?.updateSize(chatOpen: open)
    }

    // MARK: - Chat Panel Dragging

    // Window origin and global mouse position captured at drag start. Driving the
    // move from NSEvent.mouseLocation (global screen coords) keeps it smooth —
    // unlike SwiftUI's translation, which thrashes because the window it's
    // measured against is itself moving.
    private var dragStartOrigin: NSPoint?
    private var dragStartMouse: NSPoint?

    /// Begin dragging the chat panel by its header.
    func beginPanelDrag() {
        dragStartOrigin = panel?.frame.origin
        dragStartMouse = NSEvent.mouseLocation
    }

    /// Move the panel to follow the header drag, clamped fully on-screen.
    func updatePanelDrag() {
        guard let panel, let origin = dragStartOrigin, let startMouse = dragStartMouse else { return }
        let now = NSEvent.mouseLocation
        let target = NSPoint(x: origin.x + (now.x - startMouse.x),
                             y: origin.y + (now.y - startMouse.y))
        let clamped = FloatingBallPanel.clampOnScreen(origin: target, size: panel.frame.size, screen: panel.screen)
        panel.setFrameOrigin(clamped)
    }

    /// Finish the header drag.
    func endPanelDrag() {
        dragStartOrigin = nil
        dragStartMouse = nil
    }

    func toggle() {
        if isVisible {
            hide()
        } else {
            show()
        }
    }

    var isShowing: Bool { isVisible }
}
