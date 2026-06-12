import Foundation
import CoreAudio
import IOKit
import CoreGraphics

/// Native macOS system control using CoreAudio, IOKit, and NSAppleScript.
/// Replaces Python system_control.py with direct macOS APIs.
enum SystemControl {

    // MARK: - Volume
    
    static func setVolume(level: Int?, direction: String?, mute: Bool) -> ActionResult {
        if mute {
            runAS("set volume output muted true")
            return ActionResult(success: true, action: "system_volume", message: "System muted")
        }

        if let level = level {
            let clamped = max(0, min(100, level))
            runAS("set volume output volume \(clamped)")
            return ActionResult(success: true, action: "system_volume", message: "Volume set to \(clamped)%")
        }

        if let dir = direction?.lowercased() {
            let currentStr = runAS("output volume of (get volume settings)") ?? "50"
            let current = Int(currentStr.trimmingCharacters(in: .whitespacesAndNewlines)) ?? 50
            let step = 15

            if dir == "up" {
                let newVol = min(100, current + step)
                runAS("set volume output volume \(newVol)")
                return ActionResult(success: true, action: "system_volume", message: "Volume increased to \(newVol)%")
            } else if dir == "down" {
                let newVol = max(0, current - step)
                runAS("set volume output volume \(newVol)")
                return ActionResult(success: true, action: "system_volume", message: "Volume decreased to \(newVol)%")
            }
        }

        return ActionResult(success: false, action: "system_volume",
                            message: "Specify level (0-100), direction (up/down), or mute")
    }

    // MARK: - Brightness

    private typealias GetBrightnessFunc = @convention(c) (CGDirectDisplayID, UnsafeMutablePointer<Float>) -> Int32
    private typealias SetBrightnessFunc = @convention(c) (CGDirectDisplayID, Float) -> Int32

    private static func getBrightness() -> Float {
        guard let handle = dlopen("/System/Library/PrivateFrameworks/DisplayServices.framework/DisplayServices", RTLD_NOW) else {
            return 0.5
        }
        defer { dlclose(handle) }
        
        guard let sym = dlsym(handle, "DisplayServicesGetLinearBrightness") else {
            return 0.5
        }
        
        let getBrightnessFn = unsafeBitCast(sym, to: GetBrightnessFunc.self)
        var level: Float = 0.0
        let display = CGMainDisplayID()
        let result = getBrightnessFn(display, &level)
        return result == 0 ? level : 0.5
    }

    private static func setBrightnessNative(to value: Float) -> Bool {
        guard let handle = dlopen("/System/Library/PrivateFrameworks/DisplayServices.framework/DisplayServices", RTLD_NOW) else {
            return false
        }
        defer { dlclose(handle) }
        
        guard let sym = dlsym(handle, "DisplayServicesSetLinearBrightness") else {
            return false
        }
        
        let setBrightnessFn = unsafeBitCast(sym, to: SetBrightnessFunc.self)
        let display = CGMainDisplayID()
        let result = setBrightnessFn(display, value)
        return result == 0
    }

    static func setBrightness(level: Int?, direction: String?) -> ActionResult {
        if let dir = direction?.lowercased() {
            let current = getBrightness()
            let step: Float = 0.125 // standard macOS increment (1/8th of full range)
            let target: Float
            if dir == "up" {
                target = min(1.0, current + step)
            } else if dir == "down" {
                target = max(0.0, current - step)
            } else {
                return ActionResult(success: false, action: "system_brightness",
                                    message: "Invalid direction: \(dir)")
            }
            
            let success = setBrightnessNative(to: target)
            let action = dir == "up" ? "increased" : "decreased"
            return ActionResult(success: success, action: "system_brightness",
                                message: "Brightness \(action) to \(Int(round(target * 100)))%")
        }

        if let level = level {
            let clamped = max(0, min(100, level))
            let success = setBrightnessNative(to: Float(clamped) / 100.0)
            return ActionResult(success: success, action: "system_brightness",
                                message: "Brightness set to \(clamped)%")
        }

        // Return current brightness level if query (both level and direction are nil)
        let current = getBrightness()
        return ActionResult(success: true, action: "system_brightness",
                            message: "Screen brightness is set to \(Int(round(current * 100)))%")
    }

    // MARK: - Dark Mode

    static func toggleDarkMode(enable: Bool?) -> ActionResult {
        if let enable = enable {
            let script = """
            tell application "System Events"
                tell appearance preferences
                    set dark mode to \(enable ? "true" : "false")
                end tell
            end tell
            """
            runAS(script)
            return ActionResult(success: true, action: "system_dark_mode",
                                message: "Dark mode \(enable ? "enabled" : "disabled")")
        }

        // Toggle
        let script = """
        tell application "System Events"
            tell appearance preferences
                set dark mode to not dark mode
                return dark mode
            end tell
        end tell
        """
        let result = runAS(script) ?? "toggled"
        let state = result.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() == "true"
            ? "enabled" : "disabled"
        return ActionResult(success: true, action: "system_dark_mode",
                            message: "Dark mode \(state)")
    }

    // MARK: - Do Not Disturb

    static func toggleDND(enable: Bool?) -> ActionResult {
        let shortcutName: String
        if let enable = enable {
            shortcutName = enable ? "Enable DND" : "Disable DND"
        } else {
            shortcutName = "Toggle DND"
        }

        let script = """
        do shell script "shortcuts run '\(shortcutName)' 2>/dev/null || true"
        """
        runAS(script)

        let action: String
        if let enable = enable {
            action = enable ? "enabled" : "disabled"
        } else {
            action = "toggled"
        }
        return ActionResult(success: true, action: "system_dnd",
                            message: "Do Not Disturb \(action)")
    }

    // MARK: - Battery

    static func getBatteryStatus() -> ActionResult {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/pmset")
        process.arguments = ["-g", "batt"]
        let pipe = Pipe()
        process.standardOutput = pipe
        try? process.run()
        process.waitUntilExit()

        let output = String(data: pipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""

        // Parse: "87%; discharging..."
        if let range = output.range(of: #"(\d+)%"#, options: .regularExpression) {
            let levelStr = String(output[range]).replacingOccurrences(of: "%", with: "")
            let level = Int(levelStr) ?? 0
            let charging = output.contains("AC Power")
            let msg = "Battery at \(level)%, \(charging ? "charging" : "on battery")"
            return ActionResult(success: true, action: "system_battery", message: msg)
        }

        return ActionResult(success: false, action: "system_battery",
                            message: "Could not read battery status")
    }

    // MARK: - Helper

    @discardableResult
    private static func runAS(_ script: String) -> String? {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/osascript")
        process.arguments = ["-e", script]
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = Pipe()
        try? process.run()
        process.waitUntilExit()
        guard process.terminationStatus == 0 else { return nil }
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        return String(data: data, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines)
    }
}
