import Foundation
import AppKit
import CoreGraphics

/// Native input control using CGEvent for keyboard/mouse simulation.
/// Replaces Python typing.py and computer_control.py mouse operations.
enum InputControl {

    // MARK: - Keyboard

    /// Type text at the current cursor position using CGEvent.
    static func typeText(_ text: String) -> ActionResult {
        // Use AppleScript keystroke for reliability (handles Unicode)
        let escaped = text.replacingOccurrences(of: "\\", with: "\\\\")
            .replacingOccurrences(of: "\"", with: "\\\"")
        let script = "tell application \"System Events\" to keystroke \"\(escaped)\""
        runAS(script)
        return ActionResult(success: true, action: "type_text",
                            message: "Typed: \(String(text.prefix(50)))")
    }

    /// Send a keyboard shortcut (e.g. "cmd+s", "return", "escape").
    static func sendKeystroke(_ keys: String) -> ActionResult {
        let parts = keys.lowercased().split(separator: "+").map(String.init)
        var modifiers: [String] = []
        var key = ""

        for part in parts {
            switch part.trimmingCharacters(in: .whitespaces) {
            case "cmd", "command": modifiers.append("command down")
            case "shift": modifiers.append("shift down")
            case "alt", "option": modifiers.append("option down")
            case "ctrl", "control": modifiers.append("control down")
            default: key = part.trimmingCharacters(in: .whitespaces)
            }
        }

        // Special keys mapping to key codes
        let specialKeys: [String: Int] = [
            "return": 36, "enter": 36, "escape": 53, "esc": 53,
            "tab": 48, "space": 49, "delete": 51, "backspace": 51,
            "up": 126, "down": 125, "left": 123, "right": 124,
            "f1": 122, "f2": 120, "f3": 99, "f4": 118,
            "f5": 96, "f6": 97, "f7": 98, "f8": 100,
            "f9": 101, "f10": 109, "f11": 103, "f12": 111,
        ]

        let modifierStr = modifiers.isEmpty ? "" : " using {\(modifiers.joined(separator: ", "))}"

        if let keyCode = specialKeys[key] {
            runAS("tell application \"System Events\" to key code \(keyCode)\(modifierStr)")
        } else if key.count == 1 {
            runAS("tell application \"System Events\" to keystroke \"\(key)\"\(modifierStr)")
        } else {
            // Try as literal keystroke
            runAS("tell application \"System Events\" to keystroke \"\(key)\"\(modifierStr)")
        }

        return ActionResult(success: true, action: "keystroke", message: "Pressed \(keys)")
    }

    // MARK: - Mouse

    /// Click at screen coordinates.
    static func clickAt(x: Int, y: Int, double: Bool = false, right: Bool = false) -> ActionResult {
        let point = CGPoint(x: x, y: y)

        let mouseDown: CGEventType = right ? .rightMouseDown : .leftMouseDown
        let mouseUp: CGEventType = right ? .rightMouseUp : .leftMouseUp
        let button: CGMouseButton = right ? .right : .left

        if let downEvent = CGEvent(mouseEventSource: nil, mouseType: mouseDown, mouseCursorPosition: point, mouseButton: button),
           let upEvent = CGEvent(mouseEventSource: nil, mouseType: mouseUp, mouseCursorPosition: point, mouseButton: button) {

            let clicks = double ? 2 : 1
            for i in 0..<clicks {
                downEvent.setIntegerValueField(.mouseEventClickState, value: Int64(i + 1))
                upEvent.setIntegerValueField(.mouseEventClickState, value: Int64(i + 1))
                downEvent.post(tap: .cghidEventTap)
                upEvent.post(tap: .cghidEventTap)
                if double && i == 0 {
                    Thread.sleep(forTimeInterval: 0.05)
                }
            }
        }

        let action = right ? "Right-clicked" : (double ? "Double-clicked" : "Clicked")
        return ActionResult(success: true, action: "click_at", message: "\(action) at (\(x), \(y))")
    }

    /// Scroll in the focused window.
    static func scroll(direction: String, amount: Int) -> ActionResult {
        let delta = direction == "down" ? -Int32(amount * 10) : Int32(amount * 10)

        if let event = CGEvent(scrollWheelEvent2Source: nil, units: .pixel, wheelCount: 1, wheel1: delta, wheel2: 0, wheel3: 0) {
            event.post(tap: .cghidEventTap)
        }

        return ActionResult(success: true, action: "scroll", message: "Scrolled \(direction)")
    }

    /// Click and drag between two points.
    static func drag(fromX: Int, fromY: Int, toX: Int, toY: Int) -> ActionResult {
        let from = CGPoint(x: fromX, y: fromY)
        let to = CGPoint(x: toX, y: toY)

        if let downEvent = CGEvent(mouseEventSource: nil, mouseType: .leftMouseDown, mouseCursorPosition: from, mouseButton: .left) {
            downEvent.post(tap: .cghidEventTap)
        }

        Thread.sleep(forTimeInterval: 0.1)

        // Interpolate drag path
        let steps = 20
        for i in 1...steps {
            let fraction = CGFloat(i) / CGFloat(steps)
            let midPoint = CGPoint(
                x: from.x + (to.x - from.x) * fraction,
                y: from.y + (to.y - from.y) * fraction
            )
            if let dragEvent = CGEvent(mouseEventSource: nil, mouseType: .leftMouseDragged, mouseCursorPosition: midPoint, mouseButton: .left) {
                dragEvent.post(tap: .cghidEventTap)
            }
            Thread.sleep(forTimeInterval: 0.01)
        }

        if let upEvent = CGEvent(mouseEventSource: nil, mouseType: .leftMouseUp, mouseCursorPosition: to, mouseButton: .left) {
            upEvent.post(tap: .cghidEventTap)
        }

        return ActionResult(success: true, action: "drag",
                            message: "Dragged from (\(fromX),\(fromY)) to (\(toX),\(toY))")
    }

    // MARK: - Accessibility UI Control

    /// Click a button by name in any app via Accessibility API.
    static func axClickButton(app: String, buttonName: String) -> ActionResult {
        let script = """
        tell application "System Events"
            tell process "\(app)"
                click button "\(buttonName)" of window 1
            end tell
        end tell
        """
        runAS(script)
        return ActionResult(success: true, action: "ax_button",
                            message: "Clicked '\(buttonName)' in \(app)")
    }

    /// Click a menu item by path.
    static func axClickMenu(app: String, menuPath: [String]) -> ActionResult {
        guard menuPath.count >= 2 else {
            return ActionResult(success: false, action: "ax_menu",
                                message: "Menu path must have at least 2 items")
        }

        let menu = menuPath[0]
        let item = menuPath[1]

        let script = """
        tell application "\(app)" to activate
        delay 0.3
        tell application "System Events"
            tell process "\(app)"
                click menu item "\(item)" of menu "\(menu)" of menu bar item "\(menu)" of menu bar 1
            end tell
        end tell
        """
        runAS(script)
        return ActionResult(success: true, action: "ax_menu",
                            message: "Clicked menu: \(menuPath.joined(separator: " → "))")
    }

    /// Type in a named text field.
    static func axTypeInField(app: String, fieldHint: String, text: String) -> ActionResult {
        let script = """
        tell application "System Events"
            tell process "\(app)"
                set flds to every text field of window 1
                repeat with f in flds
                    if description of f contains "\(fieldHint)" or value of f contains "\(fieldHint)" then
                        click f
                        delay 0.2
                        set value of f to "\(text)"
                        return "ok"
                    end if
                end repeat
                if (count of flds) > 0 then
                    click (first item of flds)
                    delay 0.2
                    keystroke "\(text)"
                    return "ok"
                end if
            end tell
        end tell
        """
        runAS(script)
        return ActionResult(success: true, action: "ax_type",
                            message: "Typed '\(String(text.prefix(30)))' in \(app)")
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
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        return String(data: data, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines)
    }
}
