import Foundation

/// Global logging helper for the Voxa application.
/// Appends messages to the main run_app.log file.
public func appLog(_ message: String) {
    let logURL = URL(fileURLWithPath: "/Users/ananthadatta/Desktop/Voxa/VoxaApp/run_app.log")
    let formattedMessage = "[\(Date().description)] \(message)\n"
    if let data = formattedMessage.data(using: .utf8) {
        if let fileHandle = try? FileHandle(forWritingTo: logURL) {
            fileHandle.seekToEndOfFile()
            fileHandle.write(data)
            fileHandle.closeFile()
        } else {
            try? data.write(to: logURL)
        }
    }
}
