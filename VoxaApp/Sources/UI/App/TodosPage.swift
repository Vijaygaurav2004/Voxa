import SwiftUI

/// The running to-do list Voxa builds by listening — meetings and ordinary
/// conversation both feed it, and anything here can be pushed to Reminders.
struct TodosPage: View {
    @State private var todos: [PythonBridge.TodoRecord] = []
    @State private var loading = false
    @State private var error: String?
    @State private var status: String?
    @State private var newTask = ""
    @State private var showDone = false

    private var open: [PythonBridge.TodoRecord] { todos.filter { !$0.done } }
    private var done: [PythonBridge.TodoRecord] { todos.filter { $0.done } }

    var body: some View {
        Page(title: "To-dos",
             subtitle: "Captured from your meetings and conversations as they happen") {

            composer

            if let error { banner(error, tint: .red) }
            if let status { banner(status, tint: .primary) }

            HStack {
                SectionLabel(text: "\(open.count) open")
                Spacer()
                if !done.isEmpty {
                    Button(showDone ? "Hide done (\(done.count))" : "Show done (\(done.count))") {
                        showDone.toggle()
                    }
                    .buttonStyle(.plain)
                    .font(.system(size: 12)).foregroundStyle(Theme.subtle)
                }
                Button { exportReminders() } label: {
                    Label("Send to Reminders", systemImage: "square.and.arrow.up")
                        .font(.system(size: 12))
                }
                .buttonStyle(.plain).foregroundStyle(Theme.text)
                .disabled(open.isEmpty)
            }

            if todos.isEmpty && !loading {
                emptyState
            } else {
                VStack(spacing: 8) {
                    ForEach(open) { row($0) }
                }
                if showDone && !done.isEmpty {
                    HStack {
                        SectionLabel(text: "Completed")
                        Spacer()
                        Button("Clear") { clearCompleted() }
                            .buttonStyle(.plain).font(.system(size: 12)).foregroundStyle(Theme.subtle)
                    }
                    .padding(.top, 6)
                    VStack(spacing: 8) {
                        ForEach(done) { row($0) }
                    }
                }
            }
        }
        .onAppear(perform: load)
    }

    // MARK: Pieces

    private var composer: some View {
        HStack(spacing: 8) {
            TextField("Add something yourself…", text: $newTask)
                .textFieldStyle(.plain).font(.system(size: 13))
                .padding(.horizontal, 12).padding(.vertical, 10)
                .background(RoundedRectangle(cornerRadius: Theme.radiusSmall).fill(Theme.card))
                .overlay(RoundedRectangle(cornerRadius: Theme.radiusSmall).strokeBorder(Theme.stroke))
                .onSubmit(add)
            Button(action: add) {
                Image(systemName: "plus")
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(Color(NSColor.windowBackgroundColor))
                    .frame(width: 44, height: 40)
                    .background(RoundedRectangle(cornerRadius: Theme.radiusSmall)
                        .fill(newTask.trimmed.isEmpty ? Theme.card : Color.primary))
            }
            .buttonStyle(.plain).disabled(newTask.trimmed.isEmpty)
        }
    }

    private func row(_ todo: PythonBridge.TodoRecord) -> some View {
        Card(padding: 12) {
            HStack(alignment: .top, spacing: 12) {
                Button { toggle(todo) } label: {
                    Image(systemName: todo.done ? "checkmark.circle.fill" : "circle")
                        .font(.system(size: 17))
                        .foregroundStyle(todo.done ? Theme.text : Theme.faint)
                }
                .buttonStyle(.plain)

                VStack(alignment: .leading, spacing: 4) {
                    Text(todo.task)
                        .font(.system(size: 13, weight: .medium))
                        .strikethrough(todo.done, color: Theme.subtle)
                        .foregroundStyle(todo.done ? Theme.subtle : Theme.text)

                    HStack(spacing: 6) {
                        chip(sourceLabel(todo.source), icon: sourceIcon(todo.source))
                        if !todo.owner.isEmpty, todo.owner.lowercased() != "me" {
                            chip(todo.owner, icon: "person")
                        }
                        if !todo.due.isEmpty { chip(todo.due, icon: "clock") }
                        if todo.exported { chip("In Reminders", icon: "checkmark.seal") }
                    }

                    if !todo.context.isEmpty {
                        Text(todo.context)
                            .font(.system(size: 11)).foregroundStyle(Theme.faint)
                            .lineLimit(2)
                    }
                }

                Spacer(minLength: 6)

                Button { remove(todo) } label: {
                    Image(systemName: "trash").font(.system(size: 12))
                        .foregroundStyle(Theme.subtle)
                        .frame(width: 26, height: 26).background(Circle().fill(Theme.card))
                }
                .buttonStyle(.plain)
            }
        }
    }

    private func chip(_ text: String, icon: String) -> some View {
        HStack(spacing: 3) {
            Image(systemName: icon).font(.system(size: 9))
            Text(text).font(.system(size: 10, weight: .medium))
        }
        .foregroundStyle(Theme.subtle)
        .padding(.horizontal, 6).padding(.vertical, 2)
        .background(Capsule().fill(Theme.card))
    }

    private func sourceLabel(_ source: String) -> String {
        switch source {
        case "meeting":      return "Meeting"
        case "conversation": return "Overheard"
        default:             return "Added by you"
        }
    }

    private func sourceIcon(_ source: String) -> String {
        switch source {
        case "meeting":      return "person.2"
        case "conversation": return "waveform"
        default:             return "hand.point.up.left"
        }
    }

    private var emptyState: some View {
        VStack(spacing: 10) {
            Image(systemName: "checklist").font(.system(size: 34)).foregroundStyle(Theme.faint)
            Text("Nothing on your list").font(.system(size: 15, weight: .medium))
            Text("Turn on Memory or record a meeting and Voxa will add commitments here as it hears them — “I'll send the deck tonight”.")
                .font(.system(size: 12)).foregroundStyle(Theme.subtle)
                .multilineTextAlignment(.center).frame(maxWidth: 360)
        }
        .frame(maxWidth: .infinity).padding(.vertical, 46)
    }

    private func banner(_ text: String, tint: Color) -> some View {
        Text(text).font(.system(size: 12)).foregroundStyle(tint)
            .padding(10).frame(maxWidth: .infinity, alignment: .leading)
            .background(RoundedRectangle(cornerRadius: 8).fill(tint.opacity(0.1)))
    }

    // MARK: Actions

    private func load() {
        loading = true
        Task {
            do { todos = try await PythonBridge.shared.getTodos() ; error = nil }
            catch { self.error = "Couldn't load your to-dos." }
            loading = false
        }
    }

    private func add() {
        let task = newTask.trimmed
        guard !task.isEmpty else { return }
        newTask = ""
        Task {
            do {
                let res = try await PythonBridge.shared.addTodo(task: task)
                if !res.success { status = res.message ?? "Already on your list." }
                load()
            } catch { self.error = "Couldn't add that." }
        }
    }

    private func toggle(_ todo: PythonBridge.TodoRecord) {
        Task {
            _ = try? await PythonBridge.shared.setTodoDone(id: todo.id, done: !todo.done)
            load()
        }
    }

    private func remove(_ todo: PythonBridge.TodoRecord) {
        Task {
            _ = try? await PythonBridge.shared.deleteTodo(id: todo.id)
            load()
        }
    }

    private func clearCompleted() {
        Task {
            _ = try? await PythonBridge.shared.clearCompletedTodos()
            load()
        }
    }

    private func exportReminders() {
        status = nil; error = nil
        Task {
            do {
                let res = try await PythonBridge.shared.exportTodosToReminders()
                status = res.message
                load()
            } catch { self.error = "Couldn't reach the Reminders app." }
        }
    }
}
