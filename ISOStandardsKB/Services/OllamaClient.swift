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
