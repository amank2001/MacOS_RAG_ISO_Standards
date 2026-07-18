"""Grounded Q&A using retrieved chunks and local LLM."""

from __future__ import annotations

import re
from typing import Any

from indexer.database import Database
from indexer.embeddings import OllamaClient
from indexer.sanitize import sanitize_path
from indexer.search import SearchService

SIMILARITY_THRESHOLD = 0.3

RAG_SYSTEM_PROMPT = """You are an ISO standards reference assistant. Answer questions using ONLY the provided document excerpts.

Rules:
1. Answer ONLY from the provided excerpts — never use outside knowledge.
2. Cite every claim with the standard ID and clause number (e.g. ISO 27001:2022, Clause A.5.1).
3. If the excerpts do not contain enough information, respond with: "Not found in library."
4. Be precise and concise. Quote key requirement text when relevant.
5. Do not invent clause numbers, requirements, or diagram descriptions."""


class RAGService:
    DEFAULT_MAX_CONTEXT_TOKENS = 4096

    def __init__(
        self,
        db: Database,
        search: SearchService | None = None,
        ollama: OllamaClient | None = None,
        max_context_tokens: int = DEFAULT_MAX_CONTEXT_TOKENS,
    ):
        self.db = db
        self.ollama = ollama or OllamaClient()
        self.search = search or SearchService(db, self.ollama)
        self.max_context_tokens = max_context_tokens

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """Estimate the number of tokens in a text string.

        Uses a simple heuristic: split on whitespace and multiply by 1.3
        to approximate sub-word tokenization used by most LLMs.
        """
        word_count = len(text.split())
        return int(word_count * 1.3)

    def _truncate_context_blocks(self, context_blocks: list[str]) -> list[str]:
        """Truncate context blocks to fit within max_context_tokens.

        Removes whole blocks from the end (least relevant) rather than
        cutting mid-text. Returns the subset of blocks that fits.
        """
        truncated: list[str] = []
        total_tokens = 0
        for block in context_blocks:
            block_tokens = self.estimate_tokens(block)
            if total_tokens + block_tokens > self.max_context_tokens:
                break
            truncated.append(block)
            total_tokens += block_tokens
        # Always include at least one block if available
        if not truncated and context_blocks:
            truncated.append(context_blocks[0])
        return truncated

    def ask(
        self,
        question: str,
        standard_id: str | None = None,
        top_k: int = 12,
    ) -> dict[str, Any]:
        sources = self.search.hybrid_search(question, standard_id, limit=top_k)

        # Abstain only when retrieval returns nothing at all.
        if not sources:
            return {
                "status": "not_found",
                "answer": "Not found in library.",
                "evidence": [],
                "figures": [],
                "warnings": [],
            }

        # Offline: we cannot call the LLM and have no cosine signal to gate on.
        # Return the top matching excerpts directly so evidence + Export PDF work.
        if not self.ollama.is_available():
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
                "status": "answered",
                "answer": "\n".join(summary_lines),
                "evidence": self._build_evidence(sources),
                "figures": self._collect_figures(sources),
                "warnings": [],
            }

        # Online: abstain only when a real semantic cosine signal exists AND the
        # best cosine is below the threshold. Never threshold on rrf_score.
        cosine_scores = [
            s for s in (src.get("semantic_score") for src in sources) if s is not None
        ]
        if cosine_scores and max(cosine_scores) < SIMILARITY_THRESHOLD:
            return {
                "status": "not_found",
                "answer": "Not found in library.",
                "evidence": self._build_evidence(sources),
                "figures": [],
                "warnings": [],
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

        # Truncate context to stay within max_context_tokens
        context_blocks = self._truncate_context_blocks(context_blocks)

        context = "\n---\n".join(context_blocks)
        user_prompt = f"""Question: {question}

Document excerpts:
{context}

Provide a grounded answer with citations."""

        answer = self.ollama.chat(
            [
                {"role": "system", "content": RAG_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ]
        )

        evidence = self._build_evidence(sources)
        warnings = self._validate_references(answer, evidence)

        return {
            "status": "answered",
            "answer": answer,
            "evidence": evidence,
            "figures": self._collect_figures(sources),
            "warnings": warnings,
        }

    def _validate_references(self, answer: str, evidence: list[dict]) -> list[str]:
        """Scan LLM answer for clause/standard references not in evidence.

        Returns a list of warning strings for any reference in the answer text
        that does not correspond to a chunk in the evidence list.
        """
        warnings: list[str] = []

        # Collect clause numbers and standard IDs present in evidence
        evidence_clauses: set[str] = set()
        evidence_standards: set[str] = set()
        for ev in evidence:
            if ev.get("clause_number"):
                evidence_clauses.add(ev["clause_number"].strip())
            if ev.get("standard_id"):
                evidence_standards.add(ev["standard_id"].strip())

        # Regex for clause references: "Clause A.5.1", "clause 6.1.2", or standalone like "A.8.1"
        # Matches patterns like "Clause X.Y.Z" or standalone alphanumeric clause numbers
        clause_pattern = re.compile(
            r"(?:[Cc]lause\s+)([A-Z]?\d+(?:\.\d+)+)"  # "Clause 6.1.2" or "Clause A.5.1"
            r"|"
            r"(?:[Cc]lause\s+)([A-Z]\.\d+(?:\.\d+)*)"  # "Clause A.5.1"
        )

        # Also match standalone clause-like references (e.g., "A.5.1" not preceded by "ISO")
        standalone_clause_pattern = re.compile(
            r"(?<![A-Za-z0-9/])([A-Z]\.\d+(?:\.\d+)*)"  # A.5.1, A.8.1.2, etc.
        )

        # Regex for ISO standard references: "ISO 27001:2022", "ISO 9001", "ISO/IEC 27002:2022"
        standard_pattern = re.compile(
            r"(ISO(?:/IEC)?\s+\d+(?::\d{4})?)"
        )

        # Extract clause references from the answer
        answer_clauses: set[str] = set()
        for match in clause_pattern.finditer(answer):
            # Group 1 or group 2 depending on which alternative matched
            clause = match.group(1) or match.group(2)
            if clause:
                answer_clauses.add(clause.strip())

        for match in standalone_clause_pattern.finditer(answer):
            clause = match.group(1)
            if clause:
                answer_clauses.add(clause.strip())

        # Extract standard references from the answer
        answer_standards: set[str] = set()
        for match in standard_pattern.finditer(answer):
            answer_standards.add(match.group(1).strip())

        # Check clause references against evidence
        for clause in sorted(answer_clauses):
            if clause not in evidence_clauses:
                warnings.append(
                    f"Answer references clause '{clause}' which was not found in retrieved evidence"
                )

        # Check standard references against evidence
        for standard in sorted(answer_standards):
            if standard not in evidence_standards:
                warnings.append(
                    f"Answer references standard '{standard}' which was not found in retrieved evidence"
                )

        return warnings

    def _build_evidence(self, sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert raw source dicts into structured evidence objects.

        Each evidence entry contains:
        - chunk_id: int
        - file_path: absolute document path from the DB (matches /documents and
          /search); the local-only Swift client opens documents by this path.
        - standard_id: str or None
        - clause_number: str or None
        - page_number: int or None
        - quoted_text: the chunk content text
        - bbox: [x0, y0, x1, y1] list or None
        """
        evidence = []
        for src in sources:
            # Use the absolute DB file_path so the local-only client can open
            # the document (consistent with /documents and /search). Fall back
            # to file_name only if file_path is missing.
            file_path = src.get("file_path") or src.get("file_name") or ""

            # Build bbox as [x0, y0, x1, y1] if all four values are present
            bbox_x0 = src.get("bbox_x0")
            bbox_y0 = src.get("bbox_y0")
            bbox_x1 = src.get("bbox_x1")
            bbox_y1 = src.get("bbox_y1")
            if all(v is not None for v in (bbox_x0, bbox_y0, bbox_x1, bbox_y1)):
                bbox = [bbox_x0, bbox_y0, bbox_x1, bbox_y1]
            else:
                bbox = None

            evidence.append({
                "chunk_id": src.get("chunk_id"),
                "file_path": file_path,
                "standard_id": src.get("standard_id"),
                "clause_number": src.get("clause_number"),
                "page_number": src.get("page_number"),
                "quoted_text": src.get("content", ""),
                "bbox": bbox,
            })
        return evidence

    def _collect_figures(self, sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
        figures: list[dict[str, Any]] = []
        seen: set[int] = set()
        for src in sources:
            clause_id = src.get("clause_id")
            if clause_id:
                for fig in self.db.get_figures_for_clause(clause_id):
                    if fig["id"] not in seen:
                        seen.add(fig["id"])
                        # Sanitize image_path to avoid exposing absolute paths
                        if "image_path" in fig:
                            fig["image_path"] = sanitize_path(fig["image_path"])
                        figures.append(fig)
            doc_id = src.get("document_id")
            page = src.get("page_number")
            if doc_id and page:
                for fig in self.db.get_figures_for_document(doc_id):
                    if fig["page_number"] == page and fig["id"] not in seen:
                        seen.add(fig["id"])
                        # Sanitize image_path to avoid exposing absolute paths
                        if "image_path" in fig:
                            fig["image_path"] = sanitize_path(fig["image_path"])
                        figures.append(fig)
        return figures
