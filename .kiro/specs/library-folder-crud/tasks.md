# Implementation Plan: Library Folder CRUD

## Overview

Implement the three-pane library workspace and its supporting delete/rescan flows across both the FastAPI backend and the SwiftUI client. Work proceeds bottom-up: backend database helpers first, then API endpoints, then Swift transport (`BackendClient`), then orchestration (`IndexCoordinator`), then the split-out SwiftUI panes, and finally the `LibraryView` restructure that wires everything together. Property-based tests are placed close to each unit of implementation.

Convert the feature design into a series of prompts for a code-generation LLM that will implement each step with incremental progress. Make sure that each prompt builds on the previous prompts, and ends with wiring things together. There should be no hanging or orphaned code that isn't integrated into a previous step. Focus ONLY on tasks that involve writing, modifying, or testing code.

## Tasks

- [x] 1. Backend database layer (`indexer/database.py`)
  - [x] 1.1 Add library and document lookup, figure-path listing, and delete helpers
    - Implement `get_library(library_id)` and `get_document(document_id)` returning `dict | None` for the `libraries` / `documents` rows.
    - Implement `figure_paths_for_document(document_id)` returning `list[str]` of `figures.image_path`.
    - Implement `figure_paths_for_library(library_id)` returning `list[str]` from `figures` joined against `documents.library_id`.
    - Implement `delete_library(library_id) -> int` and `delete_document(document_id) -> int` that execute a single `DELETE` and commit, returning `cur.rowcount`.
    - Rely on the existing `PRAGMA foreign_keys = ON` connection so cascades on `documents`, `clauses`, `chunks`, `chunk_embeddings`, `figures`, and the `chunks_ad` FTS trigger fire automatically.
    - See design section "Backend: `indexer/database.py`".
    - _Requirements: 2.4, 2.7, 3.4, 3.7, 8.1_

  - [ ]* 1.2 Write property test for cascade deletion
    - **Property 1: Cascade deletion preserves referential integrity**
    - **Validates: Requirements 2.4, 2.7, 3.4, 3.7**
    - Use `hypothesis` with generated library sets (folders, documents, clauses, chunks, chunk_embeddings, figures) inserted into a temporary SQLite DB.
    - After each `delete_library(id)` or `delete_document(id)` call, assert there are no rows in `libraries`, `documents`, `clauses`, `chunks`, `chunk_embeddings`, `figures`, or `chunks_fts` that reference the deleted entity by id or any cascaded ancestor id.
    - Tag: `Feature: library-folder-crud, Property 1`.

- [x] 2. Backend API layer (`indexer/api.py`)
  - [x] 2.1 Add watcher-stop and figure-cleanup helpers, refactor `POST /watch/stop`
    - Introduce `_stop_watcher(path: str) -> str | None` inside `create_app` that resolves the path, pops the entry from the `watchers` dict, calls `stop()` inside a `try/except` and returns a message or `None`.
    - Introduce `_delete_figure_files(paths: list[str]) -> list[dict[str, str]]` that calls `Path(p).unlink(missing_ok=True)` for each path, collecting `{"image_path": p, "error": str(exc)}` entries for any `OSError`.
    - Refactor the existing `POST /watch/stop` handler to call `_stop_watcher` instead of manipulating `watchers` inline.
    - See design section "Backend: `indexer/api.py`".
    - _Requirements: 7.1, 7.2, 8.2, 8.3_

  - [x] 2.2 Add `DELETE /libraries/{id}` and `DELETE /documents/{id}` endpoints
    - Implement `delete_library(library_id)`: look up via `db.get_library`, return `HTTPException(404)` if missing, then call `_stop_watcher(lib["path"])`, fetch figure paths with `db.figure_paths_for_library`, call `_delete_figure_files`, then `db.delete_library`, and return `{"status": "ok", "removed": ..., "figure_errors": [...], "watcher_error": ...}`.
    - Implement `delete_document(document_id)`: look up via `db.get_document`, return `HTTPException(404)` if missing, then fetch figure paths with `db.figure_paths_for_document`, call `_delete_figure_files`, then `db.delete_document`, and return `{"status": "ok", "removed": ..., "figure_errors": [...], "watcher_error": None}`.
    - Both handlers must always run figure cleanup and row deletion when the target exists, even when `_stop_watcher` returns a non-empty error string.
    - Both handlers must close the DB in a `finally` block, matching the existing endpoint style.
    - See design section "Backend: `indexer/api.py`" and "Interfaces / HTTP".
    - _Requirements: 2.3, 2.4, 3.3, 3.4, 7.1, 7.2, 8.1, 8.2, 8.3_

  - [ ]* 2.3 Write property test for rescan idempotency
    - **Property 7: Rescan is idempotent over unchanged files**
    - **Validates: Requirement 4.3**
    - Use `pytest` + `hypothesis` (or a deterministic generator) to build a temporary folder with N generated PDF/DOCX-like files, run `IngestionPipeline.ingest_library` once, then a second time.
    - Assert the second run reports zero new `documents` rows for files whose SHA-256 matches an existing `documents.file_hash`, all such files appear in the response's `skipped` count, and existing rows' `id` and `file_hash` values are unchanged.
    - Tag: `Feature: library-folder-crud, Property 7`.

  - [ ]* 2.4 Write property test for watcher stop ordering on folder deletion
    - **Property 9: Watcher is stopped before folder deletion returns**
    - **Validates: Requirement 7.1**
    - Use `pytest` with FastAPI's `TestClient` and a fake `LibraryWatcher` (a stub whose `stop()` records a timestamp and whose registration inserts into the app's `watchers` dict).
    - Generate arbitrary library sets, register watchers for a random subset, then hit `DELETE /libraries/{id}`. Assert every registered watcher for a resolved library path had `stop()` called and the entry is absent from `watchers` before the response body is emitted.
    - Tag: `Feature: library-folder-crud, Property 9`.

  - [ ]* 2.5 Write property test for watcher-stop failure resilience
    - **Property 10: Watcher-stop failures do not abort deletion**
    - **Validates: Requirement 7.2**
    - Use `pytest` + `TestClient` with a stub watcher whose `stop()` raises. Insert library rows with associated documents and figure files.
    - For every generated failure message, assert that after `DELETE /libraries/{id}`: (a) figure cleanup ran for all documents under the library, (b) the `libraries` row is gone, (c) response status is 200, and (d) `response.json()["watcher_error"]` contains the raised message.
    - Tag: `Feature: library-folder-crud, Property 10`.

  - [ ]* 2.6 Write property test for best-effort figure cleanup
    - **Property 11: Figure image cleanup is best-effort and total**
    - **Validates: Requirements 8.1, 8.2, 8.3**
    - Use `pytest` + `hypothesis` to generate lists of `image_path` values combining existing files, missing files, and paths made unreadable via monkeypatched `Path.unlink` raising `OSError`.
    - Assert that after `DELETE /documents/{id}` or `DELETE /libraries/{id}`: every existing file is removed, missing paths are silently accepted, `OSError` paths appear in `figure_errors` with the raised error string, response status is 200, and the row is still deleted.
    - Tag: `Feature: library-folder-crud, Property 11`.

- [x] 3. Checkpoint - Backend endpoints and property tests pass
  - Ensure all backend tests pass, ask the user if questions arise.

- [x] 4. Swift `BackendClient` transport (`ISOStandardsKB/Services/BackendClient.swift`)
  - [x] 4.1 Add `DeletionResult`, `FigureError`, and shared `delete<T>` helper
    - Add nested `DeletionResult: Decodable` with `status: String`, `removed: Int?`, `figureErrors: [FigureError]`, `watcherError: String?` mapped from `figure_errors` / `watcher_error` via `CodingKeys`.
    - Add `FigureError: Decodable, Hashable` with `imagePath: String` and `error: String`, `CodingKeys` mapping `imagePath` -> `image_path`.
    - Add a private `delete<T: Decodable>(_ path: String) async throws -> T` helper that builds an `URLRequest` with `httpMethod = "DELETE"`, calls `session.data(for:)`, and reuses the existing `validate(response:data:)` before decoding.
    - See design section "BackendClient".
    - _Requirements: 2.3, 3.3, 7.2, 8.3_

  - [x] 4.2 Add `deleteLibrary(id:)` and `deleteDocument(id:)`
    - Implement `func deleteLibrary(id: Int) async throws -> DeletionResult { try await delete("/libraries/\(id)") }`.
    - Implement `func deleteDocument(id: Int) async throws -> DeletionResult { try await delete("/documents/\(id)") }`.
    - Do not add retry logic. Non-2xx responses must surface via the existing `validate` error path so callers can display the returned body.
    - _Requirements: 2.3, 2.6, 3.3, 3.6_

  - [ ]* 4.3 Write example tests for DELETE response decoding
    - Use `XCTest` with a `URLProtocol` stub to feed sample response bodies (success, `figure_errors` populated, `watcher_error` populated, 404 error).
    - Assert `DeletionResult` decodes each shape correctly and non-2xx responses throw an error whose message includes the returned body.
    - _Requirements: 2.6, 3.6, 7.2, 8.3_

- [x] 5. Swift `IndexCoordinator` orchestration (`ISOStandardsKB/Services/IndexCoordinator.swift`)
  - [x] 5.1 Add `deleteFolder`, `deleteDocument`, and `rescanFolder`
    - Implement `func deleteFolder(_ library: Library, alsoTrash: Bool) async -> Result<BackendClient.DeletionResult, Error>`: `await backend.deleteLibrary(id:)`, then only if it succeeded and `alsoTrash == true`, call `FileManager.default.trashItem(at: URL(fileURLWithPath: library.path), resultingItemURL: nil)`. If the backend call throws, return `.failure(error)` without touching the filesystem.
    - Implement `func deleteDocument(_ doc: ISODocument, alsoTrash: Bool) async -> Result<BackendClient.DeletionResult, Error>` mirroring the above using `backend.deleteDocument(id:)` and `doc.filePath`.
    - Implement `func rescanFolder(_ library: Library) async -> Result<[String: Any], Error>`: toggle `isIndexing`, call the existing `backend.ingest(path: library.path, name: library.name)`, populate `lastMessage` with `"Rescan: {indexed} new, {skipped} skipped"` on success or `"Rescan failed: ..."` on error, and return the raw stats dict.
    - Ordering is load-bearing: the trash call MUST be inside the `do` block strictly after the successful `await backend.deleteX(...)` return.
    - See design section "IndexCoordinator".
    - _Requirements: 2.3, 2.5, 2.6, 3.3, 3.5, 3.6, 4.2, 4.5_

  - [ ]* 5.2 Write property test for backend-precedes-trash ordering
    - **Property 2: Backend precedes on-disk deletion**
    - **Validates: Requirements 2.3, 3.3**
    - Introduce a `BackendClientProtocol` seam covering `deleteLibrary`/`deleteDocument` and inject a spy that records event timestamps.
    - Substitute an injectable `TrashService` protocol for `FileManager.default.trashItem` and record its call timestamp.
    - For every generated combination of success/failure and `alsoTrash`, assert that whenever the trash service was invoked, the corresponding backend DELETE completion event strictly precedes it.
    - Tag: `Feature: library-folder-crud, Property 2`.

  - [ ]* 5.3 Write property test for the trash opt-in gate
    - **Property 3: Trash opt-in gate**
    - **Validates: Requirements 2.5, 2.6, 3.5, 3.6, 5.4**
    - Using the same spy setup from 5.2, generate `alsoTrash` values and backend response statuses (2xx and non-2xx).
    - Assert `TrashService.trashItem` is invoked iff (`alsoTrash == true` AND backend returned a 2xx result). Assert zero trash calls for `alsoTrash == false` regardless of backend outcome, and zero trash calls when the backend throws.
    - Tag: `Feature: library-folder-crud, Property 3`.

  - [ ]* 5.4 Write property test for error-path state preservation
    - **Property 6: Error paths preserve UI and disk state**
    - **Validates: Requirements 2.6, 3.6, 4.5**
    - Drive `deleteFolder`, `deleteDocument`, and `rescanFolder` with an injected `BackendClient` spy returning generated non-2xx errors.
    - Assert `TrashService.trashItem` is never called, the returned `.failure` carries the backend body as its message, and for `rescanFolder` the coordinator surfaces the error without emitting a follow-up `listDocuments` call.
    - Tag: `Feature: library-folder-crud, Property 6`.

- [~] 6. Swift UI subcomponents (new files under `ISOStandardsKB/Views/`)
  - [x] 6.1 Create `DeleteConfirmationSheet.swift`
    - Add `struct DeleteConfirmationSheet: View` with `let targetName: String`, `let targetPath: String`, `let onConfirm: (_ alsoMoveToTrash: Bool) -> Void`, and `@State private var alsoMoveToTrash: Bool = false`.
    - Render the title (`"Delete \(targetName)?"`), a caption showing `targetPath` with `.textSelection(.enabled)`, a `Toggle("Also move files to Trash", isOn: $alsoMoveToTrash)`, a Cancel button that calls `dismiss()`, and a destructive Delete button that calls `onConfirm(alsoMoveToTrash)` then `dismiss()`.
    - Do not pre-populate the toggle from any persisted state; it must be `false` every time the sheet appears.
    - See design section "DeleteConfirmationSheet".
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 2.1, 3.1_

  - [x] 6.2 Create `OfflineBanner.swift`
    - Add `struct OfflineBanner: View` rendering a `.top` overlay message stating that the backend is not running and destructive actions are disabled.
    - Style the banner as a filled capsule/rectangle with contrasting foreground so it is unmistakable when `LibraryView` overlays it.
    - _Requirements: 6.4_

  - [x] 6.3 Create `FoldersPane.swift`
    - Add `struct FoldersPane: View` with `@Binding var libraries: [Library]`, `@Binding var selection: Library?`, `let isOnline: Bool`, `let onDelete: (Library) -> Void`, `let onRescan: (Library) -> Void`.
    - Render a `List(libraries, selection: $selection)` where each row exposes Delete and Rescan actions (context menu + row buttons); both actions are `.disabled(!isOnline)`.
    - _Requirements: 1.1, 1.2, 2.1, 4.1, 6.1, 6.3_

  - [x] 6.4 Create `DocumentsPane.swift`
    - Add `struct DocumentsPane: View` with `@Binding var documents: [ISODocument]`, `@Binding var selection: ISODocument?`, `let isOnline: Bool`, `let folderSelected: Bool`, `let onDelete: (ISODocument) -> Void`.
    - Render the existing document list layout (`displayTitle`, `standardId`, `StatusBadge`) bound to `documents`, with a per-row Delete action `.disabled(!isOnline)`.
    - When `folderSelected == false`, render a `ContentUnavailableView("No Folder Selected", ...)` stating no folder is selected.
    - _Requirements: 1.1, 1.3, 1.5, 3.1, 6.1, 6.3_

  - [x] 6.5 Create `DetailPane.swift`
    - Add `struct DetailPane: View` that renders `DocumentDetailView` when `document != nil` and otherwise renders `ContentUnavailableView("No Document Selected", ...)` stating no document is selected.
    - Expose `let document: ISODocument?`, `let clauses: [Clause]`, `let figures: [Figure]` so `LibraryView` can pass fetched data.
    - _Requirements: 1.1, 1.4, 1.6_

- [x] 7. Swift `LibraryView` restructure (`ISOStandardsKB/Views/LibraryView.swift`)
  - [x] 7.1 Restructure `LibraryView` into a three-pane workspace and wire delete/rescan flows
    - Replace the current body with an `HSplitView` containing `FoldersPane`, `DocumentsPane`, and `DetailPane` in left-to-right order.
    - Add `@State` for `libraries`, `selectedLibrary`, `documents`, `selectedDocument`, `clauses`, `figures`, `pendingLibraryDeletion`, `pendingDocumentDeletion`, and `errorMessage`, wired to the panes' bindings and closures per the design.
    - On `.task {}` and on `backend.isConnected` transitioning to `true`, call `backend.listLibraries()` and populate `libraries`; on `selectedLibrary` change, call `backend.listDocuments(libraryId:)` and clear `selectedDocument`; on `selectedDocument` change, fetch clauses and figures.
    - Present `DeleteConfirmationSheet` via `.sheet(item: $pendingLibraryDeletion)` and `.sheet(item: $pendingDocumentDeletion)`, invoking `indexCoordinator.deleteFolder(_:alsoTrash:)` or `indexCoordinator.deleteDocument(_:alsoTrash:)` on confirm. After success, remove the target from local state and clear the corresponding selection.
    - Wire the Rescan closure to `indexCoordinator.rescanFolder(_:)` and, on success, re-issue `backend.listDocuments(libraryId:)` for the rescanned folder. On failure, populate `errorMessage` without mutating `documents`.
    - Overlay `OfflineBanner` at `.top` when `backend.isConnected == false`. When offline, source `libraries`, `documents`, `clauses`, and `figures` from `DatabaseService` reads instead of the backend.
    - Surface `errorMessage` (backend body or `error.localizedDescription`) for any DELETE or ingest failure. Do not call `FileManager.trashItem` on any failure path (delegated to `IndexCoordinator`).
    - See design sections "LibraryView", "FoldersPane", "DocumentsPane", "DetailPane", "Error Handling / Client".
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 2.1, 2.2, 2.5, 2.6, 2.7, 3.1, 3.2, 3.5, 3.6, 3.7, 4.2, 4.4, 4.5, 4.6, 5.1, 6.1, 6.2, 6.3, 6.4, 7.1_

  - [ ]* 7.2 Write property test for confirmation checkbox default
    - **Property 4: Confirmation checkbox defaults to unchecked**
    - **Validates: Requirement 5.2**
    - Instantiate `DeleteConfirmationSheet` under `XCTest` (via `ViewInspector` or direct mirror of its `@State`), generate arbitrary `targetName`/`targetPath` pairs, and assert `alsoMoveToTrash == false` at first render for every generated case.
    - Tag: `Feature: library-folder-crud, Property 4`.

  - [ ]* 7.3 Write property test for cancellation no-op
    - **Property 5: Cancellation is a no-op**
    - **Validates: Requirements 2.2, 3.2**
    - Snapshot `libraries`, `documents`, dependent rows, `figures_dir` files, and target on-disk state via a fake `DatabaseService` + `FileManager` before presenting the sheet.
    - For every generated confirmation-then-cancel or immediate-cancel scenario, assert the post-cancel snapshots are byte-identical and no `BackendClient` or `TrashService` methods were invoked.
    - Tag: `Feature: library-folder-crud, Property 5`.

  - [ ]* 7.4 Write property test for rescan refresh
    - **Property 8: Rescan success refreshes DocumentsPane**
    - **Validates: Requirement 4.4**
    - Inject a spy `BackendClient` returning arbitrary ingest results, drive the `LibraryView` rescan flow for a selected folder, and assert `backend.listDocuments(libraryId:)` was called exactly once with the rescanned folder's id and that `documents` was replaced with the returned body.
    - Tag: `Feature: library-folder-crud, Property 8`.

  - [ ]* 7.5 Write property test for offline gating
    - **Property 12: Offline gates mutating actions**
    - **Validates: Requirements 6.1, 6.3**
    - Toggle `BackendClient.isConnected` across a generated sequence of transitions and assert every folder-delete, document-delete, and folder-rescan control's `isEnabled` equals the current `isConnected` value at all times.
    - Tag: `Feature: library-folder-crud, Property 12`.

  - [ ]* 7.6 Write property test for offline read fallback
    - **Property 13: Offline reads fall through to local cache**
    - **Validates: Requirement 6.2**
    - With `BackendClient.isConnected == false` and a spy backend that records every network call, drive `LibraryView` through folder/document selection and detail loading using a fake `DatabaseService` seeded with generated rows.
    - Assert `libraries`, `documents`, `clauses`, and `figures` displayed match the `DatabaseService` contents and the spy backend received zero calls.
    - Tag: `Feature: library-folder-crud, Property 13`.

  - [ ]* 7.7 Write property test for folder-selection fetch
    - **Property 14: Folder selection triggers document fetch**
    - **Validates: Requirement 1.3**
    - With `BackendClient.isConnected == true` and a spy backend, generate sequences of folder selections and assert that each selection change issues exactly one `GET /documents?library_id={selected.id}` call, replaces `documents` with the response body, and clears `selectedDocument`.
    - Tag: `Feature: library-folder-crud, Property 14`.

  - [ ]* 7.8 Write property test for document-selection detail load
    - **Property 15: Document selection triggers detail load**
    - **Validates: Requirement 1.4**
    - With a spy backend, generate document selections and assert `GET /documents/{id}/clauses` and `GET /documents/{id}/figures` are each issued exactly once per selection and that `DetailPane` renders `DocumentDetailView` bound to the resulting `clauses` and `figures`.
    - Tag: `Feature: library-folder-crud, Property 15`.

  - [ ]* 7.9 Write property test for confirmation dialog target identity
    - **Property 16: Confirmation dialog surfaces target identity**
    - **Validates: Requirements 2.1, 3.1**
    - Generate arbitrary `Library` and `ISODocument` values, invoke the delete action, and assert the presented `DeleteConfirmationSheet`'s visible text contains both the target's user-facing name and its filesystem path.
    - Tag: `Feature: library-folder-crud, Property 16`.

  - [ ]* 7.10 Write example tests for structural UI criteria
    - Assert `LibraryView.body` contains exactly one `HSplitView` with three panes in `FoldersPane`, `DocumentsPane`, `DetailPane` order (1.1).
    - Assert `DocumentsPane` renders "No Folder Selected" when `folderSelected == false` (1.5) and `DetailPane` renders "No Document Selected" when `document == nil` (1.6).
    - Assert `LibraryView.task` issues `GET /libraries` on appear (1.2) and `FoldersPane` exposes a Rescan control on every row (4.1) without any per-file picker in the rescan flow (4.6).
    - Assert `DeleteConfirmationSheet` contains the Cancel button, Delete button, target description with path, and the single "Also move files to Trash" toggle (5.1) which can be toggled by the user before confirming (5.3).
    - Assert `OfflineBanner` text explicitly states the backend is not running (6.4).
    - _Requirements: 1.1, 1.2, 1.5, 1.6, 4.1, 4.6, 5.1, 5.3, 6.4_

- [~] 8. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP; all property tests are optional per the workflow conventions.
- Each task references specific requirement sub-clauses so downstream reviewers can trace coverage back to the requirements document.
- Property tests are placed directly under the implementation they cover so failures surface as close to the code change as possible.
- The `IndexCoordinator` seam introduced in tasks 5.2-5.4 (`BackendClientProtocol`, `TrashService`) is also reused by the LibraryView property tests in tasks 7.2-7.9.
- No schema changes are required; existing cascading foreign keys and the `chunks_ad` FTS trigger handle referential integrity.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "2.1", "4.1", "6.1", "6.2", "6.3", "6.4", "6.5"] },
    { "id": 1, "tasks": ["1.2", "2.2", "4.2"] },
    { "id": 2, "tasks": ["2.3", "2.4", "2.5", "2.6", "4.3", "5.1"] },
    { "id": 3, "tasks": ["5.2", "5.3", "5.4", "7.1"] },
    { "id": 4, "tasks": ["7.2", "7.3", "7.4", "7.5", "7.6", "7.7", "7.8", "7.9", "7.10"] }
  ]
}
```
