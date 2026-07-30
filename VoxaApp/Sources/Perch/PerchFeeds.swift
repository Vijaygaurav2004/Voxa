import SwiftUI
import AppKit
import EventKit

// MARK: - Now Playing

/// Reads the currently playing track from Spotify / Apple Music.
///
/// macOS has no public now-playing API (MediaRemote is private and was locked
/// down in Sonoma), so this uses the same AppleScript route the rest of Voxa's
/// media control already relies on. Only queries apps that are actually running,
/// so it never launches a player just to ask what's on.
@MainActor
final class PerchNowPlaying: ObservableObject {
    static let shared = PerchNowPlaying()

    @Published private(set) var title: String = ""
    @Published private(set) var artist: String = ""
    @Published private(set) var app: String = ""
    @Published private(set) var isPlaying = false
    @Published private(set) var artwork: NSImage?

    private var timer: Timer?
    private var artworkKey: String = ""
    /// Guards against stacking pollers. `osascript` blocks until the target app
    /// answers, and an unresponsive Spotify/Music can take seconds — without
    /// this, a 3s timer would pile up blocked threads on the cooperative pool.
    private var polling = false

    var hasTrack: Bool { !title.isEmpty }

    private init() {}

    func start() {
        guard timer == nil else { return }
        refresh()
        let timer = Timer(timeInterval: 3.0, repeats: true) { [weak self] _ in
            MainActor.assumeIsolated { self?.refresh() }
        }
        RunLoop.main.add(timer, forMode: .common)
        self.timer = timer
    }

    func stop() {
        timer?.invalidate()
        timer = nil
    }

    func refresh() {
        guard !polling else { return }
        polling = true
        // A dedicated serial queue, NOT the Swift cooperative pool: these calls
        // block on a subprocess, and the pool is only core-count wide. Parking
        // pool threads here would starve `actor PythonBridge`, which is the sole
        // path for intent parsing and TTS — voice commands would quietly stop
        // working while the UI carried on repainting.
        Self.scriptQueue.async {
            let snapshot = Self.query()
            Task { @MainActor in
                self.polling = false
                self.apply(snapshot)
            }
        }
    }

    private func apply(_ snapshot: Snapshot?) {
        guard let snapshot else {
            title = ""; artist = ""; app = ""; isPlaying = false; artwork = nil; artworkKey = ""
            return
        }
        title = snapshot.title
        artist = snapshot.artist
        app = snapshot.app
        isPlaying = snapshot.playing

        let key = "\(snapshot.app)|\(snapshot.artist)|\(snapshot.title)"
        if key != artworkKey {
            artworkKey = key
            artwork = nil
            // Same serial queue as the poll, so artwork can never run
            // concurrently with (or pile up behind) a track query.
            Self.scriptQueue.async {
                let image = Self.fetchArtwork(app: snapshot.app, artist: snapshot.artist, title: snapshot.title)
                Task { @MainActor in if self.artworkKey == key { self.artwork = image } }
            }
        }
    }

    // MARK: Controls

    func playPause() { send("playpause") }
    func next()      { send("next track") }
    func previous()  { send("previous track") }

    /// Transport commands also shell out, so they must not run on the main
    /// actor — a synchronous `osascript` there freezes the whole perch (and the
    /// app) for as long as the player takes to answer.
    private func send(_ command: String) {
        let target = app.isEmpty ? "Spotify" : app
        Self.scriptQueue.async {
            Self.tell(target, command)
            Task { @MainActor in self.bump() }
        }
    }

    /// Everything that shells out to osascript is funnelled through here.
    private static let scriptQueue = DispatchQueue(label: "com.voxa.perch.nowplaying", qos: .utility)

    /// Players need a moment to settle before they report the new state.
    private func bump() {
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.35) { [weak self] in self?.refresh() }
    }

    // MARK: AppleScript

    private struct Snapshot { let app, title, artist: String; let playing: Bool }

    private nonisolated static func tell(_ app: String, _ command: String) {
        _ = runScript("tell application \"\(app)\" to \(command)")
    }

    private nonisolated static func query() -> Snapshot? {
        for app in ["Spotify", "Music"] {
            guard isRunning(app) else { continue }
            let script = """
            tell application "\(app)"
                if player state is playing or player state is paused then
                    set t to name of current track
                    set a to artist of current track
                    set p to (player state as text)
                    return t & "\u{1F}" & a & "\u{1F}" & p
                end if
            end tell
            """
            guard let out = runScript(script), !out.isEmpty else { continue }
            let parts = out.components(separatedBy: "\u{1F}")
            guard parts.count >= 3 else { continue }
            return Snapshot(app: app, title: parts[0], artist: parts[1],
                            playing: parts[2].contains("playing"))
        }
        return nil
    }

    private nonisolated static func isRunning(_ app: String) -> Bool {
        NSWorkspace.shared.runningApplications.contains {
            $0.localizedName == app || $0.bundleIdentifier?.hasSuffix(app.lowercased()) == true
        }
    }

    /// Spotify exposes a plain artwork URL, which survives the round trip through
    /// osascript as a string. Music only offers raw image data through an Apple
    /// Event descriptor, which this text-based path can't carry — that case falls
    /// back to the accent tile rather than reaching for a non-thread-safe API.
    private nonisolated static func fetchArtwork(app: String, artist: String, title: String) -> NSImage? {
        guard app == "Spotify" else { return nil }
        guard let urlString = runScript("tell application \"Spotify\" to return artwork url of current track"),
              let url = URL(string: urlString) else { return nil }

        // An explicit timeout, rather than Data(contentsOf:) — a captive portal
        // or dropped VPN would otherwise park this thread indefinitely.
        var request = URLRequest(url: url)
        request.timeoutInterval = 6
        let semaphore = DispatchSemaphore(value: 0)
        var payload: Data?
        URLSession.shared.dataTask(with: request) { data, _, _ in
            payload = data
            semaphore.signal()
        }.resume()
        _ = semaphore.wait(timeout: .now() + 8)
        guard let payload else { return nil }
        return NSImage(data: payload)
    }

    /// Runs through `/usr/bin/osascript` rather than `NSAppleScript`.
    /// NSAppleScript is documented as not thread-safe and this is called from a
    /// background task on a timer; shelling out is safe off the main thread and
    /// matches how the rest of Voxa drives AppleScript.
    private nonisolated static func runScript(_ source: String) -> String? {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/osascript")
        process.arguments = ["-e", source]
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = FileHandle.nullDevice
        do {
            try process.run()
        } catch {
            return nil
        }
        // Hard watchdog. The first `tell application` raises the macOS Automation
        // consent dialog and osascript blocks until it is answered — which may be
        // never if the user doesn't notice it. A beach-balled player blocks for
        // the ~2 minute Apple Event timeout. Neither may pin this thread.
        let watchdog = DispatchWorkItem { if process.isRunning { process.terminate() } }
        DispatchQueue.global(qos: .utility).asyncAfter(deadline: .now() + 5, execute: watchdog)
        defer { watchdog.cancel() }

        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        process.waitUntilExit()
        // A terminated process reports non-zero here, so a timeout falls through
        // to nil and `apply(nil)` clears the widget cleanly.
        guard process.terminationStatus == 0 else { return nil }
        let out = String(data: data, encoding: .utf8)?
            .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return out.isEmpty ? nil : out
    }
}

// MARK: - Weather

/// Current conditions from Open-Meteo, located by IP.
///
/// Both services are keyless, so the widget works out of the box with no setup
/// and no API key in the bundle. IP geolocation also avoids a CoreLocation
/// permission prompt for what is only ever a city-level lookup.
@MainActor
final class PerchWeather: ObservableObject {
    static let shared = PerchWeather()

    @Published private(set) var temperature: Int?
    @Published private(set) var low: Int?
    @Published private(set) var high: Int?
    @Published private(set) var summary: String = ""
    @Published private(set) var city: String = ""
    @Published private(set) var symbol: String = "cloud.sun.fill"
    @Published private(set) var failed = false

    private var lastFetch: Date?

    private init() {}

    /// Weather changes slowly — refuse to refetch more than every 15 minutes.
    func refreshIfStale() {
        if let lastFetch, Date().timeIntervalSince(lastFetch) < 900 { return }
        Task { await refresh() }
    }

    func refresh() async {
        do {
            let place = try await lookupPlace()
            let url = URL(string:
                "https://api.open-meteo.com/v1/forecast?latitude=\(place.lat)&longitude=\(place.lon)" +
                "&current=temperature_2m,weather_code&daily=temperature_2m_max,temperature_2m_min" +
                "&timezone=auto&forecast_days=1")!
            let (data, _) = try await URLSession.shared.data(from: url)
            let decoded = try JSONDecoder().decode(Forecast.self, from: data)

            temperature = Int(decoded.current.temperature_2m.rounded())
            high = decoded.daily.temperature_2m_max.first.map { Int($0.rounded()) }
            low  = decoded.daily.temperature_2m_min.first.map { Int($0.rounded()) }
            let code = decoded.current.weather_code
            summary = Self.describe(code)
            symbol = Self.symbol(for: code)
            city = place.city
            failed = false
            lastFetch = Date()
        } catch {
            appLog("[Perch] Weather fetch failed: \(error.localizedDescription)")
            failed = true
            lastFetch = Date()      // back off rather than hammering a dead network
        }
    }

    private struct Place { let lat: Double; let lon: Double; let city: String }

    private struct IPInfo: Decodable { let latitude: Double?; let longitude: Double?; let city: String? }
    private struct Forecast: Decodable {
        struct Current: Decodable { let temperature_2m: Double; let weather_code: Int }
        struct Daily: Decodable { let temperature_2m_max: [Double]; let temperature_2m_min: [Double] }
        let current: Current
        let daily: Daily
    }

    private func lookupPlace() async throws -> Place {
        let url = URL(string: "https://ipapi.co/json/")!
        let (data, _) = try await URLSession.shared.data(from: url)
        let info = try JSONDecoder().decode(IPInfo.self, from: data)
        guard let lat = info.latitude, let lon = info.longitude else {
            throw URLError(.cannotDecodeContentData)
        }
        return Place(lat: lat, lon: lon, city: info.city ?? "")
    }

    /// WMO weather interpretation codes.
    private static func describe(_ code: Int) -> String {
        switch code {
        case 0: return "Clear"
        case 1, 2: return "Partly cloudy"
        case 3: return "Cloudy"
        case 45, 48: return "Foggy"
        case 51, 53, 55, 56, 57: return "Drizzle"
        case 61, 63, 65, 66, 67: return "Rain"
        case 71, 73, 75, 77: return "Snow"
        case 80, 81, 82: return "Showers"
        case 85, 86: return "Snow showers"
        case 95, 96, 99: return "Thunderstorm"
        default: return "—"
        }
    }

    private static func symbol(for code: Int) -> String {
        switch code {
        case 0: return "sun.max.fill"
        case 1, 2: return "cloud.sun.fill"
        case 3: return "cloud.fill"
        case 45, 48: return "cloud.fog.fill"
        case 51, 53, 55, 56, 57: return "cloud.drizzle.fill"
        case 61, 63, 65, 66, 67, 80, 81, 82: return "cloud.rain.fill"
        case 71, 73, 75, 77, 85, 86: return "cloud.snow.fill"
        case 95, 96, 99: return "cloud.bolt.rain.fill"
        default: return "cloud.sun.fill"
        }
    }
}

// MARK: - Calendar

/// Today's events via EventKit. Degrades to a clear "grant access" state rather
/// than silently showing an empty day.
@MainActor
final class PerchCalendar: ObservableObject {
    static let shared = PerchCalendar()

    struct Event: Identifiable {
        let id: String
        let title: String
        let start: Date
        let isAllDay: Bool
        let color: Color

        var timeText: String {
            if isAllDay { return "All-day" }
            let f = DateFormatter()
            f.dateFormat = "h:mm a"
            return f.string(from: start)
        }
    }

    @Published private(set) var events: [Event] = []
    @Published private(set) var authorised = false
    @Published private(set) var checked = false

    private let store = EKEventStore()

    private init() {}

    func refresh() {
        let status = EKEventStore.authorizationStatus(for: .event)
        switch status {
        case .fullAccess:
            authorised = true; checked = true; load()
        case .notDetermined:
            store.requestFullAccessToEvents { [weak self] granted, _ in
                Task { @MainActor in
                    self?.authorised = granted
                    self?.checked = true
                    if granted { self?.load() }
                }
            }
        default:
            authorised = false; checked = true; events = []
        }
    }

    private func load() {
        let calendar = Calendar.current
        let start = calendar.startOfDay(for: Date())
        guard let end = calendar.date(byAdding: .day, value: 1, to: start) else { return }
        let predicate = store.predicateForEvents(withStart: start, end: end, calendars: nil)
        events = store.events(matching: predicate)
            .sorted { ($0.startDate ?? start) < ($1.startDate ?? start) }
            .prefix(8)
            .map {
                Event(id: $0.eventIdentifier ?? UUID().uuidString,
                      title: $0.title ?? "Untitled",
                      start: $0.startDate ?? start,
                      isAllDay: $0.isAllDay,
                      color: Color(nsColor: $0.calendar?.color ?? .systemGray))
            }
    }

    /// Open the Calendar app at today, which is the useful "+" affordance
    /// without asking for write access.
    func openCalendarApp() {
        NSWorkspace.shared.open(URL(string: "ical://")!)
    }
}
