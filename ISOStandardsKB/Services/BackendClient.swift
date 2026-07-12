import Foundation

enum AppConfig {
    static let apiBaseURL = URL(string: "http://127.0.0.1:8742")!
    static let appSupportDir = FileManager.default.urls(
        for: .applicationSupportDirectory,
        in: .userDomainMask
    ).first!.appendingPathComponent("ISOStandardsKB", isDirectory: true)

    static var dbPath: URL {
        appSupportDir.appendingPathComponent("library.db")
    }

    static var figuresPath: URL {
        appSupportDir.appendingPathComponent("figures", isDirectory: true)
    }
}

final class BackendClient: ObservableObject {
    static let shared = BackendClient()

    // MARK: - Nested response types

    struct DeletionResult: Decodable {
        let status: String
        let removed: Int?
        let figureErrors: [FigureError]
        let watcherError: String?

        enum CodingKeys: String, CodingKey {
            case status
            case removed
            case figureErrors = "figure_errors"
            case watcherError = "watcher_error"
        }
    }

    struct FigureError: Decodable, Hashable {
        let imagePath: String
        let error: String

        enum CodingKeys: String, CodingKey {
            case imagePath = "image_path"
            case error
        }
    }

    @Published var isConnected = false
    @Published var ollamaAvailable = false

    private let session: URLSession
    private let decoder: JSONDecoder

    init(session: URLSession = .shared) {
        self.session = session
        self.decoder = JSONDecoder()
    }

    func checkHealth() async {
        do {
            let health: HealthResponse = try await get("/health")
            await MainActor.run {
                self.isConnected = health.status == "ok"
                self.ollamaAvailable = health.ollamaAvailable
            }
        } catch {
            await MainActor.run {
                self.isConnected = false
                self.ollamaAvailable = false
            }
        }
    }

    func listLibraries() async throws -> [Library] {
        try await get("/libraries")
    }

    func listDocuments(libraryId: Int? = nil) async throws -> [ISODocument] {
        var path = "/documents"
        if let libraryId {
            path += "?library_id=\(libraryId)"
        }
        return try await get(path)
    }

    func listClauses(documentId: Int) async throws -> [Clause] {
        try await get("/documents/\(documentId)/clauses")
    }

    func listFigures(documentId: Int) async throws -> [Figure] {
        try await get("/documents/\(documentId)/figures")
    }

    func deleteLibrary(id: Int) async throws -> DeletionResult {
        try await delete("/libraries/\(id)")
    }

    func deleteDocument(id: Int) async throws -> DeletionResult {
        try await delete("/documents/\(id)")
    }

    func ingest(path: String, name: String? = nil, noEmbed: Bool = false) async throws -> [String: Any] {
        let body: [String: Any] = [
            "path": path,
            "name": name as Any,
            "no_embed": noEmbed
        ]
        return try await postJSON("/ingest", body: body)
    }

    func search(query: String, standardId: String? = nil, mode: SearchMode = .hybrid, limit: Int = 20) async throws -> [SearchResult] {
        let body: [String: Any] = [
            "query": query,
            "standard_id": standardId as Any,
            "mode": mode.rawValue,
            "limit": limit
        ]
        let data = try await postRaw("/search", body: body)
        return try decoder.decode([SearchResult].self, from: data)
    }

    func ask(question: String, standardId: String? = nil, topK: Int = 12) async throws -> AskResponse {
        let body: [String: Any] = [
            "question": question,
            "standard_id": standardId as Any,
            "top_k": topK
        ]
        let data = try await postRaw("/ask", body: body)
        return try decoder.decode(AskResponse.self, from: data)
    }

    func startWatching(path: String) async throws {
        let body: [String: Any] = ["path": path, "no_embed": false]
        _ = try await postJSON("/watch/start", body: body)
    }

    func stopWatching(path: String) async throws {
        let body: [String: Any] = ["path": path]
        _ = try await postJSON("/watch/stop", body: body)
    }

    // MARK: - HTTP helpers

    private func get<T: Decodable>(_ path: String) async throws -> T {
        let trimmed = path.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        let pathPart = trimmed.split(separator: "?", maxSplits: 1).first.map(String.init) ?? trimmed
        var components = URLComponents(
            url: AppConfig.apiBaseURL.appendingPathComponent(pathPart),
            resolvingAgainstBaseURL: false
        )!
        if let qIndex = trimmed.firstIndex(of: "?") {
            let query = String(trimmed[trimmed.index(after: qIndex)...])
            components.percentEncodedQuery = query
        }
        var request = URLRequest(url: components.url!)
        request.httpMethod = "GET"
        let (data, response) = try await session.data(for: request)
        try validate(response: response, data: data)
        return try decoder.decode(T.self, from: data)
    }

    private func postRaw(_ path: String, body: [String: Any]) async throws -> Data {
        let url = AppConfig.apiBaseURL.appendingPathComponent(path.trimmingCharacters(in: CharacterSet(charactersIn: "/")))
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: body)
        let (data, response) = try await session.data(for: request)
        try validate(response: response, data: data)
        return data
    }

    private func postJSON(_ path: String, body: [String: Any]) async throws -> [String: Any] {
        let data = try await postRaw(path, body: body)
        let obj = try JSONSerialization.jsonObject(with: data)
        return obj as? [String: Any] ?? [:]
    }

    private func delete<T: Decodable>(_ path: String) async throws -> T {
        let url = AppConfig.apiBaseURL.appendingPathComponent(
            path.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        )
        var request = URLRequest(url: url)
        request.httpMethod = "DELETE"
        let (data, response) = try await session.data(for: request)
        try validate(response: response, data: data)
        return try decoder.decode(T.self, from: data)
    }

    private func validate(response: URLResponse, data: Data) throws {
        guard let http = response as? HTTPURLResponse else { return }
        guard (200...299).contains(http.statusCode) else {
            let message = String(data: data, encoding: .utf8) ?? "Unknown error"
            throw BackendError.httpError(http.statusCode, message)
        }
    }
}

enum BackendError: LocalizedError {
    case httpError(Int, String)
    case serverUnavailable

    var errorDescription: String? {
        switch self {
        case .httpError(let code, let msg):
            return "HTTP \(code): \(msg)"
        case .serverUnavailable:
            return "Backend server is not running. Start it with: python3 isokb.py serve"
        }
    }
}
