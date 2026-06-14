import Foundation
import AppKit
import Carbon.HIToolbox

/// Global hotkey listener for ⌘+Shift+V using NSEvent.
/// Replaces the Python PyObjC hotkey hack with native Swift.
final class HotkeyManager {
    private let onActivate: () -> Void
    private var monitor: Any?

    init(onActivate: @escaping () -> Void) {
        self.onActivate = onActivate
    }

    func start() {
        // Global event monitor for key-down events
        monitor = NSEvent.addGlobalMonitorForEvents(matching: .keyDown) { [weak self] event in
            guard let self = self else { return }

            // Check for ⌘+Shift+V
            let flags = event.modifierFlags.intersection(.deviceIndependentFlagsMask)
            let isCmd = flags.contains(.command)
            let isShift = flags.contains(.shift)
            let isV = event.charactersIgnoringModifiers?.lowercased() == "v"

            if isCmd && isShift && isV {
                appLog("🔑 Hotkey ⌘+Shift+V activated!")
                self.onActivate()
            }
        }

        if monitor != nil {
            appLog("✅ Hotkey listener active (⌘+Shift+V)")
        } else {
            appLog("⚠️ Could not install hotkey listener — grant Accessibility permission")
        }
    }

    func stop() {
        if let monitor = monitor {
            NSEvent.removeMonitor(monitor)
            self.monitor = nil
        }
    }

    deinit {
        stop()
    }
}
