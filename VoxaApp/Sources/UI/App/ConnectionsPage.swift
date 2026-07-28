import SwiftUI
import AppKit

/// Accounts page — sign in with Google and connect apps Voxa can act on
/// (Google Calendar, Gmail, GitHub). Monochrome, built on AppTheme components.
struct ConnectionsPage: View {
    @State private var providers: [PythonBridge.IntegrationProvider] = []
    @State private var pendingProvider: String? = nil
    @State private var errorText: String? = nil
    @State private var expandedSetup: String? = nil

    private var google: PythonBridge.IntegrationProvider? {
        providers.first { $0.id == "google" }
    }
    private var services: [PythonBridge.IntegrationProvider] {
        providers.filter { $0.id != "google" }
    }
    /// Google-family connects (google / google_calendar / gmail) all flow
    /// through the sign-in card's pending state; GitHub shows in its row.
    private var googlePending: Bool {
        guard let p = pendingProvider else { return false }
        return p != "github"
    }

    var body: some View {
        Page(title: "Accounts", subtitle: "Sign in and connect apps Voxa can act on.") {
            googleCard

            if let errorText {
                Text(errorText)
                    .font(.system(size: 11))
                    .foregroundStyle(.red)
            }

            VStack(alignment: .leading, spacing: 8) {
                SectionLabel(text: "Connected apps")
                Card {
                    VStack(spacing: 14) {
                        ForEach(Array(services.enumerated()), id: \.element.id) { index, provider in
                            if index > 0 { Divider().overlay(Theme.stroke) }
                            serviceRow(provider)
                        }
                        if services.isEmpty {
                            Text("Waiting for the backend…")
                                .font(.system(size: 12))
                                .foregroundStyle(Theme.subtle)
                        }
                    }
                }
            }
        }
        .onAppear { load() }
        .onReceive(NotificationCenter.default.publisher(for: .voxaIntegrationsChanged)) { _ in
            pendingProvider = nil
            load()
        }
    }

    // MARK: - Google account card

    @ViewBuilder private var googleCard: some View {
        Card {
            if googlePending {
                HStack(spacing: 12) {
                    ProgressView().controlSize(.small)
                    Text("Waiting for browser…")
                        .font(.system(size: 13))
                        .foregroundStyle(Theme.subtle)
                    Spacer()
                    Button("Cancel") { pendingProvider = nil; load() }
                        .buttonStyle(GhostButtonStyle())
                        .frame(width: 90)
                }
            } else if let g = google, g.connected {
                let (name, email) = nameAndEmail(g.account_label)
                HStack(spacing: 12) {
                    avatar(urlString: g.avatar_url, label: name)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(name).font(.system(size: 13, weight: .bold))
                        if !email.isEmpty {
                            Text(email).font(.system(size: 11)).foregroundStyle(.secondary)
                        }
                    }
                    Spacer()
                    Button("Sign out") { disconnect("google") }
                        .buttonStyle(GhostButtonStyle(tint: .red))
                        .frame(width: 96)
                }
            } else {
                VStack(spacing: 10) {
                    Image(systemName: "person.crop.circle.badge.plus")
                        .font(.system(size: 28, weight: .light))
                        .foregroundStyle(Theme.faint)
                    Button("Sign in with Google") { connect("google") }
                        .buttonStyle(PrimaryButtonStyle())
                        .frame(width: 220)
                    Text("One account for Calendar and Gmail — Voxa only stores tokens on this Mac.")
                        .font(.system(size: 11))
                        .foregroundStyle(Theme.subtle)
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, 6)
            }
        }
    }

    private func avatar(urlString: String?, label: String) -> some View {
        ZStack {
            Circle().fill(Theme.card)
            Circle().strokeBorder(Theme.stroke, lineWidth: 1)
            if let urlString, let url = URL(string: urlString) {
                AsyncImage(url: url) { phase in
                    if let image = phase.image {
                        image.resizable().scaledToFill()
                    } else {
                        initialsView(label)
                    }
                }
                .clipShape(Circle())
            } else {
                initialsView(label)
            }
        }
        .frame(width: 44, height: 44)
    }

    private func initialsView(_ label: String) -> some View {
        Text(initials(label))
            .font(.system(size: 15, weight: .semibold))
            .foregroundStyle(Theme.subtle)
    }

    // MARK: - Service rows

    @ViewBuilder private func serviceRow(_ p: PythonBridge.IntegrationProvider) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            SettingRow(icon: icon(for: p.id), title: p.name, subtitle: subtitle(for: p)) {
                trailingControl(p)
            }
            if !p.configured && expandedSetup == p.id {
                setupInstructions(p)
            }
        }
    }

    @ViewBuilder private func trailingControl(_ p: PythonBridge.IntegrationProvider) -> some View {
        if !p.configured {
            Button(expandedSetup == p.id ? "Hide" : "Setup…") {
                withAnimation(.easeInOut(duration: 0.15)) {
                    expandedSetup = (expandedSetup == p.id) ? nil : p.id
                }
            }
            .buttonStyle(GhostButtonStyle())
            .frame(width: 84)
        } else if p.connected {
            Button("Disconnect") { disconnect(p.id) }
                .buttonStyle(GhostButtonStyle())
                .frame(width: 100)
        } else if pendingProvider == p.id {
            ProgressView().controlSize(.small).frame(width: 84)
        } else {
            Button("Connect") { connect(p.id) }
                .buttonStyle(PrimaryButtonStyle())
                .frame(width: 92)
        }
    }

    /// Copyable inline setup help for providers missing OAuth credentials.
    private func setupInstructions(_ p: PythonBridge.IntegrationProvider) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            if let detail = p.detail {
                Text(detail).font(.system(size: 11)).foregroundStyle(Theme.subtle)
            }
            Text(setupKeys(for: p.id))
                .font(.system(size: 11, design: .monospaced))
                .foregroundStyle(Theme.text)
                .textSelection(.enabled)
            Text("Add these to ~/.voxa/.env (see the README for step-by-step setup), then restart Voxa.")
                .font(.system(size: 11))
                .foregroundStyle(Theme.faint)
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: Theme.radiusSmall, style: .continuous)
                .fill(Theme.card)
        )
    }

    // MARK: - Data

    private func load() {
        Task { @MainActor in
            do {
                providers = try await PythonBridge.shared.getIntegrations()
                errorText = nil
            } catch {
                errorText = "Couldn't load accounts — is the backend running?"
            }
        }
    }

    private func connect(_ id: String) {
        errorText = nil
        Task { @MainActor in
            do {
                let res = try await PythonBridge.shared.connectIntegration(id)
                if res.success, let auth = res.auth_url, let url = URL(string: auth) {
                    pendingProvider = id
                    NSWorkspace.shared.open(url)
                } else {
                    errorText = res.message ?? "Couldn't start the connection."
                }
            } catch {
                errorText = error.localizedDescription
            }
        }
    }

    private func disconnect(_ id: String) {
        errorText = nil
        Task { @MainActor in
            do {
                try await PythonBridge.shared.disconnectIntegration(id)
                load()
            } catch {
                errorText = error.localizedDescription
            }
        }
    }

    // MARK: - Helpers

    private func icon(for id: String) -> String {
        switch id {
        case "google_calendar": return "calendar"
        case "gmail": return "envelope"
        case "github": return "chevron.left.forwardslash.chevron.right"
        default: return "link"
        }
    }

    private func subtitle(for p: PythonBridge.IntegrationProvider) -> String {
        if p.connected { return p.account_label ?? "Connected" }
        return p.detail ?? "Not connected"
    }

    private func setupKeys(for id: String) -> String {
        if id == "github" {
            return "GITHUB_CLIENT_ID=…\nGITHUB_CLIENT_SECRET=…"
        }
        return "GOOGLE_CLIENT_ID=…\nGOOGLE_CLIENT_SECRET=…"
    }

    /// Split an "Anantha (an@gmail.com)" label into name + email parts.
    private func nameAndEmail(_ label: String?) -> (String, String) {
        guard let label, !label.isEmpty else { return ("Google Account", "") }
        if let open = label.firstIndex(of: "("), label.hasSuffix(")") {
            let name = String(label[..<open]).trimmingCharacters(in: .whitespaces)
            let email = String(label[label.index(after: open)...].dropLast())
            return (name.isEmpty ? email : name, email)
        }
        return (label, "")
    }

    private func initials(_ label: String) -> String {
        let parts = label.split(separator: " ").prefix(2)
        let letters = parts.compactMap { $0.first.map(String.init) }
        return letters.isEmpty ? "?" : letters.joined().uppercased()
    }
}
