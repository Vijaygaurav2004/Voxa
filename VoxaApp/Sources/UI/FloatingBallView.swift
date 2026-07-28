import SwiftUI
import AppKit

// MARK: - Chat Message Model

struct ChatMessage: Identifiable, Equatable {
    let id = UUID()
    let text: String
    let isUser: Bool
    let timestamp: Date = Date()

    static func == (lhs: ChatMessage, rhs: ChatMessage) -> Bool {
        lhs.id == rhs.id
    }
}

// MARK: - Floating Ball View

/// A draggable floating ball (like iPhone's AssistiveTouch) that expands into a chat panel.
struct FloatingBallView: View {
    @EnvironmentObject var engine: VoxaEngine
    @EnvironmentObject var state: VoxaState

    @State private var isChatOpen: Bool = false
    @State private var chatInput: String = ""
    @State private var messages: [ChatMessage] = []
    @State private var isProcessing: Bool = false
    @State private var ballScale: CGFloat = 1.0
    @State private var ballRotation: Double = 0

    // Ball pulse animation
    @State private var isPulsing: Bool = false

    // Header drag-to-move state
    @State private var isDraggingPanel: Bool = false

    var body: some View {
        ZStack(alignment: .bottomTrailing) {
            if isChatOpen {
                chatPanel
                    .transition(.asymmetric(
                        insertion: .scale(scale: 0.3, anchor: .bottomTrailing)
                            .combined(with: .opacity),
                        removal: .scale(scale: 0.3, anchor: .bottomTrailing)
                            .combined(with: .opacity)
                    ))
            }

            // The floating ball
            ballButton
        }
        .frame(
            width: isChatOpen ? 360 : 56,
            // Chat panel is 480 tall + 64 bottom padding (for the ball) = 544;
            // give it 560 so the header isn't clipped at the top.
            height: isChatOpen ? 560 : 56,
            alignment: .bottomTrailing
        )
        .animation(.spring(response: 0.4, dampingFraction: 0.8), value: isChatOpen)
        .onChange(of: isChatOpen) { open in
            // Resize the host NSPanel so the chat panel isn't clipped by the
            // collapsed 64×64 window.
            if open {
                // Grow first so the expanding chat has room.
                FloatingBallManager.shared.setChatOpen(true)
            } else {
                // Let the collapse transition play, then shrink the window.
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.28) {
                    if !isChatOpen {
                        FloatingBallManager.shared.setChatOpen(false)
                    }
                }
            }
        }
    }

    // MARK: - Ball Button

    var ballButton: some View {
        ZStack {
            // Outer glow ring
            Circle()
                .fill(
                    RadialGradient(
                        colors: [
                            Color.purple.opacity(isPulsing ? 0.4 : 0.15),
                            Color.clear
                        ],
                        center: .center,
                        startRadius: 20,
                        endRadius: 36
                    )
                )
                .frame(width: 56, height: 56)

            // Main ball
            Circle()
                .fill(
                    LinearGradient(
                        colors: [
                            Color(hue: 0.75, saturation: 0.7, brightness: 0.95),
                            Color(hue: 0.8, saturation: 0.8, brightness: 0.7),
                        ],
                        startPoint: .topLeading,
                        endPoint: .bottomTrailing
                    )
                )
                .frame(width: 44, height: 44)
                .shadow(color: .purple.opacity(0.5), radius: 8, x: 0, y: 4)

            // Icon
            Image(systemName: isChatOpen ? "xmark" : "message.fill")
                .font(.system(size: isChatOpen ? 14 : 16, weight: .semibold))
                .foregroundStyle(.white)
                .rotationEffect(.degrees(isChatOpen ? 90 : 0))
        }
        .scaleEffect(ballScale)
        .frame(width: 56, height: 56)
        .contentShape(Circle())
        .onTapGesture {
            withAnimation(.spring(response: 0.35, dampingFraction: 0.7)) {
                isChatOpen.toggle()
            }
        }
        .onAppear {
            // Subtle breathing pulse
            withAnimation(.easeInOut(duration: 2.0).repeatForever(autoreverses: true)) {
                isPulsing = true
            }
        }
        .onHover { hovering in
            withAnimation(.easeInOut(duration: 0.15)) {
                ballScale = hovering ? 1.1 : 1.0
            }
        }
    }

    // MARK: - Chat Panel

    var chatPanel: some View {
        VStack(spacing: 0) {
            // Header
            chatHeader

            Divider()
                .background(Color.white.opacity(0.1))

            // Messages area
            chatMessages

            Divider()
                .background(Color.white.opacity(0.1))

            // Input area
            chatInputArea
        }
        .frame(width: 350, height: 480)
        .background(
            RoundedRectangle(cornerRadius: 20)
                .fill(.ultraThinMaterial)
                .shadow(color: .black.opacity(0.3), radius: 20, x: 0, y: 10)
        )
        .clipShape(RoundedRectangle(cornerRadius: 20))
        .overlay(
            RoundedRectangle(cornerRadius: 20)
                .strokeBorder(
                    LinearGradient(
                        colors: [
                            Color.white.opacity(0.2),
                            Color.white.opacity(0.05),
                        ],
                        startPoint: .topLeading,
                        endPoint: .bottomTrailing
                    ),
                    lineWidth: 1
                )
        )
        .padding(.bottom, 64) // Space for the ball below
    }

    // MARK: - Chat Header

    var chatHeader: some View {
        HStack(spacing: 10) {
            // Voxa avatar
            ZStack {
                Circle()
                    .fill(
                        LinearGradient(
                            colors: [.purple, .blue],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        )
                    )
                    .frame(width: 32, height: 32)

                Image(systemName: "waveform.circle.fill")
                    .font(.system(size: 18))
                    .foregroundStyle(.white)
            }

            VStack(alignment: .leading, spacing: 1) {
                Text("Voxa")
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(.primary)

                HStack(spacing: 4) {
                    Circle()
                        .fill(state.isBackendReady ? Color.green : Color.red)
                        .frame(width: 6, height: 6)
                    Text(state.isBackendReady ? "Online" : "Offline")
                        .font(.system(size: 10))
                        .foregroundStyle(.secondary)
                }
            }

            Spacer()

            // Clear chat
            Button {
                withAnimation {
                    messages.removeAll()
                }
            } label: {
                Image(systemName: "trash")
                    .font(.system(size: 12))
                    .foregroundStyle(.secondary)
                    .padding(6)
                    .background(Circle().fill(Color.primary.opacity(0.05)))
            }
            .buttonStyle(.plain)
            .help("Clear chat")
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 12)
        .contentShape(Rectangle())
        .gesture(headerDragGesture)
        .onHover { hovering in
            // Signal that the header is a move handle.
            if hovering { NSCursor.openHand.push() } else { NSCursor.pop() }
        }
        .help("Drag to move")
    }

    /// Drag the whole chat panel by its header, like a window title bar.
    private var headerDragGesture: some Gesture {
        DragGesture(minimumDistance: 2)
            .onChanged { _ in
                if !isDraggingPanel {
                    isDraggingPanel = true
                    FloatingBallManager.shared.beginPanelDrag()
                }
                FloatingBallManager.shared.updatePanelDrag()
            }
            .onEnded { _ in
                isDraggingPanel = false
                FloatingBallManager.shared.endPanelDrag()
            }
    }

    // MARK: - Chat Messages

    var chatMessages: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(spacing: 12) {
                    if messages.isEmpty {
                        emptyState
                    }

                    ForEach(messages) { message in
                        messageBubble(message)
                            .id(message.id)
                    }

                    if isProcessing {
                        typingIndicator
                    }
                }
                .padding(.horizontal, 12)
                .padding(.vertical, 8)
            }
            .onChange(of: messages.count) { _ in
                if let last = messages.last {
                    withAnimation {
                        proxy.scrollTo(last.id, anchor: .bottom)
                    }
                }
            }
        }
    }

    // MARK: - Empty State

    var emptyState: some View {
        VStack(spacing: 12) {
            Spacer()

            Image(systemName: "bubble.left.and.bubble.right")
                .font(.system(size: 36))
                .foregroundStyle(
                    LinearGradient(
                        colors: [.purple.opacity(0.5), .blue.opacity(0.5)],
                        startPoint: .topLeading,
                        endPoint: .bottomTrailing
                    )
                )

            Text("Chat with Voxa")
                .font(.system(size: 14, weight: .medium))
                .foregroundStyle(.secondary)

            Text("Type a command or ask anything")
                .font(.system(size: 11))
                .foregroundStyle(.tertiary)

            Spacer()
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 40)
    }

    // MARK: - Message Bubble

    func messageBubble(_ message: ChatMessage) -> some View {
        HStack {
            if message.isUser { Spacer(minLength: 50) }

            VStack(alignment: message.isUser ? .trailing : .leading, spacing: 4) {
                Text(message.text)
                    .font(.system(size: 13))
                    .foregroundStyle(message.isUser ? .white : .primary)
                    .textSelection(.enabled)
                    .padding(.horizontal, 14)
                    .padding(.vertical, 10)
                    .background(
                        Group {
                            if message.isUser {
                                LinearGradient(
                                    colors: [
                                        Color(hue: 0.75, saturation: 0.6, brightness: 0.85),
                                        Color(hue: 0.7, saturation: 0.7, brightness: 0.7),
                                    ],
                                    startPoint: .topLeading,
                                    endPoint: .bottomTrailing
                                )
                            } else {
                                Color.primary.opacity(0.06)
                            }
                        }
                    )
                    .clipShape(
                        RoundedRectangle(
                            cornerRadius: 16,
                            style: .continuous
                        )
                    )

                Text(formatTime(message.timestamp))
                    .font(.system(size: 9))
                    .foregroundStyle(.tertiary)
                    .padding(.horizontal, 4)
            }

            if !message.isUser { Spacer(minLength: 50) }
        }
    }

    // MARK: - Typing Indicator

    var typingIndicator: some View {
        HStack {
            HStack(spacing: 4) {
                ForEach(0..<3) { i in
                    Circle()
                        .fill(Color.secondary)
                        .frame(width: 6, height: 6)
                        .scaleEffect(isProcessing ? 1.0 : 0.5)
                        .animation(
                            .easeInOut(duration: 0.6)
                                .repeatForever(autoreverses: true)
                                .delay(Double(i) * 0.15),
                            value: isProcessing
                        )
                }
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 12)
            .background(Color.primary.opacity(0.06))
            .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))

            Spacer()
        }
    }

    // MARK: - Input Area

    var chatInputArea: some View {
        HStack(spacing: 8) {
            TextField("Type a message...", text: $chatInput)
                .textFieldStyle(.plain)
                .font(.system(size: 13))
                .padding(.horizontal, 14)
                .padding(.vertical, 10)
                .background(
                    RoundedRectangle(cornerRadius: 20, style: .continuous)
                        .fill(Color.primary.opacity(0.05))
                )
                .onSubmit {
                    sendMessage()
                }

            // Send button
            Button {
                sendMessage()
            } label: {
                ZStack {
                    Circle()
                        .fill(sendButtonFill)
                        .frame(width: 32, height: 32)

                    Image(systemName: "arrow.up")
                        .font(.system(size: 14, weight: .bold))
                        .foregroundStyle(.white)
                }
            }
            .buttonStyle(.plain)
            .disabled(chatInput.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || isProcessing)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 10)
    }

    // MARK: - Computed Helpers

    private var sendButtonFill: AnyShapeStyle {
        if chatInput.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || isProcessing {
            return AnyShapeStyle(Color.gray.opacity(0.3))
        } else {
            return AnyShapeStyle(
                LinearGradient(
                    colors: [.purple, .blue],
                    startPoint: .topLeading,
                    endPoint: .bottomTrailing
                )
            )
        }
    }

    // MARK: - Actions

    private func sendMessage() {
        let text = chatInput.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, !isProcessing else { return }

        // Add user message
        let userMsg = ChatMessage(text: text, isUser: true)
        messages.append(userMsg)
        chatInput = ""
        isProcessing = true

        // Process through Voxa engine
        Task {
            do {
                let contextResponse = try await PythonBridge.shared.getContext()
                let intentResponse = try await PythonBridge.shared.parseIntent(
                    text: text,
                    context: contextResponse.contextText
                )
                let plan = intentResponse.plan

                // Execute the plan
                let results = await ActionRouter.shared.executePlan(plan)
                let successCount = results.filter(\.success).count

                // Build response
                var responseText = plan.confirmation
                if !results.isEmpty {
                    let resultMessages = results.compactMap { r -> String? in
                        if let msg = r.message, !msg.isEmpty {
                            return msg
                        }
                        return nil
                    }
                    if !resultMessages.isEmpty {
                        responseText += "\n" + resultMessages.joined(separator: "\n")
                    }
                }

                let botMsg = ChatMessage(text: responseText, isUser: false)
                await MainActor.run {
                    messages.append(botMsg)
                    isProcessing = false
                    state.addCommand(text)
                }
            } catch {
                let errorMsg = ChatMessage(
                    text: "Sorry, I couldn't process that: \(error.localizedDescription)",
                    isUser: false
                )
                await MainActor.run {
                    messages.append(errorMsg)
                    isProcessing = false
                }
            }
        }
    }

    private static let timeFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.dateFormat = "h:mm a"
        return formatter
    }()

    private func formatTime(_ date: Date) -> String {
        return Self.timeFormatter.string(from: date)
    }
}
