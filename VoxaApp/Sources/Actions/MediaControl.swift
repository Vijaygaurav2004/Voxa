import Foundation

/// Media control using AppleScript for Spotify/Music app integration.
/// Replaces Python media_control.py.
enum MediaControl {

    static func playPause(app: String?) -> ActionResult {
        let target = app ?? "Spotify"
        runAS("tell application \"\(target)\" to playpause")
        return ActionResult(success: true, action: "media_play_pause",
                            message: "Toggled play/pause on \(target)")
    }

    static func nextTrack(app: String?) -> ActionResult {
        let target = app ?? "Spotify"
        runAS("tell application \"\(target)\" to next track")
        return ActionResult(success: true, action: "media_next",
                            message: "Skipped to next track on \(target)")
    }

    static func prevTrack(app: String?) -> ActionResult {
        let target = app ?? "Spotify"
        runAS("tell application \"\(target)\" to previous track")
        return ActionResult(success: true, action: "media_prev",
                            message: "Went to previous track on \(target)")
    }

    static func nowPlaying(app: String?) -> ActionResult {
        let target = app ?? "Spotify"
        let script = """
        tell application "\(target)"
            if player state is playing then
                set trackName to name of current track
                set artistName to artist of current track
                return "Now playing: " & trackName & " by " & artistName
            else
                return "\(target) is not currently playing"
            end if
        end tell
        """
        let result = runAS(script) ?? "\(target) is not running"
        return ActionResult(success: true, action: "media_now_playing", message: result)
    }

    static func setVolume(level: Int, app: String?) -> ActionResult {
        let target = app ?? "Spotify"
        let clamped = max(0, min(100, level))
        runAS("tell application \"\(target)\" to set sound volume to \(clamped)")
        return ActionResult(success: true, action: "media_volume",
                            message: "\(target) volume set to \(clamped)%")
    }

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
