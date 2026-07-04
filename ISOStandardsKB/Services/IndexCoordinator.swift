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
}
