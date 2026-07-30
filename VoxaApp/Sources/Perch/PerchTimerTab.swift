import SwiftUI

/// Timer: a big readout on the left, mode switch and preset chips on the right.
struct PerchTimerTab: View {
    @ObservedObject private var store = PerchTimerStore.shared
    @ObservedObject private var settings = PerchSettings.shared

    @State private var addingPreset = false
    @State private var minutesText = "5"

    private let columns = [GridItem(.flexible(), spacing: 8),
                           GridItem(.flexible(), spacing: 8),
                           GridItem(.flexible(), spacing: 8)]

    var body: some View {
        HStack(spacing: 10) {
            readout.frame(width: 250)
            VStack(spacing: 8) {
                modeSwitch
                presetGrid
            }
            .frame(maxWidth: .infinity)
        }
        .padding(12)
        .sheet(isPresented: $addingPreset) { addSheet }
    }

    // MARK: Readout

    private var readout: some View {
        VStack(spacing: 8) {
            ZStack {
                RoundedRectangle(cornerRadius: Perch.cardRadius, style: .continuous).fill(Perch.card)
                RoundedRectangle(cornerRadius: Perch.cardRadius, style: .continuous).fill(Perch.sheen)
                RoundedRectangle(cornerRadius: Perch.cardRadius, style: .continuous)
                    .strokeBorder(store.finishedAt != nil ? AnyShapeStyle(settings.accent.color)
                                                          : AnyShapeStyle(Perch.edge), lineWidth: 1)
                Text(store.display)
                    .font(.system(size: 54, weight: .heavy, design: .rounded))
                    .monospacedDigit()
                    .foregroundStyle(store.finishedAt != nil ? settings.accent.color : Perch.text)
                    .minimumScaleFactor(0.5)
                    .lineLimit(1)
                    .padding(.horizontal, 10)
            }
            .frame(maxHeight: .infinity)

            HStack(spacing: 8) {
                Button { store.toggle() } label: {
                    Image(systemName: store.running ? "pause.fill" : "play.fill")
                        .font(.system(size: 14, weight: .semibold))
                        .foregroundStyle(store.running ? Perch.text : settings.accent.onAccent)
                        .frame(maxWidth: .infinity).frame(height: 38)
                        .background(RoundedRectangle(cornerRadius: Perch.innerRadius, style: .continuous)
                            .fill(store.running ? AnyShapeStyle(Perch.card) : AnyShapeStyle(settings.accent.color)))
                        .overlay(RoundedRectangle(cornerRadius: Perch.innerRadius, style: .continuous)
                            .strokeBorder(Perch.edge, lineWidth: 1))
                }
                .buttonStyle(.plain)

                Button { store.reset() } label: {
                    Image(systemName: "arrow.counterclockwise")
                        .font(.system(size: 13, weight: .semibold)).foregroundStyle(Perch.text)
                        .frame(maxWidth: .infinity).frame(height: 38)
                        .background(RoundedRectangle(cornerRadius: Perch.innerRadius, style: .continuous).fill(Perch.card))
                        .overlay(RoundedRectangle(cornerRadius: Perch.innerRadius, style: .continuous)
                            .strokeBorder(Perch.edge, lineWidth: 1))
                }
                .buttonStyle(.plain)
                .help("Reset")
            }
        }
    }

    // MARK: Mode

    private var modeSwitch: some View {
        HStack(spacing: 4) {
            ForEach(PerchTimerStore.Mode.allCases) { mode in
                let active = store.mode == mode
                Button { store.setMode(mode) } label: {
                    HStack(spacing: 6) {
                        Image(systemName: mode.symbol).font(.system(size: 11, weight: .semibold))
                        Text(mode.title).font(.system(size: 12, weight: active ? .semibold : .regular))
                    }
                    .foregroundStyle(active ? Perch.text : Perch.subtle)
                    .frame(maxWidth: .infinity).frame(height: 32)
                    .background(RoundedRectangle(cornerRadius: 11, style: .continuous)
                        .fill(active ? AnyShapeStyle(settings.accent.color.opacity(0.22)) : AnyShapeStyle(Color.clear)))
                    .overlay(RoundedRectangle(cornerRadius: 11, style: .continuous)
                        .strokeBorder(active ? settings.accent.color.opacity(0.45) : .clear, lineWidth: 1))
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
            }
        }
        .padding(4)
        .perchSurface(radius: 15)
    }

    // MARK: Presets

    private var presetGrid: some View {
        ScrollView {
            LazyVGrid(columns: columns, spacing: 8) {
                ForEach(store.presets, id: \.self) { seconds in
                    presetChip(seconds)
                }
                addChip
            }
        }
        .scrollIndicators(.hidden)
        .opacity(store.mode == .countdown ? 1 : 0.35)
        .allowsHitTesting(store.mode == .countdown)
    }

    private func presetChip(_ seconds: Int) -> some View {
        HStack(spacing: 4) {
            Text(PerchTimerStore.format(TimeInterval(seconds)))
                .font(.system(size: 14, weight: .bold, design: .rounded))
                .monospacedDigit()
                .foregroundStyle(Perch.text)
                .lineLimit(1).minimumScaleFactor(0.7)
            Spacer(minLength: 0)
            Menu {
                Button("Start") { store.select(preset: seconds); store.start() }
                Divider()
                Button("Remove", role: .destructive) { store.removePreset(seconds) }
            } label: {
                Image(systemName: "ellipsis")
                    .font(.system(size: 10, weight: .semibold)).foregroundStyle(Perch.subtle)
                    .frame(width: 16, height: 16).contentShape(Rectangle())
            }
            .menuStyle(.borderlessButton).menuIndicator(.hidden).frame(width: 16)
        }
        .padding(.horizontal, 11).frame(height: 46)
        .perchSurface(radius: Perch.innerRadius)
        .contentShape(Rectangle())
        .onTapGesture { store.select(preset: seconds) }
        .help("Click to load · ⋯ to start or remove")
    }

    private var addChip: some View {
        Button { minutesText = "5"; addingPreset = true } label: {
            Image(systemName: "plus")
                .font(.system(size: 13, weight: .semibold)).foregroundStyle(Perch.subtle)
                .frame(maxWidth: .infinity).frame(height: 46)
                .background(RoundedRectangle(cornerRadius: Perch.innerRadius, style: .continuous).fill(Perch.card.opacity(0.5)))
                .overlay(RoundedRectangle(cornerRadius: Perch.innerRadius, style: .continuous)
                    .strokeBorder(Perch.strokeStrong, style: StrokeStyle(lineWidth: 1, dash: [5, 4])))
        }
        .buttonStyle(.plain)
    }

    // MARK: Add preset

    private var addSheet: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("New Preset").font(.system(size: 15, weight: .bold)).foregroundStyle(Perch.text)
            HStack(spacing: 8) {
                TextField("5", text: $minutesText)
                    .textFieldStyle(.plain).font(.system(size: 14, design: .rounded))
                    .foregroundStyle(Perch.text).frame(width: 70)
                    .padding(9)
                    .background(RoundedRectangle(cornerRadius: 9, style: .continuous).fill(Perch.card))
                    .overlay(RoundedRectangle(cornerRadius: 9, style: .continuous).strokeBorder(Perch.stroke))
                Text("minutes").font(.system(size: 12)).foregroundStyle(Perch.subtle)
                Spacer()
            }
            HStack {
                Spacer()
                Button("Cancel") { addingPreset = false }
                    .buttonStyle(.plain).foregroundStyle(Perch.subtle).font(.system(size: 12))
                Button("Add") {
                    // Bounded before the multiply: Swift's `*` traps on
                    // overflow, so an absurd pasted value would crash the app.
                    if let minutes = Int(minutesText.trimmed), (1...(60 * 24 * 30)).contains(minutes) {
                        store.addPreset(seconds: minutes * 60)
                    }
                    addingPreset = false
                }
                .buttonStyle(.plain).font(.system(size: 12, weight: .semibold)).foregroundStyle(.black)
                .padding(.horizontal, 14).padding(.vertical, 7)
                .background(Capsule().fill(Color.white))
            }
        }
        .padding(18).frame(width: 300).background(Perch.bg)
    }
}
