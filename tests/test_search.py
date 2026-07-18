"""Tests for hybrid search score handling.

Regression coverage for the /ask 500 error: SQLite bm25() can return NULL
(Python None) for some FTS rows. The score key IS present with value None,
so a `.get("score", 0)` default does not apply and `abs(None)` used to raise
TypeError. hybrid_search must coerce a missing OR None score to 0.
"""

from __future__ import annotations

import unittest

from indexer.search import SearchService


class FakeOllama:
    """Lightweight stub for OllamaClient."""

    def __init__(self, available: bool = False):
        self._available = available
        self.embed_model = "fake-embed"

    def is_available(self) -> bool:
        return self._available

    def embed(self, text):
        return [1.0, 0.0, 0.0]


class FakeDB:
    """Lightweight stub for Database exposing only what SearchService uses."""

    def __init__(self, keyword_rows=None):
        self._keyword_rows = keyword_rows or []

    def keyword_search(self, fts_query, standard_id, limit):
        return self._keyword_rows


class HybridSearchScoreTests(unittest.TestCase):
    def test_keyword_none_score_does_not_crash(self):
        """Keyword-only branch: a None bm25 score must not raise abs(None)."""
        keyword_rows = [
            {"chunk_id": 1, "score": None, "content": "row with null score"},
            {"chunk_id": 2, "score": -1.5, "content": "row with real bm25 score"},
            {"chunk_id": 3, "content": "row missing score key entirely"},
        ]
        db = FakeDB(keyword_rows=keyword_rows)
        ollama = FakeOllama(available=False)  # forces semantic_search -> []
        service = SearchService(db, ollama)

        # Should not raise TypeError: bad operand type for abs(): 'NoneType'
        results = service.hybrid_search("some query", limit=10)

        # Keyword-only branch returns keyword_results[:limit]
        self.assertEqual([r["chunk_id"] for r in results], [1, 2, 3])

    def test_semantic_none_score_does_not_crash(self):
        """Semantic branch: a None score in semantic results must not break fusion."""
        keyword_rows = [
            {"chunk_id": 1, "score": 0.5, "content": "kw one"},
            {"chunk_id": 2, "score": None, "content": "kw two null score"},
        ]
        db = FakeDB(keyword_rows=keyword_rows)
        ollama = FakeOllama(available=True)
        service = SearchService(db, ollama)

        # Force semantic results (with a None score) without touching the real
        # embeddings/db machinery.
        def fake_semantic(query, standard_id=None, limit=50):
            return [
                {"chunk_id": 2, "score": None, "content": "sem two null score"},
                {"chunk_id": 3, "score": 0.9, "content": "sem three"},
            ]

        service.semantic_search = fake_semantic  # type: ignore[assignment]

        results = service.hybrid_search("some query", limit=10)

        # Should not raise and should merge chunks from both branches.
        chunk_ids = {r["chunk_id"] for r in results}
        self.assertTrue(chunk_ids.issubset({1, 2, 3}))
        self.assertIn(3, chunk_ids)

    def test_semantic_score_attached_to_merged_items(self):
        """When semantic results are present, hybrid_search must attach the real
        cosine similarity as `semantic_score` on merged items so RAGService can
        apply the cosine threshold. Keyword-only chunks get semantic_score=None."""
        keyword_rows = [
            {"chunk_id": 1, "score": 0.5, "content": "kw one (also semantic)"},
            {"chunk_id": 2, "score": 0.4, "content": "kw two, keyword only"},
        ]
        db = FakeDB(keyword_rows=keyword_rows)
        ollama = FakeOllama(available=True)
        service = SearchService(db, ollama)

        def fake_semantic(query, standard_id=None, limit=50):
            return [
                {"chunk_id": 1, "score": 0.83, "content": "sem one cosine 0.83"},
                {"chunk_id": 3, "score": 0.42, "content": "sem three cosine 0.42"},
            ]

        service.semantic_search = fake_semantic  # type: ignore[assignment]

        results = service.hybrid_search("some query", limit=10)
        by_id = {r["chunk_id"]: r for r in results}

        # Chunks present in semantic results carry their cosine score.
        self.assertEqual(by_id[1]["semantic_score"], 0.83)
        self.assertEqual(by_id[3]["semantic_score"], 0.42)
        # Keyword-only chunk has no cosine signal.
        self.assertIsNone(by_id[2]["semantic_score"])


if __name__ == "__main__":
    unittest.main()
