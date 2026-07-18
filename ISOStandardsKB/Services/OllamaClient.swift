import Darwin
import Foundation

/// Direct Ollama HTTP client for optional native-side calls.
final class OllamaClient {
    static let shared = OllamaClient()

    private let baseURL = URL(string: "http://127.0.0.1:11434")!
    private let session = URLSession.shared

    func isAvailable() async -> Bool {
        var request = URLRequest(url: baseURL.appendingPathComponent("api/tags"))
        request.httpMethod = "GET"
        request.timeoutInterval = 3
        do {
            let (_, response) = try await session.data(for: request)
            return (response as? HTTPURLResponse)?.statusCode == 200
        } catch {
            return false
        }
    }
}

/// Owns an Ollama server started by ISOStandardsKB.
///
/// A server that was already running is left untouched. This prevents the app
/// from terminating Ollama sessions owned by another application or terminal.
@MainActor
final class OllamaProcessManager {
    static let shared = OllamaProcessManager()

    private var process: Process?
    private var logHandle: FileHandle?
    private var ownsProcess = false

    private init() {}

    /// Starts `ollama serve` when no Ollama server is already available and
    /// waits until its HTTP API responds.
    @discardableResult
    func startIfNeeded(timeout: TimeInterval = 30) async -> Bool {
        if await OllamaClient.shared.isAvailable() {
            return true
        }

        if let process, process.isRunning {
            return await waitUntilReady(process: process, timeout: timeout)
        }

        guard let executableURL = Self.findExecutable() else {
            NSLog("ISOStandardsKB: Ollama executable was not found")
            return false
        }

        do {
            let handle = try makeLogHandle()
            let process = Process()
            process.executableURL = executableURL
            process.arguments = ["serve"]

            var environment = ProcessInfo.processInfo.environment
            environment["OLLAMA_HOST"] = "127.0.0.1:11434"
            process.environment = environment
            process.standardOutput = handle
            process.standardError = handle

            // Retain resources before launching so a failed run can close them.
            self.process = process
            self.logHandle = handle
            try process.run()
            self.ownsProcess = true

            let ready = await waitUntilReady(process: process, timeout: timeout)
            if !ready {
                NSLog("ISOStandardsKB: Ollama did not become ready within %.0f seconds", timeout)
                stopIfOwned()
            }
            return ready
        } catch {
            NSLog("ISOStandardsKB: Failed to start Ollama: %@", error.localizedDescription)
            try? logHandle?.close()
            logHandle = nil
            process = nil
            ownsProcess = false
            return false
        }
    }

    /// Stops Ollama only when this app started the server. The app waits for a
    /// graceful exit, then terminates the exact owned PID if it does not stop.
    func stopIfOwned(gracePeriod: TimeInterval = 3) {
        guard ownsProcess else { return }

        defer {
            ownsProcess = false
            process = nil
            try? logHandle?.close()
            logHandle = nil
        }

        guard let ownedProcess = process, ownedProcess.isRunning else {
            return
        }

        let pid = ownedProcess.processIdentifier
        ownedProcess.terminate()

        let deadline = Date().addingTimeInterval(gracePeriod)
        while ownedProcess.isRunning && Date() < deadline {
            Thread.sleep(forTimeInterval: 0.05)
        }

        guard ownedProcess.isRunning else { return }

        NSLog("ISOStandardsKB: Ollama PID %d ignored SIGTERM; sending SIGKILL", pid)
        if Darwin.kill(pid, SIGKILL) == 0 {
            ownedProcess.waitUntilExit()
        } else {
            NSLog("ISOStandardsKB: Failed to stop Ollama PID %d", pid)
        }
    }

    private func waitUntilReady(process: Process, timeout: TimeInterval) async -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if await OllamaClient.shared.isAvailable() {
                return true
            }
            if !process.isRunning {
                return false
            }
            try? await Task.sleep(nanoseconds: 500_000_000)
        }
        return false
    }

    private static func findExecutable() -> URL? {
        let candidates = [
            "/usr/local/bin/ollama",
            "/opt/homebrew/bin/ollama",
            "/Applications/Ollama.app/Contents/Resources/ollama"
        ]

        return candidates
            .first(where: FileManager.default.isExecutableFile(atPath:))
            .map(URL.init(fileURLWithPath:))
    }

    private func makeLogHandle() throws -> FileHandle {
        let logsDirectory = AppConfig.appSupportDir
            .appendingPathComponent("Logs", isDirectory: true)
        try FileManager.default.createDirectory(
            at: logsDirectory,
            withIntermediateDirectories: true
        )

        let logURL = logsDirectory.appendingPathComponent("ollama.log")
        if !FileManager.default.fileExists(atPath: logURL.path) {
            _ = FileManager.default.createFile(atPath: logURL.path, contents: nil)
        }

        let handle = try FileHandle(forWritingTo: logURL)
        try handle.seekToEnd()
        let marker = "\n--- ISOStandardsKB launched Ollama at \(Date()) ---\n"
        try handle.write(contentsOf: Data(marker.utf8))
        return handle
    }
}
