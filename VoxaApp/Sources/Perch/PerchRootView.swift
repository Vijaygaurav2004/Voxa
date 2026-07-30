import SwiftUI
import AppKit

/// The perch shell: a black slab hanging off the notch, with the tab bar
/// wrapping around the notch cut-out and the active tab's content beneath.
struct PerchRootView: View {
    @ObservedObject var manager: PerchManager
    @ObservedObject private var settings = PerchSettings.shared

    var body: some View {
        ZStack(alignment: .top) {
            if manager.isOpen {
                shell
                    .transition(.asymmetric(
                        insertion: .move(edge: .top).combined(with: .opacity),
                        removal: .move(edge: .top).combined(with: .opacity)
                    ))
            } else {
                // Collapsed: an invisible sliver that simply keeps the panel alive.
                Color.clear
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .animation(.spring(response: 0.34, dampingFraction: 0.82), value: manager.isOpen)
        .animation(.easeInOut(duration: 0.18), value: manager.tab)
    }

    private var shell: some View {
        VStack(spacing: 0) {
            tabBar
            Rectangle().fill(Perch.stroke).frame(height: 1)
            content
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        }
        .background(Perch.bg)
        .clipShape(PerchShell(radius: Perch.shellRadius))
        .overlay(
            PerchShell(radius: Perch.shellRadius)
                .strokeBorder(
                    LinearGradient(colors: [.white.opacity(0.10), .white.opacity(0.02)],
                                   startPoint: .top, endPoint: .bottom),
                    lineWidth: 1)
        )
        .shadow(color: .black.opacity(0.62), radius: 30, y: 14)
    }

    // MARK: Tab bar

    private var tabBar: some View {
        HStack(spacing: 6) {
            ForEach(settings.visibleTabs.filter { !$0.isTrailing }) { tab in
                tabChip(tab)
            }
            Spacer(minLength: 8)
            // Gap for the physical notch so the chrome never sits underneath it.
            Color.clear.frame(width: manager.notchWidth + 12, height: 1)
            Spacer(minLength: 8)
            ForEach(settings.visibleTabs.filter(\.isTrailing)) { tab in
                tabChip(tab)
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 9)
    }

    private func tabChip(_ tab: PerchTab) -> some View {
        let active = manager.tab == tab
        return Button {
            manager.tab = tab
        } label: {
            HStack(spacing: 6) {
                Image(systemName: tab.icon).font(.system(size: 12, weight: .semibold))
                if active {
                    Text(tab.title).font(.system(size: 12, weight: .semibold))
                }
            }
            .foregroundStyle(active ? settings.accent.onAccent : Perch.text.opacity(0.9))
            .padding(.horizontal, active ? 13 : 10)
            .frame(height: 32)
            .background(
                RoundedRectangle(cornerRadius: Perch.chipRadius, style: .continuous)
                    .fill(active ? AnyShapeStyle(settings.accent.color) : AnyShapeStyle(Perch.inner))
            )
            .overlay(
                RoundedRectangle(cornerRadius: Perch.chipRadius, style: .continuous)
                    .strokeBorder(active ? AnyShapeStyle(Color.clear) : AnyShapeStyle(Perch.edge), lineWidth: 1)
            )
            .shadow(color: active ? settings.accent.color.opacity(0.35) : .clear, radius: 8, y: 2)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .help(tab.title)
    }

    // MARK: Content

    @ViewBuilder
    private var content: some View {
        switch manager.tab {
        case .home:     PerchHomeTab()
        case .notes:    PerchNotesTab()
        case .snippets: PerchSnippetsTab()
        case .timer:    PerchTimerTab()
        case .tray:     PerchTrayTab()
        case .settings: PerchSettingsTab()
        }
    }
}

// MARK: - Shell shape

/// Square at the top (it meets the screen edge) and rounded at the bottom, so
/// the slab reads as an extension of the notch rather than a floating window.
struct PerchShell: InsettableShape {
    var radius: CGFloat
    var inset: CGFloat = 0

    func path(in rect: CGRect) -> Path {
        let r = rect.insetBy(dx: inset, dy: inset)
        let radius = min(self.radius, min(r.width, r.height) / 2)
        var path = Path()
        path.move(to: CGPoint(x: r.minX, y: r.minY))
        path.addLine(to: CGPoint(x: r.maxX, y: r.minY))
        path.addLine(to: CGPoint(x: r.maxX, y: r.maxY - radius))
        path.addQuadCurve(to: CGPoint(x: r.maxX - radius, y: r.maxY),
                          control: CGPoint(x: r.maxX, y: r.maxY))
        path.addLine(to: CGPoint(x: r.minX + radius, y: r.maxY))
        path.addQuadCurve(to: CGPoint(x: r.minX, y: r.maxY - radius),
                          control: CGPoint(x: r.minX, y: r.maxY))
        path.closeSubpath()
        return path
    }

    func inset(by amount: CGFloat) -> some InsettableShape {
        var copy = self
        copy.inset += amount
        return copy
    }
}
