import Foundation

/// HTTP client for communicating with the Python Voxa API server.
/// Handles intent parsing, transcription, TTS, and Python-side action execution.
actor PythonBridge {
    static let shared = PythonBridge()

    private let config = VoxaConfig.shared
    private let bridgeToken = VoxaConfig.bridgeToken()
    private let session: URLSession
    private let decoder: JSONDecoder
    private let encoder: JSONEncoder

    private init() {
        let urlConfig = URLSessionConfiguration.default
        urlConfig.timeoutIntervalForRequest = 60   // LLM calls (RAG, summarization) can take 30-50s
        urlConfig.timeoutIntervalForResource = 120
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
        request.setValue(bridgeToken, forHTTPHeaderField: "X-Voxa-Token")

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

    // MARK: - Memory audio ingest (meeting capture)

    /// Stream a captured WAV chunk to the backend's memory pipeline.
    /// `source` is "mic" (this user) or "system" (other participants).
    func ingestMemoryChunk(_ wav: Data, source: String = "mic") async throws {
        let url = URL(string: "\(config.apiBaseURL)/api/memory/ingest")!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue(bridgeToken, forHTTPHeaderField: "X-Voxa-Token")
        let boundary = UUID().uuidString
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")

        var body = Data()
        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append("Content-Disposition: form-data; name=\"source\"\r\n\r\n".data(using: .utf8)!)
        body.append("\(source)\r\n".data(using: .utf8)!)
        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append("Content-Disposition: form-data; name=\"audio\"; filename=\"chunk.wav\"\r\n".data(using: .utf8)!)
        body.append("Content-Type: audio/wav\r\n\r\n".data(using: .utf8)!)
        body.append(wav)
        body.append("\r\n--\(boundary)--\r\n".data(using: .utf8)!)
        request.httpBody = body

        _ = try? await session.data(for: request)   // best-effort; drops are non-fatal
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
        var request = URLRequest(url: url)
        request.setValue(bridgeToken, forHTTPHeaderField: "X-Voxa-Token")
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
            throw PythonBridgeError.requestFailed(path)
        }
        return try decoder.decode(T.self, from: data)
    }

    /// GET the raw response body (no JSON decode) with the bridge token attached —
    /// used for binary payloads like audio clip WAV bytes.
    private func getRawData(_ path: String) async throws -> Data {
        let url = URL(string: "\(config.apiBaseURL)\(path)")!
        var request = URLRequest(url: url)
        request.setValue(bridgeToken, forHTTPHeaderField: "X-Voxa-Token")
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
            throw PythonBridgeError.requestFailed(path)
        }
        return data
    }

    private func post<T: Decodable>(_ path: String, body: [String: Any]) async throws -> T {
        let url = URL(string: "\(config.apiBaseURL)\(path)")!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue(bridgeToken, forHTTPHeaderField: "X-Voxa-Token")
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

    private func put<T: Decodable>(_ path: String, body: [String: Any]) async throws -> T {
        let url = URL(string: "\(config.apiBaseURL)\(path)")!
        var request = URLRequest(url: url)
        request.httpMethod = "PUT"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue(bridgeToken, forHTTPHeaderField: "X-Voxa-Token")
        request.httpBody = try JSONSerialization.data(withJSONObject: body)

        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw PythonBridgeError.requestFailed(path)
        }

        guard (200...299).contains(http.statusCode) else {
            let detail = String(data: data, encoding: .utf8) ?? "Unknown error"
            throw PythonBridgeError.serverError(http.statusCode, detail)
        }

        return try decoder.decode(T.self, from: data)
    }

    private func delete<T: Decodable>(_ path: String) async throws -> T {
        let url = URL(string: "\(config.apiBaseURL)\(path)")!
        var request = URLRequest(url: url)
        request.httpMethod = "DELETE"
        request.setValue(bridgeToken, forHTTPHeaderField: "X-Voxa-Token")

        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw PythonBridgeError.requestFailed(path)
        }

        guard (200...299).contains(http.statusCode) else {
            let detail = String(data: data, encoding: .utf8) ?? "Unknown error"
            throw PythonBridgeError.serverError(http.statusCode, detail)
        }

        return try decoder.decode(T.self, from: data)
    }

    // MARK: - Modes CRUD

    struct ModesResponse: Codable {
        let modes: [VoxaMode]
        let count: Int
    }

    struct ModeActionResponse: Codable {
        let success: Bool
        let message: String
    }

    func getModes() async throws -> [VoxaMode] {
        let res: ModesResponse = try await get("/api/modes")
        return res.modes
    }

    /// A mode spec generated by the small LLM from a plain-English description
    /// (not yet saved — used to pre-fill the create form for review).
    struct ModeSpec: Codable {
        let name: String
        let description: String
        let instructions: [String]
    }

    /// Ask the small LLM to turn a plain-English description into a reviewable
    /// mode spec (name + steps) without saving it.
    func generateModeSpec(description: String) async throws -> ModeSpec {
        let body: [String: Any] = ["description": description]
        return try await post("/api/modes/generate", body: body)
    }

    func createMode(name: String, instructions: [String], description: String) async throws -> ModeActionResponse {
        let body: [String: Any] = [
            "name": name,
            "instructions": instructions,
            "description": description
        ]
        return try await post("/api/modes", body: body)
    }

    func updateMode(name: String, instructions: [String], description: String) async throws -> ModeActionResponse {
        let body: [String: Any] = [
            "instructions": instructions,
            "description": description
        ]
        let nameEncoded = name.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? name
        return try await put("/api/modes/\(nameEncoded)", body: body)
    }

    func deleteMode(name: String) async throws -> ModeActionResponse {
        let nameEncoded = name.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? name
        return try await delete("/api/modes/\(nameEncoded)")
    }

    struct ActivateResponse: Decodable {
        let success: Bool?
        let message: String?
    }

    @discardableResult
    func activateMode(name: String) async throws -> ActivateResponse {
        let nameEncoded = name.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? name
        return try await post("/api/modes/\(nameEncoded)/activate", body: [:])
    }

    // MARK: - Memory query

    struct MemoryAnswer: Decodable {
        let answer: String?
        let summary: String?
    }

    func queryMemory(_ question: String) async throws -> String {
        let ans: MemoryAnswer = try await post("/api/memory/query", body: ["question": question])
        return ans.answer ?? ans.summary ?? "No answer."
    }

    // MARK: - Memory clips & storage (recordings)

    /// A stored audio recording backing one memory segment.
    struct ClipRecord: Decodable, Identifiable {
        let id: Int
        let timestamp: String
        let duration_secs: Double
        let summary: String
        let source: String
        let session_id: String
        let size_bytes: Int
    }

    struct ClipsResponse: Decodable {
        let clips: [ClipRecord]
        let count: Int
    }

    /// On-disk usage + retention settings for the memory store.
    struct StorageInfo: Decodable {
        let clips_count: Int
        let clips_size_mb: Double
        let db_size_mb: Double
        let keep_audio: Bool
        let retention_days: Int
    }

    /// Minimal `{"success": ...}` envelope returned by clip mutations.
    private struct ClipMutationResponse: Decodable { let success: Bool }

    /// List stored recordings (newest first). Only segments with a clip on disk.
    func getClips(limit: Int = 50) async throws -> [ClipRecord] {
        let res: ClipsResponse = try await get("/api/memory/clips?limit=\(limit)")
        return res.clips
    }

    /// Disk usage + keep-audio / retention settings.
    func getStorageInfo() async throws -> StorageInfo {
        return try await get("/api/memory/storage")
    }

    /// Raw WAV bytes for one clip.
    func getClipAudio(id: Int) async throws -> Data {
        return try await getRawData("/api/memory/clip/\(id)")
    }

    /// Delete a recording (audio file + DB segment + vector).
    func deleteClip(id: Int) async throws -> ModeActionResponse {
        let res: ClipMutationResponse = try await delete("/api/memory/clip/\(id)")
        return ModeActionResponse(success: res.success, message: res.success ? "Deleted" : "Not found")
    }

    /// Update keep-audio and/or retention; sends only the provided keys.
    func updateMemorySettings(keepAudio: Bool? = nil, retentionDays: Int? = nil) async throws -> StorageInfo {
        var body: [String: Any] = [:]
        if let keepAudio { body["keep_audio"] = keepAudio }
        if let retentionDays { body["retention_days"] = retentionDays }
        return try await post("/api/memory/settings", body: body)
    }

    /// Delete all clip files while keeping transcripts.
    func clearClips() async throws -> ModeActionResponse {
        let res: ClipMutationResponse = try await post("/api/memory/clips/clear", body: [:])
        return ModeActionResponse(success: res.success, message: "Cleared")
    }

    // MARK: - Memory clip sessions (recordings grouped as meetings)

    /// A recording session: the clips captured in one continuous conversation,
    /// named by an AI title and badged with the platform it was recorded on.
    struct ClipSession: Decodable, Identifiable {
        let session_id: String
        let title: String
        let platform: String
        let platform_kind: String          // browser | app | mic
        let started_iso: String
        let ended_iso: String
        let duration_secs: Double
        let clip_count: Int
        let sources: [String]
        let clips: [ClipRecord]
        var id: String { session_id }
    }

    struct ClipSessionsResponse: Decodable {
        let sessions: [ClipSession]
        let count: Int
    }

    /// List recording sessions (newest first). Only sessions with clips on disk.
    func getClipSessions(limit: Int = 30) async throws -> [ClipSession] {
        let res: ClipSessionsResponse = try await get("/api/memory/clip-sessions?limit=\(limit)")
        return res.sessions
    }

    /// Delete a whole session's clip files (transcripts stay searchable).
    func deleteSession(sessionID: String) async throws -> ModeActionResponse {
        let encoded = sessionID.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? sessionID
        let res: ClipMutationResponse = try await delete("/api/memory/session/\(encoded)")
        return ModeActionResponse(success: res.success, message: res.success ? "Deleted" : "Not found")
    }

    // MARK: - Memory (Always-On Listening)

    struct MemoryStatusResponse: Decodable {
        let active: Bool
        let running: Bool
        let paused: Bool
        let current_session: String?
        let total_segments: Int?
        let total_sessions: Int?
        let total_duration_hours: Double?
    }

    func startMemory() async throws -> ModeActionResponse {
        return try await post("/api/memory/start", body: [:])
    }

    func stopMemory() async throws -> ModeActionResponse {
        return try await post("/api/memory/stop", body: [:])
    }

    func getMemoryStatus() async throws -> MemoryStatusResponse {
        guard let url = URL(string: "\(config.apiBaseURL)/api/memory/status") else {
            throw PythonBridgeError.requestFailed("/api/memory/status")
        }
        var request = URLRequest(url: url)
        request.setValue(bridgeToken, forHTTPHeaderField: "X-Voxa-Token")
        let (data, _) = try await session.data(for: request)
        return try decoder.decode(MemoryStatusResponse.self, from: data)
    }

    // MARK: - Meeting Detection (Granola-style auto-capture)

    struct MeetingStatusResponse: Decodable {
        let enabled: Bool
        let detecting: Bool
        let in_meeting: Bool
        let recording: Bool?
        let paused: Bool?
        let awaiting_confirmation: Bool?
        let current: Current?

        struct Current: Decodable {
            let platform: String?
            let source: String?
        }
    }

    func getMeetingStatus() async throws -> MeetingStatusResponse {
        guard let url = URL(string: "\(config.apiBaseURL)/api/meeting/status") else {
            throw PythonBridgeError.requestFailed("/api/meeting/status")
        }
        var request = URLRequest(url: url)
        request.setValue(bridgeToken, forHTTPHeaderField: "X-Voxa-Token")
        let (data, _) = try await session.data(for: request)
        return try decoder.decode(MeetingStatusResponse.self, from: data)
    }

    func startMeetingDetection() async throws -> ModeActionResponse {
        return try await post("/api/meeting/start", body: [:])
    }

    func stopMeetingDetection() async throws -> ModeActionResponse {
        return try await post("/api/meeting/stop", body: [:])
    }

    /// Answer the "record this meeting?" prompt.
    @discardableResult
    func confirmMeeting(record: Bool) async throws -> ModeActionResponse {
        return try await post("/api/meeting/confirm", body: ["record": record])
    }

    /// Answer a proactive "add to calendar?" suggestion.
    @discardableResult
    func confirmSuggestion(id: String, accept: Bool) async throws -> ModeActionResponse {
        return try await post("/api/meeting/suggestion/confirm", body: ["suggestion_id": id, "accept": accept])
    }

    @discardableResult
    func pauseMeeting() async throws -> ModeActionResponse {
        return try await post("/api/meeting/pause", body: [:])
    }

    @discardableResult
    func resumeMeeting() async throws -> ModeActionResponse {
        return try await post("/api/meeting/resume", body: [:])
    }

    @discardableResult
    func endMeeting() async throws -> ModeActionResponse {
        return try await post("/api/meeting/end", body: [:])
    }

    /// A concrete commitment someone made during a meeting.
    struct MeetingActionItem: Decodable, Identifiable {
        var id: String { task + owner + due }
        let task: String
        let owner: String
        let due: String
    }

    /// An open thread to circle back on after a meeting.
    struct MeetingFollowUp: Decodable, Identifiable {
        var id: String { task + person }
        let task: String
        let person: String
    }

    /// A saved meeting note, including AI-extracted structured insights.
    struct MeetingRecord: Decodable, Identifiable {
        var id: String { (session_id ?? "") + (started_iso ?? "") }
        let platform: String?
        let summary: String?
        let started_iso: String?
        let ended_iso: String?
        let duration_secs: Double?
        let session_id: String?
        // Structured insights (nil for meetings saved before this feature).
        let key_points: [String]?
        let decisions: [String]?
        let action_items: [MeetingActionItem]?
        let todos: [String]?
        let follow_ups: [MeetingFollowUp]?
        let reminders_exported: Bool?

        /// Whether this meeting has anything worth pushing to Reminders.
        var hasTasks: Bool {
            (action_items?.isEmpty == false) || (todos?.isEmpty == false)
        }
    }

    struct MeetingsResponse: Decodable {
        let meetings: [MeetingRecord]
        let count: Int
    }

    func getMeetings(limit: Int = 30) async throws -> [MeetingRecord] {
        let res: MeetingsResponse = try await get("/api/meeting/list?limit=\(limit)")
        return res.meetings
    }

    /// (Re)generate structured notes for a saved meeting; persists them server-side.
    @discardableResult
    func regenerateMeetingInsights(sessionId: String) async throws -> ModeActionResponse {
        return try await post("/api/meeting/insights/\(sessionId)", body: [:])
    }

    struct RemindersExportResponse: Decodable {
        let success: Bool
        let created: Int
        let message: String
    }

    /// Turn a meeting's action items + to-dos into macOS Reminders.
    @discardableResult
    func exportMeetingReminders(sessionId: String) async throws -> RemindersExportResponse {
        return try await post("/api/meeting/reminders/\(sessionId)", body: [:])
    }

    // MARK: - Integrations (Google / GitHub connections)

    struct IntegrationProvider: Codable, Identifiable {
        let id: String
        let name: String
        let connected: Bool
        let configured: Bool
        let account_label: String?
        let avatar_url: String?
        let detail: String?
    }

    struct IntegrationsResponse: Codable { let providers: [IntegrationProvider] }

    struct ConnectResponse: Codable {
        let success: Bool
        let auth_url: String?
        let message: String?
    }

    func getIntegrations() async throws -> [IntegrationProvider] {
        let res: IntegrationsResponse = try await get("/api/integrations")
        return res.providers
    }

    func connectIntegration(_ id: String) async throws -> ConnectResponse {
        return try await post("/api/integrations/\(id)/connect", body: [:])
    }

    func disconnectIntegration(_ id: String) async throws {
        let _: ActivateResponse = try await post("/api/integrations/\(id)/disconnect", body: [:])
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
