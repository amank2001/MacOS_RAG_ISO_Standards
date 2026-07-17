-- ISO Standards Knowledge Base schema

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS libraries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    library_id INTEGER NOT NULL REFERENCES libraries(id) ON DELETE CASCADE,
    file_path TEXT NOT NULL,
    file_name TEXT NOT NULL,
    file_hash TEXT NOT NULL,
    file_type TEXT NOT NULL CHECK (file_type IN ('pdf', 'docx', 'doc')),
    standard_id TEXT,
    title TEXT,
    page_count INTEGER DEFAULT 0,
    indexed_at TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'indexing', 'indexed', 'error')),
    error_message TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(library_id, file_path)
);

CREATE TABLE IF NOT EXISTS clauses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    clause_number TEXT NOT NULL,
    title TEXT,
    level INTEGER NOT NULL DEFAULT 1,
    parent_clause_id INTEGER REFERENCES clauses(id) ON DELETE SET NULL,
    page_start INTEGER,
    page_end INTEGER,
    sort_order INTEGER NOT NULL DEFAULT 0,
    UNIQUE(document_id, clause_number)
);

CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    clause_id INTEGER REFERENCES clauses(id) ON DELETE SET NULL,
    content TEXT NOT NULL,
    chunk_type TEXT NOT NULL DEFAULT 'text' CHECK (chunk_type IN ('text', 'heading', 'note', 'table', 'figure_caption', 'definition', 'annex', 'body_text')),
    page_number INTEGER,
    token_count INTEGER DEFAULT 0,
    bbox_x0 REAL,
    bbox_y0 REAL,
    bbox_x1 REAL,
    bbox_y1 REAL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    content,
    clause_number,
    standard_id,
    document_title,
    content='chunks',
    content_rowid='id',
    tokenize='porter unicode61'
);

CREATE TABLE IF NOT EXISTS figures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    clause_id INTEGER REFERENCES clauses(id) ON DELETE SET NULL,
    chunk_id INTEGER REFERENCES chunks(id) ON DELETE SET NULL,
    figure_number TEXT,
    caption TEXT,
    page_number INTEGER NOT NULL,
    image_path TEXT NOT NULL,
    width INTEGER,
    height INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS chunk_embeddings (
    chunk_id INTEGER PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE,
    model_name TEXT NOT NULL,
    embedding BLOB NOT NULL,
    dimensions INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_documents_library ON documents(library_id);
CREATE INDEX IF NOT EXISTS idx_documents_standard ON documents(standard_id);
CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(status);
CREATE INDEX IF NOT EXISTS idx_clauses_document ON clauses(document_id);
CREATE INDEX IF NOT EXISTS idx_clauses_number ON clauses(clause_number);
CREATE INDEX IF NOT EXISTS idx_chunks_document ON chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_chunks_clause ON chunks(clause_id);
CREATE INDEX IF NOT EXISTS idx_figures_document ON figures(document_id);
CREATE INDEX IF NOT EXISTS idx_figures_clause ON figures(clause_id);

-- FTS sync triggers
CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts(rowid, content, clause_number, standard_id, document_title)
    SELECT NEW.id, NEW.content,
           COALESCE(c.clause_number, ''),
           COALESCE(d.standard_id, ''),
           COALESCE(d.title, d.file_name)
    FROM documents d
    LEFT JOIN clauses c ON c.id = NEW.clause_id
    WHERE d.id = NEW.document_id;
END;

CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, content, clause_number, standard_id, document_title)
    VALUES ('delete', OLD.id, OLD.content, '', '', '');
END;

CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, content, clause_number, standard_id, document_title)
    VALUES ('delete', OLD.id, OLD.content, '', '', '');
    INSERT INTO chunks_fts(rowid, content, clause_number, standard_id, document_title)
    SELECT NEW.id, NEW.content,
           COALESCE(c.clause_number, ''),
           COALESCE(d.standard_id, ''),
           COALESCE(d.title, d.file_name)
    FROM documents d
    LEFT JOIN clauses c ON c.id = NEW.clause_id
    WHERE d.id = NEW.document_id;
END;
