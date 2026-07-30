import SwiftUI
import AppKit

/// Snippets: pinned values on the left (click to copy), live clipboard history
/// on the right (click to copy, pin to keep).
struct PerchSnippetsTab: View {
    @ObservedObject private var store = PerchSnippetsStore.shared

    @State private var toastFor: UUID?
    @State private var adding = false
    @State private var newLabel = ""
    @State private var newValue = ""
    @State private var editing: PerchSnippet?

    private let columns = [GridItem(.adaptive(minimum: 150, maximum: 260), spacing: 8)]

    var body: some View {
        HStack(spacing: 10) {
            pinnedPane.frame(maxWidth: .infinity)
            historyPane.frame(width: 280)
        }
        .padding(12)
        .sheet(isPresented: $adding) { addSheet }
        .sheet(item: $editing) { snippet in
            PerchSnippetEditor(snippet: snippet) { updated in
                store.update(updated); editing = nil
            } onCancel: { editing = nil }
              onDelete: { store.delete(snippet); editing = nil }
        }
    }

    // MARK: Pinned

    private var pinnedPane: some View {
        ZStack(alignment: .bottom) {
            RoundedRectangle(cornerRadius: Perch.cardRadius, style: .continuous)
                .fill(Perch.card)
                .overlay(RoundedRectangle(cornerRadius: Perch.cardRadius, style: .continuous).fill(Perch.sheen))
                .overlay(RoundedRectangle(cornerRadius: Perch.cardRadius, style: .continuous)
                    .strokeBorder(Perch.edge, lineWidth: 1))

            if store.pinned.isEmpty {
                VStack(spacing: 5) {
                    Image(systemName: "pin").font(.system(size: 20)).foregroundStyle(Perch.faint)
                    Text("Pin anything you paste often").font(.system(size: 11)).foregroundStyle(Perch.subtle)
                }
            } else {
                ScrollView {
                    LazyVGrid(columns: columns, spacing: 8) {
                        ForEach(store.pinned) { snippet in
                            pinnedCard(snippet)
                        }
                    }
                    .padding(9)
                    .padding(.bottom, 40)
                }
                .scrollIndicators(.hidden)
            }

            Button { newLabel = ""; newValue = ""; adding = true } label: {
                Image(systemName: "plus")
                    .font(.system(size: 16, weight: .bold)).foregroundStyle(Perch.text)
                    .frame(width: 42, height: 42)
                    .background(Circle().fill(Color(white: 0.16)))
                    .overlay(Circle().strokeBorder(PerchSettings.shared.accent.color.opacity(0.45), lineWidth: 1.5))
                    .shadow(color: .black.opacity(0.5), radius: 12, y: 4)
            }
            .buttonStyle(.plain)
            .padding(.bottom, 9)
        }
    }

    private func pinnedCard(_ snippet: PerchSnippet) -> some View {
        ZStack {
            VStack(alignment: .leading, spacing: 5) {
                HStack(spacing: 6) {
                    Image(systemName: snippet.symbol)
                        .font(.system(size: 10, weight: .semibold)).foregroundStyle(Perch.text)
                    Text(snippet.label)
                        .font(.system(size: 11, weight: .semibold)).foregroundStyle(Perch.text).lineLimit(1)
                    Spacer(minLength: 4)
                    Menu {
                        Button("Copy") { copy(snippet) }
                        Button("Edit") { editing = snippet }
                        Divider()
                        Button("Delete", role: .destructive) { store.delete(snippet) }
                    } label: {
                        Image(systemName: "ellipsis")
                            .font(.system(size: 10, weight: .semibold)).foregroundStyle(Perch.subtle)
                            .frame(width: 16, height: 16).contentShape(Rectangle())
                    }
                    .menuStyle(.borderlessButton).menuIndicator(.hidden).frame(width: 16)
                }
                Text(snippet.value)
                    .font(.system(size: 10, design: .monospaced))
                    .foregroundStyle(Perch.subtle).lineLimit(1)
            }
            .padding(9)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(RoundedRectangle(cornerRadius: Perch.innerRadius, style: .continuous).fill(Perch.inner))
            .overlay(RoundedRectangle(cornerRadius: Perch.innerRadius, style: .continuous).strokeBorder(Perch.edge, lineWidth: 1))
            .blur(radius: toastFor == snippet.id ? 3 : 0)
            .contentShape(Rectangle())
            .onTapGesture { copy(snippet) }

            if toastFor == snippet.id { PerchToast(text: "Copied") }
        }
        .help("Click to copy")
    }

    // MARK: History

    private var historyPane: some View {
        VStack(alignment: .leading, spacing: 7) {
            HStack {
                Text("CLIPBOARD")
                    .font(.system(size: 9, weight: .semibold)).tracking(0.7).foregroundStyle(Perch.faint)
                Spacer()
                if !store.history.isEmpty {
                    Button("Clear") { store.clearHistory() }
                        .buttonStyle(.plain)
                        .font(.system(size: 10)).foregroundStyle(Perch.subtle)
                }
            }
            .padding(.horizontal, 2)

            if store.history.isEmpty {
                VStack(spacing: 4) {
                    Image(systemName: "doc.on.clipboard").font(.system(size: 17)).foregroundStyle(Perch.faint)
                    Text("Copy something").font(.system(size: 10)).foregroundStyle(Perch.subtle)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                ScrollView {
                    VStack(spacing: 6) {
                        ForEach(store.history) { entry in
                            historyRow(entry)
                        }
                    }
                }
                .scrollIndicators(.hidden)
            }
        }
        .padding(10)
        .perchSurface()
    }

    private func historyRow(_ entry: PerchSnippet) -> some View {
        ZStack {
            HStack(spacing: 6) {
                Text(entry.value)
                    .font(.system(size: 11))
                    .foregroundStyle(Perch.text)
                    .lineLimit(1)
                    .frame(maxWidth: .infinity, alignment: .leading)
                Button { store.pin(entry) } label: {
                    Image(systemName: "pin")
                        .font(.system(size: 9, weight: .semibold)).foregroundStyle(Perch.subtle)
                        .frame(width: 18, height: 18).contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .help("Pin this")
            }
            .padding(.horizontal, 10).padding(.vertical, 8)
            .background(RoundedRectangle(cornerRadius: 12, style: .continuous).fill(Perch.inner))
            .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).strokeBorder(Perch.stroke, lineWidth: 1))
            .blur(radius: toastFor == entry.id ? 3 : 0)
            .contentShape(Rectangle())
            .onTapGesture { copy(entry) }

            if toastFor == entry.id { PerchToast(text: "Copied") }
        }
    }

    // MARK: Add sheet

    private var addSheet: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("New Snippet").font(.system(size: 15, weight: .bold)).foregroundStyle(Perch.text)
            field("Label", text: $newLabel, placeholder: "Home Address")
            field("Value", text: $newValue, placeholder: "20 Cooper Square, New York")
            HStack {
                Spacer()
                Button("Cancel") { adding = false }
                    .buttonStyle(.plain).foregroundStyle(Perch.subtle).font(.system(size: 12))
                Button("Add") {
                    let label = newLabel.trimmed.isEmpty
                        ? PerchSnippetsStore.autoLabel(newValue.trimmed) : newLabel.trimmed
                    store.add(label: label, value: newValue.trimmed)
                    adding = false
                }
                .buttonStyle(.plain)
                .font(.system(size: 12, weight: .semibold)).foregroundStyle(.black)
                .padding(.horizontal, 14).padding(.vertical, 7)
                .background(Capsule().fill(newValue.trimmed.isEmpty ? Color.white.opacity(0.3) : Color.white))
                .disabled(newValue.trimmed.isEmpty)
            }
        }
        .padding(18).frame(width: 380).background(Perch.bg)
    }

    private func field(_ label: String, text: Binding<String>, placeholder: String) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(label.uppercased())
                .font(.system(size: 9, weight: .semibold)).tracking(0.6).foregroundStyle(Perch.faint)
            TextField(placeholder, text: text)
                .textFieldStyle(.plain).font(.system(size: 12)).foregroundStyle(Perch.text)
                .padding(9)
                .background(RoundedRectangle(cornerRadius: 9, style: .continuous).fill(Perch.card))
                .overlay(RoundedRectangle(cornerRadius: 9, style: .continuous).strokeBorder(Perch.stroke))
        }
    }

    // MARK: Copy + toast

    private func copy(_ snippet: PerchSnippet) {
        store.copy(snippet)
        withAnimation(.spring(response: 0.24, dampingFraction: 0.8)) { toastFor = snippet.id }
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.1) {
            withAnimation(.easeOut(duration: 0.2)) {
                if toastFor == snippet.id { toastFor = nil }
            }
        }
    }
}

// MARK: - Editor

struct PerchSnippetEditor: View {
    @State var snippet: PerchSnippet
    var onSave: (PerchSnippet) -> Void
    var onCancel: () -> Void
    var onDelete: () -> Void

    private let symbols = ["doc.text", "house.fill", "person.crop.circle.fill", "creditcard.fill",
                           "envelope.fill", "phone.fill", "link", "number"]

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Snippet").font(.system(size: 15, weight: .bold)).foregroundStyle(Perch.text)

            TextField("Label", text: $snippet.label)
                .textFieldStyle(.plain).font(.system(size: 13, weight: .semibold)).foregroundStyle(Perch.text)
                .padding(9)
                .background(RoundedRectangle(cornerRadius: 9, style: .continuous).fill(Perch.card))
                .overlay(RoundedRectangle(cornerRadius: 9, style: .continuous).strokeBorder(Perch.stroke))

            TextField("Value", text: $snippet.value, axis: .vertical)
                .textFieldStyle(.plain).font(.system(size: 12, design: .monospaced))
                .foregroundStyle(Perch.text).lineLimit(2...6)
                .padding(9)
                .background(RoundedRectangle(cornerRadius: 9, style: .continuous).fill(Perch.card))
                .overlay(RoundedRectangle(cornerRadius: 9, style: .continuous).strokeBorder(Perch.stroke))

            HStack(spacing: 6) {
                ForEach(symbols, id: \.self) { symbol in
                    Button { snippet.symbol = symbol } label: {
                        Image(systemName: symbol)
                            .font(.system(size: 11)).foregroundStyle(Perch.text)
                            .frame(width: 28, height: 28)
                            .background(RoundedRectangle(cornerRadius: 7, style: .continuous)
                                .fill(snippet.symbol == symbol ? Color.white.opacity(0.2) : Perch.card))
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
                Button("Save") { onSave(snippet) }
                    .buttonStyle(.plain).font(.system(size: 12, weight: .semibold)).foregroundStyle(.black)
                    .padding(.horizontal, 14).padding(.vertical, 7)
                    .background(Capsule().fill(Color.white))
            }
        }
        .padding(18).frame(width: 400).background(Perch.bg)
    }
}
