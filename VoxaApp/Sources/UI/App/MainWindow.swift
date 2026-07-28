import SwiftUI

// MARK: - Sidebar sections

enum AppSection: String, CaseIterable, Identifiable {
    case home, modes, meetings, memory, accounts, settings
    var id: String { rawValue }
    var title: String {
        switch self {
        case .home: return "Home"
        case .modes: return "Modes"
        case .meetings: return "Meetings"
        case .memory: return "Memory"
        case .accounts: return "Accounts"
        case .settings: return "Settings"
        }
    }
    var icon: String {
        switch self {
        case .home: return "house"
        case .modes: return "slider.horizontal.3"
        case .meetings: return "person.2.wave.2"
        case .memory: return "brain"
        case .accounts: return "person.crop.circle"
        case .settings: return "gearshape"
        }
    }
}

// MARK: - Main Window

struct MainWindow: View {
    @EnvironmentObject var engine: VoxaEngine
    @EnvironmentObject var state: VoxaState
    @State private var section: AppSection = .home

    var body: some View {
        HStack(spacing: 0) {
            sidebar
            Divider().overlay(Theme.stroke)
            detail
        }
        .frame(minWidth: 860, minHeight: 580)
        .background(Color(NSColor.windowBackgroundColor))
    }

    @ViewBuilder private var detail: some View {
        switch section {
        case .home:     HomePage()
        case .modes:    ModesPage()
        case .meetings: MeetingsPage()
        case .memory:   MemoryPage()
        case .accounts: ConnectionsPage()
        case .settings: SettingsPage()
        }
    }

    // MARK: Sidebar

    private var sidebar: some View {
        VStack(alignment: .leading, spacing: 3) {
            HStack(spacing: 10) {
                ZStack {
                    RoundedRectangle(cornerRadius: 9, style: .continuous).fill(Color.primary).frame(width: 30, height: 30)
                    Image(systemName: "waveform").font(.system(size: 14, weight: .bold))
                        .foregroundStyle(Color(NSColor.windowBackgroundColor))
                }
                Text("Voxa").font(.system(size: 17, weight: .bold))
            }
            .padding(.horizontal, 14).padding(.top, 36).padding(.bottom, 20)

            ForEach(AppSection.allCases) { s in
                sidebarItem(s)
            }

            Spacer()

            HStack(spacing: 7) {
                Circle().fill(state.isBackendReady ? Color.primary : Theme.faint).frame(width: 7, height: 7)
                Text(state.isBackendReady ? "Connected" : "Starting…")
                    .font(.system(size: 11)).foregroundStyle(Theme.subtle)
            }
            .padding(16)
        }
        .frame(width: 216)
        .background(Color(NSColor.windowBackgroundColor))
    }

    private func sidebarItem(_ s: AppSection) -> some View {
        Button {
            section = s
        } label: {
            HStack(spacing: 11) {
                Image(systemName: s.icon).font(.system(size: 14, weight: .medium)).frame(width: 20)
                Text(s.title).font(.system(size: 13, weight: section == s ? .semibold : .regular))
                Spacer()
            }
            .foregroundStyle(section == s ? Theme.text : Theme.subtle)
            .padding(.horizontal, 12).padding(.vertical, 8)
            .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(section == s ? Theme.card : .clear))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .padding(.horizontal, 10)
    }
}
