import SwiftUI
import AppKit
import UniformTypeIdentifiers

/// Tray: an AirDrop shortcut plus a drop-anywhere file shelf. Files dropped here
/// are copied into ~/.voxa/perch/tray, so the shelf survives the original being
/// moved or deleted, and can be dragged straight back out into any app.
struct PerchTrayTab: View {
    @ObservedObject private var store = PerchTrayStore.shared
    @ObservedObject private var settings = PerchSettings.shared

    @State private var targeted = false
    @State private var toast: String?

    var body: some View {
        HStack(spacing: 10) {
            airDropCard
            shelfCard
        }
        .padding(12)
        .onAppear { store.reload() }
    }

    // MARK: AirDrop

    private var airDropCard: some View {
        Button { airDropAll() } label: {
            VStack(spacing: 8) {
                ZStack {
                    Circle().fill(Color.white).frame(width: 62, height: 62)
                        .shadow(color: .black.opacity(0.35), radius: 10, y: 3)
                    Image(systemName: "dot.radiowaves.up.forward")
                        .font(.system(size: 28, weight: .medium))
                        .foregroundStyle(Color(red: 0.10, green: 0.42, blue: 0.95))
                }
                Text("AirDrop")
                    .font(.system(size: 13, weight: .semibold)).foregroundStyle(Perch.text)
                if !store.items.isEmpty {
                    Text("\(store.items.count) file\(store.items.count == 1 ? "" : "s")")
                        .font(.system(size: 9)).foregroundStyle(Perch.faint)
                }
            }
            .frame(width: 148)
            .frame(maxHeight: .infinity)
            .perchSurface()
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .disabled(store.items.isEmpty)
        .opacity(store.items.isEmpty ? 0.55 : 1)
        .help(store.items.isEmpty ? "Add files to the tray first" : "Send the tray via AirDrop")
    }

    // MARK: Shelf

    private var shelfCard: some View {
        ZStack {
            RoundedRectangle(cornerRadius: Perch.cardRadius, style: .continuous)
                .fill(targeted ? settings.accent.color.opacity(0.12) : Perch.card)
                .overlay(RoundedRectangle(cornerRadius: Perch.cardRadius, style: .continuous).fill(Perch.sheen))
            // The drop target advertises itself with a permanent accent ring,
            // brightening while a drag is actually over it.
            RoundedRectangle(cornerRadius: Perch.cardRadius, style: .continuous)
                .strokeBorder(settings.accent.color.opacity(targeted ? 1.0 : 0.45),
                              lineWidth: targeted ? 2 : 1.5)
                .shadow(color: settings.accent.color.opacity(targeted ? 0.45 : 0.18),
                        radius: targeted ? 14 : 7)

            if store.items.isEmpty {
                emptyShelf
            } else {
                fileGrid
            }

            if let toast {
                VStack {
                    Spacer()
                    PerchToast(text: toast, symbol: "tray.and.arrow.down.fill").padding(.bottom, 10)
                }
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .onDrop(of: [.fileURL], isTargeted: $targeted) { providers in
            handleDrop(providers)
        }
    }

    private var emptyShelf: some View {
        VStack(spacing: 5) {
            Image(systemName: "tray.fill").font(.system(size: 22)).foregroundStyle(Perch.text.opacity(0.8))
            Text("Files Tray").font(.system(size: 14, weight: .semibold)).foregroundStyle(Perch.text)
            HStack(spacing: 4) {
                Text("Drag and drop files or").font(.system(size: 11)).foregroundStyle(Perch.subtle)
                Button("Upload") { chooseFiles() }
                    .buttonStyle(.plain)
                    .font(.system(size: 11, weight: .medium))
                    .foregroundStyle(Perch.text)
                    .underline()
            }
        }
    }

    private var fileGrid: some View {
        VStack(spacing: 0) {
            HStack {
                Text("\(store.items.count) FILE\(store.items.count == 1 ? "" : "S")")
                    .font(.system(size: 9, weight: .semibold)).tracking(0.7).foregroundStyle(Perch.faint)
                Spacer()
                Button("Add") { chooseFiles() }
                    .buttonStyle(.plain).font(.system(size: 10)).foregroundStyle(Perch.subtle)
                Button("Clear") { store.clear() }
                    .buttonStyle(.plain).font(.system(size: 10)).foregroundStyle(Perch.subtle)
            }
            .padding(.horizontal, 10).padding(.top, 9).padding(.bottom, 6)

            ScrollView(.horizontal) {
                HStack(spacing: 8) {
                    ForEach(store.items) { item in
                        fileChip(item)
                    }
                }
                .padding(.horizontal, 10).padding(.bottom, 10)
            }
            .scrollIndicators(.hidden)
        }
    }

    private func fileChip(_ item: PerchTrayItem) -> some View {
        VStack(spacing: 5) {
            ZStack {
                RoundedRectangle(cornerRadius: 12, style: .continuous)
                    .fill(Perch.inner)
                    .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).strokeBorder(Perch.stroke, lineWidth: 1))
                    .frame(width: 66, height: 56)
                Image(nsImage: NSWorkspace.shared.icon(forFile: item.url.path))
                    .resizable().frame(width: 30, height: 30)
            }
            Text(item.name)
                .font(.system(size: 9)).foregroundStyle(Perch.subtle)
                .lineLimit(1).frame(width: 66)
        }
        .contentShape(Rectangle())
        // Dragging the chip hands the real file to whatever it's dropped on.
        .onDrag { NSItemProvider(contentsOf: item.url) ?? NSItemProvider() }
        .contextMenu {
            Button("Reveal in Finder") { store.revealInFinder(item) }
            Button("Open") { NSWorkspace.shared.open(item.url) }
            Divider()
            Button("Remove", role: .destructive) { store.remove(item) }
        }
        .help("\(item.name) · \(item.sizeText) — drag out to move it anywhere")
    }

    // MARK: Actions

    private func handleDrop(_ providers: [NSItemProvider]) -> Bool {
        let group = DispatchGroup()
        var urls: [URL] = []
        let lock = NSLock()

        for provider in providers where provider.hasItemConformingToTypeIdentifier(UTType.fileURL.identifier) {
            group.enter()
            _ = provider.loadObject(ofClass: URL.self) { url, _ in
                if let url {
                    lock.lock(); urls.append(url); lock.unlock()
                }
                group.leave()
            }
        }

        group.notify(queue: .main) {
            guard !urls.isEmpty else { return }
            store.acceptAsync(urls: urls) { added in
                if added > 0 { flash("Added \(added) file\(added == 1 ? "" : "s")") }
            }
        }
        return true
    }

    private func chooseFiles() {
        let panel = NSOpenPanel()
        panel.canChooseFiles = true
        panel.canChooseDirectories = false
        panel.allowsMultipleSelection = true
        guard panel.runModal() == .OK else { return }
        store.acceptAsync(urls: panel.urls) { added in
            if added > 0 { flash("Added \(added) file\(added == 1 ? "" : "s")") }
        }
    }

    private func airDropAll() {
        store.airDrop(store.items.map(\.url), from: nil)
    }

    private func flash(_ text: String) {
        withAnimation(.spring(response: 0.24, dampingFraction: 0.8)) { toast = text }
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.4) {
            withAnimation(.easeOut(duration: 0.2)) { toast = nil }
        }
    }
}
