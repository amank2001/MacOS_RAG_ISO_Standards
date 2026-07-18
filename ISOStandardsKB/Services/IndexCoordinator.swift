import Foundation
import Combine

@MainActor
final class IndexCoordinator: ObservableObject {
    @Published var isIndexing = false
    @Published var lastMessage = ""
    @Published var progress: Double = 0

    private let backend = BackendClient.shared

    func importFolder(_ url: URL, watch: Bool = true) async {
        isIndexing = true
        lastMessage = "Indexing \(url.lastPathComponent)..."
        progress = 0
        defer { isIndexing = false }

        do {
            // Submit the ingest job, then poll its status until a terminal state.
            let jobId = try await backend.ingest(path: url.path, name: url.lastPathComponent)
            let status = try await pollUntilTerminal(jobId: jobId)

            switch status.status {
            case "completed":
                let indexed = status.result?.indexed ?? 0
                let errors = status.result?.errors ?? 0
                progress = 1
                lastMessage = "Indexed \(indexed) files (\(errors) errors)"
                if watch {
                    try await backend.startWatching(path: url.path)
                    lastMessage += " — watching for changes"
                }
            default: // "failed"
                lastMessage = "Indexing failed: \(status.error ?? "unknown error")"
            }
        } catch {
            lastMessage = "Indexing failed: \(error.localizedDescription)"
        }
    }

    func deleteFolder(_ library: Library, alsoTrash: Bool) async -> Result<BackendClient.DeletionResult, Error> {
        do {
            let result = try await backend.deleteLibrary(id: library.id)
            if alsoTrash {
                try FileManager.default.trashItem(
                    at: URL(fileURLWithPath: library.path),
                    resultingItemURL: nil
                )
            }
            return .success(result)
        } catch {
            return .failure(error)
        }
    }

    func deleteDocument(_ doc: ISODocument, alsoTrash: Bool) async -> Result<BackendClient.DeletionResult, Error> {
        do {
            let result = try await backend.deleteDocument(id: doc.id)
            if alsoTrash {
                try FileManager.default.trashItem(
                    at: URL(fileURLWithPath: doc.filePath),
                    resultingItemURL: nil
                )
            }
            return .success(result)
        } catch {
            return .failure(error)
        }
    }

    func rescanFolder(_ library: Library) async -> Result<[String: Any], Error> {
        isIndexing = true
        progress = 0
        defer { isIndexing = false }
        do {
            // Submit the ingest job, then poll its status until a terminal state.
            let jobId = try await backend.ingest(path: library.path, name: library.name)
            let status = try await pollUntilTerminal(jobId: jobId)

            switch status.status {
            case "completed":
                let indexed = status.result?.indexed ?? 0
                let skipped = status.result?.skipped ?? 0
                let errors = status.result?.errors ?? 0
                progress = 1
                lastMessage = "Rescan: \(indexed) new, \(skipped) skipped"
                let stats: [String: Any] = [
                    "indexed": indexed,
                    "skipped": skipped,
                    "errors": errors
                ]
                return .success(stats)
            default: // "failed"
                let message = status.error ?? "unknown error"
                lastMessage = "Rescan failed: \(message)"
                return .failure(NSError(
                    domain: "IndexCoordinator",
                    code: 1,
                    userInfo: [NSLocalizedDescriptionKey: message]
                ))
            }
        } catch {
            lastMessage = "Rescan failed: \(error.localizedDescription)"
            return .failure(error)
        }
    }

    /// Polls `ingestStatus` for the given job until it reaches a terminal state
    /// (`completed` or `failed`), sleeping briefly between polls. While the job
    /// is `queued`/`running`, `progress` is advanced in an indeterminate,
    /// bounded fashion to signal ongoing work.
    private func pollUntilTerminal(jobId: String) async throws -> BackendClient.IngestStatus {
        while true {
            let status = try await backend.ingestStatus(jobId: jobId)
            switch status.status {
            case "completed", "failed":
                return status
            default: // "queued" / "running"
                // Indeterminate progress: cycle within a bounded range so the UI
                // shows continuous activity without a real completion percentage.
                progress = progress >= 0.9 ? 0.1 : progress + 0.1
                try await Task.sleep(nanoseconds: 1_500_000_000) // 1.5s between polls
            }
        }
    }
}
