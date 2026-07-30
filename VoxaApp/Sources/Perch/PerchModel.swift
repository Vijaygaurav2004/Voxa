import SwiftUI
import AppKit
import ServiceManagement

// MARK: - Tabs

enum PerchTab: String, CaseIterable, Identifiable, Codable {
    case home, notes, snippets, timer, tray, settings

    var id: String { rawValue }

    var title: String {
        switch self {
        case .home:     return "Home"
        case .notes:    return "Notes"
        case .snippets: return "Snippets"
        case .timer:    return "Timer"
        case .tray:     return "Tray"
        case .settings: return "Settings"
        }
    }

    var icon: String {
        switch self {
        case .home:     return "house.fill"
        case .notes:    return "note.text"
        case .snippets: return "doc.on.doc.fill"
        case .timer:    return "clock.fill"
        case .tray:     return "tray.fill"
        case .settings: return "gearshape.fill"
        }
    }

    /// Tabs pinned to the right of the notch, mirroring the reference layout.
    var isTrailing: Bool {
        switch self {
        case .snippets, .tray, .settings: return true
        default: return false
        }
    }
}

// MARK: - Accent

enum PerchAccent: String, CaseIterable, Identifiable, Codable {
    case graphite, purple, orange, red, blue, green

    var id: String { rawValue }

    var color: Color {
        switch self {
        case .graphite: return Color(white: 0.82)
        case .purple:   return Color(red: 0.64, green: 0.35, blue: 0.98)
        case .orange:   return Color(red: 0.95, green: 0.45, blue: 0.15)
        case .red:      return Color(red: 0.88, green: 0.22, blue: 0.26)
        case .blue:     return Color(red: 0.20, green: 0.48, blue: 0.98)
        case .green:    return Color(red: 0.20, green: 0.74, blue: 0.35)
        }
    }

    /// Readable foreground when the accent is used as a fill.
    var onAccent: Color { self == .graphite ? .black : .white }
}

// MARK: - Perch design tokens

/// The perch is always dark — it hangs off the notch over the wallpaper, so it
/// reads as part of the hardware rather than as an app window (the same reason
/// the radial wheel stays dark). These tokens are intentionally separate from
/// the app's adaptive `Theme`.
enum Perch {
    static let bg          = Color.black
    /// Cards sit slightly *above* the shell, not level with it.
    static let card        = Color(white: 0.105)
    static let cardHover   = Color(white: 0.15)
    /// Wells nested inside a card (transport rows, event rows, chips).
    static let inner       = Color.white.opacity(0.055)
    static let innerHover  = Color.white.opacity(0.10)
    static let stroke      = Color.white.opacity(0.07)
    static let strokeStrong = Color.white.opacity(0.16)
    static let text        = Color.white
    static let subtle      = Color.white.opacity(0.52)
    static let faint       = Color.white.opacity(0.30)

    // Generous, consistent geometry — the single biggest thing that makes this
    // read as hardware rather than as a control panel.
    static let radius: CGFloat = 20
    static let cardRadius: CGFloat = 20
    static let innerRadius: CGFloat = 14
    static let chipRadius: CGFloat = 11
    /// Corner radius of the panel's bottom edge, matching the notch curve.
    static let shellRadius: CGFloat = 30

    /// Top-lit hairline. Real hardware catches light on its upper edge, and
    /// this one detail is most of the difference between "flat rectangle" and
    /// something that looks moulded.
    static var edge: LinearGradient {
        LinearGradient(colors: [.white.opacity(0.16), .white.opacity(0.035)],
                       startPoint: .top, endPoint: .bottom)
    }

    /// Faint vertical sheen laid over a card's fill.
    static var sheen: LinearGradient {
        LinearGradient(colors: [.white.opacity(0.045), .clear],
                       startPoint: .top, endPoint: .center)
    }
}

// MARK: - Surfaces

/// Standard raised surface: fill + sheen + top-lit hairline.
struct PerchSurface: ViewModifier {
    var radius: CGFloat = Perch.cardRadius
    var fill: Color = Perch.card
    var lit: Bool = true

    func body(content: Content) -> some View {
        content
            .background(
                RoundedRectangle(cornerRadius: radius, style: .continuous)
                    .fill(fill)
                    .overlay(
                        RoundedRectangle(cornerRadius: radius, style: .continuous)
                            .fill(lit ? AnyShapeStyle(Perch.sheen) : AnyShapeStyle(Color.clear))
                    )
            )
            .overlay(
                RoundedRectangle(cornerRadius: radius, style: .continuous)
                    .strokeBorder(lit ? AnyShapeStyle(Perch.edge) : AnyShapeStyle(Perch.stroke),
                                  lineWidth: 1)
            )
    }
}

extension View {
    func perchSurface(radius: CGFloat = Perch.cardRadius,
                      fill: Color = Perch.card,
                      lit: Bool = true) -> some View {
        modifier(PerchSurface(radius: radius, fill: fill, lit: lit))
    }

    /// Nested well inside a card — flatter, no sheen.
    func perchWell(radius: CGFloat = Perch.innerRadius, fill: Color = Perch.inner) -> some View {
        background(RoundedRectangle(cornerRadius: radius, style: .continuous).fill(fill))
    }
}

// MARK: - Settings

@MainActor
final class PerchSettings: ObservableObject {
    static let shared = PerchSettings()

    private enum Keys {
        static let enabled     = "voxa.perch.enabled"
        static let width       = "voxa.perch.width"
        static let height      = "voxa.perch.height"
        static let accent      = "voxa.perch.accent"
        static let allDisplays = "voxa.perch.allDisplays"
        static let tabOrder    = "voxa.perch.tabOrder"
        static let hiddenTabs  = "voxa.perch.hiddenTabs"
        static let openOnHover = "voxa.perch.openOnHover"
        static let launchAtLogin = "voxa.perch.launchAtLogin"
    }

    static let minWidth: Double = 520
    static let maxWidth: Double = 1100
    static let minHeight: Double = 180
    static let maxHeight: Double = 420

    @Published var enabled: Bool {
        didSet {
            UserDefaults.standard.set(enabled, forKey: Keys.enabled)
            PerchManager.shared.applySettings()
        }
    }
    @Published var width: Double {
        didSet {
            UserDefaults.standard.set(width, forKey: Keys.width)
            PerchManager.shared.resize()
        }
    }
    @Published var height: Double {
        didSet {
            UserDefaults.standard.set(height, forKey: Keys.height)
            PerchManager.shared.resize()
        }
    }
    @Published var accent: PerchAccent {
        didSet { UserDefaults.standard.set(accent.rawValue, forKey: Keys.accent) }
    }
    @Published var allDisplays: Bool {
        didSet {
            UserDefaults.standard.set(allDisplays, forKey: Keys.allDisplays)
            PerchManager.shared.applySettings()
        }
    }
    /// Reveal the perch by pointing at the notch, rather than only via hotkey.
    @Published var openOnHover: Bool {
        didSet {
            UserDefaults.standard.set(openOnHover, forKey: Keys.openOnHover)
            PerchManager.shared.applySettings()
        }
    }
    @Published var tabOrder: [PerchTab] {
        didSet {
            UserDefaults.standard.set(tabOrder.map(\.rawValue), forKey: Keys.tabOrder)
        }
    }
    @Published var hiddenTabs: Set<PerchTab> {
        didSet {
            UserDefaults.standard.set(hiddenTabs.map(\.rawValue), forKey: Keys.hiddenTabs)
        }
    }
    /// Mirrors the real login-item registration, which can fail independently.
    @Published var launchAtLogin: Bool {
        didSet {
            guard launchAtLogin != oldValue else { return }
            applyLaunchAtLogin()
        }
    }

    /// Tabs actually shown, in the user's order.
    var visibleTabs: [PerchTab] { tabOrder.filter { !hiddenTabs.contains($0) } }

    private init() {
        let d = UserDefaults.standard
        d.register(defaults: [
            Keys.enabled: true,
            Keys.width: 750.0,
            Keys.height: 240.0,
            Keys.allDisplays: false,
            Keys.openOnHover: true,
        ])
        enabled     = d.bool(forKey: Keys.enabled)
        width       = max(Self.minWidth, min(Self.maxWidth, d.double(forKey: Keys.width)))
        height      = max(Self.minHeight, min(Self.maxHeight, d.double(forKey: Keys.height)))
        allDisplays = d.bool(forKey: Keys.allDisplays)
        openOnHover = d.bool(forKey: Keys.openOnHover)
        accent      = PerchAccent(rawValue: d.string(forKey: Keys.accent) ?? "") ?? .graphite

        let storedOrder = (d.array(forKey: Keys.tabOrder) as? [String] ?? []).compactMap(PerchTab.init)
        // Append any tab a future build adds so it can never go missing.
        tabOrder = storedOrder + PerchTab.allCases.filter { !storedOrder.contains($0) }
        hiddenTabs = Set((d.array(forKey: Keys.hiddenTabs) as? [String] ?? []).compactMap(PerchTab.init))

        launchAtLogin = SMAppService.mainApp.status == .enabled
    }

    /// Register/unregister the real login item, reverting the toggle if macOS
    /// refuses (unsigned dev builds commonly do).
    private func applyLaunchAtLogin() {
        do {
            if launchAtLogin {
                if SMAppService.mainApp.status != .enabled { try SMAppService.mainApp.register() }
            } else {
                if SMAppService.mainApp.status == .enabled { try SMAppService.mainApp.unregister() }
            }
        } catch {
            appLog("[Perch] Launch-at-login change failed: \(error.localizedDescription)")
            let actual = SMAppService.mainApp.status == .enabled
            if actual != launchAtLogin {
                DispatchQueue.main.async { self.launchAtLogin = actual }
            }
        }
    }

    func moveTab(_ tab: PerchTab, by delta: Int) {
        guard let index = tabOrder.firstIndex(of: tab) else { return }
        let target = index + delta
        guard target >= 0, target < tabOrder.count else { return }
        tabOrder.swapAt(index, target)
    }

    func setTab(_ tab: PerchTab, hidden: Bool) {
        // Settings must always be reachable, else the user can't undo this.
        guard tab != .settings else { return }
        if hidden { hiddenTabs.insert(tab) } else { hiddenTabs.remove(tab) }
    }

    func resetSize() {
        width = 750
        height = 240
    }
}

// MARK: - Shared chrome

/// Rounded card used throughout the perch.
struct PerchCard<Content: View>: View {
    var padding: CGFloat = 14
    var radius: CGFloat = Perch.cardRadius
    @ViewBuilder var content: Content

    var body: some View {
        content
            .padding(padding)
            .perchSurface(radius: radius)
    }
}

/// Round icon button used in the floating bars.
struct PerchIconButton: View {
    let symbol: String
    var size: CGFloat = 34
    var active: Bool = false
    var action: () -> Void

    @ObservedObject private var settings = PerchSettings.shared
    @State private var hovering = false

    var body: some View {
        Button(action: action) {
            Image(systemName: symbol)
                .font(.system(size: size * 0.40, weight: .semibold))
                .foregroundStyle(active ? settings.accent.onAccent : Perch.text)
                .frame(width: size, height: size)
                .background(
                    Circle().fill(active ? AnyShapeStyle(settings.accent.color)
                                         : AnyShapeStyle(hovering ? Perch.innerHover : Perch.inner))
                )
                .overlay(Circle().strokeBorder(Perch.edge, lineWidth: 1))
                .contentShape(Circle())
        }
        .buttonStyle(.plain)
        .onHover { hovering = $0 }
        .animation(.easeOut(duration: 0.12), value: hovering)
    }
}

/// The floating action bar the Notes and Snippets tabs sit on top of.
struct PerchFloatingBar<Content: View>: View {
    @ObservedObject private var settings = PerchSettings.shared
    @ViewBuilder var content: Content

    var body: some View {
        HStack(spacing: 8) { content }
            .padding(6)
            .background(
                Capsule().fill(Color(white: 0.13))
                    .overlay(Capsule().fill(Perch.sheen))
            )
            .overlay(Capsule().strokeBorder(settings.accent.color.opacity(0.30), lineWidth: 1))
            .shadow(color: .black.opacity(0.55), radius: 18, y: 6)
    }
}

/// A transient "Copied" style toast used by Snippets and Tray.
struct PerchToast: View {
    let text: String
    var symbol: String = "checkmark.circle.fill"

    var body: some View {
        HStack(spacing: 6) {
            Image(systemName: symbol).font(.system(size: 11, weight: .semibold))
            Text(text).font(.system(size: 12, weight: .medium))
        }
        .foregroundStyle(.black)
        .padding(.horizontal, 12).padding(.vertical, 7)
        .background(Capsule().fill(Color.white))
        .shadow(color: .black.opacity(0.35), radius: 10, y: 3)
        .transition(.scale(scale: 0.9).combined(with: .opacity))
    }
}
