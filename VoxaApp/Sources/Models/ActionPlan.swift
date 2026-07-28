import Foundation

/// Mirrors Python Action model — a single executable action.
struct Action: Codable, Identifiable {
    var id: UUID = UUID()

    let action: ActionType
    var app: String?
    var url: String?
    var query: String?
    var text: String?
    var keys: String?
    var command: String?
    var path: String?
    var delaySeconds: Double?
    let description: String
    var executionTarget: String?

    // System control
    var level: Int?
    var direction: String?
    var enable: Bool?
    var mute: Bool?

    // Timer
    var durationSeconds: Double?
    var reminderText: String?
    var timerName: String?

    // Email
    var emailTo: String?
    var emailSubject: String?
    var emailBody: String?

    // Screen
    var screenQuestion: String?
    var windowOnly: Bool?

    // Media
    var mediaApp: String?

    // Computer control
    var x: Int?
    var y: Int?
    var toX: Int?
    var toY: Int?
    var element: String?
    var menuPath: [String]?
    var fieldHint: String?
    var doubleClick: Bool?
    var rightClick: Bool?
    var amount: Int?

    // Editor AI
    var editorPrompt: String?
    var editorMode: String?

    // Messaging
    var contactName: String?

    // Maps
    var origin: String?
    var destination: String?

    // Chrome
    var tabIndex: Int?
    var tabCount: Int?
    var tabKeyword: String?
    var scrollDirection: String?

    // Custom Mode / Memory
    var modeName: String?
    var memoryQuestion: String?
    var hours: Double?

    // Integrations (Google Calendar events)
    var eventTitle: String?
    var eventStart: String?
    var eventEnd: String?
    var eventLocation: String?
    var eventDescription: String?
    var eventAttendees: [String]?

    enum CodingKeys: String, CodingKey {
        case action, app, url, query, text, keys, command, path
        case delaySeconds = "delay_seconds"
        case description
        case executionTarget = "execution_target"
        case level, direction, enable, mute
        case durationSeconds = "duration_seconds"
        case reminderText = "reminder_text"
        case timerName = "timer_name"
        case emailTo = "email_to"
        case emailSubject = "email_subject"
        case emailBody = "email_body"
        case screenQuestion = "screen_question"
        case windowOnly = "window_only"
        case mediaApp = "media_app"
        case x, y
        case toX = "to_x"
        case toY = "to_y"
        case element
        case menuPath = "menu_path"
        case fieldHint = "field_hint"
        case doubleClick = "double_click"
        case rightClick = "right_click"
        case amount
        case editorPrompt = "editor_prompt"
        case editorMode = "editor_mode"
        case contactName = "contact_name"
        case origin, destination
        case tabIndex = "tab_index"
        case tabCount = "tab_count"
        case tabKeyword = "tab_keyword"
        case scrollDirection = "scroll_direction"
        case modeName = "mode_name"
        case memoryQuestion = "memory_question"
        case hours
        case eventTitle = "event_title"
        case eventStart = "event_start"
        case eventEnd = "event_end"
        case eventLocation = "event_location"
        case eventDescription = "event_description"
        case eventAttendees = "event_attendees"
    }

    /// Whether this action should execute in Swift (vs being sent to Python).
    var shouldExecuteInSwift: Bool {
        return action.isSwiftAction
    }
}


/// Mirrors Python ActionPlan — a complete plan with ordered actions.
struct ActionPlan: Codable {
    let thought: String
    let actions: [Action]
    let confirmation: String
}


/// Result from executing a single action.
struct ActionResult: Codable {
    let success: Bool
    var action: String?
    var message: String?
    var error: String?
    var routed: String?
    var skipped: Bool?
}
