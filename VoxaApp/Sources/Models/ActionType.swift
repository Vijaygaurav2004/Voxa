import Foundation

/// Mirrors Python ActionType enum — all supported action types.
enum ActionType: String, Codable, CaseIterable {
    // App Control
    case openApp = "open_app"
    case closeApp = "close_app"
    case focusApp = "focus_app"

    // Browser
    case openURL = "open_url"
    case browserSearch = "browser_search"
    case browserNavigate = "browser_navigate"
    case browserClickFirstResult = "browser_click_first_result"
    case playYouTube = "play_youtube"
    case searchNetflix = "search_netflix"
    case mapsSearch = "maps_search"
    case mapsDirections = "maps_directions"

    // Input
    case typeText = "type_text"
    case keystroke = "keystroke"

    // Shell & Files
    case shellCommand = "shell_command"
    case fileOpen = "file_open"
    case fileOpenFolder = "file_open_folder"

    // Utility
    case wait = "wait"
    case speak = "speak"

    // System
    case systemVolume = "system_volume"
    case systemBrightness = "system_brightness"
    case systemDarkMode = "system_dark_mode"
    case systemDND = "system_dnd"
    case systemBattery = "system_battery"

    // Clipboard
    case clipboardGet = "clipboard_get"
    case clipboardSet = "clipboard_set"
    case clipboardPaste = "clipboard_paste"

    // Timers
    case setTimer = "set_timer"
    case cancelTimer = "cancel_timer"
    case listTimers = "list_timers"

    // Screen
    case screenRead = "screen_read"
    case screenshot = "screenshot"

    // Media
    case mediaPlayPause = "media_play_pause"
    case mediaNext = "media_next"
    case mediaPrev = "media_prev"
    case mediaNowPlaying = "media_now_playing"
    case mediaVolume = "media_volume"

    // Calendar
    case calendarToday = "calendar_today"
    case calendarUpcoming = "calendar_upcoming"
    case remindersList = "reminders_list"

    // Email
    case emailCompose = "email_compose"

    // Computer Control
    case visionClick = "vision_click"
    case clickAt = "click_at"
    case scroll = "scroll"
    case drag = "drag"
    case axButton = "ax_button"
    case axMenu = "ax_menu"
    case axType = "ax_type"

    // Editor AI
    case editorAIPrompt = "editor_ai_prompt"

    // Messaging
    case sendWhatsApp  = "send_whatsapp"
    case replyWhatsApp = "reply_whatsapp"

    // Chrome
    case chromeNewTab = "chrome_new_tab"
    case chromeNewTabs = "chrome_new_tabs"
    case chromeCloseTab = "chrome_close_tab"
    case chromeCloseAllTabs = "chrome_close_all_tabs"
    case chromeCloseTabsRight = "chrome_close_tabs_right"
    case chromeNextTab = "chrome_next_tab"
    case chromePrevTab = "chrome_prev_tab"
    case chromeSwitchTab = "chrome_switch_tab"
    case chromeFindTab = "chrome_find_tab"
    case chromeDuplicateTab = "chrome_duplicate_tab"
    case chromeListTabs = "chrome_list_tabs"
    case chromeNewWindow = "chrome_new_window"
    case chromeIncognito = "chrome_incognito"
    case chromeCloseWindow = "chrome_close_window"
    case chromeBack = "chrome_back"
    case chromeForward = "chrome_forward"
    case chromeReload = "chrome_reload"
    case chromeHardReload = "chrome_hard_reload"
    case chromeNavigate = "chrome_navigate"
    case chromeZoomIn = "chrome_zoom_in"
    case chromeZoomOut = "chrome_zoom_out"
    case chromeZoomReset = "chrome_zoom_reset"
    case chromeFindInPage = "chrome_find_in_page"
    case chromeBookmark = "chrome_bookmark"
    case chromeHistory = "chrome_history"
    case chromeDownloads = "chrome_downloads"
    case chromeBookmarksMgr = "chrome_bookmarks_mgr"
    case chromeSettings = "chrome_settings"
    case chromeExtensions = "chrome_extensions"
    case chromeDevtools = "chrome_devtools"
    case chromePageInfo = "chrome_page_info"
    case chromeScroll = "chrome_scroll"
    case chromeReopenTab = "chrome_reopen_tab"
    case chromeCloseTabByKeyword = "chrome_close_tab_by_keyword"
    case chromeCloseOtherTabs = "chrome_close_other_tabs"
    case chromeFullScreen = "chrome_full_screen"
    case chromeBookmarkBar = "chrome_bookmark_bar"
    case chromeBookmarkAllTabs = "chrome_bookmark_all_tabs"
    case chromeClearData = "chrome_clear_data"
    case chromePrint = "chrome_print"

    // Custom Modes
    case activateMode = "activate_mode"

    // Memory (Always-On Listening)
    case memoryStart = "memory_start"
    case memoryStop = "memory_stop"
    case memoryQuery = "memory_query"
    case memorySummary = "memory_summary"

    // Integrations (Google Calendar / Gmail / GitHub — executed in Python)
    case calendarCreateEvent = "calendar_create_event"
    case gmailSend = "gmail_send"
    case gmailUnread = "gmail_unread"
    case githubNotifications = "github_notifications"

    /// Fallback for any action type Python adds before Swift is updated.
    /// Unknown actions are forwarded to the Python backend.
    case unknown = "unknown"

    /// Custom Codable init so an unrecognised raw value falls back to .unknown
    /// instead of throwing a DecodingError and dropping the whole action plan.
    init(from decoder: Decoder) throws {
        let raw = try decoder.singleValueContainer().decode(String.self)
        self = ActionType(rawValue: raw) ?? .unknown
    }

    /// Whether this action should be executed natively in Swift.
    var isSwiftAction: Bool {
        switch self {
        case .openApp, .closeApp, .focusApp,
             .systemVolume, .systemBrightness, .systemDarkMode, .systemDND, .systemBattery,
             .typeText, .keystroke,
             .mediaPlayPause, .mediaNext, .mediaPrev, .mediaNowPlaying, .mediaVolume,
             .screenshot,
             .clipboardGet, .clipboardSet, .clipboardPaste,
             .clickAt, .scroll, .drag,
             .axButton, .axMenu, .axType,
             .wait, .speak,
             .fileOpen, .fileOpenFolder:
            return true
        default:
            // Everything else (browser, shell, WhatsApp, Chrome tabs, etc.) → Python
            return false
        }
    }
}
