"""Hybrid keyword + semantic search."""

from __future__ import annotations

from typing import Any

from indexer.database import Database
from indexer.embeddings import OllamaClient, cosine_similarity, reciprocal_rank_fusion


class SearchService:
    def __init__(self, db: Database, ollama: OllamaClient | None = None):
        self.db = db
        self.ollama = ollama or OllamaClient()

    def keyword_search(
        self,
        query: str,
        standard_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        fts_query = self._prepare_fts_query(query)
        try:
            return self.db.keyword_search(fts_query, standard_id, limit)
        except Exception:
            # Fallback to simple LIKE if FTS query is malformed
            return self._fallback_search(query, standard_id, limit)

    def semantic_search(
        self,
        query: str,
        standard_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        if not self.ollama.is_available():
            return []

        query_vec = self.ollama.embed(query)
        embeddings = self.db.get_all_embeddings(self.ollama.embed_model)
        scored: list[tuple[int, float]] = []
        for chunk_id, vec in embeddings:
            score = cosine_similarity(query_vec, vec)
            scored.append((chunk_id, score))
        scored.sort(key=lambda x: x[1], reverse=True)

        results = []
        for chunk_id, score in scored[: limit * 2]:
            details = self.db.get_chunk_details(chunk_id)
            if not details:
                continue
            if standard_id and details.get("standard_id") != standard_id:
                continue
            details["score"] = score
            details["chunk_id"] = chunk_id
            results.append(details)
            if len(results) >= limit:
                break
        return results

    def hybrid_search(
        self,
        query: str,
        standard_id: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        keyword_results = self.keyword_search(query, standard_id, limit=limit * 2)
        kw_ranked = [
            (r["chunk_id"], abs(r.get("score", 0)))
            for r in keyword_results
        ]

        semantic_results = self.semantic_search(query, standard_id, limit=limit * 2)
        sem_ranked = [(r["chunk_id"], r.get("score", 0)) for r in semantic_results]

        if not sem_ranked:
            return keyword_results[:limit]

        fused = reciprocal_rank_fusion([kw_ranked, sem_ranked])
        merged: dict[int, dict] = {}
        for r in keyword_results + semantic_results:
            merged[r["chunk_id"]] = r

        results = []
        for chunk_id, rrf_score in fused[:limit]:
            item = merged.get(chunk_id)
            if item:
                item = dict(item)
                item["rrf_score"] = rrf_score
                results.append(item)
        return results

    def _prepare_fts_query(self, query: str) -> str:
        query = query.strip()
        if not query:
            return '""'
        # Clause numbers: search as phrase
        if query.replace(".", "").replace(" ", "").isalnum() and "." in query:
            return f'"{query}"'
        terms = query.split()
        if len(terms) == 1:
            return terms[0]
        return " OR ".join(terms)

    def _fallback_search(
        self,
        query: str,
        standard_id: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        sql = """
            SELECT c.id AS chunk_id, c.content, c.page_number, c.chunk_type,
                   cl.clause_number, cl.title AS clause_title,
                   d.id AS document_id, d.standard_id, d.title AS document_title,
                   d.file_path, d.file_name, 0 AS score
            FROM chunks c
            JOIN documents d ON d.id = c.document_id
            LEFT JOIN clauses cl ON cl.id = c.clause_id
            WHERE c.content LIKE ?
        """
        params: list = [f"%{query}%"]
        if standard_id:
            sql += " AND d.standard_id = ?"
            params.append(standard_id)
        sql += " LIMIT ?"
        params.append(limit)
        rows = self.db.conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
