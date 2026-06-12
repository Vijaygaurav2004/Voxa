import Foundation
import AppKit

/// Clipboard operations using NSPasteboard.
/// Replaces Python clipboard.py with direct Cocoa API.
enum ClipboardControl {

    /// Read clipboard contents.
    static func getClipboard() -> ActionResult {
        let pasteboard = NSPasteboard.general
        if let text = pasteboard.string(forType: .string) {
            let preview = String(text.prefix(200))
            return ActionResult(success: true, action: "clipboard_get",
                                message: "Clipboard: \(preview)")
        }
        return ActionResult(success: true, action: "clipboard_get",
                            message: "Clipboard is empty or contains non-text data")
    }

    /// Set clipboard contents.
    static func setClipboard(_ text: String) -> ActionResult {
        let pasteboard = NSPasteboard.general
        pasteboard.clearContents()
        pasteboard.setString(text, forType: .string)
        return ActionResult(success: true, action: "clipboard_set",
                            message: "Copied to clipboard: \(String(text.prefix(50)))")
    }

    /// Paste clipboard via ⌘+V.
    static func paste() -> ActionResult {
        return InputControl.sendKeystroke("cmd+v")
    }
}
