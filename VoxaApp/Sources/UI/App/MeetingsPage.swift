import SwiftUI

struct MeetingsPage: View {
    @State private var enabled = false
    @State private var inProgress = false
    @State private var paused = false
    @State private var platform = ""
    @State private var loadingToggle = false

    @State private var meetings: [PythonBridge.MeetingRecord] = []
    @State private var loadingList = false
    @State private var regenerating: Set<String> = []
    @State private var exporting: Set<String> = []
    @State private var exportMsg: [String: String] = [:]

    var body: some View {
        Page(title: "Meetings", subtitle: "Auto-detect calls and capture notes — like Granola") {
            // Detection + live controls
            Card {
                VStack(spacing: 14) {
                    SettingRow(icon: inProgress ? "record.circle" : "person.2.wave.2",
                               title: "Meeting Detection",
                               subtitle: inProgress
                                    ? (paused ? "In a \(platform) meeting — paused" : "Recording \(platform) meeting")
                                    : (enabled ? "Watching for meetings" : "Off")) {
                        if loadingToggle { ProgressView().controlSize(.small) }
                        else { MonoToggle(isOn: Binding(get: { enabled }, set: toggle)) }
                    }

                    if inProgress {
                        Divider().overlay(Theme.stroke)
                        HStack(spacing: 10) {
                            Button {
                                Task {
                                    if paused { _ = try? await PythonBridge.shared.resumeMeeting() }
                                    else { _ = try? await PythonBridge.shared.pauseMeeting() }
                                    paused.toggle()
                                }
                            } label: { Label(paused ? "Resume" : "Pause", systemImage: paused ? "play.fill" : "pause.fill") }
                                .buttonStyle(GhostButtonStyle())

                            Button {
                                Task { _ = try? await PythonBridge.shared.endMeeting(); inProgress = false; paused = false; loadList() }
                            } label: { Label("End & Save", systemImage: "stop.fill") }
                                .buttonStyle(GhostButtonStyle(tint: .red))
                        }
                    }
                }
            }

            HStack {
                SectionLabel(text: "Notes")
                Spacer()
                Button { loadList() } label: { Image(systemName: "arrow.clockwise").font(.system(size: 12)).foregroundStyle(Theme.subtle) }.buttonStyle(.plain)
            }

            if meetings.isEmpty && !loadingList {
                VStack(spacing: 10) {
                    Image(systemName: "text.badge.checkmark").font(.system(size: 32)).foregroundStyle(Theme.faint)
                    Text("No meeting notes yet").font(.system(size: 14, weight: .medium))
                    Text("Notes appear here after Voxa records a meeting.").font(.system(size: 12)).foregroundStyle(Theme.subtle)
                }
                .frame(maxWidth: .infinity).padding(.vertical, 44)
            } else {
                VStack(spacing: 12) {
                    ForEach(meetings) { m in noteCard(m) }
                }
            }
        }
        .onAppear { loadStatus(); loadList() }
    }

    private func noteCard(_ m: PythonBridge.MeetingRecord) -> some View {
        Card {
            VStack(alignment: .leading, spacing: 10) {
                // Header
                HStack {
                    Image(systemName: "person.2.fill").font(.system(size: 12)).foregroundStyle(Theme.subtle)
                    Text(m.platform ?? "Meeting").font(.system(size: 14, weight: .semibold))
                    Spacer()
                    Text(Self.pretty(m.started_iso)).font(.system(size: 11)).foregroundStyle(Theme.subtle)
                }
                if let s = m.duration_secs, s > 0 {
                    Text(Self.dur(s)).font(.system(size: 11)).foregroundStyle(Theme.faint)
                }

                // AI summary
                if let summary = m.summary, !summary.isEmpty {
                    Text(summary)
                        .font(.system(size: 12)).foregroundStyle(Theme.subtle)
                        .textSelection(.enabled).fixedSize(horizontal: false, vertical: true)
                } else {
                    Text("No summary was generated for this meeting.")
                        .font(.system(size: 12)).foregroundStyle(Theme.faint)
                }

                // Structured insights
                bulletSection("Key points", icon: "list.bullet", items: m.key_points)
                bulletSection("Decisions", icon: "checkmark.seal", items: m.decisions)
                actionItemsSection(m.action_items)
                bulletSection("To-dos", icon: "checklist", items: m.todos)
                followUpsSection(m.follow_ups)

                // Footer actions
                if let sid = m.session_id, !sid.isEmpty {
                    Divider().overlay(Theme.stroke)
                    HStack(spacing: 16) {
                        if m.hasTasks {
                            Button { exportReminders(sid) } label: {
                                HStack(spacing: 5) {
                                    if exporting.contains(sid) { ProgressView().controlSize(.small) }
                                    else {
                                        Image(systemName: (m.reminders_exported == true) ? "checkmark.circle.fill" : "bell.badge")
                                            .font(.system(size: 11))
                                    }
                                    Text((m.reminders_exported == true) ? "Added to Reminders" : "Add to Reminders")
                                        .font(.system(size: 11))
                                }
                            }
                            .buttonStyle(.plain).foregroundStyle(Theme.subtle)
                            .disabled(exporting.contains(sid))
                        }

                        Button { regenerate(sid) } label: {
                            HStack(spacing: 5) {
                                if regenerating.contains(sid) { ProgressView().controlSize(.small) }
                                else { Image(systemName: "sparkles").font(.system(size: 11)) }
                                Text(regenerating.contains(sid) ? "Regenerating…" : "Regenerate notes")
                                    .font(.system(size: 11))
                            }
                        }
                        .buttonStyle(.plain).foregroundStyle(Theme.subtle)
                        .disabled(regenerating.contains(sid))

                        Spacer()
                    }

                    if let msg = exportMsg[sid] {
                        Text(msg).font(.system(size: 10.5)).foregroundStyle(Theme.faint)
                    }
                }
            }
        }
    }

    // MARK: - Insight sections

    @ViewBuilder
    private func sectionHeader(_ title: String, icon: String) -> some View {
        HStack(spacing: 5) {
            Image(systemName: icon).font(.system(size: 10))
            Text(title.uppercased()).font(.system(size: 10, weight: .semibold)).tracking(0.6)
        }
        .foregroundStyle(Theme.faint)
        .padding(.top, 2)
    }

    @ViewBuilder
    private func bulletRow(_ text: String) -> some View {
        HStack(alignment: .top, spacing: 6) {
            Text("•").font(.system(size: 12)).foregroundStyle(Theme.faint)
            Text(text).font(.system(size: 12)).foregroundStyle(Theme.text)
                .fixedSize(horizontal: false, vertical: true)
        }
        .textSelection(.enabled)
    }

    @ViewBuilder
    private func bulletSection(_ title: String, icon: String, items: [String]?) -> some View {
        if let items, !items.isEmpty {
            VStack(alignment: .leading, spacing: 5) {
                sectionHeader(title, icon: icon)
                ForEach(Array(items.enumerated()), id: \.offset) { _, item in
                    bulletRow(item)
                }
            }
        }
    }

    @ViewBuilder
    private func actionItemsSection(_ items: [PythonBridge.MeetingActionItem]?) -> some View {
        if let items, !items.isEmpty {
            VStack(alignment: .leading, spacing: 5) {
                sectionHeader("Action items", icon: "checkmark.circle")
                ForEach(items) { it in
                    HStack(alignment: .top, spacing: 6) {
                        Image(systemName: "square").font(.system(size: 11)).foregroundStyle(Theme.faint).padding(.top, 1)
                        VStack(alignment: .leading, spacing: 1) {
                            Text(it.task).font(.system(size: 12)).foregroundStyle(Theme.text)
                                .fixedSize(horizontal: false, vertical: true)
                            let meta = Self.actionMeta(owner: it.owner, due: it.due)
                            if !meta.isEmpty {
                                Text(meta).font(.system(size: 10.5)).foregroundStyle(Theme.faint)
                            }
                        }
                    }
                    .textSelection(.enabled)
                }
            }
        }
    }

    @ViewBuilder
    private func followUpsSection(_ items: [PythonBridge.MeetingFollowUp]?) -> some View {
        if let items, !items.isEmpty {
            VStack(alignment: .leading, spacing: 5) {
                sectionHeader("Follow-ups", icon: "arrow.uturn.right")
                ForEach(items) { it in
                    HStack(alignment: .top, spacing: 6) {
                        Text("•").font(.system(size: 12)).foregroundStyle(Theme.faint)
                        Text(it.person.isEmpty ? it.task : "\(it.task) — with \(it.person)")
                            .font(.system(size: 12)).foregroundStyle(Theme.text)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    .textSelection(.enabled)
                }
            }
        }
    }

    private func regenerate(_ sid: String) {
        regenerating.insert(sid)
        Task {
            _ = try? await PythonBridge.shared.regenerateMeetingInsights(sessionId: sid)
            meetings = (try? await PythonBridge.shared.getMeetings()) ?? meetings
            regenerating.remove(sid)
        }
    }

    private func exportReminders(_ sid: String) {
        exporting.insert(sid)
        Task {
            if let res = try? await PythonBridge.shared.exportMeetingReminders(sessionId: sid) {
                exportMsg[sid] = res.message
            } else {
                exportMsg[sid] = "Couldn't reach the Reminders app."
            }
            meetings = (try? await PythonBridge.shared.getMeetings()) ?? meetings
            exporting.remove(sid)
        }
    }

    static func actionMeta(owner: String, due: String) -> String {
        var parts: [String] = []
        if !owner.isEmpty { parts.append(owner) }
        if !due.isEmpty { parts.append("due \(due)") }
        return parts.joined(separator: " · ")
    }

    private func toggle(_ on: Bool) {
        loadingToggle = true
        Task {
            do {
                if on { _ = try await PythonBridge.shared.startMeetingDetection(); enabled = true }
                else { _ = try await PythonBridge.shared.stopMeetingDetection(); enabled = false; inProgress = false; paused = false }
            } catch { enabled = !on }
            loadingToggle = false
        }
    }
    private func loadStatus() {
        Task {
            if let s = try? await PythonBridge.shared.getMeetingStatus() {
                enabled = s.enabled; inProgress = s.in_meeting; paused = s.paused ?? false; platform = s.current?.platform ?? ""
            }
        }
    }
    private func loadList() {
        loadingList = true
        Task { meetings = (try? await PythonBridge.shared.getMeetings()) ?? []; loadingList = false }
    }

    static func dur(_ s: Double) -> String { s < 60 ? "\(Int(s))s" : "\(Int(s/60))m" }
    static let iso: DateFormatter = { let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"; f.locale = Locale(identifier: "en_US_POSIX"); return f }()
    static let out: DateFormatter = { let f = DateFormatter(); f.dateFormat = "MMM d, h:mm a"; return f }()
    static func pretty(_ s: String?) -> String { guard let s, let d = iso.date(from: s) else { return "" }; return out.string(from: d) }
}
