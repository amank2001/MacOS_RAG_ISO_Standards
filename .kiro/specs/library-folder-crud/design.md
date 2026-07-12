# Design Document

## Overview

The Library Folder CRUD feature spans two processes:

- The **macOS SwiftUI client** (`ISOStandardsKB/Views/LibraryView.swift` and neighbours), which owns the three-pane workspace UI, confirmation dialogs, offline gating, and the optional `FileManager.trashItem` step.
- The **FastAPI backend** (`indexer/api.py`, `indexer/database.py`), which owns index mutation, watcher lifecycle, and figure-image cleanup on disk.

The client and backend communicate over HTTP against `AppConfig.apiBaseURL`. All index mutations are backend-side; the client's on-disk deletion is limited to the user-facing "Also move files to Trash" opt-in.

The database schema already declares `ON DELETE CASCADE` for `documents`, `clauses`, `chunks`, `chunk_embeddings`, and `figures`, so backend deletion only removes the top-level row and manually cleans figure image files (which live outside SQLite under `figures_dir`).

## Architecture

```
+-----------------------------------+          HTTP           +--------------------------------+
|          LibraryView (Swift)      |  -----------------> /libraries, /documents,
|                                   |                       /ingest, /watch/*,
|  HSplitView                       |                       DELETE /libraries/{id},
|   +-- FoldersPane                 |                       DELETE /documents/{id}
|   +-- DocumentsPane               |                                         (FastAPI)
|   +-- DocumentDetailView          |  <-----------------                              |
|                                   |                                                  |
|  DeleteConfirmationSheet          |                                                  v
|                                   |                                    +-----------------------+
|  BackendClient        IndexCoord. |                                    |  api.py               |
|      isConnected      rescanFolder|                                    |    watchers: dict     |
|      deleteLibrary    deleteFolder|                                    |    DELETE handlers    |
|      deleteDocument   deleteDoc   |                                    +-----------+-----------+
+-----------------------------------+                                                |
             |                                                                       v
             | (opt-in, after 2xx)                                    +-----------------------+
             v                                                        |  database.py          |
   FileManager.trashItem(url)                                         |    delete_library()   |
                                                                      |    delete_document()  |
                                                                      |    figure_paths_for_* |
                                                                      +-----------+-----------+
                                                                                  |
                                                                                  v
                                                             SQLite (cascade) + figures_dir cleanup
```

The client is the source of truth for user intent; the backend is the source of truth for the index and for on-disk figure images. Only files that the user explicitly opts to trash cross that boundary from the client side.

## Components

### LibraryView (SwiftUI)

Restructured to three panes inside a single `HSplitView`:

```swift
struct LibraryView: View {
    @EnvironmentObject var backend: BackendClient
    @EnvironmentObject var indexCoordinator: IndexCoordinator

    @State private var libraries: [Library] = []
    @State private var selectedLibrary: Library?

    @State private var documents: [ISODocument] = []
    @State private var selectedDocument: ISODocument?

    @State private var clauses: [Clause] = []
    @State private var figures: [Figure] = []

    @State private var pendingLibraryDeletion: Library?
    @State private var pendingDocumentDeletion: ISODocument?

    @State private var errorMessage: String?

    var body: some View {
        HSplitView {
            FoldersPane(
                libraries: $libraries,
                selection: $selectedLibrary,
                isOnline: backend.isConnected,
                onDelete: { pendingLibraryDeletion = $0 },
                onRescan: { library in
                    Task { await rescan(library) }
                }
            )
            .frame(minWidth: 220)

            DocumentsPane(
                documents: $documents,
                selection: $selectedDocument,
                isOnline: backend.isConnected,
                folderSelected: selectedLibrary != nil,
                onDelete: { pendingDocumentDeletion = $0 }
            )
            .frame(minWidth: 260)

            DetailPane(
                document: selectedDocument,
                clauses: clauses,
                figures: figures
            )
        }
        .sheet(item: $pendingLibraryDeletion) { library in
            DeleteConfirmationSheet(
                targetName: library.name,
                targetPath: library.path,
                onConfirm: { alsoTrash in Task { await deleteLibrary(library, alsoTrash: alsoTrash) } }
            )
        }
        .sheet(item: $pendingDocumentDeletion) { doc in
            DeleteConfirmationSheet(
                targetName: doc.displayTitle,
                targetPath: doc.filePath,
                onConfirm: { alsoTrash in Task { await deleteDocument(doc, alsoTrash: alsoTrash) } }
            )
        }
        .overlay(alignment: .top) {
            if !backend.isConnected {
                OfflineBanner()
            }
        }
        // task/onChange as today, plus GET /libraries and per-folder GET /documents
    }
}
```

Key responsibilities:

- Owns the SwiftUI state listed above.
- Loads libraries on `.task {}` via `backend.listLibraries()`.
- On `selectedLibrary` change, calls `backend.listDocuments(libraryId:)` and repopulates `documents`, clearing `selectedDocument`.
- On `selectedDocument` change, fetches clauses and figures.
- Presents `DeleteConfirmationSheet` for pending deletions.
- Calls into `IndexCoordinator` for delete and rescan flows.

### FoldersPane

`List(libraries, selection: $selection)` with a context menu / trailing swipe / row-level buttons for **Delete** and **Rescan**. Both buttons are `.disabled(!isOnline)`.

### DocumentsPane

Preserves the existing document list layout (`displayTitle`, `standardId`, `StatusBadge`) but binds to `documents: [ISODocument]` for the currently selected folder. Includes a per-row **Delete** action, `.disabled(!isOnline)`. When `folderSelected == false`, renders `ContentUnavailableView("No Folder Selected", ...)`.

### DetailPane

Renders the existing `DocumentDetailView` when `selectedDocument != nil`, otherwise a `ContentUnavailableView("No Document Selected", ...)` message. This is a thin wrapper around today's `DocumentDetailView`.

### DeleteConfirmationSheet

New reusable SwiftUI view:

```swift
struct DeleteConfirmationSheet: View {
    let targetName: String
    let targetPath: String
    let onConfirm: (_ alsoMoveToTrash: Bool) -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var alsoMoveToTrash: Bool = false   // default per Requirement 5.2

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("Delete \(targetName)?")
                .font(.headline)
            Text(targetPath)
                .font(.caption)
                .foregroundStyle(.secondary)
                .textSelection(.enabled)
            Toggle("Also move files to Trash", isOn: $alsoMoveToTrash)
            HStack {
                Spacer()
                Button("Cancel", role: .cancel) { dismiss() }
                Button("Delete", role: .destructive) {
                    onConfirm(alsoMoveToTrash)
                    dismiss()
                }
                .keyboardShortcut(.defaultAction)
            }
        }
        .padding(20)
        .frame(minWidth: 420)
    }
}
```

The sheet is used for both library and document deletions. `alsoMoveToTrash` is always initialized to `false`.

### BackendClient

Adds two new endpoints and a shared `delete` HTTP helper:

```swift
extension BackendClient {
    struct DeletionResult: Decodable {
        let status: String              // "ok"
        let removed: Int?               // rows removed
        let figureErrors: [FigureError] // best-effort image cleanup failures
        let watcherError: String?       // for library delete only
    }

    struct FigureError: Decodable, Hashable {
        let imagePath: String
        let error: String
        enum CodingKeys: String, CodingKey {
            case imagePath = "image_path"
            case error
        }
    }

    func deleteLibrary(id: Int) async throws -> DeletionResult {
        try await delete("/libraries/\(id)")
    }

    func deleteDocument(id: Int) async throws -> DeletionResult {
        try await delete("/documents/\(id)")
    }

    private func delete<T: Decodable>(_ path: String) async throws -> T {
        let url = AppConfig.apiBaseURL.appendingPathComponent(
            path.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        )
        var request = URLRequest(url: url)
        request.httpMethod = "DELETE"
        let (data, response) = try await session.data(for: request)
        try validate(response: response, data: data)
        return try decoder.decode(T.self, from: data)
    }
}
```

`listDocuments(libraryId:)` already exists and is reused verbatim.

### IndexCoordinator

Adds folder-deletion, document-deletion, and rescan orchestration. It is the single place that (a) calls the backend, (b) invokes `FileManager.trashItem` when opted in, and (c) surfaces errors:

```swift
extension IndexCoordinator {
    func deleteFolder(_ library: Library, alsoTrash: Bool) async -> Result<BackendClient.DeletionResult, Error> {
        do {
            let result = try await backend.deleteLibrary(id: library.id)
            if alsoTrash {
                try FileManager.default.trashItem(
                    at: URL(fileURLWithPath: library.path),
                    resultingItemURL: nil
                )
            }
            return .success(result)
        } catch {
            return .failure(error)
        }
    }

    func deleteDocument(_ doc: ISODocument, alsoTrash: Bool) async -> Result<BackendClient.DeletionResult, Error> {
        do {
            let result = try await backend.deleteDocument(id: doc.id)
            if alsoTrash {
                try FileManager.default.trashItem(
                    at: URL(fileURLWithPath: doc.filePath),
                    resultingItemURL: nil
                )
            }
            return .success(result)
        } catch {
            return .failure(error)
        }
    }

    func rescanFolder(_ library: Library) async -> Result<[String: Any], Error> {
        isIndexing = true
        defer { isIndexing = false }
        do {
            let stats = try await backend.ingest(path: library.path, name: library.name)
            let indexed = stats["indexed"] as? Int ?? 0
            let skipped = stats["skipped"] as? Int ?? 0
            lastMessage = "Rescan: \(indexed) new, \(skipped) skipped"
            return .success(stats)
        } catch {
            lastMessage = "Rescan failed: \(error.localizedDescription)"
            return .failure(error)
        }
    }
}
```

The ordering above is load-bearing: the trash call is inside the `do` block **after** `await backend.deleteX(...)` returns. If the DELETE throws, control jumps to `catch` and `trashItem` is never invoked, satisfying the ordering requirements (2.3, 2.6, 3.3, 3.6).

### Backend: `indexer/api.py`

Refactor the existing in-scope `watchers` dict so both `/watch/stop` and `DELETE /libraries/{id}` can stop watchers through the same helper:

```python
def create_app(db_path: Path, figures_dir: Path) -> FastAPI:
    app = FastAPI(...)
    watchers: dict[str, LibraryWatcher] = {}

    def _stop_watcher(path: str) -> str | None:
        """Stop and drop the watcher for `path`. Return an error message or None."""
        resolved = str(Path(path).resolve())
        watcher = watchers.pop(resolved, None)
        if watcher is None:
            return None
        try:
            watcher.stop()
            return None
        except Exception as exc:  # noqa: BLE001
            return f"watcher stop failed: {exc!s}"

    def _delete_figure_files(paths: list[str]) -> list[dict[str, str]]:
        """Best-effort removal. Missing files are ok. Return list of {image_path, error}."""
        errors: list[dict[str, str]] = []
        for p in paths:
            try:
                Path(p).unlink(missing_ok=True)   # missing -> no-op, no error
            except OSError as exc:
                errors.append({"image_path": p, "error": str(exc)})
        return errors

    @app.delete("/libraries/{library_id}")
    def delete_library(library_id: int) -> dict[str, Any]:
        db = get_db()
        try:
            lib = db.get_library(library_id)
            if lib is None:
                raise HTTPException(404, f"Library {library_id} not found")

            watcher_error = _stop_watcher(lib["path"])
            figure_paths = db.figure_paths_for_library(library_id)
            figure_errors = _delete_figure_files(figure_paths)
            removed = db.delete_library(library_id)

            return {
                "status": "ok",
                "removed": removed,
                "figure_errors": figure_errors,
                "watcher_error": watcher_error,
            }
        finally:
            db.close()

    @app.delete("/documents/{document_id}")
    def delete_document(document_id: int) -> dict[str, Any]:
        db = get_db()
        try:
            doc = db.get_document(document_id)
            if doc is None:
                raise HTTPException(404, f"Document {document_id} not found")

            figure_paths = db.figure_paths_for_document(document_id)
            figure_errors = _delete_figure_files(figure_paths)
            removed = db.delete_document(document_id)

            return {
                "status": "ok",
                "removed": removed,
                "figure_errors": figure_errors,
                "watcher_error": None,
            }
        finally:
            db.close()
```

`_stop_watcher` intentionally swallows exceptions and returns them as a message, so figure cleanup and row deletion always run (satisfies 7.2). `_delete_figure_files` uses `Path.unlink(missing_ok=True)` for the missing-file case (8.2) and collects `OSError` per-path errors (8.3). The `POST /watch/stop` handler is refactored to call `_stop_watcher` too.

### Backend: `indexer/database.py`

Adds three methods:

```python
def get_library(self, library_id: int) -> dict[str, Any] | None:
    row = self.conn.execute(
        "SELECT * FROM libraries WHERE id = ?", (library_id,)
    ).fetchone()
    return dict(row) if row else None

def get_document(self, document_id: int) -> dict[str, Any] | None:
    row = self.conn.execute(
        "SELECT * FROM documents WHERE id = ?", (document_id,)
    ).fetchone()
    return dict(row) if row else None

def figure_paths_for_document(self, document_id: int) -> list[str]:
    rows = self.conn.execute(
        "SELECT image_path FROM figures WHERE document_id = ?",
        (document_id,),
    ).fetchall()
    return [r["image_path"] for r in rows]

def figure_paths_for_library(self, library_id: int) -> list[str]:
    rows = self.conn.execute(
        """SELECT f.image_path FROM figures f
           JOIN documents d ON d.id = f.document_id
           WHERE d.library_id = ?""",
        (library_id,),
    ).fetchall()
    return [r["image_path"] for r in rows]

def delete_library(self, library_id: int) -> int:
    cur = self.conn.execute(
        "DELETE FROM libraries WHERE id = ?", (library_id,)
    )
    self.conn.commit()
    return cur.rowcount

def delete_document(self, document_id: int) -> int:
    cur = self.conn.execute(
        "DELETE FROM documents WHERE id = ?", (document_id,)
    )
    self.conn.commit()
    return cur.rowcount
```

Because the SQLite connection is opened with `PRAGMA foreign_keys = ON` and the schema declares cascading foreign keys, deleting the `libraries` or `documents` row is sufficient to remove all dependent `documents`, `clauses`, `chunks`, `chunk_embeddings`, and `figures` rows. FTS rows are removed via the existing `chunks_ad` trigger when chunk rows cascade.

### Rescan (POST /ingest)

No backend changes required. `IngestionPipeline.ingest_library` already computes each file's SHA-256 via `db.file_hash(path)` and compares against `documents.file_hash`; matches are skipped via the existing `if existing["file_hash"] == file_hash and existing["status"] == "indexed": return existing["id"]` short-circuit in `upsert_document`. The pipeline's return dict includes counts we surface to the client. Rescan reuses `POST /ingest` with the folder's stored `path`; the client does not need a file picker.

## Interfaces

### HTTP

| Method | Path | Body | Response |
|--------|------|------|----------|
| GET    | `/libraries` | — | `[Library]` |
| GET    | `/documents?library_id={id}` | — | `[Document]` |
| POST   | `/ingest` | `{path, name?, no_embed}` | `{indexed, skipped, errors, ...}` |
| POST   | `/watch/stop` | `{path}` | `{status, path}` |
| **DELETE** | **`/libraries/{id}`** | — | `{status: "ok", removed: int, figure_errors: [...], watcher_error: str \| null}` |
| **DELETE** | **`/documents/{id}`** | — | `{status: "ok", removed: int, figure_errors: [...], watcher_error: null}` |

Both DELETE responses return HTTP 200 on success. `figure_errors` and `watcher_error` are surfaced regardless of success so the client can log per-figure failures without blocking (7.2, 8.3).

### Swift API surface added

```swift
BackendClient.deleteLibrary(id: Int) async throws -> DeletionResult
BackendClient.deleteDocument(id: Int) async throws -> DeletionResult
IndexCoordinator.deleteFolder(_ library: Library, alsoTrash: Bool) async -> Result<DeletionResult, Error>
IndexCoordinator.deleteDocument(_ doc: ISODocument, alsoTrash: Bool) async -> Result<DeletionResult, Error>
IndexCoordinator.rescanFolder(_ library: Library) async -> Result<[String: Any], Error>
```

## Data Models

No schema changes. Cascade behaviour is already correct:

- `documents.library_id REFERENCES libraries(id) ON DELETE CASCADE`
- `clauses.document_id REFERENCES documents(id) ON DELETE CASCADE`
- `chunks.document_id REFERENCES documents(id) ON DELETE CASCADE`
- `chunks.clause_id REFERENCES clauses(id) ON DELETE SET NULL`
- `figures.document_id REFERENCES documents(id) ON DELETE CASCADE`
- `chunk_embeddings.chunk_id REFERENCES chunks(id) ON DELETE CASCADE`

The `chunks_ad` FTS trigger removes matching FTS rows when a chunk is deleted, so the FTS index stays in sync automatically.

Swift-side `Library` and `ISODocument` in `Models/Models.swift` are unchanged. A new small `DeletionResult` and `FigureError` value type live on `BackendClient`.

## Error Handling

### Client

- Every backend call is wrapped in `do/try/catch`. On failure, the coordinator populates `LibraryView.errorMessage` with the returned body (or `error.localizedDescription`). Requirement 2.6/3.6/4.5.
- `FileManager.trashItem` is only invoked **after** a successful `await backend.deleteX(...)` return. If the backend call throws, control jumps to `catch` and no on-disk mutation occurs.
- If `FileManager.trashItem` itself throws (e.g. sandbox denial), the index change has already been committed by the backend; the error is surfaced in `errorMessage` without attempting rollback (out of scope per the requirements).
- All delete/rescan buttons are `.disabled(!backend.isConnected)`. An `OfflineBanner` is rendered on top of `LibraryView` when disconnected (6.1, 6.2, 6.3). Attempts to trigger a disabled action are impossible at the SwiftUI level; the offline banner covers 6.4.
- When a `.sheet` is dismissed via Cancel, no coordinator call is made and no state is mutated (2.2, 3.2).

### Backend

- 404 for unknown ids (return `HTTPException(404, ...)`).
- Figure removal is best-effort per file: missing files are treated as clean (`unlink(missing_ok=True)`) and OS errors are collected into `figure_errors`. The overall status remains 200 (8.1, 8.2, 8.3).
- Watcher stop failures are captured into `watcher_error` and do not abort figure cleanup or row deletion. Status remains 200 (7.2).
- Row deletion is a single `DELETE` inside SQLite's implicit transaction; failures raise and become HTTP 500 (fatal, dedicated error path).

## Correctness Pre-work

See the acceptance criteria testing prework recorded via the `prework` tool for the full step-by-step analysis and the property reflection that consolidated overlapping properties into the set below.

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system, essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Cascade deletion preserves referential integrity

For any successful `DELETE /libraries/{id}` (respectively `DELETE /documents/{id}`), after the call returns 200 there SHALL be no row in `libraries`, `documents`, `clauses`, `chunks`, `chunk_embeddings`, `figures`, or `chunks_fts` that references the deleted entity by id or by any cascaded ancestor id.

**Validates: Requirements 2.4, 2.7, 3.4, 3.7**

### Property 2: Backend precedes on-disk deletion

For any confirmed deletion invoked from `LibraryView`, if `FileManager.trashItem` is called then the corresponding `DELETE /libraries/{id}` or `DELETE /documents/{id}` response with status 2xx has already been received. Equivalently, in every execution trace the DELETE completion event precedes any `trashItem` event for the same target.

**Validates: Requirements 2.3, 3.3**

### Property 3: Trash opt-in gate

For any confirmed deletion, `FileManager.trashItem` is invoked on the target's filesystem path if and only if the "Also move files to Trash" checkbox was checked at confirm time **and** the backend DELETE returned a 2xx status. In particular, no `trashItem` call is made when the checkbox is unchecked, and no `trashItem` call is made when the backend returns a non-2xx response.

**Validates: Requirements 2.5, 2.6, 3.5, 3.6, 5.4**

### Property 4: Confirmation checkbox defaults to unchecked

For any presentation of `DeleteConfirmationSheet`, at the moment the sheet becomes visible the `alsoMoveToTrash` state is `false`.

**Validates: Requirement 5.2**

### Property 5: Cancellation is a no-op

For any presentation of `DeleteConfirmationSheet` that is dismissed via Cancel, the sets of `libraries` rows, `documents` rows, dependent rows in `clauses`/`chunks`/`chunk_embeddings`/`figures`, and files under `figures_dir` and under the target's filesystem path are byte-identical to their pre-presentation state.

**Validates: Requirements 2.2, 3.2**

### Property 6: Error paths preserve UI and disk state

For any DELETE request that returns a non-2xx status, or any rescan `POST /ingest` that returns a non-2xx status, `FileManager.trashItem` SHALL NOT be invoked, `LibraryView.errorMessage` SHALL be set to the returned body, and (for rescan) `documents` in the current `DocumentsPane` SHALL equal its pre-request value.

**Validates: Requirements 2.6, 3.6, 4.5**

### Property 7: Rescan is idempotent over unchanged files

For any Library_Folder previously indexed with a set of files whose SHA-256 hashes match existing `documents.file_hash` values for that library, re-invoking `POST /ingest` on the same folder SHALL produce zero new `documents` rows for those files, SHALL leave their existing rows' `id` and `file_hash` unchanged, and SHALL report every such file in the response's skipped count.

**Validates: Requirement 4.3**

### Property 8: Rescan success refreshes DocumentsPane

For any successful rescan of a Library_Folder, `LibraryView` SHALL subsequently issue `GET /documents?library_id={id}` for that folder and set `documents` to the response body.

**Validates: Requirement 4.4**

### Property 9: Watcher is stopped before folder deletion returns

For any Library_Folder whose resolved path is present in the in-process `watchers` dict at the moment `DELETE /libraries/{id}` is received, the watcher's `stop()` SHALL be invoked and the entry SHALL be removed from `watchers` before the endpoint returns any response.

**Validates: Requirement 7.1**

### Property 10: Watcher-stop failures do not abort deletion

For any `DELETE /libraries/{id}` where the associated watcher's `stop()` raises, the endpoint SHALL still (a) attempt figure image cleanup for every document under the library, (b) delete the `libraries` row, and (c) return a 2xx status whose response body's `watcher_error` field contains the raised error's message.

**Validates: Requirement 7.2**

### Property 11: Figure image cleanup is best-effort and total

For any `DELETE /documents/{id}` (invoked directly or reached via cascade from `DELETE /libraries/{id}`), the backend SHALL attempt filesystem removal of every `image_path` recorded in the `figures` rows associated with the target document(s). Missing files SHALL be treated as successfully cleaned. Filesystem errors SHALL be recorded per-path in the response body's `figure_errors` field. The overall response status SHALL be 2xx.

**Validates: Requirements 8.1, 8.2, 8.3**

### Property 12: Offline gates mutating actions

For any `LibraryView` state, the enabled state of every folder-delete button, document-delete button, and folder-rescan button SHALL equal `BackendClient.isConnected`. Transitions of `isConnected` SHALL propagate to control enablement without additional user action.

**Validates: Requirements 6.1, 6.3**

### Property 13: Offline reads fall through to local cache

For any `LibraryView` state where `BackendClient.isConnected == false`, the `libraries`, `documents`, `clauses`, and `figures` displayed SHALL be sourced from `DatabaseService` (the local SQLite cache) and no HTTP requests SHALL be issued to the backend.

**Validates: Requirement 6.2**

### Property 14: Folder selection triggers document fetch

For any user selection of a Library_Folder while `BackendClient.isConnected == true`, `LibraryView` SHALL issue `GET /documents?library_id={selected.id}` exactly once and set `documents` to the response body; `selectedDocument` SHALL be cleared as part of the selection change.

**Validates: Requirement 1.3**

### Property 15: Document selection triggers detail load

For any user selection of a Document while `BackendClient.isConnected == true`, `LibraryView` SHALL issue `GET /documents/{selected.id}/clauses` and `GET /documents/{selected.id}/figures` and render `DocumentDetailView` populated with the responses.

**Validates: Requirement 1.4**

### Property 16: Confirmation dialog surfaces target identity

For any invocation of the delete action on a Library_Folder or Document, the presented `DeleteConfirmationSheet`'s visible text SHALL contain the target's user-facing name and its filesystem path.

**Validates: Requirements 2.1, 3.1**

## Testing Strategy

- **Property tests** cover the sixteen properties above. Each property test uses at least 100 iterations of generated inputs (arbitrary library sets, document sets, figure files on disk, checkbox states, connectivity states). Backend property tests mock the filesystem where useful. Client property tests mock `BackendClient` via a protocol seam so the ordering property (Property 2) can observe call sequences.
- **Example / unit tests** cover the fixed-shape UI structural criteria: three-pane layout (1.1), empty states (1.5, 1.6), Rescan action presence (4.1), no per-file picker (4.6), dialog element inventory (5.1), checkbox toggle (5.3), offline banner text (6.4), and libraries load on appear (1.2).
- Each property test is tagged **`Feature: library-folder-crud, Property {n}: {property_text}`** and cross-references the requirements it validates.
