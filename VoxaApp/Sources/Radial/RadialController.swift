import Foundation
import AppKit
import SwiftUI
import Carbon.HIToolbox

// MARK: - Launcher settings

/// How the wheel is summoned.
enum RadialTrigger: String, Codable, CaseIterable, Identifiable {
    /// Tap the hotkey to open; it stays up until you pick something or hit Esc.
    case toggle
    /// Hold the hotkey down, aim with the mouse, release to fire.
    case hold

    var id: String { rawValue }
    var title: String { self == .toggle ? "Tap to open" : "Hold to aim" }
    var detail: String {
        self == .toggle
            ? "Press the shortcut once. Click a slice, press its key, or hit Esc."
            : "Hold the shortcut, move the mouse to aim, release to launch."
    }
}

/// A registerable global shortcut.
struct RadialHotkeySpec: Codable, Equatable, Hashable, Identifiable {
    var keyCode: UInt32
    var carbonModifiers: UInt32
    var label: String

    var id: String { "\(keyCode)-\(carbonModifiers)" }

    /// The presets offered in Settings. Deliberately avoids ⌘Space (Spotlight)
    /// and ⌘⇧V (Voxa's own push-to-talk).
    static let presets: [RadialHotkeySpec] = [
        .init(keyCode: UInt32(kVK_Space),      carbonModifiers: UInt32(optionKey),              label: "⌥ Space"),
        .init(keyCode: UInt32(kVK_Space),      carbonModifiers: UInt32(controlKey),             label: "⌃ Space"),
        .init(keyCode: UInt32(kVK_Space),      carbonModifiers: UInt32(cmdKey | shiftKey),      label: "⌘⇧ Space"),
        .init(keyCode: UInt32(kVK_ANSI_R),     carbonModifiers: UInt32(cmdKey | optionKey),     label: "⌘⌥ R"),
        .init(keyCode: UInt32(kVK_ANSI_Grave), carbonModifiers: UInt32(optionKey),              label: "⌥ `"),
        .init(keyCode: UInt32(kVK_Tab),        carbonModifiers: UInt32(controlKey | optionKey), label: "⌃⌥ Tab"),
    ]

    static let `default` = presets[0]

    /// The Cocoa modifier set matching `carbonModifiers`.
    var cocoaModifiers: NSEvent.ModifierFlags {
        var flags: NSEvent.ModifierFlags = []
        if carbonModifiers & UInt32(cmdKey)     != 0 { flags.insert(.command) }
        if carbonModifiers & UInt32(optionKey)  != 0 { flags.insert(.option) }
        if carbonModifiers & UInt32(controlKey) != 0 { flags.insert(.control) }
        if carbonModifiers & UInt32(shiftKey)   != 0 { flags.insert(.shift) }
        return flags
    }
}

@MainActor
final class RadialSettings: ObservableObject {
    static let shared = RadialSettings()

    private enum Keys {
        static let enabled    = "voxa.launcher.enabled"
        static let trigger    = "voxa.launcher.trigger"
        static let hotkey     = "voxa.launcher.hotkey"
        static let slots      = "voxa.launcher.slots"
        static let atCursor   = "voxa.launcher.atCursor"
        static let labels     = "voxa.launcher.showLabels"
        static let closeAfter = "voxa.launcher.closeAfterLaunch"
        static let scale      = "voxa.launcher.scale"
        static let pinX       = "voxa.launcher.pinX"
        static let pinY       = "voxa.launcher.pinY"
        static let hasPin     = "voxa.launcher.hasPin"
        static let dwell      = "voxa.launcher.dwellToExpand"
    }

    /// Master on/off. Everything else is inert while this is false.
    @Published var enabled: Bool {
        didSet {
            UserDefaults.standard.set(enabled, forKey: Keys.enabled)
            RadialLauncher.shared.applySettings()
        }
    }
    @Published var trigger: RadialTrigger {
        didSet {
            UserDefaults.standard.set(trigger.rawValue, forKey: Keys.trigger)
            RadialLauncher.shared.applySettings()
        }
    }
    @Published var hotkey: RadialHotkeySpec {
        didSet {
            if let data = try? JSONEncoder().encode(hotkey) {
                UserDefaults.standard.set(data, forKey: Keys.hotkey)
            }
            RadialLauncher.shared.applySettings()
        }
    }
    /// Slices in the root ring.
    @Published var slots: Int {
        didSet { UserDefaults.standard.set(slots, forKey: Keys.slots) }
    }
    /// Open at the pointer (true) or centred on the active screen (false).
    /// A pinned position overrides both.
    @Published var showAtCursor: Bool {
        didSet { UserDefaults.standard.set(showAtCursor, forKey: Keys.atCursor) }
    }
    @Published var showLabels: Bool {
        didSet { UserDefaults.standard.set(showLabels, forKey: Keys.labels) }
    }
    @Published var closeAfterLaunch: Bool {
        didSet { UserDefaults.standard.set(closeAfterLaunch, forKey: Keys.closeAfter) }
    }
    /// Overall wheel size multiplier. Adjustable live with the scroll wheel.
    @Published var scale: Double {
        didSet {
            let clamped = min(Self.maxScale, max(Self.minScale, scale))
            if clamped != scale { scale = clamped; return }
            UserDefaults.standard.set(scale, forKey: Keys.scale)
        }
    }
    /// Where the user dragged the wheel to, as a fraction of the screen
    /// (0…1 on both axes) so it survives resolution and display changes.
    @Published var pinnedFraction: CGPoint? {
        didSet {
            let d = UserDefaults.standard
            if let pinnedFraction {
                d.set(pinnedFraction.x, forKey: Keys.pinX)
                d.set(pinnedFraction.y, forKey: Keys.pinY)
                d.set(true, forKey: Keys.hasPin)
            } else {
                d.set(false, forKey: Keys.hasPin)
            }
        }
    }
    /// Expand a folder's children by hovering it, rather than requiring a click.
    @Published var dwellToExpand: Bool {
        didSet { UserDefaults.standard.set(dwellToExpand, forKey: Keys.dwell) }
    }

    static let minScale = 0.55
    static let maxScale = 1.9

    var isPinned: Bool { pinnedFraction != nil }

    private init() {
        let d = UserDefaults.standard
        d.register(defaults: [
            Keys.enabled: true,
            Keys.slots: 10,
            Keys.atCursor: true,
            Keys.labels: true,
            Keys.closeAfter: true,
            Keys.scale: 1.0,
            Keys.hasPin: false,
            Keys.dwell: true,
        ])
        enabled          = d.bool(forKey: Keys.enabled)
        slots            = max(4, min(14, d.integer(forKey: Keys.slots)))
        showAtCursor     = d.bool(forKey: Keys.atCursor)
        showLabels       = d.bool(forKey: Keys.labels)
        closeAfterLaunch = d.bool(forKey: Keys.closeAfter)
        dwellToExpand    = d.bool(forKey: Keys.dwell)
        let rawScale     = d.double(forKey: Keys.scale)
        scale            = rawScale == 0 ? 1.0 : min(Self.maxScale, max(Self.minScale, rawScale))
        pinnedFraction   = d.bool(forKey: Keys.hasPin)
            ? CGPoint(x: d.double(forKey: Keys.pinX), y: d.double(forKey: Keys.pinY))
            : nil
        trigger          = RadialTrigger(rawValue: d.string(forKey: Keys.trigger) ?? "") ?? .toggle
        if let data = d.data(forKey: Keys.hotkey),
           let spec = try? JSONDecoder().decode(RadialHotkeySpec.self, from: data) {
            hotkey = spec
        } else {
            hotkey = .default
        }
    }
}

// MARK: - Ring

/// One concentric ring of slices. Ring 0 is the full 360° root; deeper rings are
/// fans centred on the parent slice they branched from.
struct RadialRing: Identifiable {
    let id = UUID()
    var items: [RadialItem]
    var page: Int = 0
    /// Slot in the previous ring that opened this one (nil for the root).
    var parentSlot: Int?
    /// Centre angle of that parent slice — the fan is centred here.
    var centreAngle: Double?

    var isRoot: Bool { centreAngle == nil }
}

/// Which slice the pointer (or keyboard) is on.
struct RadialTarget: Equatable {
    var ring: Int
    var slot: Int
}

// MARK: - Wheel state machine

/// Drives one open wheel: the stack of concentric rings, what's under the
/// pointer, drag/resize, and what happens when a slice fires.
@MainActor
final class RadialController: ObservableObject {
    static let shared = RadialController()

    private let catalog = RadialCatalog.shared
    private let settings = RadialSettings.shared

    /// rings[0] is the root; each subsequent entry is a branched-out fan.
    @Published private(set) var rings: [RadialRing] = []
    @Published var hovered: RadialTarget? = nil
    /// The ring the keyboard and the hub's page controls act on. Sticky on
    /// purpose: it follows the pointer *onto* a ring but does not reset when the
    /// pointer merely leaves the ring band — otherwise moving inward to click
    /// the ‹ › arrows would retarget them to a different ring first.
    @Published private(set) var focusedRing: Int = 0
    /// Centre of the wheel in the panel's SwiftUI coordinate space.
    @Published var center: CGPoint = .zero
    /// True while the user is dragging the wheel by its hub.
    @Published var isDragging = false
    /// Bumped on every open so the view can replay its entry animation.
    @Published private(set) var generation: Int = 0

    /// True when the last thing fired brings its own app forward, so the
    /// launcher knows not to steal focus back.
    private(set) var lastActivationStealsFocus = false

    /// Pending hover-to-expand, cancelled whenever the hover target changes.
    private var expandWork: DispatchWorkItem?

    private init() {}

    // MARK: Derived state

    var scale: Double { settings.scale }
    var deepestRing: Int { max(0, rings.count - 1) }
    var slotsPerPage: Int { max(4, min(14, settings.slots)) }

    func ring(_ index: Int) -> RadialRing? {
        index >= 0 && index < rings.count ? rings[index] : nil
    }

    /// Items drawn on the current page of a ring.
    func visibleItems(ring index: Int) -> [RadialItem] {
        guard let ring = ring(index) else { return [] }
        let start = ring.page * slotsPerPage
        guard start < ring.items.count else { return [] }
        return Array(ring.items[start..<min(start + slotsPerPage, ring.items.count)])
    }

    func pageCount(ring index: Int) -> Int {
        guard let ring = ring(index) else { return 1 }
        return max(1, Int(ceil(Double(ring.items.count) / Double(slotsPerPage))))
    }

    /// Slices the root ring is divided into. A partly-filled last page still
    /// draws a full ring so geometry doesn't jump between pages.
    func sliceCount(ring index: Int) -> Int {
        guard index == 0 else { return visibleItems(ring: index).count }
        let count = visibleItems(ring: 0).count
        return pageCount(ring: 0) > 1 ? slotsPerPage : max(1, min(slotsPerPage, count))
    }

    func item(ring: Int, slot: Int) -> RadialItem? {
        let items = visibleItems(ring: ring)
        return slot >= 0 && slot < items.count ? items[slot] : nil
    }

    var hoveredItem: RadialItem? {
        guard let hovered else { return nil }
        return item(ring: hovered.ring, slot: hovered.slot)
    }

    /// Global index (1-based) of a slot, for the "3 / 5" hub readout.
    func globalIndex(_ target: RadialTarget) -> Int {
        (ring(target.ring)?.page ?? 0) * slotsPerPage + target.slot + 1
    }

    /// Breadcrumb title shown in the hub when nothing is hovered.
    var levelTitle: String {
        if rings.count > 1, let parent = rings[rings.count - 1].parentSlot,
           let item = item(ring: rings.count - 2, slot: parent) {
            return item.title
        }
        return "Voxa"
    }

    var canGoBack: Bool { rings.count > 1 }

    /// Keyboard label for a slot: the item's override, else 1-9, 0, then a-z.
    ///
    /// Only the root ring carries shortcuts. Branched fans would otherwise
    /// repeat the same "1, 2, 3…" as the root and the key would be ambiguous —
    /// children are reached with the arrows / Return instead.
    func shortcutLabel(ring: Int, slot: Int) -> String {
        guard ring == 0 else { return "" }
        if let custom = item(ring: ring, slot: slot)?.shortcut, !custom.isEmpty {
            return custom.lowercased()
        }
        let n = (self.ring(ring)?.page ?? 0) * slotsPerPage + slot
        if n < 9 { return String(n + 1) }
        if n == 9 { return "0" }
        let letters = Array("abcdefghijklmnopqrstuvwxyz")
        let offset = n - 10
        return offset < letters.count ? String(letters[offset]) : "•"
    }

    // MARK: Geometry

    /// Angular layout of a ring: where its first slice starts and how wide each is.
    func layout(ring index: Int) -> (start: Double, perSlice: Double) {
        guard let ring = ring(index), let centre = ring.centreAngle else {
            let count = max(1, sliceCount(ring: 0))
            return (0, 360.0 / Double(count))
        }
        let count = max(1, visibleItems(ring: index).count)
        // Keep child wedges a comfortable width until the fan would overrun.
        let per = count <= 9 ? 34.0 : (340.0 / Double(count))
        let span = per * Double(count)
        return (centre - span / 2, per)
    }

    /// Centre angle of a slice, used to place its contents and to centre the
    /// fan of any ring it branches into.
    func centreAngle(ring index: Int, slot: Int) -> Double {
        let l = layout(ring: index)
        return l.start + (Double(slot) + 0.5) * l.perSlice
    }

    // MARK: Lifecycle

    func reset() {
        cancelExpand()
        rings = [RadialRing(items: catalog.items)]
        hovered = nil
        focusedRing = 0
        isDragging = false
        lastActivationStealsFocus = false
        generation &+= 1
    }

    // MARK: Navigation

    /// Close the deepest branched ring.
    func goBack() {
        guard rings.count > 1 else { return }
        cancelExpand()
        rings.removeLast()
        hovered = nil
        focusedRing = min(focusedRing, rings.count - 1)
    }

    /// Collapse every ring deeper than `index`.
    func collapse(deeperThan index: Int) {
        // Drop any pending dwell FIRST. A page flip routes through here while
        // rings.count is still index+1 — which is exactly when an expand is
        // scheduled — so an early return here would let it fire against the
        // new page and fan out a slice nobody hovered.
        cancelExpand()
        guard rings.count > index + 1 else { return }
        rings.removeSubrange((index + 1)...)
        // Never leave hover or focus pointing into a ring that no longer exists.
        if let current = hovered, current.ring > index { hovered = nil }
        focusedRing = min(focusedRing, index)
    }

    func nextPage() {
        let index = activeRingIndex
        guard pageCount(ring: index) > 1 else { return }
        collapse(deeperThan: index)
        rings[index].page = (rings[index].page + 1) % pageCount(ring: index)
        hovered = nil
    }

    func previousPage() {
        let index = activeRingIndex
        guard pageCount(ring: index) > 1 else { return }
        collapse(deeperThan: index)
        let count = pageCount(ring: index)
        rings[index].page = (rings[index].page - 1 + count) % count
        hovered = nil
    }

    /// The ring the keyboard and page controls act on, always within bounds.
    var activeRingIndex: Int { min(max(0, focusedRing), max(0, rings.count - 1)) }

    /// Move the highlight around the active ring, so the wheel is fully
    /// driveable without a mouse.
    func step(_ delta: Int) {
        let index = activeRingIndex
        let count = visibleItems(ring: index).count
        guard count > 0 else { return }
        if let current = hovered, current.ring == index {
            setHover(RadialTarget(ring: index, slot: (current.slot + delta + count) % count))
        } else {
            setHover(RadialTarget(ring: index, slot: delta > 0 ? 0 : count - 1))
        }
    }

    // MARK: Hit testing

    /// Slice under `point`, searching the outermost ring first so a branched fan
    /// wins over the root ring it overlaps.
    func hitTest(_ point: CGPoint) -> RadialTarget? {
        for index in stride(from: rings.count - 1, through: 0, by: -1) {
            if let slot = slot(inRing: index, at: point) {
                return RadialTarget(ring: index, slot: slot)
            }
        }
        return nil
    }

    private func slot(inRing index: Int, at point: CGPoint) -> Int? {
        let dx = point.x - center.x
        let dy = point.y - center.y
        let distance = sqrt(dx * dx + dy * dy)
        guard distance >= RadialGeometry.inner(ring: index, scale: scale),
              distance <= RadialGeometry.outer(ring: index, scale: scale) else { return nil }

        var degrees = atan2(Double(dx), Double(-dy)) * 180 / .pi
        if degrees < 0 { degrees += 360 }

        let count = visibleItems(ring: index).count
        guard count > 0 else { return nil }
        let l = layout(ring: index)

        if index == 0 {
            let slot = Int(degrees / l.perSlice)
            return slot < count ? slot : nil
        }
        // Branched fan: measure relative to its start, handling wraparound.
        var relative = (degrees - l.start).truncatingRemainder(dividingBy: 360)
        if relative < 0 { relative += 360 }
        let span = l.perSlice * Double(count)
        guard relative < span else { return nil }
        let slot = Int(relative / l.perSlice)
        return slot < count ? slot : nil
    }

    /// True when the pointer is inside the hub (drag handle / back target).
    func isInHub(_ point: CGPoint) -> Bool {
        let dx = point.x - center.x
        let dy = point.y - center.y
        return sqrt(dx * dx + dy * dy) < RadialGeometry.hubRadius * scale
    }

    // MARK: Hover + branch-out

    /// Update the hovered slice, and schedule any ring change behind a dwell.
    ///
    /// BOTH collapsing a stale branch and expanding a folder are debounced, and
    /// that is load-bearing. The rings do not overlap radially (ring 0 ends at
    /// 196, ring 1 starts at 203), so travelling from a parent slice to a child
    /// on the far side of its fan necessarily crosses *other* root slices. If
    /// the collapse fired immediately, the fan would be destroyed mid-gesture
    /// and every child outside the parent's own wedge would be unreachable by
    /// mouse. Deferring it means a pointer merely passing through leaves the fan
    /// intact, while a pointer that actually settles still switches branches.
    func setHover(_ target: RadialTarget?) {
        guard target != hovered else { return }
        cancelExpand()

        guard let target else {
            hovered = nil
            return
        }

        let sameBranch = rings.count > target.ring + 1
            && rings[target.ring + 1].parentSlot == target.slot
        let needsCollapse = target.ring < deepestRing && !sameBranch

        // The highlight itself tracks the pointer with no delay.
        hovered = target
        focusedRing = target.ring

        let hit = item(ring: target.ring, slot: target.slot)
        let wantsExpand = settings.dwellToExpand
            && (hit?.isSubmenu ?? false)
            && !(hit?.children.isEmpty ?? true)

        guard needsCollapse || wantsExpand else { return }

        let work = DispatchWorkItem { [weak self] in
            MainActor.assumeIsolated {
                guard let self else { return }
                if needsCollapse { self.collapse(deeperThan: target.ring) }
                // `expand` no-ops when this branch is already showing.
                if wantsExpand { self.expand(target) }
            }
        }
        expandWork = work
        // Tearing a fan down is held off noticeably longer than building one up,
        // so a slow hand crossing intervening slices on the way to a child does
        // not lose the fan, while settling on another slice still switches.
        let delay = needsCollapse ? 0.38 : 0.16
        DispatchQueue.main.asyncAfter(deadline: .now() + delay, execute: work)
    }

    private func cancelExpand() {
        expandWork?.cancel()
        expandWork = nil
    }

    /// Branch a folder's children out into a new concentric ring.
    ///
    /// `enterIt` moves the highlight into the new fan — what you want from the
    /// keyboard (Return on a folder should step you inside), but not from a
    /// mouse dwell, where the pointer is still physically on the parent slice.
    func expand(_ target: RadialTarget, enterIt: Bool = false) {
        guard let item = item(ring: target.ring, slot: target.slot),
              item.isSubmenu, !item.children.isEmpty else { return }

        // Already showing this branch — just step inside if asked.
        if rings.count > target.ring + 1,
           rings[target.ring + 1].parentSlot == target.slot {
            if enterIt { enterRing(target.ring + 1) }
            return
        }

        collapse(deeperThan: target.ring)
        rings.append(RadialRing(
            items: item.children,
            parentSlot: target.slot,
            centreAngle: centreAngle(ring: target.ring, slot: target.slot)
        ))
        if enterIt { enterRing(target.ring + 1) }
    }

    /// Put the highlight on the first slice of a ring.
    private func enterRing(_ index: Int) {
        guard index < rings.count, !visibleItems(ring: index).isEmpty else { return }
        hovered = RadialTarget(ring: index, slot: 0)
        focusedRing = index
    }

    // MARK: Drag

    func beginDrag() {
        cancelExpand()
        isDragging = true
        hovered = nil
    }

    func drag(to point: CGPoint, in size: CGSize) {
        center = CGPoint(
            x: RadialGeometry.clampAxis(point.x, extent: size.width, scale: scale),
            y: RadialGeometry.clampAxis(point.y, extent: size.height, scale: scale)
        )
    }

    /// Pin the wheel where it was dropped, as a screen fraction so it survives
    /// display changes.
    func endDrag(in size: CGSize) {
        isDragging = false
        guard size.width > 0, size.height > 0 else { return }
        settings.pinnedFraction = CGPoint(x: center.x / size.width, y: center.y / size.height)
    }

    // MARK: Resize

    /// Live resize from the scroll wheel.
    func nudgeScale(by delta: Double) {
        settings.scale = min(RadialSettings.maxScale,
                             max(RadialSettings.minScale, settings.scale + delta))
    }

    // MARK: Activation

    /// Fire a slice. Returns true when the wheel should close.
    ///
    /// `viaKeyboard` makes a folder step you inside the fan it opens, so the
    /// arrows can keep going; a mouse click just fans it out and leaves the
    /// highlight under the pointer.
    @discardableResult
    func activate(_ target: RadialTarget, viaKeyboard: Bool = false) -> Bool {
        guard let item = item(ring: target.ring, slot: target.slot) else { return false }

        if item.isSubmenu {
            guard !item.children.isEmpty else { return false }
            expand(target, enterIt: viaKeyboard)   // branch out, stay open
            return false
        }

        perform(item)
        return settings.closeAfterLaunch
    }

    /// Activate whatever a keyboard character maps to. Only the root ring
    /// carries shortcuts, so there is exactly one candidate and no ambiguity
    /// with a branched fan. Returns true to close.
    @discardableResult
    func activate(character: String) -> Bool {
        let needle = character.lowercased()
        guard !needle.isEmpty else { return false }
        for slot in visibleItems(ring: 0).indices
        where shortcutLabel(ring: 0, slot: slot) == needle {
            return activate(RadialTarget(ring: 0, slot: slot), viaKeyboard: true)
        }
        return false
    }

    /// Run a non-submenu item.
    func perform(_ item: RadialItem) {
        appLog("[Radial] Activating \(item.kind.rawValue): \(item.title)")

        // App / URL / Finder targets pull the foreground themselves.
        lastActivationStealsFocus = (item.kind == .app || item.kind == .url || item.kind == .path)

        switch item.kind {
        case .app:
            guard let url = AppCatalog.url(forAppNamedOrBundleID: item.target) else {
                appLog("[Radial] App not found: \(item.target)")
                return
            }
            let config = NSWorkspace.OpenConfiguration()
            config.activates = true
            NSWorkspace.shared.openApplication(at: url, configuration: config)

        case .url:
            var raw = item.target.trimmingCharacters(in: .whitespacesAndNewlines)
            if !raw.isEmpty, !raw.contains("://") { raw = "https://" + raw }
            if let url = URL(string: raw) { NSWorkspace.shared.open(url) }

        case .path:
            let expanded = (item.target as NSString).expandingTildeInPath
            guard !expanded.isEmpty else { return }
            NSWorkspace.shared.open(URL(fileURLWithPath: expanded))

        case .shell:
            runShell(item.target)

        case .command:
            let text = item.target.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !text.isEmpty else { return }
            Task { await VoxaEngine.shared.processCommand(text) }

        case .mode:
            let name = item.target.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !name.isEmpty else { return }
            Task { _ = try? await PythonBridge.shared.activateMode(name: name) }

        case .listen:
            Task { await VoxaEngine.shared.triggerVoiceCommand() }

        case .submenu:
            break
        }
    }

    /// Detached login shell so `~`, PATH and aliases behave like a Terminal run.
    private func runShell(_ command: String) {
        let trimmed = command.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/bin/zsh")
        process.arguments = ["-lc", trimmed]
        process.currentDirectoryURL = URL(fileURLWithPath: NSHomeDirectory())
        process.standardOutput = FileHandle.nullDevice
        process.standardError = FileHandle.nullDevice
        do {
            try process.run()
        } catch {
            appLog("[Radial] Shell command failed: \(error.localizedDescription)")
        }
    }
}
