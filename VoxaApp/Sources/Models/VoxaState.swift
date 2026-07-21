import Foundation
import SwiftUI
import Combine
import AppKit

/// Observable app state for the entire Voxa application.
@MainActor
final class VoxaState: ObservableObject {
    static let shared = VoxaState()

    /// Current pipeline state.
    enum PipelineState: String {
        case idle
        case listening
        case transcribing
        case thinking
        case executing
        case done
        case error
    }

    @Published var pipelineState: PipelineState = .idle
    @Published var statusMessage: String = "Ready"
    @Published var isBackendReady: Bool = false
    @Published var lastCommand: String? = nil
    @Published var lastPlan: ActionPlan? = nil
    @Published var isOverlayVisible: Bool = false
    @Published var useNotchHalo: Bool = UserDefaults.standard.bool(forKey: "useNotchHalo") {
        didSet {
            UserDefaults.standard.set(useNotchHalo, forKey: "useNotchHalo")
            NotificationCenter.default.post(name: .voxaStateChanged, object: nil)
        }
    }
    @Published var notchRect: NSRect? = nil

    var overlayWidth: CGFloat {
        if useNotchHalo {
            let notchW = notchRect?.width ?? 180
            return notchW + 180
        } else {
            return 260
        }
    }

    var overlayHeight: CGFloat {
        if useNotchHalo {
            let notchH = notchRect?.height ?? 32
            return notchH + 120
        } else {
            return 280
        }
    }

    // Audio levels for waveform visualization
    @Published var audioLevel: Float = 0.0

    // History
    @Published var recentCommands: [String] = []

    /// The SF Symbol name for the menu bar icon, changes with state.
    var menuBarIcon: String {
        switch pipelineState {
        case .idle:         return "waveform.circle"
        case .listening:    return "mic.fill"
        case .transcribing: return "text.bubble"
        case .thinking:     return "brain"
        case .executing:    return "play.circle.fill"
        case .done:         return "checkmark.circle.fill"
        case .error:        return "exclamationmark.triangle.fill"
        }
    }

    /// Color for the current state.
    var stateColor: Color {
        switch pipelineState {
        case .idle:         return .secondary
        case .listening:    return .cyan
        case .transcribing: return .blue
        case .thinking:     return .yellow
        case .executing:    return .green
        case .done:         return .green
        case .error:        return .red
        }
    }

    func setState(_ state: PipelineState, message: String? = nil) {
        withAnimation(.easeInOut(duration: 0.2)) {
            self.pipelineState = state
            if let message = message {
                self.statusMessage = message
            } else {
                switch state {
                case .idle:         statusMessage = "Ready"
                case .listening:    statusMessage = "Listening..."
                case .transcribing: statusMessage = "Transcribing..."
                case .thinking:     statusMessage = "Understanding..."
                case .executing:    statusMessage = "Executing..."
                case .done:         statusMessage = "Done!"
                case .error:        statusMessage = "Error"
                }
            }

            // Show overlay for active states
            isOverlayVisible = (state != .idle)
        }

        // Notify the floating orb panel
        NotificationCenter.default.post(name: .voxaStateChanged, object: nil)

        // Auto-dismiss done/error after delay
        if state == .done || state == .error {
            Task {
                try? await Task.sleep(nanoseconds: 2_500_000_000) // 2.5s
                if self.pipelineState == state {
                    self.setState(.idle)
                }
            }
        }
    }

    func addCommand(_ command: String) {
        lastCommand = command
        recentCommands.insert(command, at: 0)
        if recentCommands.count > 20 {
            recentCommands.removeLast()
        }
    }

    private init() {
        // Default to true for Notch Halo on first launch
        UserDefaults.standard.register(defaults: ["useNotchHalo": true])
    }
}

extension NSScreen {
    /// Returns the rect of the hardware notch (sensor housing) in screen coordinates.
    /// If there is no hardware notch or the OS version is < macOS 12, returns nil.
    var notchRect: NSRect? {
        guard #available(macOS 12.0, *) else { return nil }
        
        // When a notch is present, auxiliaryTopLeftArea and auxiliaryTopRightArea are non-nil.
        guard let topLeft = auxiliaryTopLeftArea,
              let topRight = auxiliaryTopRightArea else {
            return nil
        }
        
        // The notch is in the middle space between these two areas.
        let x = topLeft.maxX
        let width = topRight.minX - topLeft.maxX
        let height = safeAreaInsets.top
        let y = frame.maxY - height
        
        // A safety check to ensure it looks like a valid notch (e.g. width/height make sense)
        guard width > 0 && height > 0 else { return nil }
        
        return NSRect(x: x, y: y, width: width, height: height)
    }
}
