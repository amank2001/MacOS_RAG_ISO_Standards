# Implementation Plan: RAG MVP Enhancement

## Overview

Incremental enhancements to the ISO Standards RAG Knowledge Base covering: schema migration, PDF parser bbox extraction, content type classification, retrieval boosting, structured answer generation with evidence validation, API security (token auth + input validation), atomic re-indexing, Swift app updates (token auth + enhanced citations + PDF export), and an evaluation test suite.

## Tasks

- [x] 1. Add bbox columns (bbox_x0, bbox_y0, bbox_x1, bbox_y1 REAL) to chunks table in resources/schema.sql and extend chunk_type CHECK to include: text, heading, note, table, figure_caption, definition, annex, body_text
- [x] 2. Add migration logic in Database._init_schema() using ALTER TABLE ADD COLUMN wrapped in try/except for existing databases
- [x] 3. Update Database.insert_chunk() to accept optional bbox_x0, bbox_y0, bbox_x1, bbox_y1 parameters and persist them
- [x] 4. Add TextBlock dataclass to pdf_parser.py (page_number, text, bbox tuple, block_index) and add blocks field to ParsedPage
- [x] 5. Modify parse_pdf() to use page.get_text("dict") to populate TextBlock list with bbox coordinates, falling back to get_text("text") with null bbox when blocks are empty
- [x] 6. Create indexer/parsers/content_classifier.py with classify_content_type(text, clause_info) function implementing heuristic rules for heading, definition, note, table, annex, figure_caption, body_text
- [x] 7. Integrate content classifier into IngestionPipeline._index_clauses_and_chunks() passing classified type and bbox data to insert_chunk()
- [x] 8. Add _analyze_query(query) method to SearchService extracting clause numbers, standard IDs, and content type keywords from the query text
- [x] 9. Add _apply_boosts(results, query_analysis) method to SearchService applying clause boost (2.0x), standard boost (1.5x), and content type boost (1.5x) to RRF scores
- [x] 10. Integrate _apply_boosts into hybrid_search() after RRF fusion before returning results
- [x] 11. Add similarity threshold check in RAGService.ask(): if max chunk score < 0.3, return status not_found without calling Ollama
- [x] 12. Restructure RAGService.ask() return format to include status, evidence array (chunk_id, file_path relative, standard_id, clause_number, page_number, quoted_text, bbox), and warnings list
- [x] 13. Add post-generation validation in RAGService: scan LLM answer for clause/standard references, check against evidence list, add unreferenced claims to warnings
- [x] 14. Add context token limiter: truncate assembled context to configurable max tokens (default 4096) before sending to Ollama
- [x] 15. Add Pydantic validators to AskRequest: question max_length=2000, top_k le=50; return HTTP 400 on violation
- [x] 16. Create indexer/auth.py with generate_token() that writes a 32-byte hex token to application support directory and verify_token() FastAPI dependency
- [x] 17. Apply verify_token dependency to all routes except /health in create_app() and remove wildcard CORS
- [x] 18. Add response path sanitizer utility and apply to all file_path fields in /search and /ask responses
- [x] 19. Refactor ingest_file() to wrap chunk/embedding insertion in a single database transaction with ROLLBACK on failure
- [ ] 20. Update BackendClient.swift to read API token from application support directory and add Authorization Bearer header to all requests
- [ ] 21. Update AskResponse Swift model to match new structured response (status, evidence array with quoted_text and bbox, warnings)
- [ ] 22. Update QAView to display answer status and render evidence citations as clickable links that open PDFViewerSheet at the cited page
- [ ] 23. When bbox data is available in evidence, add PDFKit highlight annotation at the bbox coordinates in PDFViewerSheet
- [ ] 24. Create ISOStandardsKB/Services/PDFExporter.swift that generates a PDF report (question, answer, numbered citations, timestamp, disclaimer footer) using Core Graphics
- [ ] 25. Add Export PDF button to QAView answer section that calls PDFExporter and presents a save dialog
- [ ] 26. Create tests/eval_dataset.json with 15+ test cases and tests/evaluation.py with run_evaluation() computing recall@10, citation_accuracy, p95_latency
- [ ] 27. Add evaluate CLI command to isokb.py that runs the evaluation suite and prints results with regression detection

## Task Dependency Graph

```json
{
  "waves": [
    [1, 4, 6, 8, 15, 16, 26],
    [2, 5, 9, 11, 17, 27],
    [3, 7, 10, 12, 18],
    [19, 13, 14, 20],
    [21, 24],
    [22, 23, 25]
  ]
}
```

Parallel tracks:
- **Track A (Backend Parsing):** Tasks 1–7, 19
- **Track B (Retrieval):** Tasks 8–10
- **Track C (RAG Answer):** Tasks 11–15, 18
- **Track D (Security):** Tasks 16–17
- **Track E (Swift App):** Tasks 20–25
- **Track F (Evaluation):** Tasks 26–27

## Notes

- All Python changes use existing dependencies only (no new pip packages required)
- Swift changes use system frameworks (PDFKit, Core Graphics) already available
- Schema migration is backward-compatible — existing databases gain new nullable columns
- Token auth can be temporarily disabled during development by skipping the verify_token dependency
- The evaluation suite requires at least one indexed library to produce meaningful results

