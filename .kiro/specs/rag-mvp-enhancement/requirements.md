# Requirements Document

## Introduction

This document specifies requirements for the MVP enhancement of the ISO Standards RAG Knowledge Base application. The system already provides library management, hybrid search (keyword + semantic), basic Q&A with citations, and PDF viewing. These enhancements focus on improving answer quality, citation precision, and security within a 2-day delivery window. Each requirement builds incrementally on the existing codebase.

## Glossary

- **Indexer**: The Python/FastAPI backend service (indexer/ directory) handling parsing, embeddings, search, and RAG
- **App**: The macOS SwiftUI application providing the user interface
- **Ollama**: The local LLM daemon providing embedding and chat capabilities
- **Chunk**: A unit of indexed text already stored in the chunks table
- **Evidence_Record**: A structured citation object adding quotation and coordinates to existing search results
- **API_Token**: A per-launch bearer token for App-to-Indexer authentication

## Requirements

### Requirement 1: Evaluation Test Suite

**User Story:** As a developer, I want a small evaluation dataset, so that I can verify improvements do not regress existing quality.

#### Acceptance Criteria

1. THE Indexer SHALL include an evaluation dataset of at least 15 test cases covering clause-number lookups, natural language questions, not-in-library questions, and cross-standard comparisons stored as a JSON file in the tests/ directory
2. WHEN an evaluation run is triggered via CLI command, THE Indexer SHALL execute all test cases and report retrieval recall at k=10, citation accuracy, and p95 latency
3. WHEN any metric drops below baseline by more than 10 percentage points, THE Indexer SHALL flag the regression in the output

### Requirement 2: Enhanced Text Extraction with Block Coordinates

**User Story:** As a user, I want citations to reference exact positions in the PDF, so that I can jump to the precise quoted text.

#### Acceptance Criteria

1. WHEN a PDF is parsed, THE Indexer SHALL extract text blocks with page number and bounding rectangle coordinates (x0, y0, x1, y1) in addition to the text content
2. WHEN chunks are stored, THE Indexer SHALL persist the bounding coordinates alongside existing chunk data in a new bbox column
3. WHEN a chunk has no extractable text (scanned page), THE Indexer SHALL log a warning and skip that page rather than failing the entire document

### Requirement 3: Content Type Classification

**User Story:** As a user, I want chunks classified by content type, so that retrieval can prioritize the right kind of content for each question.

#### Acceptance Criteria

1. WHEN text is extracted, THE Indexer SHALL classify each chunk as one of: heading, definition, note, table, annex, figure_caption, or body_text using heuristic pattern matching on the text content
2. THE Indexer SHALL store the content type in the existing chunk_type column extending the current allowed values
3. WHEN a question targets a specific content type (detected via keywords like "define", "table", "annex"), THE Indexer SHALL boost chunks of that type during ranking

### Requirement 4: Improved Retrieval Ranking

**User Story:** As a user, I want search results that boost matching clause numbers and standards, so that targeted lookups return the right result first.

#### Acceptance Criteria

1. WHEN a hybrid search is performed, THE Indexer SHALL apply a boost multiplier to chunks where the clause number matches a clause number detected in the query
2. WHEN a hybrid search is performed, THE Indexer SHALL apply a boost multiplier to chunks where the standard_id matches a standard detected in the query
3. WHEN the query mentions a specific content type keyword, THE Indexer SHALL boost matching content type chunks by a configurable factor (default 1.5x)

### Requirement 5: Structured Answer with Evidence

**User Story:** As a user, I want answers that clearly separate claims from evidence, so that I can verify each statement independently.

#### Acceptance Criteria

1. WHEN the Indexer generates an answer, THE Indexer SHALL return a structured response containing: status (answered, not_found, or partial), answer text, and a list of evidence objects each linking a claim to source chunk IDs
2. WHEN an evidence object is returned, THE Indexer SHALL include: document file path, standard_id, clause_number, page_number, and the exact quoted text from the chunk
3. IF no retrieved chunk meets a minimum similarity threshold of 0.3, THEN THE Indexer SHALL return status not_found without calling the LLM
4. THE Indexer SHALL validate that every source referenced in the answer text corresponds to a chunk that was actually retrieved — unreferenced claims are flagged in the response

### Requirement 6: Citation Click-to-Source in the App

**User Story:** As a user, I want to click a citation in the answer and jump to the exact page in the PDF viewer, so that I can verify the source instantly.

#### Acceptance Criteria

1. WHEN the App displays an answer with evidence, THE App SHALL render each citation as a clickable link showing the standard, clause, and page
2. WHEN the user clicks a citation link, THE App SHALL open the PDF viewer at the referenced page number
3. WHEN bounding coordinates are available for a cited chunk, THE App SHALL scroll to and highlight the cited region using PDFKit annotations

### Requirement 7: Per-Launch API Token Authentication

**User Story:** As a user, I want communication between the App and backend secured with a per-launch token, so that other local processes cannot access my data.

#### Acceptance Criteria

1. WHEN the Indexer starts, THE Indexer SHALL generate a random 32-byte hex API_Token and write it to a known file in the application support directory
2. WHEN the App connects to the Indexer, THE App SHALL read the token file and include it as a Bearer token in the Authorization header of every HTTP request
3. IF a request arrives without a valid API_Token, THEN THE Indexer SHALL reject it with HTTP 401 Unauthorized
4. THE Indexer SHALL bind exclusively to 127.0.0.1 and THE Indexer SHALL not configure wildcard CORS origins

### Requirement 8: Input Validation and Safety Limits

**User Story:** As a user, I want the system to enforce input limits, so that malicious or oversized inputs cannot exhaust resources.

#### Acceptance Criteria

1. THE Indexer SHALL reject questions longer than 2000 characters with HTTP 400
2. THE Indexer SHALL limit the context window assembled for Ollama to a maximum of 4096 tokens (configurable)
3. THE Indexer SHALL cap the top_k parameter at 50 and reject requests exceeding this limit
4. THE Indexer SHALL not expose absolute file system paths in API responses — paths SHALL be relative to the library root

### Requirement 9: Atomic Re-indexing

**User Story:** As a user, I want document re-indexing to be safe, so that a failure during re-index does not corrupt my existing data.

#### Acceptance Criteria

1. WHEN a document is re-indexed, THE Indexer SHALL write new chunks and embeddings within a database transaction
2. IF the transaction fails, THEN THE Indexer SHALL roll back and preserve the previous indexed state unchanged
3. WHEN re-indexing completes successfully, THE Indexer SHALL atomically replace old chunks with new chunks in a single commit

### Requirement 10: Basic PDF Export of Answers

**User Story:** As a user, I want to export a Q&A result as a simple PDF report, so that I can share findings with colleagues.

#### Acceptance Criteria

1. WHEN the user requests a PDF export of an answer, THE App SHALL generate a PDF containing: the question, the answer text, numbered citations with standard/clause/page references, and the generation timestamp
2. THE App SHALL render the PDF using native Core Graphics or PDFKit without third-party dependencies
3. THE App SHALL include a disclaimer footer stating "Generated from locally indexed sources — verify against official publications"

