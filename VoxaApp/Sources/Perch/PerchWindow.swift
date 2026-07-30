import SwiftUI
import AppKit

// MARK: - Panel

/// The perch itself: a borderless panel hugging the top edge of the screen,
/// centred on the notch. It is intentionally *not* activating — pointing at the
/// notch should reveal the shelf without stealing focus from what you're doing.
final class PerchPanel: NSPanel {

    init(screen: NSScreen, content: NSView) {
        super.init(
            contentRect: NSRect(origin: .zero, size: NSSize(width: 100, height: 100)),
            styleMask: [.nonactivatingPanel, .borderless],
            backing: .buffered,
            defer: false
        )
        isOpaque = false
        backgroundColor = .clear
        hasShadow = false                 // the SwiftUI shell draws its own
        isFloatingPanel = true
        level = .statusBar                // above the menu bar, like the notch
        collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary, .ignoresCycle]
        hidesOnDeactivate = false
        animationBehavior = .none
        acceptsMouseMovedEvents = true

        content.autoresizingMask = [.width, .height]
        contentView = content
    }

    /// Never let macOS push a top-edge window down below the menu bar.
    override func constrainFrameRect(_ frameRect: NSRect, to _: NSScreen?) -> NSRect { frameRect }

    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { false }
}

// MARK: - Manager

/// Owns the panel, the hover detection at the notch, and the expand/collapse
/// state machine.
@MainActor
final class PerchManager: ObservableObject {
    static let shared = PerchManager()

    private let settings = PerchSettings.shared

    /// Collapsed shows only a thin sliver under the notch; expanded is the shelf.
    @Published var isOpen = false
    @Published var tab: PerchTab = .home

    private var panel: PerchPanel?
    private var hoverMonitor: Any?
    private var screenObserver: Any?
    private var screen: NSScreen?
    /// Guards against the pointer skimming past the notch on its way elsewhere.
    private var openWork: DispatchWorkItem?
    private var closeWork: DispatchWorkItem?

    /// Height of the always-present hover strip when collapsed.
    private let collapsedHeight: CGFloat = 8
    private let hoverPadding: CGFloat = 14

    private init() {}

    // MARK: Lifecycle

    func start() { applySettings() }

    func applySettings() {
        guard settings.enabled else {
            teardown()
            appLog("[Perch] Disabled")
            return
        }
        if panel == nil { build() }
        resize()
        installHoverMonitor()
    }

    func stop() { teardown() }

    private func teardown() {
        removeHoverMonitor()
        cancelPending()
        panel?.orderOut(nil)
        panel = nil
        isOpen = false
        PerchNowPlaying.shared.stop()
        PerchSnippetsStore.shared.stopWatching()
    }

    private func build() {
        let target = targetScreen()
        self.screen = target

        let host = NSHostingView(rootView: PerchRootView(manager: self))
        let panel = PerchPanel(screen: target, content: host)
        self.panel = panel
        panel.orderFront(nil)

        PerchNowPlaying.shared.start()
        PerchSnippetsStore.shared.startWatching()
        appLog("[Perch] Ready on \(target.localizedName)")
    }

    private func targetScreen() -> NSScreen {
        // Prefer a screen that actually has a notch; that's where a perch belongs.
        if !settings.allDisplays, let notched = NSScreen.screens.first(where: { $0.notchRect != nil }) {
            return notched
        }
        return NSScreen.main ?? NSScreen.screens.first!
    }

    // MARK: Geometry

    /// Recompute the panel frame for the current open/closed state and size.
    func resize() {
        guard let panel else { return }
        let target = targetScreen()
        screen = target

        let width = CGFloat(settings.width)
        let height = isOpen ? CGFloat(settings.height) : collapsedHeight
        let anchorX = notchCentreX(on: target)

        let frame = NSRect(
            x: anchorX - width / 2,
            y: target.frame.maxY - height,
            width: width,
            height: height
        )
        panel.setFrame(frame, display: true)

        // Collapsed, the panel is a sliver lying directly over the menu bar. If
        // it stayed hit-testable it would swallow every menu-bar click, so it
        // only accepts the mouse while it is actually open. Hover detection uses
        // a global monitor and is unaffected.
        panel.ignoresMouseEvents = !isOpen
    }

    /// Horizontal centre of the notch, falling back to the screen centre on
    /// displays without one.
    private func notchCentreX(on screen: NSScreen) -> CGFloat {
        screen.notchRect?.midX ?? screen.frame.midX
    }

    /// Width of the physical notch, used to leave a gap in the tab bar.
    var notchWidth: CGFloat {
        guard let screen = screen ?? NSScreen.main else { return 180 }
        return screen.notchRect?.width ?? 180
    }

    // MARK: Open / close

    func open() {
        cancelPending()
        guard !isOpen else { return }
        isOpen = true
        resize()
    }

    func close() {
        cancelPending()
        guard isOpen else { return }
        isOpen = false
        resize()
    }

    /// Cancel AND clear both dwell items. Clearing matters: `evaluateHover`
    /// only schedules a close when `closeWork == nil`, so leaving a cancelled
    /// item in place would permanently disable auto-close.
    private func cancelPending() {
        openWork?.cancel();  openWork = nil
        closeWork?.cancel(); closeWork = nil
    }

    func toggle() { isOpen ? close() : open() }

    func show(tab: PerchTab) {
        self.tab = tab
        open()
    }

    // MARK: Hover

    /// A global mouse-moved monitor is the only way to notice the pointer
    /// arriving at the notch while another app is frontmost. It observes only —
    /// it never consumes events.
    private func installHoverMonitor() {
        removeHoverMonitor()
        guard settings.openOnHover else { return }
        // `.leftMouseDragged` is essential, not a nicety: while a button is held
        // macOS posts drag events INSTEAD of `.mouseMoved`. Without it the perch
        // can never open under a file being dragged toward the notch, which
        // makes the Tray's whole drop target unreachable.
        hoverMonitor = NSEvent.addGlobalMonitorForEvents(
            matching: [.mouseMoved, .leftMouseDragged]
        ) { [weak self] _ in
            MainActor.assumeIsolated { self?.evaluateHover() }
        }
        screenObserver = NotificationCenter.default.addObserver(
            forName: NSApplication.didChangeScreenParametersNotification,
            object: nil, queue: .main
        ) { [weak self] _ in
            // Re-anchor after a display is added, removed or rearranged —
            // otherwise both the panel and the hot zone stay on a stale screen.
            MainActor.assumeIsolated { self?.resize() }
        }
    }

    private func removeHoverMonitor() {
        if let hoverMonitor { NSEvent.removeMonitor(hoverMonitor) }
        hoverMonitor = nil
        if let screenObserver { NotificationCenter.default.removeObserver(screenObserver) }
        screenObserver = nil
    }

    private func evaluateHover() {
        guard settings.enabled, let panel, let screen = screen ?? NSScreen.main else { return }
        let mouse = NSEvent.mouseLocation

        // A presented sheet (note editor, snippet editor, add-preset) extends
        // BELOW the panel, so moving onto it leaves `panel.frame` and would
        // otherwise auto-close the shelf — destroying the editor and the user's
        // unsaved text with it. Never collapse while a sheet is up.
        if panel.attachedSheet != nil {
            closeWork?.cancel(); closeWork = nil
            return
        }

        if isOpen {
            // Stay open while the pointer is anywhere over the shelf.
            let inside = panel.frame.insetBy(dx: -hoverPadding, dy: -hoverPadding).contains(mouse)
            if inside {
                closeWork?.cancel(); closeWork = nil
            } else if closeWork == nil {
                let work = DispatchWorkItem { [weak self] in
                    MainActor.assumeIsolated { self?.closeWork = nil; self?.close() }
                }
                closeWork = work
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.45, execute: work)
            }
            return
        }

        // Closed: open when the pointer settles in the notch's hot zone.
        let hot = hotZone(on: screen)
        if hot.contains(mouse) {
            if openWork == nil {
                let work = DispatchWorkItem { [weak self] in
                    MainActor.assumeIsolated { self?.openWork = nil; self?.open() }
                }
                openWork = work
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.18, execute: work)
            }
        } else {
            openWork?.cancel(); openWork = nil
        }
    }

    /// The strip of screen that reveals the perch — the notch itself, widened a
    /// little so it is comfortable to hit.
    private func hotZone(on screen: NSScreen) -> NSRect {
        let notch = screen.notchRect
        let width = (notch?.width ?? 200) + 90
        let height: CGFloat = notch?.height ?? 34
        let centreX = notch?.midX ?? screen.frame.midX
        return NSRect(x: centreX - width / 2,
                      y: screen.frame.maxY - height,
                      width: width,
                      height: height)
    }
}
