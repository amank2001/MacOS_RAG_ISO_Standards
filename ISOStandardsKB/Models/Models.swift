import Foundation

struct Library: Identifiable, Codable, Hashable {
    let id: Int
    let path: String
    let name: String
    let createdAt: String
    let updatedAt: String

    enum CodingKeys: String, CodingKey {
        case id, path, name
        case createdAt = "created_at"
        case updatedAt = "updated_at"
    }
}

struct ISODocument: Identifiable, Codable, Hashable {
    let id: Int
    let libraryId: Int
    let filePath: String
    let fileName: String
    let fileHash: String
    let fileType: String
    let standardId: String?
    let title: String?
    let pageCount: Int
    let indexedAt: String?
    let status: String
    let errorMessage: String?

    enum CodingKeys: String, CodingKey {
        case id
        case libraryId = "library_id"
        case filePath = "file_path"
        case fileName = "file_name"
        case fileHash = "file_hash"
        case fileType = "file_type"
        case standardId = "standard_id"
        case title
        case pageCount = "page_count"
        case indexedAt = "indexed_at"
        case status
        case errorMessage = "error_message"
    }

    var displayTitle: String {
        title ?? standardId ?? fileName
    }
}

struct Clause: Identifiable, Codable, Hashable {
    let id: Int
    let documentId: Int
    let clauseNumber: String
    let title: String?
    let level: Int
    let parentClauseId: Int?
    let pageStart: Int?
    let pageEnd: Int?
    let sortOrder: Int

    enum CodingKeys: String, CodingKey {
        case id
        case documentId = "document_id"
        case clauseNumber = "clause_number"
        case title, level
        case parentClauseId = "parent_clause_id"
        case pageStart = "page_start"
        case pageEnd = "page_end"
        case sortOrder = "sort_order"
    }

    var displayName: String {
        if let title, !title.isEmpty {
            return "\(clauseNumber) — \(title)"
        }
        return clauseNumber
    }
}

struct SearchResult: Identifiable, Codable, Hashable {
    let chunkId: Int
    let content: String
    let pageNumber: Int?
    let chunkType: String?
    let clauseNumber: String?
    let clauseTitle: String?
    let documentId: Int
    let standardId: String?
    let documentTitle: String?
    let filePath: String
    let fileName: String
    let score: Double?
    let rrfScore: Double?

    var id: Int { chunkId }

    enum CodingKeys: String, CodingKey {
        case chunkId = "chunk_id"
        case content
        case pageNumber = "page_number"
        case chunkType = "chunk_type"
        case clauseNumber = "clause_number"
        case clauseTitle = "clause_title"
        case documentId = "document_id"
        case standardId = "standard_id"
        case documentTitle = "document_title"
        case filePath = "file_path"
        case fileName = "file_name"
        case score
        case rrfScore = "rrf_score"
    }

    var citation: String {
        var parts: [String] = []
        if let standardId { parts.append(standardId) }
        if let clauseNumber { parts.append("Clause \(clauseNumber)") }
        if let pageNumber { parts.append("p.\(pageNumber)") }
        return parts.joined(separator: ", ")
    }
}

struct Figure: Identifiable, Codable, Hashable {
    let id: Int
    let documentId: Int
    let clauseId: Int?
    let chunkId: Int?
    let figureNumber: String?
    let caption: String?
    let pageNumber: Int
    let imagePath: String
    let width: Int?
    let height: Int?

    enum CodingKeys: String, CodingKey {
        case id
        case documentId = "document_id"
        case clauseId = "clause_id"
        case chunkId = "chunk_id"
        case figureNumber = "figure_number"
        case caption
        case pageNumber = "page_number"
        case imagePath = "image_path"
        case width, height
    }
}

struct EvidenceItem: Identifiable, Codable, Hashable {
    let chunkId: Int
    let filePath: String
    let standardId: String?
    let clauseNumber: String?
    let pageNumber: Int?
    let quotedText: String
    let bbox: [Double]?

    var id: Int { chunkId }

    enum CodingKeys: String, CodingKey {
        case chunkId = "chunk_id"
        case filePath = "file_path"
        case standardId = "standard_id"
        case clauseNumber = "clause_number"
        case pageNumber = "page_number"
        case quotedText = "quoted_text"
        case bbox
    }

    var citation: String {
        var parts: [String] = []
        if let standardId { parts.append(standardId) }
        if let clauseNumber { parts.append("Clause \(clauseNumber)") }
        if let pageNumber { parts.append("p.\(pageNumber)") }
        return parts.joined(separator: ", ")
    }
}

struct AskResponse: Codable {
    let status: String
    let answer: String
    let evidence: [EvidenceItem]
    let figures: [Figure]
    let warnings: [String]
}

struct HealthResponse: Codable {
    let status: String
    let ollamaAvailable: Bool
    let dbPath: String

    enum CodingKeys: String, CodingKey {
        case status
        case ollamaAvailable = "ollama_available"
        case dbPath = "db_path"
    }
}

enum SearchMode: String, CaseIterable, Identifiable {
    case keyword
    case semantic
    case hybrid

    var id: String { rawValue }

    var label: String {
        switch self {
        case .keyword: return "Keyword"
        case .semantic: return "Semantic"
        case .hybrid: return "Hybrid"
        }
    }
}
