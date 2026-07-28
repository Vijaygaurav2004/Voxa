import Foundation
import AVFoundation
import ScreenCaptureKit

/// Captures the Mac's system audio output (i.e. the OTHER participants in a
/// meeting) via ScreenCaptureKit and streams it to the backend memory pipeline,
/// tagged as "system". Combined with MeetingCapture (the mic = this user), the
/// notes get BOTH sides of the conversation.
///
/// Requires Screen Recording permission (System Settings → Privacy & Security →
/// Screen Recording). Degrades gracefully to a logged hint if not granted.
final class SystemAudioCapture: NSObject, SCStreamOutput, SCStreamDelegate {
    private var stream: SCStream?
    private var isRunning = false
    private var isPaused = false

    private let audioQueue = DispatchQueue(label: "com.voxa.systemaudio")
    private let targetSampleRate: Double = 16000.0
    private let chunkSeconds: Double = 20.0
    private let silenceThresholdDB: Float = -50.0

    private var converter: AVAudioConverter?
    private var outFormat: AVAudioFormat?
    private var pcm = Data()
    private var speechInWindow = false

    func start() {
        guard !isRunning else { return }
        isRunning = true
        isPaused = false
        pcm = Data()
        speechInWindow = false
        Task { await self.startCapture() }
    }

    func pause() { isPaused = true }
    func resume() { isPaused = false }

    func stop() {
        guard isRunning else { return }
        isRunning = false
        let s = stream
        stream = nil
        Task {
            try? await s?.stopCapture()
            self.flush()
        }
        appLog("🛑 SystemAudioCapture stopped")
    }

    // MARK: - Setup

    private func startCapture() async {
        do {
            // Triggers the Screen Recording permission check/prompt on first use.
            let content = try await SCShareableContent.excludingDesktopWindows(false,
                                                                               onScreenWindowsOnly: false)
            guard let display = content.displays.first else {
                appLog("⚠️ SystemAudioCapture: no display available")
                isRunning = false
                return
            }

            let filter = SCContentFilter(display: display, excludingWindows: [])
            let config = SCStreamConfiguration()
            config.capturesAudio = true
            config.excludesCurrentProcessAudio = true   // don't capture Voxa's own TTS
            config.sampleRate = 48000
            config.channelCount = 2
            // Audio-only: minimal video config (we register no video output).
            config.width = 2
            config.height = 2
            config.minimumFrameInterval = CMTime(value: 1, timescale: 1)

            let stream = SCStream(filter: filter, configuration: config, delegate: self)
            try stream.addStreamOutput(self, type: .audio, sampleHandlerQueue: audioQueue)
            try await stream.startCapture()
            self.stream = stream
            appLog("🔊 SystemAudioCapture streaming other participants' audio")
        } catch {
            isRunning = false
            appLog("⚠️ SystemAudioCapture unavailable — grant Screen Recording permission "
                   + "(System Settings → Privacy & Security → Screen Recording). Error: \(error.localizedDescription)")
        }
    }

    // MARK: - SCStreamDelegate

    func stream(_ stream: SCStream, didStopWithError error: Error) {
        appLog("⚠️ SystemAudioCapture stopped with error: \(error.localizedDescription)")
        isRunning = false
    }

    // MARK: - SCStreamOutput

    func stream(_ stream: SCStream, didOutputSampleBuffer sampleBuffer: CMSampleBuffer, of type: SCStreamOutputType) {
        guard type == .audio, isRunning, !isPaused, sampleBuffer.isValid else { return }

        guard let fmtDesc = CMSampleBufferGetFormatDescription(sampleBuffer),
              let asbd = CMAudioFormatDescriptionGetStreamBasicDescription(fmtDesc),
              let srcFormat = AVAudioFormat(streamDescription: asbd) else { return }

        let frames = CMSampleBufferGetNumSamples(sampleBuffer)
        guard frames > 0,
              let srcBuffer = AVAudioPCMBuffer(pcmFormat: srcFormat, frameCapacity: AVAudioFrameCount(frames)) else { return }
        srcBuffer.frameLength = AVAudioFrameCount(frames)

        let status = CMSampleBufferCopyPCMDataIntoAudioBufferList(
            sampleBuffer, at: 0, frameCount: Int32(frames), into: srcBuffer.mutableAudioBufferList)
        guard status == noErr else { return }

        if rmsDB(srcBuffer) > silenceThresholdDB { speechInWindow = true }

        guard let data = convertToTarget(srcBuffer) else { return }
        pcm.append(data)

        let bytesPerWindow = Int(targetSampleRate * chunkSeconds) * 2
        if pcm.count >= bytesPerWindow { flush() }
    }

    // MARK: - Streaming

    private func flush() {
        let data = pcm
        let hadSpeech = speechInWindow
        pcm = Data()
        speechInWindow = false
        guard hadSpeech, data.count > 3200 else { return }
        let wav = MeetingCapture.wrapWAV(pcm: data, sampleRate: Int(targetSampleRate))
        Task { try? await PythonBridge.shared.ingestMemoryChunk(wav, source: "system") }
    }

    // MARK: - Conversion

    private func convertToTarget(_ input: AVAudioPCMBuffer) -> Data? {
        if outFormat == nil {
            outFormat = AVAudioFormat(commonFormat: .pcmFormatInt16,
                                      sampleRate: targetSampleRate, channels: 1, interleaved: true)
        }
        guard let outFormat else { return nil }
        if converter == nil || converter?.inputFormat != input.format {
            converter = AVAudioConverter(from: input.format, to: outFormat)
        }
        guard let converter else { return nil }

        let ratio = targetSampleRate / input.format.sampleRate
        let capacity = AVAudioFrameCount(Double(input.frameLength) * ratio) + 16
        guard let out = AVAudioPCMBuffer(pcmFormat: outFormat, frameCapacity: capacity) else { return nil }

        var err: NSError?
        var fed = false
        converter.convert(to: out, error: &err) { _, status in
            if fed { status.pointee = .noDataNow; return nil }
            fed = true
            status.pointee = .haveData
            return input
        }
        guard err == nil, out.frameLength > 0, let src = out.int16ChannelData else { return nil }
        let bytes = Int(out.frameLength) * Int(outFormat.streamDescription.pointee.mBytesPerFrame)
        return Data(bytes: src[0], count: bytes)
    }

    private func rmsDB(_ buffer: AVAudioPCMBuffer) -> Float {
        guard let ch = buffer.floatChannelData else { return 0 }   // non-float → assume audible
        let n = Int(buffer.frameLength)
        guard n > 0 else { return -100 }
        var sum: Float = 0
        for i in 0..<n { let s = ch[0][i]; sum += s * s }
        return 20 * log10(max(sqrt(sum / Float(n)), 1e-10))
    }
}
