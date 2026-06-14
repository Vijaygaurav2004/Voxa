import Foundation

/// HTTP client for communicating with the Python Voxa API server.
/// Handles intent parsing, transcription, TTS, and Python-side action execution.
actor PythonBridge {
    static let shared = PythonBridge()

    private let config = VoxaConfig.shared
    private let session: URLSession
    private let decoder: JSONDecoder
    private let encoder: JSONEncoder

    private init() {
        let urlConfig = URLSessionConfiguration.default
        urlConfig.timeoutIntervalForRequest = 30
        urlConfig.timeoutIntervalForResource = 60
        self.session = URLSession(configuration: urlConfig)

        self.decoder = JSONDecoder()
        self.encoder = JSONEncoder()
    }

    // MARK: - Health Check

    /// Check if the Python backend is running and healthy.
    func healthCheck() async -> Bool {
        guard let url = URL(string: "\(config.apiBaseURL)/api/health") else { return false }
        do {
            let (_, response) = try await session.data(from: url)
            guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
                return false
            }
            return true
        } catch {
            return false
        }
    }

    /// Wait for the Python backend to become healthy, with retries.
    func waitForBackend(maxAttempts: Int = 30, intervalSeconds: Double = 1.0) async -> Bool {
        for attempt in 1...maxAttempts {
            if await healthCheck() {
                print("✅ Python backend ready (attempt \(attempt))")
                return true
            }
            print("⏳ Waiting for Python backend... (attempt \(attempt)/\(maxAttempts))")
            try? await Task.sleep(nanoseconds: UInt64(intervalSeconds * 1_000_000_000))
        }
        print("❌ Python backend not available after \(maxAttempts) attempts")
        return false
    }

    // MARK: - Intent Parsing

    /// Parse natural language text into an ActionPlan.
    func parseIntent(text: String, context: String = "") async throws -> IntentResponse {
        let body: [String: Any] = [
            "text": text,
            "context": context,
            "use_fast_model": false,
        ]
        return try await post("/api/intent", body: body)
    }

    struct IntentResponse: Codable {
        let plan: ActionPlan
        let elapsedMs: Int

        enum CodingKeys: String, CodingKey {
            case plan
            case elapsedMs = "elapsed_ms"
        }
    }

    // MARK: - Action Execution

    /// Execute a full action plan (Python-side only by default).
    func executePlan(_ plan: ActionPlan, pythonOnly: Bool = true) async throws -> ExecuteResponse {
        let planData = try encoder.encode(plan)
        let planDict = try JSONSerialization.jsonObject(with: planData) as? [String: Any] ?? [:]

        let body: [String: Any] = [
            "plan": planDict,
            "python_only": pythonOnly,
        ]
        return try await post("/api/execute", body: body)
    }

    struct ExecuteResponse: Codable {
        let results: [ActionResult]
        let successCount: Int
        let total: Int
        let elapsedMs: Int

        enum CodingKeys: String, CodingKey {
            case results
            case successCount = "success_count"
            case total
            case elapsedMs = "elapsed_ms"
        }
    }

    /// Execute a single action on the Python side.
    func executeAction(_ action: Action) async throws -> ActionResult {
        let actionData = try encoder.encode(action)
        let actionDict = try JSONSerialization.jsonObject(with: actionData) as? [String: Any] ?? [:]

        let body: [String: Any] = ["action": actionDict]
        return try await post("/api/execute-action", body: body)
    }

    // MARK: - Full Command Pipeline

    /// Process a full command: text → intent → execute (combined).
    func processCommand(text: String, context: String = "", pythonOnly: Bool = true) async throws -> CommandResponse {
        let body: [String: Any] = [
            "text": text,
            "context": context,
            "python_only": pythonOnly,
        ]
        return try await post("/api/command", body: body)
    }

    struct CommandResponse: Codable {
        let type: String
        let plan: ActionPlan?
        let results: [ActionResult]?
        let successCount: Int?
        let total: Int?
        let elapsedMs: Int
        let skillName: String?

        enum CodingKeys: String, CodingKey {
            case type, plan, results
            case successCount = "success_count"
            case total
            case elapsedMs = "elapsed_ms"
            case skillName = "skill_name"
        }
    }

    // MARK: - Transcription

    /// Send audio data to Python for Whisper transcription.
    func transcribe(audioData: Data) async throws -> String {
        let url = URL(string: "\(config.apiBaseURL)/api/transcribe")!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"

        // Multipart form data
        let boundary = UUID().uuidString
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")

        var body = Data()
        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append("Content-Disposition: form-data; name=\"audio\"; filename=\"recording.wav\"\r\n".data(using: .utf8)!)
        body.append("Content-Type: audio/wav\r\n\r\n".data(using: .utf8)!)
        body.append(audioData)
        body.append("\r\n--\(boundary)--\r\n".data(using: .utf8)!)
        request.httpBody = body

        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
            throw PythonBridgeError.transcriptionFailed
        }

        struct TranscribeResponse: Codable { let text: String }
        let result = try decoder.decode(TranscribeResponse.self, from: data)
        return result.text
    }

    // MARK: - TTS

    struct TTSResponse: Codable {
        let success: Bool
        let text: String
    }

    /// Request Python to speak text aloud.
    func speak(text: String, blocking: Bool = false) async throws {
        let body: [String: Any] = ["text": text, "blocking": blocking]
        let _: TTSResponse = try await post("/api/tts", body: body)
    }

    // MARK: - Context

    /// Get session context for LLM.
    func getContext() async throws -> ContextResponse {
        return try await get("/api/context")
    }

    struct ContextResponse: Codable {
        let contextText: String
        let lastApp: String?
        let lastUrl: String?
        let lastQuery: String?

        enum CodingKeys: String, CodingKey {
            case contextText = "context_text"
            case lastApp = "last_app"
            case lastUrl = "last_url"
            case lastQuery = "last_query"
        }
    }

    // MARK: - Networking Helpers

    private func get<T: Decodable>(_ path: String) async throws -> T {
        let url = URL(string: "\(config.apiBaseURL)\(path)")!
        let (data, response) = try await session.data(from: url)
        guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
            throw PythonBridgeError.requestFailed(path)
        }
        return try decoder.decode(T.self, from: data)
    }

    private func post<T: Decodable>(_ path: String, body: [String: Any]) async throws -> T {
        let url = URL(string: "\(config.apiBaseURL)\(path)")!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: body)

        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw PythonBridgeError.requestFailed(path)
        }

        if http.statusCode == 422 {
            throw PythonBridgeError.intentParseFailed
        }

        guard (200...299).contains(http.statusCode) else {
            let detail = String(data: data, encoding: .utf8) ?? "Unknown error"
            throw PythonBridgeError.serverError(http.statusCode, detail)
        }

        return try decoder.decode(T.self, from: data)
    }
}

// MARK: - Errors

enum PythonBridgeError: Error, LocalizedError {
    case requestFailed(String)
    case serverError(Int, String)
    case intentParseFailed
    case transcriptionFailed

    var errorDescription: String? {
        switch self {
        case .requestFailed(let path):
            return "Request to \(path) failed"
        case .serverError(let code, let detail):
            return "Server error \(code): \(detail)"
        case .intentParseFailed:
            return "Could not understand the command"
        case .transcriptionFailed:
            return "Could not transcribe audio"
        }
    }
}
