import SwiftUI

/// Small animated status indicator dot.
struct StatusIndicator: View {
    @EnvironmentObject var state: VoxaState

    var body: some View {
        HStack(spacing: 4) {
            Circle()
                .fill(state.stateColor)
                .frame(width: 8, height: 8)
                .overlay(
                    Circle()
                        .stroke(state.stateColor.opacity(0.3), lineWidth: 2)
                        .scaleEffect(state.pipelineState != .idle ? 2.0 : 1.0)
                        .opacity(state.pipelineState != .idle ? 0.0 : 0.3)
                        .animation(
                            .easeOut(duration: 1.0).repeatForever(autoreverses: false),
                            value: state.pipelineState
                        )
                )

            Text(state.pipelineState.rawValue.capitalized)
                .font(.caption2)
                .foregroundStyle(.secondary)
        }
    }
}
