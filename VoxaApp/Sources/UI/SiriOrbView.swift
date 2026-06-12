import SwiftUI

// MARK: - Siri-style Orb Animation

/// A flowing, multi-color animated orb that pulses and reacts to audio,
/// mimicking Apple's Siri activation animation.
struct SiriOrbView: View {
    let audioLevel: Float      // 0.0 – 1.0 live mic level
    let state: VoxaState.PipelineState

    // Phase drivers — start at random offsets so orb is pre-warmed when panel appears
    @State private var phase1: Double = Double.random(in: 0...(2 * .pi))
    @State private var phase2: Double = Double.random(in: 0...(2 * .pi))
    @State private var phase3: Double = Double.random(in: 0...(2 * .pi))
    @State private var ripple:  Double = Double.random(in: 0...1)
    @State private var glow:    Double = Double.random(in: 0...1)

    private var isActive: Bool {
        state == .listening || state == .transcribing || state == .thinking || state == .executing
    }

    var body: some View {
        ZStack {
            // — Outer ripple rings —
            ForEach(0..<3) { i in
                Circle()
                    .stroke(ringColor(for: i).opacity(0.25 - Double(i) * 0.07), lineWidth: 1.5)
                    .frame(width: orbSize + CGFloat(i + 1) * 22, height: orbSize + CGFloat(i + 1) * 22)
                    .scaleEffect(isActive ? 1 + CGFloat(i) * 0.04 + CGFloat(ripple) * 0.06 : 0.85)
                    .animation(
                        .easeInOut(duration: 1.6 + Double(i) * 0.4)
                        .repeatForever(autoreverses: true)
                        .delay(Double(i) * 0.3),
                        value: ripple
                    )
            }

            // — Core orb made of layered blobs —
            ZStack {
                blob(phase: phase1, colors: [.cyan, .blue], scale: 0.92 + CGFloat(audioLevel) * 0.12)
                blob(phase: phase2, colors: [.purple, .indigo], scale: 0.85 + CGFloat(audioLevel) * 0.10)
                blob(phase: phase3, colors: [.teal, .mint],  scale: 0.78 + CGFloat(audioLevel) * 0.08)
            }
            .frame(width: orbSize, height: orbSize)
            .clipShape(Circle())
            .overlay(
                Circle()
                    .fill(
                        RadialGradient(
                            colors: [.white.opacity(0.35), .clear],
                            center: .init(x: 0.35, y: 0.28),
                            startRadius: 0,
                            endRadius: orbSize * 0.55
                        )
                    )
            )
            .shadow(color: glowColor.opacity(0.55 + glow * 0.25), radius: 22 + glow * 10)
            .scaleEffect(isActive ? 1.0 + CGFloat(audioLevel) * 0.14 : 0.72)
            .animation(.spring(response: 0.18, dampingFraction: 0.55), value: audioLevel)
            .animation(.spring(response: 0.4, dampingFraction: 0.7), value: isActive)
        }
        .onAppear {
            withAnimation(.linear(duration: 6).repeatForever(autoreverses: false)) { phase1 = .pi * 2 }
            withAnimation(.linear(duration: 8).repeatForever(autoreverses: false)) { phase2 = .pi * 2 + 2.0 }
            withAnimation(.linear(duration: 10).repeatForever(autoreverses: false)) { phase3 = .pi * 2 + 4.0 }
            withAnimation(.easeInOut(duration: 1.4).repeatForever(autoreverses: true)) { ripple = 1 }
            withAnimation(.easeInOut(duration: 2.0).repeatForever(autoreverses: true)) { glow = 1 }
        }
    }

    // MARK: - Helpers

    private var orbSize: CGFloat { 110 }

    private var glowColor: Color {
        switch state {
        case .listening:    return .cyan
        case .transcribing: return .blue
        case .thinking:     return .purple
        case .executing:    return .green
        case .done:         return .mint
        case .error:        return .red
        default:            return .indigo
        }
    }

    private func ringColor(for index: Int) -> Color {
        [Color.cyan, Color.purple, Color.blue][index % 3]
    }

    /// One animated blob layer
    @ViewBuilder
    private func blob(phase: Double, colors: [Color], scale: CGFloat) -> some View {
        Ellipse()
            .fill(
                LinearGradient(
                    colors: colors.map { $0.opacity(0.75) },
                    startPoint: UnitPoint(
                        x: 0.5 + 0.5 * cos(phase),
                        y: 0.5 + 0.5 * sin(phase)
                    ),
                    endPoint: UnitPoint(
                        x: 0.5 - 0.5 * cos(phase),
                        y: 0.5 - 0.5 * sin(phase)
                    )
                )
            )
            .scaleEffect(x: scale, y: scale * (0.88 + 0.12 * abs(sin(phase * 1.3))))
            .rotationEffect(.radians(phase * 0.4))
            .blendMode(.plusLighter)
    }
}

// MARK: - State Label Strip

/// Animated label shown beneath the orb (e.g. "Listening…", "Thinking…")
struct OrbStateLabel: View {
    let text: String
    @State private var dotCount = 0
    let timer = Timer.publish(every: 0.4, on: .main, in: .common).autoconnect()

    var body: some View {
        HStack(spacing: 2) {
            Text(text)
            Text(String(repeating: ".", count: dotCount))
                .frame(width: 18, alignment: .leading)
        }
        .font(.system(.caption, design: .rounded, weight: .semibold))
        .foregroundStyle(.secondary)
        .onReceive(timer) { _ in
            dotCount = (dotCount + 1) % 4
        }
    }
}
