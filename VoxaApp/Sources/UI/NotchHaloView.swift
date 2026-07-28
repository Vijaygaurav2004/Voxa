import SwiftUI

/// A sleek, futuristic notch-hugging halo/orb visualizer for Voxa.
/// It appears at the top center of the screen, wrapping around/below the MacBook camera notch.
struct NotchHaloView: View {
    @EnvironmentObject var state: VoxaState

    @State private var phase1: Double = Double.random(in: 0...(2 * .pi))
    @State private var phase2: Double = Double.random(in: 0...(2 * .pi))
    @State private var phase3: Double = Double.random(in: 0...(2 * .pi))
    @State private var glowPhase: Double = 0
    @State private var rotatePhase: Double = 0

    // The padding around the notch
    private let notchPadding: CGFloat = 4
    // Corner radius of the notch halo
    private let haloCornerRadius: CGFloat = 11

    private var notchWidth: CGFloat {
        state.notchRect?.width ?? 180
    }

    private var notchHeight: CGFloat {
        state.notchRect?.height ?? 32
    }

    private var haloWidth: CGFloat {
        notchWidth + 2 * notchPadding
    }

    private var haloHeight: CGFloat {
        2 * (notchHeight + notchPadding)
    }

    private var haloOffset: CGFloat {
        -(notchHeight + notchPadding)
    }

    private var isActive: Bool {
        state.pipelineState != .idle
    }

    var body: some View {
        ZStack(alignment: .top) {
            // Layer 1: Ambient Background Glow (Layered Siri-style Animated Blobs)
            ZStack {
                // Left blob
                blob(phase: phase1, colors: blobColors(for: 0), scale: isActive ? 1.0 + CGFloat(state.audioLevel) * 0.45 : 0.7)
                    .frame(width: notchWidth * 0.75, height: notchHeight * 1.8)
                    .offset(x: -notchWidth * 0.2, y: -notchHeight * 0.9)
                
                // Right blob
                blob(phase: phase2, colors: blobColors(for: 1), scale: isActive ? 1.0 + CGFloat(state.audioLevel) * 0.4 : 0.65)
                    .frame(width: notchWidth * 0.75, height: notchHeight * 1.8)
                    .offset(x: notchWidth * 0.2, y: -notchHeight * 0.9)
                
                // Central blob
                blob(phase: phase3, colors: blobColors(for: 2), scale: isActive ? 1.1 + CGFloat(state.audioLevel) * 0.5 : 0.75)
                    .frame(width: notchWidth * 0.65, height: notchHeight * 1.5)
                    .offset(y: -notchHeight * 0.8)
            }
            .blur(radius: 20)
            .blendMode(.plusLighter)
            .opacity(isActive ? 0.85 + sin(glowPhase) * 0.12 : 0.3)

            // Layer 2: Moving gradient light trail wrapping the notch border
            // Top half is tucked off-screen, bottom half outlines the notch (y = 0 to notchHeight + notchPadding)
            RoundedRectangle(cornerRadius: haloCornerRadius, style: .continuous)
                .stroke(
                    AngularGradient(
                        colors: [state.stateColor, state.stateColor.opacity(0.1), state.stateColor, state.stateColor.opacity(0.1), state.stateColor],
                        center: .center,
                        angle: .radians(rotatePhase)
                    ),
                    lineWidth: isActive ? 3.0 : 1.5
                )
                .frame(width: haloWidth, height: haloHeight)
                .offset(y: haloOffset)
                .shadow(color: state.stateColor.opacity(isActive ? 0.9 : 0.2), radius: isActive ? 12 : 3, y: 2)
                .animation(.spring(response: 0.25, dampingFraction: 0.6), value: isActive)

            // Layer 3: Secondary colored accent line for high-contrast neon look
            RoundedRectangle(cornerRadius: haloCornerRadius, style: .continuous)
                .stroke(
                    LinearGradient(
                        colors: [
                            state.stateColor,
                            state.stateColor.opacity(0.4),
                            state.stateColor
                        ],
                        startPoint: .leading,
                        endPoint: .trailing
                    ),
                    lineWidth: 1
                )
                .frame(width: haloWidth, height: haloHeight)
                .offset(y: haloOffset)
                .opacity(isActive ? 0.9 : 0.3)
                
            // Optional Listening state: tiny vertical waveforms on the sides of the notch
            if state.pipelineState == .listening {
                HStack(spacing: haloWidth + 12) { // Sits on left and right edges of the notch
                    miniAudioBar(index: 0)
                    miniAudioBar(index: 1)
                }
                .offset(y: notchHeight / 2)
            }

            // — State Label & Status message below the notch —
            VStack(spacing: 2) {
                HStack(spacing: 6) {
                    Circle()
                        .fill(state.stateColor)
                        .frame(width: 6, height: 6)
                        .shadow(color: state.stateColor, radius: 3)
                        .opacity(isActive ? 1 : 0.5)

                    Text(state.statusMessage)
                        .font(.system(.subheadline, design: .rounded, weight: .bold))
                        .foregroundStyle(state.stateColor)
                        .shadow(color: state.stateColor.opacity(isActive ? 0.4 : 0.05), radius: 6)
                }

                if !state.liveTranscript.isEmpty {
                    // Live transcript replaces the "Speak now" caption.
                    Text(state.liveTranscript)
                        .font(.system(size: 14, weight: .medium, design: .rounded))
                        .foregroundStyle(state.transcriptIsFinal ? .primary : .secondary)
                        .multilineTextAlignment(.center)
                        .lineLimit(2)
                        .truncationMode(.head)          // newest words always visible
                        .contentTransition(.interpolate)
                        .frame(maxWidth: min(500, state.overlayWidth - 40))
                        .fixedSize(horizontal: false, vertical: true)
                        .transition(.opacity.combined(with: .move(edge: .bottom)))
                        .animation(.easeOut(duration: 0.18), value: state.liveTranscript)
                        .animation(.easeOut(duration: 0.25), value: state.transcriptIsFinal)
                } else if state.pipelineState == .listening {
                    Text("Speak now")
                        .font(.system(.caption2, design: .rounded, weight: .semibold))
                        .foregroundStyle(.secondary)
                        .opacity(0.7)
                        .transition(.opacity)
                }
            }
            .offset(y: notchHeight + notchPadding + 12)
        }
        .frame(width: state.overlayWidth, height: state.overlayHeight)
        .ignoresSafeArea()
        .onAppear {
            // Animate phase drivers for ambient flow
            withAnimation(.linear(duration: 4.5).repeatForever(autoreverses: false)) {
                rotatePhase = 2 * .pi
            }
            withAnimation(.easeInOut(duration: 1.8).repeatForever(autoreverses: true)) {
                glowPhase = .pi
            }
            withAnimation(.linear(duration: 5.5).repeatForever(autoreverses: false)) { phase1 = .pi * 2 }
            withAnimation(.linear(duration: 7.0).repeatForever(autoreverses: false)) { phase2 = .pi * 2 + 1.5 }
            withAnimation(.linear(duration: 8.5).repeatForever(autoreverses: false)) { phase3 = .pi * 2 + 3.0 }
        }
    }

    @ViewBuilder
    private func blob(phase: Double, colors: [Color], scale: CGFloat) -> some View {
        Ellipse()
            .fill(
                LinearGradient(
                    colors: colors.map { $0.opacity(0.8) },
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
            .scaleEffect(x: scale, y: scale * (0.85 + 0.15 * abs(sin(phase * 1.25))))
            .rotationEffect(.radians(phase * 0.35))
            .blendMode(.plusLighter)
    }

    private func blobColors(for index: Int) -> [Color] {
        switch state.pipelineState {
        case .listening:
            return index == 0 ? [.cyan, .blue] : (index == 1 ? [.teal, .cyan] : [.blue, .purple])
        case .transcribing:
            return index == 0 ? [.blue, .indigo] : (index == 1 ? [.purple, .blue] : [.cyan, .indigo])
        case .thinking:
            return index == 0 ? [.yellow, .orange] : (index == 1 ? [.orange, .red] : [.yellow, .pink])
        case .executing, .done:
            return index == 0 ? [.green, .mint] : (index == 1 ? [.teal, .green] : [.mint, .cyan])
        case .error:
            return index == 0 ? [.red, .orange] : (index == 1 ? [.pink, .red] : [.purple, .red])
        default:
            return index == 0 ? [.indigo, .purple] : (index == 1 ? [.blue, .indigo] : [.purple, .pink])
        }
    }

    @ViewBuilder
    private func miniAudioBar(index: Int) -> some View {
        HStack(spacing: 2) {
            ForEach(0..<3) { i in
                RoundedRectangle(cornerRadius: 1)
                    .fill(state.stateColor)
                    .frame(
                        width: 2.5,
                        height: 6 + CGFloat(state.audioLevel) * CGFloat.random(in: 8...22)
                    )
            }
        }
    }
}
