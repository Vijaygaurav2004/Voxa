import Foundation
import AppKit

/// Native macOS app control using NSWorkspace and NSRunningApplication.
/// Replaces Python AppleScript subprocess calls with direct Cocoa APIs.
enum AppControl {

    /// Open/activate an application by name.
    static func openApp(_ appName: String) async -> ActionResult {
        let resolved = resolveAppName(appName)

        // Check if the application is already open
        if isAppRunning(resolved) {
            _ = focusApp(resolved)
            return ActionResult(success: true, action: "open_app", message: "\(resolved) is already open")
        }

        // 1. Try NSWorkspace (fastest)
        if let url = NSWorkspace.shared.urlForApplication(withBundleIdentifier: bundleID(for: resolved)) {
            let config = NSWorkspace.OpenConfiguration()
            config.activates = true

            let success = await withCheckedContinuation { continuation in
                NSWorkspace.shared.openApplication(at: url, configuration: config) { app, error in
                    continuation.resume(returning: error == nil)
                }
            }
            if success {
                return ActionResult(success: true, action: "open_app", message: "Opened \(resolved)")
            }
        }

        // 2. Try open -a (works for any .app)
        let result = shell("open", "-a", resolved)
        if result.status == 0 {
            return ActionResult(success: true, action: "open_app", message: "Opened \(resolved)")
        }

        // 3. Try AppleScript activate
        let asResult = runAppleScript("tell application \"\(resolved)\" to activate")
        if asResult != nil {
            return ActionResult(success: true, action: "open_app", message: "Opened \(resolved)")
        }

        return ActionResult(success: false, action: "open_app",
                            message: "Could not open \(appName). Is it installed?")
    }

    /// Check if an application is currently running.
    static func isAppRunning(_ appName: String) -> Bool {
        let resolved = resolveAppName(appName)
        let bundleIdentifier = bundleID(for: resolved)
        if !NSRunningApplication.runningApplications(withBundleIdentifier: bundleIdentifier).isEmpty {
            return true
        }
        for app in NSWorkspace.shared.runningApplications {
            if let name = app.localizedName, name.localizedCaseInsensitiveCompare(resolved) == .orderedSame {
                return true
            }
            if let bid = app.bundleIdentifier, bid.localizedCaseInsensitiveCompare(bundleIdentifier) == .orderedSame {
                return true
            }
        }
        return false
    }

    /// Close/quit an application.
    static func closeApp(_ appName: String) async -> ActionResult {
        let resolved = resolveAppName(appName)

        // Find running apps matching by name (case-insensitive) or bundle identifier
        let runningApps = NSWorkspace.shared.runningApplications.filter { app in
            if let name = app.localizedName, name.localizedCaseInsensitiveCompare(resolved) == .orderedSame {
                return true
            }
            if let name = app.localizedName, name.localizedCaseInsensitiveCompare(appName) == .orderedSame {
                return true
            }
            let bid = bundleID(for: resolved)
            if let appBid = app.bundleIdentifier, appBid.localizedCaseInsensitiveCompare(bid) == .orderedSame {
                return true
            }
            return false
        }

        guard !runningApps.isEmpty else {
            return ActionResult(success: true, action: "close_app", message: "\(resolved) is already closed")
        }

        // Try to terminate all instances
        for app in runningApps {
            app.terminate()
        }

        // Wait a short time to see if they terminate
        var allTerminated = false
        for _ in 0..<10 {
            try? await Task.sleep(nanoseconds: 100_000_000) // 100ms
            if runningApps.allSatisfy({ $0.isTerminated }) {
                allTerminated = true
                break
            }
        }

        // If any app is still running, force terminate
        if !allTerminated {
            for app in runningApps {
                if !app.isTerminated {
                    app.forceTerminate()
                }
            }
            // Wait again
            for _ in 0..<5 {
                try? await Task.sleep(nanoseconds: 100_000_000)
                if runningApps.allSatisfy({ $0.isTerminated }) {
                    allTerminated = true
                    break
                }
            }
        }

        // Final fallback: AppleScript quit and shell killall
        if !allTerminated {
            let _ = runAppleScript("tell application \"\(resolved)\" to quit")
            let _ = shell("killall", resolved)
            let _ = shell("killall", "-9", resolved)
        }

        return ActionResult(success: true, action: "close_app", message: "Closed \(resolved)")
    }

    /// Bring an app to the foreground.
    static func focusApp(_ appName: String) -> ActionResult {
        let resolved = resolveAppName(appName)

        if let app = NSRunningApplication.runningApplications(withBundleIdentifier: bundleID(for: resolved)).first {
            app.activate(options: [.activateAllWindows, .activateIgnoringOtherApps])
            return ActionResult(success: true, action: "focus_app", message: "Focused \(resolved)")
        }

        // Fallback
        let _ = runAppleScript("tell application \"\(resolved)\" to activate")
        return ActionResult(success: true, action: "focus_app", message: "Focused \(resolved)")
    }

    /// Open a file.
    static func openFile(_ path: String) -> ActionResult {
        let url = URL(fileURLWithPath: (path as NSString).expandingTildeInPath)
        if NSWorkspace.shared.open(url) {
            return ActionResult(success: true, action: "file_open", message: "Opened \(path)")
        }
        return ActionResult(success: false, action: "file_open", message: "Could not open \(path)")
    }

    /// Open a folder in Finder.
    static func openFolder(_ path: String) -> ActionResult {
        let url = URL(fileURLWithPath: (path as NSString).expandingTildeInPath)
        NSWorkspace.shared.selectFile(nil, inFileViewerRootedAtPath: url.path)
        return ActionResult(success: true, action: "file_open_folder", message: "Opened folder \(path)")
    }

    // MARK: - Helpers

    private static let appAliases: [String: String] = [
        "visual studio code": "Cursor",
        "vscode": "Cursor",
        "vs code": "Cursor",
        "code": "Cursor",
        "chrome": "Google Chrome",
        "firefox": "Firefox",
        "safari": "Safari",
        "terminal": "Terminal",
        "iterm": "iTerm",
        "iterm2": "iTerm",
        "zoom": "zoom.us",
    ]

    private static func resolveAppName(_ name: String) -> String {
        var cleaned = name.trimmingCharacters(in: .whitespacesAndNewlines)

        let suffixes = [" application", " app", " program", " software"]
        for suffix in suffixes {
            if cleaned.lowercased().hasSuffix(suffix) {
                cleaned = String(cleaned.dropLast(suffix.count)).trimmingCharacters(in: .whitespacesAndNewlines)
            }
        }

        let lowerCleaned = cleaned.lowercased()
        if let alias = appAliases[lowerCleaned] {
            return alias
        }

        if cleaned.count > 0 {
            let firstChar = cleaned.prefix(1).uppercased()
            let remaining = cleaned.dropFirst()
            return firstChar + remaining
        }
        return cleaned
    }

    private static func bundleID(for appName: String) -> String {
        let knownBundles: [String: String] = [
            "Google Chrome": "com.google.Chrome",
            "Safari": "com.apple.Safari",
            "Terminal": "com.apple.Terminal",
            "Finder": "com.apple.finder",
            "Notes": "com.apple.Notes",
            "Mail": "com.apple.mail",
            "Music": "com.apple.Music",
            "Messages": "com.apple.MobileSMS",
            "Slack": "com.tinyspeck.slackmacgap",
            "Discord": "com.hnc.Discord",
            "Cursor": "todesktop.com.Cursor",
            "Spotify": "com.spotify.client",
            "Keynote": "com.apple.iWork.Keynote",
            "Pages": "com.apple.iWork.Pages",
            "Numbers": "com.apple.iWork.Numbers",
            "Xcode": "com.apple.dt.Xcode",
            "System Settings": "com.apple.systempreferences",
        ]
        return knownBundles[appName] ?? "com.apple.\(appName)"
    }

    private static func shell(_ args: String...) -> (status: Int32, output: String) {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        process.arguments = args
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = pipe
        try? process.run()
        process.waitUntilExit()
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        return (process.terminationStatus, String(data: data, encoding: .utf8) ?? "")
    }

    private static func runAppleScript(_ script: String) -> String? {
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
