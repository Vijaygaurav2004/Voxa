import Foundation
import AVFoundation

/// Continuous meeting audio capture. Records the microphone in fixed windows and
/// streams each speech-containing chunk to the backend's /api/memory/ingest.
///
/// This runs in the Swift app on purpose: the app reliably holds macOS microphone
/// permission, whereas the spawned Python backend process may not — which is why
/// meeting notes came back empty when capture lived in Python.
final class MeetingCapture {
    private var engine: AVAudioEngine?
    private var isRunning = false
    private var isPaused = false

    private let targetSampleRate: Double = 16000.0
    private let chunkSeconds: Double = 20.0        // window length before flushing
    private let silenceThresholdDB: Float = -52.0  // below this = silence (sensitive to quiet speech)

    // Accumulated 16kHz mono Int16 PCM for the current window (touched only on the
    // audio tap thread, and on stop() after the tap is removed).
    private var pcm = Data()
    private var speechInWindow = false

    func start() {
        guard !isRunning else { return }
        isRunning = true
        isPaused = false
        pcm = Data()
        speechInWindow = false

        let engine = AVAudioEngine()
        self.engine = engine
        let input = engine.inputNode
        let inputFormat = input.outputFormat(forBus: 0)

        guard inputFormat.sampleRate > 0,
              let outFormat = AVAudioFormat(commonFormat: .pcmFormatInt16,
                                            sampleRate: targetSampleRate,
                                            channels: 1, interleaved: true),
              let converter = AVAudioConverter(from: inputFormat, to: outFormat) else {
            appLog("❌ MeetingCapture: could not set up audio format")
            isRunning = false
            return
        }

        let bytesPerWindow = Int(targetSampleRate * chunkSeconds) * 2 // Int16

        input.installTap(onBus: 0, bufferSize: 4096, format: inputFormat) { [weak self] buffer, _ in
            guard let self, self.isRunning, !self.isPaused else { return }

            if self.rmsDB(buffer) > self.silenceThresholdDB {
                self.speechInWindow = true
            }
            if let data = self.convert(buffer, converter: converter, outputFormat: outFormat) {
                self.pcm.append(data)
            }
            if self.pcm.count >= bytesPerWindow {
                self.flush()
            }
        }

        do {
            try engine.start()
            appLog("🎙️ MeetingCapture streaming started (\(Int(inputFormat.sampleRate))Hz)")
        } catch {
            appLog("❌ MeetingCapture engine start failed: \(error.localizedDescription)")
            teardown()
        }
    }

    func pause() { isPaused = true }
    func resume() { isPaused = false }

    func stop() {
        guard isRunning else { return }
        engine?.inputNode.removeTap(onBus: 0)   // stop the tap first…
        flush()                                  // …then flush any trailing audio
        teardown()
        appLog("🛑 MeetingCapture stopped")
    }

    private func teardown() {
        isRunning = false
        engine?.stop()
        engine = nil
        pcm = Data()
        speechInWindow = false
    }

    /// Snapshot the current window and POST it if it contained speech.
    private func flush() {
        let data = pcm
        let hadSpeech = speechInWindow
        pcm = Data()
        speechInWindow = false
        guard hadSpeech, data.count > 3200 else { return }   // ≥0.1s of audio

        let wav = Self.wrapWAV(pcm: data, sampleRate: Int(targetSampleRate))
        Task { try? await PythonBridge.shared.ingestMemoryChunk(wav, source: "mic") }
    }

    // MARK: - Audio helpers

    private func rmsDB(_ buffer: AVAudioPCMBuffer) -> Float {
        guard let ch = buffer.floatChannelData else { return -100 }
        let n = Int(buffer.frameLength)
        guard n > 0 else { return -100 }
        var sum: Float = 0
        for i in 0..<n { let s = ch[0][i]; sum += s * s }
        return 20 * log10(max(sqrt(sum / Float(n)), 1e-10))
    }

    private func convert(_ input: AVAudioPCMBuffer, converter: AVAudioConverter, outputFormat: AVAudioFormat) -> Data? {
        let ratio = outputFormat.sampleRate / input.format.sampleRate
        let capacity = AVAudioFrameCount(Double(input.frameLength) * ratio)
        guard capacity > 0,
              let out = AVAudioPCMBuffer(pcmFormat: outputFormat, frameCapacity: capacity) else { return nil }

        var err: NSError?
        var fed = false
        converter.convert(to: out, error: &err) { _, status in
            if fed { status.pointee = .noDataNow; return nil }
            fed = true
            status.pointee = .haveData
            return input
        }
        guard err == nil, out.frameLength > 0, let src = out.int16ChannelData else { return nil }
        let bytes = Int(out.frameLength) * Int(outputFormat.streamDescription.pointee.mBytesPerFrame)
        return Data(bytes: src[0], count: bytes)
    }

    static func wrapWAV(pcm: Data, sampleRate: Int, channels: Int = 1) -> Data {
        var wav = Data()
        let bitsPerSample = 16
        let blockAlign = channels * bitsPerSample / 8
        let byteRate = sampleRate * blockAlign
        let dataSize = pcm.count
        func u32(_ v: Int) -> Data { withUnsafeBytes(of: UInt32(v).littleEndian) { Data($0) } }
        func u16(_ v: Int) -> Data { withUnsafeBytes(of: UInt16(v).littleEndian) { Data($0) } }
        wav.append("RIFF".data(using: .ascii)!); wav.append(u32(36 + dataSize)); wav.append("WAVE".data(using: .ascii)!)
        wav.append("fmt ".data(using: .ascii)!); wav.append(u32(16)); wav.append(u16(1)); wav.append(u16(channels))
        wav.append(u32(sampleRate)); wav.append(u32(byteRate)); wav.append(u16(blockAlign)); wav.append(u16(bitsPerSample))
        wav.append("data".data(using: .ascii)!); wav.append(u32(dataSize)); wav.append(pcm)
        return wav
    }
}
