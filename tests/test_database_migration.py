"""Tests for the stale-schema chunk_type constraint migration."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from indexer.database import Database

# The old, narrow chunks table definition that predates the schema update.
# It only permits 5 chunk_type values and lacks the bbox_* columns, mimicking
# a live database created before both migrations landed.
OLD_CHUNKS_DDL = """
CREATE TABLE chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    clause_id INTEGER REFERENCES clauses(id) ON DELETE SET NULL,
    content TEXT NOT NULL,
    chunk_type TEXT NOT NULL DEFAULT 'text'
        CHECK (chunk_type IN ('text','heading','note','table','figure_caption')),
    page_number INTEGER,
    token_count INTEGER DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


class ChunkTypeConstraintMigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "stale.db"
        self._create_stale_db()

    def tearDown(self):
        self.tmpdir.cleanup()

    def _create_stale_db(self):
        """Build a DB with the OLD narrow chunks constraint plus a couple rows."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(
            """
            CREATE TABLE libraries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE TABLE documents (
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
                status TEXT NOT NULL DEFAULT 'pending',
                error_message TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(library_id, file_path)
            );
            CREATE TABLE clauses (
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
            """
        )
        conn.executescript(OLD_CHUNKS_DDL)
        conn.execute(
            "INSERT INTO libraries (id, path, name) VALUES (1, '/lib', 'lib')"
        )
        conn.execute(
            """INSERT INTO documents (id, library_id, file_path, file_name,
               file_hash, file_type, standard_id, title)
               VALUES (1, 1, '/lib/a.pdf', 'a.pdf', 'hash', 'pdf', 'ISO 1', 'Doc A')"""
        )
        # Two pre-existing rows using values allowed by the OLD constraint.
        conn.execute(
            "INSERT INTO chunks (id, document_id, content, chunk_type) "
            "VALUES (1, 1, 'existing text chunk', 'text')"
        )
        conn.execute(
            "INSERT INTO chunks (id, document_id, content, chunk_type) "
            "VALUES (2, 1, 'existing heading chunk', 'heading')"
        )
        conn.commit()
        conn.close()

    def test_old_constraint_rejects_body_text_before_migration(self):
        """Sanity check: the stale DB genuinely rejects 'body_text'."""
        conn = sqlite3.connect(str(self.db_path))
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO chunks (document_id, content, chunk_type) "
                "VALUES (1, 'x', 'body_text')"
            )
        conn.close()

    def test_body_text_insert_succeeds_after_migration(self):
        db = Database(self.db_path)
        chunk_id = db.insert_chunk(
            document_id=1, content="new body text", chunk_type="body_text"
        )
        self.assertIsNotNone(chunk_id)
        row = db.conn.execute(
            "SELECT chunk_type FROM chunks WHERE id = ?", (chunk_id,)
        ).fetchone()
        self.assertEqual(row["chunk_type"], "body_text")
        # The other newly-allowed values should also work.
        db.insert_chunk(document_id=1, content="a def", chunk_type="definition")
        db.insert_chunk(document_id=1, content="an annex", chunk_type="annex")
        db.close()

    def test_preexisting_rows_are_preserved(self):
        db = Database(self.db_path)
        rows = db.conn.execute(
            "SELECT id, content, chunk_type FROM chunks ORDER BY id"
        ).fetchall()
        db.close()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["id"], 1)
        self.assertEqual(rows[0]["content"], "existing text chunk")
        self.assertEqual(rows[0]["chunk_type"], "text")
        self.assertEqual(rows[1]["id"], 2)
        self.assertEqual(rows[1]["content"], "existing heading chunk")

    def test_fts_triggers_function_after_migration(self):
        db = Database(self.db_path)
        chunk_id = db.insert_chunk(
            document_id=1,
            content="searchable zebra sentence",
            chunk_type="body_text",
        )
        # The chunks_ai trigger should have populated chunks_fts.
        results = db.keyword_search("zebra")
        db_ids = [r["chunk_id"] for r in results]
        self.assertIn(chunk_id, db_ids)
        db.close()

    def test_migration_is_idempotent(self):
        # First init performs the rebuild.
        db1 = Database(self.db_path)
        sql_after_first = db1.conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='chunks'"
        ).fetchone()["sql"]
        db1.close()
        self.assertIn("'body_text'", sql_after_first)

        # Second init must early-return (no rebuild). Insert a sentinel row and
        # confirm it survives, proving the table was not dropped/rebuilt again.
        db2 = Database(self.db_path)
        sentinel_id = db2.insert_chunk(
            document_id=1, content="sentinel", chunk_type="body_text"
        )
        db2.close()

        db3 = Database(self.db_path)
        row = db3.conn.execute(
            "SELECT content FROM chunks WHERE id = ?", (sentinel_id,)
        ).fetchone()
        db3.close()
        self.assertIsNotNone(row)
        self.assertEqual(row["content"], "sentinel")


if __name__ == "__main__":
    unittest.main()
