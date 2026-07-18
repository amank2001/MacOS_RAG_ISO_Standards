"""Tests for RAGService.ask abstain / offline / online decision flow.

Regression coverage for the /ask "Not Found in Library" bug: relevant evidence
was retrieved but the answer abstained. Two causes:

(1) OFFLINE: keyword-only sources have no rrf_score, so the old
    `max(src.get("rrf_score", 0.0) ...)` was 0.0 < 0.3 -> not_found, and the
    intended offline "excerpts" fallback (status="answered") was never reached.
(2) SCALE MISMATCH: rrf_score is reciprocal-rank fusion (max ~0.03), always
    below the 0.3 cosine threshold, so even online it abstained on every query.

The fix abstains only when retrieval is empty, returns offline excerpts when
Ollama is unavailable, and applies the 0.3 threshold ONLY to the real semantic
cosine (semantic_score), never to rrf_score.
"""

from __future__ import annotations

import unittest

from indexer.rag import RAGService


class FakeSearch:
    """Search stub whose hybrid_search returns a preset list of sources."""

    def __init__(self, sources):
        self._sources = sources
        self.calls = 0

    def hybrid_search(self, query, standard_id=None, limit=20):
        self.calls += 1
        return list(self._sources)


class FakeOllama:
    """Ollama stub with controllable availability and a stubbed chat()."""

    def __init__(self, available: bool):
        self._available = available
        self.chat_calls = 0

    def is_available(self) -> bool:
        return self._available

    def chat(self, messages):
        self.chat_calls += 1
        return "Grounded answer from ISO 27001:2022, Clause A.5.1."


class FakeDB:
    """Minimal Database stub (only figure lookups are used by RAGService)."""

    def get_figures_for_clause(self, clause_id):
        return []

    def get_figures_for_document(self, document_id):
        return []


def make_rag(sources, available):
    db = FakeDB()
    search = FakeSearch(sources)
    ollama = FakeOllama(available=available)
    return RAGService(db, search=search, ollama=ollama), search, ollama


class RagAskTests(unittest.TestCase):
    def test_offline_keyword_only_sources_are_answered(self):
        """Exact user-reported regression: offline + keyword-only sources
        (no semantic_score, no rrf_score) must return status='answered'
        with non-empty evidence, NOT 'not_found'."""
        sources = [
            {
                "chunk_id": 1,
                "content": "Access control policy shall be defined.",
                "file_path": "/library/iso27001.pdf",
                "standard_id": "ISO 27001:2022",
                "clause_number": "A.5.1",
                "page_number": 12,
            },
            {
                "chunk_id": 2,
                "content": "Information security roles and responsibilities.",
                "file_path": "/library/iso27001.pdf",
                "standard_id": "ISO 27001:2022",
                "clause_number": "A.5.2",
                "page_number": 13,
            },
        ]
        rag, _search, ollama = make_rag(sources, available=False)

        result = rag.ask("What is the access control policy?")

        self.assertEqual(result["status"], "answered")
        self.assertTrue(result["evidence"])
        self.assertEqual(ollama.chat_calls, 0)  # LLM not called offline

    def test_online_high_cosine_calls_llm_and_answers(self):
        """Online with a source whose semantic_score >= 0.3 -> answered via LLM."""
        sources = [
            {
                "chunk_id": 1,
                "content": "Access control policy shall be defined.",
                "file_path": "/library/iso27001.pdf",
                "standard_id": "ISO 27001:2022",
                "clause_number": "A.5.1",
                "page_number": 12,
                "semantic_score": 0.72,
                "rrf_score": 0.016,
            },
        ]
        rag, _search, ollama = make_rag(sources, available=True)

        result = rag.ask("What is the access control policy?")

        self.assertEqual(result["status"], "answered")
        self.assertTrue(result["evidence"])
        self.assertEqual(ollama.chat_calls, 1)  # LLM was used

    def test_online_low_cosine_abstains_with_evidence(self):
        """Online with all semantic_score < 0.3 -> not_found, evidence populated."""
        sources = [
            {
                "chunk_id": 1,
                "content": "Unrelated boilerplate text.",
                "file_path": "/library/iso27001.pdf",
                "standard_id": "ISO 27001:2022",
                "clause_number": "A.9.9",
                "page_number": 99,
                "semantic_score": 0.11,
                "rrf_score": 0.016,
            },
        ]
        rag, _search, ollama = make_rag(sources, available=True)

        result = rag.ask("Completely unrelated question?")

        self.assertEqual(result["status"], "not_found")
        self.assertTrue(result["evidence"])  # evidence still populated
        self.assertEqual(ollama.chat_calls, 0)  # abstained before LLM

    def test_no_sources_is_not_found_with_empty_evidence(self):
        """No retrieval results at all -> not_found with empty evidence."""
        rag, _search, ollama = make_rag([], available=True)

        result = rag.ask("Anything?")

        self.assertEqual(result["status"], "not_found")
        self.assertEqual(result["evidence"], [])
        self.assertEqual(ollama.chat_calls, 0)


if __name__ == "__main__":
    unittest.main()
