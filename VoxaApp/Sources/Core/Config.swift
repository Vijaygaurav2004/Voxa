import Foundation

/// Reads configuration from the .env file in the Voxa project root.
struct VoxaConfig {
    static let shared = VoxaConfig()

    let apiServerHost: String
    let apiServerPort: Int
    let wakeWord: String
    let hotkeyCombo: String
    let defaultBrowser: String
    let dashboardPort: Int

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

    // MARK: - Distribution (standalone .app)

    /// User config directory — canonical home for the distributed app's settings
    /// and the API key. Survives app updates and is writable.
    static var userConfigDir: URL {
        URL(fileURLWithPath: NSHomeDirectory()).appendingPathComponent(".voxa")
    }

    /// The user-owned .env (`~/.voxa/.env`) written by the first-run key prompt.
    static var userEnvPath: URL {
        userConfigDir.appendingPathComponent(".env")
    }

    /// Shared secret between the app and its local backend (~/.voxa/bridge_token).
    /// Read the existing token, or create one on first use (owner-only, 0o600).
    static func bridgeToken() -> String {
        let path = userConfigDir.appendingPathComponent("bridge_token")
        if let content = try? String(contentsOf: path, encoding: .utf8) {
            let token = content.trimmingCharacters(in: .whitespacesAndNewlines)
            if !token.isEmpty { return token }
        }
        let token = UUID().uuidString
        try? FileManager.default.createDirectory(at: userConfigDir, withIntermediateDirectories: true)
        try? token.write(to: path, atomically: true, encoding: .utf8)
        try? FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: path.path)
        return token
    }

    /// Path to the Python backend embedded inside the .app bundle, if present.
    /// Layout: `<App>.app/Contents/Resources/backend/voxa-backend/voxa-backend`.
    var embeddedBackendURL: URL? {
        guard let res = Bundle.main.resourceURL else { return nil }
        let candidate = res
            .appendingPathComponent("backend/voxa-backend/voxa-backend")
        return FileManager.default.fileExists(atPath: candidate.path) ? candidate : nil
    }

    /// True when running as a distributed standalone app (backend is embedded).
    var isBundledApp: Bool { embeddedBackendURL != nil }

    // MARK: - Embedded defaults (baked into the DMG at build time)

    /// Credentials the build pipeline bakes into the bundle so a downloaded DMG
    /// works out of the box: `<App>.app/Contents/Resources/voxa-defaults.env`.
    /// Contains only the OpenAI key and OAuth client ids/secrets the developer
    /// chose to ship. User-provided values (real env / ~/.voxa/.env) always win —
    /// these are fallbacks only. Absent in dev checkouts → empty.
    static let embeddedDefaults: [String: String] = {
        guard let res = Bundle.main.resourceURL else { return [:] }
        let url = res.appendingPathComponent("voxa-defaults.env")
        guard let content = try? String(contentsOf: url, encoding: .utf8) else { return [:] }
        var out: [String: String] = [:]
        for line in content.components(separatedBy: .newlines) {
            let trimmed = line.trimmingCharacters(in: .whitespaces)
            guard !trimmed.isEmpty, !trimmed.hasPrefix("#") else { continue }
            let parts = trimmed.split(separator: "=", maxSplits: 1)
            guard parts.count == 2 else { continue }
            let key = String(parts[0]).trimmingCharacters(in: .whitespaces)
            let value = String(parts[1]).trimmingCharacters(in: .whitespaces)
            if !value.isEmpty { out[key] = value }
        }
        return out
    }()

    // MARK: - API Key management

    /// Read the OpenAI API key from ~/.voxa/.env, then the dev .env, then env,
    /// then the DMG-embedded default (so a downloaded app needs no key entry).
    static func readAPIKey() -> String? {
        for path in [userEnvPath, shared.envFilePath] {
            if let content = try? String(contentsOf: path, encoding: .utf8),
               let key = parseValue("OPENAI_API_KEY", from: content),
               !key.isEmpty {
                return key
            }
        }
        if let envKey = ProcessInfo.processInfo.environment["OPENAI_API_KEY"], !envKey.isEmpty {
            return envKey
        }
        return embeddedDefaults["OPENAI_API_KEY"]
    }

    /// True if a line is an `OPENAI_API_KEY=...` assignment, tolerating spaces
    /// around the `=` (e.g. a hand-edited `OPENAI_API_KEY = sk-...`).
    private static func isOpenAIKeyAssignment(_ line: String) -> Bool {
        let t = line.trimmingCharacters(in: .whitespaces)
        guard let eq = t.firstIndex(of: "=") else { return false }
        return t[..<eq].trimmingCharacters(in: .whitespaces) == "OPENAI_API_KEY"
    }

    /// Persist the OpenAI API key to ~/.voxa/.env (creating/merging the file).
    @discardableResult
    static func saveAPIKey(_ key: String) -> Bool {
        let trimmed = key.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return false }
        try? FileManager.default.createDirectory(at: userConfigDir, withIntermediateDirectories: true)

        var lines: [String] = []
        if let content = try? String(contentsOf: userEnvPath, encoding: .utf8) {
            // Drop ANY existing OPENAI_API_KEY line (with or without spaces around
            // '=') so we never leave a stale duplicate that would win on read.
            lines = content.components(separatedBy: .newlines)
                .filter { !isOpenAIKeyAssignment($0) }
        }
        lines.append("OPENAI_API_KEY=\(trimmed)")
        let out = lines.filter { !$0.isEmpty }.joined(separator: "\n") + "\n"
        do {
            try out.write(to: userEnvPath, atomically: true, encoding: .utf8)
            return true
        } catch {
            return false
        }
    }

    private static func parseValue(_ key: String, from content: String) -> String? {
        for line in content.components(separatedBy: .newlines) {
            let trimmed = line.trimmingCharacters(in: .whitespaces)
            guard !trimmed.isEmpty, !trimmed.hasPrefix("#") else { continue }
            let parts = trimmed.split(separator: "=", maxSplits: 1)
            guard parts.count == 2, String(parts[0]).trimmingCharacters(in: .whitespaces) == key else { continue }
            return String(parts[1]).trimmingCharacters(in: .whitespaces)
        }
        return nil
    }

    private init() {
        // Parse .env file
        var env: [String: String] = [:]
        let possiblePaths = [
            VoxaConfig.userEnvPath,  // ~/.voxa/.env — distributed app
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
        self.dashboardPort = Int(env["DASHBOARD_PORT"] ?? "7429") ?? 7429
    }
}
