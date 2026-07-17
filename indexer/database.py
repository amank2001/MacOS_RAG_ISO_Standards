"""SQLite database operations for the indexer."""

from __future__ import annotations

import hashlib
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any


class Database:
    """Thread-safe wrapper around a SQLite database.

    Every thread that touches the :pyattr:`conn` property receives its own
    :class:`sqlite3.Connection`, opened lazily on first use. This lets a single
    ``Database`` instance be shared between the FastAPI request thread, the
    watchdog observer thread and the per-event worker threads spawned by the
    library watcher without tripping ``sqlite3.ProgrammingError: SQLite objects
    created in a thread can only be used in that same thread``.

    SQLite in WAL mode already coordinates concurrent readers and a single
    writer across independent connections, so this pattern is safe and does
    not require an application-level lock.
    """

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._in_transaction = False
        self._init_schema()

    def _init_schema_once(self) -> None:
        """Run the schema DDL exactly once, on a dedicated connection.

        The statements in ``resources/schema.sql`` are all ``IF NOT EXISTS``
        forms and running them from every per-thread connection would be
        wasteful and would risk racing on FTS5 shadow tables. Doing it up
        front means later per-thread connections open onto a fully
        initialized schema.
        """
        schema_path = Path(__file__).resolve().parents[1] / "resources" / "schema.sql"
        if schema_path.exists():
            self.conn.executescript(schema_path.read_text())
            self.conn.commit()
        self._migrate_schema()

    def _migrate_schema(self) -> None:
        """Add new columns to existing databases that were created before schema updates."""
        migrations = [
            "ALTER TABLE chunks ADD COLUMN bbox_x0 REAL",
            "ALTER TABLE chunks ADD COLUMN bbox_y0 REAL",
            "ALTER TABLE chunks ADD COLUMN bbox_x1 REAL",
            "ALTER TABLE chunks ADD COLUMN bbox_y1 REAL",
        ]
        for sql in migrations:
            try:
                self.conn.execute(sql)
            except sqlite3.OperationalError:
                # Column already exists — safe to ignore
                pass
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    @contextmanager
    def transaction(self):
        """Context manager for atomic database transactions.

        Suppresses individual commits within the transaction scope.
        All changes are committed atomically at the end, or rolled back on failure.
        """
        self._in_transaction = True
        try:
            yield
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        finally:
            self._in_transaction = False

    def _commit(self) -> None:
        """Commit unless inside a transaction() block."""
        if not self._in_transaction:
            self.conn.commit()

    def get_or_create_library(self, path: str, name: str | None = None) -> int:
        resolved = str(Path(path).resolve())
        display_name = name or Path(resolved).name
        row = self.conn.execute(
            "SELECT id FROM libraries WHERE path = ?", (resolved,)
        ).fetchone()
        if row:
            return row["id"]
        cur = self.conn.execute(
            "INSERT INTO libraries (path, name) VALUES (?, ?)",
            (resolved, display_name),
        )
        self._commit()
        return cur.lastrowid

    def file_hash(self, file_path: Path) -> str:
        h = hashlib.sha256()
        with open(file_path, "rb") as f:
            for block in iter(lambda: f.read(65536), b""):
                h.update(block)
        return h.hexdigest()

    def get_document_by_path(self, library_id: int, file_path: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM documents WHERE library_id = ? AND file_path = ?",
            (library_id, file_path),
        ).fetchone()

    def upsert_document(
        self,
        library_id: int,
        file_path: str,
        file_name: str,
        file_hash: str,
        file_type: str,
        standard_id: str | None = None,
        title: str | None = None,
        page_count: int = 0,
    ) -> int:
        existing = self.get_document_by_path(library_id, file_path)
        if existing:
            if existing["file_hash"] == file_hash and existing["status"] == "indexed":
                return existing["id"]
            doc_id = existing["id"]
            self.conn.execute(
                """UPDATE documents SET file_hash = ?, standard_id = ?, title = ?,
                   page_count = ?, status = 'pending', error_message = NULL,
                   updated_at = datetime('now') WHERE id = ?""",
                (file_hash, standard_id, title, page_count, doc_id),
            )
            self._clear_document_content(doc_id)
        else:
            cur = self.conn.execute(
                """INSERT INTO documents
                   (library_id, file_path, file_name, file_hash, file_type,
                    standard_id, title, page_count, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')""",
                (library_id, file_path, file_name, file_hash, file_type,
                 standard_id, title, page_count),
            )
            doc_id = cur.lastrowid
        self._commit()
        return doc_id

    def _clear_document_content(self, document_id: int) -> None:
        chunk_ids = [
            r["id"]
            for r in self.conn.execute(
                "SELECT id FROM chunks WHERE document_id = ?", (document_id,)
            ).fetchall()
        ]
        for cid in chunk_ids:
            self.conn.execute("DELETE FROM chunk_embeddings WHERE chunk_id = ?", (cid,))
        self.conn.execute("DELETE FROM figures WHERE document_id = ?", (document_id,))
        self.conn.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))
        self.conn.execute("DELETE FROM clauses WHERE document_id = ?", (document_id,))

    def set_document_status(
        self, document_id: int, status: str, error_message: str | None = None
    ) -> None:
        self.conn.execute(
            """UPDATE documents SET status = ?, error_message = ?,
               indexed_at = CASE WHEN ? = 'indexed' THEN datetime('now') ELSE indexed_at END,
               updated_at = datetime('now') WHERE id = ?""",
            (status, error_message, status, document_id),
        )
        self._commit()

    def insert_clause(
        self,
        document_id: int,
        clause_number: str,
        title: str | None,
        level: int,
        parent_clause_id: int | None,
        page_start: int | None,
        page_end: int | None,
        sort_order: int,
    ) -> int:
        cur = self.conn.execute(
            """INSERT OR REPLACE INTO clauses
               (document_id, clause_number, title, level, parent_clause_id,
                page_start, page_end, sort_order)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (document_id, clause_number, title, level, parent_clause_id,
             page_start, page_end, sort_order),
        )
        self._commit()
        return cur.lastrowid

    def get_clause_id(self, document_id: int, clause_number: str) -> int | None:
        row = self.conn.execute(
            "SELECT id FROM clauses WHERE document_id = ? AND clause_number = ?",
            (document_id, clause_number),
        ).fetchone()
        return row["id"] if row else None

    def insert_chunk(
        self,
        document_id: int,
        content: str,
        clause_id: int | None = None,
        chunk_type: str = "text",
        page_number: int | None = None,
        token_count: int = 0,
        bbox_x0: float | None = None,
        bbox_y0: float | None = None,
        bbox_x1: float | None = None,
        bbox_y1: float | None = None,
    ) -> int:
        cur = self.conn.execute(
            """INSERT INTO chunks
               (document_id, clause_id, content, chunk_type, page_number, token_count,
                bbox_x0, bbox_y0, bbox_x1, bbox_y1)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (document_id, clause_id, content, chunk_type, page_number, token_count,
             bbox_x0, bbox_y0, bbox_x1, bbox_y1),
        )
        self._commit()
        return cur.lastrowid

    def insert_figure(
        self,
        document_id: int,
        image_path: str,
        page_number: int,
        clause_id: int | None = None,
        chunk_id: int | None = None,
        figure_number: str | None = None,
        caption: str | None = None,
        width: int | None = None,
        height: int | None = None,
    ) -> int:
        cur = self.conn.execute(
            """INSERT INTO figures
               (document_id, clause_id, chunk_id, figure_number, caption,
                page_number, image_path, width, height)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (document_id, clause_id, chunk_id, figure_number, caption,
             page_number, image_path, width, height),
        )
        self._commit()
        return cur.lastrowid

    def store_embedding(
        self, chunk_id: int, model_name: str, embedding: list[float]
    ) -> None:
        import struct

        blob = struct.pack(f"{len(embedding)}f", *embedding)
        self.conn.execute(
            """INSERT OR REPLACE INTO chunk_embeddings
               (chunk_id, model_name, embedding, dimensions)
               VALUES (?, ?, ?, ?)""",
            (chunk_id, model_name, blob, len(embedding)),
        )
        self._commit()

    def keyword_search(
        self,
        query: str,
        standard_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        sql = """
            SELECT
                c.id AS chunk_id,
                c.content,
                c.page_number,
                c.chunk_type,
                cl.clause_number,
                cl.title AS clause_title,
                d.id AS document_id,
                d.standard_id,
                d.title AS document_title,
                d.file_path,
                d.file_name,
                bm25(chunks_fts) AS score
            FROM chunks_fts
            JOIN chunks c ON c.id = chunks_fts.rowid
            JOIN documents d ON d.id = c.document_id
            LEFT JOIN clauses cl ON cl.id = c.clause_id
            WHERE chunks_fts MATCH ?
        """
        params: list[Any] = [query]
        if standard_id:
            sql += " AND d.standard_id = ?"
            params.append(standard_id)
        sql += " ORDER BY score LIMIT ?"
        params.append(limit)
        rows = self.conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def get_all_embeddings(self, model_name: str) -> list[tuple[int, list[float]]]:
        import struct

        rows = self.conn.execute(
            "SELECT chunk_id, embedding, dimensions FROM chunk_embeddings WHERE model_name = ?",
            (model_name,),
        ).fetchall()
        result = []
        for row in rows:
            dims = row["dimensions"]
            vec = list(struct.unpack(f"{dims}f", row["embedding"]))
            result.append((row["chunk_id"], vec))
        return result

    def get_chunk_details(self, chunk_id: int) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT c.*, c.clause_id, cl.clause_number, cl.title AS clause_title,
                   d.id AS document_id, d.standard_id, d.title AS document_title,
                   d.file_path, d.file_name
            FROM chunks c
            JOIN documents d ON d.id = c.document_id
            LEFT JOIN clauses cl ON cl.id = c.clause_id
            WHERE c.id = ?
            """,
            (chunk_id,),
        ).fetchone()
        return dict(row) if row else None

    def get_figures_for_clause(self, clause_id: int) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM figures WHERE clause_id = ? ORDER BY page_number",
            (clause_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_figures_for_document(self, document_id: int) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM figures WHERE document_id = ? ORDER BY page_number",
            (document_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def list_libraries(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM libraries ORDER BY name"
        ).fetchall()
        return [dict(r) for r in rows]

    def list_documents(self, library_id: int | None = None) -> list[dict[str, Any]]:
        if library_id:
            rows = self.conn.execute(
                "SELECT * FROM documents WHERE library_id = ? ORDER BY standard_id, file_name",
                (library_id,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM documents ORDER BY standard_id, file_name"
            ).fetchall()
        return [dict(r) for r in rows]

    def list_clauses(self, document_id: int) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM clauses WHERE document_id = ? ORDER BY sort_order, clause_number",
            (document_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_unindexed_documents(self, library_id: int) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """SELECT * FROM documents
               WHERE library_id = ? AND status IN ('pending', 'error')
               ORDER BY file_name""",
            (library_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_library(self, library_id: int) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM libraries WHERE id = ?", (library_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_document(self, document_id: int) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM documents WHERE id = ?", (document_id,)
        ).fetchone()
        return dict(row) if row else None

    def figure_paths_for_document(self, document_id: int) -> list[str]:
        rows = self.conn.execute(
            "SELECT image_path FROM figures WHERE document_id = ?",
            (document_id,),
        ).fetchall()
        return [r["image_path"] for r in rows]

    def figure_paths_for_library(self, library_id: int) -> list[str]:
        rows = self.conn.execute(
            """SELECT f.image_path FROM figures f
               JOIN documents d ON d.id = f.document_id
               WHERE d.library_id = ?""",
            (library_id,),
        ).fetchall()
        return [r["image_path"] for r in rows]

    def delete_library(self, library_id: int) -> int:
        # Relies on PRAGMA foreign_keys = ON so cascades on documents, clauses,
        # chunks, chunk_embeddings, figures, and the chunks_ad FTS trigger fire
        # automatically.
        cur = self.conn.execute(
            "DELETE FROM libraries WHERE id = ?", (library_id,)
        )
        self._commit()
        return cur.rowcount

    def delete_document(self, document_id: int) -> int:
        # Relies on PRAGMA foreign_keys = ON so cascades on clauses, chunks,
        # chunk_embeddings, figures, and the chunks_ad FTS trigger fire
        # automatically.
        cur = self.conn.execute(
            "DELETE FROM documents WHERE id = ?", (document_id,)
        )
        self._commit()
        return cur.rowcount
