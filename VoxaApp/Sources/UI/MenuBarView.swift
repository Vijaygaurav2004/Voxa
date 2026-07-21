import SwiftUI
import AppKit

/// Menu bar dropdown view for the Voxa menu bar extra.
struct MenuBarView: View {
    @EnvironmentObject var engine: VoxaEngine
    @EnvironmentObject var state: VoxaState

    @State private var commandText: String = ""
    @State private var showingSettings: Bool = false
    @State private var modes: [VoxaMode] = []
    @State private var isLoading: Bool = false
    @State private var errorText: String? = nil
    @State private var memoryActive: Bool = false
    @State private var memoryLoading: Bool = false
    @State private var chatBallVisible: Bool = true

    // Edit/Create states
    @State private var isEditing: Bool = false
    @State private var isNewMode: Bool = false
    @State private var modeName: String = ""
    @State private var modeDescription: String = ""
    @State private var modeInstructions: [InstructionItem] = [InstructionItem(text: "")]

    struct InstructionItem: Identifiable {
        let id = UUID()
        var text: String
    }

    var body: some View {
        Group {
            if showingSettings {
                settingsView
            } else {
                mainView
            }
        }
        .padding(.vertical, 12)
        .frame(width: 320)
        .onAppear {
            loadModes()
            loadMemoryStatus()
        }
    }

    // MARK: - Main View
    var mainView: some View {
        VStack(spacing: 12) {
            // Header
            HStack {
                Image(systemName: "waveform.circle.fill")
                    .font(.title2)
                    .foregroundStyle(.cyan)
                Text("Voxa")
                    .font(.headline)
                Spacer()
                StatusIndicator()
                    .environmentObject(state)
            }
            .padding(.horizontal)

            Divider()

            // Status
            HStack {
                Circle()
                    .fill(state.stateColor)
                    .frame(width: 8, height: 8)
                Text(state.statusMessage)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                Spacer()
            }
            .padding(.horizontal)

            // Quick command input
            HStack {
                TextField("Type a command...", text: $commandText)
                    .textFieldStyle(.roundedBorder)
                    .onSubmit {
                        guard !commandText.isEmpty else { return }
                        let cmd = commandText
                        commandText = ""
                        Task {
                            await engine.processCommand(cmd)
                        }
                    }

                Button {
                    Task {
                        await engine.processCommand(commandText)
                    }
                } label: {
                    Image(systemName: "arrow.right.circle.fill")
                        .font(.title3)
                }
                .disabled(commandText.isEmpty)
                .buttonStyle(.plain)
            }
            .padding(.horizontal)

            Divider()

            // Recent commands
            if !state.recentCommands.isEmpty {
                VStack(alignment: .leading, spacing: 4) {
                    Text("Recent")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .padding(.horizontal)

                    ForEach(state.recentCommands.prefix(5), id: \.self) { command in
                        Button {
                            Task {
                                await engine.processCommand(command)
                            }
                        } label: {
                            HStack {
                                Image(systemName: "arrow.counterclockwise")
                                    .font(.caption2)
                                    .foregroundStyle(.secondary)
                                  Text(command)
                                    .font(.caption)
                                    .lineLimit(1)
                                Spacer()
                            }
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        .padding(.horizontal)
                    }
                }
            }

            Divider()

            // Backend status & Notch Halo Toggle
            HStack {
                HStack(spacing: 6) {
                    Image(systemName: state.isBackendReady ? "checkmark.circle.fill" : "xmark.circle.fill")
                        .foregroundStyle(state.isBackendReady ? .green : .red)
                    Text(state.isBackendReady ? "Backend connected" : "Backend offline")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                
                Spacer()
                
                Toggle(isOn: $state.useNotchHalo) {
                    Text("Notch Halo")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                .toggleStyle(.switch)
                .controlSize(.mini)
            }
            .padding(.horizontal)

            // Memory toggle
            HStack {
                HStack(spacing: 6) {
                    Image(systemName: memoryActive ? "brain.fill" : "brain")
                        .foregroundStyle(memoryActive ? .purple : .secondary)
                    Text(memoryActive ? "Memory active" : "Memory off")
                        .font(.caption)
                        .foregroundStyle(memoryActive ? .primary : .secondary)
                }
                
                Spacer()
                
                if memoryLoading {
                    ProgressView()
                        .controlSize(.mini)
                } else {
                    Toggle(isOn: Binding(
                        get: { memoryActive },
                        set: { newValue in
                            toggleMemory(newValue)
                        }
                    )) {
                        Text("")
                    }
                    .toggleStyle(.switch)
                    .controlSize(.mini)
                }
            }
            .padding(.horizontal)

            // Chat Ball toggle
            HStack {
                HStack(spacing: 6) {
                    Image(systemName: chatBallVisible ? "bubble.left.and.bubble.right.fill" : "bubble.left.and.bubble.right")
                        .foregroundStyle(chatBallVisible ? .blue : .secondary)
                    Text(chatBallVisible ? "Chat Ball on" : "Chat Ball off")
                        .font(.caption)
                        .foregroundStyle(chatBallVisible ? .primary : .secondary)
                }
                
                Spacer()
                
                Toggle(isOn: Binding(
                    get: { chatBallVisible },
                    set: { newValue in
                        chatBallVisible = newValue
                        if newValue {
                            FloatingBallManager.shared.show()
                        } else {
                            FloatingBallManager.shared.hide()
                        }
                    }
                )) {
                    Text("")
                }
                .toggleStyle(.switch)
                .controlSize(.mini)
            }
            .padding(.horizontal)

            // Controls
            HStack {
                Button("Voice ⌘⇧V") {
                    // Trigger voice command programmatically
                    // (hotkey handler will pick this up)
                }
                .font(.caption)

                Spacer()

                Button {
                    showingSettings = true
                    loadModes()
                } label: {
                    HStack(spacing: 4) {
                        Image(systemName: "gearshape")
                        Text("Settings")
                    }
                }
                .font(.caption)

                Spacer()

                Button("Quit") {
                    engine.stop()
                    NSApplication.shared.terminate(nil)
                }
                .font(.caption)
                .foregroundStyle(.red)
            }
            .padding(.horizontal)
        }
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
                                                    .foregroundStyle(.blue)
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
    }

    private func startCreating() {
        modeName = ""
        modeDescription = ""
        modeInstructions = [InstructionItem(text: "")]
        isNewMode = true
        isEditing = true
        errorText = nil
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
}

