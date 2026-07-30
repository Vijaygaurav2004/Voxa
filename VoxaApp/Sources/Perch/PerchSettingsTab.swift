import SwiftUI
import AppKit

/// Settings: general behaviour, accent, size, and tab management.
struct PerchSettingsTab: View {
    @ObservedObject private var settings = PerchSettings.shared

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 10) {
                generalCard
                tabsCard
            }
            .padding(12)
        }
        .scrollIndicators(.hidden)
    }

    // MARK: General

    private var generalCard: some View {
        PerchCard(padding: 12) {
            VStack(alignment: .leading, spacing: 10) {
                Text("General").font(.system(size: 13, weight: .bold)).foregroundStyle(Perch.text)

                row("Launch at Login") {
                    Toggle("", isOn: $settings.launchAtLogin)
                        .labelsHidden().toggleStyle(.switch).controlSize(.small)
                        .tint(settings.accent.color)
                }
                row("Reveal on hover") {
                    Toggle("", isOn: $settings.openOnHover)
                        .labelsHidden().toggleStyle(.switch).controlSize(.small)
                        .tint(settings.accent.color)
                }
                row("Display Perch on") {
                    Picker("", selection: $settings.allDisplays) {
                        Text("Notched display").tag(false)
                        Text("Main display").tag(true)
                    }
                    .labelsHidden().frame(width: 150).controlSize(.small)
                }
                row("Accent colour") {
                    HStack(spacing: 7) {
                        ForEach(PerchAccent.allCases) { accent in
                            Button { settings.accent = accent } label: {
                                Circle()
                                    .fill(accent.color)
                                    .frame(width: 19, height: 19)
                                    .overlay(
                                        Circle().strokeBorder(
                                            settings.accent == accent ? Color.white : Color.white.opacity(0.16),
                                            lineWidth: settings.accent == accent ? 2.5 : 1)
                                    )
                                    .shadow(color: settings.accent == accent ? accent.color.opacity(0.55) : .clear,
                                            radius: 6)
                            }
                            .buttonStyle(.plain)
                        }
                    }
                }

                Rectangle().fill(Perch.stroke).frame(height: 1)

                slider("Width", value: $settings.width,
                       range: PerchSettings.minWidth...PerchSettings.maxWidth, unit: "px")
                slider("Height", value: $settings.height,
                       range: PerchSettings.minHeight...PerchSettings.maxHeight, unit: "px")
            }
        }
    }

    private func row<V: View>(_ title: String, @ViewBuilder trailing: () -> V) -> some View {
        HStack {
            Text(title).font(.system(size: 12)).foregroundStyle(Perch.subtle)
            Spacer(minLength: 10)
            trailing()
        }
    }

    private func slider(_ title: String, value: Binding<Double>,
                        range: ClosedRange<Double>, unit: String) -> some View {
        HStack(spacing: 9) {
            Text(title).font(.system(size: 12)).foregroundStyle(Perch.subtle).frame(width: 48, alignment: .leading)
            Button {
                title == "Width" ? (settings.width = 750) : (settings.height = 240)
            } label: {
                Image(systemName: "arrow.counterclockwise")
                    .font(.system(size: 9)).foregroundStyle(Perch.faint)
            }
            .buttonStyle(.plain)
            .help("Reset")
            Slider(value: value, in: range)
                .controlSize(.small)
                .tint(settings.accent.color)
            Text("\(Int(value.wrappedValue))\(unit)")
                .font(.system(size: 11, design: .rounded)).monospacedDigit()
                .foregroundStyle(Perch.subtle).frame(width: 46, alignment: .trailing)
        }
    }

    // MARK: Tabs

    private var tabsCard: some View {
        PerchCard(padding: 12) {
            VStack(alignment: .leading, spacing: 9) {
                Text("Tab Management").font(.system(size: 13, weight: .bold)).foregroundStyle(Perch.text)
                Text("Reorder with the arrows, or hide a tab you don't use.")
                    .font(.system(size: 10)).foregroundStyle(Perch.faint)

                VStack(spacing: 6) {
                    ForEach(Array(settings.tabOrder.enumerated()), id: \.element) { index, tab in
                        tabRow(tab, index: index)
                    }
                }
            }
        }
    }

    private func tabRow(_ tab: PerchTab, index: Int) -> some View {
        let hidden = settings.hiddenTabs.contains(tab)
        return HStack(spacing: 8) {
            Text("\(index + 1)")
                .font(.system(size: 9, weight: .semibold)).foregroundStyle(Perch.faint).frame(width: 12)
            Image(systemName: tab.icon)
                .font(.system(size: 11, weight: .medium))
                .foregroundStyle(hidden ? Perch.faint : Perch.text)
                .frame(width: 20)
            Text(tab.title)
                .font(.system(size: 12, weight: .medium))
                .foregroundStyle(hidden ? Perch.faint : Perch.text)
            Spacer(minLength: 6)

            Button { settings.moveTab(tab, by: -1) } label: {
                Image(systemName: "chevron.up").font(.system(size: 9, weight: .bold)).foregroundStyle(Perch.subtle)
                    .frame(width: 20, height: 20).contentShape(Rectangle())
            }
            .buttonStyle(.plain).disabled(index == 0).opacity(index == 0 ? 0.3 : 1)

            Button { settings.moveTab(tab, by: 1) } label: {
                Image(systemName: "chevron.down").font(.system(size: 9, weight: .bold)).foregroundStyle(Perch.subtle)
                    .frame(width: 20, height: 20).contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .disabled(index == settings.tabOrder.count - 1)
            .opacity(index == settings.tabOrder.count - 1 ? 0.3 : 1)

            Button { settings.setTab(tab, hidden: !hidden) } label: {
                Image(systemName: hidden ? "eye.slash" : "eye")
                    .font(.system(size: 10)).foregroundStyle(Perch.subtle)
                    .frame(width: 20, height: 20).contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .disabled(tab == .settings)
            .opacity(tab == .settings ? 0.3 : 1)
            .help(tab == .settings ? "Settings can't be hidden" : (hidden ? "Show" : "Hide"))
        }
        .padding(.horizontal, 10).padding(.vertical, 7)
        .background(RoundedRectangle(cornerRadius: 12, style: .continuous).fill(Perch.inner))
        .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).strokeBorder(Perch.stroke, lineWidth: 1))
    }
}
