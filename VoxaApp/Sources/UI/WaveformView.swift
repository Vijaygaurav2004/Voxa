import SwiftUI

/// Animated audio waveform visualization.
/// Shows real-time audio levels during voice recording.
struct WaveformView: View {
    let level: Float // 0.0 - 1.0

    private let barCount = 20
    @State private var animatedBars: [CGFloat] = Array(repeating: 0.1, count: 20)

    var body: some View {
        HStack(spacing: 2) {
            ForEach(0..<barCount, id: \.self) { i in
                RoundedRectangle(cornerRadius: 1.5)
                    .fill(barColor(for: i))
                    .frame(width: 3, height: animatedBars[i] * 40)
            }
        }
        .onChange(of: level) { _, newLevel in
            withAnimation(.easeOut(duration: 0.05)) {
                updateBars(level: newLevel)
            }
        }
    }

    private func updateBars(level: Float) {
        for i in 0..<barCount {
            // Create a natural waveform shape (higher in middle)
            let centerDistance = abs(CGFloat(i) - CGFloat(barCount) / 2) / CGFloat(barCount) * 2
            let baseHeight = max(0.05, CGFloat(level) * (1.0 - centerDistance * 0.6))
            let randomVariation = CGFloat.random(in: -0.1...0.1)
            animatedBars[i] = max(0.05, min(1.0, baseHeight + randomVariation))
        }
    }

    private func barColor(for index: Int) -> Color {
        let fraction = CGFloat(index) / CGFloat(barCount)
        return Color(
            hue: 0.5 + fraction * 0.15, // Cyan to blue gradient
            saturation: 0.7,
            brightness: 0.9
        )
    }
}
