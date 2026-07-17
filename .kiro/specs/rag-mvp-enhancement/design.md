# Design Document

## Overview

This design describes the incremental enhancements to the existing ISO Standards RAG Knowledge Base. The implementation adds bounding-box extraction, content type classification, retrieval boosting, structured answers with evidence validation, citation-to-PDF navigation, API security, input validation, atomic re-indexing, a basic evaluation suite, and simple PDF export. All changes extend the existing architecture without major rewrites.

## Architecture

The system consists of a macOS SwiftUI frontend communicating over HTTP with a Python/FastAPI backend. Both run locally. The backend manages document parsing, indexing, search, and RAG answer generation against a SQLite database. Ollama provides local LLM inference for embeddings and chat. The enhancements add security (token auth), precision (bbox coordinates, content types, retrieval boosts), quality (structured answers, evidence validation), and observability (evaluation suite).

## Components and Interfaces

### Current State

```
┌─────────────────────┐         HTTP (localhost:8742)        ┌─────────────────────┐
│  SwiftUI App        │ ◄──────────────────────────────────► │  FastAPI Indexer     │
│  - Library browser  │                                      │  - PDF/DOCX parser   │
│  - Search view      │                                      │  - Clause detector   │
│  - Q&A view         │                                      │  - Embeddings        │
│  - PDF viewer       │                                      │  - Hybrid search     │
│  - Settings         │                                      │  - RAG (Ollama chat) │
└─────────────────────┘                                      └─────────────────────┘
                                                                      │
                                                              ┌───────┴───────┐
                                                              │  SQLite DB    │
                                                              │  + FTS5       │
                                                              │  + embeddings │
                                                              └───────────────┘
```

### Enhanced State

```
┌─────────────────────┐       HTTP + Bearer Token            ┌─────────────────────────┐
│  SwiftUI App        │ ◄──────────────────────────────────► │  FastAPI Indexer         │
│  + Citation links   │                                      │  + Block bbox extraction │
│  + PDF highlighting │                                      │  + Content type classify │
│  + PDF export       │                                      │  + Retrieval boosts      │
│  + Token auth       │                                      │  + Structured answers    │
└─────────────────────┘                                      │  + Evidence validation   │
                                                             │  + Token auth middleware │
                                                             │  + Input validation      │
                                                             │  + Atomic re-index       │
                                                             └─────────────────────────┘
```

### Component Interfaces

1. **PDF Parser** (`indexer/parsers/pdf_parser.py`) → produces `ParsedDocument` with `TextBlock` objects containing bbox
2. **Content Classifier** (`indexer/parsers/content_classifier.py` — new) → accepts text and clause info, returns content type string
3. **Search Service** (`indexer/search.py`) → extended with `_analyze_query()` and `_apply_boosts()` methods
4. **RAG Service** (`indexer/rag.py`) → returns structured response with status, evidence, warnings
5. **Auth Module** (`indexer/auth.py` — new) → generates token, provides FastAPI middleware
6. **PDF Exporter** (`ISOStandardsKB/Services/PDFExporter.swift` — new) → generates PDF from answer data
7. **Evaluation Runner** (`tests/evaluation.py` — new) → executes test suite, computes metrics

## Data Models

### TextBlock (Python — pdf_parser.py)

```python
@dataclass
class TextBlock:
    page_number: int
    text: str
    bbox: tuple[float, float, float, float]  # (x0, y0, x1, y1)
    block_index: int
```

### ParsedPage (Python — extended)

```python
@dataclass
class ParsedPage:
    page_number: int
    text: str
    blocks: list[TextBlock] = field(default_factory=list)
```

### Structured Answer Response (JSON)

```json
{
    "status": "answered | not_found | partial",
    "answer": "string",
    "evidence": [
        {
            "chunk_id": 42,
            "file_path": "relative/path.pdf",
            "standard_id": "ISO 27001:2022",
            "clause_number": "A.5.1",
            "page_number": 17,
            "quoted_text": "exact text from chunk",
            "bbox": [100.0, 200.0, 500.0, 220.0]
        }
    ],
    "figures": [],
    "warnings": []
}
```

### Schema Changes (chunks table)

```sql
ALTER TABLE chunks ADD COLUMN bbox_x0 REAL;
ALTER TABLE chunks ADD COLUMN bbox_y0 REAL;
ALTER TABLE chunks ADD COLUMN bbox_x1 REAL;
ALTER TABLE chunks ADD COLUMN bbox_y1 REAL;
```

The `chunk_type` CHECK constraint is extended to: `'text', 'heading', 'note', 'table', 'figure_caption', 'definition', 'annex', 'body_text'`

### Evaluation Test Case (JSON)

```json
{
    "id": "q1",
    "question": "What does ISO 27001 require for access control?",
    "type": "natural_language",
    "expected_standard": "ISO 27001:2022",
    "expected_clause": "A.9.1",
    "expected_keywords": ["access control", "policy"],
    "expected_not_found": false
}
```

## Error Handling

| Failure | Impact | Mitigation |
|---------|--------|------------|
| PyMuPDF `get_text("dict")` returns empty blocks | No bbox data for page | Fall back to `get_text("text")` with null bbox |
| Ollama unavailable during /ask | Cannot generate answer | Return top excerpts directly (existing behavior), status=partial |
| Token file unreadable by App | App cannot authenticate | Show connection error with instructions to restart backend |
| Re-index transaction grows too large | SQLite lock timeout | Process chunks in batches of 100 within the transaction |
| PDF export with very long answers | Multi-page layout overflow | Implement page-break logic at paragraph boundaries |
| Question exceeds 2000 chars | Potential resource abuse | Return HTTP 400 before any processing |
| top_k exceeds 50 | Excessive retrieval cost | Return HTTP 400 before any processing |

## Testing Strategy

### Unit Tests
- Content type classifier: test each heuristic rule with representative inputs
- Query analyzer: test clause/standard/content-type extraction from various queries
- Path sanitizer: verify absolute paths are stripped correctly
- Token generation: verify token format and file creation

### Integration Tests
- End-to-end /ask with structured response validation
- Token authentication: valid token succeeds, missing/invalid token gets 401
- Input validation: oversized questions rejected, top_k cap enforced
- Atomic re-index: simulate failure mid-transaction, verify rollback

### Evaluation Suite
- 15+ test cases run against indexed test corpus
- Metrics tracked over time for regression detection

## Correctness Properties

### Property 1: Block Bounding Box Validity
For all text blocks extracted from a valid PDF page, every block has bbox coordinates where x0 < x1 and y0 < y1 and all values are non-negative.
**Validates: Requirements 2.1**

### Property 2: Content Type Classification Completeness
For all text inputs to the content classifier, the output is always exactly one of the defined content types (heading, definition, note, table, annex, figure_caption, body_text).
**Validates: Requirements 3.1**

### Property 3: Structured Answer Schema Conformance
For all responses from the /ask endpoint, the response always contains a valid `status` field (one of: answered, not_found, partial) and an `evidence` array where each entry has the required fields.
**Validates: Requirements 5.1, 5.2**

### Property 4: Threshold-Based Abstention
For all queries where the maximum similarity score among retrieved chunks is below 0.3, the response status is always `not_found` and no LLM call is made.
**Validates: Requirements 5.3**

### Property 5: Input Rejection for Oversized Questions
For all question strings longer than 2000 characters, the /ask endpoint returns HTTP 400.
**Validates: Requirements 8.1**

### Property 6: Top-K Cap Enforcement
For all requests with top_k > 50, the /ask endpoint returns HTTP 400.
**Validates: Requirements 8.3**

### Property 7: No Absolute Paths in Responses
For all API responses from /search and /ask endpoints, no file_path field value starts with "/" or a Windows drive letter pattern.
**Validates: Requirements 8.4**

### Property 8: Atomic Re-index Rollback
For all simulated failures during re-indexing, the chunk count and content for the document remain identical to the pre-reindex state.
**Validates: Requirements 9.2**

