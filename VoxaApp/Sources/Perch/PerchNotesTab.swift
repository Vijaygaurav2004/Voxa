import SwiftUI

/// Notes: a scrolling grid of cards with a floating search / sort / add bar.
struct PerchNotesTab: View {
    @ObservedObject private var store = PerchNotesStore.shared
    @ObservedObject private var settings = PerchSettings.shared

    @State private var searching = false
    @State private var editing: PerchNote?
    @State private var selected: UUID?

    private let columns = [GridItem(.adaptive(minimum: 200, maximum: 320), spacing: 8)]

    var body: some View {
        ZStack(alignment: .bottom) {
            ScrollView {
                LazyVGrid(columns: columns, spacing: 8) {
                    ForEach(store.filtered) { note in
                        card(note)
                    }
                }
                .padding(12)
                .padding(.bottom, 52)      // clear the floating bar
            }
            .scrollIndicators(.hidden)

            if store.filtered.isEmpty {
                empty
            }

            floatingBar
        }
        .sheet(item: $editing) { note in
            PerchNoteEditor(note: note) { updated in
                store.update(updated)
                editing = nil
            } onCancel: {
                editing = nil
            } onDelete: {
                store.delete(note)
                editing = nil
            }
        }
    }

    // MARK: Card

    private func card(_ note: PerchNote) -> some View {
        let isSelected = selected == note.id
        return VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 7) {
                Image(systemName: note.symbol)
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundStyle(Perch.text)
                    .frame(width: 24, height: 24)
                    .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(Perch.innerHover))
                Text(note.title)
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(Perch.text).lineLimit(1)
                Spacer(minLength: 4)
                Menu {
                    Button("Edit") { editing = note }
                    Button("Duplicate") { store.duplicate(note) }
                    Divider()
                    Button("Delete", role: .destructive) { store.delete(note) }
                } label: {
                    Image(systemName: "ellipsis")
                        .font(.system(size: 11, weight: .semibold))
                        .foregroundStyle(Perch.subtle)
                        .frame(width: 18, height: 18)
                        .contentShape(Rectangle())
                }
                .menuStyle(.borderlessButton)
                .menuIndicator(.hidden)
                .frame(width: 18)
            }

            Text(note.preview.isEmpty ? "Empty note" : note.preview)
                .font(.system(size: 11))
                .foregroundStyle(Perch.subtle)
                .lineLimit(2)
                .multilineTextAlignment(.leading)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(11)
        .background(
            RoundedRectangle(cornerRadius: Perch.cardRadius, style: .continuous)
                .fill(isSelected ? settings.accent.color.opacity(0.16) : Perch.card)
                .overlay(RoundedRectangle(cornerRadius: Perch.cardRadius, style: .continuous).fill(Perch.sheen))
        )
        .overlay(
            RoundedRectangle(cornerRadius: Perch.cardRadius, style: .continuous)
                .strokeBorder(isSelected ? AnyShapeStyle(settings.accent.color.opacity(0.75))
                                         : AnyShapeStyle(Perch.edge), lineWidth: 1)
        )
        .shadow(color: .black.opacity(isSelected ? 0.35 : 0.2), radius: isSelected ? 10 : 5, y: 3)
        .contentShape(Rectangle())
        // Double-click must be declared BEFORE the single-tap, otherwise the
        // single-tap recogniser claims the event and editing never fires.
        .onTapGesture(count: 2) { editing = note }
        .onTapGesture { selected = note.id }
        .help("Double-click to edit")
    }

    private var empty: some View {
        VStack(spacing: 6) {
            Image(systemName: "note.text").font(.system(size: 22)).foregroundStyle(Perch.faint)
            Text(store.query.trimmed.isEmpty ? "No notes yet" : "Nothing matches")
                .font(.system(size: 12, weight: .medium)).foregroundStyle(Perch.subtle)
        }
        .frame(maxHeight: .infinity)
        .padding(.bottom, 40)
    }

    // MARK: Floating bar

    private var floatingBar: some View {
        PerchFloatingBar {
            if searching {
                HStack(spacing: 6) {
                    Image(systemName: "magnifyingglass").font(.system(size: 11)).foregroundStyle(Perch.subtle)
                    TextField("Search notes", text: $store.query)
                        .textFieldStyle(.plain)
                        .font(.system(size: 12))
                        .foregroundStyle(Perch.text)
                        .frame(width: 150)
                    Button {
                        store.query = ""; searching = false
                    } label: {
                        Image(systemName: "xmark").font(.system(size: 10, weight: .bold)).foregroundStyle(Perch.subtle)
                    }
                    .buttonStyle(.plain)
                }
                .padding(.horizontal, 12).frame(height: 34)
            } else {
                PerchIconButton(symbol: "magnifyingglass") { searching = true }
            }

            PerchIconButton(symbol: "arrow.up.arrow.down", active: store.sortAlphabetical) {
                store.sortAlphabetical.toggle()
            }
            .help(store.sortAlphabetical ? "Sorted A–Z" : "Sorted by newest")

            PerchIconButton(symbol: "plus") {
                editing = store.add()
            }
        }
        .padding(.bottom, 12)
    }
}

// MARK: - Editor

struct PerchNoteEditor: View {
    @State var note: PerchNote
    var onSave: (PerchNote) -> Void
    var onCancel: () -> Void
    var onDelete: () -> Void

    private let symbols = ["note.text", "bookmark.fill", "backpack.fill", "book.fill",
                           "flag.fill", "fork.knife", "graduationcap.fill", "lightbulb.fill"]

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Note").font(.system(size: 15, weight: .bold)).foregroundStyle(Perch.text)

            TextField("Title", text: $note.title)
                .textFieldStyle(.plain)
                .font(.system(size: 14, weight: .semibold))
                .foregroundStyle(Perch.text)
                .padding(9)
                .background(RoundedRectangle(cornerRadius: 9, style: .continuous).fill(Perch.card))
                .overlay(RoundedRectangle(cornerRadius: 9, style: .continuous).strokeBorder(Perch.stroke))

            TextEditor(text: $note.body)
                .font(.system(size: 12))
                .foregroundStyle(Perch.text)
                .scrollContentBackground(.hidden)
                .padding(6)
                .frame(height: 150)
                .background(RoundedRectangle(cornerRadius: 9, style: .continuous).fill(Perch.card))
                .overlay(RoundedRectangle(cornerRadius: 9, style: .continuous).strokeBorder(Perch.stroke))

            HStack(spacing: 6) {
                ForEach(symbols, id: \.self) { symbol in
                    Button { note.symbol = symbol } label: {
                        Image(systemName: symbol)
                            .font(.system(size: 12))
                            .foregroundStyle(Perch.text)
                            .frame(width: 28, height: 28)
                            .background(RoundedRectangle(cornerRadius: 7, style: .continuous)
                                .fill(note.symbol == symbol ? Color.white.opacity(0.2) : Perch.card))
                    }
                    .buttonStyle(.plain)
                }
            }

            HStack {
                Button("Delete", role: .destructive) { onDelete() }
                    .buttonStyle(.plain).foregroundStyle(.red).font(.system(size: 12, weight: .medium))
                Spacer()
                Button("Cancel") { onCancel() }
                    .buttonStyle(.plain).foregroundStyle(Perch.subtle).font(.system(size: 12))
                Button("Save") { onSave(note) }
                    .buttonStyle(.plain)
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(.black)
                    .padding(.horizontal, 14).padding(.vertical, 7)
                    .background(Capsule().fill(Color.white))
            }
        }
        .padding(18)
        .frame(width: 420)
        .background(Perch.bg)
    }
}
