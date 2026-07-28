import SwiftUI

struct ModesPage: View {
    @State private var modes: [VoxaMode] = []
    @State private var loading = false
    @State private var error: String?
    @State private var editing = false

    // Editor state
    @State private var isNew = true
    @State private var name = ""
    @State private var desc = ""
    @State private var steps: [Step] = [Step()]
    @State private var aiPrompt = ""
    @State private var generating = false

    struct Step: Identifiable { let id = UUID(); var text = "" }

    var body: some View {
        if editing { editor } else { list }
    }

    // MARK: - List

    private var list: some View {
        Page(title: "Modes", subtitle: "One-tap routines built from plain-English steps") {
            HStack {
                SectionLabel(text: "\(modes.count) mode\(modes.count == 1 ? "" : "s")")
                Spacer()
                Button { startCreate() } label: { Label("New Mode", systemImage: "plus") }
                    .buttonStyle(GhostButtonStyle())
                    .frame(width: 130)
            }

            if let error { errorBanner(error) }

            if modes.isEmpty && !loading {
                emptyState(icon: "slider.horizontal.3",
                           title: "No modes yet",
                           subtitle: "Create a mode like “Work Mode” that opens your apps and sets the scene.")
            } else {
                VStack(spacing: 12) {
                    ForEach(modes) { mode in modeCard(mode) }
                }
            }
        }
        .onAppear(perform: load)
    }

    private func modeCard(_ mode: VoxaMode) -> some View {
        Card {
            VStack(alignment: .leading, spacing: 8) {
                HStack {
                    Text(mode.name).font(.system(size: 15, weight: .semibold))
                    Spacer()
                    Button { Task { try? await PythonBridge.shared.activateMode(name: mode.name) } } label: {
                        Text("Activate").font(.system(size: 12, weight: .semibold))
                            .foregroundStyle(Color(NSColor.windowBackgroundColor))
                            .padding(.horizontal, 12).padding(.vertical, 6)
                            .background(Capsule().fill(Color.primary))
                    }.buttonStyle(.plain)
                    iconButton("pencil") { startEdit(mode) }
                    iconButton("trash") { remove(mode.name) }
                }
                if !mode.description.isEmpty {
                    Text(mode.description).font(.system(size: 12)).foregroundStyle(Theme.subtle)
                }
                VStack(alignment: .leading, spacing: 4) {
                    ForEach(Array(mode.instructions.prefix(4).enumerated()), id: \.offset) { _, inst in
                        HStack(alignment: .top, spacing: 7) {
                            Circle().fill(Theme.faint).frame(width: 4, height: 4).padding(.top, 6)
                            Text(inst).font(.system(size: 12)).foregroundStyle(Theme.subtle).lineLimit(1)
                        }
                    }
                    if mode.instructions.count > 4 {
                        Text("+ \(mode.instructions.count - 4) more").font(.system(size: 11)).foregroundStyle(Theme.faint)
                    }
                }
            }
        }
    }

    // MARK: - Editor

    private var editor: some View {
        Page(title: isNew ? "New Mode" : "Edit Mode") {
            // AI generate
            VStack(alignment: .leading, spacing: 8) {
                SectionLabel(text: "Describe it — Voxa builds it")
                HStack(spacing: 8) {
                    TextField("e.g. a work mode that opens VS Code and mutes notifications", text: $aiPrompt, axis: .vertical)
                        .textFieldStyle(.plain).font(.system(size: 13)).lineLimit(1...3)
                        .padding(.horizontal, 12).padding(.vertical, 10)
                        .background(RoundedRectangle(cornerRadius: Theme.radiusSmall).fill(Theme.card))
                        .overlay(RoundedRectangle(cornerRadius: Theme.radiusSmall).strokeBorder(Theme.stroke))
                        .disabled(generating)
                    Button(action: generate) {
                        if generating { ProgressView().controlSize(.small) }
                        else { Image(systemName: "wand.and.stars").font(.system(size: 14, weight: .semibold)).foregroundStyle(Color(NSColor.windowBackgroundColor)) }
                    }
                    .frame(width: 44, height: 40)
                    .background(RoundedRectangle(cornerRadius: Theme.radiusSmall).fill(aiPrompt.trimmed.isEmpty ? Theme.card : Color.primary))
                    .buttonStyle(.plain)
                    .disabled(generating || aiPrompt.trimmed.isEmpty)
                }
            }

            field("Name") { TextField("e.g. Work Mode", text: $name).textFieldStyle(.roundedBorder).disabled(!isNew) }
            field("Description (optional)") { TextField("Short description", text: $desc).textFieldStyle(.roundedBorder) }

            VStack(alignment: .leading, spacing: 8) {
                HStack {
                    SectionLabel(text: "Steps")
                    Spacer()
                    Button { steps.append(Step()) } label: { Label("Add", systemImage: "plus").font(.system(size: 12)) }.buttonStyle(.plain).foregroundStyle(Theme.subtle)
                }
                ForEach($steps) { $step in
                    HStack(spacing: 8) {
                        Text("\((steps.firstIndex { $0.id == step.id } ?? 0) + 1)").font(.system(size: 11)).foregroundStyle(Theme.faint).frame(width: 16)
                        TextField("e.g. Open Google Chrome", text: $step.text).textFieldStyle(.roundedBorder)
                        Button { steps.removeAll { $0.id == step.id } } label: { Image(systemName: "minus.circle").foregroundStyle(Theme.subtle) }
                            .buttonStyle(.plain).disabled(steps.count <= 1)
                    }
                }
            }

            if let error { errorBanner(error) }

            HStack(spacing: 10) {
                Button("Cancel") { editing = false; error = nil }.buttonStyle(GhostButtonStyle())
                Button(isNew ? "Create Mode" : "Save Changes") { save() }.buttonStyle(PrimaryButtonStyle())
            }
        }
    }

    // MARK: - Helpers

    private func field<V: View>(_ label: String, @ViewBuilder _ content: () -> V) -> some View {
        VStack(alignment: .leading, spacing: 6) { SectionLabel(text: label); content() }
    }
    private func iconButton(_ icon: String, _ action: @escaping () -> Void) -> some View {
        Button(action: action) { Image(systemName: icon).font(.system(size: 13)).foregroundStyle(Theme.subtle).frame(width: 26, height: 26).background(Circle().fill(Theme.card)) }.buttonStyle(.plain)
    }
    private func errorBanner(_ text: String) -> some View {
        Text(text).font(.system(size: 12)).foregroundStyle(.red)
            .padding(10).frame(maxWidth: .infinity, alignment: .leading)
            .background(RoundedRectangle(cornerRadius: 8).fill(Color.red.opacity(0.1)))
    }
    private func emptyState(icon: String, title: String, subtitle: String) -> some View {
        VStack(spacing: 10) {
            Image(systemName: icon).font(.system(size: 34)).foregroundStyle(Theme.faint)
            Text(title).font(.system(size: 15, weight: .medium))
            Text(subtitle).font(.system(size: 12)).foregroundStyle(Theme.subtle).multilineTextAlignment(.center).frame(maxWidth: 320)
        }
        .frame(maxWidth: .infinity).padding(.vertical, 50)
    }

    // MARK: - Actions

    private func load() {
        loading = true; error = nil
        Task {
            do { modes = try await PythonBridge.shared.getModes() }
            catch { self.error = "Couldn't load modes." }
            loading = false
        }
    }
    private func startCreate() { isNew = true; name = ""; desc = ""; steps = [Step()]; aiPrompt = ""; error = nil; editing = true }
    private func startEdit(_ m: VoxaMode) {
        isNew = false; name = m.name; desc = m.description
        steps = m.instructions.isEmpty ? [Step()] : m.instructions.map { Step(text: $0) }
        aiPrompt = ""; error = nil; editing = true
    }
    private func remove(_ name: String) {
        Task { _ = try? await PythonBridge.shared.deleteMode(name: name); load() }
    }
    private func generate() {
        let p = aiPrompt.trimmed; guard !p.isEmpty else { return }
        generating = true; error = nil
        Task {
            do {
                let spec = try await PythonBridge.shared.generateModeSpec(description: p)
                await MainActor.run {
                    if isNew { name = spec.name }
                    if isNew || desc.trimmed.isEmpty { desc = spec.description }
                    let items = spec.instructions.map { Step(text: $0) }
                    steps = items.isEmpty ? [Step()] : items
                    generating = false
                }
            } catch { await MainActor.run { self.error = "Couldn't generate that mode."; generating = false } }
        }
    }
    private func save() {
        let cleanName = name.trimmed
        guard !cleanName.isEmpty else { error = "Name can't be empty."; return }
        let instructions = steps.map { $0.text.trimmed }.filter { !$0.isEmpty }
        guard !instructions.isEmpty else { error = "Add at least one step."; return }
        error = nil
        Task {
            do {
                if isNew { _ = try await PythonBridge.shared.createMode(name: cleanName, instructions: instructions, description: desc) }
                else { _ = try await PythonBridge.shared.updateMode(name: cleanName, instructions: instructions, description: desc) }
                await MainActor.run { editing = false; load() }
            } catch { await MainActor.run { self.error = "Couldn't save the mode." } }
        }
    }
}
