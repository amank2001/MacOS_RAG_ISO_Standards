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
        defer { isIndexing = false }

        do {
            let stats = try await backend.ingest(path: url.path, name: url.lastPathComponent)
            let indexed = stats["indexed"] as? Int ?? 0
            let errors = stats["errors"] as? Int ?? 0
            lastMessage = "Indexed \(indexed) files (\(errors) errors)"
            if watch {
                try await backend.startWatching(path: url.path)
                lastMessage += " — watching for changes"
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
        defer { isIndexing = false }
        do {
            let stats = try await backend.ingest(path: library.path, name: library.name)
            let indexed = stats["indexed"] as? Int ?? 0
            let skipped = stats["skipped"] as? Int ?? 0
            lastMessage = "Rescan: \(indexed) new, \(skipped) skipped"
            return .success(stats)
        } catch {
            lastMessage = "Rescan failed: \(error.localizedDescription)"
            return .failure(error)
        }
    }
}
