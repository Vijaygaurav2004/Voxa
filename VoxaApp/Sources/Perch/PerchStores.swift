import SwiftUI
import AppKit
import Combine

/// Everything the perch persists lives under ~/.voxa/perch/.
enum PerchPaths {
    static var root: URL {
        let url = VoxaConfig.userConfigDir.appendingPathComponent("perch")
        try? FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        return url
    }
    static var notes: URL    { root.appendingPathComponent("notes.json") }
    static var snippets: URL { root.appendingPathComponent("snippets.json") }
    static var timers: URL   { root.appendingPathComponent("timers.json") }
    static var trayDir: URL {
        let url = root.appendingPathComponent("tray")
        try? FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        return url
    }
}

/// Tiny JSON helper — every store is small enough that atomic whole-file writes
/// are simpler and safer than anything incremental.
private enum PerchDisk {
    static func load<T: Decodable>(_ type: T.Type, from url: URL) -> T? {
        guard let data = try? Data(contentsOf: url) else { return nil }
        return try? JSONDecoder().decode(type, from: data)
    }
    static func save<T: Encodable>(_ value: T, to url: URL) {
        do {
            let encoder = JSONEncoder()
            encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
            try encoder.encode(value).write(to: url, options: .atomic)
        } catch {
            appLog("[Perch] Save failed for \(url.lastPathComponent): \(error.localizedDescription)")
        }
    }
}

// MARK: - Notes

struct PerchNote: Codable, Identifiable, Equatable {
    var id: UUID = UUID()
    var title: String
    var body: String
    var symbol: String = "note.text"
    var updated: Date = Date()

    var preview: String {
        body.replacingOccurrences(of: "\n", with: " ")
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }
}

@MainActor
final class PerchNotesStore: ObservableObject {
    static let shared = PerchNotesStore()

    @Published private(set) var notes: [PerchNote] = []
    /// Newest-first vs A-Z, toggled by the sort button.
    @Published var sortAlphabetical = false
    @Published var query = ""

    private init() {
        notes = PerchDisk.load([PerchNote].self, from: PerchPaths.notes) ?? Self.starter()
        if PerchDisk.load([PerchNote].self, from: PerchPaths.notes) == nil { save() }
    }

    var filtered: [PerchNote] {
        let base = query.trimmed.isEmpty ? notes : notes.filter {
            $0.title.localizedCaseInsensitiveContains(query) ||
            $0.body.localizedCaseInsensitiveContains(query)
        }
        return sortAlphabetical
            ? base.sorted { $0.title.localizedCaseInsensitiveCompare($1.title) == .orderedAscending }
            : base.sorted { $0.updated > $1.updated }
    }

    @discardableResult
    func add(title: String = "New Note", body: String = "") -> PerchNote {
        let note = PerchNote(title: title, body: body)
        notes.insert(note, at: 0)
        save()
        return note
    }

    func update(_ note: PerchNote) {
        guard let index = notes.firstIndex(where: { $0.id == note.id }) else { return }
        var updated = note
        updated.updated = Date()
        notes[index] = updated
        save()
    }

    func delete(_ note: PerchNote) {
        notes.removeAll { $0.id == note.id }
        save()
    }

    func duplicate(_ note: PerchNote) {
        var copy = note
        copy.id = UUID()
        copy.title = note.title + " copy"
        copy.updated = Date()
        notes.insert(copy, at: 0)
        save()
    }

    private func save() { PerchDisk.save(notes, to: PerchPaths.notes) }

    private static func starter() -> [PerchNote] {
        [
            PerchNote(title: "Meeting Notes", body: "Discuss budget allocation for new projects. Review team performance metrics.", symbol: "bookmark.fill"),
            PerchNote(title: "Weekend Ideas", body: "Build a small herb garden on the balcony. Organise photo albums from the summer trip.", symbol: "backpack.fill"),
            PerchNote(title: "Reading List", body: "The Design of Everyday Things — Don Norman. Atomic Habits — James Clear.", symbol: "book.fill"),
        ]
    }
}

// MARK: - Snippets + clipboard history

struct PerchSnippet: Codable, Identifiable, Equatable {
    var id: UUID = UUID()
    var label: String
    var value: String
    var symbol: String = "doc.text"
    /// Pinned snippets live in the left grid; unpinned are clipboard history.
    var pinned: Bool = true
    var created: Date = Date()
}

@MainActor
final class PerchSnippetsStore: ObservableObject {
    static let shared = PerchSnippetsStore()

    @Published private(set) var snippets: [PerchSnippet] = []
    /// Recent clipboard captures, newest first. Not persisted beyond the cap.
    @Published private(set) var history: [PerchSnippet] = []

    private var pasteboardCount: Int = NSPasteboard.general.changeCount
    private var timer: Timer?
    private let historyCap = 40

    var pinned: [PerchSnippet] { snippets.filter(\.pinned) }

    private init() {
        snippets = PerchDisk.load([PerchSnippet].self, from: PerchPaths.snippets) ?? Self.starter()
        if PerchDisk.load([PerchSnippet].self, from: PerchPaths.snippets) == nil { save() }
    }

    // MARK: Clipboard watching

    /// Poll the pasteboard — AppKit offers no change notification, so a light
    /// 1s `changeCount` poll is the standard approach and costs nothing when idle.
    func startWatching() {
        guard timer == nil else { return }
        let timer = Timer(timeInterval: 1.0, repeats: true) { [weak self] _ in
            MainActor.assumeIsolated { self?.pollPasteboard() }
        }
        RunLoop.main.add(timer, forMode: .common)
        self.timer = timer
    }

    func stopWatching() {
        timer?.invalidate()
        timer = nil
    }

    private func pollPasteboard() {
        let board = NSPasteboard.general
        guard board.changeCount != pasteboardCount else { return }
        pasteboardCount = board.changeCount
        guard let text = board.string(forType: .string) else { return }
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, trimmed.count <= 5000 else { return }
        // Don't log our own copy-outs, or repeat the newest entry.
        if history.first?.value == trimmed { return }
        if pinned.contains(where: { $0.value == trimmed }) { return }

        history.insert(PerchSnippet(label: Self.autoLabel(trimmed), value: trimmed, pinned: false), at: 0)
        if history.count > historyCap { history.removeLast(history.count - historyCap) }
    }

    /// A short human label guessed from the content's shape.
    static func autoLabel(_ value: String) -> String {
        if value.hasPrefix("http://") || value.hasPrefix("https://") { return "Link" }
        if value.contains("@"), value.contains("."), !value.contains(" ") { return "Email" }
        let digits = value.filter(\.isNumber).count
        if digits >= 7, Double(digits) / Double(max(1, value.count)) > 0.5 { return "Number" }
        return value.count > 42 ? "Text" : value
    }

    // MARK: Mutations

    func copy(_ snippet: PerchSnippet) {
        let board = NSPasteboard.general
        board.clearContents()
        board.setString(snippet.value, forType: .string)
        // Adopt the new count so our own write isn't re-captured as history.
        pasteboardCount = board.changeCount
    }

    @discardableResult
    func add(label: String, value: String, symbol: String = "doc.text") -> PerchSnippet {
        let snippet = PerchSnippet(label: label, value: value, symbol: symbol, pinned: true)
        snippets.insert(snippet, at: 0)
        save()
        return snippet
    }

    /// Promote a clipboard capture into the pinned grid.
    func pin(_ snippet: PerchSnippet) {
        history.removeAll { $0.id == snippet.id }
        var pinnedCopy = snippet
        pinnedCopy.pinned = true
        snippets.insert(pinnedCopy, at: 0)
        save()
    }

    func update(_ snippet: PerchSnippet) {
        guard let index = snippets.firstIndex(where: { $0.id == snippet.id }) else { return }
        snippets[index] = snippet
        save()
    }

    func delete(_ snippet: PerchSnippet) {
        snippets.removeAll { $0.id == snippet.id }
        history.removeAll { $0.id == snippet.id }
        save()
    }

    func clearHistory() { history.removeAll() }

    private func save() { PerchDisk.save(snippets, to: PerchPaths.snippets) }

    private static func starter() -> [PerchSnippet] {
        [
            PerchSnippet(label: "Home Address", value: "20 Cooper Square, New York, NY 10003", symbol: "house.fill"),
            PerchSnippet(label: "Email", value: "", symbol: "envelope.fill"),
        ].filter { !$0.value.isEmpty }
    }
}

// MARK: - Tray (file shelf)

struct PerchTrayItem: Identifiable, Equatable {
    let id: UUID
    let url: URL
    let name: String
    let size: Int
    let added: Date

    var isImage: Bool {
        ["png", "jpg", "jpeg", "gif", "heic", "webp", "tiff"].contains(url.pathExtension.lowercased())
    }
    var sizeText: String {
        ByteCountFormatter.string(fromByteCount: Int64(size), countStyle: .file)
    }
}

@MainActor
final class PerchTrayStore: ObservableObject {
    static let shared = PerchTrayStore()

    @Published private(set) var items: [PerchTrayItem] = []

    private init() { reload() }

    /// The tray is just a folder on disk — copies live there so the shelf keeps
    /// working after the original is moved or deleted.
    func reload() {
        let dir = PerchPaths.trayDir
        let urls = (try? FileManager.default.contentsOfDirectory(
            at: dir,
            includingPropertiesForKeys: [.fileSizeKey, .creationDateKey],
            options: [.skipsHiddenFiles])) ?? []

        items = urls.compactMap { url in
            let values = try? url.resourceValues(forKeys: [.fileSizeKey, .creationDateKey])
            return PerchTrayItem(
                id: UUID(),
                url: url,
                name: url.lastPathComponent,
                size: values?.fileSize ?? 0,
                added: values?.creationDate ?? Date()
            )
        }
        .sorted { $0.added > $1.added }
    }

    /// Copy dropped files into the tray off the main thread, then refresh.
    ///
    /// The copy is a full byte-for-byte duplication — dropping a few GB of video
    /// would freeze the entire app if this ran inline on the main actor.
    func acceptAsync(urls: [URL], completion: @escaping (Int) -> Void) {
        DispatchQueue.global(qos: .userInitiated).async {
            let added = Self.copyIntoTray(urls: urls)
            Task { @MainActor in
                if added > 0 { self.reload() }
                completion(added)
            }
        }
    }

    /// Synchronous variant kept for callers already off the main thread.
    @discardableResult
    func accept(urls: [URL]) -> Int {
        let added = Self.copyIntoTray(urls: urls)
        if added > 0 { reload() }
        return added
    }

    /// Copy with name uniquing so nothing is clobbered. Pure file I/O — safe to
    /// call from any thread.
    private nonisolated static func copyIntoTray(urls: [URL]) -> Int {
        var added = 0
        for source in urls {
            var destination = PerchPaths.trayDir.appendingPathComponent(source.lastPathComponent)
            var counter = 2
            while FileManager.default.fileExists(atPath: destination.path) {
                let base = source.deletingPathExtension().lastPathComponent
                let ext = source.pathExtension
                let name = ext.isEmpty ? "\(base) \(counter)" : "\(base) \(counter).\(ext)"
                destination = PerchPaths.trayDir.appendingPathComponent(name)
                counter += 1
            }
            do {
                try FileManager.default.copyItem(at: source, to: destination)
                added += 1
            } catch {
                appLog("[Perch] Tray copy failed for \(source.lastPathComponent): \(error.localizedDescription)")
            }
        }
        return added
    }

    func remove(_ item: PerchTrayItem) {
        try? FileManager.default.removeItem(at: item.url)
        reload()
    }

    func clear() {
        for item in items { try? FileManager.default.removeItem(at: item.url) }
        reload()
    }

    func revealInFinder(_ item: PerchTrayItem) {
        NSWorkspace.shared.activateFileViewerSelecting([item.url])
    }

    /// Hand the whole shelf to the system AirDrop sharing service.
    func airDrop(_ urls: [URL], from view: NSView?) {
        guard !urls.isEmpty else { return }
        guard let service = NSSharingService(named: .sendViaAirDrop) else { return }
        if service.canPerform(withItems: urls) {
            service.perform(withItems: urls)
        } else {
            appLog("[Perch] AirDrop unavailable for the current selection")
        }
    }
}

// MARK: - Timer

@MainActor
final class PerchTimerStore: ObservableObject {
    static let shared = PerchTimerStore()

    enum Mode: String, CaseIterable, Identifiable, Codable {
        case countdown, stopwatch
        var id: String { rawValue }
        var title: String { self == .countdown ? "Countdown" : "Stopwatch" }
        var symbol: String { self == .countdown ? "timer" : "stopwatch" }
    }

    @Published var mode: Mode = .countdown
    /// Presets in seconds, shown as the chip grid.
    @Published private(set) var presets: [Int] = []
    /// Remaining (countdown) or elapsed (stopwatch) seconds.
    @Published private(set) var value: TimeInterval = 600
    @Published private(set) var running = false
    /// Fires when a countdown reaches zero so the UI can react.
    @Published private(set) var finishedAt: Date?

    private var duration: TimeInterval = 600
    private var ticker: Timer?
    private var lastTick: Date?

    private init() {
        presets = PerchDisk.load([Int].self, from: PerchPaths.timers)
            ?? [120, 600, 900, 1800, 3600, 7200]
        value = TimeInterval(presets.first ?? 600)
        duration = value
    }

    var display: String { Self.format(mode == .countdown ? value : value) }

    static func format(_ seconds: TimeInterval) -> String {
        let total = max(0, Int(seconds.rounded()))
        let h = total / 3600, m = (total % 3600) / 60, s = total % 60
        return h > 0 ? String(format: "%02d:%02d:%02d", h, m, s)
                     : String(format: "%02d:%02d", m, s)
    }

    // MARK: Controls

    func toggle() { running ? pause() : start() }

    func start() {
        if mode == .countdown && value <= 0 { value = duration }
        guard !running else { return }
        running = true
        finishedAt = nil
        lastTick = Date()
        let ticker = Timer(timeInterval: 0.1, repeats: true) { [weak self] _ in
            MainActor.assumeIsolated { self?.tick() }
        }
        RunLoop.main.add(ticker, forMode: .common)
        self.ticker = ticker
    }

    func pause() {
        running = false
        ticker?.invalidate()
        ticker = nil
        lastTick = nil
    }

    func reset() {
        pause()
        value = mode == .countdown ? duration : 0
        finishedAt = nil
    }

    func setMode(_ new: Mode) {
        guard new != mode else { return }
        pause()
        mode = new
        value = new == .countdown ? duration : 0
        finishedAt = nil
    }

    func select(preset seconds: Int) {
        pause()
        mode = .countdown
        duration = TimeInterval(seconds)
        value = duration
        finishedAt = nil
    }

    func addPreset(seconds: Int) {
        guard seconds > 0, !presets.contains(seconds) else { return }
        presets.append(seconds)
        presets.sort()
        PerchDisk.save(presets, to: PerchPaths.timers)
    }

    func removePreset(_ seconds: Int) {
        presets.removeAll { $0 == seconds }
        PerchDisk.save(presets, to: PerchPaths.timers)
    }

    /// Wall-clock delta rather than a fixed decrement, so the timer stays honest
    /// if the run loop stalls or the machine sleeps.
    private func tick() {
        let now = Date()
        let delta = now.timeIntervalSince(lastTick ?? now)
        lastTick = now

        switch mode {
        case .countdown:
            value = max(0, value - delta)
            if value <= 0 { finish() }
        case .stopwatch:
            value += delta
        }
    }

    private func finish() {
        pause()
        value = 0
        finishedAt = Date()
        NSSound(named: "Glass")?.play()
    }
}
