import AppKit
import SwiftUI
import Carbon.HIToolbox

// MARK: - Carbon hot key

/// Registers a real system hot key. Unlike `NSEvent.addGlobalMonitorForEvents`
/// (which only observes), a Carbon hot key *consumes* the keystroke, so the
/// shortcut never leaks into whatever app is in front.
private final class CarbonHotKey {
    /// Carbon's callback is a bare C function pointer, so the handlers live here.
    static var onPressed: (() -> Void)?
    static var onReleased: (() -> Void)?

    private var hotKeyRef: EventHotKeyRef?
    private var handlerRef: EventHandlerRef?

    func register(_ spec: RadialHotkeySpec, wantsRelease: Bool) {
        unregister()

        var specs = [
            EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed)),
            EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyReleased)),
        ]

        InstallEventHandler(
            GetApplicationEventTarget(),
            { _, event, _ -> OSStatus in
                guard let event else { return noErr }
                let kind = GetEventKind(event)
                DispatchQueue.main.async {
                    if kind == UInt32(kEventHotKeyPressed) {
                        CarbonHotKey.onPressed?()
                    } else if kind == UInt32(kEventHotKeyReleased) {
                        CarbonHotKey.onReleased?()
                    }
                }
                return noErr
            },
            specs.count, &specs, nil, &handlerRef
        )

        // 'VOXA' as a four-char signature.
        let hotKeyID = EventHotKeyID(signature: OSType(0x564F5841), id: 1)
        let status = RegisterEventHotKey(
            spec.keyCode, spec.carbonModifiers, hotKeyID,
            GetApplicationEventTarget(), 0, &hotKeyRef
        )
        if status != noErr {
            appLog("[Radial] Failed to register hotkey \(spec.label) (status \(status))")
        } else {
            appLog("[Radial] Hotkey registered: \(spec.label)\(wantsRelease ? " (hold mode)" : "")")
        }
    }

    func unregister() {
        if let hotKeyRef { UnregisterEventHotKey(hotKeyRef) }
        hotKeyRef = nil
        if let handlerRef { RemoveEventHandler(handlerRef) }
        handlerRef = nil
    }

    deinit { unregister() }
}

// MARK: - Overlay panel

/// Full-screen, transparent, click-through-to-dismiss panel that hosts the wheel.
/// Covering the whole display means hover tracking and backdrop clicks are plain
/// SwiftUI gestures — no accessibility-gated global mouse monitors needed.
final class RadialPanel: NSPanel {

    init(screen: NSScreen, controller: RadialController, onDismiss: @escaping () -> Void) {
        super.init(
            contentRect: screen.frame,
            styleMask: [.nonactivatingPanel, .borderless],
            backing: .buffered,
            defer: false
        )

        isOpaque = false
        backgroundColor = .clear
        hasShadow = false
        isFloatingPanel = true
        level = .popUpMenu                       // above normal windows and the menu bar
        collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary, .ignoresCycle]
        hidesOnDeactivate = false
        animationBehavior = .none
        acceptsMouseMovedEvents = true
        isMovableByWindowBackground = false

        let host = NSHostingView(
            rootView: RadialMenuView(controller: controller, onDismiss: onDismiss)
        )
        host.frame = NSRect(origin: .zero, size: screen.frame.size)
        host.autoresizingMask = [.width, .height]
        contentView = host

        setFrame(screen.frame, display: false)
    }

    // Never let macOS nudge a full-screen overlay below the menu bar.
    override func constrainFrameRect(_ frameRect: NSRect, to _: NSScreen?) -> NSRect { frameRect }

    // Must become key to receive number/arrow/Esc keys.
    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { false }
}

// MARK: - Launcher

/// Owns the hot key, the overlay panel, and the key handling for the wheel.
@MainActor
final class RadialLauncher {
    static let shared = RadialLauncher()

    private let controller = RadialController.shared
    private let settings = RadialSettings.shared
    private let hotKey = CarbonHotKey()

    private var panel: RadialPanel?
    private var keyMonitor: Any?
    private var resignObserver: Any?
    /// The app that was in front when we opened, so focus can be handed back.
    private weak var previousApp: NSRunningApplication?

    private(set) var isOpen = false

    private init() {}

    // MARK: Lifecycle

    /// Called once at app launch, and again whenever settings change.
    func start() { applySettings() }

    func applySettings() {
        hotKey.unregister()
        CarbonHotKey.onPressed = nil
        CarbonHotKey.onReleased = nil

        guard settings.enabled else {
            if isOpen { dismiss() }
            appLog("[Radial] Launcher disabled")
            return
        }

        let holdMode = settings.trigger == .hold
        CarbonHotKey.onPressed = { [weak self] in
            guard let self else { return }
            if holdMode {
                if !self.isOpen { self.show() }
            } else {
                self.toggle()
            }
        }
        CarbonHotKey.onReleased = { [weak self] in
            guard let self, holdMode, self.isOpen else { return }
            // Release fires whatever the pointer is aiming at. Aiming at a
            // folder branches it out instead of closing, so you can keep going.
            if let hovered = self.controller.hovered {
                if self.controller.activate(hovered) { self.dismiss() }
            } else {
                self.dismiss()
            }
        }

        hotKey.register(settings.hotkey, wantsRelease: holdMode)
    }

    func stop() {
        dismiss()
        hotKey.unregister()
        CarbonHotKey.onPressed = nil
        CarbonHotKey.onReleased = nil
    }

    // MARK: Show / hide

    func toggle() { isOpen ? dismiss() : show() }

    func show() {
        guard settings.enabled, !isOpen else { return }

        let mouse = NSEvent.mouseLocation
        let screen = NSScreen.screens.first { $0.frame.contains(mouse) }
            ?? NSScreen.main
            ?? NSScreen.screens.first
        guard let screen else { return }

        controller.reset()
        controller.center = wheelCenter(mouse: mouse, screen: screen)

        // Remember who had focus so Esc can hand it straight back.
        let front = NSWorkspace.shared.frontmostApplication
        previousApp = (front?.bundleIdentifier == Bundle.main.bundleIdentifier) ? nil : front

        let panel = RadialPanel(screen: screen, controller: controller) { [weak self] in
            self?.dismiss()
        }
        self.panel = panel

        installKeyMonitor()

        // A launcher has to take key focus to read number keys; focus is returned
        // in `dismiss()` when nothing that opens its own window was fired.
        NSApp.activate(ignoringOtherApps: true)
        panel.makeKeyAndOrderFront(nil)
        isOpen = true

        // Close if focus moves elsewhere, so the wheel can't be left floating on
        // another display. Armed after a beat because activation itself can
        // briefly bounce key status around.
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.35) { [weak self, weak panel] in
            MainActor.assumeIsolated {
                guard let self, self.isOpen, let panel, self.panel === panel else { return }
                self.resignObserver = NotificationCenter.default.addObserver(
                    forName: NSWindow.didResignKeyNotification, object: panel, queue: .main
                ) { [weak self] _ in
                    MainActor.assumeIsolated { self?.dismiss() }
                }
            }
        }
    }

    func dismiss() {
        guard isOpen else { return }
        isOpen = false

        removeKeyMonitor()
        if let resignObserver { NotificationCenter.default.removeObserver(resignObserver) }
        resignObserver = nil
        panel?.orderOut(nil)
        panel = nil

        // Don't fight an app we just launched for the foreground.
        if !controller.lastActivationStealsFocus, let previousApp {
            previousApp.activate()
        }
        self.previousApp = nil
        controller.hovered = nil
    }

    /// Where the wheel sits, clamped so it never runs off the display.
    /// A position the user dragged to (pinned) wins over both other modes.
    private func wheelCenter(mouse: NSPoint, screen: NSScreen) -> CGPoint {
        let size = screen.frame.size
        let raw: CGPoint
        if let pin = settings.pinnedFraction {
            raw = CGPoint(x: pin.x * size.width, y: pin.y * size.height)
        } else if settings.showAtCursor {
            // Screen coords are bottom-left origin; SwiftUI's are top-left.
            raw = CGPoint(x: mouse.x - screen.frame.minX,
                          y: size.height - (mouse.y - screen.frame.minY))
        } else {
            raw = CGPoint(x: size.width / 2, y: size.height / 2)
        }

        return CGPoint(
            x: RadialGeometry.clampAxis(raw.x, extent: size.width, scale: settings.scale),
            y: RadialGeometry.clampAxis(raw.y, extent: size.height, scale: settings.scale)
        )
    }

    // MARK: Keyboard

    /// A local monitor intercepts keys before SwiftUI sees them, so digits and
    /// arrows drive the wheel instead of being swallowed by the hosting view.
    /// Scroll events are captured here too, which is how resize works.
    private func installKeyMonitor() {
        removeKeyMonitor()
        keyMonitor = NSEvent.addLocalMonitorForEvents(matching: [.keyDown, .scrollWheel]) { [weak self] event in
            // The monitor is app-wide, so it must not touch events aimed at
            // Voxa's other windows — otherwise typing in Settings or scrolling
            // a list would be swallowed and reinterpreted as wheel input.
            // `event.window` is the key window for .keyDown and the window under
            // the pointer for .scrollWheel, so this is tighter than isKeyWindow:
            // a scroll over another Voxa window passes straight through.
            guard let self, self.isOpen,
                  let panel = self.panel, event.window === panel else { return event }
            if event.type == .scrollWheel {
                self.handleScroll(event)
                return nil
            }
            return self.handle(event) ? nil : event
        }
    }

    /// Scroll anywhere over the overlay to resize the wheel live.
    private func handleScroll(_ event: NSEvent) {
        // Trackpads report small continuous deltas; wheels report coarse lines.
        let raw = event.hasPreciseScrollingDeltas
            ? Double(event.scrollingDeltaY) * 0.004
            : Double(event.scrollingDeltaY) * 0.04
        guard raw != 0 else { return }
        controller.nudgeScale(by: raw)
    }

    private func removeKeyMonitor() {
        if let keyMonitor { NSEvent.removeMonitor(keyMonitor) }
        keyMonitor = nil
    }

    /// Returns true when the key was consumed by the wheel.
    private func handle(_ event: NSEvent) -> Bool {
        switch Int(event.keyCode) {
        case kVK_Escape:
            dismiss()
            return true

        case kVK_Return, kVK_ANSI_KeypadEnter:
            if let hovered = controller.hovered, controller.activate(hovered, viaKeyboard: true) { dismiss() }
            return true

        case kVK_Delete, kVK_ForwardDelete:
            if controller.canGoBack { controller.goBack() } else { dismiss() }
            return true

        case kVK_LeftArrow:
            controller.pageCount(ring: controller.activeRingIndex) > 1
                ? controller.previousPage() : controller.step(-1)
            return true

        case kVK_RightArrow:
            controller.pageCount(ring: controller.activeRingIndex) > 1
                ? controller.nextPage() : controller.step(1)
            return true

        case kVK_UpArrow:
            controller.step(-1)
            return true

        case kVK_DownArrow:
            controller.step(1)
            return true

        case kVK_Tab:
            controller.step(event.modifierFlags.contains(.shift) ? -1 : 1)
            return true

        case kVK_Space:
            // Space confirms, but only when it isn't the trigger being held.
            if settings.trigger == .toggle, let hovered = controller.hovered {
                if controller.activate(hovered, viaKeyboard: true) { dismiss() }
                return true
            }
            return false

        default:
            guard let characters = event.charactersIgnoringModifiers, !characters.isEmpty else { return false }
            // Ignore chorded input so ⌘Q etc. still reach the app.
            guard !event.modifierFlags.contains(.command) else { return false }
            if controller.activate(character: characters) { dismiss() }
            return true
        }
    }
}
