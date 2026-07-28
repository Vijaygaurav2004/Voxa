import SwiftUI

struct MemoryPage: View {
    @State private var active = false
    @State private var loadingToggle = false
    @State private var question = ""
    @State private var answer: String?
    @State private var asking = false

    // Storage + recordings
    @StateObject private var clipPlayer = ClipPlayer()
    @State private var storage: PythonBridge.StorageInfo?
    @State private var sessions: [PythonBridge.ClipSession] = []
    @State private var expanded: Set<String> = []
    @State private var keepAudio = true
    @State private var retentionDays = 30
    @State private var loadingSessions = false
    @State private var fetchingClipID: Int?
    @State private var confirmingClear = false
    @State private var clipError: String?

    private let retentionOptions = [7, 30, 90, 365]

    var body: some View {
        Page(title: "Memory", subtitle: "Ambient recall — ask about past conversations") {
            Card {
                SettingRow(icon: active ? "brain.head.profile" : "brain",
                           title: "Ambient Memory",
                           subtitle: active ? "Listening and remembering" : "Off") {
                    if loadingToggle { ProgressView().controlSize(.small) }
                    else { MonoToggle(isOn: Binding(get: { active }, set: toggle)) }
                }
            }

            VStack(alignment: .leading, spacing: 8) {
                SectionLabel(text: "Ask your memory")
                HStack(spacing: 8) {
                    TextField("e.g. what did we decide about the launch date?", text: $question)
                        .textFieldStyle(.plain).font(.system(size: 13))
                        .padding(.horizontal, 12).padding(.vertical, 11)
                        .background(RoundedRectangle(cornerRadius: Theme.radiusSmall).fill(Theme.card))
                        .overlay(RoundedRectangle(cornerRadius: Theme.radiusSmall).strokeBorder(Theme.stroke))
                        .onSubmit(ask)
                    Button(action: ask) {
                        if asking { ProgressView().controlSize(.small) }
                        else { Image(systemName: "arrow.up").font(.system(size: 14, weight: .bold)).foregroundStyle(Color(NSColor.windowBackgroundColor)) }
                    }
                    .frame(width: 44, height: 42)
                    .background(RoundedRectangle(cornerRadius: Theme.radiusSmall).fill(question.trimmed.isEmpty ? Theme.card : Color.primary))
                    .buttonStyle(.plain)
                    .disabled(asking || question.trimmed.isEmpty)
                }

                if let answer {
                    Card {
                        Text(answer).font(.system(size: 13)).foregroundStyle(Theme.text)
                            .textSelection(.enabled).fixedSize(horizontal: false, vertical: true)
                    }
                }
            }

            storageCard

            recordingsSection
        }
        .onAppear { loadStatus(); loadStorage(); loadSessions() }
    }

    // MARK: - Storage card

    private var storageCard: some View {
        Card {
            VStack(spacing: 14) {
                SettingRow(icon: "internaldrive",
                           title: "Recordings",
                           subtitle: storageSubtitle) { EmptyView() }

                Divider().overlay(Theme.stroke)

                SettingRow(icon: "waveform",
                           title: "Keep audio clips",
                           subtitle: "Save a recording for each memory") {
                    MonoToggle(isOn: Binding(get: { keepAudio }, set: setKeepAudio))
                }

                Divider().overlay(Theme.stroke)

                SettingRow(icon: "clock.arrow.circlepath",
                           title: "Delete after",
                           subtitle: "Automatically remove old recordings") {
                    retentionMenu
                }

                Divider().overlay(Theme.stroke)

                if confirmingClear {
                    HStack(spacing: 10) {
                        Text("Delete all recordings?").font(.system(size: 12)).foregroundStyle(Theme.subtle)
                        Spacer()
                        Button("Cancel") { confirmingClear = false }
                            .buttonStyle(GhostButtonStyle()).frame(width: 90)
                        Button("Clear all") { clearAll() }
                            .buttonStyle(GhostButtonStyle(tint: .red)).frame(width: 100)
                    }
                } else {
                    Button { confirmingClear = true } label: {
                        Label("Clear all clips", systemImage: "trash")
                    }
                    .buttonStyle(GhostButtonStyle(tint: .red))
                }

                Text("Silent and filler audio is skipped automatically to save space.")
                    .font(.system(size: 11)).foregroundStyle(Theme.faint)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
    }

    private var retentionMenu: some View {
        Menu {
            ForEach(retentionOptions, id: \.self) { d in
                Button(Self.retentionLabel(d)) { setRetention(d) }
            }
        } label: {
            HStack(spacing: 4) {
                Text(Self.retentionLabel(retentionDays))
                Image(systemName: "chevron.up.chevron.down").font(.system(size: 9))
            }
            .font(.system(size: 12, weight: .medium))
            .foregroundStyle(Theme.text)
        }
        .menuStyle(.borderlessButton)
        .fixedSize()
    }

    private var storageSubtitle: String {
        guard let s = storage else { return "Loading…" }
        return String(format: "%d clips · %.1f MB", s.clips_count, s.clips_size_mb)
    }

    // MARK: - Recordings list

    @ViewBuilder private var recordingsSection: some View {
        HStack {
            SectionLabel(text: "Recordings")
            Spacer()
            Button { loadSessions() } label: {
                Image(systemName: "arrow.clockwise").font(.system(size: 12)).foregroundStyle(Theme.subtle)
            }.buttonStyle(.plain)
        }

        if let clipError {
            Text(clipError).font(.system(size: 11)).foregroundStyle(.red)
        }

        if sessions.isEmpty && !loadingSessions {
            VStack(spacing: 10) {
                Image(systemName: "waveform.slash").font(.system(size: 32)).foregroundStyle(Theme.faint)
                Text("No recordings yet").font(.system(size: 14, weight: .medium))
                Text("Turn on ambient memory or record a meeting.")
                    .font(.system(size: 12)).foregroundStyle(Theme.subtle)
            }
            .frame(maxWidth: .infinity).padding(.vertical, 44)
        } else {
            // One card per session (meeting), grouped by day — Today / Yesterday /
            // weekday+date / older, newest first.
            VStack(alignment: .leading, spacing: 18) {
                ForEach(groupedSessions, id: \.header) { group in
                    VStack(alignment: .leading, spacing: 8) {
                        HStack {
                            Text(group.header)
                                .font(.system(size: 12, weight: .semibold))
                                .foregroundStyle(Theme.subtle)
                            Spacer()
                            Text("\(group.items.count)")
                                .font(.system(size: 11, weight: .medium))
                                .foregroundStyle(Theme.faint)
                        }
                        VStack(spacing: 10) {
                            ForEach(group.items) { s in sessionCard(s) }
                        }
                    }
                }
            }
        }
    }

    /// Sessions bucketed by calendar day (of their start), newest day first,
    /// newest session first within each day.
    private var groupedSessions: [(header: String, items: [PythonBridge.ClipSession])] {
        let sorted = sessions.sorted {
            (Self.parseDate($0.started_iso) ?? .distantPast) > (Self.parseDate($1.started_iso) ?? .distantPast)
        }
        var order: [String] = []
        var groups: [String: [PythonBridge.ClipSession]] = [:]
        for s in sorted {
            let header = Self.parseDate(s.started_iso).map(Self.dayHeader) ?? "Earlier"
            if groups[header] == nil { groups[header] = []; order.append(header) }
            groups[header]?.append(s)
        }
        return order.map { (header: $0, items: groups[$0] ?? []) }
    }

    // MARK: - Session card

    private func sessionCard(_ s: PythonBridge.ClipSession) -> some View {
        Card {
            VStack(alignment: .leading, spacing: 0) {
                HStack(spacing: 12) {
                    ZStack {
                        RoundedRectangle(cornerRadius: Theme.radiusSmall, style: .continuous)
                            .fill(Theme.card).frame(width: 32, height: 32)
                        Image(systemName: platformIcon(s))
                            .font(.system(size: 14, weight: .medium)).foregroundStyle(Theme.text)
                    }
                    VStack(alignment: .leading, spacing: 2) {
                        Text(s.title).font(.system(size: 15, weight: .semibold))
                            .foregroundStyle(Theme.text).lineLimit(1)
                        Text(sessionCaption(s)).font(.system(size: 11))
                            .foregroundStyle(Theme.subtle).lineLimit(1)
                    }
                    Spacer(minLength: 8)

                    Button { playSession(s) } label: {
                        Image(systemName: clipPlayer.playingSessionID == s.session_id ? "pause.fill" : "play.fill")
                            .font(.system(size: 13)).foregroundStyle(Theme.text)
                    }
                    .buttonStyle(.plain).frame(width: 30, height: 30)

                    Button { toggleExpanded(s.session_id) } label: {
                        Image(systemName: expanded.contains(s.session_id) ? "chevron.up" : "chevron.down")
                            .font(.system(size: 12)).foregroundStyle(Theme.subtle)
                    }
                    .buttonStyle(.plain).frame(width: 30, height: 30)

                    Button { deleteSession(s) } label: {
                        Image(systemName: "trash").font(.system(size: 12)).foregroundStyle(Theme.subtle)
                    }
                    .buttonStyle(.plain).frame(width: 30, height: 30)
                }

                if expanded.contains(s.session_id) {
                    Divider().overlay(Theme.stroke).padding(.vertical, 12)
                    VStack(spacing: 10) {
                        ForEach(s.clips) { c in clipRow(c) }
                    }
                }
            }
        }
    }

    private func sessionCaption(_ s: PythonBridge.ClipSession) -> String {
        let clips = "\(s.clip_count) clip\(s.clip_count == 1 ? "" : "s")"
        var parts: [String] = []
        let time = Self.timeOfDay(s.started_iso)
        if !time.isEmpty { parts.append(time) }
        parts.append(s.platform)
        parts.append(clips)
        parts.append(Self.sessionDuration(s.duration_secs))
        return parts.joined(separator: " · ")
    }

    /// SF Symbol for a session's recording platform.
    private func platformIcon(_ s: PythonBridge.ClipSession) -> String {
        if s.platform_kind == "mic" { return "mic" }
        let p = s.platform.lowercased()
        if p.contains("zoom") { return "video.fill" }
        if p.contains("teams") { return "person.2.fill" }
        if p.contains("webex") { return "video.badge.waveform" }
        if p.contains("meet") { return "video" }
        if s.platform_kind == "browser" { return "video" }
        if s.platform_kind == "app" { return "app.badge" }
        return "waveform"
    }

    private func clipRow(_ c: PythonBridge.ClipRecord) -> some View {
        Card {
            HStack(spacing: 12) {
                ZStack {
                    RoundedRectangle(cornerRadius: Theme.radiusSmall, style: .continuous)
                        .fill(Theme.card).frame(width: 32, height: 32)
                    Image(systemName: c.source == "system" ? "speaker.wave.2" : "mic")
                        .font(.system(size: 14, weight: .medium)).foregroundStyle(Theme.text)
                }
                VStack(alignment: .leading, spacing: 2) {
                    Text(clipTitle(c)).font(.system(size: 13, weight: .medium))
                        .foregroundStyle(Theme.text).lineLimit(2)
                    Text(clipCaption(c)).font(.system(size: 11)).foregroundStyle(Theme.subtle).lineLimit(1)
                }
                Spacer(minLength: 8)
                Button { play(c) } label: {
                    if fetchingClipID == c.id {
                        ProgressView().controlSize(.small)
                    } else {
                        Image(systemName: clipPlayer.playingID == c.id ? "pause.fill" : "play.fill")
                            .font(.system(size: 13)).foregroundStyle(Theme.text)
                    }
                }
                .buttonStyle(.plain).frame(width: 30, height: 30)

                Button { delete(c) } label: {
                    Image(systemName: "trash").font(.system(size: 12)).foregroundStyle(Theme.subtle)
                }
                .buttonStyle(.plain).frame(width: 30, height: 30)
            }
        }
    }

    private func clipTitle(_ c: PythonBridge.ClipRecord) -> String {
        c.summary.trimmed.isEmpty ? (Self.pretty(c.timestamp) ?? "Recording") : c.summary
    }

    private func clipCaption(_ c: PythonBridge.ClipRecord) -> String {
        let time = Self.timeOfDay(c.timestamp)
        let source = c.source == "system" ? "Participant" : "You"
        return time.isEmpty
            ? "\(source) · \(Self.dur(c.duration_secs))"
            : "\(time) · \(source) · \(Self.dur(c.duration_secs))"
    }

    // MARK: - Ambient memory toggle

    private func toggle(_ on: Bool) {
        loadingToggle = true
        Task {
            do {
                if on { _ = try await PythonBridge.shared.startMemory(); active = true }
                else { _ = try await PythonBridge.shared.stopMemory(); active = false }
            } catch { active = !on }
            loadingToggle = false
        }
    }
    private func loadStatus() {
        Task { if let s = try? await PythonBridge.shared.getMemoryStatus() { active = s.active } }
    }
    private func ask() {
        let q = question.trimmed; guard !q.isEmpty else { return }
        asking = true; answer = nil
        Task {
            let a = (try? await PythonBridge.shared.queryMemory(q)) ?? "I couldn't answer that."
            await MainActor.run { answer = a; asking = false }
        }
    }

    // MARK: - Storage / recordings actions

    private func loadStorage() { Task { @MainActor in await loadStorageAsync() } }
    private func loadStorageAsync() async {
        if let s = try? await PythonBridge.shared.getStorageInfo() { apply(s) }
    }

    private func loadSessions() {
        loadingSessions = true
        Task { @MainActor in
            sessions = (try? await PythonBridge.shared.getClipSessions()) ?? []
            loadingSessions = false
        }
    }

    private func apply(_ s: PythonBridge.StorageInfo) {
        storage = s; keepAudio = s.keep_audio; retentionDays = s.retention_days
    }

    private func setKeepAudio(_ on: Bool) {
        keepAudio = on
        clipError = nil
        Task { @MainActor in
            if let s = try? await PythonBridge.shared.updateMemorySettings(keepAudio: on) { apply(s) }
        }
    }

    private func setRetention(_ days: Int) {
        retentionDays = days
        clipError = nil
        Task { @MainActor in
            if let s = try? await PythonBridge.shared.updateMemorySettings(retentionDays: days) { apply(s) }
        }
    }

    private func clearAll() {
        confirmingClear = false
        clipPlayer.stop()
        Task { @MainActor in
            _ = try? await PythonBridge.shared.clearClips()
            await loadStorageAsync()
            loadSessions()
        }
    }

    // MARK: - Session actions

    private func playSession(_ s: PythonBridge.ClipSession) {
        clipError = nil
        clipPlayer.playSession(s.session_id, clipIDs: s.clips.map { $0.id }) { id in
            try? await PythonBridge.shared.getClipAudio(id: id)
        }
    }

    private func toggleExpanded(_ id: String) {
        if expanded.contains(id) { expanded.remove(id) } else { expanded.insert(id) }
    }

    private func deleteSession(_ s: PythonBridge.ClipSession) {
        if clipPlayer.playingSessionID == s.session_id { clipPlayer.stop() }
        Task { @MainActor in
            _ = try? await PythonBridge.shared.deleteSession(sessionID: s.session_id)
            sessions.removeAll { $0.session_id == s.session_id }
            expanded.remove(s.session_id)
            await loadStorageAsync()
        }
    }

    // MARK: - Individual clip actions (expanded view)

    private func play(_ c: PythonBridge.ClipRecord) {
        if clipPlayer.playingID == c.id { clipPlayer.stop(); return }
        clipError = nil
        fetchingClipID = c.id
        Task { @MainActor in
            do {
                let data = try await PythonBridge.shared.getClipAudio(id: c.id)
                fetchingClipID = nil
                clipPlayer.toggle(id: c.id, data: data)
            } catch {
                fetchingClipID = nil
                clipError = "Couldn't play that recording."
            }
        }
    }

    private func delete(_ c: PythonBridge.ClipRecord) {
        if clipPlayer.playingID == c.id { clipPlayer.stop() }
        Task { @MainActor in
            _ = try? await PythonBridge.shared.deleteClip(id: c.id)
            await loadStorageAsync()
            loadSessions()
        }
    }

    // MARK: - Formatting helpers

    static func retentionLabel(_ d: Int) -> String { d >= 365 ? "1 year" : "\(d) days" }
    static func dur(_ s: Double) -> String { s < 60 ? "\(Int(s))s" : "\(Int(s / 60))m" }

    /// Whole-session length: "45s" / "5:12" (mm:ss) / "1h 20m".
    static func sessionDuration(_ s: Double) -> String {
        let total = max(0, Int(s))
        if total < 60 { return "\(total)s" }
        if total < 3600 { return String(format: "%d:%02d", total / 60, total % 60) }
        let h = total / 3600, m = (total % 3600) / 60
        return m == 0 ? "\(h)h" : "\(h)h \(m)m"
    }

    // Backend timestamps are local ISO (datetime.now().isoformat()) — WITH
    // microseconds when non-zero, WITHOUT when zero — so parse both forms.
    private static let isoFrac: DateFormatter = {
        let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd'T'HH:mm:ss.SSSSSS"
        f.locale = Locale(identifier: "en_US_POSIX"); return f
    }()
    private static let isoPlain: DateFormatter = {
        let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
        f.locale = Locale(identifier: "en_US_POSIX"); return f
    }()
    private static let timeFmt: DateFormatter = { let f = DateFormatter(); f.dateFormat = "h:mm a"; return f }()
    private static let dateTimeFmt: DateFormatter = { let f = DateFormatter(); f.dateFormat = "MMM d, h:mm a"; return f }()
    private static let weekdayDateFmt: DateFormatter = { let f = DateFormatter(); f.dateFormat = "EEEE, MMM d"; return f }()
    private static let dateYearFmt: DateFormatter = { let f = DateFormatter(); f.dateFormat = "MMM d, yyyy"; return f }()

    static func parseDate(_ s: String) -> Date? {
        if let d = isoFrac.date(from: s) { return d }
        if let d = isoPlain.date(from: s) { return d }
        if let dot = s.firstIndex(of: "."), let d = isoPlain.date(from: String(s[..<dot])) { return d }
        return nil
    }

    static func pretty(_ s: String?) -> String? { guard let s, let d = parseDate(s) else { return nil }; return dateTimeFmt.string(from: d) }
    static func timeOfDay(_ s: String) -> String { guard let d = parseDate(s) else { return "" }; return timeFmt.string(from: d) }

    /// Day-section header: Today / Yesterday / "Monday, Jul 20" / "Jul 20, 2025".
    static func dayHeader(_ date: Date) -> String {
        let cal = Calendar.current
        if cal.isDateInToday(date) { return "Today" }
        if cal.isDateInYesterday(date) { return "Yesterday" }
        let sameYear = cal.component(.year, from: date) == cal.component(.year, from: Date())
        return sameYear ? weekdayDateFmt.string(from: date) : dateYearFmt.string(from: date)
    }
}
