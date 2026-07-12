import Foundation
import SQLite3

/// Direct SQLite access for offline library browsing when backend is unavailable.
final class DatabaseService {
    static let shared = DatabaseService()

    private var db: OpaquePointer?

    init() {
        try? open()
    }

    deinit {
        if db != nil { sqlite3_close(db) }
    }

    func open() throws {
        let path = AppConfig.dbPath.path
        try FileManager.default.createDirectory(
            at: AppConfig.appSupportDir,
            withIntermediateDirectories: true
        )
        if sqlite3_open(path, &db) != SQLITE_OK {
            throw DatabaseError.openFailed(String(cString: sqlite3_errmsg(db)))
        }
        sqlite3_exec(db, "PRAGMA foreign_keys = ON;", nil, nil, nil)
        let schemaURL = Bundle.main.url(forResource: "schema", withExtension: "sql")
            ?? Bundle.main.bundleURL
                .deletingLastPathComponent()
                .deletingLastPathComponent()
                .deletingLastPathComponent()
                .appendingPathComponent("resources/schema.sql")
        if FileManager.default.fileExists(atPath: schemaURL.path),
           let sql = try? String(contentsOf: schemaURL) {
            sqlite3_exec(db, sql, nil, nil, nil)
        }
    }

    func fetchLibraries() -> [Library] {
        query("""
            SELECT id, path, name, created_at, updated_at
            FROM libraries ORDER BY name
            """)
    }

    func fetchDocuments() -> [ISODocument] {
        query("""
            SELECT id, library_id, file_path, file_name, file_hash, file_type,
                   standard_id, title, page_count, indexed_at, status, error_message
            FROM documents ORDER BY standard_id, file_name
            """)
    }

    func fetchDocuments(libraryId: Int) -> [ISODocument] {
        query("""
            SELECT id, library_id, file_path, file_name, file_hash, file_type,
                   standard_id, title, page_count, indexed_at, status, error_message
            FROM documents WHERE library_id = \(libraryId)
            ORDER BY standard_id, file_name
            """)
    }

    func fetchClauses(documentId: Int) -> [Clause] {
        query("""
            SELECT id, document_id, clause_number, title, level, parent_clause_id,
                   page_start, page_end, sort_order
            FROM clauses WHERE document_id = \(documentId)
            ORDER BY sort_order, clause_number
            """)
    }

    func fetchFigures(documentId: Int) -> [Figure] {
        query("""
            SELECT id, document_id, clause_id, chunk_id, figure_number, caption,
                   page_number, image_path, width, height
            FROM figures WHERE document_id = \(documentId)
            ORDER BY page_number, id
            """)
    }

    func keywordSearch(_ query: String, limit: Int = 50) -> [SearchResult] {
        let escaped = query.replacingOccurrences(of: "'", with: "''")
        let sql = """
            SELECT c.id AS chunk_id, c.content, c.page_number, c.chunk_type,
                   cl.clause_number, cl.title AS clause_title,
                   d.id AS document_id, d.standard_id, d.title AS document_title,
                   d.file_path, d.file_name, bm25(chunks_fts) AS score
            FROM chunks_fts
            JOIN chunks c ON c.id = chunks_fts.rowid
            JOIN documents d ON d.id = c.document_id
            LEFT JOIN clauses cl ON cl.id = c.clause_id
            WHERE chunks_fts MATCH '\(escaped)'
            ORDER BY score LIMIT \(limit)
            """
        return self.query(sql)
    }

    private func query<T: Decodable>(_ sql: String) -> [T] {
        guard let db else { return [] }
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else { return [] }
        defer { sqlite3_finalize(stmt) }

        var rows: [[String: Any]] = []
        let colCount = sqlite3_column_count(stmt)
        while sqlite3_step(stmt) == SQLITE_ROW {
            var row: [String: Any] = [:]
            for i in 0..<colCount {
                let name = String(cString: sqlite3_column_name(stmt, i))
                switch sqlite3_column_type(stmt, i) {
                case SQLITE_INTEGER:
                    row[name] = Int(sqlite3_column_int64(stmt, i))
                case SQLITE_FLOAT:
                    row[name] = sqlite3_column_double(stmt, i)
                case SQLITE_TEXT:
                    if let cStr = sqlite3_column_text(stmt, i) {
                        row[name] = String(cString: cStr)
                    }
                default:
                    break
                }
            }
            rows.append(row)
        }

        guard let data = try? JSONSerialization.data(withJSONObject: rows) else { return [] }
        let decoder = JSONDecoder()
        return (try? decoder.decode([T].self, from: data)) ?? []
    }
}

enum DatabaseError: Error {
    case openFailed(String)
}
