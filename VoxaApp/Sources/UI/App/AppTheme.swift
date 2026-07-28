import SwiftUI

// MARK: - Minimalist Black & White Theme

/// A restrained monochrome design system: black/white/greys only, thin borders,
/// generous whitespace, one inverted "primary" accent. Adapts to light/dark.
enum Theme {
    // Surfaces (adaptive so it reads clean in both appearances)
    static let card       = Color.primary.opacity(0.04)
    static let cardHover   = Color.primary.opacity(0.07)
    static let stroke      = Color.primary.opacity(0.10)
    static let strokeStrong = Color.primary.opacity(0.18)

    // Text
    static let text       = Color.primary
    static let subtle     = Color.secondary
    static let faint      = Color.primary.opacity(0.35)

    // Radii / spacing
    static let radius: CGFloat = 12
    static let radiusSmall: CGFloat = 8
    static let pad: CGFloat = 20
}

// MARK: - Card container

struct Card<Content: View>: View {
    var padding: CGFloat = 16
    @ViewBuilder var content: Content
    var body: some View {
        content
            .padding(padding)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(RoundedRectangle(cornerRadius: Theme.radius, style: .continuous).fill(Theme.card))
            .overlay(RoundedRectangle(cornerRadius: Theme.radius, style: .continuous).strokeBorder(Theme.stroke, lineWidth: 1))
    }
}

// MARK: - Section label

struct SectionLabel: View {
    let text: String
    var body: some View {
        Text(text.uppercased())
            .font(.system(size: 11, weight: .semibold))
            .tracking(0.8)
            .foregroundStyle(Theme.faint)
    }
}

// MARK: - Buttons

/// Inverted monochrome primary button (white on dark / black on light).
struct PrimaryButtonStyle: ButtonStyle {
    var disabled: Bool = false
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 13, weight: .semibold))
            .foregroundStyle(disabled ? AnyShapeStyle(Theme.faint) : AnyShapeStyle(Color(NSColor.windowBackgroundColor)))
            .padding(.horizontal, 16).padding(.vertical, 9)
            .frame(maxWidth: .infinity)
            .background(
                RoundedRectangle(cornerRadius: Theme.radiusSmall, style: .continuous)
                    .fill(disabled ? Theme.card : Color.primary)
            )
            .opacity(configuration.isPressed ? 0.85 : 1)
    }
}

/// Outlined/ghost button.
struct GhostButtonStyle: ButtonStyle {
    var tint: Color = .primary
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 13, weight: .medium))
            .foregroundStyle(tint)
            .padding(.horizontal, 14).padding(.vertical, 8)
            .frame(maxWidth: .infinity)
            .background(RoundedRectangle(cornerRadius: Theme.radiusSmall, style: .continuous).fill(Theme.card))
            .overlay(RoundedRectangle(cornerRadius: Theme.radiusSmall, style: .continuous).strokeBorder(Theme.stroke, lineWidth: 1))
            .opacity(configuration.isPressed ? 0.7 : 1)
    }
}

// MARK: - Toggle / setting row

struct SettingRow<Trailing: View>: View {
    let icon: String
    let title: String
    var subtitle: String? = nil
    @ViewBuilder var trailing: Trailing

    var body: some View {
        HStack(spacing: 12) {
            ZStack {
                RoundedRectangle(cornerRadius: Theme.radiusSmall, style: .continuous)
                    .fill(Theme.card)
                    .frame(width: 32, height: 32)
                Image(systemName: icon).font(.system(size: 14, weight: .medium)).foregroundStyle(Theme.text)
            }
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(.system(size: 13, weight: .medium)).foregroundStyle(Theme.text)
                if let subtitle { Text(subtitle).font(.system(size: 11)).foregroundStyle(Theme.subtle).lineLimit(1) }
            }
            Spacer(minLength: 8)
            trailing
        }
    }
}

// MARK: - Monochrome toggle

struct MonoToggle: View {
    @Binding var isOn: Bool
    var body: some View {
        Toggle("", isOn: $isOn)
            .labelsHidden()
            .toggleStyle(.switch)
            .tint(Color.primary)      // monochrome accent
            .controlSize(.small)
    }
}

// MARK: - Page scaffold

/// Standard page: a large title, optional trailing control, then content.
struct Page<Content: View, Trailing: View>: View {
    let title: String
    var subtitle: String? = nil
    @ViewBuilder var trailing: Trailing
    @ViewBuilder var content: Content

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                HStack(alignment: .firstTextBaseline) {
                    VStack(alignment: .leading, spacing: 3) {
                        Text(title).font(.system(size: 24, weight: .bold))
                        if let subtitle { Text(subtitle).font(.system(size: 12)).foregroundStyle(Theme.subtle) }
                    }
                    Spacer()
                    trailing
                }
                content
            }
            .padding(28)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .background(Color(NSColor.windowBackgroundColor))
    }
}

extension Page where Trailing == EmptyView {
    init(title: String, subtitle: String? = nil, @ViewBuilder content: () -> Content) {
        self.init(title: title, subtitle: subtitle, trailing: { EmptyView() }, content: content)
    }
}
