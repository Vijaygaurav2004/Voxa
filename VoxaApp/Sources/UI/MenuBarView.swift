import SwiftUI

/// Menu bar dropdown view for the Voxa menu bar extra.
struct MenuBarView: View {
    @EnvironmentObject var engine: VoxaEngine
    @EnvironmentObject var state: VoxaState

    @State private var commandText: String = ""

    var body: some View {
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

            // Backend status
            HStack {
                Image(systemName: state.isBackendReady ? "checkmark.circle.fill" : "xmark.circle.fill")
                    .foregroundStyle(state.isBackendReady ? .green : .red)
                Text(state.isBackendReady ? "Backend connected" : "Backend offline")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Spacer()
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

                Button("Quit") {
                    engine.stop()
                    NSApplication.shared.terminate(nil)
                }
                .font(.caption)
                .foregroundStyle(.red)
            }
            .padding(.horizontal)
        }
        .padding(.vertical, 12)
        .frame(width: 320)
    }
}
