import Foundation
import AVFoundation

/// Native macOS voice capture using AVAudioEngine.
/// Replaces Python's sounddevice + webrtcvad approach with Apple's native audio APIs.
/// Much better Bluetooth device handling and lower latency.
final class VoiceCapture {
    private var audioEngine: AVAudioEngine?
    private var isRecording = false

    // Audio format: 16kHz mono Int16 (matches Whisper API input)
    private let targetSampleRate: Double = 16000.0
    private let targetChannels: AVAudioChannelCount = 1

    // Silence detection
    private let silenceThresholdDB: Float = -40.0 // dBFS threshold for silence
    private let silenceDurationSeconds: Double = 0.7 // How long silence must last to stop
    private let maxRecordingDuration: Double = 30.0
    private let minRecordingDuration: Double = 0.5

    init() {
        appLog("🎧 VoiceCapture initialized (AVAudioEngine)")
    }

    /// Record audio from the microphone until silence is detected.
    /// Returns WAV audio data at 16kHz mono, ready for Whisper API.
    func recordUntilSilence() async -> Data? {
        return await withCheckedContinuation { continuation in
            recordUntilSilenceAsync { data in
                continuation.resume(returning: data)
            }
        }
    }

    private func recordUntilSilenceAsync(completion: @escaping (Data?) -> Void) {
        guard !isRecording else {
            completion(nil)
            return
        }

        isRecording = true
        let engine = AVAudioEngine()
        self.audioEngine = engine

        let inputNode = engine.inputNode
        let inputFormat = inputNode.outputFormat(forBus: 0)

        // Target format for recording (16kHz mono)
        guard let recordingFormat = AVAudioFormat(
            commonFormat: .pcmFormatInt16,
            sampleRate: targetSampleRate,
            channels: targetChannels,
            interleaved: true
        ) else {
            appLog("❌ Could not create recording format")
            isRecording = false
            completion(nil)
            return
        }

        // Converter from input format to target format
        guard let converter = AVAudioConverter(from: inputFormat, to: recordingFormat) else {
            appLog("❌ Could not create audio converter from \(inputFormat.sampleRate)Hz to \(targetSampleRate)Hz")
            isRecording = false
            completion(nil)
            return
        }

        var audioBuffers: [Data] = []
        var speechDetected = false
        var silenceFrameCount = 0
        let framesPerBuffer = UInt32(inputFormat.sampleRate * 0.03) // 30ms frames
        let silenceFrameThreshold = Int(silenceDurationSeconds / 0.03)
        let maxFrames = Int(maxRecordingDuration / 0.03)
        var totalFrames = 0

        let bufferSize = AVAudioFrameCount(4096)

        inputNode.installTap(onBus: 0, bufferSize: bufferSize, format: inputFormat) { [weak self] buffer, time in
            guard let self = self, self.isRecording else { return }

            totalFrames += 1
            if totalFrames >= maxFrames {
                self.stopRecording(engine: engine, completion: completion, buffers: audioBuffers, speechDetected: speechDetected)
                return
            }

            // Calculate RMS level
            let level = self.calculateRMS(buffer: buffer)
            let isSpeech = level > self.silenceThresholdDB

            if isSpeech {
                if !speechDetected {
                    speechDetected = true
                    appLog("🗣️  Speech detected — recording...")

                    // Update audio level on main thread
                    DispatchQueue.main.async {
                        VoxaState.shared.audioLevel = self.normalizeDB(level)
                    }
                }
                silenceFrameCount = 0

                // Convert and store buffer
                if let convertedData = self.convertBuffer(buffer, converter: converter, outputFormat: recordingFormat) {
                    audioBuffers.append(convertedData)
                }
            } else if speechDetected {
                silenceFrameCount += 1

                // Still collect audio during silence (captures trailing words)
                if let convertedData = self.convertBuffer(buffer, converter: converter, outputFormat: recordingFormat) {
                    audioBuffers.append(convertedData)
                }

                if silenceFrameCount >= silenceFrameThreshold {
                    appLog("🔇 Silence detected — stopping recording")
                    self.stopRecording(engine: engine, completion: completion, buffers: audioBuffers, speechDetected: speechDetected)
                    return
                }
            }

            // Update audio level visualization
            DispatchQueue.main.async {
                VoxaState.shared.audioLevel = self.normalizeDB(level)
            }
        }

        do {
            try engine.start()
            appLog("🎤 Listening... (AVAudioEngine, \(inputFormat.sampleRate)Hz)")
        } catch {
            appLog("❌ Audio engine start failed: \(error)")
            isRecording = false
            completion(nil)
        }
    }

    private func stopRecording(engine: AVAudioEngine, completion: @escaping (Data?) -> Void, buffers: [Data], speechDetected: Bool) {
        guard isRecording else { return }
        isRecording = false

        engine.inputNode.removeTap(onBus: 0)
        engine.stop()

        DispatchQueue.main.async {
            VoxaState.shared.audioLevel = 0
        }

        guard speechDetected, !buffers.isEmpty else {
            completion(nil)
            return
        }

        // Combine all buffers into a single PCM data block
        var pcmData = Data()
        for buffer in buffers {
            pcmData.append(buffer)
        }

        // Check minimum duration
        let sampleCount = pcmData.count / 2 // Int16 = 2 bytes per sample
        let duration = Double(sampleCount) / targetSampleRate
        guard duration >= minRecordingDuration else {
            appLog("⚠️ Recording too short (\(String(format: "%.2f", duration))s), discarding")
            completion(nil)
            return
        }

        appLog("📝 Recorded \(String(format: "%.2f", duration))s of audio")

        // Wrap in WAV format
        let wavData = createWAV(from: pcmData, sampleRate: Int(targetSampleRate), channels: 1)
        completion(wavData)
    }

    func stop() {
        isRecording = false
        audioEngine?.inputNode.removeTap(onBus: 0)
        audioEngine?.stop()
        audioEngine = nil
    }

    // MARK: - Audio Helpers

    private func calculateRMS(buffer: AVAudioPCMBuffer) -> Float {
        guard let channelData = buffer.floatChannelData else { return -100 }
        let channelSamples = channelData[0]
        let count = Int(buffer.frameLength)
        guard count > 0 else { return -100 }

        var sum: Float = 0
        for i in 0..<count {
            let sample = channelSamples[i]
            sum += sample * sample
        }
        let rms = sqrt(sum / Float(count))
        let db = 20 * log10(max(rms, 1e-10))
        return db
    }

    private func normalizeDB(_ db: Float) -> Float {
        // Convert dBFS to 0-1 range (-60dB = 0, 0dB = 1)
        let clamped = max(-60, min(0, db))
        return (clamped + 60) / 60
    }

    private func convertBuffer(_ inputBuffer: AVAudioPCMBuffer, converter: AVAudioConverter, outputFormat: AVAudioFormat) -> Data? {
        let ratio = outputFormat.sampleRate / inputBuffer.format.sampleRate
        let outputFrameCount = AVAudioFrameCount(Double(inputBuffer.frameLength) * ratio)
        guard let outputBuffer = AVAudioPCMBuffer(pcmFormat: outputFormat, frameCapacity: outputFrameCount) else {
            return nil
        }

        var error: NSError?
        var hasData = true
        converter.convert(to: outputBuffer, error: &error) { inNumPackets, outStatus in
            if hasData {
                outStatus.pointee = .haveData
                hasData = false
                return inputBuffer
            }
            outStatus.pointee = .noDataNow
            return nil
        }

        if let error = error {
            print("⚠️ Audio conversion error: \(error)")
            return nil
        }

        guard outputBuffer.frameLength > 0 else { return nil }
        let byteCount = Int(outputBuffer.frameLength) * Int(outputFormat.streamDescription.pointee.mBytesPerFrame)
        return Data(bytes: outputBuffer.int16ChannelData![0], count: byteCount)
    }

    private func createWAV(from pcmData: Data, sampleRate: Int, channels: Int) -> Data {
        var wav = Data()
        let bitsPerSample = 16
        let bytesPerSample = bitsPerSample / 8
        let blockAlign = channels * bytesPerSample
        let byteRate = sampleRate * blockAlign
        let dataSize = pcmData.count
        let chunkSize = 36 + dataSize

        // RIFF header
        wav.append("RIFF".data(using: .ascii)!)
        wav.append(withUnsafeBytes(of: UInt32(chunkSize).littleEndian) { Data($0) })
        wav.append("WAVE".data(using: .ascii)!)

        // fmt sub-chunk
        wav.append("fmt ".data(using: .ascii)!)
        wav.append(withUnsafeBytes(of: UInt32(16).littleEndian) { Data($0) }) // Sub-chunk size
        wav.append(withUnsafeBytes(of: UInt16(1).littleEndian) { Data($0) })  // PCM format
        wav.append(withUnsafeBytes(of: UInt16(channels).littleEndian) { Data($0) })
        wav.append(withUnsafeBytes(of: UInt32(sampleRate).littleEndian) { Data($0) })
        wav.append(withUnsafeBytes(of: UInt32(byteRate).littleEndian) { Data($0) })
        wav.append(withUnsafeBytes(of: UInt16(blockAlign).littleEndian) { Data($0) })
        wav.append(withUnsafeBytes(of: UInt16(bitsPerSample).littleEndian) { Data($0) })

        // data sub-chunk
        wav.append("data".data(using: .ascii)!)
        wav.append(withUnsafeBytes(of: UInt32(dataSize).littleEndian) { Data($0) })
        wav.append(pcmData)

        return wav
    }
}
