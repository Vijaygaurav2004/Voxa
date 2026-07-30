import Foundation
import AppKit
import SwiftUI

// MARK: - What a slice does

/// The kinds of thing a radial slice can be bound to.
///
/// `.submenu` is what makes the wheel a *launcher* rather than a flat menu — a
/// slice with children drills into its own ring (the "•••" slices in the design).
enum RadialKind: String, Codable, CaseIterable, Identifiable {
    case app        // target = bundle id ("com.apple.Safari") or app name ("Safari")
    case url        // target = https://…
    case path       // target = a file or folder path (~ is expanded)
    case shell      // target = a shell command
    case command    // target = a natural-language Voxa command (full AI pipeline)
    case mode       // target = a Voxa mode name
    case listen     // start a voice command (same as the ⌘⇧V hotkey)
    case submenu    // children = a nested ring

    var id: String { rawValue }

    var title: String {
        switch self {
        case .app:     return "Open App"
        case .url:     return "Open URL"
        case .path:    return "Open File / Folder"
        case .shell:   return "Run Shell Command"
        case .command: return "Voxa Command"
        case .mode:    return "Activate Mode"
        case .listen:  return "Start Listening"
        case .submenu: return "Folder (nested ring)"
        }
    }

    var placeholder: String {
        switch self {
        case .app:     return "Safari  or  com.apple.Safari"
        case .url:     return "https://github.com"
        case .path:    return "~/Downloads"
        case .shell:   return "open -a Terminal"
        case .command: return "turn on do not disturb"
        case .mode:    return "Work Mode"
        case .listen:  return "—"
        case .submenu: return "—"
        }
    }

    /// Kinds that take no target value.
    var isTargetless: Bool { self == .listen || self == .submenu }

    var defaultSymbol: String {
        switch self {
        case .app:     return "app"
        case .url:     return "globe"
        case .path:    return "folder"
        case .shell:   return "terminal"
        case .command: return "sparkles"
        case .mode:    return "slider.horizontal.3"
        case .listen:  return "mic"
        case .submenu: return "square.grid.2x2"
        }
    }
}

// MARK: - A slice

struct RadialItem: Codable, Identifiable, Hashable {
    var id: UUID = UUID()
    var title: String
    var kind: RadialKind
    var target: String = ""
    /// SF Symbol used when no real app icon can be resolved.
    var symbol: String = "square.grid.2x2"
    /// Optional custom keyboard shortcut ("c"). Defaults to the slot number.
    var shortcut: String? = nil
    var children: [RadialItem] = []

    init(
        id: UUID = UUID(),
        _ title: String,
        _ kind: RadialKind,
        target: String = "",
        symbol: String? = nil,
        shortcut: String? = nil,
        children: [RadialItem] = []
    ) {
        self.id = id
        self.title = title
        self.kind = kind
        self.target = target
        self.symbol = symbol ?? kind.defaultSymbol
        self.shortcut = shortcut
        self.children = children
    }

    var isSubmenu: Bool { kind == .submenu }

    /// Decoding is lenient so a catalogue written by an older build (or hand
    /// edited) still loads instead of wiping the user's wheel.
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id       = (try? c.decode(UUID.self, forKey: .id)) ?? UUID()
        title    = (try? c.decode(String.self, forKey: .title)) ?? "Untitled"
        kind     = (try? c.decode(RadialKind.self, forKey: .kind)) ?? .command
        target   = (try? c.decode(String.self, forKey: .target)) ?? ""
        symbol   = (try? c.decode(String.self, forKey: .symbol)) ?? kind.defaultSymbol
        shortcut = try? c.decodeIfPresent(String.self, forKey: .shortcut)
        children = (try? c.decode([RadialItem].self, forKey: .children)) ?? []
    }
}

// MARK: - Icon resolution

enum RadialIcon {
    private static var cache: [String: NSImage] = [:]

    /// The real macOS icon for an app slice, or nil to fall back to an SF Symbol.
    static func appIcon(for item: RadialItem) -> NSImage? {
        guard item.kind == .app || item.kind == .path else { return nil }
        let key = "\(item.kind.rawValue):\(item.target)"
        if let hit = cache[key] { return hit }

        var image: NSImage?
        switch item.kind {
        case .app:
            if let url = AppCatalog.url(forAppNamedOrBundleID: item.target) {
                image = NSWorkspace.shared.icon(forFile: url.path)
            }
        case .path:
            let path = (item.target as NSString).expandingTildeInPath
            if FileManager.default.fileExists(atPath: path) {
                image = NSWorkspace.shared.icon(forFile: path)
            }
        default:
            break
        }

        if let image {
            image.size = NSSize(width: 44, height: 44)
            cache[key] = image
        }
        return image
    }

    static func clearCache() { cache.removeAll() }
}

// MARK: - Installed application lookup

enum AppCatalog {
    private static let searchDirs: [URL] = {
        var dirs = [
            URL(fileURLWithPath: "/Applications"),
            URL(fileURLWithPath: "/System/Applications"),
            URL(fileURLWithPath: "/System/Applications/Utilities"),
            URL(fileURLWithPath: "/Applications/Utilities"),
        ]
        dirs.append(URL(fileURLWithPath: NSHomeDirectory()).appendingPathComponent("Applications"))
        return dirs
    }()

    /// Resolve "Safari", "safari", or "com.apple.Safari" to an app bundle URL.
    static func url(forAppNamedOrBundleID value: String) -> URL? {
        let v = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !v.isEmpty else { return nil }

        // Looks like a bundle id — ask LaunchServices directly (cheapest, exact).
        if v.contains("."), !v.hasSuffix(".app"),
           let url = NSWorkspace.shared.urlForApplication(withBundleIdentifier: v) {
            return url
        }
        // An explicit path.
        if v.hasPrefix("/") || v.hasPrefix("~") {
            let p = (v as NSString).expandingTildeInPath
            if FileManager.default.fileExists(atPath: p) { return URL(fileURLWithPath: p) }
        }
        // A display name — scan the usual folders.
        let wanted = v.hasSuffix(".app") ? v : v + ".app"
        for dir in searchDirs {
            let candidate = dir.appendingPathComponent(wanted)
            if FileManager.default.fileExists(atPath: candidate.path) { return candidate }
        }
        // Case-insensitive sweep as a last resort.
        for dir in searchDirs {
            guard let entries = try? FileManager.default.contentsOfDirectory(atPath: dir.path) else { continue }
            if let hit = entries.first(where: { $0.caseInsensitiveCompare(wanted) == .orderedSame }) {
                return dir.appendingPathComponent(hit)
            }
        }
        return nil
    }

    static func isInstalled(_ value: String) -> Bool { url(forAppNamedOrBundleID: value) != nil }

    /// Every installed app, de-duplicated and sorted — used by the picker.
    static func allInstalled() -> [(name: String, url: URL)] {
        var seen = Set<String>()
        var out: [(String, URL)] = []
        for dir in searchDirs {
            guard let entries = try? FileManager.default.contentsOfDirectory(atPath: dir.path) else { continue }
            for entry in entries where entry.hasSuffix(".app") {
                let name = String(entry.dropLast(4))
                guard !seen.contains(name.lowercased()) else { continue }
                seen.insert(name.lowercased())
                out.append((name, dir.appendingPathComponent(entry)))
            }
        }
        return out.sorted { $0.0.localizedCaseInsensitiveCompare($1.0) == .orderedAscending }
    }

    /// First installed app from a preference list — lets the shipped defaults
    /// adapt to whatever this particular Mac actually has.
    static func firstInstalled(_ candidates: [String]) -> String? {
        candidates.first(where: isInstalled)
    }
}

// MARK: - Default wheel

enum RadialDefaults {

    /// A sensible starter wheel, built from what's actually installed on this Mac.
    static func catalogue() -> [RadialItem] {
        var items: [RadialItem] = []

        if let term = AppCatalog.firstInstalled(["Ghostty", "iTerm", "Warp", "Terminal"]) {
            items.append(RadialItem(term, .app, target: term, symbol: "terminal", shortcut: "1"))
        }
        if let notes = AppCatalog.firstInstalled(["Obsidian", "Notion", "Bear", "Notes"]) {
            items.append(RadialItem(notes, .app, target: notes, symbol: "note.text", shortcut: "2"))
        }
        if let browser = AppCatalog.firstInstalled(["Arc", "Google Chrome", "Safari"]) {
            items.append(RadialItem(browser, .app, target: browser, symbol: "safari", shortcut: "3"))
        }
        if let music = AppCatalog.firstInstalled(["Spotify", "Music"]) {
            items.append(RadialItem(music, .app, target: music, symbol: "music.note", shortcut: "4"))
        }
        if let editor = AppCatalog.firstInstalled(["Cursor", "Visual Studio Code", "Zed", "Xcode"]) {
            items.append(RadialItem(editor, .app, target: editor, symbol: "chevron.left.forwardslash.chevron.right", shortcut: "5"))
        }

        items.append(RadialItem("Folders", .submenu, symbol: "folder", shortcut: "6", children: [
            RadialItem("Home",       .path, target: "~",             symbol: "house"),
            RadialItem("Desktop",    .path, target: "~/Desktop",     symbol: "menubar.dock.rectangle"),
            RadialItem("Documents",  .path, target: "~/Documents",   symbol: "doc"),
            RadialItem("Downloads",  .path, target: "~/Downloads",   symbol: "arrow.down.circle"),
            RadialItem("Applications", .path, target: "/Applications", symbol: "square.grid.3x3"),
            RadialItem("Voxa Data",  .path, target: "~/.voxa",       symbol: "internaldrive"),
        ]))

        items.append(RadialItem("System", .submenu, symbol: "gearshape", shortcut: "7", children: [
            RadialItem("Settings",   .app,   target: "System Settings", symbol: "gearshape"),
            RadialItem("Wi-Fi",      .shell, target: "open 'x-apple.systempreferences:com.apple.wifi-settings-extension'", symbol: "wifi"),
            RadialItem("Bluetooth",  .shell, target: "open 'x-apple.systempreferences:com.apple.BluetoothSettings'", symbol: "dot.radiowaves.right"),
            RadialItem("Displays",   .shell, target: "open 'x-apple.systempreferences:com.apple.Displays-Settings-Extension'", symbol: "display"),
            RadialItem("Dark Mode",  .command, target: "toggle dark mode", symbol: "circle.lefthalf.filled"),
            RadialItem("Do Not Disturb", .command, target: "turn on do not disturb", symbol: "moon"),
            RadialItem("Lock Screen", .shell, target: "pmset displaysleepnow", symbol: "lock"),
        ]))

        items.append(RadialItem("Utility", .submenu, symbol: "wrench.and.screwdriver", shortcut: "8", children: [
            RadialItem("Screenshot",  .shell, target: "screencapture -i ~/Desktop/Screenshot-$(date +%H%M%S).png", symbol: "camera.viewfinder"),
            RadialItem("Activity",    .app,   target: "Activity Monitor", symbol: "chart.bar"),
            RadialItem("Calculator",  .app,   target: "Calculator", symbol: "plusminus"),
            RadialItem("Empty Trash", .shell, target: "osascript -e 'tell application \"Finder\" to empty trash'", symbol: "trash"),
            RadialItem("Battery",     .command, target: "what is my battery level", symbol: "battery.100"),
        ]))

        items.append(RadialItem("Voxa", .submenu, symbol: "waveform", shortcut: "9", children: [
            RadialItem("Listen",       .listen,  symbol: "mic"),
            RadialItem("What's on screen", .command, target: "what is on my screen", symbol: "eye"),
            RadialItem("Today's Calendar", .command, target: "what is on my calendar today", symbol: "calendar"),
            RadialItem("Recap Today",  .command, target: "summarise the last 24 hours", symbol: "text.book.closed"),
        ]))

        items.append(RadialItem("Clipboard", .command,
                                target: "what is in my clipboard",
                                symbol: "clipboard", shortcut: "c"))

        return items
    }
}

// MARK: - Persistent catalogue

/// The user's wheel, stored at `~/.voxa/radial.json`.
@MainActor
final class RadialCatalog: ObservableObject {
    static let shared = RadialCatalog()

    @Published var items: [RadialItem] = [] {
        didSet { scheduleSave() }
    }

    private static var fileURL: URL {
        VoxaConfig.userConfigDir.appendingPathComponent("radial.json")
    }

    private var saveWorkItem: DispatchWorkItem?

    private init() {
        if let loaded = Self.load(), !loaded.isEmpty {
            items = loaded
        } else {
            items = RadialDefaults.catalogue()
            save()
        }
    }

    // MARK: Disk

    private static func load() -> [RadialItem]? {
        guard let data = try? Data(contentsOf: fileURL) else { return nil }
        return try? JSONDecoder().decode([RadialItem].self, from: data)
    }

    /// Coalesce rapid edits (typing in the editor) into one write.
    private func scheduleSave() {
        saveWorkItem?.cancel()
        let work = DispatchWorkItem { [weak self] in
            MainActor.assumeIsolated { self?.save() }
        }
        saveWorkItem = work
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.4, execute: work)
    }

    func save() {
        do {
            try FileManager.default.createDirectory(
                at: VoxaConfig.userConfigDir, withIntermediateDirectories: true)
            let encoder = JSONEncoder()
            encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
            try encoder.encode(items).write(to: Self.fileURL, options: .atomic)
        } catch {
            appLog("[Radial] Failed to save catalogue: \(error.localizedDescription)")
        }
    }

    func resetToDefaults() {
        RadialIcon.clearCache()
        items = RadialDefaults.catalogue()
        save()
    }

    // MARK: Mutation helpers (used by the editor page)

    /// Resolve a path of indices into a nested item list.
    func items(at path: [Int]) -> [RadialItem] {
        var current = items
        for index in path {
            guard index < current.count else { return [] }
            current = current[index].children
        }
        return current
    }

    func replace(at path: [Int], with newItems: [RadialItem]) {
        if path.isEmpty {
            items = newItems
        } else {
            var root = items
            Self.assign(newItems, in: &root, path: path)
            items = root
        }
    }

    private static func assign(_ newItems: [RadialItem], in list: inout [RadialItem], path: [Int]) {
        guard let head = path.first, head < list.count else { return }
        if path.count == 1 {
            list[head].children = newItems
        } else {
            assign(newItems, in: &list[head].children, path: Array(path.dropFirst()))
        }
    }
}
