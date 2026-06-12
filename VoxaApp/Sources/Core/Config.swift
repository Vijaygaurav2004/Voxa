import Foundation

/// Reads configuration from the .env file in the Voxa project root.
struct VoxaConfig {
    static let shared = VoxaConfig()

    let apiServerHost: String
    let apiServerPort: Int
    let wakeWord: String
    let hotkeyCombo: String
    let defaultBrowser: String

    /// Base URL for the Python API server.
    var apiBaseURL: URL {
        URL(string: "http://\(apiServerHost):\(apiServerPort)")!
    }

    /// WebSocket URL for real-time status.
    var wsURL: URL {
        URL(string: "ws://\(apiServerHost):\(apiServerPort)/ws/status")!
    }

    /// Path to the Python project root (parent of VoxaApp/).
    var projectRoot: URL {
        // VoxaApp is at <project>/VoxaApp, so go up one level
        let bundle = Bundle.main.bundleURL
        // In dev: the binary is deeper, find the project root from env or fallback
        if let envRoot = ProcessInfo.processInfo.environment["VOXA_PROJECT_ROOT"] {
            return URL(fileURLWithPath: envRoot)
        }
        // Walk up from bundle to find the Voxa root (contains voxa/ directory)
        var url = bundle
        for _ in 0..<6 {
            let voxaDir = url.appendingPathComponent("voxa")
            if FileManager.default.fileExists(atPath: voxaDir.path) {
                return url
            }
            url = url.deletingLastPathComponent()
        }
        // Fallback: hardcoded dev path
        return URL(fileURLWithPath: NSHomeDirectory())
            .appendingPathComponent("Desktop/Voxa")
    }

    /// Path to the .env file.
    var envFilePath: URL {
        projectRoot.appendingPathComponent(".env")
    }

    /// Path to the Python venv.
    var pythonPath: URL {
        projectRoot.appendingPathComponent("venv/bin/python3")
    }

    private init() {
        // Parse .env file
        var env: [String: String] = [:]
        let possiblePaths = [
            URL(fileURLWithPath: NSHomeDirectory()).appendingPathComponent("Desktop/Voxa/.env"),
        ]

        for path in possiblePaths {
            if let content = try? String(contentsOf: path, encoding: .utf8) {
                for line in content.components(separatedBy: .newlines) {
                    let trimmed = line.trimmingCharacters(in: .whitespaces)
                    guard !trimmed.isEmpty, !trimmed.hasPrefix("#") else { continue }
                    let parts = trimmed.split(separator: "=", maxSplits: 1)
                    guard parts.count == 2 else { continue }
                    let key = String(parts[0]).trimmingCharacters(in: .whitespaces)
                    let value = String(parts[1]).trimmingCharacters(in: .whitespaces)
                    env[key] = value
                }
                break
            }
        }

        self.apiServerHost = env["API_SERVER_HOST"] ?? "127.0.0.1"
        self.apiServerPort = Int(env["API_SERVER_PORT"] ?? "7430") ?? 7430
        self.wakeWord = env["WAKE_WORD"] ?? "hey voxa"
        self.hotkeyCombo = env["HOTKEY_COMBO"] ?? "cmd+shift+v"
        self.defaultBrowser = env["DEFAULT_BROWSER"] ?? "Google Chrome"
    }
}
