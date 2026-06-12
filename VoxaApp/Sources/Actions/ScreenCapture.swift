import Foundation
import AppKit

/// Screenshot capture using screencapture CLI.
/// Replaces Python screen_reader.py screenshot functionality.
enum ScreenCapture {

    /// Take a screenshot and save to a file.
    static func takeScreenshot(path: String?, windowOnly: Bool) -> ActionResult {
        let destination: String
        if let path = path {
            destination = (path as NSString).expandingTildeInPath
        } else {
            let formatter = DateFormatter()
            formatter.dateFormat = "yyyy-MM-dd_HH-mm-ss"
            let timestamp = formatter.string(from: Date())
            let desktop = NSHomeDirectory() + "/Desktop"
            destination = "\(desktop)/voxa_screenshot_\(timestamp).png"
        }

        var args = ["-x"] // silent (no camera sound)
        if windowOnly {
            args.append("-w") // window mode (user clicks to select)
        }
        args.append(destination)

        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/sbin/screencapture")
        process.arguments = args
        try? process.run()
        process.waitUntilExit()

        if process.terminationStatus == 0 {
            return ActionResult(success: true, action: "screenshot",
                                message: "Screenshot saved to \(destination)")
        }
        return ActionResult(success: false, action: "screenshot",
                            message: "Screenshot failed")
    }
}
