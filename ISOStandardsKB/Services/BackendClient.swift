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

    static var tokenPath: URL {
        appSupportDir.appendingPathComponent("api_token")
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

    /// Response from submitting an ingest job via `POST /ingest`.
    struct IngestJob: Decodable {
        let jobId: String
        let status: String

        enum CodingKeys: String, CodingKey {
            case jobId = "job_id"
            case status
        }
    }

    /// Response from polling `GET /ingest/status/{job_id}`.
    struct IngestStatus: Decodable {
        let status: String
        let result: IngestResult?
        let error: String?

        struct IngestResult: Decodable {
            let indexed: Int
            let skipped: Int
            let errors: Int
        }
    }

    @Published var isConnected = false
    @Published var ollamaAvailable = false

    private let session: URLSession
    private let decoder: JSONDecoder
    private var cachedToken: String?

    init(session: URLSession = .shared) {
        self.session = session
        self.decoder = JSONDecoder()
        self.cachedToken = Self.loadToken()
    }

    // MARK: - Token management

    /// Reads the API token from the application support directory.
    /// Returns nil if the file doesn't exist or can't be read.
    private static func loadToken() -> String? {
        guard let content = try? String(contentsOf: AppConfig.tokenPath, encoding: .utf8) else {
            return nil
        }
        let token = content.trimmingCharacters(in: .whitespacesAndNewlines)
        return token.isEmpty ? nil : token
    }

    /// Adds the Authorization Bearer header to the request if a token is available.
    ///
    /// The token is re-read from disk on each call. The backend mints a new
    /// per-launch token every time it starts, so caching the value from app
    /// launch would break with a stale token whenever the server restarts.
    private func applyAuth(to request: inout URLRequest) {
        let token = Self.loadToken() ?? cachedToken
        if let token {
            cachedToken = token
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
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

    /// Submits an ingest job and returns the generated job id.
    ///
    /// `POST /ingest` is now a fast submit endpoint that enqueues the work on a
    /// background worker and returns `{job_id, status}` immediately. Callers poll
    /// `ingestStatus(jobId:)` until a terminal state is reached.
    func ingest(path: String, name: String? = nil, noEmbed: Bool = false) async throws -> String {
        let body: [String: Any] = [
            "path": path,
            "name": name as Any,
            "no_embed": noEmbed
        ]
        let data = try await postRaw("/ingest", body: body)
        let job = try decoder.decode(IngestJob.self, from: data)
        return job.jobId
    }

    /// Polls the status of a previously submitted ingest job.
    ///
    /// Returns the job's lifecycle state (`queued` / `running` / `completed` /
    /// `failed`), the `{indexed, skipped, errors}` result on completion, and an
    /// `error` message on failure.
    func ingestStatus(jobId: String) async throws -> IngestStatus {
        try await get("/ingest/status/\(jobId)")
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
        applyAuth(to: &request)
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
        applyAuth(to: &request)
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
        applyAuth(to: &request)
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
