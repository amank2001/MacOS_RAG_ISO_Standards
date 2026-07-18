"""Regression tests for the /search and /ask "file is no longer at" bug.

The macOS client opens documents by the ``file_path`` returned from the API.
``documents.file_path`` in the DB is an ABSOLUTE path (the ingest pipeline
stores ``file_path.resolve()``), and the /documents endpoint returns it
unchanged, so opening works there and in offline DatabaseService mode.

Previously /search and /ask reduced ``file_path`` to a basename via
``sanitize_path`` (no library_root), producing values like "ISO_0.docx". The
Swift ``DocumentOpener`` then failed ``FileManager.fileExists`` and raised the
"The file is no longer at: <basename>" alert.

This app is explicitly local-only (127.0.0.1, same user), so /search and /ask
now return the ABSOLUTE DB path, consistent with /documents. These tests lock
in that behavior.
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from indexer import auth
from indexer.api import create_app
from indexer.database import Database
from indexer.pipeline import IngestionPipeline
from tests.create_fixtures import create_sample_docx

TOKEN = "test-token-path-exposure"


def _auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


def _seed_library() -> tuple[TestClient, str]:
    """Seed a fresh DB with one ingested docx and return (client, abs_path).

    ``abs_path`` is the absolute ``documents.file_path`` recorded by the
    ingestion pipeline for the seeded document.
    """
    auth._current_token = TOKEN
    tmp = Path(tempfile.mkdtemp())
    db_path = tmp / "test.db"
    figures_dir = tmp / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    fixture_dir = Path(tempfile.mkdtemp())
    create_sample_docx(fixture_dir, "ISO_27001_2022_sample.docx")

    db = Database(db_path)
    try:
        pipeline = IngestionPipeline(db, figures_dir, embed=False)
        result = pipeline.ingest_library(fixture_dir, "lib")
        assert result.get("indexed", 0) >= 1, result
    finally:
        db.close()

    conn = sqlite3.connect(str(db_path))
    try:
        abs_path = conn.execute(
            "SELECT file_path FROM documents LIMIT 1"
        ).fetchone()[0]
    finally:
        conn.close()

    assert abs_path.startswith("/"), f"expected absolute DB path, got {abs_path!r}"

    app = create_app(db_path=db_path, figures_dir=figures_dir)
    return TestClient(app), abs_path


def test_search_returns_absolute_file_path() -> None:
    """POST /search returns the absolute DB file_path (not a basename), so the
    local-only client can open the document via FileManager."""
    client, abs_path = _seed_library()

    resp = client.post(
        "/search",
        json={"query": "scope", "mode": "keyword"},
        headers=_auth_headers(),
    )
    assert resp.status_code == 200, resp.text
    results = resp.json()
    assert results, "expected at least one keyword search hit for 'scope'"

    for r in results:
        assert "file_path" in r
        # Absolute path, matching /documents — NOT a sanitized basename.
        assert r["file_path"].startswith("/"), r["file_path"]
        assert r["file_path"] == abs_path, r["file_path"]
        assert r["file_path"] != Path(abs_path).name


def test_ask_evidence_returns_absolute_file_path() -> None:
    """POST /ask returns evidence whose file_path is the absolute DB path, so
    the client can open the cited document."""
    client, abs_path = _seed_library()

    resp = client.post(
        "/ask",
        json={"question": "scope of the organization"},
        headers=_auth_headers(),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    evidence = body.get("evidence", [])
    assert evidence, "expected evidence entries for a matching question"

    for ev in evidence:
        assert "file_path" in ev
        assert ev["file_path"].startswith("/"), ev["file_path"]
        assert ev["file_path"] == abs_path, ev["file_path"]
        assert ev["file_path"] != Path(abs_path).name


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
