import SwiftUI

struct HomePage: View {
    @EnvironmentObject var engine: VoxaEngine
    @EnvironmentObject var state: VoxaState
    @State private var command: String = ""
    @State private var chatBallVisible: Bool = FloatingBallManager.shared.isShowing

    var body: some View {
        Page(title: "Home", subtitle: "Ask Voxa, or run a quick command") {
            // Status
            Card {
                HStack(spacing: 10) {
                    Circle().fill(state.stateColor).frame(width: 9, height: 9)
                    Text(state.statusMessage).font(.system(size: 13)).foregroundStyle(Theme.text)
                    Spacer()
                    Text(state.pipelineState.rawValue.capitalized)
                        .font(.system(size: 11, weight: .medium)).foregroundStyle(Theme.subtle)
                }
            }

            // Command input
            VStack(spacing: 10) {
                HStack(spacing: 10) {
                    TextField("Ask Voxa to do something…", text: $command)
                        .textFieldStyle(.plain)
                        .font(.system(size: 14))
                        .padding(.horizontal, 14).padding(.vertical, 12)
                        .background(RoundedRectangle(cornerRadius: Theme.radius, style: .continuous).fill(Theme.card))
                        .overlay(RoundedRectangle(cornerRadius: Theme.radius, style: .continuous).strokeBorder(Theme.stroke, lineWidth: 1))
                        .onSubmit(send)

                    Button(action: send) {
                        Image(systemName: "arrow.up").font(.system(size: 15, weight: .bold))
                            .foregroundStyle(Color(NSColor.windowBackgroundColor))
                            .frame(width: 42, height: 42)
                            .background(Circle().fill(command.trimmed.isEmpty ? Theme.card : Color.primary))
                    }
                    .buttonStyle(.plain)
                    .disabled(command.trimmed.isEmpty)
                }

                Button {
                    Task { await engine.triggerVoiceCommand() }
                } label: {
                    HStack(spacing: 7) {
                        Image(systemName: "mic.fill")
                        Text("Tap to speak").fontWeight(.semibold)
                        Text("· ⌘⇧V").foregroundStyle(Color(NSColor.windowBackgroundColor).opacity(0.6))
                    }
                }
                .buttonStyle(PrimaryButtonStyle())
            }

            // Recent
            if !state.recentCommands.isEmpty {
                VStack(alignment: .leading, spacing: 8) {
                    SectionLabel(text: "Recent")
                    ForEach(state.recentCommands.prefix(6), id: \.self) { cmd in
                        Button { Task { await engine.processCommand(cmd) } } label: {
                            HStack(spacing: 10) {
                                Image(systemName: "arrow.counterclockwise").font(.system(size: 11)).foregroundStyle(Theme.subtle)
                                Text(cmd).font(.system(size: 13)).foregroundStyle(Theme.text).lineLimit(1)
                                Spacer()
                                Image(systemName: "arrow.up.backward").font(.system(size: 10)).foregroundStyle(Theme.faint)
                            }
                            .padding(.horizontal, 14).padding(.vertical, 10)
                            .background(RoundedRectangle(cornerRadius: Theme.radiusSmall, style: .continuous).fill(Theme.card))
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                    }
                }
            }

            // Quick toggles
            VStack(alignment: .leading, spacing: 8) {
                SectionLabel(text: "Quick Settings")
                Card {
                    VStack(spacing: 14) {
                        SettingRow(icon: "sparkles.rectangle.stack", title: "Notch Halo", subtitle: "Wrap the animation around the notch") {
                            MonoToggle(isOn: $state.useNotchHalo)
                        }
                        Divider().overlay(Theme.stroke)
                        SettingRow(icon: "bubble.left.and.bubble.right", title: "Chat Ball", subtitle: "Floating chat button on screen") {
                            MonoToggle(isOn: Binding(
                                get: { chatBallVisible },
                                set: { v in chatBallVisible = v; v ? FloatingBallManager.shared.show() : FloatingBallManager.shared.hide() }
                            ))
                        }
                    }
                }
            }
        }
    }

    private func send() {
        let text = command.trimmed
        guard !text.isEmpty else { return }
        command = ""
        Task { await engine.processCommand(text) }
    }
}

extension String {
    var trimmed: String { trimmingCharacters(in: .whitespacesAndNewlines) }
}
