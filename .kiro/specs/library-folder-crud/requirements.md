# Requirements Document

## Introduction

The Library Folder CRUD feature extends the existing macOS SwiftUI `LibraryView` into a three-pane workspace that lets users manage indexed folders (libraries) and their documents. Users can browse folders, browse the documents inside a selected folder, view document details, remove folders or documents from the index, optionally move the underlying files to the system Trash, and rescan a folder to pick up newly added files. The feature spans the SwiftUI client and the FastAPI backend: two new backend endpoints (`DELETE /libraries/{id}`, `DELETE /documents/{id}`) provide index removal, while the Swift client owns optional on-disk deletion via `FileManager.trashItem`. The existing schema already supports cascading deletes for clauses, chunks, figures, and embeddings, so backend deletion only needs to remove the top-level row and clean up figure image files on disk.

## Glossary

- **LibraryView**: The macOS SwiftUI screen that hosts the three-pane library workspace.
- **Library_Folder**: A row in the `libraries` table representing a filesystem folder the user has imported.
- **Document**: A row in the `documents` table representing a single indexed PDF or DOCX file belonging to exactly one Library_Folder.
- **FoldersPane**: The left pane of `LibraryView` listing every Library_Folder.
- **DocumentsPane**: The middle pane of `LibraryView` listing every Document whose `library_id` equals the selected Library_Folder's `id`.
- **DetailPane**: The right pane of `LibraryView` that renders `DocumentDetailView` for the selected Document.
- **LibraryBackend**: The FastAPI service reachable at `AppConfig.apiBaseURL` that exposes `/libraries`, `/documents`, `/ingest`, `/watch/start`, `/watch/stop`, and the new delete endpoints.
- **IndexCoordinator**: The Swift `ObservableObject` that orchestrates ingest and watcher operations against LibraryBackend.
- **Rescan**: A user-triggered action on a Library_Folder that re-invokes `POST /ingest` with the folder's stored `path` so that new files are indexed and previously indexed files are skipped by file hash.
- **DeleteConfirmationDialog**: A modal shown before any delete operation containing a description of the target, a "Also move files to Trash" checkbox that defaults to unchecked, a Cancel button, and a Delete button.
- **FiguresDirectory**: The directory at `AppConfig.figuresPath` where extracted figure images are stored on disk.
- **BackendConnected**: The state where `BackendClient.isConnected == true` following a successful `/health` response.
- **OfflineMode**: The state where `BackendClient.isConnected == false`.

## Requirements

### Requirement 1: Three-pane library layout

**User Story:** As a user, I want the Library screen to show folders, files, and details side by side, so that I can navigate from a folder to a specific document without leaving the page.

#### Acceptance Criteria

1. THE LibraryView SHALL render exactly three horizontally-arranged panes in a single `HSplitView`, in left-to-right order: FoldersPane, DocumentsPane, DetailPane.
2. WHEN LibraryView appears, THE LibraryView SHALL request the Library_Folder list from LibraryBackend via `GET /libraries` and display the returned rows in FoldersPane.
3. WHEN the user selects a Library_Folder in FoldersPane, THE LibraryView SHALL request `GET /documents?library_id={id}` from LibraryBackend and display the returned Documents in DocumentsPane.
4. WHEN the user selects a Document in DocumentsPane, THE LibraryView SHALL render the `DocumentDetailView` for that Document in DetailPane, populated with the Document's clauses and figures fetched from LibraryBackend.
5. WHILE no Library_Folder is selected, THE DocumentsPane SHALL display an empty-state message stating that no folder is selected.
6. WHILE a Library_Folder is selected and no Document is selected, THE DetailPane SHALL display an empty-state message stating that no document is selected.

### Requirement 2: Delete a folder from the index

**User Story:** As a user, I want to remove a folder from my library, so that its documents no longer appear in search results and I can optionally move the folder's files to the Trash.

#### Acceptance Criteria

1. WHEN the user invokes the delete action on a Library_Folder in FoldersPane, THE LibraryView SHALL present a DeleteConfirmationDialog naming the target Library_Folder and its filesystem path.
2. WHEN the user cancels the DeleteConfirmationDialog, THE LibraryView SHALL close the dialog and leave the Library_Folder and its Documents unchanged in the index and on disk.
3. WHEN the user confirms the DeleteConfirmationDialog for a Library_Folder, THE LibraryView SHALL call `DELETE /libraries/{id}` on LibraryBackend before performing any on-disk action.
4. WHEN LibraryBackend receives `DELETE /libraries/{id}`, THE LibraryBackend SHALL invoke `/watch/stop` semantics for the folder's stored path, delete every figure image file under FiguresDirectory that belongs to any Document whose `library_id` equals the deleted Library_Folder's `id`, and delete the `libraries` row so that dependent `documents`, `clauses`, `chunks`, `chunk_embeddings`, and `figures` rows are removed via existing cascading deletes.
5. WHERE the user checked "Also move files to Trash" in the DeleteConfirmationDialog, THE LibraryView SHALL, after receiving a successful response from `DELETE /libraries/{id}`, call `FileManager.trashItem` on the Library_Folder's stored filesystem path.
6. IF `DELETE /libraries/{id}` returns a non-2xx response, THEN THE LibraryView SHALL display the returned error message and SHALL NOT invoke `FileManager.trashItem`.
7. WHEN `DELETE /libraries/{id}` returns a successful response, THE LibraryView SHALL remove the deleted Library_Folder from FoldersPane and clear DocumentsPane and DetailPane if the deleted Library_Folder was selected.

### Requirement 3: Delete a document from the index

**User Story:** As a user, I want to remove a single document from my library, so that it no longer appears in search results and I can optionally move the file to the Trash.

#### Acceptance Criteria

1. WHEN the user invokes the delete action on a Document in DocumentsPane, THE LibraryView SHALL present a DeleteConfirmationDialog naming the target Document and its filesystem path.
2. WHEN the user cancels the DeleteConfirmationDialog, THE LibraryView SHALL close the dialog and leave the Document unchanged in the index and on disk.
3. WHEN the user confirms the DeleteConfirmationDialog for a Document, THE LibraryView SHALL call `DELETE /documents/{id}` on LibraryBackend before performing any on-disk action.
4. WHEN LibraryBackend receives `DELETE /documents/{id}`, THE LibraryBackend SHALL delete every figure image file under FiguresDirectory whose `document_id` equals the target Document's `id` and delete the `documents` row so that dependent `clauses`, `chunks`, `chunk_embeddings`, and `figures` rows are removed via existing cascading deletes.
5. WHERE the user checked "Also move files to Trash" in the DeleteConfirmationDialog, THE LibraryView SHALL, after receiving a successful response from `DELETE /documents/{id}`, call `FileManager.trashItem` on the Document's `file_path`.
6. IF `DELETE /documents/{id}` returns a non-2xx response, THEN THE LibraryView SHALL display the returned error message and SHALL NOT invoke `FileManager.trashItem`.
7. WHEN `DELETE /documents/{id}` returns a successful response, THE LibraryView SHALL remove the deleted Document from DocumentsPane and clear DetailPane if the deleted Document was selected.

### Requirement 4: Rescan a folder for new files

**User Story:** As a user who has added new files to a folder outside the app, I want to rescan the folder, so that the new files are indexed without re-indexing files that are already present.

#### Acceptance Criteria

1. THE FoldersPane SHALL expose a Rescan action on every Library_Folder row.
2. WHEN the user invokes Rescan on a Library_Folder, THE LibraryView SHALL call `POST /ingest` on LibraryBackend with the Library_Folder's stored `path`.
3. WHEN LibraryBackend processes a Rescan `POST /ingest` request, THE LibraryBackend SHALL skip every file whose SHA-256 file hash matches the `file_hash` column of an existing `documents` row for that Library_Folder.
4. WHEN a Rescan `POST /ingest` request completes successfully, THE LibraryView SHALL refresh DocumentsPane for the rescanned Library_Folder from `GET /documents?library_id={id}`.
5. IF `POST /ingest` returns a non-2xx response during Rescan, THEN THE LibraryView SHALL display the returned error message and SHALL leave DocumentsPane contents unchanged.
6. THE LibraryView SHALL NOT present a per-file picker as part of the Rescan action.

### Requirement 5: Confirmation dialog contents and defaults

**User Story:** As a user, I want every destructive action to require explicit confirmation with a clear opt-in for on-disk deletion, so that I do not accidentally lose files.

#### Acceptance Criteria

1. THE DeleteConfirmationDialog SHALL contain a Cancel button, a Delete button, a text description that names the target and its filesystem path, and a single checkbox labeled "Also move files to Trash".
2. WHEN the DeleteConfirmationDialog is presented, THE "Also move files to Trash" checkbox SHALL be unchecked by default.
3. WHILE the DeleteConfirmationDialog is presented, THE user SHALL be able to toggle the "Also move files to Trash" checkbox before confirming.
4. WHEN the user confirms a DeleteConfirmationDialog while the "Also move files to Trash" checkbox is unchecked, THE LibraryView SHALL remove the target from the index only and SHALL leave the target's files on disk unchanged.

### Requirement 6: Backend connectivity required for CRUD

**User Story:** As a user working offline, I want the app to make it clear when destructive or ingest operations are unavailable, so that I do not perform actions that cannot succeed.

#### Acceptance Criteria

1. WHILE the LibraryView is in OfflineMode, THE LibraryView SHALL disable the delete action on every Library_Folder, disable the delete action on every Document, and disable the Rescan action on every Library_Folder.
2. WHILE the LibraryView is in OfflineMode, THE LibraryView SHALL still display Library_Folder rows, Document rows, and Document details sourced from the local `DatabaseService` cache in read-only form.
3. WHEN the LibraryView transitions from OfflineMode to BackendConnected, THE LibraryView SHALL re-enable the delete and Rescan actions.
4. IF the user attempts a CRUD action while the LibraryView is in OfflineMode, THEN THE LibraryView SHALL display a message stating that the backend is not running.

### Requirement 7: Watcher lifecycle on folder deletion

**User Story:** As a user, I want the folder watcher to stop when I delete a folder, so that background processes do not continue observing a folder that is no longer indexed.

#### Acceptance Criteria

1. WHEN LibraryBackend processes `DELETE /libraries/{id}`, THE LibraryBackend SHALL stop any active filesystem watcher registered for the deleted Library_Folder's stored `path` before returning a successful response.
2. IF stopping the watcher raises an error inside LibraryBackend, THEN THE LibraryBackend SHALL still proceed with figure cleanup and row deletion, and SHALL include the watcher error in the response body while returning a 2xx status.

### Requirement 8: Figure image cleanup on document deletion

**User Story:** As a user, I want figure images to be removed from disk when I delete a document, so that stale image files do not accumulate under application support.

#### Acceptance Criteria

1. WHEN LibraryBackend deletes a Document via `DELETE /documents/{id}` or via cascading deletion from `DELETE /libraries/{id}`, THE LibraryBackend SHALL attempt to remove every file at the `image_path` column value of every `figures` row associated with that Document.
2. IF a figure image file referenced by `image_path` does not exist on disk when LibraryBackend attempts to remove it, THEN THE LibraryBackend SHALL treat that individual file as already cleaned up and SHALL continue processing the remaining figures.
3. IF removing a figure image file raises a filesystem error, THEN THE LibraryBackend SHALL include the failing `image_path` and error message in the response body while returning a 2xx status for the overall deletion.
