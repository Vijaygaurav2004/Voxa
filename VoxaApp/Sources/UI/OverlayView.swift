import SwiftUI

/// Floating overlay window that shows during voice commands.
/// Features a Siri-style animated orb, waveform, and status strip.
struct OverlayView: View {
    @EnvironmentObject var state: VoxaState

    var body: some View {
        ZStack {
            if state.useNotchHalo {
                NotchHaloView()
            } else {
                classicBody
            }
        }
        .frame(width: state.overlayWidth, height: state.overlayHeight)
        .ignoresSafeArea()
        .opacity(state.isOverlayVisible ? 1 : 0)
        .scaleEffect(state.isOverlayVisible ? 1 : (state.useNotchHalo ? 0.95 : 0.68))
        .offset(y: state.isOverlayVisible ? 0 : (state.useNotchHalo ? -60 : 0))
        .animation(.spring(response: 0.22, dampingFraction: 0.75), value: state.isOverlayVisible)
    }

    @ViewBuilder
    private var classicBody: some View {
        ZStack {
            // — Glass pill background —
            RoundedRectangle(cornerRadius: 32, style: .continuous)
                .fill(.ultraThinMaterial)
                .overlay(
                    RoundedRectangle(cornerRadius: 32, style: .continuous)
                        .stroke(
                            LinearGradient(
                                colors: [.white.opacity(0.25), .white.opacity(0.05)],
                                startPoint: .topLeading,
                                endPoint: .bottomTrailing
                            ),
                            lineWidth: 1
                        )
                )
                .shadow(color: .black.opacity(0.22), radius: 30, y: 12)

            VStack(spacing: 0) {
                // — Siri orb —
                SiriOrbView(audioLevel: state.audioLevel, state: state.pipelineState)
                    .frame(width: 160, height: 160)
                    .padding(.top, 28)

                // — Waveform strip (listening only) —
                if state.pipelineState == .listening {
                    SiriWaveformStrip(level: state.audioLevel)
                        .frame(height: 36)
                        .padding(.horizontal, 32)
                        .transition(.opacity.combined(with: .scale(scale: 0.8)))
                }

                Spacer(minLength: 10)

                // — Live transcript (Siri-style) —
                // Shown in place of the status capsule to avoid duplication;
                // the capsule returns once the transcript is empty again.
                if !state.liveTranscript.isEmpty {
                    Text(state.liveTranscript)
                        .font(.system(size: 17, weight: .medium, design: .rounded))
                        .foregroundStyle(state.transcriptIsFinal ? .primary : .secondary)
                        .multilineTextAlignment(.center)
                        .lineLimit(3)
                        .truncationMode(.head)          // newest words always visible
                        .contentTransition(.interpolate)
                        .frame(maxWidth: 380)
                        .fixedSize(horizontal: false, vertical: true)
                        .transition(.opacity.combined(with: .move(edge: .bottom)))
                        .animation(.easeOut(duration: 0.18), value: state.liveTranscript)
                        .animation(.easeOut(duration: 0.25), value: state.transcriptIsFinal)
                        .padding(.horizontal, 24)
                        .padding(.bottom, 26)
                } else {
                    // — Status pill —
                    statusLabel
                        .padding(.bottom, 28)
                }
            }
        }
    }

    // MARK: - Status Label

    @ViewBuilder
    private var statusLabel: some View {
        HStack(spacing: 6) {
            // Colored dot
            Circle()
                .fill(state.stateColor)
                .frame(width: 7, height: 7)
                .shadow(color: state.stateColor, radius: 4)

            switch state.pipelineState {
            case .listening:
                OrbStateLabel(text: "Listening")
            case .transcribing:
                OrbStateLabel(text: "Transcribing")
            case .thinking:
                OrbStateLabel(text: "Thinking")
            case .executing:
                OrbStateLabel(text: "Executing")
            default:
                Text(state.statusMessage)
                    .font(.system(.caption, design: .rounded, weight: .semibold))
                    .foregroundStyle(.secondary)
            }
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 8)
        .background(
            Capsule()
                .fill(state.stateColor.opacity(0.12))
                .overlay(Capsule().stroke(state.stateColor.opacity(0.2), lineWidth: 1))
        )
    }
}

// MARK: - Siri Waveform Strip

/// A smooth, multi-bar waveform with color gradient — reacts to mic level in real-time.
struct SiriWaveformStrip: View {
    let level: Float

    private let barCount = 28
    @State private var heights: [CGFloat] = Array(repeating: 0.08, count: 28)
    @State private var basePhase: Double = 0
    let timer = Timer.publish(every: 0.04, on: .main, in: .common).autoconnect()

    var body: some View {
        HStack(spacing: 2.5) {
            ForEach(0..<barCount, id: \.self) { i in
                RoundedRectangle(cornerRadius: 2)
                    .fill(barGradient(for: i))
                    .frame(width: 3.5, height: max(4, heights[i] * 36))
                    .animation(.easeOut(duration: 0.06), value: heights[i])
            }
        }
        .onReceive(timer) { _ in
            basePhase += 0.22
            animateBars()
        }
    }

    private func animateBars() {
        let lvl = CGFloat(level)
        for i in 0..<barCount {
            let pos = Double(i) / Double(barCount)
            let wave = sin(basePhase + pos * .pi * 2.5) * 0.4
            let centre = 1.0 - abs(pos - 0.5) * 1.6
            let base = max(0.05, lvl * CGFloat(max(0, centre)) * 0.9)
            heights[i] = max(0.05, min(1.0, base + CGFloat(wave) * max(0.08, lvl)))
        }
    }

    private func barGradient(for index: Int) -> LinearGradient {
        let frac = CGFloat(index) / CGFloat(barCount)
        let top = Color(hue: 0.52 + frac * 0.18, saturation: 0.85, brightness: 0.95)
        let bot = Color(hue: 0.52 + frac * 0.18, saturation: 0.6, brightness: 0.75)
        return LinearGradient(colors: [top, bot], startPoint: .top, endPoint: .bottom)
    }
}
