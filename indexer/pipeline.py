"""Document ingestion pipeline."""

from __future__ import annotations

import logging
from pathlib import Path

from indexer.database import Database
from indexer.embeddings import OllamaClient
from indexer.extractors.figure_extractor import save_figures
from indexer.parsers.clause_detector import (
    detect_standard_id,
    estimate_tokens,
    parent_clause_number,
    split_text_by_clauses,
)
from indexer.parsers.content_classifier import classify_content_type
from indexer.parsers.docx_parser import parse_docx
from indexer.parsers.pdf_parser import parse_pdf

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".doc"}


class IngestionPipeline:
    def __init__(
        self,
        db: Database,
        figures_dir: Path,
        ollama: OllamaClient | None = None,
        embed: bool = True,
    ):
        self.db = db
        self.figures_dir = figures_dir
        self.ollama = ollama or OllamaClient()
        self.embed = embed

    def ingest_library(self, library_path: str | Path, library_name: str | None = None) -> dict:
        path = Path(library_path).resolve()
        if not path.is_dir():
            raise ValueError(f"Library path is not a directory: {path}")

        library_id = self.db.get_or_create_library(str(path), library_name)
        stats = {"indexed": 0, "skipped": 0, "errors": 0, "files": []}

        for file_path in sorted(path.rglob("*")):
            if not file_path.is_file():
                continue
            if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            if file_path.name.startswith("."):
                continue
            try:
                result = self.ingest_file(library_id, file_path)
                stats["files"].append(result)
                if result["status"] == "indexed":
                    stats["indexed"] += 1
                elif result["status"] == "skipped":
                    stats["skipped"] += 1
            except Exception as exc:
                logger.exception("Failed to ingest %s", file_path)
                stats["errors"] += 1
                stats["files"].append(
                    {"file": str(file_path), "status": "error", "error": str(exc)}
                )

        return stats

    def ingest_file(self, library_id: int, file_path: Path) -> dict:
        file_path = file_path.resolve()
        rel_path = str(file_path)
        file_type = file_path.suffix.lower().lstrip(".")
        if file_type == "doc":
            file_type = "docx"

        file_hash = self.db.file_hash(file_path)
        existing = self.db.get_document_by_path(library_id, rel_path)
        if existing and existing["file_hash"] == file_hash and existing["status"] == "indexed":
            return {"file": rel_path, "status": "skipped", "document_id": existing["id"]}

        parsed = parse_docx(file_path) if file_type == "docx" else parse_pdf(file_path)
        standard_id = detect_standard_id(parsed.full_text, file_path.name)
        title = parsed.title or file_path.stem

        doc_id = self.db.upsert_document(
            library_id=library_id,
            file_path=rel_path,
            file_name=file_path.name,
            file_hash=file_hash,
            file_type=file_type,
            standard_id=standard_id,
            title=title,
            page_count=len(parsed.pages),
        )
        self.db.set_document_status(doc_id, "indexing")

        try:
            with self.db.transaction():
                self._index_clauses_and_chunks(doc_id, parsed)
                figures = save_figures(parsed, self.figures_dir, doc_id)
                self._store_figures(doc_id, figures)
                if self.embed and self.ollama.is_available():
                    self._embed_document_chunks(doc_id)
            self.db.set_document_status(doc_id, "indexed")
            return {"file": rel_path, "status": "indexed", "document_id": doc_id}
        except Exception as exc:
            self.db.set_document_status(doc_id, "error", str(exc))
            raise

    def _index_clauses_and_chunks(self, doc_id: int, parsed) -> None:
        page_tuples = [(p.page_number, p.text) for p in parsed.pages]
        segments = split_text_by_clauses(page_tuples)

        # Build page-to-blocks mapping for efficient bbox lookup
        page_blocks: dict[int, list] = {}
        for page in parsed.pages:
            if page.blocks:
                page_blocks[page.page_number] = page.blocks

        clause_id_map: dict[str, int] = {}
        sort_order = 0

        for clause_info, page_num, content in segments:
            clause_id = None
            if clause_info and clause_info.level < 99:
                parent_num = parent_clause_number(clause_info.clause_number)
                parent_id = clause_id_map.get(parent_num) if parent_num else None
                sort_order += 1
                clause_id = self.db.insert_clause(
                    document_id=doc_id,
                    clause_number=clause_info.clause_number,
                    title=clause_info.title,
                    level=clause_info.level,
                    parent_clause_id=parent_id,
                    page_start=page_num,
                    page_end=page_num,
                    sort_order=sort_order,
                )
                clause_id_map[clause_info.clause_number] = clause_id

            # Build clause_info dict for the content classifier
            clause_info_dict: dict | None = None
            if clause_info:
                clause_info_dict = {
                    "clause_number": clause_info.clause_number,
                    "is_annex": clause_info.clause_number.lower().startswith("annex"),
                    "title": clause_info.title,
                }

            chunk_type = classify_content_type(content, clause_info_dict)

            # Look up bbox from page blocks
            bbox_x0, bbox_y0, bbox_x1, bbox_y1 = None, None, None, None
            blocks = page_blocks.get(page_num)
            if blocks:
                bbox_x0, bbox_y0, bbox_x1, bbox_y1 = self._find_bbox_for_content(
                    content, blocks
                )

            self.db.insert_chunk(
                document_id=doc_id,
                content=content,
                clause_id=clause_id,
                chunk_type=chunk_type,
                page_number=page_num,
                token_count=estimate_tokens(content),
                bbox_x0=bbox_x0,
                bbox_y0=bbox_y0,
                bbox_x1=bbox_x1,
                bbox_y1=bbox_y1,
            )

    def _find_bbox_for_content(
        self, content: str, blocks: list
    ) -> tuple[float | None, float | None, float | None, float | None]:
        """Find the bounding box that covers the content within the given blocks.

        Searches for blocks whose text appears in the content and computes a
        union bbox covering all matching blocks. If no match is found, returns
        the first block's bbox as a fallback.
        """
        matching_blocks = [b for b in blocks if b.text and b.text in content]

        if not matching_blocks:
            # Fallback: use the first block's bbox
            if blocks:
                bbox = blocks[0].bbox
                return bbox[0], bbox[1], bbox[2], bbox[3]
            return None, None, None, None

        # Compute union bbox across all matching blocks
        x0 = min(b.bbox[0] for b in matching_blocks)
        y0 = min(b.bbox[1] for b in matching_blocks)
        x1 = max(b.bbox[2] for b in matching_blocks)
        y1 = max(b.bbox[3] for b in matching_blocks)
        return x0, y0, x1, y1

    def _store_figures(self, doc_id: int, figures: list[dict]) -> None:
        clause_rows = self.db.conn.execute(
            """SELECT id, page_start, clause_number FROM clauses
               WHERE document_id = ? ORDER BY sort_order""",
            (doc_id,),
        ).fetchall()

        for fig in figures:
            clause_id = self._nearest_clause(clause_rows, fig["page_number"])
            self.db.insert_figure(
                document_id=doc_id,
                image_path=fig["image_path"],
                page_number=fig["page_number"],
                clause_id=clause_id,
                figure_number=fig.get("figure_number"),
                caption=fig.get("caption"),
                width=fig.get("width"),
                height=fig.get("height"),
            )

    def _nearest_clause(self, clause_rows, page_number: int) -> int | None:
        best_id = None
        best_page = -1
        for row in clause_rows:
            page = row["page_start"] or 0
            if page <= page_number and page >= best_page:
                best_page = page
                best_id = row["id"]
        return best_id

    def _embed_document_chunks(self, doc_id: int) -> None:
        rows = self.db.conn.execute(
            "SELECT id, content FROM chunks WHERE document_id = ?", (doc_id,)
        ).fetchall()
        for row in rows:
            try:
                vec = self.ollama.embed(row["content"][:8000])
                self.db.store_embedding(row["id"], self.ollama.embed_model, vec)
            except Exception as exc:
                logger.warning("Embedding failed for chunk %s: %s", row["id"], exc)
