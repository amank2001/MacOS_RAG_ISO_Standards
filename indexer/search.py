"""Hybrid keyword + semantic search."""

from __future__ import annotations

import re
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

        # Apply retrieval boosts based on query analysis
        query_analysis = self._analyze_query(query)
        results = self._apply_boosts(results, query_analysis)

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

    # Regex patterns for query analysis
    _CLAUSE_PATTERN = re.compile(r'(?:[A-Z]\.)?(?:\d+(?:\.\d+)+)')
    _STANDARD_PATTERN = re.compile(
        r'ISO(?:/IEC|/TS)?\s+\d+(?::\d{4})?', re.IGNORECASE
    )
    _CONTENT_TYPE_KEYWORDS: dict[str, str] = {
        "definition": "definition",
        "define": "definition",
        "defined": "definition",
        "table": "table",
        "tables": "table",
        "annex": "annex",
        "appendix": "annex",
        "note": "note",
        "notes": "note",
        "heading": "heading",
        "section title": "heading",
        "figure": "figure_caption",
        "diagram": "figure_caption",
        "chart": "figure_caption",
    }

    def _apply_boosts(
        self,
        results: list[dict[str, Any]],
        query_analysis: dict[str, list[str]],
    ) -> list[dict[str, Any]]:
        """Apply retrieval boosts to RRF scores based on query analysis.

        Boost multipliers:
            - Clause number match: 2.0x
            - Standard ID match: 1.5x (case-insensitive, partial match)
            - Content type match: 1.5x

        Returns results re-sorted by boosted rrf_score descending.
        """
        if not results:
            return results

        clause_numbers = query_analysis.get("clause_numbers", [])
        standard_ids = query_analysis.get("standard_ids", [])
        content_types = query_analysis.get("content_types", [])

        # If no boosts to apply, return results unchanged
        if not clause_numbers and not standard_ids and not content_types:
            return results

        # Normalize standard IDs for case-insensitive partial matching
        standard_ids_lower = [sid.lower() for sid in standard_ids]

        for result in results:
            score = result.get("rrf_score")
            if score is None:
                continue

            # Clause number boost (2.0x)
            result_clause = result.get("clause_number")
            if result_clause and clause_numbers:
                if result_clause in clause_numbers:
                    score *= 2.0

            # Standard ID boost (1.5x) — case-insensitive partial match
            result_standard = result.get("standard_id")
            if result_standard and standard_ids_lower:
                result_standard_lower = result_standard.lower()
                for sid_lower in standard_ids_lower:
                    if sid_lower in result_standard_lower or result_standard_lower in sid_lower:
                        score *= 1.5
                        break

            # Content type boost (1.5x)
            result_type = result.get("chunk_type")
            if result_type and content_types:
                if result_type in content_types:
                    score *= 1.5

            result["rrf_score"] = score

        # Re-sort by boosted rrf_score descending
        results.sort(key=lambda r: r.get("rrf_score", 0), reverse=True)
        return results

    def _analyze_query(self, query: str) -> dict[str, list[str]]:
        """Extract clause numbers, standard IDs, and content type keywords from query.

        Returns a dict with keys:
            clause_numbers: list of clause number strings (e.g. ["A.5.1", "4.2"])
            standard_ids: list of standard ID strings (e.g. ["ISO 27001:2022"])
            content_types: list of matched content type strings (e.g. ["definition"])
        """
        if not query or not query.strip():
            return {
                "clause_numbers": [],
                "standard_ids": [],
                "content_types": [],
            }

        clause_numbers = self._CLAUSE_PATTERN.findall(query)
        standard_ids = self._STANDARD_PATTERN.findall(query)

        query_lower = query.lower()
        content_types: list[str] = []
        seen_types: set[str] = set()
        for keyword, content_type in self._CONTENT_TYPE_KEYWORDS.items():
            if keyword in query_lower and content_type not in seen_types:
                content_types.append(content_type)
                seen_types.add(content_type)

        return {
            "clause_numbers": clause_numbers,
            "standard_ids": standard_ids,
            "content_types": content_types,
        }
