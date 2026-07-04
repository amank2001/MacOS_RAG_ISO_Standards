"""Grounded Q&A using retrieved chunks and local LLM."""

from __future__ import annotations

from typing import Any

from indexer.database import Database
from indexer.embeddings import OllamaClient
from indexer.search import SearchService

RAG_SYSTEM_PROMPT = """You are an ISO standards reference assistant. Answer questions using ONLY the provided document excerpts.

Rules:
1. Answer ONLY from the provided excerpts — never use outside knowledge.
2. Cite every claim with the standard ID and clause number (e.g. ISO 27001:2022, Clause A.5.1).
3. If the excerpts do not contain enough information, respond with: "Not found in library."
4. Be precise and concise. Quote key requirement text when relevant.
5. Do not invent clause numbers, requirements, or diagram descriptions."""


class RAGService:
    def __init__(
        self,
        db: Database,
        search: SearchService | None = None,
        ollama: OllamaClient | None = None,
    ):
        self.db = db
        self.ollama = ollama or OllamaClient()
        self.search = search or SearchService(db, self.ollama)

    def ask(
        self,
        question: str,
        standard_id: str | None = None,
        top_k: int = 12,
    ) -> dict[str, Any]:
        sources = self.search.hybrid_search(question, standard_id, limit=top_k)

        if not sources:
            return {
                "answer": "Not found in library.",
                "sources": [],
                "figures": [],
            }

        context_blocks = []
        for i, src in enumerate(sources, 1):
            block = (
                f"[Excerpt {i}]\n"
                f"Standard: {src.get('standard_id') or 'Unknown'}\n"
                f"Clause: {src.get('clause_number') or 'N/A'}\n"
                f"Document: {src.get('document_title') or src.get('file_name')}\n"
                f"Page: {src.get('page_number') or 'N/A'}\n"
                f"Content:\n{src.get('content', '')}\n"
            )
            context_blocks.append(block)

        context = "\n---\n".join(context_blocks)
        user_prompt = f"""Question: {question}

Document excerpts:
{context}

Provide a grounded answer with citations."""

        if not self.ollama.is_available():
            # Offline fallback: return top source excerpts directly
            summary_lines = [
                "Ollama is not available. Showing top matching excerpts:",
                "",
            ]
            for src in sources[:5]:
                summary_lines.append(
                    f"- {src.get('standard_id', 'Unknown')}, "
                    f"Clause {src.get('clause_number', 'N/A')}, "
                    f"p.{src.get('page_number', '?')}: "
                    f"{src.get('content', '')[:200]}..."
                )
            return {
                "answer": "\n".join(summary_lines),
                "sources": sources,
                "figures": self._collect_figures(sources),
            }

        answer = self.ollama.chat(
            [
                {"role": "system", "content": RAG_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ]
        )

        return {
            "answer": answer,
            "sources": sources,
            "figures": self._collect_figures(sources),
        }

    def _collect_figures(self, sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
        figures: list[dict[str, Any]] = []
        seen: set[int] = set()
        for src in sources:
            clause_id = src.get("clause_id")
            if clause_id:
                for fig in self.db.get_figures_for_clause(clause_id):
                    if fig["id"] not in seen:
                        seen.add(fig["id"])
                        figures.append(fig)
            doc_id = src.get("document_id")
            page = src.get("page_number")
            if doc_id and page:
                for fig in self.db.get_figures_for_document(doc_id):
                    if fig["page_number"] == page and fig["id"] not in seen:
                        seen.add(fig["id"])
                        figures.append(fig)
        return figures
