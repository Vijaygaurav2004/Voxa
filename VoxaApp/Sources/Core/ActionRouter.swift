import Foundation
import AppKit

/// Routes actions to Swift (native) or Python (API) based on action type.
/// For mixed plans, executes steps sequentially — Swift actions locally,
/// Python actions via the PythonBridge HTTP client.
final class ActionRouter {
    static let shared = ActionRouter()

    private let bridge = PythonBridge.shared

    private init() {}

    private func logMessage(_ message: String) {
        appLog("[Router] \(message)")
    }

    private let speakResultActions: Set<ActionType> = [
        .screenRead, .screenshot, .clipboardGet, .systemBattery,
        .listTimers, .calendarToday, .calendarUpcoming, .remindersList,
        .mediaNowPlaying, .chromeListTabs, .chromePageInfo,
        .memoryQuery, .memorySummary
    ]

    /// Route and execute a complete ActionPlan.
    /// Swift-classified actions execute locally, Python ones go to the API.
    func executePlan(_ plan: ActionPlan) async -> [ActionResult] {
        var results: [ActionResult] = []

        for (index, action) in plan.actions.enumerated() {
            let stepNum = index + 1
            logMessage("━━ Step \(stepNum)/\(plan.actions.count): \(action.action.rawValue) — \(action.description)")

            let result: ActionResult
            if action.shouldExecuteInSwift {
                logMessage("   Running locally in Swift...")
                result = await executeLocally(action)
            } else {
                logMessage("   Sending to Python backend...")
                result = await executePython(action)
            }

            results.append(result)

            let status = result.success ? "✅" : "❌"
            logMessage("   \(status) \(result.message ?? "Done")")

            // Auto-speak results for query actions
            if speakResultActions.contains(action.action), result.success, let message = result.message {
                logMessage("🗣️  Speaking result: \(message)")
                try? await bridge.speak(text: message, blocking: false)
            }

            // Abort on fatal error
            if !result.success {
                // Continue on non-fatal errors
            }
        }

        let successCount = results.filter(\.success).count
        logMessage("✅ Plan complete: \(successCount)/\(results.count) steps succeeded")
        return results
    }

    // MARK: - Local Swift Execution

    private func executeLocally(_ action: Action) async -> ActionResult {
        do {
            switch action.action {
            // ── App Control ──────────────────────────────────────────────
            case .openApp:
                return await AppControl.openApp(action.app ?? "")

            case .closeApp:
                return await AppControl.closeApp(action.app ?? "")

            case .focusApp:
                return AppControl.focusApp(action.app ?? "")

            // ── System Control ───────────────────────────────────────────
            case .systemVolume:
                return SystemControl.setVolume(
                    level: action.level,
                    direction: action.direction,
                    mute: action.mute ?? false
                )

            case .systemBrightness:
                return SystemControl.setBrightness(
                    level: action.level,
                    direction: action.direction
                )

            case .systemDarkMode:
                return SystemControl.toggleDarkMode(enable: action.enable)

            case .systemDND:
                return SystemControl.toggleDND(enable: action.enable)

            case .systemBattery:
                return SystemControl.getBatteryStatus()

            // ── Input ────────────────────────────────────────────────────
            case .typeText:
                return InputControl.typeText(action.text ?? "")

            case .keystroke:
                return InputControl.sendKeystroke(action.keys ?? "")

            // ── Mouse / UI ───────────────────────────────────────────────
            case .clickAt:
                return InputControl.clickAt(
                    x: action.x ?? 0, y: action.y ?? 0,
                    double: action.doubleClick ?? false,
                    right: action.rightClick ?? false
                )

            case .scroll:
                return InputControl.scroll(
                    direction: action.direction ?? "down",
                    amount: action.amount ?? 3
                )

            case .drag:
                return InputControl.drag(
                    fromX: action.x ?? 0, fromY: action.y ?? 0,
                    toX: action.toX ?? 0, toY: action.toY ?? 0
                )

            case .axButton:
                return InputControl.axClickButton(
                    app: action.app ?? "",
                    buttonName: action.element ?? ""
                )

            case .axMenu:
                return InputControl.axClickMenu(
                    app: action.app ?? "",
                    menuPath: action.menuPath ?? []
                )

            case .axType:
                return InputControl.axTypeInField(
                    app: action.app ?? "",
                    fieldHint: action.fieldHint ?? "",
                    text: action.text ?? ""
                )

            // ── Media ────────────────────────────────────────────────────
            case .mediaPlayPause:
                return MediaControl.playPause(app: action.mediaApp)

            case .mediaNext:
                return MediaControl.nextTrack(app: action.mediaApp)

            case .mediaPrev:
                return MediaControl.prevTrack(app: action.mediaApp)

            case .mediaNowPlaying:
                return MediaControl.nowPlaying(app: action.mediaApp)

            case .mediaVolume:
                return MediaControl.setVolume(level: action.level ?? 50, app: action.mediaApp)

            // ── Clipboard ────────────────────────────────────────────────
            case .clipboardGet:
                return ClipboardControl.getClipboard()

            case .clipboardSet:
                return ClipboardControl.setClipboard(action.text ?? "")

            case .clipboardPaste:
                return ClipboardControl.paste()

            // ── Screenshot ───────────────────────────────────────────────
            case .screenshot:
                return ScreenCapture.takeScreenshot(
                    path: action.path,
                    windowOnly: action.windowOnly ?? false
                )

            // ── Files ────────────────────────────────────────────────────
            case .fileOpen:
                return AppControl.openFile(action.path ?? "")

            case .fileOpenFolder:
                return AppControl.openFolder(action.path ?? "")

            // ── Utility ──────────────────────────────────────────────────
            case .wait:
                let delay = action.delaySeconds ?? 1.0
                try await Task.sleep(nanoseconds: UInt64(delay * 1_000_000_000))
                return ActionResult(success: true, action: "wait", message: "Waited \(delay)s")

            case .speak:
                // Use Python TTS for now (best voice quality)
                try await bridge.speak(text: action.text ?? action.description, blocking: false)
                return ActionResult(success: true, action: "speak", message: "Spoke: \(action.text ?? "")")

            default:
                return ActionResult(success: false, action: action.action.rawValue,
                                    message: "No Swift handler for \(action.action.rawValue)")
            }
        } catch {
            return ActionResult(success: false, action: action.action.rawValue,
                                message: "Swift execution error: \(error.localizedDescription)",
                                error: error.localizedDescription)
        }
    }

    // MARK: - Python Execution

    private func executePython(_ action: Action) async -> ActionResult {
        do {
            return try await bridge.executeAction(action)
        } catch {
            return ActionResult(success: false, action: action.action.rawValue,
                                message: "Python execution error: \(error.localizedDescription)",
                                error: error.localizedDescription)
        }
    }
}
