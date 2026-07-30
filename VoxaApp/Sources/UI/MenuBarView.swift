import SwiftUI
import AppKit

/// Menu bar dropdown view for the Voxa menu bar extra.
struct MenuBarView: View {
    @EnvironmentObject var engine: VoxaEngine
    @EnvironmentObject var state: VoxaState
    @ObservedObject private var perch = PerchSettings.shared
    @ObservedObject private var perchManager = PerchManager.shared

    @State private var commandText: String = ""
    @State private var showingSettings: Bool = false
    @State private var showingMeetings: Bool = false
    @State private var meetings: [PythonBridge.MeetingRecord] = []
    @State private var meetingsLoading: Bool = false
    @State private var modes: [VoxaMode] = []
    @State private var isLoading: Bool = false
    @State private var errorText: String? = nil
    @State private var memoryActive: Bool = false
    @State private var memoryLoading: Bool = false
    @State private var chatBallVisible: Bool = true

    // Meeting auto-detection (Granola-style)
    @State private var meetingEnabled: Bool = false
    @State private var meetingLoading: Bool = false
    @State private var meetingInProgress: Bool = false
    @State private var meetingPaused: Bool = false
    @State private var meetingPlatform: String = ""

    // Edit/Create states
    @State private var isEditing: Bool = false
    @State private var isNewMode: Bool = false
    @State private var modeName: String = ""
    @State private var modeDescription: String = ""
    @State private var modeInstructions: [InstructionItem] = [InstructionItem(text: "")]

    // AI "describe it in plain English" generation
    @State private var aiDescription: String = ""
    @State private var isGenerating: Bool = false

    struct InstructionItem: Identifiable {
        let id = UUID()
        var text: String
    }

    var body: some View {
        Group {
            if showingSettings {
                settingsView
            } else if showingMeetings {
                meetingsView
            } else {
                mainView
            }
        }
        .padding(.vertical, 12)
        .frame(width: 320)
        .onAppear {
            loadModes()
            loadMemoryStatus()
            loadMeetingStatus()
        }
    }

    // MARK: - Main View
    var mainView: some View {
        VStack(spacing: 12) {
            header
            statusRow
            commandInput
            listenButton

            if !state.recentCommands.isEmpty {
                recentSection
            }

            settingsCards
            footer
        }
    }

    // MARK: - Header

    private var header: some View {
        HStack(spacing: 10) {
            // Same mark as the main window's sidebar.
            ZStack {
                RoundedRectangle(cornerRadius: 9, style: .continuous)
                    .fill(Color.primary).frame(width: 30, height: 30)
                Image(systemName: "waveform")
                    .font(.system(size: 14, weight: .bold))
                    .foregroundStyle(Color(NSColor.windowBackgroundColor))
            }
            VStack(alignment: .leading, spacing: 1) {
                Text("Voxa").font(.system(size: 16, weight: .bold))
                Text(state.isBackendReady ? "Ready" : "Starting up…")
                    .font(.system(size: 10)).foregroundStyle(Theme.subtle)
            }
            Spacer()
            HStack(spacing: 5) {
                Circle()
                    .fill(state.isBackendReady ? Color.primary : Theme.faint)
                    .frame(width: 6, height: 6)
                Text(state.isBackendReady ? "Online" : "Offline")
                    .font(.system(size: 10, weight: .medium))
                    .foregroundStyle(Theme.subtle)
            }
            .padding(.horizontal, 8).padding(.vertical, 4)
            .background(Capsule().fill(Theme.card))
            .overlay(Capsule().strokeBorder(Theme.stroke, lineWidth: 1))
        }
        .padding(.horizontal)
    }

    // MARK: - Status Row

    private var statusRow: some View {
        HStack(spacing: 8) {
            Circle()
                .fill(state.pipelineState == .idle ? Theme.faint : Color.primary)
                .frame(width: 8, height: 8)
            Text(state.statusMessage)
                .font(.system(size: 12)).foregroundStyle(Theme.subtle).lineLimit(1)
            Spacer()
        }
        .padding(.horizontal, 12).padding(.vertical, 8)
        .background(RoundedRectangle(cornerRadius: Theme.radiusSmall, style: .continuous).fill(Theme.card))
        .overlay(RoundedRectangle(cornerRadius: Theme.radiusSmall, style: .continuous).strokeBorder(Theme.stroke, lineWidth: 1))
        .padding(.horizontal)
    }

    // MARK: - Command Input

    private var commandInput: some View {
        HStack(spacing: 8) {
            HStack(spacing: 8) {
                TextField("Ask Voxa to do something…", text: $commandText)
                    .textFieldStyle(.plain)
                    .font(.system(size: 13))
                    .onSubmit(submitCommand)
                if !commandText.isEmpty {
                    Button { commandText = "" } label: {
                        Image(systemName: "xmark.circle.fill").foregroundStyle(Theme.faint)
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(.horizontal, 12).padding(.vertical, 9)
            .background(RoundedRectangle(cornerRadius: Theme.radiusSmall, style: .continuous).fill(Theme.card))
            .overlay(RoundedRectangle(cornerRadius: Theme.radiusSmall, style: .continuous).strokeBorder(Theme.stroke, lineWidth: 1))

            Button(action: submitCommand) {
                Image(systemName: "arrow.up")
                    .font(.system(size: 13, weight: .bold))
                    .foregroundStyle(commandText.trimmed.isEmpty
                                     ? AnyShapeStyle(Theme.faint)
                                     : AnyShapeStyle(Color(NSColor.windowBackgroundColor)))
                    .frame(width: 34, height: 34)
                    .background(
                        RoundedRectangle(cornerRadius: Theme.radiusSmall, style: .continuous)
                            .fill(commandText.trimmed.isEmpty ? Theme.card : Color.primary)
                    )
            }
            .buttonStyle(.plain)
            .disabled(commandText.trimmed.isEmpty)
        }
        .padding(.horizontal)
    }

    // MARK: - Listen Button

    private var listenButton: some View {
        Button {
            Task { await engine.triggerVoiceCommand() }
        } label: {
            HStack(spacing: 6) {
                Image(systemName: "mic.fill")
                Text("Tap to speak").fontWeight(.semibold)
                Text("· ⌘⇧V").foregroundStyle(Color(NSColor.windowBackgroundColor).opacity(0.6))
            }
            .font(.system(size: 12))
            .foregroundStyle(Color(NSColor.windowBackgroundColor))
            .frame(maxWidth: .infinity)
            .padding(.vertical, 10)
            .background(RoundedRectangle(cornerRadius: Theme.radiusSmall, style: .continuous).fill(Color.primary))
        }
        .buttonStyle(.plain)
        .padding(.horizontal)
    }

    // MARK: - Recent

    private var recentSection: some View {
        VStack(alignment: .leading, spacing: 6) {
            SectionLabel(text: "Recent").padding(.horizontal)

            ForEach(state.recentCommands.prefix(4), id: \.self) { command in
                Button {
                    Task { await engine.processCommand(command) }
                } label: {
                    HStack(spacing: 8) {
                        Image(systemName: "arrow.counterclockwise")
                            .font(.system(size: 10)).foregroundStyle(Theme.subtle)
                        Text(command)
                            .font(.system(size: 12)).lineLimit(1).foregroundStyle(Theme.text)
                        Spacer()
                        Image(systemName: "arrow.up.backward")
                            .font(.system(size: 9)).foregroundStyle(Theme.faint)
                    }
                    .padding(.horizontal, 10).padding(.vertical, 7)
                    .background(RoundedRectangle(cornerRadius: Theme.radiusSmall, style: .continuous).fill(Theme.card))
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .padding(.horizontal)
            }
        }
    }

    // MARK: - Setting Cards

    private var settingsCards: some View {
        VStack(spacing: 8) {
            toggleCard(
                icon: "sparkles.rectangle.stack",
                title: "Notch Halo",
                subtitle: "Wrap the animation around the notch",
                isOn: $state.useNotchHalo
            )
            toggleCard(
                icon: meetingInProgress ? "person.2.wave.2.fill" : "calendar.badge.clock",
                title: "Meeting Notes",
                subtitle: meetingInProgress
                    ? (meetingPaused ? "In a \(meetingPlatform) meeting — paused" : "Recording \(meetingPlatform) meeting")
                    : (meetingEnabled ? "Auto-detecting meetings" : "Auto-capture meetings like Granola"),
                isOn: Binding(get: { meetingEnabled }, set: { toggleMeetingDetection($0) }),
                loading: meetingLoading
            )
            if meetingInProgress {
                meetingControls
            }
            toggleCard(
                icon: memoryActive ? "brain.head.profile" : "brain",
                title: "Memory",
                subtitle: memoryActive ? "Listening for recall" : "Ambient recall is off",
                isOn: Binding(get: { memoryActive }, set: { toggleMemory($0) }),
                loading: memoryLoading
            )
            perchCard
            toggleCard(
                icon: "bubble.left.and.bubble.right.fill",
                title: "Chat Ball",
                subtitle: "Floating chat button on screen",
                isOn: Binding(
                    get: { chatBallVisible },
                    set: { newValue in
                        chatBallVisible = newValue
                        newValue ? FloatingBallManager.shared.show() : FloatingBallManager.shared.hide()
                    }
                )
            )
        }
        .padding(.horizontal)
    }

    /// The perch gets its own card because it needs BOTH an on/off switch and a
    /// way to open it by hand. Hover-reveal depends on a global mouse monitor,
    /// which silently does nothing without Accessibility permission — without
    /// this button there would be no way to open the perch at all on a Mac where
    /// that was denied, or on one with no notch to point at.
    private var perchCard: some View {
        HStack(spacing: 10) {
            Button {
                if perch.enabled { perchManager.toggle() }
            } label: {
                ZStack {
                    RoundedRectangle(cornerRadius: Theme.radiusSmall, style: .continuous)
                        .fill(Theme.card).frame(width: 30, height: 30)
                    Image(systemName: "macbook.gen2")
                        .font(.system(size: 13, weight: .medium))
                        .foregroundStyle(perch.enabled ? Theme.text : Theme.faint)
                }
            }
            .buttonStyle(.plain)
            .disabled(!perch.enabled)
            .help(perch.enabled ? "Open or close the perch" : "Turn the perch on first")

            VStack(alignment: .leading, spacing: 1) {
                Text("Notch Perch").font(.system(size: 12, weight: .medium)).foregroundStyle(Theme.text)
                Text(perch.enabled
                     ? (perchManager.isOpen ? "Open — click the icon to close" : "Point at the notch, or click the icon")
                     : "Shelf that drops from the notch")
                    .font(.system(size: 10)).foregroundStyle(Theme.subtle).lineLimit(1)
            }
            Spacer(minLength: 6)
            MonoToggle(isOn: $perch.enabled)
        }
        .padding(.horizontal, 10).padding(.vertical, 8)
        .background(RoundedRectangle(cornerRadius: Theme.radius, style: .continuous).fill(Theme.card))
        .overlay(RoundedRectangle(cornerRadius: Theme.radius, style: .continuous).strokeBorder(Theme.stroke, lineWidth: 1))
    }

    /// Pause / Resume + End controls, shown while a meeting is being recorded.
    private var meetingControls: some View {
        HStack(spacing: 8) {
            Button {
                pauseResumeMeeting()
            } label: {
                HStack(spacing: 5) {
                    Image(systemName: meetingPaused ? "play.fill" : "pause.fill")
                    Text(meetingPaused ? "Resume" : "Pause")
                }
                .font(.system(size: 11, weight: .medium))
                .foregroundStyle(Theme.text)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 6)
                .background(RoundedRectangle(cornerRadius: Theme.radiusSmall, style: .continuous).fill(Theme.card))
                .overlay(RoundedRectangle(cornerRadius: Theme.radiusSmall, style: .continuous).strokeBorder(Theme.stroke, lineWidth: 1))
            }
            .buttonStyle(.plain)

            Button {
                endMeetingRecording()
            } label: {
                HStack(spacing: 5) {
                    Image(systemName: "stop.fill")
                    Text("End & Save")
                }
                .font(.system(size: 11, weight: .medium))
                .foregroundStyle(.red)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 6)
                .background(RoundedRectangle(cornerRadius: 7).fill(Color.red.opacity(0.08)))
            }
            .buttonStyle(.plain)
        }
    }

    private func toggleCard(
        icon: String,
        title: String,
        subtitle: String,
        isOn: Binding<Bool>,
        loading: Bool = false
    ) -> some View {
        HStack(spacing: 10) {
            ZStack {
                RoundedRectangle(cornerRadius: Theme.radiusSmall, style: .continuous)
                    .fill(Theme.card).frame(width: 30, height: 30)
                Image(systemName: icon)
                    .font(.system(size: 13, weight: .medium)).foregroundStyle(Theme.text)
            }
            VStack(alignment: .leading, spacing: 1) {
                Text(title).font(.system(size: 12, weight: .medium)).foregroundStyle(Theme.text)
                Text(subtitle).font(.system(size: 10)).foregroundStyle(Theme.subtle).lineLimit(1)
            }
            Spacer(minLength: 6)
            if loading {
                ProgressView().controlSize(.small)
            } else {
                MonoToggle(isOn: isOn)
            }
        }
        .padding(.horizontal, 10).padding(.vertical, 8)
        .background(RoundedRectangle(cornerRadius: Theme.radius, style: .continuous).fill(Theme.card))
        .overlay(RoundedRectangle(cornerRadius: Theme.radius, style: .continuous).strokeBorder(Theme.stroke, lineWidth: 1))
    }

    // MARK: - Footer

    private var footer: some View {
        HStack(spacing: 8) {
            footerButton(icon: "circle.hexagongrid", title: "Wheel") {
                RadialLauncher.shared.show()
            }
            footerButton(icon: "slider.horizontal.3", title: "Modes") {
                showingSettings = true
                loadModes()
            }
            footerButton(icon: "doc.text.magnifyingglass", title: "Notes") {
                showingMeetings = true
                loadMeetings()
            }
            Button {
                engine.stop()
                NSApplication.shared.terminate(nil)
            } label: {
                HStack(spacing: 5) {
                    Image(systemName: "power")
                    Text("Quit")
                }
                .font(.system(size: 12, weight: .medium))
                .foregroundStyle(.red)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 8)
                .background(RoundedRectangle(cornerRadius: Theme.radiusSmall, style: .continuous).fill(Theme.card))
                .overlay(RoundedRectangle(cornerRadius: Theme.radiusSmall, style: .continuous).strokeBorder(Theme.stroke, lineWidth: 1))
            }
            .buttonStyle(.plain)
        }
        .padding(.horizontal)
    }

    private func footerButton(icon: String, title: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: 5) {
                Image(systemName: icon)
                Text(title)
            }
            .font(.system(size: 12, weight: .medium))
            .foregroundStyle(Theme.text)
            .frame(maxWidth: .infinity)
            .padding(.vertical, 8)
            .background(RoundedRectangle(cornerRadius: Theme.radiusSmall, style: .continuous).fill(Theme.card))
            .overlay(RoundedRectangle(cornerRadius: Theme.radiusSmall, style: .continuous).strokeBorder(Theme.stroke, lineWidth: 1))
        }
        .buttonStyle(.plain)
    }

    // MARK: - Meetings View

    private var meetingsView: some View {
        VStack(spacing: 12) {
            HStack {
                Button { showingMeetings = false } label: {
                    Image(systemName: "chevron.left").font(.title3)
                }
                .buttonStyle(.plain)
                Text("Meeting Notes").font(.headline)
                Spacer()
                if meetingsLoading {
                    ProgressView().controlSize(.small)
                } else {
                    Button { loadMeetings() } label: { Image(systemName: "arrow.clockwise") }
                        .buttonStyle(.plain)
                }
            }
            .padding(.horizontal)

            Divider()

            if meetings.isEmpty && !meetingsLoading {
                VStack(spacing: 10) {
                    Spacer()
                    Image(systemName: "text.badge.checkmark")
                        .font(.system(size: 34))
                        .foregroundStyle(.secondary)
                    Text("No meeting notes yet")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                    Text("Notes appear here after Voxa records a meeting.")
                        .font(.caption)
                        .foregroundStyle(.tertiary)
                        .multilineTextAlignment(.center)
                    Spacer()
                }
                .frame(height: 220)
                .padding(.horizontal)
            } else {
                ScrollView {
                    VStack(spacing: 10) {
                        ForEach(meetings) { meetingCard($0) }
                    }
                    .padding(.horizontal)
                    .padding(.top, 4)
                }
                .frame(maxHeight: 340)
            }
        }
    }

    private func meetingCard(_ m: PythonBridge.MeetingRecord) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 6) {
                Image(systemName: "person.2.fill")
                    .font(.caption)
                    .foregroundStyle(Theme.subtle)
                Text(m.platform ?? "Meeting")
                    .font(.subheadline).bold()
                Spacer()
                Text(Self.prettyDate(m.started_iso))
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }
            if let secs = m.duration_secs, secs > 0 {
                Text(Self.durationText(secs))
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
            }
            Text((m.summary?.isEmpty == false) ? m.summary! : "No summary was generated for this meeting.")
                .font(.caption)
                .foregroundStyle(.secondary)
                .textSelection(.enabled)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(10)
        .background(RoundedRectangle(cornerRadius: 8).fill(Color(NSColor.windowBackgroundColor)))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color.secondary.opacity(0.2), lineWidth: 1))
    }

    private func loadMeetings() {
        meetingsLoading = true
        Task {
            do {
                self.meetings = try await PythonBridge.shared.getMeetings()
            } catch {
                self.meetings = []
            }
            self.meetingsLoading = false
        }
    }

    private static func durationText(_ secs: Double) -> String {
        if secs < 60 { return "\(Int(secs))s" }
        let m = Int(secs / 60), s = Int(secs.truncatingRemainder(dividingBy: 60))
        return s > 0 ? "\(m)m \(s)s" : "\(m)m"
    }

    private static let isoParser: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
        f.locale = Locale(identifier: "en_US_POSIX")
        return f
    }()
    private static let prettyFormatter: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "MMM d, h:mm a"
        return f
    }()
    private static func prettyDate(_ iso: String?) -> String {
        guard let iso, let d = isoParser.date(from: iso) else { return "" }
        return prettyFormatter.string(from: d)
    }

    private func submitCommand() {
        let cmd = commandText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !cmd.isEmpty else { return }
        commandText = ""
        Task { await engine.processCommand(cmd) }
    }

    // MARK: - Settings View
    var settingsView: some View {
        VStack(spacing: 12) {
            // Header
            HStack {
                Button {
                    if isEditing {
                        isEditing = false
                        errorText = nil
                    } else {
                        showingSettings = false
                    }
                } label: {
                    Image(systemName: "chevron.left")
                        .font(.title3)
                }
                .buttonStyle(.plain)
                
                Text(isEditing ? (isNewMode ? "Create Mode" : "Edit Mode") : "Custom Modes")
                    .font(.headline)
                
                Spacer()
                
                if isLoading {
                    ProgressView()
                        .controlSize(.small)
                }
            }
            .padding(.horizontal)
            
            Divider()
            
            if let errorText = errorText {
                HStack {
                    Text(errorText)
                        .font(.caption)
                        .foregroundStyle(.red)
                        .multilineTextAlignment(.leading)
                    Spacer()
                }
                .padding(8)
                .background(Color.red.opacity(0.1))
                .cornerRadius(6)
                .padding(.horizontal)
            }
            
            if isEditing {
                // Edit/Create Mode View
                ScrollView {
                    VStack(alignment: .leading, spacing: 14) {
                        // ✨ AI generation — describe the mode in plain English and
                        // let the small LLM fill in the name + steps for review.
                        aiGenerateSection

                        VStack(alignment: .leading, spacing: 4) {
                            Text("Mode Name")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                            TextField("e.g. Work Mode", text: $modeName)
                                .textFieldStyle(.roundedBorder)
                                .disabled(!isNewMode)
                        }
                        
                        VStack(alignment: .leading, spacing: 4) {
                            Text("Description (Optional)")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                            TextField("Short description", text: $modeDescription)
                                .textFieldStyle(.roundedBorder)
                        }
                        
                        VStack(alignment: .leading, spacing: 8) {
                            HStack {
                                Text("Instructions")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                                Spacer()
                                Button("+ Add") {
                                    modeInstructions.append(InstructionItem(text: ""))
                                }
                                .font(.caption)
                            }
                            
                            ForEach($modeInstructions) { $item in
                                HStack {
                                    let index = modeInstructions.firstIndex(where: { $0.id == item.id }) ?? 0
                                    Text("\(index + 1)")
                                        .font(.caption2)
                                        .foregroundStyle(.secondary)
                                        .frame(width: 15)
                                    
                                    TextField("e.g. open Chrome", text: $item.text)
                                        .textFieldStyle(.roundedBorder)
                                    
                                    Button {
                                        if modeInstructions.count > 1 {
                                            modeInstructions.removeAll(where: { $0.id == item.id })
                                        }
                                    } label: {
                                        Image(systemName: "trash")
                                            .foregroundStyle(.red)
                                    }
                                    .disabled(modeInstructions.count <= 1)
                                    .buttonStyle(.plain)
                                }
                            }
                        }
                    }
                    .padding(.horizontal)
                    .padding(.top, 4)
                }
                
                Divider()
                
                HStack {
                    Button("Cancel") {
                        isEditing = false
                        errorText = nil
                    }
                    .font(.caption)
                    
                    Spacer()
                    
                    Button("Save") {
                        saveMode()
                    }
                    .font(.caption)
                    .buttonStyle(.borderedProminent)
                }
                .padding(.horizontal)
            } else {
                // Modes List View
                if modes.isEmpty && !isLoading {
                    VStack(spacing: 12) {
                        Spacer()
                        Image(systemName: "slider.horizontal.3")
                            .font(.system(size: 36))
                            .foregroundStyle(.secondary)
                        Text("No custom modes defined.")
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                        Spacer()
                    }
                    .frame(height: 200)
                } else {
                    ScrollView {
                        VStack(spacing: 10) {
                            ForEach(modes) { mode in
                                VStack(alignment: .leading, spacing: 6) {
                                    HStack {
                                        Text(mode.name)
                                            .font(.subheadline)
                                            .bold()
                                        Spacer()
                                        
                                        HStack(spacing: 12) {
                                            Button {
                                                startEditing(mode)
                                            } label: {
                                                Image(systemName: "pencil")
                                                    .foregroundStyle(Theme.subtle)
                                            }
                                            .buttonStyle(.plain)
                                            
                                            Button {
                                                deleteMode(name: mode.name)
                                            } label: {
                                                Image(systemName: "trash")
                                                    .foregroundStyle(.red)
                                            }
                                            .buttonStyle(.plain)
                                        }
                                    }
                                    
                                    if !mode.description.isEmpty {
                                        Text(mode.description)
                                            .font(.caption)
                                            .foregroundStyle(.secondary)
                                            .lineLimit(2)
                                    }
                                    
                                    VStack(alignment: .leading, spacing: 2) {
                                        ForEach(mode.instructions.prefix(3), id: \.self) { inst in
                                            HStack(alignment: .top, spacing: 4) {
                                                Circle()
                                                    .fill(Color.secondary)
                                                    .frame(width: 4, height: 4)
                                                    .padding(.top, 5)
                                                Text(inst)
                                                    .font(.caption2)
                                                    .foregroundStyle(.secondary)
                                                    .lineLimit(1)
                                            }
                                        }
                                        if mode.instructions.count > 3 {
                                            Text("+ \(mode.instructions.count - 3) more...")
                                                .font(.caption2)
                                                .foregroundStyle(.secondary)
                                                .italic()
                                                .padding(.leading, 8)
                                        }
                                    }
                                    .padding(.top, 2)
                                }
                                .padding(10)
                                .background(Color(NSColor.windowBackgroundColor))
                                .cornerRadius(8)
                                .overlay(
                                    RoundedRectangle(cornerRadius: 8)
                                        .stroke(Color.secondary.opacity(0.2), lineWidth: 1)
                                )
                            }
                        }
                        .padding(.horizontal)
                        .padding(.top, 4)
                    }
                    .frame(maxHeight: 280)
                }
                
                Divider()
                
                Button(action: startCreating) {
                    HStack {
                        Image(systemName: "plus.circle.fill")
                        Text("Add New Mode")
                    }
                    .frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.regular)
                .padding(.horizontal)
            }
        }
    }

    // MARK: - AI Generate Section

    /// "Describe it in plain English" — the small LLM drafts the name + steps,
    /// which populate the form below for the user to review and save.
    var aiGenerateSection: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 4) {
                Image(systemName: "sparkles")
                    .foregroundStyle(
                        LinearGradient(colors: [.purple, .blue],
                                       startPoint: .leading, endPoint: .trailing)
                    )
                Text("Describe it — Voxa builds it")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            HStack(spacing: 6) {
                TextField("e.g. a work mode that opens VS Code and mutes notifications",
                          text: $aiDescription, axis: .vertical)
                    .textFieldStyle(.roundedBorder)
                    .lineLimit(1...3)
                    .font(.caption)
                    .disabled(isGenerating)
                    .onSubmit(generateFromDescription)

                Button(action: generateFromDescription) {
                    if isGenerating {
                        ProgressView().controlSize(.small)
                    } else {
                        Image(systemName: "wand.and.stars")
                    }
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.regular)
                .disabled(isGenerating ||
                          aiDescription.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                .help("Generate a mode from your description")
            }
        }
        .padding(10)
        .background(
            RoundedRectangle(cornerRadius: Theme.radiusSmall, style: .continuous)
                .fill(Theme.card)
        )
        .overlay(
            RoundedRectangle(cornerRadius: 8)
                .stroke(
                    LinearGradient(colors: [.purple.opacity(0.35), .blue.opacity(0.35)],
                                   startPoint: .leading, endPoint: .trailing),
                    lineWidth: 1
                )
        )
    }

    private func generateFromDescription() {
        let desc = aiDescription.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !desc.isEmpty, !isGenerating else { return }

        isGenerating = true
        errorText = nil
        Task {
            do {
                let spec = try await PythonBridge.shared.generateModeSpec(description: desc)
                await MainActor.run {
                    // When editing, don't overwrite the user's existing name or a
                    // description they've already written — only fill blanks.
                    if isNewMode { modeName = spec.name }
                    if isNewMode || modeDescription.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                        modeDescription = spec.description
                    }
                    let items = spec.instructions.map { InstructionItem(text: $0) }
                    modeInstructions = items.isEmpty ? [InstructionItem(text: "")] : items
                    isGenerating = false
                }
            } catch {
                await MainActor.run {
                    errorText = "Couldn't generate that mode. Try rephrasing."
                    isGenerating = false
                }
            }
        }
    }

    // MARK: - Actions & CRUD Logic

    private func loadModes() {
        isLoading = true
        errorText = nil
        Task {
            do {
                self.modes = try await PythonBridge.shared.getModes()
            } catch {
                self.errorText = "Failed to load modes: \(error.localizedDescription)"
            }
            self.isLoading = false
        }
    }

    private func deleteMode(name: String) {
        isLoading = true
        errorText = nil
        Task {
            do {
                let res = try await PythonBridge.shared.deleteMode(name: name)
                if res.success {
                    loadModes()
                } else {
                    self.errorText = res.message
                    self.isLoading = false
                }
            } catch {
                self.errorText = "Failed to delete: \(error.localizedDescription)"
                self.isLoading = false
            }
        }
    }

    private func startEditing(_ mode: VoxaMode) {
        modeName = mode.name
        modeDescription = mode.description
        modeInstructions = mode.instructions.map { InstructionItem(text: $0) }
        if modeInstructions.isEmpty {
            modeInstructions = [InstructionItem(text: "")]
        }
        isNewMode = false
        isEditing = true
        errorText = nil
        aiDescription = ""
    }

    private func startCreating() {
        modeName = ""
        modeDescription = ""
        modeInstructions = [InstructionItem(text: "")]
        isNewMode = true
        isEditing = true
        errorText = nil
        aiDescription = ""
    }

    private func saveMode() {
        guard !modeName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            self.errorText = "Mode name cannot be empty"
            return
        }
        let filteredInstructions = modeInstructions.map { $0.text.trimmingCharacters(in: .whitespacesAndNewlines) }.filter { !$0.isEmpty }
        guard !filteredInstructions.isEmpty else {
            self.errorText = "Add at least one instruction"
            return
        }
        
        isLoading = true
        errorText = nil
        
        Task {
            do {
                let res: PythonBridge.ModeActionResponse
                if isNewMode {
                    res = try await PythonBridge.shared.createMode(
                        name: modeName,
                        instructions: filteredInstructions,
                        description: modeDescription
                    )
                } else {
                    res = try await PythonBridge.shared.updateMode(
                        name: modeName,
                        instructions: filteredInstructions,
                        description: modeDescription
                    )
                }
                
                if res.success {
                    isEditing = false
                    loadModes()
                } else {
                    self.errorText = res.message
                    self.isLoading = false
                }
            } catch {
                self.errorText = "Failed to save: \(error.localizedDescription)"
                self.isLoading = false
            }
        }
    }

    // MARK: - Memory Actions

    private func loadMemoryStatus() {
        Task {
            do {
                let status = try await PythonBridge.shared.getMemoryStatus()
                self.memoryActive = status.active
            } catch {
                // Memory not available yet — that's fine
                self.memoryActive = false
            }
        }
    }

    private func toggleMemory(_ enable: Bool) {
        memoryLoading = true
        Task {
            do {
                if enable {
                    _ = try await PythonBridge.shared.startMemory()
                    self.memoryActive = true
                } else {
                    _ = try await PythonBridge.shared.stopMemory()
                    self.memoryActive = false
                }
            } catch {
                // Revert on failure
                self.memoryActive = !enable
            }
            self.memoryLoading = false
        }
    }

    // MARK: - Meeting Detection

    private func loadMeetingStatus() {
        Task {
            do {
                let status = try await PythonBridge.shared.getMeetingStatus()
                self.meetingEnabled = status.enabled
                self.meetingInProgress = status.in_meeting
                self.meetingPaused = status.paused ?? false
                self.meetingPlatform = status.current?.platform ?? ""
            } catch {
                self.meetingEnabled = false
                self.meetingInProgress = false
                self.meetingPaused = false
            }
        }
    }

    private func toggleMeetingDetection(_ enable: Bool) {
        meetingLoading = true
        Task {
            do {
                if enable {
                    _ = try await PythonBridge.shared.startMeetingDetection()
                    self.meetingEnabled = true
                } else {
                    _ = try await PythonBridge.shared.stopMeetingDetection()
                    self.meetingEnabled = false
                    self.meetingInProgress = false
                    self.meetingPaused = false
                }
            } catch {
                self.meetingEnabled = !enable
            }
            self.meetingLoading = false
        }
    }

    private func pauseResumeMeeting() {
        let wasPaused = meetingPaused
        meetingPaused.toggle()   // optimistic
        Task {
            do {
                if wasPaused {
                    _ = try await PythonBridge.shared.resumeMeeting()
                } else {
                    _ = try await PythonBridge.shared.pauseMeeting()
                }
            } catch {
                self.meetingPaused = wasPaused   // revert on failure
            }
        }
    }

    private func endMeetingRecording() {
        Task {
            _ = try? await PythonBridge.shared.endMeeting()
            self.meetingInProgress = false
            self.meetingPaused = false
        }
    }
}

