import SwiftUI
import AppKit

/// App-wide light / dark / follow-system appearance.
///
/// Setting `NSApp.appearance` covers every surface at once — the main window,
/// the menu-bar popover, the floating chat ball and the onboarding sheet — so
/// the whole app flips together rather than each view having to opt in. The
/// monochrome `Theme` is built on `Color.primary` and `NSColor.windowBackgroundColor`,
/// both of which resolve against whatever appearance is active, so nothing else
/// needs to change.
///
/// The radial wheel is deliberately exempt: it is a translucent overlay drawn on
/// top of the desktop (like Spotlight's), so it keeps its dark plate in both
/// modes and stays legible over any wallpaper.
@MainActor
final class AppearanceManager: ObservableObject {
    static let shared = AppearanceManager()

    enum Mode: String, CaseIterable, Identifiable, Codable {
        case system, light, dark

        var id: String { rawValue }
        var title: String {
            switch self {
            case .system: return "System"
            case .light:  return "Light"
            case .dark:   return "Dark"
            }
        }
        var symbol: String {
            switch self {
            case .system: return "circle.lefthalf.filled"
            case .light:  return "sun.max"
            case .dark:   return "moon"
            }
        }
        /// nil means "inherit whatever macOS is set to".
        var nsAppearance: NSAppearance? {
            switch self {
            case .system: return nil
            case .light:  return NSAppearance(named: .aqua)
            case .dark:   return NSAppearance(named: .darkAqua)
            }
        }
    }

    private static let key = "voxa.appearance"

    @Published var mode: Mode {
        didSet {
            UserDefaults.standard.set(mode.rawValue, forKey: Self.key)
            apply()
        }
    }

    private init() {
        let raw = UserDefaults.standard.string(forKey: Self.key) ?? Mode.system.rawValue
        mode = Mode(rawValue: raw) ?? .system
    }

    /// Push the stored preference onto NSApp. Called once at launch and on every
    /// change; safe to call repeatedly.
    func apply() {
        NSApp.appearance = mode.nsAppearance
    }
}

// MARK: - Picker

/// Segmented light/dark/system control used in Settings.
struct AppearancePicker: View {
    @ObservedObject var appearance = AppearanceManager.shared

    var body: some View {
        HStack(spacing: 4) {
            ForEach(AppearanceManager.Mode.allCases) { mode in
                let selected = appearance.mode == mode
                Button {
                    appearance.mode = mode
                } label: {
                    HStack(spacing: 5) {
                        Image(systemName: mode.symbol).font(.system(size: 11, weight: .medium))
                        Text(mode.title).font(.system(size: 11, weight: selected ? .semibold : .regular))
                    }
                    .foregroundStyle(selected ? AnyShapeStyle(Color(NSColor.windowBackgroundColor))
                                              : AnyShapeStyle(Theme.subtle))
                    .padding(.horizontal, 10).padding(.vertical, 6)
                    .background(
                        RoundedRectangle(cornerRadius: 7, style: .continuous)
                            .fill(selected ? AnyShapeStyle(Color.primary) : AnyShapeStyle(Color.clear))
                    )
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
            }
        }
        .padding(3)
        .background(RoundedRectangle(cornerRadius: 9, style: .continuous).fill(Theme.card))
        .overlay(RoundedRectangle(cornerRadius: 9, style: .continuous).strokeBorder(Theme.stroke, lineWidth: 1))
    }
}
