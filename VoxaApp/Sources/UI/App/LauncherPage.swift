import SwiftUI
import AppKit
import UniformTypeIdentifiers

// MARK: - Launcher settings + wheel editor

struct LauncherPage: View {
    @ObservedObject private var settings = RadialSettings.shared
    @ObservedObject private var catalog = RadialCatalog.shared

    /// Which ring the editor is showing (indices into the nested catalogue).
    @State private var path: [Int] = []
    @State private var editTarget: EditTarget?
    @State private var confirmReset = false

    struct EditTarget: Identifiable {
        let id = UUID()
        /// nil when adding a new slice.
        var index: Int?
        var item: RadialItem
    }

    private var currentItems: [RadialItem] { catalog.items(at: path) }

    var body: some View {
        Page(title: "Launcher", subtitle: "A radial menu for apps, folders, shell commands and Voxa actions") {

            masterToggle

            if settings.enabled {
                triggerCard
                behaviourCard
                wheelEditor
                dangerZone
            } else {
                disabledHint
            }
        }
        .sheet(item: $editTarget) { target in
            ItemEditor(
                target: target,
                onSave: { save($0) },
                onCancel: { editTarget = nil }
            )
        }
    }

    // MARK: Master switch

    private var masterToggle: some View {
        Card {
            SettingRow(icon: "circle.hexagongrid",
                       title: "Radial Launcher",
                       subtitle: settings.enabled
                            ? "Press \(settings.hotkey.label) anywhere to summon the wheel"
                            : "Off — the shortcut is released back to the system") {
                MonoToggle(isOn: $settings.enabled)
            }
        }
    }

    private var disabledHint: some View {
        VStack(spacing: 10) {
            Image(systemName: "circle.hexagongrid").font(.system(size: 34)).foregroundStyle(Theme.faint)
            Text("Launcher is off").font(.system(size: 15, weight: .medium))
            Text("Turn it on to bind a global shortcut and customise the wheel.")
                .font(.system(size: 12)).foregroundStyle(Theme.subtle)
                .multilineTextAlignment(.center).frame(maxWidth: 320)
        }
        .frame(maxWidth: .infinity).padding(.vertical, 40)
    }

    // MARK: Trigger

    private var triggerCard: some View {
        VStack(alignment: .leading, spacing: 8) {
            SectionLabel(text: "Trigger")
            Card {
                VStack(spacing: 14) {
                    SettingRow(icon: "command", title: "Shortcut", subtitle: "Global — works in any app") {
                        Picker("", selection: $settings.hotkey) {
                            ForEach(RadialHotkeySpec.presets) { spec in
                                Text(spec.label).tag(spec)
                            }
                        }
                        .labelsHidden().frame(width: 130)
                    }
                    Divider().overlay(Theme.stroke)
                    SettingRow(icon: "hand.tap", title: "Mode", subtitle: settings.trigger.detail) {
                        Picker("", selection: $settings.trigger) {
                            ForEach(RadialTrigger.allCases) { mode in
                                Text(mode.title).tag(mode)
                            }
                        }
                        .labelsHidden().frame(width: 130)
                    }
                    Divider().overlay(Theme.stroke)
                    SettingRow(icon: "play.circle", title: "Try it", subtitle: "Open the wheel right now") {
                        Button("Open") { RadialLauncher.shared.show() }
                            .buttonStyle(GhostButtonStyle()).frame(width: 96)
                    }
                }
            }
        }
    }

    // MARK: Behaviour

    private var behaviourCard: some View {
        VStack(alignment: .leading, spacing: 8) {
            SectionLabel(text: "Appearance & behaviour")
            Card {
                VStack(spacing: 14) {
                    SettingRow(icon: "circle.grid.cross",
                               title: "Slices per ring",
                               subtitle: "Items beyond this paginate with ‹ ›") {
                        HStack(spacing: 8) {
                            Stepper("", value: $settings.slots, in: 4...14).labelsHidden()
                            Text("\(settings.slots)")
                                .font(.system(size: 13, weight: .medium, design: .rounded))
                                .monospacedDigit().frame(width: 22)
                        }
                    }
                    Divider().overlay(Theme.stroke)
                    SettingRow(icon: "arrow.up.left.and.down.right.magnifyingglass",
                               title: "Size",
                               subtitle: "Scroll over the wheel to resize it live") {
                        HStack(spacing: 8) {
                            Slider(value: $settings.scale,
                                   in: RadialSettings.minScale...RadialSettings.maxScale)
                                .frame(width: 130)
                            Text("\(Int(settings.scale * 100))%")
                                .font(.system(size: 12, weight: .medium, design: .rounded))
                                .monospacedDigit().frame(width: 38, alignment: .trailing)
                        }
                    }
                    Divider().overlay(Theme.stroke)
                    SettingRow(icon: "folder.badge.plus", title: "Branch on hover",
                               subtitle: "Dwell on a folder and its children fan out. Off requires a click.") {
                        MonoToggle(isOn: $settings.dwellToExpand)
                    }
                    Divider().overlay(Theme.stroke)
                    SettingRow(icon: "pin", title: "Position",
                               subtitle: settings.isPinned
                                    ? "Pinned where you dragged it"
                                    : "Drag the wheel's centre to pin it somewhere") {
                        if settings.isPinned {
                            Button("Unpin") { settings.pinnedFraction = nil }
                                .buttonStyle(GhostButtonStyle()).frame(width: 96)
                        } else {
                            Text("Not pinned").font(.system(size: 11)).foregroundStyle(Theme.faint)
                        }
                    }
                    Divider().overlay(Theme.stroke)
                    SettingRow(icon: "cursorarrow", title: "Open at pointer",
                               subtitle: settings.isPinned
                                    ? "Overridden while the wheel is pinned"
                                    : "Off centres the wheel on the active display") {
                        MonoToggle(isOn: $settings.showAtCursor)
                    }
                    .opacity(settings.isPinned ? 0.5 : 1)
                    Divider().overlay(Theme.stroke)
                    SettingRow(icon: "textformat", title: "Show labels",
                               subtitle: "Off shows icons only — a tighter wheel") {
                        MonoToggle(isOn: $settings.showLabels)
                    }
                    Divider().overlay(Theme.stroke)
                    SettingRow(icon: "xmark.circle", title: "Close after launch",
                               subtitle: "Off keeps the wheel up so you can fire several actions") {
                        MonoToggle(isOn: $settings.closeAfterLaunch)
                    }
                }
            }
            keyHints
        }
    }

    private var keyHints: some View {
        Card(padding: 14) {
            VStack(alignment: .leading, spacing: 7) {
                hint("1 – 9, 0, a – z", "Fire that slice directly")
                hint("↑ ↓ / Tab", "Move the highlight")
                hint("← →", "Flip pages")
                hint("Return", "Fire the highlighted slice")
                hint("Delete", "Collapse the branched ring")
                hint("Esc", "Close and return focus")
                hint("Drag centre", "Move the wheel, then it stays there")
                hint("Scroll", "Resize the wheel")
            }
        }
    }

    private func hint(_ keys: String, _ text: String) -> some View {
        HStack(spacing: 10) {
            Text(keys)
                .font(.system(size: 11, weight: .medium, design: .rounded))
                .foregroundStyle(Theme.text)
                .padding(.horizontal, 7).padding(.vertical, 3)
                .background(RoundedRectangle(cornerRadius: 5).fill(Theme.card))
                .overlay(RoundedRectangle(cornerRadius: 5).strokeBorder(Theme.stroke))
                .frame(width: 120, alignment: .leading)
            Text(text).font(.system(size: 12)).foregroundStyle(Theme.subtle)
            Spacer()
        }
    }

    // MARK: Wheel editor

    private var wheelEditor: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 6) {
                SectionLabel(text: "Wheel")
                if !path.isEmpty {
                    Text("›").foregroundStyle(Theme.faint).font(.system(size: 11, weight: .semibold))
                    Text(breadcrumb)
                        .font(.system(size: 11, weight: .semibold))
                        .foregroundStyle(Theme.subtle)
                }
                Spacer()
                if !path.isEmpty {
                    Button { path.removeLast() } label: {
                        Label("Back", systemImage: "chevron.left").font(.system(size: 12))
                    }
                    .buttonStyle(.plain).foregroundStyle(Theme.subtle)
                }
                Button { addItem() } label: {
                    Label("Add", systemImage: "plus").font(.system(size: 12))
                }
                .buttonStyle(.plain).foregroundStyle(Theme.text)
            }

            if currentItems.isEmpty {
                Card {
                    Text("This ring is empty. Add a slice to fill it.")
                        .font(.system(size: 12)).foregroundStyle(Theme.subtle)
                        .frame(maxWidth: .infinity, alignment: .center).padding(.vertical, 18)
                }
            } else {
                VStack(spacing: 8) {
                    ForEach(Array(currentItems.enumerated()), id: \.element.id) { index, item in
                        slotRow(index: index, item: item)
                    }
                }
                if currentItems.count > settings.slots {
                    Text("\(currentItems.count) items · \(Int(ceil(Double(currentItems.count) / Double(settings.slots)))) pages")
                        .font(.system(size: 11)).foregroundStyle(Theme.faint)
                }
            }
        }
    }

    private func slotRow(index: Int, item: RadialItem) -> some View {
        Card(padding: 12) {
            HStack(spacing: 12) {
                Text(slotLabel(index))
                    .font(.system(size: 11, weight: .semibold, design: .rounded))
                    .foregroundStyle(Theme.subtle)
                    .frame(width: 20)

                ZStack {
                    RoundedRectangle(cornerRadius: Theme.radiusSmall).fill(Theme.card).frame(width: 32, height: 32)
                    if let icon = RadialIcon.appIcon(for: item) {
                        Image(nsImage: icon).resizable().frame(width: 22, height: 22)
                    } else {
                        Image(systemName: item.symbol).font(.system(size: 14)).foregroundStyle(Theme.text)
                    }
                }

                VStack(alignment: .leading, spacing: 2) {
                    Text(item.title).font(.system(size: 13, weight: .medium))
                    Text(subtitle(for: item)).font(.system(size: 11)).foregroundStyle(Theme.subtle).lineLimit(1)
                }

                Spacer(minLength: 6)

                if item.isSubmenu {
                    Button { path.append(index) } label: {
                        Label("\(item.children.count)", systemImage: "chevron.right")
                            .font(.system(size: 11, weight: .medium))
                            .foregroundStyle(Theme.subtle)
                    }
                    .buttonStyle(.plain)
                }

                iconButton("arrow.up")   { move(index, by: -1) }.disabled(index == 0)
                iconButton("arrow.down") { move(index, by:  1) }.disabled(index == currentItems.count - 1)
                iconButton("pencil")     { editTarget = EditTarget(index: index, item: item) }
                iconButton("trash")      { remove(index) }
            }
        }
    }

    private func iconButton(_ symbol: String, _ action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: symbol).font(.system(size: 12)).foregroundStyle(Theme.subtle)
                .frame(width: 26, height: 26).background(Circle().fill(Theme.card))
        }
        .buttonStyle(.plain)
    }

    private var dangerZone: some View {
        HStack {
            Spacer()
            Button("Reset wheel to defaults") { confirmReset = true }
                .buttonStyle(GhostButtonStyle(tint: .red)).frame(width: 200)
        }
        .confirmationDialog("Reset the wheel?", isPresented: $confirmReset) {
            Button("Reset", role: .destructive) { path = []; catalog.resetToDefaults() }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("Your custom slices will be replaced with the defaults for this Mac.")
        }
    }

    // MARK: Helpers

    private var breadcrumb: String {
        var items = catalog.items
        var parts: [String] = []
        for index in path {
            guard index < items.count else { break }
            parts.append(items[index].title)
            items = items[index].children
        }
        return parts.joined(separator: " › ")
    }

    private func slotLabel(_ index: Int) -> String {
        if let custom = currentItems[index].shortcut, !custom.isEmpty { return custom.uppercased() }
        if index < 9 { return String(index + 1) }
        if index == 9 { return "0" }
        let letters = Array("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
        let offset = index - 10
        return offset < letters.count ? String(letters[offset]) : "•"
    }

    private func subtitle(for item: RadialItem) -> String {
        switch item.kind {
        case .submenu: return "Folder · \(item.children.count) item\(item.children.count == 1 ? "" : "s")"
        case .listen:  return "Start listening"
        default:       return "\(item.kind.title) · \(item.target)"
        }
    }

    // MARK: Mutations

    private func addItem() {
        editTarget = EditTarget(index: nil, item: RadialItem("New Item", .app))
    }

    private func save(_ target: EditTarget) {
        var items = currentItems
        if let index = target.index, index < items.count {
            // Keep the children of a folder that's being renamed/retargeted.
            var updated = target.item
            updated.children = target.item.isSubmenu ? items[index].children : []
            items[index] = updated
        } else {
            items.append(target.item)
        }
        catalog.replace(at: path, with: items)
        RadialIcon.clearCache()
        editTarget = nil
    }

    private func remove(_ index: Int) {
        var items = currentItems
        guard index < items.count else { return }
        items.remove(at: index)
        catalog.replace(at: path, with: items)
    }

    private func move(_ index: Int, by delta: Int) {
        var items = currentItems
        let destination = index + delta
        guard index >= 0, index < items.count, destination >= 0, destination < items.count else { return }
        items.swapAt(index, destination)
        catalog.replace(at: path, with: items)
    }
}

// MARK: - Slice editor sheet

private struct ItemEditor: View {
    @State var target: LauncherPage.EditTarget
    var onSave: (LauncherPage.EditTarget) -> Void
    var onCancel: () -> Void

    private let symbolPalette = [
        "app", "folder", "globe", "terminal", "sparkles", "mic", "gearshape",
        "music.note", "safari", "note.text", "clipboard", "camera.viewfinder",
        "moon", "lock", "trash", "square.grid.2x2", "bolt", "star", "envelope",
        "calendar", "message", "chart.bar", "wrench.and.screwdriver", "display",
    ]

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text(target.index == nil ? "New Slice" : "Edit Slice")
                .font(.system(size: 18, weight: .bold))

            field("Name") {
                TextField("e.g. Safari", text: $target.item.title).textFieldStyle(.roundedBorder)
            }

            field("Does what") {
                Picker("", selection: $target.item.kind) {
                    ForEach(RadialKind.allCases) { kind in Text(kind.title).tag(kind) }
                }
                .labelsHidden().pickerStyle(.menu)
                .onChange(of: target.item.kind) { _, newKind in
                    if target.item.symbol.isEmpty { target.item.symbol = newKind.defaultSymbol }
                    if newKind.isTargetless { target.item.target = "" }
                }
            }

            if !target.item.kind.isTargetless {
                field(target.item.kind == .app ? "Application" : "Target") {
                    HStack(spacing: 8) {
                        TextField(target.item.kind.placeholder, text: $target.item.target)
                            .textFieldStyle(.roundedBorder)
                        if target.item.kind == .app || target.item.kind == .path {
                            Button("Choose…") { chooseTarget() }
                                .buttonStyle(GhostButtonStyle()).frame(width: 96)
                        }
                    }
                }
            }

            field("Icon") {
                VStack(alignment: .leading, spacing: 8) {
                    TextField("SF Symbol name", text: $target.item.symbol).textFieldStyle(.roundedBorder)
                    LazyVGrid(columns: Array(repeating: GridItem(.fixed(30), spacing: 6), count: 12), spacing: 6) {
                        ForEach(symbolPalette, id: \.self) { symbol in
                            Button { target.item.symbol = symbol } label: {
                                Image(systemName: symbol)
                                    .font(.system(size: 13))
                                    .frame(width: 28, height: 28)
                                    .background(RoundedRectangle(cornerRadius: 6)
                                        .fill(target.item.symbol == symbol ? Theme.cardHover : Theme.card))
                                    .overlay(RoundedRectangle(cornerRadius: 6)
                                        .strokeBorder(target.item.symbol == symbol ? Theme.strokeStrong : .clear))
                            }
                            .buttonStyle(.plain)
                        }
                    }
                }
            }

            field("Keyboard shortcut (optional)") {
                TextField("Defaults to the slot number", text: Binding(
                    get: { target.item.shortcut ?? "" },
                    set: { target.item.shortcut = $0.isEmpty ? nil : String($0.prefix(1)).lowercased() }
                ))
                .textFieldStyle(.roundedBorder).frame(width: 220)
            }

            HStack(spacing: 10) {
                Spacer()
                Button("Cancel") { onCancel() }.buttonStyle(GhostButtonStyle()).frame(width: 100)
                Button("Save") { onSave(target) }
                    .buttonStyle(PrimaryButtonStyle(disabled: !isValid))
                    .frame(width: 100).disabled(!isValid)
            }
        }
        .padding(24)
        .frame(width: 520)
    }

    private var isValid: Bool {
        let hasTitle = !target.item.title.trimmingCharacters(in: .whitespaces).isEmpty
        let hasTarget = target.item.kind.isTargetless
            || !target.item.target.trimmingCharacters(in: .whitespaces).isEmpty
        return hasTitle && hasTarget
    }

    private func field<V: View>(_ label: String, @ViewBuilder _ content: () -> V) -> some View {
        VStack(alignment: .leading, spacing: 6) { SectionLabel(text: label); content() }
    }

    /// Native picker so any app or folder can be bound, not just the ones we scan.
    private func chooseTarget() {
        let panel = NSOpenPanel()
        let wantsApp = target.item.kind == .app
        panel.canChooseFiles = true
        panel.canChooseDirectories = !wantsApp
        panel.allowsMultipleSelection = false
        panel.directoryURL = URL(fileURLWithPath: wantsApp ? "/Applications" : NSHomeDirectory())
        if wantsApp { panel.allowedContentTypes = [.application] }

        guard panel.runModal() == .OK, let url = panel.url else { return }
        if wantsApp {
            let name = url.deletingPathExtension().lastPathComponent
            // Store something resolvable, not the bare display name: the picker
            // exists precisely so apps *outside* the handful of folders we scan
            // can be bound, and a name alone can never be resolved back to those.
            // Bundle id first so the binding survives the app being moved.
            target.item.target = Bundle(url: url)?.bundleIdentifier ?? url.path
            if target.item.title.isEmpty || target.item.title == "New Item" { target.item.title = name }
        } else {
            target.item.target = url.path
            if target.item.title.isEmpty || target.item.title == "New Item" {
                target.item.title = url.lastPathComponent
            }
        }
    }
}
