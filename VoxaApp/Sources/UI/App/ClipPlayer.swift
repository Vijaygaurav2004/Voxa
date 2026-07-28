import Foundation
import AVFoundation

/// Tiny AVAudioPlayer wrapper for the Recordings list. Plays one clip at a time
/// (single-clip `toggle`) or a whole session in sequence (`playSession`), and
/// publishes which clip / session is currently playing.
///
/// A monotonically increasing `generation` token guards the sequential path: any
/// new `playSession` / `toggle` / `stop` bumps it, so a stale async clip fetch
/// that resolves late can't resume playback for a run the user already ended.
@MainActor
final class ClipPlayer: NSObject, ObservableObject {
    /// The id of the clip currently playing, or nil when stopped.
    @Published var playingID: Int?
    /// The session id currently playing sequentially, or nil.
    @Published var playingSessionID: String?

    private var player: AVAudioPlayer?

    /// Bumped by every new play/stop so in-flight sequences and fetches bail.
    private var generation = 0
    /// The sequential-playback loop, if one is running.
    private var sequenceTask: Task<Void, Never>?
    /// Resumed when the current clip finishes (or is interrupted) so the loop advances.
    private var finishContinuation: CheckedContinuation<Void, Never>?

    // MARK: - Single clip

    /// Toggle playback for `id`: stop if that lone clip is already playing,
    /// otherwise start a fresh player from `data` (cancelling any session/clip first).
    func toggle(id: Int, data: Data) {
        if playingSessionID == nil && playingID == id {
            stop()
            return
        }
        stop()
        _ = startPlaying(id: id, data: data)
    }

    // MARK: - Session (sequential)

    /// Play `clipIDs` in order for `sessionID`: fetch each clip's Data just-in-time,
    /// play it, and advance when it finishes. Toggling the same session stops it.
    /// The `generation` token captured at start is checked before every play step,
    /// so a late fetch can't restart a run the user has since replaced or stopped.
    func playSession(_ sessionID: String, clipIDs: [Int], fetch: @escaping (Int) async -> Data?) {
        if playingSessionID == sessionID {
            stop()
            return
        }
        stop()
        guard !clipIDs.isEmpty else { return }

        let gen = generation
        playingSessionID = sessionID

        sequenceTask = Task { @MainActor in
            for clipID in clipIDs {
                if gen != self.generation { break }
                guard let data = await fetch(clipID) else { continue }
                if gen != self.generation { break }
                guard self.startPlaying(id: clipID, data: data) else { continue }
                // Wait for this clip to finish naturally (delegate) or be interrupted.
                await withCheckedContinuation { (cont: CheckedContinuation<Void, Never>) in
                    self.finishContinuation = cont
                }
                if gen != self.generation { break }
            }
            if gen == self.generation { self.stop() }
        }
    }

    // MARK: - Stop

    func stop() {
        invalidate()
        player?.stop()
        player = nil
        playingID = nil
        playingSessionID = nil
    }

    // MARK: - Internals

    /// Start a fresh player for `id`. Returns whether playback actually began.
    private func startPlaying(id: Int, data: Data) -> Bool {
        player?.stop()
        do {
            let p = try AVAudioPlayer(data: data)
            p.delegate = self
            p.prepareToPlay()
            p.play()
            player = p
            playingID = id
            return true
        } catch {
            player = nil
            playingID = nil
            return false
        }
    }

    /// Bump the generation, cancel any running sequence, and unblock a waiting
    /// loop so it observes the new generation and bails.
    private func invalidate() {
        generation &+= 1
        sequenceTask?.cancel()
        sequenceTask = nil
        if let cont = finishContinuation {
            finishContinuation = nil
            cont.resume()
        }
    }

    /// Called when a clip finishes on its own: advance a session run, or clear a lone clip.
    private func handleFinish() {
        player = nil
        playingID = nil
        if let cont = finishContinuation {
            finishContinuation = nil
            cont.resume()
        }
    }
}

extension ClipPlayer: AVAudioPlayerDelegate {
    nonisolated func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool) {
        Task { @MainActor in
            self.handleFinish()
        }
    }
}
